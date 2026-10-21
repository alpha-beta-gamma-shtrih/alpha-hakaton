"""Explicit public DTOs. No internal comments, technical errors or fixture payloads."""

from copy import deepcopy

from sqlalchemy import select

from credit_cabinet.models import (
    ApplicationRevision,
    Assessment,
    CheckResult,
    Decision,
    InformationRequest,
)
from credit_cabinet.models.enums import CheckSource, InfoStatus
from credit_cabinet.schemas.business import (
    AssessmentResponse,
    DecisionResponse,
    InformationRequestResponse,
)
from credit_cabinet.schemas.submissions import RevisionResponse
from credit_cabinet.services.reasons import public_reasons


def revision_view(revision):
    return RevisionResponse.model_validate(revision, from_attributes=True)


def assessment_view(db, assessment, revision):
    checks = list(
        db.scalars(
            select(CheckResult)
            .where(CheckResult.assessment_id == assessment.id)
            .order_by(CheckResult.source)
        )
    )
    provenance = {
        "company": deepcopy(revision.company_snapshot.get("provenance")),
        "financial_months": deepcopy(revision.financial_snapshot["provenance"]["financial_months"]),
        "credit_history": None,
    }
    for check in checks:
        if check.normalized_data and check.source in (CheckSource.FNS, CheckSource.BKI):
            provenance["company" if check.source == CheckSource.FNS else "credit_history"] = (
                check.normalized_data.get("provenance")
            )
    return AssessmentResponse(
        id=assessment.id,
        revision_id=assessment.revision_id,
        run_no=assessment.run_no,
        rules_version=assessment.rules_version,
        risk_score=assessment.risk_score,
        risk_band=assessment.risk_band,
        routing=assessment.routing,
        reasons=public_reasons(assessment.reason_codes),
        calculation_details=deepcopy(assessment.calculation_details),
        checks=[
            {
                "source": check.source,
                "status": check.status,
                "reasons": public_reasons(check.reason_codes),
                "source_version": check.source_version,
                "completed_at": check.completed_at,
            }
            for check in checks
        ],
        provenance=provenance,
        completed_at=assessment.completed_at,
    )


def decision_view(row):
    return DecisionResponse(
        id=row.id,
        revision_id=row.revision_id,
        assessment_id=row.assessment_id,
        outcome=row.outcome,
        source=row.source,
        approved_amount=row.approved_amount,
        approved_term_months=row.approved_term_months,
        annual_rate_percent=row.annual_rate_percent,
        monthly_payment=row.monthly_payment,
        reasons=public_reasons(row.reason_codes),
        public_explanation=row.public_explanation,
        policy_version=row.policy_version,
        created_at=row.created_at,
    )


def enrich_application(db, application, response):
    revision = db.scalar(
        select(ApplicationRevision)
        .where(ApplicationRevision.application_id == application.id)
        .order_by(ApplicationRevision.revision_no.desc())
        .limit(1)
    )
    if revision:
        response.latest_revision_id = revision.id
        response.latest_revision_no = revision.revision_no
        has_confirmation = (
            application.draft_data.get("confirmations", {}).get("credit_history_check_allowed")
            is True
        )
        assessment = (
            db.scalar(
                select(Assessment)
                .where(Assessment.revision_id == revision.id)
                .order_by(Assessment.run_no.desc())
                .limit(1)
            )
            if has_confirmation
            else None
        )
        # Current draft consent gates access to cached history as well as new calls.
        if (
            assessment
            and application.draft_data.get("confirmations", {}).get("credit_history_check_allowed")
            is True
        ):
            response.assessment = assessment_view(db, assessment, revision)
    decision = db.scalar(select(Decision).where(Decision.application_id == application.id))
    if decision:
        response.decision = decision_view(decision)
    pending = db.scalar(
        select(InformationRequest).where(
            InformationRequest.application_id == application.id,
            InformationRequest.status == InfoStatus.OPEN,
        )
    )
    if pending:
        response.open_information_request = InformationRequestResponse.model_validate(
            pending, from_attributes=True
        )
    return response
