from copy import deepcopy
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from credit_cabinet.models import ApplicationRevision, Assessment, Decision
from tests.bank_helpers import review_application
from tests.conftest import csrf_headers, login
from tests.test_advisor import explain
from tests.test_agreement_decline import decline
from tests.test_agreements import approved, sign, sign_body, url
from tests.test_bank_commands import command, decision_body
from tests.test_bank_offers import offered, quote
from tests.test_scenario_sets import create_set
from tests.test_submissions import ready, send


def summary(client, app):
    response = client.get(f"/api/companies/{app['company_id']}")
    assert response.status_code == 200, response.text
    return response.json()["credit_exposure"]


def test_signed_and_reserved_payments_accumulate_and_refusal_releases_reserve(seeded, client):
    first = approved(client)
    payment = Decimal(first["decision"]["monthly_payment"])
    before = summary(client, first)
    assert before["reserved_payment"] == str(payment) and before["signed_payment"] == "0.00"
    document = client.get(url(first)).json()
    signed = sign(client, first, sign_body(first, document))
    assert signed.status_code == 200, signed.text
    after = summary(client, first)
    assert after["signed_payment"] == str(payment) and after["reserved_payment"] == "0.00"
    assert Decimal(after["current_payment"]) == Decimal(after["reported_payment"]) + payment
    second = approved(client)
    details = second["assessment"]["calculation_details"]
    assert details["base_existing_payment"] == "30000.00"
    assert Decimal(details["existing_payment"]) == Decimal("30000") + payment
    assert details["service_signed_payment"] == str(payment)
    assert details["service_reserved_payment"] == "0.00"
    assert "DEBT_PAYMENT_MISMATCH" not in {r["code"] for r in second["assessment"]["reasons"]}
    third = send(client, ready(client)).json()["application"]
    assert third["status"] == "REJECTED"
    assert third["assessment"]["reasons"][0]["code"] == "DEBT_LOAD_LIMIT_EXCEEDED"
    assert decline(client, second).status_code == 200
    released = summary(client, first)
    assert released["reserved_count"] == 0 and released["signed_count"] == 1
    fourth = approved(client)
    assert fourth["decision"] and summary(client, first)["reserved_count"] == 1
    # Historical financial rows and the original submitted/assessment snapshot stay unchanged.
    assert (
        client.get(f"/api/applications/{first['id']}").json()["assessment"] == first["assessment"]
    )


def test_unsigned_approvals_also_prevent_unlimited_loans(seeded, client):
    one, two = approved(client), approved(client)
    blocked = send(client, ready(client)).json()["application"]
    assert blocked["status"] == "REJECTED"
    exposure = summary(client, one)
    assert exposure["reserved_count"] == 2 and exposure["signed_count"] == 0
    assert Decimal(exposure["reserved_payment"]) == sum(
        Decimal(app["decision"]["monthly_payment"]) for app in (one, two)
    )


def test_pending_bank_decision_and_offer_preview_use_current_obligations(seeded, client):
    pending = review_application(client)
    login(client, "bank@example.com")
    old = quote(client, pending["application"]).json()
    assert old["can_approve"]
    login(client)
    new = approved(client)
    login(client, "bank@example.com")
    assert (
        command(
            client, pending, "decision", decision_body(pending["application"]["version"])
        ).status_code
        == 422
    )
    stale = command(
        client,
        pending,
        "decision",
        decision_body(pending["application"]["version"], offer=offered(old)),
    )
    assert stale.status_code == 409 and stale.json()["code"] == "OFFER_PREVIEW_CHANGED"
    current = quote(client, pending["application"]).json()
    assert not current["can_approve"] and current["preview_hash"] != old["preview_hash"]
    card = client.get(f"/api/bank/applications/{pending['application']['id']}").json()
    assert not card["current_credit_check"]["can_approve_original"]
    login(client)
    assert decline(client, new).status_code == 200
    login(client, "bank@example.com")
    refreshed = quote(client, pending["application"]).json()
    assert refreshed["can_approve"]
    assert (
        command(
            client,
            pending,
            "decision",
            decision_body(pending["application"]["version"], offer=offered(refreshed)),
        ).status_code
        == 200
    )


