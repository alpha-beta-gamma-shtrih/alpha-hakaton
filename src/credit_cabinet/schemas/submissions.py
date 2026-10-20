from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from credit_cabinet.schemas.business import (
    AssessmentResponse,
    DraftResponse,
    MoneyOutput,
    PositiveInteger,
    Purpose,
    StrictModel,
)


class SubmitRequest(StrictModel):
    expected_version: PositiveInteger
    submission_key: UUID


class RetryRequest(StrictModel):
    expected_version: PositiveInteger


class RevisionResponse(BaseModel):
    id: UUID
    application_id: UUID
    revision_no: int
    source_lock_version: int
    submission_key: UUID
    input_hash: str
    requested_amount: MoneyOutput
    term_months: int
    purpose_code: Purpose
    company_snapshot: dict
    financial_snapshot: dict
    product_snapshot: dict
    document_refs: list
    schema_version: int
    submitted_by_user_id: UUID
    created_at: datetime


class SubmissionResponse(BaseModel):
    application: DraftResponse
    revision: RevisionResponse
    assessment: AssessmentResponse | None


class RetryResponse(BaseModel):
    application_id: UUID
    version: int
    status: str
    revision_id: UUID
    assessment: AssessmentResponse | None
    allowed_actions: list[Literal["RETRY_PROCESSING"]]
