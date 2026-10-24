import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    WithJsonSchema,
    field_validator,
    model_validator,
)

from credit_cabinet.core.demo import FINANCIAL_MONTHS
from credit_cabinet.models.enums import (
    ApplicationStatus,
    CheckSource,
    CheckStatus,
    DecisionOutcome,
    DecisionSource,
    FormStep,
    LegalForm,
    Purpose,
    RiskBand,
    Routing,
)
from credit_cabinet.schemas.documents import DocumentResponse

MAX_MONEY = Decimal("9999999999999999.99")


def parse_money(value):
    if not isinstance(value, str) or not re.fullmatch(r"(0|[1-9][0-9]{0,15})\.[0-9]{2}", value):
        raise ValueError("Use a decimal string with two decimal places")
    result = Decimal(value)
    if result > MAX_MONEY:
        raise ValueError("Amount is too large")
    return result


MoneyInput = Annotated[
    Decimal,
    BeforeValidator(parse_money),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": r"^(0|[1-9][0-9]{0,15})\.[0-9]{2}$",
            "examples": ["1000000.00"],
        }
    ),
]
MoneyOutput = Annotated[
    Decimal, PlainSerializer(lambda value: format(value, ".2f"), return_type=str)
]
RateOutput = Annotated[
    Decimal, PlainSerializer(lambda value: format(value, ".3f"), return_type=str)
]
PositiveInteger = Annotated[int, Field(strict=True, gt=0, le=2147483647)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FinancialMonthInput(StrictModel):
    month: date
    cash_inflow: MoneyInput | None = None
    operating_outflow: MoneyInput | None = None
    existing_debt_payment: MoneyInput | None = None

    @field_validator("month", mode="before")
    @classmethod
    def check_month(cls, value):
        if not isinstance(value, str) or value not in {
            month.isoformat() for month in FINANCIAL_MONTHS
        }:
            raise ValueError("Month must belong to the demo financial window")
        return value


class FinancialMonthResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    month: date
    cash_inflow: MoneyOutput | None
    operating_outflow: MoneyOutput | None
    existing_debt_payment: MoneyOutput | None


class ConfirmationPatch(StrictModel):
    data_confirmed: bool = Field(default=False, strict=True)
    credit_history_check_allowed: bool = Field(default=False, strict=True)


class DraftDelete(StrictModel):
    expected_version: PositiveInteger


class DraftDataPatch(StrictModel):
    purchase_from_bank_partner: bool = Field(default=False, strict=True)
    financial_months: list[FinancialMonthInput] = Field(default_factory=list, max_length=6)
    confirmations: ConfirmationPatch = Field(default_factory=ConfirmationPatch)
    info_response: str | None = Field(default=None, max_length=1000)

    @field_validator("financial_months")
    @classmethod
    def unique_months(cls, value):
        if len({row.month for row in value}) != len(value):
            raise ValueError("Duplicate financial month")
        return value


class DraftCreate(StrictModel):
    company_id: UUID
    product_id: UUID


class DraftPatch(StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "expected_version": 1,
                    "requested_amount": "1000000.00",
                    "term_months": 12,
                    "purpose_code": "INVENTORY",
                    "ui_step": "FINANCES",
                }
            ]
        },
    )
    expected_version: PositiveInteger
    requested_amount: MoneyInput | None = None
    term_months: PositiveInteger | None = None
    purpose_code: Purpose | None = None
    purpose_details: str | None = Field(default=None, max_length=1000)
    draft_data: DraftDataPatch = Field(default_factory=DraftDataPatch)
    ui_step: FormStep = FormStep.NEED

    @field_validator("requested_amount")
    @classmethod
    def positive_amount(cls, value):
        if value is not None and value <= 0:
            raise ValueError("Requested amount must be positive")
        return value

    @model_validator(mode="after")
    def contains_change(self):
        if self.model_fields_set == {"expected_version"}:
            raise ValueError("Specify at least one field to save")
        return self