def test_legacy_overcommitment_blocks_signature_and_allows_bank_to_reconsider(seeded, client):
    other, pending = approved(client), approved(client)
    document = client.get(url(pending)).json()
    original = deepcopy(pending["decision"])
    with seeded.state.session_factory() as db:
        # Simulate an overcommitted portfolio created before this feature was deployed.
        db.get(Decision, UUID(other["decision"]["id"])).monthly_payment = Decimal("900000")
        frozen = db.get(ApplicationRevision, UUID(pending["latest_revision_id"])).input_hash
        db.commit()
    result = sign(client, pending, sign_body(pending, document))
    assert result.status_code == 409 and result.json()["code"] == "COMPANY_EXPOSURE_CHANGED"
    reopened = client.get(f"/api/applications/{pending['id']}").json()
    assert reopened["status"] == "MANUAL_REVIEW" and reopened["credit_review_required"]
    assert reopened["decision"] is None and reopened["signature"] is None
    assert summary(client, pending)["reserved_count"] == 1
    assert sign(client, pending, sign_body(pending, document)).status_code == 409
    login(client, "bank@example.com")
    history = client.get(f"/api/bank/applications/{pending['id']}/events").json()["items"]
    archived = next(row for row in history if "superseded_decision" in row["details"])
    assert archived["visibility"] == "BANK"
    assert archived["details"]["superseded_decision"]["id"] == original["id"]
    assert (
        archived["details"]["superseded_decision"]["monthly_payment"] == original["monthly_payment"]
    )
    assert (
        command(
            client, {"application": reopened}, "decision", decision_body(reopened["version"])
        ).status_code
        == 422
    )
    login(client)
    assert decline(client, other).status_code == 200
    login(client, "bank@example.com")
    response = command(
        client, {"application": reopened}, "decision", decision_body(reopened["version"])
    )
    assert response.status_code == 200, response.text
    assert response.json()["decision"]["id"] != original["id"]
    login(client)
    updated = client.get(f"/api/applications/{pending['id']}").json()
    assert not updated["credit_review_required"]
    assert sign(client, updated, sign_body(updated, document)).status_code == 409
    fresh = client.get(url(updated)).json()
    assert sign(client, updated, sign_body(updated, fresh)).status_code == 200
    with seeded.state.session_factory() as db:
        assert db.get(ApplicationRevision, UUID(pending["latest_revision_id"])).input_hash == frozen
        assert (
            len(
                list(
                    db.scalars(
                        select(Decision).where(Decision.application_id == UUID(pending["id"]))
                    )
                )
            )
            == 1
        )


def test_new_commitments_invalidate_saved_options_and_ai_cache(seeded, client):
    draft = ready(client)
    saved = create_set(client, draft).json()
    draft, options = saved["application"], saved["scenario_set"]
    report = explain(client, draft).json()
    assert report["is_current"]
    approved(client)
    fetched = client.get(f"/api/applications/{draft['id']}/scenario-set").json()
    assert not fetched["is_current"] and fetched["candidates"] == options["candidates"]
    selection = client.post(
        f"/api/applications/{draft['id']}/scenario-set/select",
        headers=csrf_headers(client),
        json={
            "expected_version": draft["version"],
            "scenario_set_id": options["id"],
            "candidate_id": "LOWER_AMOUNT",
        },
    )
    assert selection.status_code == 409
    cached = client.get(f"/api/applications/{draft['id']}/advisor").json()
    assert not cached["is_current"]


def test_existing_assessments_without_exposure_fields_still_allow_signing(seeded, client):
    app = approved(client)
    document = client.get(url(app)).json()
    with seeded.state.session_factory() as db:
        assessment = db.get(Assessment, UUID(app["assessment"]["id"]))
        facts, details = deepcopy(assessment.input_facts), deepcopy(assessment.calculation_details)
        facts.pop("service_exposure")
        for key in (
            "base_existing_payment",
            "service_signed_payment",
            "service_reserved_payment",
            "service_exposure",
        ):
            details.pop(key)
        assessment.input_facts, assessment.calculation_details = facts, details
        db.commit()
    response = sign(client, app, sign_body(app, document))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "SIGNED"


def test_ai_hash_uses_the_same_exposure_as_its_comparison(seeded, client, monkeypatch):
    from credit_cabinet.services import advisor

    other = approved(client)
    draft = ready(client)
    original, changed = advisor.basis_hash, False

    def after_comparison(db, application, **kwargs):
        nonlocal changed
        if kwargs.get("payload") is not None and not changed:
            # An external commitment changes between comparison and cache-key creation.
            with seeded.state.session_factory() as writer:
                writer.get(Decision, UUID(other["decision"]["id"])).monthly_payment = Decimal(
                    "100000"
                )
                writer.commit()
            changed = True
        return original(db, application, **kwargs)

    monkeypatch.setattr(advisor, "basis_hash", after_comparison)
    report = explain(client, draft)
    assert report.status_code == 200, report.text
    assert changed and not report.json()["is_current"]
