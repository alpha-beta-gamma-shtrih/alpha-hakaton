from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from credit_cabinet.models import Application, CreditProduct
from tests.conftest import SEED_PASSWORD, csrf_headers, login
from tests.test_drafts import patch
from tests.test_submissions import AlteredSources, ready, send


def approved(client):
    response = send(client, ready(client))
    assert response.status_code == 200, response.text
    app = response.json()["application"]
    assert app["status"] == "APPROVED"
    return app


def url(app):
    return f"/api/applications/{app['id']}/agreement"


def sign_body(app, document):
    return {
        "expected_version": app["version"],
        "decision_id": document["content"]["decision_id"],
        "content_sha256": document["content_sha256"],
        "accepted": True,
    }


def sign(client, app, body):
    return client.post(url(app) + "/sign", json=body, headers=csrf_headers(client))


def test_full_cycle_preserves_decision_snapshot_and_one_signature(seeded, client):
    app = approved(client)
    assert "SIGN_AGREEMENT" in app["allowed_actions"]
    decision = client.get(f"/api/applications/{app['id']}/decision").json()
    revision_url = f"/api/applications/{app['id']}/revisions/{app['latest_revision_no']}"
    revision = client.get(revision_url).json()
    before = client.get(f"/api/applications/{app['id']}/events").json()
    document = client.get(url(app)).json()
    assert document == client.get(url(app)).json()
    assert document["content"]["approved_amount"] == decision["approved_amount"]
    assert document["content"]["annual_rate_percent"] == decision["annual_rate_percent"]
    assert "имитирует" in document["content"]["notice"] and document["signature"] is None
    assert client.get(f"/api/applications/{app['id']}/events").json() == before
    body = sign_body(app, document)
    response = sign(client, app, body)
    assert response.status_code == 200, response.text
    signed = response.json()
    assert signed["status"] == "SIGNED" and signed["version"] == app["version"] + 1
    assert signed["allowed_actions"] == []
    assert signed["signature"]["method"] == "DEMO"
    assert signed["signature"]["content_sha256"] == document["content_sha256"]
    assert "signed_by_user_id" not in signed["signature"] and "content" not in signed["signature"]
    history = client.get(f"/api/applications/{app['id']}/events").json()["items"]
    assert len(history) == len(before["items"]) + 1
    assert history[-1]["event_type"] == "AGREEMENT_SIGNED"
    assert history[-1]["from_status"] == "APPROVED" and history[-1]["to_status"] == "SIGNED"
    assert sign(client, app, body).json() == signed  # lost response / double click
    assert len(client.get(f"/api/applications/{app['id']}/events").json()["items"]) == len(history)
    saved = client.get(url(app)).json()
    assert saved["content"] == document["content"] and saved["signature"] == signed["signature"]
    assert client.get(revision_url).json() == revision
    assert client.get(f"/api/applications/{app['id']}/decision").json() == decision
    assert patch(client, signed, requested_amount="900000.00").status_code == 409
    assert client.get("/api/auth/me").json()["user"]["ui_context"] == {"section": "applications"}
    assert login(client, "bank@example.com").status_code == 200
    card = client.get(f"/api/bank/applications/{app['id']}").json()
    assert (
        card["status"] == "SIGNED"
        and card["signature"] == signed["signature"]
        and card["allowed_actions"] == []
    )
    queue = client.get("/api/bank/applications?status=SIGNED").json()
    assert app["id"] in {row["id"] for row in queue["items"]}


@pytest.mark.parametrize(
    "case", ["version", "hash", "decision", "accepted", "extra", "string_bool"]
)
def test_signing_checks_exact_viewed_document_and_confirmation(seeded, client, case):
    app = approved(client)
    body = sign_body(app, client.get(url(app)).json())
    if case == "version":
        body["expected_version"] -= 1
    elif case == "hash":
        body["content_sha256"] = "a" * 64
    elif case == "decision":
        body["decision_id"] = str(uuid4())
    elif case == "accepted":
        body["accepted"] = False
    elif case == "extra":
        body["approved_amount"] = "1.00"
    else:
        body["accepted"] = "true"
    response = sign(client, app, body)
    assert response.status_code == (409 if case in {"version", "hash", "decision"} else 422), (
        response.text
    )
    assert client.get(f"/api/applications/{app['id']}").json() == app


def test_csrf_role_membership_and_anonymous_access(seeded, client):
    app = approved(client)
    body = sign_body(app, client.get(url(app)).json())
    assert client.post(url(app) + "/sign", json=body).status_code == 403
    assert login(client, "client2@example.com", SEED_PASSWORD).status_code == 200
    assert client.get(url(app)).status_code == 404
    assert sign(client, app, body).status_code == 404
    assert login(client, "bank@example.com").status_code == 200
    assert client.get(url(app)).status_code == 403 and sign(client, app, body).status_code == 403
    client.cookies.clear()
    assert client.get(url(app)).status_code == 401 and sign(client, app, body).status_code == 401


@pytest.mark.parametrize("state", ["draft", "reject", "needs_info", "manual"])
def test_only_final_approval_allows_signing(seeded, client, state):
    draft = ready(client)
    if state == "reject":
        seeded.state.sources = AlteredSources(
            seeded.state.sources, credit={"current_overdue_amount": "1.00"}
        )
    elif state == "needs_info":
        draft = patch(
            client,
            draft,
            draft_data={"financial_months": draft["draft_data"]["financial_months"][:-1]},
        ).json()
    elif state == "manual":
        seeded.state.sources = AlteredSources(seeded.state.sources, errors={"FNS": "TEST_ERROR"})
    app = draft if state == "draft" else send(client, draft).json()["application"]
    assert "SIGN_AGREEMENT" not in app["allowed_actions"]
    assert client.get(url(app)).status_code == 409
    assert (
        sign(
            client,
            app,
            {
                "expected_version": app["version"],
                "decision_id": str(uuid4()),
                "content_sha256": "a" * 64,
                "accepted": True,
            },
        ).status_code
        == 409
    )


def test_live_profile_product_changes_do_not_change_approved_document(seeded, client):
    app = approved(client)
    document = client.get(url(app)).json()
    with seeded.state.session_factory() as db:
        db.get(CreditProduct, UUID(app["product_id"])).annual_rate_percent = 99
        db.commit()
    assert client.get(url(app)).json() == document


def test_signed_record_rejects_direct_sql_rewrite(seeded, client):
    app = approved(client)
    document = client.get(url(app)).json()
    assert sign(client, app, sign_body(app, document)).status_code == 200
    with seeded.state.session_factory() as db:
        with pytest.raises(IntegrityError):
            db.execute(
                update(Application)
                .where(Application.id == UUID(app["id"]))
                .values(signing_record={"tampered": True})
            )
        db.rollback()
        record = db.scalar(
            select(Application.signing_record).where(Application.id == UUID(app["id"]))
        )
        assert record["content_sha256"] == document["content_sha256"]
