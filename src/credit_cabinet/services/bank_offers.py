"""Read-only offer preview, calculated exclusively from the submitted snapshot and saved checks."""

from decimal import Decimal

from credit_cabinet.api.errors import APIError
from credit_cabinet.schemas.bank import OfferPreviewResponse
from credit_cabinet.schemas.business import OfferTermsResponse
from credit_cabinet.services.bank_policy import saved_evaluation
from credit_cabinet.services.policy import annuity, canonical_hash
from credit_cabinet.services.reasons import public_reasons


def calculate(db, application, revision, assessment, parameters):
    product = revision.product_snapshot
    amount, term = parameters.amount, parameters.term_months
    if (
        not Decimal(product["min_amount"])
        <= amount
        <= min(revision.requested_amount, Decimal(product["max_amount"]))
    ):
        raise APIError(
            422,
            "OFFER_AMOUNT_INVALID",
            "Сумма должна быть в пределах продукта и не больше запроса клиента",
        )
    if not product["min_term_months"] <= term <= product["max_term_months"]:
        raise APIError(
            422,
            "OFFER_TERM_INVALID",
            "Срок должен соответствовать версии продукта отправленной заявки",
        )
    if amount == revision.requested_amount and term == revision.term_months:
        raise APIError(422, "OFFER_UNCHANGED", "Условия не изменены; используйте обычное одобрение")
    result = saved_evaluation(db, revision, assessment, amount=amount, term=term)
    original = saved_evaluation(db, revision, assessment)
    if result is None or original is None:
        raise APIError(
            409, "OFFER_CHECKS_INVALID", "Сохранённые проверки не позволяют рассчитать предложение"
        )
    details = result.calculation_details
    # Even a blocked preview must show the calculation if available, but it can never be approved.
    old = original.calculation_details
    payment = annuity(
        amount, term, Decimal(details.get("annual_rate_percent", product["annual_rate_percent"]))
    )
    terms = OfferTermsResponse(
        original_amount=revision.requested_amount,
        original_term_months=revision.term_months,
        original_annual_rate_percent=old.get("annual_rate_percent", product["annual_rate_percent"]),
        original_monthly_payment=old["monthly_payment"],
        amount=amount,
        term_months=term,
        annual_rate_percent=details.get("annual_rate_percent", product["annual_rate_percent"]),
        **payment,
        load_ratio=details.get("load_ratio"),
        pricing=details.get(
            "pricing", {"status": "FIXED", "annual_rate_percent": product["annual_rate_percent"]}
        ),
    )
    snapshot = {
        "schema_version": "BANK-OFFER-1",
        "application_id": str(application.id),
        "revision_id": str(revision.id),
        "revision_input_hash": revision.input_hash,
        "assessment_id": str(assessment.id),
        "application_version": application.lock_version,
        "terms": terms.model_dump(mode="json"),
        "risk_score": result.risk_score,
        "risk_band": result.risk_band,
        "routing": result.routing,
        "reason_codes": result.reason_codes,
        "calculation_details": details,
    }
    allowed = result.routing == "APPROVE" or (
        result.routing == "MANUAL_REVIEW"
        and result.reason_codes[0] == "BORDERLINE_RISK"
        and result.risk_score is not None
        and 30 <= result.risk_score <= 59
    )
    preview = OfferPreviewResponse(
        application_version=application.lock_version,
        terms=terms,
        risk_score=result.risk_score,
        risk_band=result.risk_band,
        routing=result.routing,
        reasons=public_reasons(result.reason_codes),
        can_approve=allowed,
        preview_hash=canonical_hash(snapshot),
    )
    return preview, snapshot
