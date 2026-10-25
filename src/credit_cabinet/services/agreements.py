"""View final approved terms and atomically record a simulated signature, never a loan payout."""

import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm.exc import StaleDataError

from credit_cabinet.api.errors import APIError
from credit_cabinet.core.security import utc_now
from credit_cabinet.models import ApplicationRevision, CreditProduct, Decision
from credit_cabinet.models.enums import ApplicationStatus
from credit_cabinet.schemas.agreements import AgreementContent, AgreementResponse
from credit_cabinet.services.access import client_application
from credit_cabinet.services.drafts import draft_view
from credit_cabinet.services.policy import canonical_hash
from credit_cabinet.services.submissions import event

logger = logging.getLogger(__name__)
NOTICE = "Демонстрационный документ хакатона. Кнопка «Подписать» имитирует электронную подпись; юридически значимая электронная подпись не создаётся, договор с реальным банком не заключается, средства не выдаются."


def agreement_view(db, application):
    if application.status == "SIGNED":
        record = application.signing_record
        return AgreementResponse(
            content=record["content"], content_sha256=record["content_sha256"], signature=record
        )
    if application.status != "APPROVED":
        raise APIError(409, "AGREEMENT_NOT_AVAILABLE", "Документ доступен после одобрения заявки")
    decision = db.scalar(select(Decision).where(Decision.application_id == application.id))
    if decision is None or decision.outcome != "APPROVED":
        raise APIError(409, "AGREEMENT_NOT_AVAILABLE", "Одобренные условия не найдены")
    revision = db.get(ApplicationRevision, decision.revision_id)
    total = decision.monthly_payment * decision.approved_term_months
    content = AgreementContent(
        title="Демонстрационные условия кредитного договора",
        notice=NOTICE,
        issued_at=decision.created_at,
        application_id=application.id,
        decision_id=decision.id,
        revision_id=revision.id,
        company_name=revision.company_snapshot["legal_name"],
        inn=revision.company_snapshot["inn"],
        purpose_code=revision.purpose_code,
        approved_amount=decision.approved_amount,
        term_months=decision.approved_term_months,
        annual_rate_percent=decision.annual_rate_percent,
        monthly_payment=decision.monthly_payment,
        estimated_total_payment=total,
        estimated_overpayment=total - Decimal(decision.approved_amount),
    )
    return AgreementResponse(
        content=content,
        content_sha256=canonical_hash(content.model_dump(mode="json")),
        signature=None,
    )


def read(db, principal, application_id):
    return agreement_view(db, client_application(db, principal.user.id, application_id))


def decline(db, principal, application_id, body, auth):
    application = client_application(db, principal.user.id, application_id, lock=True)
    if application.decline_record:
        if application.decline_record["decision_id"] != str(body.decision_id):
            raise APIError(409, "AGREEMENT_CHANGED", "Предложение банка изменилось")
        # An identical retry after a lost response returns the original refusal.
        auth.activity(db, principal, commit=False)
        db.commit()
        return draft_view(application, db.get(CreditProduct, application.product_id), db)
    document = agreement_view(db, application)
    if application.status != ApplicationStatus.APPROVED:
        raise APIError(409, "AGREEMENT_NOT_AVAILABLE", "Отказ доступен до подписания документа")
    if document.content.decision_id != body.decision_id:
        raise APIError(409, "AGREEMENT_CHANGED", "Получите актуальное предложение банка")
    if application.lock_version != body.expected_version:
        raise APIError(409, "VERSION_CONFLICT", "Заявка изменена; получите актуальную версию")
    now = utc_now()
    application.decline_record = {
        "decision_id": str(body.decision_id),
        "declined_at": now.isoformat(),
        "declined_by_user_id": str(principal.user.id),
        "declined_by_display_name": principal.user.display_name,
    }
    application.status = ApplicationStatus.REJECTED
    application.closed_at = now
    application.updated_at = now
    try:
        event(
            db,
            application,
            "AGREEMENT_DECLINED",
            "Клиент отказался от предложенных условий. Заявка закрыта без подписания.",
            revision=db.get(ApplicationRevision, document.content.revision_id),
            actor=principal.user.id,
            previous="APPROVED",
            details={"decision_id": str(body.decision_id)},
        )
        auth.activity(db, principal, commit=False)
        db.commit()
    except StaleDataError:
        db.rollback()
        raise APIError(
            409, "VERSION_CONFLICT", "Заявка изменена; получите актуальную версию"
        ) from None
    logger.info(
        "application.agreement_declined",
        extra={"application_id": str(application.id), "user_id": str(principal.user.id)},
    )
    return draft_view(application, db.get(CreditProduct, application.product_id), db)


def sign(db, principal, application_id, body, auth):
    application = client_application(db, principal.user.id, application_id, lock=True)
    document = agreement_view(db, application)
    if not body.accepted:
        raise APIError(
            422, "SIGNING_CONFIRMATION_REQUIRED", "Нужно подтвердить подписание демо-документа"
        )
    if (
        document.content.decision_id != body.decision_id
        or document.content_sha256 != body.content_sha256
    ):
        raise APIError(409, "AGREEMENT_CHANGED", "Получите актуальный документ перед подписанием")
    if application.status == "SIGNED":
        # An identical retry after a lost response returns the original signature, even with the old version.
        auth.activity(db, principal, commit=False)
        db.commit()
        return draft_view(application, db.get(CreditProduct, application.product_id), db)
    if application.lock_version != body.expected_version:
        raise APIError(409, "VERSION_CONFLICT", "Заявка изменена; получите актуальную версию")
    now = utc_now()
    application.signing_record = {
        "decision_id": str(body.decision_id),
        "content_sha256": document.content_sha256,
        "content": document.content.model_dump(mode="json"),
        "method": "DEMO",
        "signed_at": now.isoformat(),
        "signed_by_user_id": str(principal.user.id),
        "signed_by_display_name": principal.user.display_name,
    }
    application.status = ApplicationStatus.SIGNED
    application.updated_at = now
    principal.user.ui_context = {"section": "applications"}
    try:
        event(
            db,
            application,
            "AGREEMENT_SIGNED",
            "Демо-документ подписан: электронная подпись имитирована, выдача средств не выполнялась.",
            revision=db.get(ApplicationRevision, document.content.revision_id),
            actor=principal.user.id,
            previous="APPROVED",
            details={
                "decision_id": str(body.decision_id),
                "content_sha256": document.content_sha256,
                "method": "DEMO",
            },
        )
        auth.activity(db, principal, commit=False)
        db.commit()
    except StaleDataError:
        db.rollback()
        raise APIError(
            409, "VERSION_CONFLICT", "Заявка изменена; получите актуальную версию"
        ) from None
    logger.info(
        "application.agreement_signed",
        extra={
            "application_id": str(application.id),
            "user_id": str(principal.user.id),
            "version": application.lock_version,
        },
    )
    return draft_view(application, db.get(CreditProduct, application.product_id), db)
