import logging
from copy import deepcopy
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from credit_cabinet.api.errors import APIError
from credit_cabinet.core.security import utc_now
from credit_cabinet.integrations.documents import DocumentStore
from credit_cabinet.models import (
    ApplicationEvent,
    ApplicationRevision,
    Assessment,
    CheckResult,
    Decision,
    InformationRequest,
)
from credit_cabinet.models.enums import (
    ApplicationStatus,
    CheckSource,
    CheckStatus,
    InfoStatus,
    Routing,
)
from credit_cabinet.schemas.submissions import SubmitRequest
from credit_cabinet.services.access import bank_application, client_application
from credit_cabinet.services.auth import AuthService, Principal
from credit_cabinet.services.documents import document_references, ensure_documents
from credit_cabinet.services.drafts import remember_draft
from credit_cabinet.services.policy import (
    evaluate,
)
from credit_cabinet.services.product_policy import evaluation_options
from credit_cabinet.services.reasons import MESSAGES
from credit_cabinet.services.snapshots import application_input, financial_input_hash

logger = logging.getLogger(__name__)
EDITABLE = {ApplicationStatus.DRAFT, ApplicationStatus.NEEDS_INFO}
RETRY_REASONS = {
    "SOURCE_FNS_UNAVAILABLE",
    "SOURCE_BKI_UNAVAILABLE",
    "SOURCE_RESPONSE_INVALID",
    "COMPANY_DATA_MISMATCH",
    "LEGAL_STATUS_UNCONFIRMED",
}


def event(
    db, application, kind, message, *, revision=None, actor=None, previous=None, details=None
):
    number = (
        db.scalar(
            select(func.max(ApplicationEvent.sequence_no)).where(
                ApplicationEvent.application_id == application.id
            )
        )
        or 0
    )
    db.add(
        ApplicationEvent(
            application_id=application.id,
            revision_id=revision.id if revision else None,
            sequence_no=number + 1,
            actor_user_id=actor,
            event_type=kind,
            from_status=previous,
            to_status=application.status,
            visibility="CLIENT",
            message=message,
            details=details or {},
        )
    )
    db.flush()


def latest_revision(db, application_id):
    return db.scalar(
        select(ApplicationRevision)
        .where(ApplicationRevision.application_id == application_id)
        .order_by(ApplicationRevision.revision_no.desc())
        .limit(1)
    )


def latest_assessment(db, revision_id):
    return db.scalar(
        select(Assessment)
        .where(Assessment.revision_id == revision_id)
        .order_by(Assessment.run_no.desc())
        .limit(1)
    )


def can_retry(application, assessment):
    if application.status == ApplicationStatus.SUBMITTED:
        return True
    return (
        application.status == ApplicationStatus.MANUAL_REVIEW
        and assessment is not None
        and bool(set(assessment.reason_codes) & RETRY_REASONS)
    )


