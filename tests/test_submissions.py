from copy import deepcopy
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from credit_cabinet.core.security import utc_now
from credit_cabinet.models import (
    ApplicationRevision,
    Assessment,
    CheckResult,
    Company,
    CreditProduct,
    Decision,
    InformationRequest,
)
from credit_cabinet.services.policy import SourceResult
from tests.conftest import csrf_headers, login
from tests.test_drafts import C01, C02, SEED_PASSWORD, new_draft, patch


def ready(client, **fields):
    draft = new_draft(client)
    result = patch(
        client,
        draft,
        requested_amount="1000000.00",
        term_months=12,
        purpose_code="INVENTORY",
        draft_data={
            "confirmations": {"data_confirmed": True, "credit_history_check_allowed": True}
        },
        **fields,
    )
    assert result.status_code == 200, result.text
    return result.json()


def send(client, draft, *, key=None, version=None):
    return client.post(
        f"/api/applications/{draft['id']}/submit",
        json={
            "expected_version": draft["version"] if version is None else version,
            "submission_key": str(key or uuid4()),
        },
        headers=csrf_headers(client),
    )


class AlteredSources:
    def __init__(self, original, *, legal=None, credit=None, errors=None, crash=False):
        self.original = original
        self.legal = legal or {}
        self.credit = credit or {}
        self.errors = errors or {}
        self.calls = []
        self.crash = crash

    def check(self, inn, source, revision_no, run_no):
        self.calls.append((str(source), revision_no, run_no))
        if self.crash:
            raise RuntimeError("simulated processing interruption")
        result = self.original.check(inn, source, revision_no, run_no)
        if source in self.errors:
            now = utc_now()
            return SourceResult(
                source, "ERROR", None, self.errors[source], result.source_version, now, now
            )
        data = deepcopy(result.normalized_data)
        data.update(self.legal if source == "FNS" else self.credit)
        return SourceResult(
            result.source,
            result.status,
            data,
            result.error_code,
            result.source_version,
            result.started_at,
            result.completed_at,
        )


def counts(app):
    with app.state.session_factory() as db:
        return {
            model.__tablename__: db.scalar(select(func.count()).select_from(model))
            for model in (
                ApplicationRevision,
                Assessment,
                CheckResult,
                Decision,
                InformationRequest,
            )
        }


def test_c01_submit_persists_frozen_snapshot_checks_and_public_result(seeded, client):
    draft = ready(client, purpose_details="Frozen explanation")
    assert (
        client.get(f"/api/applications/{draft['id']}/decision").json()["code"]
        == "DECISION_NOT_FOUND"
    )
    response = send(client, draft)
    assert response.status_code == 200, response.text
    body = response.json()
    app, rev, assessment = body["application"], body["revision"], body["assessment"]
    assert app["status"] == "APPROVED" and app["allowed_actions"] == []
    assert assessment["risk_score"] == 10 and assessment["routing"] == "APPROVE"
    assert assessment["calculation_details"]["monthly_payment"] == "94559.60"
    assert app["decision"]["approved_amount"] == "1000000.00"
    assert app["decision"]["monthly_payment"] == "94559.60"
    assert client.get(f"/api/applications/{draft['id']}/decision").json() == app["decision"]
    assert "internal_comment" not in response.text and "password_hash" not in response.text
    assert rev["source_lock_version"] == draft["version"] and rev["revision_no"] == 1
    assert rev["financial_snapshot"]["purpose_details"] == "Frozen explanation"
    assert rev["financial_snapshot"]["confirmations"] == {
        "data_confirmed": True,
        "credit_history_check_allowed": True,
    }
    assert rev["financial_snapshot"]["provenance"]["credit_history"] is None
    assert rev["product_snapshot"]["policy_config"]["maximum_load_ratio"] == "0.80"
    assert {check["source"] for check in assessment["checks"]} == {"FNS", "BKI", "DATA_QUALITY"}
    assert assessment["provenance"]["credit_history"]["source"] == "MOCK_BKI"
    assert assessment["provenance"]["credit_history"]["checked_at"] is not None
    assert len(rev["input_hash"]) == 64
    assert client.get(f"/api/applications/{draft['id']}/revisions/1").json() == rev
    current = client.get(f"/api/applications/{draft['id']}").json()
    assert current["assessment"]["id"] == assessment["id"]
    assert patch(client, current, requested_amount="2000000.00").status_code == 409
    assert counts(seeded) == {
        "application_revisions": 1,
        "assessments": 1,
        "check_results": 3,
        "decisions": 1,
        "information_requests": 0,
    }
    events = client.get(f"/api/applications/{draft['id']}/events").json()["items"]
    assert [row["event_type"] for row in events] == [
        "DRAFT_CREATED",
        "SUBMITTED",
        "CHECKS_COMPLETED",
        "DECISION_MADE",
    ]


