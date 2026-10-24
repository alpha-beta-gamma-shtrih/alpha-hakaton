"""Bank permissions are derived from the latest submitted snapshot and saved checks."""

from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy import select

from credit_cabinet.core.demo import CALCULATION_DATE
from credit_cabinet.models import CheckResult
from credit_cabinet.models.enums import ApplicationStatus, CheckSource, CheckStatus
from credit_cabinet.schemas.business import DraftDataPatch
from credit_cabinet.schemas.seed import CreditFacts, LegalFacts
from credit_cabinet.services.policy import SourceResult, evaluate
from credit_cabinet.services.product_policy import evaluation_options, supported
from credit_cabinet.services.submissions import can_retry


def saved_evaluation(db, revision, assessment):
    """Recheck mandatory conditions locally, with no source calls and no new assessment."""
    if (
        assessment is None
        or assessment.revision_id != revision.id
        or assessment.rules_version != revision.product_snapshot.get("policy_version")
    ):
        return None
    product = revision.product_snapshot
    confirmations = revision.financial_snapshot.get("confirmations", {})
    if (
        revision.schema_version != 2
        or not supported(product)
        or confirmations.get("data_confirmed") is not True
        or confirmations.get("credit_history_check_allowed") is not True
    ):
        return None
    try:
        if not (
            Decimal(product["min_amount"])
            <= revision.requested_amount
            <= Decimal(product["max_amount"])
            and product["min_term_months"] <= revision.term_months <= product["max_term_months"]
            and revision.purpose_code in product["allowed_purposes"]
        ):
            return None
        DraftDataPatch.model_validate(
            {
                key: value
                for key, value in revision.financial_snapshot.items()
                if key in DraftDataPatch.model_fields
            }
        )
        checks = {
            row.source: row
            for row in db.scalars(
                select(CheckResult).where(CheckResult.assessment_id == assessment.id)
            )
        }
        if set(checks) != {CheckSource.FNS, CheckSource.BKI, CheckSource.DATA_QUALITY} or any(
            row.status != CheckStatus.SUCCESS or row.normalized_data is None
            for row in checks.values()
        ):
            return None

        def source(kind):
            row = checks[kind]
            raw = {key: value for key, value in row.normalized_data.items() if key != "provenance"}
            data = (
                (LegalFacts if kind == CheckSource.FNS else CreditFacts)
                .model_validate(raw)
                .model_dump(mode="json")
            )
            return SourceResult(
                kind,
                row.status,
                data,
                row.error_code,
                row.source_version,
                row.started_at,
                row.completed_at,
            )

        result = evaluate(
            company=revision.company_snapshot,
            financials=revision.financial_snapshot["financial_months"],
            amount=revision.requested_amount,
            term=revision.term_months,
            annual_rate=Decimal(product["annual_rate_percent"]),
            calculation_date=CALCULATION_DATE,
            source=source,
            **evaluation_options(
                {
                    "product_snapshot": product,
                    "financial_snapshot": revision.financial_snapshot,
                    "purpose_code": revision.purpose_code.value,
                }
            ),
        )
        if (
            result.routing != assessment.routing
            or result.risk_score != assessment.risk_score
            or result.risk_band != assessment.risk_band
            or result.reason_codes != assessment.reason_codes
            or result.calculation_details != assessment.calculation_details
        ):
            return None
        return result
    except (KeyError, ValueError, TypeError, ValidationError, ArithmeticError):
        return None


def bank_actions(db, application, revision, assessment):
    if application.status == ApplicationStatus.SUBMITTED:
        return ["RETRY_PROCESSING"]
    if application.status != ApplicationStatus.MANUAL_REVIEW:
        return []
    if can_retry(application, assessment):
        return ["RETRY_PROCESSING"]
    result = saved_evaluation(db, revision, assessment)
    if result is None:
        return []
    if (
        result.reason_codes[0] == "BORDERLINE_RISK"
        and result.risk_score is not None
        and 30 <= result.risk_score <= 59
    ):
        return ["REQUEST_INFO", "APPROVE", "REJECT"]
    if result.reason_codes == ["TREND_BASELINE_ZERO"]:
        return ["REQUEST_INFO"]
    return []
