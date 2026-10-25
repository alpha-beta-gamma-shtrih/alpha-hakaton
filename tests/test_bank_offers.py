from copy import deepcopy
from decimal import Decimal
from uuid import UUID

import pytest

from credit_cabinet.models import CreditProduct
from tests.bank_helpers import review_application
from tests.conftest import csrf_headers, login
from tests.test_agreements import sign, sign_body, url
from tests.test_bank_commands import command, decision_body
from tests.test_personal_pricing_api import personal as personal
from tests.test_personal_pricing_api import prepared
from tests.test_submissions import AlteredSources, counts, send


def quote(client, app, **changes):
    return client.post(
        f"/api/bank/applications/{app['id']}/offer-preview",
        json={
            "expected_version": app["version"],
            "amount": "400000.00",
            "term_months": 24,
            **changes,
        },
        headers=csrf_headers(client),
    )


def offered(preview):
    return {
        "amount": preview["terms"]["amount"],
        "term_months": preview["terms"]["term_months"],
        "preview_hash": preview["preview_hash"],
    }


def test_offer_preview_approval_signature_and_frozen_original(seeded, client):
    submitted = review_application(client)
    app = submitted["application"]
    frozen = deepcopy(submitted["revision"])
    original = deepcopy(app["assessment"])
    login(client, "bank@example.com")
    before = counts(seeded)
    response = quote(client, app)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["can_approve"] and preview["terms"]["annual_rate_percent"] == "24.000"
    assert quote(client, app).json() == preview and counts(seeded) == before
    # No fixture request or live catalog change can affect the saved sources/product.
    seeded.state.sources = AlteredSources(
        seeded.state.sources, errors={"FNS": "TIMEOUT", "BKI": "TIMEOUT"}
    )
    with seeded.state.session_factory() as db:
        db.get(CreditProduct, UUID(app["product_id"])).annual_rate_percent = Decimal(99)
        db.commit()
    assert quote(client, app).json() == preview
    response = command(
        client,
        submitted,
        "decision",
        decision_body(app["version"], offer=offered(preview), internal_comment="BANK-ONLY-OFFER"),
    )
    assert response.status_code == 200, response.text
    card = response.json()
    assert card["revision"] == frozen and card["assessment"]["id"] == original["id"]
    decision = card["decision"]
    assert card["approved_amount"] == "400000.00" and card["terms_changed"] is True
    queued = client.get("/api/bank/applications?status=APPROVED").json()["items"][0]
    assert queued["requested_amount"] == "1000000.00" and queued["approved_term_months"] == 24
    assert decision["approved_amount"] == "400000.00" and decision["approved_term_months"] == 24
    assert decision["monthly_payment"] == preview["terms"]["monthly_payment"]
    assert decision["offer_risk_score"] == preview["risk_score"]
    assert counts(seeded)["assessments"] == before["assessments"]
    assert (
        command(
            client, submitted, "decision", decision_body(card["version"], offer=offered(preview))
        ).status_code
        == 409
    )
    login(client)
    saved = client.get(f"/api/applications/{app['id']}").json()
    assert saved["requested_amount"] == "1000000.00" and saved["term_months"] == 12
    assert saved["assessment"] == original
    assert saved["decision"]["offer"] == preview["terms"]
    assert "offer_risk_score" not in saved["decision"] and "BANK-ONLY-OFFER" not in str(saved)
    document = client.get(url(app)).json()
    assert document["content"]["approved_amount"] == "400000.00"
    assert document["content"]["term_months"] == 24
    assert sign(client, saved, sign_body(saved, document)).json()["status"] == "SIGNED"
    assert client.get(f"/api/applications/{app['id']}/revisions/1").json() == frozen


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"amount": "1100000.00"}, "OFFER_AMOUNT_INVALID"),
        ({"amount": "99999.99"}, "OFFER_AMOUNT_INVALID"),
        ({"term_months": 25}, "OFFER_TERM_INVALID"),
        ({"term_months": 5}, "OFFER_TERM_INVALID"),
        ({"amount": "1000000.00", "term_months": 12}, "OFFER_UNCHANGED"),
        ({"expected_version": 1}, "VERSION_CONFLICT"),
    ],
)
def test_offer_limits_and_stale_version(seeded, client, changes, code):
    app = review_application(client)["application"]
    login(client, "bank@example.com")
    response = quote(client, app, **changes)
    assert response.status_code in (409, 422) and response.json()["code"] == code