def submit(
    db: Session,
    principal: Principal,
    application_id: UUID,
    body: SubmitRequest,
    auth: AuthService,
    sources,
):
    application = client_application(db, principal.user.id, application_id, lock=True)
    existing = db.scalar(
        select(ApplicationRevision).where(
            ApplicationRevision.application_id == application.id,
            ApplicationRevision.submission_key == body.submission_key,
        )
    )
    if existing is not None:
        if existing.source_lock_version != body.expected_version:
            raise APIError(
                409, "SUBMISSION_KEY_CONFLICT", "Ключ отправки уже связан с другим входом"
            )
        # Authenticate/access have already been checked. No source call or version bump on replay.
        return application, existing
    if application.lock_version != body.expected_version:
        raise APIError(409, "VERSION_CONFLICT", "Заявка уже изменена; получите актуальную версию")
    if application.status not in EDITABLE:
        raise APIError(
            409, "APPLICATION_NOT_SUBMITTABLE", "Заявку нельзя отправить в текущем статусе"
        )
    payload = application_input(db, application)
    store = DocumentStore(auth.settings)
    for document in ensure_documents(db, application, principal.user.id, store):
        store.read(document)
    payload["document_refs"] = document_references(db, application.id)
    number = (
        db.scalar(
            select(func.max(ApplicationRevision.revision_no)).where(
                ApplicationRevision.application_id == application.id
            )
        )
        or 0
    ) + 1
    revision = ApplicationRevision(
        application_id=application.id,
        revision_no=number,
        submitted_by_user_id=principal.user.id,
        source_lock_version=application.lock_version,
        submission_key=body.submission_key,
        input_hash=financial_input_hash(payload),
        requested_amount=application.requested_amount,
        term_months=application.term_months,
        purpose_code=application.purpose_code,
        company_snapshot=payload["company_snapshot"],
        financial_snapshot=payload["financial_snapshot"],
        product_snapshot=payload["product_snapshot"],
        document_refs=payload["document_refs"],
        schema_version=2,
    )
    db.add(revision)
    db.flush()
    pending = db.scalar(
        select(InformationRequest).where(
            InformationRequest.application_id == application.id,
            InformationRequest.status == InfoStatus.OPEN,
        )
    )
    if application.status == ApplicationStatus.NEEDS_INFO and pending is None:
        raise APIError(409, "INFORMATION_REQUEST_NOT_FOUND", "Активный дозапрос не найден")
    previous = application.status
    application.status = ApplicationStatus.SUBMITTED
    application.submitted_at = utc_now()
    if pending is not None:
        pending.status = InfoStatus.ANSWERED
        pending.answer_text = revision.financial_snapshot["info_response"]
        pending.answered_revision_id = revision.id
        pending.answered_at = application.submitted_at
        event(
            db,
            application,
            "INFO_ANSWERED",
            "Отправлен ответ на дозапрос",
            revision=revision,
            actor=principal.user.id,
            previous=previous,
        )
    event(
        db,
        application,
        "SUBMITTED",
        "Заявка отправлена на демонстрационную проверку",
        revision=revision,
        actor=principal.user.id,
        previous=previous,
    )
    remember_draft(principal, application)
    auth.activity(db, principal, commit=False)
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        raise APIError(409, "VERSION_CONFLICT", "Заявка уже изменена") from None
    logger.info(
        "application.submitted",
        extra={
            "application_id": str(application.id),
            "revision_id": str(revision.id),
            "version": application.lock_version,
        },
    )
    # The snapshot survives a processing crash. Retry always reads this revision, never the draft.
    application = client_application(db, principal.user.id, application_id, lock=True)
    if (
        application.status == ApplicationStatus.SUBMITTED
        and latest_revision(db, application_id).id == revision.id
    ):
        process(db, application, revision, sources)
        db.commit()
    return application, revision


