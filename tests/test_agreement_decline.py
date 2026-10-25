from uuid import UUID, uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from credit_cabinet.models import Application
from tests.conftest import SEED_PASSWORD, csrf_headers, login
from tests.test_agreements import approved, sign, sign_body, url
from tests.test_drafts import patch
from tests.test_submissions import ready


def decline_body(app):
    return {"expected_version": app["version"], "decision_id": app["decision"]["id"]}


def decline(client, app, body=None):
    return client.post(
        url(app) + "/decline", json=body or decline_body(app), headers=csrf_headers(client)
    )


def test_decline_closes_application_preserves_bank_decision_and_is_idempotent(seeded, client):
    app = approved(client)
    document = client.get(url(app)).json()
    revision_url = f"/api/applications/{app['id']}/revisions/1"
    revision = client.get(revision_url).json()
    assert "DECLINE_AGREEMENT" in app["allowed_actions"]
    response = decline(client, app)
    assert response.status_code == 200, response.text
    refused = response.json()
    assert refused["status"] == "REJECTED" and refused["version"] == app["version"] + 1
    assert refused["decline"]["decision_id"] == app["decision"]["id"]
    assert "declined_by_user_id" not in refused["decline"]
    assert refused["decision"] == app["decision"]
    assert refused["signature"] is None and refused["allowed_actions"] == []
    assert client.get(revision_url).json() == revision
    assert decline(client, app).json() == refused
    history = client.get(f"/api/applications/{app['id']}/events").json()["items"]
    events = [row for row in history if row["event_type"] == "AGREEMENT_DECLINED"]
    assert len(events) == 1
    assert events[0]["from_status"] == "APPROVED" and events[0]["to_status"] == "REJECTED"
    assert client.get(url(app)).status_code == 409
    assert sign(client, app, sign_body(app, document)).status_code == 409
    assert patch(client, refused, requested_amount="900000.00").status_code == 409
    assert client.get(f"/api/companies/{app['company_id']}/agreements").json()["items"] == []
    assert login(client, "bank@example.com").status_code == 200
    card = client.get(f"/api/bank/applications/{app['id']}").json()
    assert card["decline"] == refused["decline"] and card["allowed_actions"] == []
    assert card["status"] == "REJECTED" and card["decision"]["outcome"] == "APPROVED"
    queue = client.get("/api/bank/applications?status=REJECTED").json()
    assert app["id"] in {row["id"] for row in queue["items"]}
    with seeded.state.session_factory() as db:
        with pytest.raises(IntegrityError):
            db.execute(
                update(Application)
                .where(Application.id == UUID(app["id"]))
                .values(decline_record=None)
            )
        db.rollback()


@pytest.mark.parametrize("case", ["version", "decision", "extra", "type"])
def test_decline_validates_current_offer_without_changes_on_error(seeded, client, case):
    app = approved(client)
    body = decline_body(app)
    if case == "version":
        body["expected_version"] -= 1
    elif case == "decision":
        body["decision_id"] = str(uuid4())
    elif case == "extra":
        body["approved_amount"] = "1.00"
    else:
        body["expected_version"] = True
    response = decline(client, app, body)
    assert response.status_code == (409 if case in ("version", "decision") else 422)
    assert client.get(f"/api/applications/{app['id']}").json() == app


def test_decline_checks_csrf_role_and_company_membership(seeded, client):
    app = approved(client)
    assert client.post(url(app) + "/decline", json=decline_body(app)).status_code == 403
    assert login(client, "client2@example.com", SEED_PASSWORD).status_code == 200
    assert decline(client, app).status_code == 404
    assert login(client, "bank@example.com").status_code == 200
    assert decline(client, app).status_code == 403
    client.cookies.clear()
    assert client.post(url(app) + "/decline", json=decline_body(app)).status_code == 401


def test_signed_and_draft_applications_cannot_be_declined(seeded, client):
    draft = ready(client)
    assert (
        decline(
            client, draft, {"expected_version": draft["version"], "decision_id": str(uuid4())}
        ).status_code
        == 409
    )
    app = approved(client)
    document = client.get(url(app)).json()
    signed = sign(client, app, sign_body(app, document)).json()
    assert decline(client, app).status_code == 409
    assert client.get(f"/api/applications/{app['id']}").json() == signed
