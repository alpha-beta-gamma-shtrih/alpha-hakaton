"""Validate submitted inputs and build canonical, detached snapshot values."""

from copy import deepcopy

from pydantic import ValidationError

from credit_cabinet.api.errors import APIError
from credit_cabinet.core.demo import CALCULATION_DATE
from credit_cabinet.models import Company, CreditProduct
from credit_cabinet.schemas.business import CompanyResponse, DraftDataPatch, ProductResponse
from credit_cabinet.services.documents import document_references
from credit_cabinet.services.drafts import profile_provenance
from credit_cabinet.services.policy import canonical_hash, money
from credit_cabinet.services.pricing import PURCHASE_PURPOSES
from credit_cabinet.services.product_policy import supported


def invalid(code, message, path):
    raise APIError(422, code, message, fields=[{"field": path, "message": message}])


def validate_parameters(application, product):
    if not supported(product) or application.calculation_date != CALCULATION_DATE:
        raise APIError(
            409,
            "POLICY_VERSION_UNSUPPORTED",
            "Условия продукта требуют согласованной версии демо-правил",
        )
    if not product.is_active:
        raise APIError(409, "PRODUCT_UNAVAILABLE", "Продукт недоступен для новой отправки")
    if (
        application.requested_amount is None
        or not product.min_amount <= application.requested_amount <= product.max_amount
    ):
        invalid("VALIDATION_ERROR", "Укажите сумму в пределах продукта", "requested_amount")
    if (
        application.term_months is None
        or not product.min_term_months <= application.term_months <= product.max_term_months
    ):
        invalid("VALIDATION_ERROR", "Укажите срок в пределах продукта", "term_months")
    if application.purpose_code is None or application.purpose_code not in product.allowed_purposes:
        invalid("VALIDATION_ERROR", "Выберите допустимую цель", "purpose_code")


def application_input(db, application, *, require_confirmation=True):
    product = db.get(CreditProduct, application.product_id)
    validate_parameters(application, product)
    raw = deepcopy(application.draft_data)
    provenance = raw.pop("provenance", profile_provenance())
    try:
        draft = DraftDataPatch.model_validate(raw)
    except ValidationError:
        invalid("VALIDATION_ERROR", "Проверьте структуру финансовых данных", "draft_data")
    if require_confirmation and draft.confirmations.credit_history_check_allowed is not True:
        invalid(
            "CREDIT_HISTORY_CONFIRMATION_REQUIRED",
            "Подтвердите демонстрационную проверку кредитной истории",
            "draft_data.confirmations.credit_history_check_allowed",
        )
    if require_confirmation and draft.confirmations.data_confirmed is not True:
        invalid(
            "DATA_CONFIRMATION_REQUIRED",
            "Подтвердите указанные сведения",
            "draft_data.confirmations.data_confirmed",
        )
    data = draft.model_dump(mode="json")
    if product.version == 2:
        if draft.purchase_from_bank_partner:
            invalid(
                "VALIDATION_ERROR",
                "Партнёрская программа недоступна для прежнего продукта",
                "draft_data.purchase_from_bank_partner",
            )
        data.pop("purchase_from_bank_partner", None)
    elif draft.purchase_from_bank_partner and application.purpose_code not in PURCHASE_PURPOSES:
        invalid(
            "VALIDATION_ERROR",
            "Партнёрская скидка доступна только для закупочных целей",
            "draft_data.purchase_from_bank_partner",
        )
    data["financial_months"] = sorted(data["financial_months"], key=lambda row: row["month"])
    data["provenance"] = deepcopy(provenance)
    data["provenance"]["credit_history"] = None
    # The initial schema stores optional client explanations inside financial_snapshot.
    data["purpose_details"] = application.purpose_details
    company = db.get(Company, application.company_id)
    product_data = ProductResponse.model_validate(product).model_dump(mode="json")
    product_data["policy_config"] = deepcopy(product.policy_config)
    return {
        "schema_version": 2,
        "calculation_date": application.calculation_date.isoformat(),
        "requested_amount": money(application.requested_amount),
        "term_months": application.term_months,
        "purpose_code": application.purpose_code.value,
        "company_snapshot": {
            **CompanyResponse.model_validate(company).model_dump(mode="json"),
            **(
                {"has_active_loan_in_our_bank": company.has_active_loan_in_our_bank}
                if product.version == 3
                else {}
            ),
            "provenance": deepcopy(provenance["company"]),
        },
        "financial_snapshot": data,
        "product_snapshot": product_data,
        "document_refs": document_references(db, application.id),
    }


def financial_input_hash(payload):
    def strip_timing(value):
        if isinstance(value, dict):
            return {key: strip_timing(item) for key, item in value.items() if key != "checked_at"}
        if isinstance(value, list):
            return [strip_timing(item) for item in value]
        return value

    return canonical_hash(strip_timing(payload))