def process(db, application, revision, sources):
    started = utc_now()
    prior = latest_assessment(db, revision.id)
    run_no = prior.run_no + 1 if prior else 1
    result = evaluate(
        company=revision.company_snapshot,
        financials=revision.financial_snapshot["financial_months"],
        amount=revision.requested_amount,
        term=revision.term_months,
        annual_rate=Decimal(revision.product_snapshot["annual_rate_percent"]),
        calculation_date=date_from_revision(revision),
        source=lambda kind: sources.check(
            revision.company_snapshot["inn"], kind, revision.revision_no, run_no
        ),
        **evaluation_options(
            {
                "product_snapshot": revision.product_snapshot,
                "financial_snapshot": revision.financial_snapshot,
                "purpose_code": revision.purpose_code.value,
            }
        ),
    )
    completed = utc_now()
    assessment = Assessment(
        revision_id=revision.id,
        run_no=run_no,
        rules_version=revision.product_snapshot["policy_version"],
        input_facts={
            "company": deepcopy(revision.company_snapshot),
            "financial_months": deepcopy(revision.financial_snapshot["financial_months"]),
            "confirmations": deepcopy(revision.financial_snapshot["confirmations"]),
            "calculation_date": date_from_revision(revision).isoformat(),
            **result.input_facts,
        },
        risk_score=result.risk_score,
        risk_band=result.risk_band,
        routing=result.routing,
        reason_codes=result.reason_codes,
        calculation_details=result.calculation_details,
        started_at=started,
        completed_at=completed,
    )
    db.add(assessment)
    db.flush()
    for check in result.checks:
        reasons = []
        if check.status != CheckStatus.SUCCESS:
            reasons = [
                "SOURCE_RESPONSE_INVALID"
                if check.error_code == "SOURCE_RESPONSE_INVALID"
                else "SOURCE_FNS_UNAVAILABLE"
                if check.source == CheckSource.FNS
                else "SOURCE_BKI_UNAVAILABLE"
                if check.source == CheckSource.BKI
                else "FINANCIAL_HISTORY_INCOMPLETE"
            ]
        elif check.source == CheckSource.DATA_QUALITY and result.routing == Routing.NEEDS_INFO:
            reasons = result.reason_codes
        db.add(
            CheckResult(
                assessment_id=assessment.id,
                source=check.source,
                status=check.status,
                normalized_data=check.normalized_data,
                reason_codes=reasons,
                error_code=check.error_code,
                source_version=check.source_version,
                started_at=check.started_at,
                completed_at=check.completed_at,
            )
        )
    previous = application.status
    application.status = {
        Routing.APPROVE: ApplicationStatus.APPROVED,
        Routing.REJECT: ApplicationStatus.REJECTED,
        Routing.NEEDS_INFO: ApplicationStatus.NEEDS_INFO,
        Routing.MANUAL_REVIEW: ApplicationStatus.MANUAL_REVIEW,
    }[result.routing]
    application.updated_at = completed
    if result.routing in (Routing.APPROVE, Routing.REJECT):
        approved = result.routing == Routing.APPROVE
        application.closed_at = completed
        db.add(
            Decision(
                application_id=application.id,
                revision_id=revision.id,
                assessment_id=assessment.id,
                source="AUTO",
                decided_by_user_id=None,
                outcome=application.status.value,
                approved_amount=revision.requested_amount if approved else None,
                approved_term_months=revision.term_months if approved else None,
                annual_rate_percent=Decimal(
                    result.calculation_details.get(
                        "annual_rate_percent", revision.product_snapshot["annual_rate_percent"]
                    )
                )
                if approved
                else None,
                monthly_payment=Decimal(result.calculation_details["monthly_payment"])
                if approved
                else None,
                reason_codes=result.reason_codes,
                public_explanation=MESSAGES[result.reason_codes[0]],
                internal_comment=None,
                policy_version=assessment.rules_version,
            )
        )
    elif result.routing == Routing.NEEDS_INFO:
        db.add(
            InformationRequest(
                application_id=application.id,
                revision_id=revision.id,
                created_by_user_id=None,
                requested_fields=result.requested_fields,
                message_to_client=MESSAGES[result.reason_codes[0]],
                status=InfoStatus.OPEN,
            )
        )
    event(
        db,
        application,
        "CHECKS_COMPLETED",
        MESSAGES[result.reason_codes[0]],
        revision=revision,
        previous=previous,
        details={"assessment_id": str(assessment.id), "run_no": run_no},
    )
    if result.routing in (Routing.APPROVE, Routing.REJECT):
        event(
            db,
            application,
            "DECISION_MADE",
            "Зафиксирован итог демонстрационной проверки",
            revision=revision,
            previous=application.status,
        )
    elif result.routing == Routing.NEEDS_INFO:
        event(
            db,
            application,
            "INFO_REQUESTED",
            MESSAGES[result.reason_codes[0]],
            revision=revision,
            previous=application.status,
        )
    logger.info(
        "application.checks_completed",
        extra={
            "application_id": str(application.id),
            "revision_id": str(revision.id),
            "run_no": run_no,
            "routing": result.routing.value,
            "version": application.lock_version,
        },
    )
    return assessment


def date_from_revision(revision):
    return date.fromisoformat(revision.product_snapshot["policy_config"]["calculation_date"])


def retry(db, principal, application_id, body, auth, sources):
    application, revision = bank_application(db, application_id, lock=True)
    if application.lock_version != body.expected_version:
        raise APIError(409, "VERSION_CONFLICT", "Заявка уже изменена")
    assessment = latest_assessment(db, revision.id) if revision else None
    if revision is None or not can_retry(application, assessment):
        raise APIError(409, "PROCESSING_RETRY_NOT_ALLOWED", "Повтор обработки недоступен")
    event(
        db,
        application,
        "PROCESSING_RETRIED",
        "Повтор демонстрационной обработки отправленного снимка",
        revision=revision,
        actor=principal.user.id,
        previous=application.status,
    )
    process(db, application, revision, sources)
    auth.activity(db, principal, commit=False)
    db.commit()
    return application, revision
