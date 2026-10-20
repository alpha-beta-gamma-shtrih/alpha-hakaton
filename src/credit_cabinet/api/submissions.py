from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request
from sqlalchemy import select

from credit_cabinet.api.dependencies import Database, require_bank_staff, require_client
from credit_cabinet.api.errors import APIError
from credit_cabinet.models import ApplicationRevision, CreditProduct, Decision
from credit_cabinet.schemas.business import DecisionResponse
from credit_cabinet.schemas.errors import ErrorResponse
from credit_cabinet.schemas.submissions import (
    RetryRequest,
    RetryResponse,
    RevisionResponse,
    SubmissionResponse,
    SubmitRequest,
)
from credit_cabinet.services.access import client_application
from credit_cabinet.services.auth import Principal
from credit_cabinet.services.drafts import draft_view
from credit_cabinet.services.submissions import can_retry, latest_assessment, retry, submit
from credit_cabinet.services.views import assessment_view, decision_view, revision_view

Client = Annotated[Principal, Depends(require_client)]
Bank = Annotated[Principal, Depends(require_bank_staff)]
router = APIRouter(
    prefix="/api",
    responses={status: {"model": ErrorResponse} for status in (401, 403, 404, 409, 422, 503)},
)


@router.post(
    "/applications/{application_id}/submit", response_model=SubmissionResponse, tags=["submissions"]
)
def submit_application(
    application_id: UUID, body: SubmitRequest, request: Request, db: Database, principal: Client
):
    application, revision = submit(
        db, principal, application_id, body, request.app.state.auth, request.app.state.sources
    )
    assessment = latest_assessment(db, revision.id)
    return SubmissionResponse(
        application=draft_view(application, db.get(CreditProduct, application.product_id), db),
        revision=revision_view(revision),
        assessment=assessment_view(db, assessment, revision)
        if assessment
        and application.draft_data.get("confirmations", {}).get("credit_history_check_allowed")
        is True
        else None,
    )


@router.get(
    "/applications/{application_id}/revisions/{revision_no}",
    response_model=RevisionResponse,
    tags=["submissions"],
)
def revision(
    application_id: UUID, revision_no: Annotated[int, Path(ge=1)], db: Database, principal: Client
):
    client_application(db, principal.user.id, application_id)
    row = db.scalar(
        select(ApplicationRevision).where(
            ApplicationRevision.application_id == application_id,
            ApplicationRevision.revision_no == revision_no,
        )
    )
    if row is None:
        raise APIError(404, "REVISION_NOT_FOUND", "Отправленная версия не найдена")
    return revision_view(row)


@router.get(
    "/applications/{application_id}/decision", response_model=DecisionResponse, tags=["submissions"]
)
def decision(application_id: UUID, db: Database, principal: Client):
    client_application(db, principal.user.id, application_id)
    row = db.scalar(select(Decision).where(Decision.application_id == application_id))
    if row is None:
        raise APIError(404, "DECISION_NOT_FOUND", "Итоговое решение еще не принято")
    return decision_view(row)


@router.post(
    "/bank/applications/{application_id}/retry-processing",
    response_model=RetryResponse,
    tags=["bank-processing"],
)
def retry_processing(
    application_id: UUID, body: RetryRequest, request: Request, db: Database, principal: Bank
):
    application, revision = retry(
        db, principal, application_id, body, request.app.state.auth, request.app.state.sources
    )
    assessment = latest_assessment(db, revision.id)
    return RetryResponse(
        application_id=application.id,
        version=application.lock_version,
        status=application.status.value,
        revision_id=revision.id,
        assessment=assessment_view(db, assessment, revision) if assessment else None,
        allowed_actions=["RETRY_PROCESSING"] if can_retry(application, assessment) else [],
    )
