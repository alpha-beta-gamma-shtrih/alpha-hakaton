"""Employee read models contain submitted values only, never the current client draft."""

from copy import deepcopy

from sqlalchemy import func, select

from credit_cabinet.api.errors import APIError
from credit_cabinet.models import (
    Application,
    ApplicationEvent,
    ApplicationRevision,
    Assessment,
    CheckResult,
    Decision,
    InformationRequest,
)
from credit_cabinet.models.enums import InfoStatus
from credit_cabinet.schemas.bank import (
    ACTIVE_BANK_STATUSES,
    BankAssessmentResponse,
    BankCard,
    BankDecisionResponse,
    BankQueueItem,
    BankRevisionDetail,
)
from credit_cabinet.schemas.business import SignatureResponse
from credit_cabinet.services.access import bank_application, submitted_query
from credit_cabinet.services.bank_policy import bank_actions
from credit_cabinet.services.reasons import public_reasons
from credit_cabinet.services.submissions import latest_assessment
from credit_cabinet.services.views import assessment_view, decision_view, revision_view


def queue_item(db, application, revision, assessment):
    decision = db.scalar(select(Decision).where(Decision.application_id == application.id))
    return BankQueueItem(
        approved_amount=decision.approved_amount if decision else None,
        approved_term_months=decision.approved_term_months if decision else None,
        terms_changed=bool(decision and decision.offer_snapshot),
        id=application.id,
        company_id=application.company_id,
        company_name=revision.company_snapshot["legal_name"],
        inn=revision.company_snapshot["inn"],
        product_id=application.product_id,
        product_code=revision.product_snapshot["code"],
        product_version=revision.product_snapshot["version"],
        risk_score=assessment.risk_score if assessment else None,
        risk_band=assessment.risk_band if assessment else "UNKNOWN",
        assessment_reasons=public_reasons(assessment.reason_codes) if assessment else [],
        status=application.status,
        version=application.lock_version,
        latest_revision_id=revision.id,
        latest_revision_no=revision.revision_no,
        requested_amount=revision.requested_amount,
        term_months=revision.term_months,
        purpose_code=revision.purpose_code,
        submitted_at=revision.created_at,
        allowed_actions=bank_actions(db, application, revision, assessment),
    )


def queue(db, *, statuses, company_id, limit, offset):
    query = submitted_query().where(Application.status.in_(statuses or ACTIVE_BANK_STATUSES))
    if company_id is not None:
        query = query.where(Application.company_id == company_id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(
        query.order_by(ApplicationRevision.created_at, Application.id).limit(limit).offset(offset)
    )
    return {
        "items": [
            queue_item(db, application, revision, latest_assessment(db, revision.id))
            for application, revision in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def bank_assessment_view(db, assessment, revision):
    public = assessment_view(db, assessment, revision)
    checks = list(
        db.scalars(
            select(CheckResult)
            .where(CheckResult.assessment_id == assessment.id)
            .order_by(CheckResult.source)
        )
    )
    public_checks = {row.source: row for row in public.checks}
    return BankAssessmentResponse(
        **{key: value for key, value in public.model_dump().items() if key != "checks"},
        checks=[
            {
                **public_checks[row.source].model_dump(),
                "normalized_data": deepcopy(row.normalized_data),
                "error_code": row.error_code,
                "started_at": row.started_at,
            }
            for row in checks
        ],
        input_facts=deepcopy(assessment.input_facts),
        started_at=assessment.started_at,
    )


def card(db, application, revision):
    assessment = latest_assessment(db, revision.id)
    decision = db.scalar(select(Decision).where(Decision.application_id == application.id))
    requests = list(
        db.scalars(
            select(InformationRequest)
            .where(InformationRequest.application_id == application.id)
            .order_by(InformationRequest.created_at, InformationRequest.id)
        )
    )
    revisions = list(
        db.scalars(
            select(ApplicationRevision)
            .where(ApplicationRevision.application_id == application.id)
            .order_by(ApplicationRevision.revision_no)
        )
    )
    return BankCard(
        signature=SignatureResponse.model_validate(application.signing_record)
        if application.signing_record
        else None,
        **queue_item(db, application, revision, assessment).model_dump(),
        revision=revision_view(revision),
        assessment=bank_assessment_view(db, assessment, revision) if assessment else None,
        decision=BankDecisionResponse(
            **decision_view(decision).model_dump(),
            decided_by_user_id=decision.decided_by_user_id,
            internal_comment=decision.internal_comment,
            offer_risk_score=decision.offer_snapshot["risk_score"]
            if decision.offer_snapshot
            else None,
            offer_risk_band=decision.offer_snapshot["risk_band"]
            if decision.offer_snapshot
            else None,
        )
        if decision
        else None,
        open_information_request=next(
            (row for row in requests if row.status == InfoStatus.OPEN), None
        ),
        information_requests=requests,
        revisions=revisions,
    )


def revision_detail(db, application_id, revision_no):
    bank_application(db, application_id)
    revision = db.scalar(
        select(ApplicationRevision).where(
            ApplicationRevision.application_id == application_id,
            ApplicationRevision.revision_no == revision_no,
        )
    )
    if revision is None:
        raise APIError(404, "REVISION_NOT_FOUND", "Отправленная версия не найдена")
    assessments = db.scalars(
        select(Assessment).where(Assessment.revision_id == revision.id).order_by(Assessment.run_no)
    )
    return BankRevisionDetail(
        revision=revision_view(revision),
        assessments=[bank_assessment_view(db, row, revision) for row in assessments],
    )


def history(db, application_id):
    bank_application(db, application_id)
    return {
        "items": list(
            db.scalars(
                select(ApplicationEvent)
                .where(ApplicationEvent.application_id == application_id)
                .order_by(ApplicationEvent.sequence_no)
            )
        )
    }
