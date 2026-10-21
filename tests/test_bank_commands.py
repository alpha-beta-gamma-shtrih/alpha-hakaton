from copy import deepcopy
from decimal import Decimal
from uuid import UUID

import pytest

from credit_cabinet.models import Application, CreditProduct
from tests.bank_helpers import review_application
from tests.conftest import csrf_headers, login
from tests.test_drafts import patch
from tests.test_submissions import AlteredSources, counts, ready, send

EXPLANATION = "Показатели изучены, риск оценен в рамках демонстрационной политики."
QUESTION = "Уточните назначение расходов и подтвердите ожидаемые поступления компании."


def decision_body(version, outcome="APPROVED", **extra):
    return {
        "expected_version": version,
        "outcome": outcome,
        "public_explanation": EXPLANATION,
        **extra,
    }


def question_body(version, **extra):
    return {
        "expected_version": version,
        "message_to_client": QUESTION,
        "requested_fields": ["purpose_details", "draft_data.info_response"],
        **extra,
    }


def command(client, body, action, payload):
    return client.post(
        f"/api/bank/applications/{body['application']['id']}/{action}",
        json=payload,
        headers=csrf_headers(client),
    )


@pytest.mark.parametrize("outcome", ["APPROVED", "REJECTED"])
def test_manual_decision_is_atomic_bound_to_snapshot_and_public_private_separated(
    seeded, client, outcome, capsys
):
    submitted = review_application(client)
    frozen = deepcopy(submitted["revision"])
    login(client, email="bank@example.com")
    employee_id = client.get("/api/auth/me").json()["user"]["id"]
    before = client.get("/api/auth/me").json()["idle_expires_at"]
    # Current catalog terms do not replace terms of the submitted version.
    with seeded.state.session_factory() as db:
        product = db.get(CreditProduct, UUID(submitted["application"]["product_id"]))
        product.annual_rate_percent = Decimal("99.999")
        product.is_active = False
        db.commit()
    response = command(
        client,
        submitted,
        "decision",
        decision_body(
            submitted["application"]["version"], outcome, internal_comment="BANK-PRIVATE-NOTE-ONLY"
        ),
    )
    assert response.status_code == 200, response.text
    card = response.json()
    assert card["status"] == outcome and card["allowed_actions"] == []
    assert card["version"] > submitted["application"]["version"]
    assert card["revision"] == frozen
    decision = card["decision"]
    assert decision["source"] == "MANUAL" and decision["decided_by_user_id"] == employee_id
    assert decision["internal_comment"] == "BANK-PRIVATE-NOTE-ONLY"
    assert decision["public_explanation"] == EXPLANATION
    assert decision["reasons"][0]["code"] == (
        "MANUAL_APPROVED" if outcome == "APPROVED" else "MANUAL_REJECTED"
    )
    assert "BORDERLINE_RISK" not in str(decision["reasons"])
    if outcome == "APPROVED":
        assert (
            decision["approved_amount"] == "1000000.00" and decision["approved_term_months"] == 12
        )
        assert (
            decision["annual_rate_percent"] == "24.000"
            and decision["monthly_payment"] == "94559.60"
        )
    else:
        assert all(
            decision[field] is None
            for field in (
                "approved_amount",
                "approved_term_months",
                "annual_rate_percent",
                "monthly_payment",
            )
        )
    assert counts(seeded)["decisions"] == 1 and counts(seeded)["assessments"] == 1
    assert (
        card["assessment"]["risk_score"] == 40
    )  # Assessment is a recommendation, not the final decision.
    events = client.get(f"/api/bank/applications/{card['id']}/events").json()["items"]
    assert (
        events[-1]["event_type"] == "DECISION_MADE" and events[-1]["actor_user_id"] == employee_id
    )
    assert events[-1]["from_status"] == "MANUAL_REVIEW" and events[-1]["to_status"] == outcome
    assert "BANK-PRIVATE-NOTE-ONLY" not in str(events)
    assert client.get("/api/auth/me").json()["idle_expires_at"] >= before
    assert "BANK-PRIVATE-NOTE-ONLY" not in capsys.readouterr().out
    assert (
        command(client, submitted, "decision", decision_body(card["version"])).json()["code"]
        == "BANK_ACTION_NOT_ALLOWED"
    )
    assert (
        command(client, submitted, "request-info", question_body(card["version"])).status_code
        == 409
    )
    assert client.get("/api/bank/applications").json()["total"] == 0
    assert client.get(f"/api/bank/applications?status={outcome}").json()["total"] == 1
    login(client)
    for suffix in ("", "/decision", "/events", "/revisions/1"):
        result = client.get(f"/api/applications/{card['id']}{suffix}")
        assert result.status_code == 200, result.text
        assert "BANK-PRIVATE-NOTE-ONLY" not in result.text and "internal_comment" not in result.text
    assert "BANK-PRIVATE-NOTE-ONLY" not in client.get("/api/applications").text
    replay = send(
        client,
        {**submitted["application"], "version": frozen["source_lock_version"]},
        key=frozen["submission_key"],
    )
    assert replay.status_code == 200 and "BANK-PRIVATE-NOTE-ONLY" not in replay.text