def test_blocked_preview_and_tampering_never_create_decision(seeded, client):
    submitted = review_application(client)
    app = submitted["application"]
    login(client, "bank@example.com")
    blocked = quote(client, app, amount="1000000.00", term_months=6).json()
    assert blocked["can_approve"] is False
    assert (
        command(
            client, submitted, "decision", decision_body(app["version"], offer=offered(blocked))
        ).json()["code"]
        == "OFFER_NOT_APPROVABLE"
    )
    preview = quote(client, app).json()
    changed = {**offered(preview), "amount": "300000.00"}
    assert (
        command(client, submitted, "decision", decision_body(app["version"], offer=changed)).json()[
            "code"
        ]
        == "OFFER_PREVIEW_CHANGED"
    )
    extra = {**offered(preview), "annual_rate_percent": "20.000"}
    assert (
        command(
            client, submitted, "decision", decision_body(app["version"], offer=extra)
        ).status_code
        == 422
    )
    assert (
        command(
            client,
            submitted,
            "decision",
            decision_body(app["version"], "REJECTED", offer=offered(preview)),
        ).status_code
        == 422
    )
    assert counts(seeded)["decisions"] == 0


def test_offer_auth_and_csrf(seeded, client):
    app = review_application(client)["application"]
    assert quote(client, app).status_code == 403
    login(client, "bank@example.com")
    assert (
        client.post(
            f"/api/bank/applications/{app['id']}/offer-preview",
            json={"expected_version": app["version"], "amount": "400000.00", "term_months": 24},
        ).status_code
        == 403
    )
    client.cookies.clear()
    assert quote(client, app).status_code == 401


@pytest.mark.parametrize(
    "source",
    [
        {"legal": {"is_bankrupt": None}},
        {"legal": {"is_bankrupt": True}},
        {"errors": {"BKI": "TIMEOUT"}},
    ],
)
def test_no_offer_overrides_source_or_legal_stops(seeded, client, source):
    seeded.state.sources = AlteredSources(seeded.state.sources, **source)
    from tests.test_submissions import ready

    app = send(client, ready(client)).json()["application"]
    login(client, "bank@example.com")
    assert quote(client, app).status_code == 409


def test_personal_rate_and_ai_use_approved_changed_terms(personal, client):
    draft = prepared(client, amount="2500000.00", term=12, purpose="OTHER", partner=False)
    submitted = send(client, draft).json()
    app = submitted["application"]
    assert app["status"] == "MANUAL_REVIEW"
    login(client, "bank@example.com")
    response = quote(client, app, amount="1500000.00", term_months=36)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["terms"]["annual_rate_percent"] == "21.500" and preview["risk_score"] == 0
    assert preview["terms"]["original_annual_rate_percent"] == "20.000"
    assert (
        command(
            client, submitted, "decision", decision_body(app["version"], offer=offered(preview))
        ).status_code
        == 200
    )
    login(client)
    saved = client.get(f"/api/applications/{app['id']}").json()
    from tests.test_advisor import explain

    report = explain(client, saved).json()
    assert report["is_current"] is True
    assert report["scenarios"][0]["requested_amount"] == "1500000.00"
    assert report["scenarios"][0]["term_months"] == 36
    assert report["scenarios"][0]["annual_rate_percent"] == "21.500"
    assert len(report["scenarios"]) == 1
