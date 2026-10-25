from uuid import UUID

from fastapi import APIRouter, Request

from credit_cabinet.api.business import Client
from credit_cabinet.api.dependencies import Database
from credit_cabinet.schemas.agreements import (
    AgreementResponse,
    DeclineAgreementRequest,
    SignAgreementRequest,
)
from credit_cabinet.schemas.business import DraftResponse
from credit_cabinet.schemas.errors import ErrorResponse
from credit_cabinet.services import agreements

router = APIRouter(
    prefix="/api/applications",
    tags=["agreements"],
    responses={status: {"model": ErrorResponse} for status in (401, 403, 404, 409, 422)},
)


@router.get("/{application_id}/agreement", response_model=AgreementResponse)
def read_agreement(application_id: UUID, db: Database, principal: Client):
    return agreements.read(db, principal, application_id)


@router.post("/{application_id}/agreement/sign", response_model=DraftResponse)
def sign_agreement(
    application_id: UUID,
    body: SignAgreementRequest,
    request: Request,
    db: Database,
    principal: Client,
):
    return agreements.sign(db, principal, application_id, body, request.app.state.auth)


@router.post("/{application_id}/agreement/decline", response_model=DraftResponse)
def decline_agreement(
    application_id: UUID,
    body: DeclineAgreementRequest,
    request: Request,
    db: Database,
    principal: Client,
):
    return agreements.decline(db, principal, application_id, body, request.app.state.auth)
