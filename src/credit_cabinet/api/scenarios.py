from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from credit_cabinet.api.dependencies import Database, require_client
from credit_cabinet.schemas.errors import ErrorResponse
from credit_cabinet.schemas.scenarios import (
    ScenarioSelectRequest,
    ScenarioSetRequest,
    ScenarioSetResponse,
    ScenarioSetUpdate,
    ScenariosRequest,
    ScenariosResponse,
)
from credit_cabinet.services import scenario_sets
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


@router.get("/{application_id}/scenario-set", response_model=ScenarioSetResponse | None)
def scenario_set(application_id: UUID, request: Request, db: Database, principal: Client):
    return scenario_sets.read(db, principal.user.id, application_id, request.app.state.settings)


@router.post("/{application_id}/scenario-set", response_model=ScenarioSetUpdate)
def create_scenario_set(
    application_id: UUID,
    body: ScenarioSetRequest,
    request: Request,
    db: Database,
    principal: Client,
):
    return scenario_sets.create(
        db, principal, application_id, body, request.app.state.auth, request.app.state.sources
    )


@router.post("/{application_id}/scenario-set/select", response_model=ScenarioSetUpdate)
def select_scenario(
    application_id: UUID,
    body: ScenarioSelectRequest,
    request: Request,
    db: Database,
    principal: Client,
):
    return scenario_sets.select(db, principal, application_id, body, request.app.state.auth)
