"""Deterministic demo pricing, independent of the new payment and final risk score."""

from decimal import Decimal

PRICING_VERSION = "demo-pricing-0.3"
PURCHASE_PURPOSES = {"INVENTORY", "SEASONAL_PURCHASE", "EQUIPMENT"}
PRICING_CONFIG = {
    "version": PRICING_VERSION,
    "base_rate": "20.000",
    "minimum_rate": "20.000",
    "age_additions": ["2.000", "1.000", "0.000"],
    "history_additions": {"absent": "2.000", "clean": "0.000", "1_29": "2.000", "30_59": "4.000"},
    "trend_additions": ["0.000", "1.000", "2.000"],
    "term_additions": ["0.000", "1.000", "2.000", "3.000", "4.000"],
    "purpose_discounts": {
        "INVENTORY": "0.500",
        "OPERATING_EXPENSES": "0.000",
        "SEASONAL_PURCHASE": "0.500",
        "EQUIPMENT": "1.000",
        "OTHER": "0.000",
    },
    "bank_customer_discount": "0.500",
    "partner_discount": "0.500",
}


def quote(*, age, history, overdue, trend, term, purpose, bank_customer=False, partner=False):
    """Caller has checked sources, hard stops and completeness. Values are percentage points."""
    config = PRICING_CONFIG
    history_key = (
        "absent" if not history else "30_59" if overdue >= 30 else "1_29" if overdue else "clean"
    )
    additions = [
        (
            "BUSINESS_AGE",
            "Возраст бизнеса",
            config["age_additions"][0 if age < 12 else 1 if age < 24 else 2],
        ),
        ("CREDIT_HISTORY", "Кредитная история", config["history_additions"][history_key]),
        (
            "INFLOW_TREND",
            "Динамика поступлений",
            config["trend_additions"][
                2 if trend <= Decimal("-0.30") else 1 if trend <= Decimal("-0.15") else 0
            ],
        ),
        ("TERM", "Срок кредита", config["term_additions"][min(4, (term - 1) // 12)]),
    ]
    discounts = [
        ("PURPOSE", "Целевая программа", config["purpose_discounts"][purpose]),
        (
            "BANK_CUSTOMER",
            "Исправный заёмщик нашего банка · DEMO",
            config["bank_customer_discount"]
            if bank_customer and history and overdue == 0
            else "0.000",
        ),
        (
            "PARTNER",
            "Покупка у партнёра · заявлено клиентом · DEMO",
            config["partner_discount"] if partner and purpose in PURCHASE_PURPOSES else "0.000",
        ),
    ]
    base = Decimal(config["base_rate"])
    before = base + sum(Decimal(row[2]) for row in additions)
    requested = sum(Decimal(row[2]) for row in discounts)
    final = max(Decimal(config["minimum_rate"]), before - requested)
    return {
        "status": "PERSONALIZED",
        "pricing_version": PRICING_VERSION,
        "base_rate_percent": format(base, ".3f"),
        "minimum_rate_percent": config["minimum_rate"],
        "rate_before_discounts": format(before, ".3f"),
        "requested_discount_pp": format(requested, ".3f"),
        "applied_discount_pp": format(before - final, ".3f"),
        "floor_adjustment_pp": format(final - (before - requested), ".3f"),
        "annual_rate_percent": format(final, ".3f"),
        "additions": [
            {"code": code, "label": label, "percentage_points": value}
            for code, label, value in additions
        ],
        "discounts": [
            {"code": code, "label": label, "percentage_points": value}
            for code, label, value in discounts
        ],
        "bank_relationship_source": "DEMO_BANK_PROFILE",
        "has_active_loan_in_our_bank": bank_customer,
        "purchase_from_bank_partner": partner,
        "purpose_code": purpose,
    }


def unpriced(rate, *, personal=False, reason="CONSENT_REQUIRED"):
    return {
        "status": "INDICATIVE" if personal else "FIXED",
        "annual_rate_percent": format(rate, ".3f"),
        "reason_code": reason if personal else None,
    }