def test_submit_replay_precedes_version_and_status_checks(seeded, client):
    draft = ready(client)
    key = uuid4()
    first = send(client, draft, key=key)
    assert first.status_code == 200, first.text
    prior = counts(seeded)
    repeat = send(client, draft, key=key)
    assert repeat.status_code == 200 and repeat.json() == first.json()
    assert counts(seeded) == prior
    assert send(client, draft).json()["code"] == "VERSION_CONFLICT"
    conflict = send(client, draft, key=key, version=draft["version"] + 1)
    assert conflict.status_code == 409 and conflict.json()["code"] == "SUBMISSION_KEY_CONFLICT"


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("credit_history_check_allowed", False, "CREDIT_HISTORY_CONFIRMATION_REQUIRED"),
        ("data_confirmed", False, "DATA_CONFIRMATION_REQUIRED"),
    ],
)
def test_confirmation_error_has_field_path_and_no_side_effects(seeded, client, field, value, code):
    draft = ready(client)
    draft = patch(client, draft, draft_data={"confirmations": {field: value}}).json()
    adapter = AlteredSources(seeded.state.sources)
    seeded.state.sources = adapter
    response = send(client, draft)
    assert response.status_code == 422 and response.json()["code"] == code
    assert response.json()["field_errors"][0]["field"] == f"draft_data.confirmations.{field}"
    assert not adapter.calls and not any(counts(seeded).values())


@pytest.mark.parametrize(
    "fields",
    [
        {"requested_amount": None},
        {"requested_amount": "99999.99"},
        {"requested_amount": "5000000.01"},
        {"term_months": 5},
        {"term_months": 25},
        {"purpose_code": None},
    ],
)
def test_invalid_parameters_are_not_credit_rejections(seeded, client, fields):
    draft = ready(client)
    draft = patch(client, draft, **fields).json()
    response = send(client, draft)
    assert response.status_code == 422 and response.json()["field_errors"]
    assert not any(counts(seeded).values())


def test_inactive_or_changed_policy_stops_new_submission(seeded, client):
    draft = ready(client)
    with seeded.state.session_factory() as db:
        product = db.get(CreditProduct, UUID(draft["product_id"]))
        product.is_active = False
        db.commit()
    assert send(client, draft).json()["code"] == "PRODUCT_UNAVAILABLE"
    with seeded.state.session_factory() as db:
        product = db.get(CreditProduct, UUID(draft["product_id"]))
        product.is_active = True
        product.policy_config = {**product.policy_config, "maximum_load_ratio": "0.99"}
        db.commit()
    assert send(client, draft).json()["code"] == "POLICY_VERSION_UNSUPPORTED"
    assert not any(counts(seeded).values())


def test_c02_rejection_has_no_fabricated_score_or_offer(seeded, client):
    assert login(client, email="client2@example.com", password=SEED_PASSWORD).status_code == 200
    product = client.get("/api/products").json()["items"][0]["id"]
    draft = client.post(
        "/api/applications",
        json={"company_id": C02, "product_id": product},
        headers=csrf_headers(client),
    ).json()
    draft = patch(
        client,
        draft,
        requested_amount="2000000.00",
        term_months=12,
        purpose_code="INVENTORY",
        draft_data={
            "confirmations": {"data_confirmed": True, "credit_history_check_allowed": True}
        },
    ).json()
    response = send(client, draft)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["application"]["status"] == "REJECTED"
    assert body["assessment"]["risk_score"] is None and body["assessment"]["risk_band"] == "UNKNOWN"
    assert body["assessment"]["reasons"][0]["code"] == "DEBT_LOAD_LIMIT_EXCEEDED"
    assert body["application"]["decision"]["approved_amount"] is None


def test_needs_info_resubmission_keeps_old_snapshot_and_closes_request(seeded, client):
    draft = ready(client)
    original = deepcopy(draft["draft_data"]["financial_months"])
    draft = patch(
        client,
        draft,
        draft_data={"financial_months": [row for row in original if row["month"] != "2026-06-01"]},
    ).json()
    first = send(client, draft, key=uuid4()).json()
    assert first["application"]["status"] == "NEEDS_INFO", first
    assert first["application"]["decision"] is None
    assert client.get(f"/api/applications/{first['application']['id']}/decision").status_code == 404
    assert any(
        "2026-06-01" in field
        for field in first["application"]["open_information_request"]["requested_fields"]
    )
    frozen = deepcopy(first["revision"])
    # Changing the company profile does not rewrite the first snapshot.
    with seeded.state.session_factory() as db:
        company = db.get(Company, UUID(C01))
        company.business_description = "Later profile description"
        db.commit()
    updated = patch(
        client,
        first["application"],
        draft_data={"financial_months": original, "info_response": "Добавлен июнь"},
    ).json()
    assert updated["assessment"]["id"] == first["assessment"]["id"]
    assert client.get(f"/api/applications/{draft['id']}/revisions/1").json() == frozen
    second = send(client, updated)
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["application"]["status"] == "APPROVED" and body["revision"]["revision_no"] == 2
    assert body["revision"]["document_refs"] == frozen["document_refs"]
    assert body["revision"]["input_hash"] != frozen["input_hash"]
    assert body["application"]["open_information_request"] is None
    with seeded.state.session_factory() as db:
        request = db.scalar(select(InformationRequest))
        assert request.status == "ANSWERED" and request.answer_text == "Добавлен июнь"
        assert str(request.answered_revision_id) == body["revision"]["id"]
    assert client.get(f"/api/applications/{draft['id']}/revisions/1").json() == frozen


