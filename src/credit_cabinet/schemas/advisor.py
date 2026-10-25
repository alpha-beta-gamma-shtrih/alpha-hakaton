from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from credit_cabinet.models.enums import ReportStatus
from credit_cabinet.schemas.business import PositiveInteger, StrictModel
from credit_cabinet.schemas.scenarios import CandidateResponse

AdvisorMode = Literal["EXPLAIN", "COMPARE"]
AdvisorPriority = Literal["BALANCED", "KEEP_AMOUNT", "LOWER_PAYMENT", "LOWER_OVERPAYMENT"]


class AdvisorRequest(StrictModel):
    expected_version: PositiveInteger
    mode: AdvisorMode = "EXPLAIN"
    priority: AdvisorPriority = "BALANCED"


class ModelNarrative(StrictModel):
    benefit: str = Field(min_length=15, max_length=350)
    tradeoff: str = Field(min_length=15, max_length=350)


class FactorCard(StrictModel):
    factor_id: str
    candidate_id: str | None = None
    text: str


class CandidateSelection(StrictModel):
    candidate_id: str = Field(min_length=1, max_length=64)
    factor_ids: list[str] = Field(min_length=1, max_length=3)


class ModelSelection(StrictModel):
    """Only grounded identifiers; the model cannot introduce new financial assertions."""

    summary_factor_ids: list[str] = Field(min_length=1, max_length=4)
    comparisons: list[CandidateSelection] = Field(max_length=3)
    next_step_id: str = Field(min_length=1, max_length=64)


class ExplanationSection(BaseModel):
    factor_ids: list[str]
    text: str


class CandidateExplanation(ExplanationSection):
    candidate_id: str


class AdvisorExplanation(BaseModel):
    summary: ExplanationSection
    comparisons: list[CandidateExplanation]
    next_step: dict[str, str]
    notice: str


class AdvisorResponse(BaseModel):
    id: UUID
    application_id: UUID
    revision_id: UUID | None
    draft_lock_version: int | None
    mode: AdvisorMode
    priority: AdvisorPriority = "BALANCED"
    preferred_candidate_ids: list[str] = Field(default_factory=list)
    status: ReportStatus
    is_current: bool
    input_hash: str
    factors: list[FactorCard]
    scenarios: list[CandidateResponse]
    explanation: AdvisorExplanation
    model_id: str | None
    model_digest: str | None
    prompt_version: str
    generation_config: dict
    latency_ms: int
    error_code: str | None
    created_at: datetime
