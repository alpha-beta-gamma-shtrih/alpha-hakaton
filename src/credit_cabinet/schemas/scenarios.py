from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from credit_cabinet.models.enums import Routing
from credit_cabinet.schemas.business import (
    DraftResponse,
    MoneyOutput,
    PositiveInteger,
    ProvenanceResponse,
    RateOutput,
    ReasonResponse,
    StrictModel,
)


class ScenariosRequest(StrictModel):
    expected_version: PositiveInteger


class CandidateResponse(BaseModel):
    pricing: dict = Field(default_factory=dict)
    candidate_id: Literal["REQUESTED", "LOWER_AMOUNT", "LONGER_TERM"]
    requested_amount: MoneyOutput
    term_months: int
    annual_rate_percent: RateOutput
    monthly_payment: MoneyOutput
    estimated_total_payment: MoneyOutput
    estimated_overpayment: MoneyOutput
    load_ratio: str | None
    risk_score: int | None
    preliminary_route: Routing | None
    reason_codes: list[str]
    reasons: list[ReasonResponse]
    provenance: ProvenanceResponse
    policy_version: str
    input_hash: str
    is_binding: Literal[False] = False


class ScenariosResponse(BaseModel):
    mode: Literal["CALCULATION_ONLY", "PREVIEW"]
    application_version: int
    candidates: list[CandidateResponse]


class ScenarioSetRequest(ScenariosRequest):
    refresh: bool = Field(default=False, strict=True)


class ScenarioSelectRequest(ScenariosRequest):
    scenario_set_id: UUID
    candidate_id: Literal["REQUESTED", "LOWER_AMOUNT", "LONGER_TERM"]


class ScenarioSetResponse(ScenariosResponse):
    id: UUID
    created_at: datetime
    is_current: bool
    stale_reason: str | None
    selected_candidate_id: Literal["REQUESTED", "LOWER_AMOUNT", "LONGER_TERM"] | None


class ScenarioSetUpdate(BaseModel):
    application: DraftResponse
    scenario_set: ScenarioSetResponse