def test_snapshot_is_immutable_even_via_sql(seeded, client):
    body = send(client, ready(client)).json()
    with seeded.state.session_factory() as db:
        with pytest.raises(IntegrityError, match="immutable"):
            db.execute(
                text("UPDATE application_revisions SET financial_snapshot = '{}' WHERE id = :id"),
                {"id": UUID(body["revision"]["id"]).hex},
            )
        db.rollback()
    assert (
        client.get(f"/api/applications/{body['application']['id']}/revisions/1").json()
        == body["revision"]
    )


@pytest.mark.parametrize(
    "legal,credit,status,reason",
    [
        ({"is_bankrupt": True}, {}, "REJECTED", "COMPANY_BANKRUPTCY"),
        ({"is_bankrupt": None}, {}, "MANUAL_REVIEW", "LEGAL_STATUS_UNCONFIRMED"),
        ({}, {"current_overdue_amount": "1.00"}, "REJECTED", "CURRENT_OVERDUE"),
        ({}, {"max_overdue_days_12m": 60}, "REJECTED", "SEVERE_OVERDUE_HISTORY"),
        ({}, {"current_monthly_payment": "100000.00"}, "NEEDS_INFO", "DEBT_PAYMENT_MISMATCH"),
    ],
)
def test_priority_outcomes_through_api(seeded, client, legal, credit, status, reason):
    adapter = AlteredSources(seeded.state.sources, legal=legal, credit=credit)
    seeded.state.sources = adapter
    body = send(client, ready(client)).json()
    assert body["application"]["status"] == status, body
    assert body["assessment"]["reasons"][0]["code"] == reason
    assert body["assessment"]["risk_score"] is None
    if legal:
        assert [call[0] for call in adapter.calls] == ["FNS"]


def test_technical_failure_has_no_decision_and_bank_retry_uses_same_snapshot(seeded, client):
    original = seeded.state.sources
    adapter = AlteredSources(original, errors={"BKI": "TIMEOUT-private-fixture-error"})
    seeded.state.sources = adapter
    first = send(client, ready(client)).json()
    assert first["application"]["status"] == "MANUAL_REVIEW", first
    assert first["application"]["decision"] is None
    assert first["assessment"]["risk_score"] is None
    assert "TIMEOUT-private" not in str(first)
    with seeded.state.session_factory() as db:
        product = db.scalar(select(CreditProduct))
        product.is_active = False
        product.annual_rate_percent = Decimal("99.999")
        db.commit()
    endpoint = f"/api/bank/applications/{first['application']['id']}/retry-processing"
    assert (
        client.post(
            endpoint,
            json={"expected_version": first["application"]["version"]},
            headers=csrf_headers(client),
        ).status_code
        == 403
    )
    assert login(client, email="bank@example.com").status_code == 200
    seeded.state.sources = original
    response = client.post(
        endpoint,
        json={"expected_version": first["application"]["version"]},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "APPROVED" and body["assessment"]["run_no"] == 2
    assert body["revision_id"] == first["revision"]["id"]
    assert body["assessment"]["calculation_details"]["monthly_payment"] == "94559.60"
    assert counts(seeded)["application_revisions"] == 1 and counts(seeded)["assessments"] == 2
    assert (
        client.post(
            endpoint, json={"expected_version": body["version"]}, headers=csrf_headers(client)
        ).status_code
        == 409
    )


def test_processing_crash_keeps_durable_submitted_revision(seeded, client):
    original = seeded.state.sources
    seeded.state.sources = AlteredSources(original, crash=True)
    draft = ready(client)
    key = uuid4()
    response = send(client, draft, key=key)
    assert response.status_code == 500
    current = client.get(f"/api/applications/{draft['id']}").json()
    assert current["status"] == "SUBMITTED" and current["latest_revision_no"] == 1
    assert counts(seeded)["assessments"] == 0
    replay = send(client, draft, key=key)
    assert replay.status_code == 200 and replay.json()["assessment"] is None
    assert login(client, email="bank@example.com").status_code == 200
    seeded.state.sources = original
    response = client.post(
        f"/api/bank/applications/{draft['id']}/retry-processing",
        json={"expected_version": current["version"]},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "APPROVED"
    assert counts(seeded)["application_revisions"] == 1


def test_submit_and_snapshot_require_membership_role_and_csrf(seeded, client):
    draft = ready(client)
    body = {"expected_version": draft["version"], "submission_key": str(uuid4())}
    endpoint = f"/api/applications/{draft['id']}/submit"
    assert client.post(endpoint, json=body).status_code == 403
    assert login(client, email="client2@example.com", password=SEED_PASSWORD).status_code == 200
    assert client.post(endpoint, json=body, headers=csrf_headers(client)).status_code == 404
    assert client.get(f"/api/applications/{draft['id']}/revisions/1").status_code == 404
    assert login(client, email="bank@example.com").status_code == 200
    assert client.post(endpoint, json=body, headers=csrf_headers(client)).status_code == 403
    assert not any(counts(seeded).values())
