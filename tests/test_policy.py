from copy import deepcopy
from datetime import date
from decimal import Decimal as D

import pytest

from credit_cabinet.core.demo import CALCULATION_DATE, FINANCIAL_MONTHS
from credit_cabinet.core.security import utc_now
from credit_cabinet.services.policy import (
    POLICY_CONFIG,
    SourceResult,
    age_months,
    annuity,
    canonical_hash,
    evaluate,
    score_factors,
    score_route,
)
from credit_cabinet.services.seed import load_bundle
from tests.conftest import ROOT


def policy_input(
    *, inflow="1200000.00", outflow="850000.00", debt="30000.00", registered="2022-10-01"
):
    company = {"inn": "0000000001", "legal_form": "OOO", "registered_on": registered}
    months = [
        {
            "month": month.isoformat(),
            "cash_inflow": inflow,
            "operating_outflow": outflow,
            "existing_debt_payment": debt,
        }
        for month in FINANCIAL_MONTHS
    ]
    legal = {**company, "registry_status": "ACTIVE", "is_bankrupt": False}
    credit = {
        "history_present": True,
        "current_monthly_payment": debt,
        "current_overdue_amount": "0.00",
        "max_overdue_days_12m": 0,
    }
    return company, months, legal, credit


def run_policy(company, months, legal, credit, amount="1000000.00", term=12, *, errors=None):
    calls = []

    def source(kind):
        calls.append(kind.value)
        now = utc_now()
        status, error = (errors or {}).get(kind.value, ("SUCCESS", None))
        return SourceResult(
            kind,
            status,
            (legal if kind == "FNS" else credit) if status == "SUCCESS" else None,
            error,
            "test",
            now,
            now,
        )

    result = evaluate(
        company=company,
        financials=months,
        amount=D(amount),
        term=term,
        annual_rate=D("24.000"),
        calculation_date=CALCULATION_DATE,
        source=source,
    )
    return result, calls


@pytest.mark.parametrize(
    "amount,term,payment",
    [
        ("1000000", 12, "94559.60"),
        ("2000000", 12, "189119.19"),
        ("1500000", 12, "141839.39"),
        ("500000", 18, "33351.05"),
        ("1500000", 24, "79306.65"),
    ],
)
def test_annuity_contract(amount, term, payment):
    result = annuity(D(amount), term, D(24))
    assert result["monthly_payment"] == payment
    assert D(result["estimated_total_payment"]) == D(payment) * term
    assert D(result["estimated_overpayment"]) == D(payment) * term - D(amount)


def test_zero_rate_and_half_up():
    assert annuity(D("1.01"), 2, D(0))["monthly_payment"] == "0.51"


@pytest.mark.parametrize(
    "registered,age",
    [
        ("2026-04-01", 6),
        ("2026-04-02", 5),
        ("2025-10-01", 12),
        ("2024-10-01", 24),
        ("2026-03-31", 6),
    ],
)
def test_full_calendar_months(registered, age):
    assert age_months(date.fromisoformat(registered), CALCULATION_DATE) == age


@pytest.mark.parametrize(
    "score,band,route",
    [
        (29, "LOW", "APPROVE"),
        (30, "MEDIUM", "MANUAL_REVIEW"),
        (59, "MEDIUM", "MANUAL_REVIEW"),
        (60, "HIGH", "REJECT"),
    ],
)
def test_route_boundaries(score, band, route):
    assert score_route(score)[:2] == (band, route)


@pytest.mark.parametrize(
    "age,load,trend,overdue,history,points",
    [
        (6, "0.35", "0", 0, True, 20),
        (11, "0.35", "0", 0, True, 20),
        (12, "0.35", "0", 0, True, 10),
        (23, "0.35", "0", 0, True, 10),
        (24, "0.35", "0", 0, True, 0),
        (48, "0.35000000000001", "0", 0, True, 10),
        (48, "0.50", "0", 0, True, 10),
        (48, "0.50000000000001", "0", 0, True, 25),
        (48, "0.65", "0", 0, True, 25),
        (48, "0.65000000000001", "0", 0, True, 40),
        (48, "0.80", "0", 0, True, 40),
        (48, "0.35", "-0.15", 0, True, 5),
        (48, "0.35", "-0.15000000000001", 0, True, 15),
        (48, "0.35", "-0.30", 0, True, 15),
        (48, "0.35", "-0.30000000000001", 0, True, 25),
        (48, "0.35", "0", 29, True, 10),
        (48, "0.35", "0", 30, True, 25),
        (48, "0.35", "0", 59, True, 25),
        (48, "0.35", "0", 0, False, 15),
    ],
)
def test_scoring_boundaries(age, load, trend, overdue, history, points):
    assert (
        sum(factor["points"] for factor in score_factors(age, D(load), D(trend), overdue, history))
        == points
    )


