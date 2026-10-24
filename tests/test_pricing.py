from decimal import Decimal as D

import pytest

from credit_cabinet.core.demo import CALCULATION_DATE
from credit_cabinet.core.security import utc_now
from credit_cabinet.services.policy import SourceResult, evaluate
from credit_cabinet.services.pricing import quote
from tests.test_policy import policy_input


def price(**changes):
    args = dict(age=36, history=True, overdue=0, trend=D(0), term=12, purpose="OTHER")
    return quote(**{**args, **changes})


@pytest.mark.parametrize(
    "term,rate",
    [
        (6, 20),
        (12, 20),
        (13, 21),
        (24, 21),
        (25, 22),
        (36, 22),
        (37, 23),
        (48, 23),
        (49, 24),
        (60, 24),
    ],
)
def test_term_boundaries(term, rate):
    assert D(price(term=term)["annual_rate_percent"]) == rate


@pytest.mark.parametrize("age,extra", [(6, 2), (11, 2), (12, 1), (23, 1), (24, 0)])
def test_age_boundaries(age, extra):
    assert D(price(age=age)["annual_rate_percent"]) == 20 + extra


@pytest.mark.parametrize("days,extra", [(0, 0), (1, 2), (29, 2), (30, 4), (59, 4)])
def test_history_boundaries(days, extra):
    assert D(price(overdue=days)["annual_rate_percent"]) == 20 + extra


@pytest.mark.parametrize(
    "trend,extra", [("-0.14999", 0), ("-0.15", 1), ("-0.29999", 1), ("-0.30", 2)]
)
def test_trend_boundaries(trend, extra):
    assert D(price(trend=D(trend))["annual_rate_percent"]) == 20 + extra


@pytest.mark.parametrize(
    "purpose,discount",
    [
        ("INVENTORY", "0.5"),
        ("SEASONAL_PURCHASE", "0.5"),
        ("OPERATING_EXPENSES", "0"),
        ("EQUIPMENT", "1"),
        ("OTHER", "0"),
    ],
)
def test_purpose_discounts(purpose, discount):
    report = price(term=60, purpose=purpose)
    assert D(report["annual_rate_percent"]) == 24 - D(discount)


def test_floor_shows_actual_discount_and_ineligible_relationship():
    report = price(term=13, purpose="EQUIPMENT", bank_customer=True, partner=True)
    assert report["annual_rate_percent"] == "20.000"
    assert report["requested_discount_pp"] == "2.000"
    assert report["applied_discount_pp"] == "1.000"
    assert report["floor_adjustment_pp"] == "1.000"
    assert price(history=False, bank_customer=True)["discounts"][1]["percentage_points"] == "0.000"
    assert price(overdue=1, bank_customer=True)["discounts"][1]["percentage_points"] == "0.000"
    assert price(purpose="OTHER", partner=True)["discounts"][2]["percentage_points"] == "0.000"
    assert (
        D(price(age=6, history=True, overdue=59, trend=D("-0.3"), term=60)["annual_rate_percent"])
        == 32
    )


def test_personal_pricing_precedes_payment_and_does_not_bypass_hard_stops():
    company, months, legal, credit = policy_input()
    company["has_active_loan_in_our_bank"] = True

    def run():
        return evaluate(
            company=company,
            financials=months,
            amount=D("1000000"),
            term=60,
            annual_rate=D(20),
            calculation_date=CALCULATION_DATE,
            source=lambda kind: SourceResult(
                kind,
                "SUCCESS",
                legal if kind == "FNS" else credit,
                None,
                "test",
                utc_now(),
                utc_now(),
            ),
            personal_pricing=True,
            purpose="EQUIPMENT",
            partner_purchase=True,
        )

    result = run()
    assert result.calculation_details["annual_rate_percent"] == "22.000"
    credit["current_overdue_amount"] = "1.00"
    result = run()
    assert result.routing == "REJECT"
    assert result.reason_codes == ["CURRENT_OVERDUE"]
    assert result.calculation_details["pricing"]["status"] == "INDICATIVE"
