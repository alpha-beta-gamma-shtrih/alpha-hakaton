from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, EmailStr, Field, SecretStr, field_validator, model_validator

from credit_cabinet.core.demo import CALCULATION_DATE, DEMO_NAMESPACE, FINANCIAL_MONTHS
from credit_cabinet.models.enums import CheckStatus, LegalForm, Purpose, Role
from credit_cabinet.schemas.business import MoneyInput, ProvenanceItem, StrictModel

CompanyKey = str


class CompanySeed(StrictModel):
    company_key: str = Field(pattern=r"^C(?:[0-9]{2}|[1-9][0-9]{2})$")
    legal_name: str = Field(min_length=1, max_length=200)
    legal_form: LegalForm
    inn: str = Field(pattern=r"^[0-9]{10}([0-9]{2})?$")
    registration_number: str | None = Field(default=None, pattern=r"^[0-9]{13}([0-9]{2})?$")
    registered_on: date
    okved_code: str = Field(min_length=1, max_length=16)
    region_code: str = Field(min_length=1, max_length=8)
    business_description: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def legal_identifiers(self):
        if len(self.inn) != (12 if self.legal_form == LegalForm.IP else 10):
            raise ValueError("INN length must match legal form")
        if self.registered_on > CALCULATION_DATE:
            raise ValueError("Registration must precede calculation")
        return self


class FinancialSeed(StrictModel):
    company_key: str
    month: date
    cash_inflow: MoneyInput
    operating_outflow: MoneyInput
    existing_debt_payment: MoneyInput
    source: Literal["DEMO"]

    @field_validator("month")
    @classmethod
    def window(cls, value):
        if value not in FINANCIAL_MONTHS:
            raise ValueError("Month outside financial window")
        return value


class UserSeed(StrictModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    user_key: str = Field(min_length=1, max_length=64)
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=200)
    role: Role
    is_active: bool = Field(strict=True)
    # Public demo credentials only; never copy this field to API responses or logs.
    password: SecretStr | None = Field(default=None, min_length=12, max_length=1024, repr=False)

    @field_validator("email", mode="before")
    @classmethod
    def normalized(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class MembershipSeed(StrictModel):
    user_key: str
    company_key: str


class ProductSeed(StrictModel):
    code: Literal["WC_DEMO"]
    version: Literal[2, 3]
    name: str = Field(min_length=1)
    description: str
    allowed_purposes: list[Purpose]
    min_amount: MoneyInput
    max_amount: MoneyInput
    min_term_months: Literal[6]
    max_term_months: Literal[24, 60]
    annual_rate_percent: Literal["24.000", "20.000"]
    policy_version: Literal["demo-policy-0.2", "demo-policy-0.3"]
    policy_config: dict
    is_active: bool = Field(strict=True)

    @model_validator(mode="after")
    def current_contract(self):
        if self.min_amount != 100000 or self.max_amount != 5000000:
            raise ValueError("Amount bounds differ from demo-0.2")
        from credit_cabinet.services.product_policy import supported

        if not supported(self) or len(self.allowed_purposes) != len(set(self.allowed_purposes)):
            raise ValueError("Unsupported immutable product contract")
        if self.policy_config.get("calculation_date") != CALCULATION_DATE.isoformat():
            raise ValueError("Missing fixed calculation date")
        return self


class DocumentTemplate(StrictModel):
    company_key: str
    kind: Literal["FINANCIAL_STATEMENT"]
    path: str
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class Manifest(StrictModel):
    schema_version: Literal[2]
    dataset_version: Literal["demo-0.2", "demo-0.3"]
    policy_version: Literal["demo-policy-0.2", "demo-policy-0.3"]
    subset: Literal["C01_C02_BOOTSTRAP", "FULL"]
    seed: Literal[42]
    calculation_date: date
    financial_months: list[date]
    uuid_namespace: UUID
    source_versions: dict[str, str]
    company_keys: list[str] = Field(min_length=1, max_length=1000)
    files: dict[str, str]
    document_templates: list[DocumentTemplate]

    @model_validator(mode="after")
    def fixed_context(self):
        if (
            self.calculation_date != CALCULATION_DATE
            or tuple(self.financial_months) != FINANCIAL_MONTHS
        ):
            raise ValueError("Wrong demo calendar")
        if self.uuid_namespace != DEMO_NAMESPACE:
            raise ValueError("Wrong deterministic namespace")
        if self.source_versions != {"FNS": "legal-mock-0.2", "BKI": "bki-mock-0.2"}:
            raise ValueError("Wrong fixture versions")
        if len(set(self.company_keys)) != len(self.company_keys):
            raise ValueError("Duplicate company keys")
        return self


class LegalFacts(StrictModel):
    inn: str
    legal_form: LegalForm
    registered_on: date
    registry_status: Literal["ACTIVE", "LIQUIDATING", "CLOSED"]
    is_bankrupt: bool | None = Field(strict=True)


class CreditFacts(StrictModel):
    history_present: bool = Field(strict=True)
    current_monthly_payment: MoneyInput
    current_overdue_amount: MoneyInput
    max_overdue_days_12m: int = Field(ge=0, le=365, strict=True)

    @model_validator(mode="after")
    def no_history(self):
        if not self.history_present and (
            self.current_monthly_payment != 0
            or self.current_overdue_amount != 0
            or self.max_overdue_days_12m != 0
        ):
            raise ValueError("No-history fixture must have zero indicators")
        return self


class FixtureEntry(StrictModel):
    company_key: str
    status: CheckStatus
    error_code: str | None
    source_version: str
    normalized_data: dict | None
    provenance: ProvenanceItem
    revision_no: int | None = Field(default=None, strict=True, ge=1)
    run_no: int = Field(default=1, strict=True, ge=1)


class ScenarioSeed(StrictModel):
    purchase_from_bank_partner: bool = Field(default=False, strict=True)
    scenario_key: str = Field(min_length=1)
    company_key: str
    requested_amount: MoneyInput
    term_months: int = Field(strict=True, ge=6, le=60)
    purpose_code: Purpose
    sequence: list[str]
    expected_result: dict


class BankRelationshipSeed(StrictModel):
    company_key: str
    has_active_loan_in_our_bank: bool = Field(strict=True)
