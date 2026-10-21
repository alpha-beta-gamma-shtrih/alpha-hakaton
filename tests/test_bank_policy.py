from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from credit_cabinet.models import Application, ApplicationRevision, Assessment, CheckResult
from credit_cabinet.schemas.bank import ManualDecision, ManualInformationRequest
from credit_cabinet.services.bank_policy import bank_actions
from tests.bank_helpers import review_application
from tests.test_submissions import AlteredSources, ready, send


def actions(app, body):
    with app.state.session_factory() as db:
        application = db.get(Application, UUID(body["application"]["id"]))
        revision = db.get(ApplicationRevision, UUID(body["revision"]["id"]))
        assessment = (
            db.get(Assessment, UUID(body["assessment"]["id"])) if body["assessment"] else None
        )
        return bank_actions(db, application, revision, assessment)


def test_borderline_allows_only_three_manual_actions(seeded, client):
    body = review_application(client)
    assert body["assessment"]["risk_score"] == 40
    assert actions(seeded, body) == ["REQUEST_INFO", "APPROVE", "REJECT"]


def test_undefined_trend_allows_request_only(seeded, client):
    body = review_application(client, "zero_baseline")
    assert body["assessment"]["reasons"][0]["code"] == "TREND_BASELINE_ZERO"
    assert actions(seeded, body) == ["REQUEST_INFO"]


@pytest.mark.parametrize(
    "legal,errors",
    [({"is_bankrupt": None}, {}), ({}, {"BKI": "TIMEOUT"}), ({"inn": "0000000002"}, {})],
)
def test_technical_or_unconfirmed_facts_never_allow_final_decision(seeded, client, legal, errors):
    seeded.state.sources = AlteredSources(seeded.state.sources, legal=legal, errors=errors)
    body = send(client, ready(client)).json()
    assert actions(seeded, body) == ["RETRY_PROCESSING"]


def test_final_is_not_reopened(seeded, client):
    body = send(client, ready(client)).json()
    assert actions(seeded, body) == []


@pytest.mark.parametrize(
    "damage", ["missing_bki", "failed_fns", "unknown_bankruptcy", "score", "rules"]
)
def test_manual_actions_revalidate_saved_mandatory_checks(seeded, client, damage):
    body = review_application(client)
    with seeded.state.session_factory() as db:
        assessment = db.get(Assessment, UUID(body["assessment"]["id"]))
        check = db.scalar(
            select(CheckResult).where(
                CheckResult.assessment_id == assessment.id,
                CheckResult.source == ("BKI" if damage == "missing_bki" else "FNS"),
            )
        )
        if damage == "missing_bki":
            db.delete(check)
        elif damage == "failed_fns":
            check.status, check.normalized_data = "ERROR", None
        elif damage == "unknown_bankruptcy":
            check.normalized_data = {**check.normalized_data, "is_bankrupt": None}
        elif damage == "score":
            assessment.risk_score = 35
        else:
            assessment.rules_version = "unsupported"
        db.commit()
    assert actions(seeded, body) == []


@pytest.mark.parametrize(
    "fields",
    [
        [],
        ["role"],
        ["status"],
        ["company_id"],
        ["is_bankrupt"],
        ["draft_data.provenance"],
        ["draft_data.financial_months.2026-10-01.cash_inflow"],
        ["purpose_details", "purpose_details"],
    ],
)
def test_request_fields_are_known_editable_paths(fields):
    with pytest.raises(ValidationError):
        ManualInformationRequest(
            expected_version=1,
            message_to_client="Уточните назначение операционных расходов компании.",
            requested_fields=fields,
        )


@pytest.mark.parametrize("explanation", ["", "   ", "решил сотрудник"])
def test_manual_decision_requires_explanation(explanation):
    with pytest.raises(ValidationError):
        ManualDecision(expected_version=1, outcome="REJECTED", public_explanation=explanation)


def test_employee_cannot_assign_new_offer_terms():
    with pytest.raises(ValidationError):
        ManualDecision(
            expected_version=1,
            outcome="APPROVED",
            public_explanation="Подтверждены показатели и приемлемость риска по демо-политике.",
            approved_amount="5000000.00",
        )
