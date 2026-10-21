from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query

from credit_cabinet.api.dependencies import Database, require_bank_staff
from credit_cabinet.schemas.bank import (
    BankCard,
    BankEventList,
    BankQueuePage,
    BankRevisionDetail,
    BankStatus,
)
from credit_cabinet.schemas.errors import ErrorResponse
from credit_cabinet.services import bank as service
from credit_cabinet.services.auth import Principal

Bank = Annotated[Principal, Depends(require_bank_staff)]
router = APIRouter(
    prefix="/api/bank/applications",
    tags=["bank"],
    responses={status: {"model": ErrorResponse} for status in (401, 403, 404, 409, 422, 503)},
)


@router.get("", response_model=BankQueuePage)
def queue(
    db: Database,
    principal: Bank,
    status: Annotated[list[BankStatus] | None, Query()] = None,
    company_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=2147483647)] = 0,
):
    return service.queue(db, statuses=status, company_id=company_id, limit=limit, offset=offset)


@router.get("/{application_id}", response_model=BankCard)
def application(application_id: UUID, db: Database, principal: Bank):
    row, revision = service.bank_application(db, application_id)
    return service.card(db, row, revision)


@router.get("/{application_id}/revisions/{revision_no}", response_model=BankRevisionDetail)
def revision(
    application_id: UUID, revision_no: Annotated[int, Path(ge=1)], db: Database, principal: Bank
):
    return service.revision_detail(db, application_id, revision_no)


@router.get("/{application_id}/events", response_model=BankEventList)
def events(application_id: UUID, db: Database, principal: Bank):
    return service.history(db, application_id)
