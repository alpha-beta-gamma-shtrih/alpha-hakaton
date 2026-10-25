from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from credit_cabinet.core.demo import FINANCIAL_MONTHS
from credit_cabinet.models.enums import ApplicationStatus, InfoStatus, Purpose, RiskBand, Visibility
from credit_cabinet.schemas.business import (
    AssessmentResponse,
    CheckResponse,
    DecisionResponse,
    DeclineResponse,
    EventResponse,
    MoneyInput,
    MoneyOutput,
    OfferTermsResponse,
    PositiveInteger,
    ReasonResponse,
    SignatureResponse,
    StrictModel,
)
from credit_cabinet.schemas.submissions import RevisionResponse

BankAction = Literal["REQUEST_INFO", "APPROVE", "REJECT", "RETRY_PROCESSING"]
BankStatus = Literal[
    "SUBMITTED", "CHECKING", "NEEDS_INFO", "MANUAL_REVIEW", "APPROVED", "REJECTED", "SIGNED"
]
ACTIVE_BANK_STATUSES = ("SUBMITTED", "CHECKING", "NEEDS_INFO", "MANUAL_REVIEW")
REQUESTABLE_FIELDS = frozenset(
    {
        "requested_amount",
        "term_months",
        "purpose_code",
        "purpose_details",
        "draft_data.financial_months",
        "draft_data.info_response",
        *{
            f"draft_data.financial_months.{month.isoformat()}.{field}"
            for month in FINANCIAL_MONTHS
            for field in ("cash_inflow", "operating_outflow", "existing_debt_payment")
        },
    }
)
PublicText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=20, max_length=1000)
]
InternalText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]


class BankCheckResponse(CheckResponse):
    normalized_data: dict | None
    error_code: str | None
    started_at: datetime


class BankAssessmentResponse(AssessmentResponse):
    checks: list[BankCheckResponse]
    input_facts: dict
    started_at: datetime


class BankDecisionResponse(DecisionResponse):
    decided_by_user_id: UUID | None
    internal_comment: str | None
    offer_risk_score: int | None = None
    offer_risk_band: RiskBand | None = None


class BankInformationRequest(BaseModel):
    model_config = {"from_attributes": True}
    id: UUID
    revision_id: UUID
    created_by_user_id: UUID | None
    requested_fields: list[str]
    message_to_client: str
    status: InfoStatus
    answer_text: str | None
    answered_revision_id: UUID | None
    answered_at: datetime | None
    created_at: datetime


class BankRevisionSummary(BaseModel):
    model_config = {"from_attributes": True}
    id: UUID
    revision_no: int
    input_hash: str
    created_at: datetime


class BankQueueItem(BaseModel):
    id: UUID
    company_id: UUID
    company_name: str
    inn: str
    product_id: UUID
    product_code: str
    product_version: int
    risk_score: int | None
    risk_band: RiskBand
    assessment_reasons: list[ReasonResponse]
    status: ApplicationStatus
    version: int
    latest_revision_id: UUID
    latest_revision_no: int
    requested_amount: MoneyOutput
    approved_amount: MoneyOutput | None = None
    approved_term_months: int | None = None
    terms_changed: bool = False
    term_months: int
    purpose_code: Purpose
    submitted_at: datetime
    allowed_actions: list[BankAction]


class BankQueuePage(BaseModel):
    items: list[BankQueueItem]
    total: int
    limit: int
    offset: int


class CurrentCreditCheck(BaseModel):
    calculation_details: dict
    can_approve_original: bool
    reasons: list[ReasonResponse]


class BankCard(BankQueueItem):
    credit_review_required: bool = False
    current_credit_check: CurrentCreditCheck | None = None
    signature: SignatureResponse | None = None
    decline: DeclineResponse | None = None
    revision: RevisionResponse
    assessment: BankAssessmentResponse | None
    decision: BankDecisionResponse | None
    open_information_request: BankInformationRequest | None
    information_requests: list[BankInformationRequest]
    revisions: list[BankRevisionSummary]


class BankRevisionDetail(BaseModel):
    revision: RevisionResponse
    assessments: list[BankAssessmentResponse]


class BankEventResponse(EventResponse):
    revision_id: UUID | None
    actor_user_id: UUID | None
    visibility: Visibility
    details: dict


class BankEventList(BaseModel):
    items: list[BankEventResponse]


class ManualInformationRequest(StrictModel):
    expected_version: PositiveInteger
    message_to_client: PublicText = Field(
        examples=["Уточните назначение расходов и ожидаемые поступления компании."]
    )
    requested_fields: list[str] = Field(
        min_length=1,
        max_length=24,
        json_schema_extra={
            "items": {"type": "string", "enum": sorted(REQUESTABLE_FIELDS)},
            "uniqueItems": True,
        },
    )

    @field_validator("requested_fields")
    @classmethod
    def allowed_fields(cls, value):
        if len(set(value)) != len(value) or not set(value) <= REQUESTABLE_FIELDS:
            raise ValueError("Use unique editable form paths from REQUESTABLE_FIELDS")
        return value


class OfferParameters(StrictModel):
    amount: MoneyInput
    term_months: PositiveInteger


class OfferPreviewRequest(OfferParameters):
    expected_version: PositiveInteger


class AdjustedOffer(OfferParameters):
    preview_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class OfferPreviewResponse(BaseModel):
    application_version: int
    terms: OfferTermsResponse
    risk_score: int | None
    risk_band: RiskBand
    routing: str
    reasons: list[ReasonResponse]
    can_approve: bool
    preview_hash: str


class ManualDecision(StrictModel):
    expected_version: PositiveInteger
    outcome: Literal["APPROVED", "REJECTED"]
    public_explanation: PublicText = Field(
        examples=["Показатели изучены, риск оценен в рамках демонстрационной политики."]
    )
    internal_comment: InternalText | None = None
    offer: AdjustedOffer | None = None

    @model_validator(mode="after")
    def offer_only_for_approval(self):
        if self.offer is not None and self.outcome != "APPROVED":
            raise ValueError("Changed terms require APPROVED")
        return self