def test_manual_request_client_answer_and_new_submission_preserve_history(seeded, client):
    submitted = review_application(client)
    frozen = deepcopy(submitted["revision"])
    login(client, email="bank@example.com")
    employee_id = client.get("/api/auth/me").json()["user"]["id"]
    response = command(
        client, submitted, "request-info", question_body(submitted["application"]["version"])
    )
    assert response.status_code == 200, response.text
    card = response.json()
    assert (
        card["status"] == "NEEDS_INFO"
        and card["decision"] is None
        and card["allowed_actions"] == []
    )
    request = card["open_information_request"]
    assert request["created_by_user_id"] == employee_id and request["revision_id"] == frozen["id"]
    assert request["message_to_client"] == QUESTION
    assert (
        command(client, submitted, "request-info", question_body(card["version"])).status_code
        == 409
    )
    assert counts(seeded)["information_requests"] == 1
    login(client)
    app = client.get(f"/api/applications/{card['id']}").json()
    assert app["open_information_request"]["message_to_client"] == QUESTION
    updated = patch(
        client,
        app,
        requested_amount="500000.00",
        term_months=24,
        purpose_details="Товар на сезон",
        draft_data={"info_response": "Параметры уточнены, сумма и срок изменены."},
    ).json()
    assert client.get(f"/api/applications/{card['id']}/revisions/1").json() == frozen
    result = send(client, updated)
    assert result.status_code == 200, result.text
    final = result.json()
    assert final["application"]["status"] == "APPROVED" and final["revision"]["revision_no"] == 2
    login(client, email="bank@example.com")
    bank_card = client.get(f"/api/bank/applications/{card['id']}").json()
    assert bank_card["open_information_request"] is None and len(bank_card["revisions"]) == 2
    assert bank_card["information_requests"][0]["status"] == "ANSWERED"
    assert bank_card["information_requests"][0]["answered_revision_id"] == final["revision"]["id"]
    assert (
        bank_card["information_requests"][0]["answer_text"]
        == "Параметры уточнены, сумма и срок изменены."
    )
    old = client.get(f"/api/bank/applications/{card['id']}/revisions/1").json()
    assert old["revision"] == frozen and old["assessments"][0]["risk_score"] == 40
    assert bank_card["decision"]["source"] == "AUTO"
    with seeded.state.session_factory() as db:
        assert db.get(Application, UUID(card["id"])).closed_at is not None


@pytest.mark.parametrize(
    "mode,legal,errors",
    [
        ("zero_baseline", {}, {}),
        (None, {"is_bankrupt": None}, {}),
        (None, {"is_bankrupt": True}, {}),
        (None, {}, {"BKI": "TIMEOUT"}),
    ],
)
def test_manual_decisions_cannot_bypass_unknown_technical_or_hard_limits(
    seeded, client, mode, legal, errors
):
    seeded.state.sources = AlteredSources(seeded.state.sources, legal=legal, errors=errors)
    submitted = review_application(client, mode) if mode else send(client, ready(client)).json()
    login(client, email="bank@example.com")
    before = counts(seeded)
    for outcome in ("APPROVED", "REJECTED"):
        response = command(
            client,
            submitted,
            "decision",
            decision_body(submitted["application"]["version"], outcome),
        )
        assert response.status_code == 409 and response.json()["code"] == "BANK_ACTION_NOT_ALLOWED"
    if mode:
        assert (
            command(
                client,
                submitted,
                "request-info",
                question_body(
                    submitted["application"]["version"],
                    requested_fields=["draft_data.financial_months"],
                ),
            ).status_code
            == 200
        )
    else:
        assert (
            command(
                client,
                submitted,
                "request-info",
                question_body(submitted["application"]["version"]),
            ).status_code
            == 409
        )
        assert counts(seeded) == before


