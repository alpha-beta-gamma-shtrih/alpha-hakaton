"""Allowlisted immutable product versions; legacy demo-0.2 remains reproducible."""

from copy import deepcopy
from decimal import Decimal

from credit_cabinet.services.policy import POLICY_CONFIG
from credit_cabinet.services.pricing import PRICING_CONFIG

PERSONAL_POLICY_VERSION = "demo-policy-0.3"
PERSONAL_POLICY_CONFIG = {**deepcopy(POLICY_CONFIG), "pricing": deepcopy(PRICING_CONFIG)}
LEGACY_PURPOSES = {"INVENTORY", "OPERATING_EXPENSES", "SEASONAL_PURCHASE"}


def supported(product):
    get = product.get if isinstance(product, dict) else lambda key: getattr(product, key, None)
    version = get("version")
    personal = version == 3
    return (
        get("code") == "WC_DEMO"
        and version in (2, 3)
        and get("policy_version") == (PERSONAL_POLICY_VERSION if personal else "demo-policy-0.2")
        and get("policy_config") == (PERSONAL_POLICY_CONFIG if personal else POLICY_CONFIG)
        and Decimal(get("annual_rate_percent")) == (Decimal(20) if personal else Decimal(24))
        and Decimal(get("min_amount")) == Decimal(100000)
        and Decimal(get("max_amount")) == Decimal(5000000)
        and get("min_term_months") == 6
        and get("max_term_months") == (60 if personal else 24)
        and set(get("allowed_purposes"))
        == (LEGACY_PURPOSES | {"EQUIPMENT", "OTHER"} if personal else LEGACY_PURPOSES)
    )


def evaluation_options(payload):
    personal = payload["product_snapshot"]["policy_version"] == PERSONAL_POLICY_VERSION
    return {
        "personal_pricing": personal,
        "purpose": payload.get("purpose_code"),
        "partner_purchase": payload["financial_snapshot"].get("purchase_from_bank_partner", False)
        if personal
        else False,
    }
