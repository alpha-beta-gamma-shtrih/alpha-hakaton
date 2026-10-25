from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from credit_cabinet.models.enums import Purpose
from credit_cabinet.schemas.business import (
    MoneyOutput,
    PositiveInteger,
    RateOutput,
    SignatureResponse,
    StrictModel,
)


class AgreementContent(StrictModel):
    schema_version: Literal["DEMO-1"] = "DEMO-1"
    title: str
    notice: str
    issued_at: datetime
    application_id: UUID
    revision_id: UUID
    decision_id: UUID
    company_name: str
    inn: str
    purpose_code: Purpose
    approved_amount: MoneyOutput
    term_months: int
    annual_rate_percent: RateOutput
    monthly_payment: MoneyOutput
    estimated_total_payment: MoneyOutput
    estimated_overpayment: MoneyOutput


class AgreementResponse(StrictModel):
    content: AgreementContent
    content_sha256: str
    signature: SignatureResponse | None


class SignAgreementRequest(StrictModel):
    expected_version: PositiveInteger
    decision_id: UUID
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    accepted: bool = Field(strict=True)
