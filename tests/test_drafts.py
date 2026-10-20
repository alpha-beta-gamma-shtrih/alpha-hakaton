from copy import deepcopy
from datetime import timedelta
from uuid import UUID, uuid4, uuid5

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from credit_cabinet.core.demo import DEMO_NAMESPACE
from credit_cabinet.core.security import utc_now
from credit_cabinet.main import create_app
from credit_cabinet.models import (
    Application,
    ApplicationEvent,
    AuthSession,
    CompanyMembership,
)
from credit_cabinet.services.seed import import_bundle, load_bundle
from tests.conftest import ROOT, csrf_headers, login

SEED_PASSWORD = "New-demo-password-only-26!"
C01 = str(uuid5(DEMO_NAMESPACE, "company:C01"))
C02 = str(uuid5(DEMO_NAMESPACE, "company:C02"))


@pytest.fixture
def seeded(app):
    with app.state.session_factory() as db:
        import_bundle(db, load_bundle(ROOT / "demo_data/demo_0_2"), SEED_PASSWORD)
    return app


def new_draft(client):
    assert login(client).status_code == 200
    product_id = client.get("/api/products").json()["items"][0]["id"]
    response = client.post(
        "/api/applications",
        json={"company_id": C01, "product_id": product_id},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


def patch(client, draft, **fields):
    return client.patch(
        f"/api/applications/{draft['id']}",
        json={"expected_version": draft["version"], **fields},
        headers=csrf_headers(client),
    )


def test_company_catalog_and_product_contract(seeded, client):
    login(client)
    companies = client.get("/api/companies").json()
    assert companies["total"] == 1 and companies["items"][0]["id"] == C01
    detail = client.get(f"/api/companies/{C01}").json()
    assert len(detail["financial_months"]) == 6
    assert detail["financial_months"][0]["cash_inflow"] == "1200000.00"
    assert detail["provenance"]["credit_history"] is None
    assert "is_bankrupt" not in detail
    products = client.get("/api/products").json()["items"]
    assert len(products) == 1
    assert products[0]["annual_rate_percent"] == "24.000"
    assert products[0]["min_amount"] == "100000.00"
    assert products[0]["currency"] == "RUB"


def test_create_prefills_without_confirmation_or_evaluation(seeded, client):
    draft = new_draft(client)
    assert draft["version"] == 1 and draft["status"] == "DRAFT"
    assert draft["requested_amount"] is None and draft["ui_step"] == "NEED"
    assert draft["draft_data"]["confirmations"] == {
        "data_confirmed": False,
        "credit_history_check_allowed": False,
    }
    assert len(draft["draft_data"]["financial_months"]) == 6
    assert draft["provenance"]["credit_history"] is None
    assert draft["allowed_actions"] == ["EDIT_DRAFT"]
    assert draft["decision"] is None and draft["open_information_request"] is None
    context = client.get("/api/auth/me").json()["user"]["ui_context"]
    assert context == {
        "section": "applications",
        "last_application_id": draft["id"],
        "step": "NEED",
    }
    events = client.get(f"/api/applications/{draft['id']}/events").json()["items"]
    assert len(events) == 1 and events[0]["event_type"] == "DRAFT_CREATED"
    with seeded.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Application)) == 1
        assert db.scalar(select(func.count()).select_from(ApplicationEvent)) == 1


