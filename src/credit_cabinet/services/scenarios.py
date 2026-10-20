"""Read-only comparison; at most three candidates share one frozen set of source facts."""

from copy import deepcopy
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select

from credit_cabinet.api.errors import APIError
from credit_cabinet.models import CheckResult
from credit_cabinet.models.enums import ApplicationStatus, CheckSource
from credit_cabinet.schemas.scenarios import ScenariosResponse
from credit_cabinet.services.access import client_application
from credit_cabinet.services.policy import SourceResult, annuity, evaluate
from credit_cabinet.services.reasons import public_reasons
from credit_cabinet.services.snapshots import application_input, financial_input_hash
from credit_cabinet.services.submissions import latest_assessment, latest_revision


def compare(db, user_id, application_id, body, sources):
    application = client_application(db, user_id, application_id)
    if application.lock_version != body.expected_version:
        raise APIError(
            409,
            "VERSION_CONFLICT",
            "Заявка уже изменена; сохраните форму и получите актуальную версию",
        )
    revision = latest_revision(db, application.id)
    assessment = latest_assessment(db, revision.id) if revision else None
    if revision and application.status not in (
        ApplicationStatus.DRAFT,
        ApplicationStatus.NEEDS_INFO,
    ):
        # A result is compared against its submitted terms, even if the catalog changes later.
        payload = {
            "schema_version": revision.schema_version,
            "calculation_date": revision.product_snapshot["policy_config"]["calculation_date"],
            "requested_amount": format(revision.requested_amount, ".2f"),
            "term_months": revision.term_months,
            "purpose_code": revision.purpose_code.value,
            "company_snapshot": deepcopy(revision.company_snapshot),
            "financial_snapshot": deepcopy(revision.financial_snapshot),
            "product_snapshot": deepcopy(revision.product_snapshot),
            "document_refs": deepcopy(revision.document_refs),
        }
    else:
        payload = application_input(db, application, require_confirmation=False)
    allowed = (
        application.draft_data.get("confirmations", {}).get("credit_history_check_allowed") is True
    )
    cache = {}
    if allowed and assessment:
        for row in db.scalars(
            select(CheckResult).where(
                CheckResult.assessment_id == assessment.id,
                CheckResult.source.in_([CheckSource.FNS, CheckSource.BKI]),
            )
        ):
            cache[row.source] = SourceResult(
                row.source,
                row.status,
                deepcopy(row.normalized_data),
                row.error_code,
                row.source_version,
                row.started_at,
                row.completed_at,
            )

    def source(kind):
        if kind not in cache:
            cache[kind] = sources.check(
                payload["company_snapshot"]["inn"],
                kind,
                revision.revision_no if revision else 1,
                assessment.run_no if assessment else 1,
            )
        return cache[kind]

    product = payload["product_snapshot"]
    amount = Decimal(payload["requested_amount"])
    term = payload["term_months"]
    options = [
        ("REQUESTED", amount, term),
        (
            "LOWER_AMOUNT",
            max(
                Decimal(product["min_amount"]),
                (amount * Decimal("0.8")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            ),
            term,
        ),
        ("LONGER_TERM", amount, min(term + 12, product["max_term_months"])),
    ]
    candidates = []
    seen = set()
    for candidate_id, value, months in options:
        if (value, months) in seen:
            continue
        seen.add((value, months))
        payment = annuity(value, months, Decimal(product["annual_rate_percent"]))
        result = None
        if allowed:
            result = evaluate(
                company=payload["company_snapshot"],
                financials=payload["financial_snapshot"]["financial_months"],
                amount=value,
                term=months,
                annual_rate=Decimal(product["annual_rate_percent"]),
                calculation_date=date.fromisoformat(payload["calculation_date"]),
                source=source,
            )
        provenance = {
            "company": deepcopy(payload["company_snapshot"]["provenance"]),
            "financial_months": deepcopy(
                payload["financial_snapshot"]["provenance"]["financial_months"]
            ),
            "credit_history": None,
        }
        if result:
            for check in result.checks:
                if check.normalized_data and check.source in (CheckSource.FNS, CheckSource.BKI):
                    provenance[
                        "company" if check.source == CheckSource.FNS else "credit_history"
                    ] = deepcopy(check.normalized_data.get("provenance"))
        codes = result.reason_codes if result else ["CREDIT_HISTORY_CONFIRMATION_REQUIRED"]
        candidates.append(
            {
                "candidate_id": candidate_id,
                "requested_amount": value,
                "term_months": months,
                "annual_rate_percent": Decimal(product["annual_rate_percent"]),
                **payment,
                "load_ratio": result.calculation_details.get("load_ratio") if result else None,
                "risk_score": result.risk_score if result else None,
                "preliminary_route": result.routing if result else None,
                "reason_codes": codes,
                "reasons": public_reasons(codes),
                "provenance": provenance,
                "policy_version": product["policy_version"],
                "input_hash": "",
                "is_binding": False,
            }
        )
    # Every candidate's hash uses the same source context; observation time is excluded.
    source_context = {
        str(kind): {
            "status": check.status.value if hasattr(check.status, "value") else check.status,
            "normalized_data": check.normalized_data,
            "source_version": check.source_version,
        }
        for kind, check in cache.items()
    }
    for candidate in candidates:
        candidate["input_hash"] = financial_input_hash(
            {
                "input": payload,
                "sources": source_context,
                "assessment_id": str(assessment.id) if allowed and assessment else None,
                "requested_amount": format(candidate["requested_amount"], ".2f"),
                "term_months": candidate["term_months"],
            }
        )
    return ScenariosResponse(
        mode="PREVIEW" if allowed else "CALCULATION_ONLY",
        application_version=application.lock_version,
        candidates=candidates,
    )
