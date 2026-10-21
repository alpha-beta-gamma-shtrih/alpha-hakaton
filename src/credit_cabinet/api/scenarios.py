from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from credit_cabinet.api.dependencies import Database, require_client
from credit_cabinet.schemas.errors import ErrorResponse
from credit_cabinet.schemas.scenarios import ScenariosRequest, ScenariosResponse
from credit_cabinet.services.auth import Principal
from credit_cabinet.services.scenarios import compare

Client = Annotated[Principal, Depends(require_client)]
router = APIRouter(
    prefix="/api/applications",
    tags=["scenarios"],
    responses={status: {"model": ErrorResponse} for status in (401, 403, 404, 409, 422, 503)},
)


@router.post("/{application_id}/scenarios", response_model=ScenariosResponse)
def scenarios(
    application_id: UUID, body: ScenariosRequest, request: Request, db: Database, principal: Client
):
    return compare(db, principal.user.id, application_id, body, request.app.state.sources)
