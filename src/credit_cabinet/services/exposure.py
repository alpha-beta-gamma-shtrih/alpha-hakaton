"""Current demo commitments, derived from final terms; no ledger or repayment simulation."""

from decimal import Decimal

from sqlalchemy import select

from credit_cabinet.api.errors import APIError
from credit_cabinet.models import Application, ApplicationEvent, Decision
from credit_cabinet.services.policy import canonical_hash, money


def service_exposure(db, company_id, *, exclude_application_id=None):
    query = (
        select(Application.id, Application.status, Decision.id, Decision.monthly_payment)
        .outerjoin(Decision, Decision.application_id == Application.id)
        .where(
            Application.company_id == company_id,
            Application.status.in_(["APPROVED", "SIGNED"]),
            Application.archived_at.is_(None),
        )
        .order_by(Application.id)
    )
    if exclude_application_id is not None:
        query = query.where(Application.id != exclude_application_id)
    signed, reserved = Decimal(0), Decimal(0)
    signed_count, reserved_count, entries = 0, 0, []
    for app_id, status, decision_id, payment in db.execute(query):
        if decision_id is None or payment is None or payment <= 0:
            raise APIError(
                409, "EXPOSURE_DATA_INVALID", "Условия обязательств компании требуют проверки"
            )
        if status == "SIGNED":
            signed += payment
            signed_count += 1
        else:
            reserved += payment
            reserved_count += 1
        entries.append([str(app_id), status, str(decision_id), money(payment)])
    return {
        "signed_payment": money(signed),
        "reserved_payment": money(reserved),
        "signed_count": signed_count,
        "reserved_count": reserved_count,
        "basis_hash": canonical_hash(entries),
    }


def review_required(db, application, revision_id):
    if application.status != "MANUAL_REVIEW":
        return False
    details = db.scalar(
        select(ApplicationEvent.details)
        .where(
            ApplicationEvent.application_id == application.id,
            ApplicationEvent.revision_id == revision_id,
            ApplicationEvent.event_type == "PROCESSING_RETRIED",
        )
        .order_by(ApplicationEvent.sequence_no.desc())
        .limit(1)
    )
    return bool(details and details.get("reason_code") == "COMPANY_EXPOSURE_CHANGED")


def approvable(result, *, manual=True):
    return result is not None and (
        result.routing == "APPROVE"
        or (
            manual
            and result.routing == "MANUAL_REVIEW"
            and result.reason_codes[0] == "BORDERLINE_RISK"
            and result.risk_score is not None
            and 30 <= result.risk_score <= 59
        )
    )


def decision_exposure(db, application, assessment, decision):
    """Frozen decision-time obligations for explanations of already final terms."""
    if decision is not None:
        rows = db.scalars(
            select(ApplicationEvent.details)
            .where(
                ApplicationEvent.application_id == application.id,
                ApplicationEvent.event_type == "DECISION_MADE",
            )
            .order_by(ApplicationEvent.sequence_no.desc())
        )
        for details in rows:
            if details.get("decision_id") == str(decision.id) and "service_exposure" in details:
                return details["service_exposure"]
    return assessment.input_facts.get("service_exposure") if assessment else None


def company_summary(db, company_id, months):
    exposure = service_exposure(db, company_id)
    # Profile figures are historical client/demo data, not a fresh BKI request.
    reported = months[-1].existing_debt_payment if months else None
    current = reported + Decimal(exposure["signed_payment"]) if reported is not None else None
    return {
        **exposure,
        "reported_payment": reported,
        "current_payment": current,
        "committed_payment": current + Decimal(exposure["reserved_payment"])
        if current is not None
        else None,
    }