def test_stale_employee_action_does_not_duplicate_request_or_decision(seeded, client):
    submitted = review_application(client)
    login(client, email="bank@example.com")
    initial_version = submitted["application"]["version"]
    assert (
        command(client, submitted, "request-info", question_body(initial_version)).status_code
        == 200
    )
    for action, body in (
        ("request-info", question_body(initial_version)),
        ("decision", decision_body(initial_version)),
    ):
        response = command(client, submitted, action, body)
        assert response.status_code == 409 and response.json()["code"] == "VERSION_CONFLICT"
    assert counts(seeded)["information_requests"] == 1 and counts(seeded)["decisions"] == 0


@pytest.mark.parametrize("action", ["decision", "request-info"])
def test_employee_commands_require_role_and_csrf(seeded, client, action):
    submitted = review_application(client)
    body = (
        decision_body(submitted["application"]["version"])
        if action == "decision"
        else question_body(submitted["application"]["version"])
    )
    assert command(client, submitted, action, body).status_code == 403
    login(client, email="bank@example.com")
    assert (
        client.post(
            f"/api/bank/applications/{submitted['application']['id']}/{action}", json=body
        ).status_code
        == 403
    )
    assert counts(seeded)["decisions"] == counts(seeded)["information_requests"] == 0


@pytest.mark.parametrize(
    "extra",
    [
        {"approved_amount": "5000000.00"},
        {"annual_rate_percent": "0.000"},
        {"revision_id": "any"},
        {"risk_score": 1},
        {"public_explanation": "решил сотрудник"},
        {"internal_comment": " "},
    ],
)
def test_decision_input_does_not_allow_offer_or_source_overrides(seeded, client, extra):
    submitted = review_application(client)
    login(client, email="bank@example.com")
    response = command(
        client, submitted, "decision", decision_body(submitted["application"]["version"], **extra)
    )
    assert response.status_code == 422
    assert counts(seeded)["decisions"] == 0


@pytest.mark.parametrize(
    "fields",
    [
        [],
        ["role"],
        ["draft_data.confirmations.credit_history_check_allowed"],
        ["purpose_details", "purpose_details"],
    ],
)
def test_request_input_rejects_unknown_or_duplicate_paths(seeded, client, fields):
    submitted = review_application(client)
    login(client, email="bank@example.com")
    response = command(
        client,
        submitted,
        "request-info",
        question_body(submitted["application"]["version"], requested_fields=fields),
    )
    assert response.status_code == 422 and counts(seeded)["information_requests"] == 0


@pytest.mark.parametrize("action", ["decision", "request-info"])
def test_command_rolls_back_result_status_and_event_if_session_activity_fails(
    seeded, client, action, monkeypatch
):
    from credit_cabinet.api.errors import APIError

    submitted = review_application(client)
    login(client, email="bank@example.com")
    old_card = client.get(f"/api/bank/applications/{submitted['application']['id']}").json()
    old_events = client.get(
        f"/api/bank/applications/{submitted['application']['id']}/events"
    ).json()

    def expired(*_args, **_kwargs):
        raise APIError(401, "AUTH_REQUIRED", "Требуется повторный вход")

    monkeypatch.setattr(seeded.state.auth, "activity", expired)
    payload = (
        decision_body(old_card["version"])
        if action == "decision"
        else question_body(old_card["version"])
    )
    assert command(client, submitted, action, payload).status_code == 401
    assert client.get(f"/api/bank/applications/{old_card['id']}").json() == old_card
    assert client.get(f"/api/bank/applications/{old_card['id']}/events").json() == old_events
    assert counts(seeded)["decisions"] == counts(seeded)["information_requests"] == 0
