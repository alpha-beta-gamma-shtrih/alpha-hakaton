from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from credit_cabinet.api.dependencies import Database, require_bank_staff, require_client
from credit_cabinet.core.constants import SESSION_COOKIE
from credit_cabinet.schemas.advisor import AdvisorRequest, AdvisorResponse
from credit_cabinet.schemas.errors import ErrorResponse
from credit_cabinet.services import advisor as service
from credit_cabinet.services.auth import Principal

Client = Annotated[Principal, Depends(require_client)]
Bank = Annotated[Principal, Depends(require_bank_staff)]
router = APIRouter(
    prefix="/api",
    tags=["advisor"],
    responses={status: {"model": ErrorResponse} for status in (401, 403, 404, 409, 422, 503)},
)


@router.post("/applications/{application_id}/advisor", response_model=AdvisorResponse)
def generate(
    application_id: UUID, body: AdvisorRequest, request: Request, db: Database, principal: Client
):
    # A synchronous endpoint runs in the worker pool, outside the ASGI event loop.
    return service.generate(
        db,
        principal,
        application_id,
        body,
        request.app.state.auth,
        request.app.state.sources,
        request.app.state.advisor,
        request.cookies.get(SESSION_COOKIE),
    )


@router.get("/applications/{application_id}/advisor", response_model=AdvisorResponse)
def latest(application_id: UUID, request: Request, db: Database, principal: Client):
    return service.read(db, principal, application_id, request.app.state.settings)


@router.get(
    "/applications/{application_id}/advisor-reports/{report_id}", response_model=AdvisorResponse
)
def report(
    application_id: UUID, report_id: UUID, request: Request, db: Database, principal: Client
):
    return service.read(db, principal, application_id, request.app.state.settings, report_id)


@router.get("/bank/applications/{application_id}/advisor", response_model=AdvisorResponse)
def bank_latest(application_id: UUID, request: Request, db: Database, principal: Bank):
    return service.read(db, principal, application_id, request.app.state.settings, bank=True)


@router.get(
    "/bank/applications/{application_id}/advisor-reports/{report_id}",
    response_model=AdvisorResponse,
)
def bank_report(
    application_id: UUID, report_id: UUID, request: Request, db: Database, principal: Bank
):
    return service.read(
        db, principal, application_id, request.app.state.settings, report_id, bank=True
    )