def test_eight_reference_profiles():
    cases = [
        (policy_input(), "1000000.00", "APPROVE", 10, "DEMO_POLICY_PASSED"),
        (
            policy_input(inflow="800000.00", outflow="600000.00", debt="100000.00"),
            "2000000.00",
            "REJECT",
            None,
            "DEBT_LOAD_LIMIT_EXCEEDED",
        ),
        (
            policy_input(
                inflow="800000.00", outflow="500000.00", debt="50000.00", registered="2025-04-01"
            ),
            "1500000.00",
            "MANUAL_REVIEW",
            35,
            "BORDERLINE_RISK",
        ),
        (policy_input(), "1000000.00", "NEEDS_INFO", None, "FINANCIAL_HISTORY_INCOMPLETE"),
        (policy_input(), "1000000.00", "REJECT", None, "SEVERE_OVERDUE_HISTORY"),
        (policy_input(), "1000000.00", "MANUAL_REVIEW", None, "SOURCE_BKI_UNAVAILABLE"),
        (
            policy_input(
                inflow="800000.00", outflow="500000.00", debt="0.00", registered="2026-02-01"
            ),
            "1000000.00",
            "MANUAL_REVIEW",
            35,
            "BORDERLINE_RISK",
        ),
        (
            policy_input(inflow="600000.00", outflow="650000.00", debt="20000.00"),
            "500000.00",
            "REJECT",
            None,
            "NON_POSITIVE_CASHFLOW",
        ),
    ]
    for index, (inputs, amount, route, score, reason) in enumerate(cases):
        company, months, legal, credit = deepcopy(inputs)
        if index == 3:
            months.pop(2)
        if index == 4:
            credit["max_overdue_days_12m"] = 75
        if index == 6:
            credit["history_present"] = False
        result, _ = run_policy(
            company,
            months,
            legal,
            credit,
            amount,
            errors={"BKI": ("ERROR", "TIMEOUT")} if index == 5 else None,
        )
        assert (result.routing, result.risk_score, result.reason_codes[0]) == (route, score, reason)
        if score is None:
            assert result.risk_band == "UNKNOWN"


@pytest.mark.parametrize(
    "change,reason",
    [
        ("closed", "COMPANY_NOT_ACTIVE"),
        ("bankrupt", "COMPANY_BANKRUPTCY"),
        ("unknown", "LEGAL_STATUS_UNCONFIRMED"),
        ("mismatch", "COMPANY_DATA_MISMATCH"),
        ("young", "BUSINESS_TOO_YOUNG"),
    ],
)
def test_legal_priority_skips_bki(change, reason):
    inputs = list(policy_input(registered="2026-04-02" if change == "young" else "2022-10-01"))
    if change == "closed":
        inputs[2]["registry_status"] = "CLOSED"
    if change == "bankrupt":
        inputs[2]["is_bankrupt"] = True
    if change == "unknown":
        inputs[2]["is_bankrupt"] = None
    if change == "mismatch":
        inputs[2]["inn"] = "0000000002"
    result, calls = run_policy(*inputs, errors={"BKI": ("ERROR", "TIMEOUT")})
    assert result.reason_codes == [reason] and calls == ["FNS"]
    assert result.risk_score is None


@pytest.mark.parametrize(
    "status,error,reason",
    [
        ("ERROR", "TIMEOUT", "SOURCE_FNS_UNAVAILABLE"),
        ("NO_DATA", None, "SOURCE_FNS_UNAVAILABLE"),
        ("ERROR", "SOURCE_RESPONSE_INVALID", "SOURCE_RESPONSE_INVALID"),
    ],
)
def test_source_failure_precedes_financial_rejection(status, error, reason):
    inputs = list(policy_input(outflow="2000000.00"))
    result, calls = run_policy(*inputs, errors={"FNS": (status, error)})
    assert result.routing == "MANUAL_REVIEW" and result.reason_codes == [reason]
    assert calls == ["FNS"] and result.calculation_details == {}


def test_debt_tolerance_and_no_double_counting():
    company, months, legal, credit = policy_input(debt="10000.00")
    credit["current_monthly_payment"] = "11111.11"
    result, _ = run_policy(company, months, legal, credit)
    assert result.calculation_details["existing_payment"] == "11111.11"
    credit["current_monthly_payment"] = "11111.12"
    result, _ = run_policy(company, months, legal, credit)
    assert result.reason_codes == ["DEBT_PAYMENT_MISMATCH"]
    company, months, legal, credit = policy_input(debt="0.00")
    credit["current_monthly_payment"] = "1000.00"
    assert run_policy(company, months, legal, credit)[0].routing == "APPROVE"
    credit["current_monthly_payment"] = "1000.01"
    assert run_policy(company, months, legal, credit)[0].routing == "NEEDS_INFO"


def test_zero_baseline_no_division_by_zero_and_load_priority():
    company, months, legal, credit = policy_input(inflow="2000000.00", outflow="0.00", debt="0.00")
    for row in months[:3]:
        row["cash_inflow"] = "0.00"
    result, _ = run_policy(company, months, legal, credit)
    assert result.reason_codes == ["TREND_BASELINE_ZERO"]
    for row in months:
        row["cash_inflow"] = "0.00"
    assert run_policy(company, months, legal, credit)[0].reason_codes == ["NON_POSITIVE_CASHFLOW"]


def test_published_configuration_and_hash_are_reproducible():
    bundle = load_bundle(ROOT / "demo_data/demo_0_2")
    assert bundle.products[0].policy_config == POLICY_CONFIG
    assert canonical_hash({"a": 1, "b": 2}) == canonical_hash({"b": 2, "a": 1})


@pytest.mark.parametrize("flow,route", [("118199.50", "MANUAL_REVIEW"), ("118199.49", "REJECT")])
def test_load_limit_uses_unrounded_ratio(flow, route):
    result, _ = run_policy(*policy_input(inflow=flow, outflow="0.00", debt="0.00"))
    assert result.routing == route


def test_declining_inflow_and_past_overdue_push_reference_c03_to_sixty():
    company, months, legal, credit = policy_input(
        inflow="800000.00", outflow="500000.00", debt="50000.00", registered="2025-04-01"
    )
    credit["max_overdue_days_12m"] = 30
    result, _ = run_policy(company, months, legal, credit, "1500000.00")
    assert result.risk_score == 60 and result.routing == "REJECT"
    credit["max_overdue_days_12m"] = 0
    for index, row in enumerate(months):
        row["cash_inflow"] = "1000000.00" if index < 3 else "650000.00"
    result, _ = run_policy(company, months, legal, credit, "1500000.00")
    assert result.risk_score == 60 and result.routing == "REJECT"