def test_partial_save_clear_and_conflict(seeded, client):
    draft = new_draft(client)
    response = patch(
        client,
        draft,
        requested_amount="1000000.00",
        term_months=12,
        purpose_code="INVENTORY",
        purpose_details="Поставка",
        ui_step="FINANCES",
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["version"] == 2 and updated["requested_amount"] == "1000000.00"
    assert updated["purpose_details"] == "Поставка"
    assert patch(client, draft, requested_amount="1500000.00").status_code == 409
    assert client.get(f"/api/applications/{draft['id']}").json()["requested_amount"] == "1000000.00"
    cleared = patch(client, updated, purpose_details=None).json()
    assert cleared["version"] == 3 and cleared["purpose_details"] is None
    assert cleared["term_months"] == 12 and cleared["requested_amount"] == "1000000.00"
    assert client.get("/api/applications").json()["items"][0]["id"] == draft["id"]


def test_financial_replacement_and_confirmations_merge(seeded, client):
    draft = new_draft(client)
    first = patch(client, draft, draft_data={"confirmations": {"data_confirmed": True}}).json()
    changed = patch(
        client,
        first,
        draft_data={
            "financial_months": [
                {
                    "month": "2026-09-01",
                    "cash_inflow": "20.00",
                    "operating_outflow": None,
                    "existing_debt_payment": "0.00",
                }
            ],
            "confirmations": {"credit_history_check_allowed": True},
        },
    ).json()
    assert len(changed["draft_data"]["financial_months"]) == 1
    assert changed["draft_data"]["financial_months"][0]["operating_outflow"] is None
    assert changed["draft_data"]["confirmations"] == {
        "data_confirmed": True,
        "credit_history_check_allowed": True,
    }
    assert changed["provenance"]["financial_months"]["source"] == "CLIENT_DECLARED"
    assert changed["provenance"]["credit_history"] is None
    profile = client.get(f"/api/companies/{C01}").json()
    assert len(profile["financial_months"]) == 6
    assert profile["financial_months"][0]["cash_inflow"] == "1200000.00"
    assert profile["provenance"]["financial_months"]["source"] == "DEMO_PROFILE"
    empty = patch(client, changed, draft_data={"financial_months": []}).json()
    assert empty["draft_data"]["financial_months"] == []


def test_other_client_and_staff_do_not_read_drafts(seeded, client):
    draft = new_draft(client)
    product_id = draft["product_id"]
    assert client.get(f"/api/companies/{C02}").status_code == 404
    assert client.get(f"/api/companies/{uuid4()}").status_code == 404
    assert (
        client.post(
            "/api/applications",
            headers=csrf_headers(client),
            json={"company_id": C02, "product_id": product_id},
        ).status_code
        == 404
    )
    assert login(client, "client2@example.com", SEED_PASSWORD).status_code == 200
    assert client.get("/api/companies").json()["items"][0]["id"] == C02
    assert client.get("/api/applications").json()["total"] == 0
    assert client.get(f"/api/applications/{draft['id']}").status_code == 404
    assert client.get(f"/api/applications/{draft['id']}/events").status_code == 404
    assert patch(client, draft, purpose_details="Forbidden").status_code == 404
    assert client.get(f"/api/applications?company_id={C01}").status_code == 404
    assert login(client, "bank@example.com").status_code == 200
    for url in [
        "/api/companies",
        "/api/products",
        "/api/applications",
        f"/api/applications/{draft['id']}",
    ]:
        assert client.get(url).status_code == 403


def test_membership_revocation_invalidates_access_and_recovery(seeded, client):
    draft = new_draft(client)
    with seeded.state.session_factory() as db:
        membership = db.scalar(
            select(CompanyMembership).where(CompanyMembership.company_id == UUID(C01))
        )
        db.delete(membership)
        db.commit()
    assert client.get(f"/api/applications/{draft['id']}").status_code == 404
    assert client.get("/api/auth/me").json()["user"]["ui_context"] == {"section": "overview"}


def test_restart_preserves_data_and_context(seeded, client, settings):
    draft = new_draft(client)
    response = patch(client, draft, requested_amount="1000000.00", ui_step="FINANCES")
    token = client.cookies.get("credit_session")
    with TestClient(create_app(settings)) as restarted:
        restarted.cookies.set("credit_session", token)
        restored = restarted.get(f"/api/applications/{draft['id']}").json()
        assert restored["version"] == response.json()["version"]
        assert restored["requested_amount"] == "1000000.00"
        assert restarted.get("/api/auth/me").json()["user"]["ui_context"]["step"] == "FINANCES"


def test_writes_refresh_idle_but_reads_do_not(seeded, client, monkeypatch):
    draft = new_draft(client)
    with seeded.state.session_factory() as db:
        session = db.scalar(select(AuthSession).where(AuthSession.revoked_at.is_(None)))
        before = session.idle_expires_at
    later = utc_now() + timedelta(minutes=10)
    monkeypatch.setattr("credit_cabinet.services.auth.utc_now", lambda: later)
    assert client.get(f"/api/applications/{draft['id']}").status_code == 200
    with seeded.state.session_factory() as db:
        assert (
            db.scalar(select(AuthSession).where(AuthSession.revoked_at.is_(None))).idle_expires_at
            == before
        )
    assert patch(client, draft, ui_step="COMPANY").status_code == 200
    with seeded.state.session_factory() as db:
        assert (
            db.scalar(select(AuthSession).where(AuthSession.revoked_at.is_(None))).idle_expires_at
            > before
        )


@pytest.mark.parametrize(
    "fields",
    [
        {"status": "APPROVED"},
        {"company_id": C02},
        {"product_id": str(uuid4())},
        {"risk_score": 0},
        {"provenance": {}},
        {"draft_data": {"is_bankrupt": False}},
        {"draft_data": {"provenance": {}}},
        {"requested_amount": 1000000},
        {"requested_amount": "1.001"},
        {"requested_amount": "NaN"},
        {"requested_amount": "-1.00"},
        {"requested_amount": "0.00"},
        {"term_months": True},
        {"term_months": "12"},
        {"term_months": 0},
        {"draft_data": None},
        {"ui_step": None},
        {"draft_data": {"confirmations": {"data_confirmed": "true"}}},
        {"draft_data": {"confirmations": {"credit_history_check_allowed": None}}},
        {"draft_data": {"financial_months": None}},
        {"draft_data": {"financial_months": [{"month": "2026-10-01"}]}},
        {"draft_data": {"financial_months": [{"month": "2026-09-01"}, {"month": "2026-09-01"}]}},
        {"draft_data": {"financial_months": [{"month": "2026-09-01", "cash_inflow": "-0.01"}]}},
    ],
)
def test_invalid_patch_is_rejected_atomically(seeded, client, fields):
    draft = new_draft(client)
    response = patch(client, draft, **deepcopy(fields))
    assert response.status_code == 422, response.text
    assert response.json()["field_errors"]
    restored = client.get(f"/api/applications/{draft['id']}").json()
    assert restored["version"] == 1
    assert restored["draft_data"]["confirmations"]["credit_history_check_allowed"] is False


def test_csrf_required_on_writes_and_pagination_bounded(seeded, client):
    draft = new_draft(client)
    assert (
        client.patch(
            f"/api/applications/{draft['id']}",
            json={
                "expected_version": 1,
                "ui_step": "REVIEW",
            },
        ).status_code
        == 403
    )
    assert client.get("/api/applications?limit=101").status_code == 422
    assert client.get("/api/companies?offset=-1").status_code == 422
    assert client.get("/api/applications?limit=1&offset=1").json()["items"] == []


def test_no_edit_after_status_change_and_no_events_per_keystroke(seeded, client):
    draft = new_draft(client)
    current = patch(client, draft, purpose_details="a").json()
    current = patch(client, current, purpose_details="ab").json()
    assert len(client.get(f"/api/applications/{draft['id']}/events").json()["items"]) == 1
    with seeded.state.session_factory() as db:
        row = db.get(Application, UUID(draft["id"]))
        row.status = "SUBMITTED"
        db.commit()
    assert patch(client, current, purpose_details="abc").status_code == 409
    assert client.get(f"/api/applications/{draft['id']}").json()["allowed_actions"] == []
