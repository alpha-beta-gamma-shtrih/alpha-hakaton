"""Versioned demo rules. Decimal arithmetic; no DB, HTTP, model or scenario labels."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext
from importlib.resources import files

from credit_cabinet.core.demo import FINANCIAL_MONTHS
from credit_cabinet.models.enums import CheckSource, CheckStatus, RiskBand, Routing
from credit_cabinet.services.pricing import quote, unpriced

POLICY_VERSION = "demo-policy-0.2"
POLICY_CONFIG = json.loads(
    files("credit_cabinet.core").joinpath("policy_contract.json").read_text(encoding="utf-8")
)
CENT = Decimal("0.01")


def canonical_hash(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def money(value: Decimal) -> str:
    return format(value, ".2f")


def annuity(amount: Decimal, months: int, annual_rate: Decimal) -> dict:
    if amount <= 0 or months <= 0 or annual_rate < 0:
        raise ValueError("Invalid annuity inputs")
    with localcontext() as context:
        context.prec = 40
        rate = annual_rate / 100 / 12
        payment = amount / months if rate == 0 else amount * rate / (1 - (1 + rate) ** -months)
        payment = payment.quantize(CENT, rounding=ROUND_HALF_UP)
        total = payment * months
        return {
            "monthly_payment": money(payment),
            "estimated_total_payment": money(total),
            "estimated_overpayment": money(total - amount),
        }


def age_months(registered_on: date, calculation_date: date) -> int:
    return (
        (calculation_date.year - registered_on.year) * 12
        + calculation_date.month
        - registered_on.month
        - (calculation_date.day < registered_on.day)
    )


def score_route(score: int) -> tuple[RiskBand, Routing, str]:
    if not 0 <= score <= 100:
        raise ValueError("Risk score outside demo range")
    if score <= 29:
        return RiskBand.LOW, Routing.APPROVE, "DEMO_POLICY_PASSED"
    if score <= 59:
        return RiskBand.MEDIUM, Routing.MANUAL_REVIEW, "BORDERLINE_RISK"
    return RiskBand.HIGH, Routing.REJECT, "RISK_SCORE_LIMIT_EXCEEDED"


def score_factors(age: int, load: Decimal, trend: Decimal, overdue: int, history: bool) -> list:
    factors = []

    def add(code, points, value):
        if points:
            factors.append({"factor_id": code, "points": points, "value": str(value)})

    add(
        "BUSINESS_AGE_6_11" if age < 12 else "BUSINESS_AGE_12_23",
        20 if age < 12 else 10 if age < 24 else 0,
        age,
    )
    if load > Decimal("0.65"):
        add("LOAD_65_80", 40, load)
    elif load > Decimal("0.50"):
        add("LOAD_50_65", 25, load)
    elif load > Decimal("0.35"):
        add("LOAD_35_50", 10, load)
    if trend < Decimal("-0.30"):
        add("INFLOW_DROP_OVER_30", 25, trend)
    elif trend < Decimal("-0.15"):
        add("INFLOW_DROP_15_30", 15, trend)
    elif trend < 0:
        add("INFLOW_DROP_0_15", 5, trend)
    if overdue >= 30:
        add("OVERDUE_30_59", 25, overdue)
    elif overdue > 0:
        add("OVERDUE_1_29", 10, overdue)
    if not history:
        add("CREDIT_HISTORY_ABSENT", 15, False)
    return factors


@dataclass(frozen=True)
class SourceResult:
    source: CheckSource
    status: CheckStatus
    normalized_data: dict | None
    error_code: str | None
    source_version: str
    started_at: datetime
    completed_at: datetime


@dataclass
class Evaluation:
    routing: Routing
    reason_codes: list[str]
    risk_score: int | None = None
    risk_band: RiskBand = RiskBand.UNKNOWN
    calculation_details: dict = field(default_factory=dict)
    checks: list[SourceResult] = field(default_factory=list)
    requested_fields: list[str] = field(default_factory=list)
    input_facts: dict = field(default_factory=dict)


def evaluate(
    *,
    company: dict,
    financials: list[dict],
    amount: Decimal,
    term: int,
    annual_rate: Decimal,
    calculation_date: date,
    source: Callable[[CheckSource], SourceResult],
    personal_pricing: bool = False,
    purpose: str | None = None,
    partner_purchase: bool = False,
    service_exposure: dict | None = None,
) -> Evaluation:
    with localcontext() as context:
        context.prec = 40
        result = _evaluate(
            company,
            financials,
            amount,
            term,
            annual_rate,
            calculation_date,
            source,
            personal_pricing,
            purpose,
            partner_purchase,
            service_exposure,
        )
        if personal_pricing and "pricing" not in result.calculation_details:
            result.calculation_details["pricing"] = unpriced(
                annual_rate, personal=True, reason=result.reason_codes[0]
            )
        return result


def _evaluate(
    company,
    financials,
    amount,
    term,
    annual_rate,
    calculation_date,
    source,
    personal_pricing,
    purpose,
    partner_purchase,
    service_exposure,
):
    result = Evaluation(Routing.MANUAL_REVIEW, [])
    if service_exposure is not None:
        result.input_facts["service_exposure"] = service_exposure.copy()

    def finish(route, reason, fields=None):
        result.routing = route
        result.reason_codes = [reason]
        result.requested_fields = fields or []
        return result

    def consult(kind):
        response = source(kind)
        result.checks.append(response)
        result.input_facts[kind.value.lower()] = response.normalized_data
        return response

    legal = consult(CheckSource.FNS)
    if legal.status != CheckStatus.SUCCESS:
        return finish(
            Routing.MANUAL_REVIEW,
            "SOURCE_RESPONSE_INVALID"
            if legal.error_code == "SOURCE_RESPONSE_INVALID"
            else "SOURCE_FNS_UNAVAILABLE",
        )
    facts = legal.normalized_data
    if any(str(facts[key]) != str(company[key]) for key in ("inn", "legal_form", "registered_on")):
        return finish(Routing.MANUAL_REVIEW, "COMPANY_DATA_MISMATCH")
    if facts["registry_status"] != "ACTIVE":
        return finish(Routing.REJECT, "COMPANY_NOT_ACTIVE")
    if facts["is_bankrupt"] is True:
        return finish(Routing.REJECT, "COMPANY_BANKRUPTCY")
    if facts["is_bankrupt"] is None:
        return finish(Routing.MANUAL_REVIEW, "LEGAL_STATUS_UNCONFIRMED")
    age = age_months(date.fromisoformat(company["registered_on"]), calculation_date)
    result.calculation_details["business_age_months"] = age
    if age < 6:
        return finish(Routing.REJECT, "BUSINESS_TOO_YOUNG")
    credit = consult(CheckSource.BKI)
    if credit.status != CheckStatus.SUCCESS:
        return finish(
            Routing.MANUAL_REVIEW,
            "SOURCE_RESPONSE_INVALID"
            if credit.error_code == "SOURCE_RESPONSE_INVALID"
            else "SOURCE_BKI_UNAVAILABLE",
        )
    facts = credit.normalized_data
    if Decimal(facts["current_overdue_amount"]) > 0:
        return finish(Routing.REJECT, "CURRENT_OVERDUE")
    if facts["max_overdue_days_12m"] >= 60:
        return finish(Routing.REJECT, "SEVERE_OVERDUE_HISTORY")
    by_month = {row["month"]: row for row in financials}
    missing = []
    for month in FINANCIAL_MONTHS:
        key = month.isoformat()
        for name in ("cash_inflow", "operating_outflow", "existing_debt_payment"):
            if by_month.get(key, {}).get(name) is None:
                missing.append(f"draft_data.financial_months.{key}.{name}")
    result.checks.append(
        SourceResult(
            CheckSource.DATA_QUALITY,
            CheckStatus.NO_DATA if missing else CheckStatus.SUCCESS,
            None if missing else {"financial_month_count": 6},
            "FINANCIAL_HISTORY_INCOMPLETE" if missing else None,
            "data-quality-0.2",
            credit.completed_at,
            credit.completed_at,
        )
    )
    if missing:
        return finish(Routing.NEEDS_INFO, "FINANCIAL_HISTORY_INCOMPLETE", missing)
    months = [by_month[month.isoformat()] for month in FINANCIAL_MONTHS]
    declared = Decimal(months[-1]["existing_debt_payment"])
    confirmed = Decimal(facts["current_monthly_payment"])
    result.calculation_details.update(
        declared_current_payment=money(declared), confirmed_current_payment=money(confirmed)
    )
    if abs(declared - confirmed) > max(
        Decimal("1000.00"), Decimal("0.10") * max(declared, confirmed)
    ):
        return finish(
            Routing.NEEDS_INFO,
            "DEBT_PAYMENT_MISMATCH",
            ["draft_data.financial_months.2026-09-01.existing_debt_payment"],
        )
    average = (
        sum(Decimal(row["cash_inflow"]) - Decimal(row["operating_outflow"]) for row in months) / 6
    )
    result.calculation_details["average_operating_cashflow"] = str(average)
    if average <= 0:
        return finish(Routing.REJECT, "NON_POSITIVE_CASHFLOW")
    if personal_pricing:
        first = sum(Decimal(row["cash_inflow"]) for row in months[:3])
        if first == 0:
            return finish(Routing.MANUAL_REVIEW, "TREND_BASELINE_ZERO")
        trend = sum(Decimal(row["cash_inflow"]) for row in months[3:]) / first - 1
        pricing = quote(
            age=age,
            history=facts["history_present"],
            overdue=facts["max_overdue_days_12m"],
            trend=trend,
            term=term,
            purpose=purpose,
            bank_customer=company.get("has_active_loan_in_our_bank", False),
            partner=partner_purchase,
        )
        result.calculation_details["pricing"] = pricing
        annual_rate = Decimal(pricing["annual_rate_percent"])
        result.calculation_details["annual_rate_percent"] = format(annual_rate, ".3f")
    payment = annuity(amount, term, annual_rate)
    existing = max(declared, confirmed)
    if service_exposure is not None:
        result.calculation_details.update(
            base_existing_payment=money(existing),
            service_signed_payment=service_exposure["signed_payment"],
            service_reserved_payment=service_exposure["reserved_payment"],
            service_exposure=service_exposure.copy(),
        )
        existing += Decimal(service_exposure["signed_payment"]) + Decimal(
            service_exposure["reserved_payment"]
        )
    load = (existing + Decimal(payment["monthly_payment"])) / average
    result.calculation_details.update(
        payment, existing_payment=money(existing), load_ratio=str(load)
    )
    if load > Decimal("0.80"):
        return finish(Routing.REJECT, "DEBT_LOAD_LIMIT_EXCEEDED")
    first = sum(Decimal(row["cash_inflow"]) for row in months[:3])
    if first == 0:
        return finish(Routing.MANUAL_REVIEW, "TREND_BASELINE_ZERO")
    trend = sum(Decimal(row["cash_inflow"]) for row in months[3:]) / first - 1
    factors = score_factors(
        age, load, trend, facts["max_overdue_days_12m"], facts["history_present"]
    )
    score = min(100, sum(row["points"] for row in factors))
    band, route, reason = score_route(score)
    result.risk_score, result.risk_band, result.routing = score, band, route
    result.reason_codes = [reason, *[row["factor_id"] for row in factors]]
    result.calculation_details.update(inflow_trend=str(trend), factors=factors)
    return result