class ProvenanceItem(BaseModel):
    source: Literal["DEMO_PROFILE", "CLIENT_DECLARED", "MOCK_FNS", "MOCK_BKI"]
    as_of_date: date
    checked_at: datetime | None = None


class ProvenanceResponse(BaseModel):
    company: ProvenanceItem | None
    financial_months: ProvenanceItem | None
    credit_history: ProvenanceItem | None = None


class CompanyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    legal_name: str
    legal_form: LegalForm
    inn: str
    registration_number: str | None
    registered_on: date
    okved_code: str
    region_code: str
    business_description: str | None


class CompanyDetail(CompanyResponse):
    financial_months: list[FinancialMonthResponse]
    provenance: ProvenanceResponse


class CompanyPage(BaseModel):
    items: list[CompanyResponse]
    total: int
    limit: int
    offset: int


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    code: str
    version: int
    name: str
    description: str
    min_amount: MoneyOutput
    max_amount: MoneyOutput
    min_term_months: int
    max_term_months: int
    annual_rate_percent: RateOutput
    currency: Literal["RUB"] = "RUB"
    allowed_purposes: list[Purpose]
    policy_version: str


class ProductPage(BaseModel):
    items: list[ProductResponse]
    total: int
    limit: int
    offset: int


class ConfirmationsResponse(BaseModel):
    data_confirmed: bool
    credit_history_check_allowed: bool


class DraftDataResponse(BaseModel):
    financial_months: list[FinancialMonthResponse]
    confirmations: ConfirmationsResponse
    info_response: str | None = None


class ReasonResponse(BaseModel):
    code: str
    message: str


class DecisionResponse(BaseModel):
    id: UUID
    revision_id: UUID
    assessment_id: UUID
    outcome: DecisionOutcome
    source: DecisionSource
    approved_amount: MoneyOutput | None
    approved_term_months: int | None
    annual_rate_percent: RateOutput | None
    monthly_payment: MoneyOutput | None
    reasons: list[ReasonResponse]
    public_explanation: str
    policy_version: str
    created_at: datetime


class InformationRequestResponse(BaseModel):
    id: UUID
    message_to_client: str
    requested_fields: list[str]


class CheckResponse(BaseModel):
    source: CheckSource
    status: CheckStatus
    reasons: list[ReasonResponse]
    source_version: str
    completed_at: datetime


class AssessmentResponse(BaseModel):
    id: UUID
    revision_id: UUID
    run_no: int
    rules_version: str
    risk_score: int | None
    risk_band: RiskBand
    routing: Routing
    reasons: list[ReasonResponse]
    calculation_details: dict
    checks: list[CheckResponse]
    provenance: ProvenanceResponse
    completed_at: datetime


class DraftResponse(BaseModel):
    documents: list[DocumentResponse]
    id: UUID
    company_id: UUID
    product_id: UUID
    status: ApplicationStatus
    version: int
    requested_amount: MoneyOutput | None
    term_months: int | None
    purpose_code: Purpose | None
    purpose_details: str | None
    draft_data: DraftDataResponse
    ui_step: FormStep
    calculation_date: date
    policy_version: str
    provenance: ProvenanceResponse
    allowed_actions: list[Literal["EDIT_DRAFT", "SUBMIT"]]
    open_information_request: InformationRequestResponse | None = None
    decision: DecisionResponse | None = None
    latest_revision_id: UUID | None = None
    latest_revision_no: int | None = None
    assessment: AssessmentResponse | None = None
    created_at: datetime
    updated_at: datetime


class DraftPage(BaseModel):
    items: list[DraftResponse]
    total: int
    limit: int
    offset: int


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    sequence_no: int
    event_type: str
    from_status: ApplicationStatus | None
    to_status: ApplicationStatus | None
    message: str
    created_at: datetime


class EventList(BaseModel):
    items: list[EventResponse]
