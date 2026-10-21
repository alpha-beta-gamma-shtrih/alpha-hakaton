"""Employee commands lock the application and commit result, actor and history together."""

import logging
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm.exc import StaleDataError

from credit_cabinet.api.errors import APIError
from credit_cabinet.core.security import utc_now
from credit_cabinet.models import Decision, InformationRequest
from credit_cabinet.models.enums import ApplicationStatus, InfoStatus, Role
from credit_cabinet.services.bank import bank_application
from credit_cabinet.services.bank_policy import bank_actions, saved_evaluation
from credit_cabinet.services.submissions import event, latest_assessment

logger = logging.getLogger(__name__)


def command_context(db, principal, application_id, expected_version, action):
    if principal.user.role != Role.BANK_STAFF:
        raise APIError(403, "ROLE_FORBIDDEN", "Требуется учетная запись сотрудника банка")
    application, revision = bank_application(db, application_id, lock=True)
    if application.lock_version != expected_version:
        raise APIError(409, "VERSION_CONFLICT", "Заявка уже изменена; получите актуальную карточку")
    assessment = latest_assessment(db, revision.id)
    if action not in bank_actions(db, application, revision, assessment):
        raise APIError(
            409,
            "BANK_ACTION_NOT_ALLOWED",
            "Действие недоступно по текущему состоянию и демо-проверкам",
        )
    if db.scalar(select(Decision.id).where(Decision.application_id == application.id)) is not None:
        raise APIError(409, "BANK_ACTION_NOT_ALLOWED", "Итоговое решение уже принято")
    if (
        db.scalar(
            select(InformationRequest.id).where(
                InformationRequest.application_id == application.id,
                InformationRequest.status == InfoStatus.OPEN,
            )
        )
        is not None
    ):
        raise APIError(
            409, "OPEN_INFORMATION_REQUEST_EXISTS", "В заявке уже есть открытый дозапрос"
        )
    return application, revision, assessment


def request_information(db, principal, application_id, body, auth):
    application, revision, _assessment = command_context(
        db, principal, application_id, body.expected_version, "REQUEST_INFO"
    )
    previous = application.status
    try:
        request = InformationRequest(
            id=uuid4(),
            application_id=application.id,
            revision_id=revision.id,
            created_by_user_id=principal.user.id,
            requested_fields=body.requested_fields,
            message_to_client=body.message_to_client,
            status=InfoStatus.OPEN,
        )
        db.add(request)
        application.status = ApplicationStatus.NEEDS_INFO
        application.updated_at = utc_now()
        event(
            db,
            application,
            "INFO_REQUESTED",
            body.message_to_client,
            revision=revision,
            actor=principal.user.id,
            previous=previous,
            details={"information_request_id": str(request.id), "source": "MANUAL"},
        )
        auth.activity(db, principal, commit=False)
        db.commit()
    except StaleDataError:
        db.rollback()
        raise APIError(
            409, "VERSION_CONFLICT", "Заявка уже изменена; получите актуальную карточку"
        ) from None
    logger.info(
        "bank.info_requested",
        extra={
            "application_id": str(application.id),
            "revision_id": str(revision.id),
            "user_id": str(principal.user.id),
            "role": principal.user.role.value,
            "version": application.lock_version,
        },
    )
    return application, revision


def decide(db, principal, application_id, body, auth):
    action = "APPROVE" if body.outcome == "APPROVED" else "REJECT"
    application, revision, assessment = command_context(
        db, principal, application_id, body.expected_version, action
    )
    result = saved_evaluation(db, revision, assessment)
    approved = body.outcome == "APPROVED"
    previous = application.status
    try:
        decision = Decision(
            id=uuid4(),
            application_id=application.id,
            revision_id=revision.id,
            assessment_id=assessment.id,
            source="MANUAL",
            decided_by_user_id=principal.user.id,
            outcome=body.outcome,
            approved_amount=revision.requested_amount if approved else None,
            approved_term_months=revision.term_months if approved else None,
            annual_rate_percent=Decimal(revision.product_snapshot["annual_rate_percent"])
            if approved
            else None,
            monthly_payment=Decimal(result.calculation_details["monthly_payment"])
            if approved
            else None,
            reason_codes=[
                "MANUAL_APPROVED" if approved else "MANUAL_REJECTED",
                *[row["factor_id"] for row in result.calculation_details["factors"]],
            ],
            public_explanation=body.public_explanation,
            internal_comment=body.internal_comment,
            policy_version=revision.product_snapshot["policy_version"],
        )
        db.add(decision)
        application.status = ApplicationStatus(body.outcome)
        application.closed_at = utc_now()
        application.updated_at = application.closed_at
        event(
            db,
            application,
            "DECISION_MADE",
            body.public_explanation,
            revision=revision,
            actor=principal.user.id,
            previous=previous,
            details={"decision_id": str(decision.id), "source": "MANUAL"},
        )
        auth.activity(db, principal, commit=False)
        db.commit()
    except StaleDataError:
        db.rollback()
        raise APIError(
            409, "VERSION_CONFLICT", "Заявка уже изменена; получите актуальную карточку"
        ) from None
    logger.info(
        "bank.decision_made",
        extra={
            "application_id": str(application.id),
            "revision_id": str(revision.id),
            "user_id": str(principal.user.id),
            "role": principal.user.role.value,
            "version": application.lock_version,
        },
    )
    return application, revision
