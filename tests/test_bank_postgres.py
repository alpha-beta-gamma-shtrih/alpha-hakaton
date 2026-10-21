"""Bank command races and restart, isolated in a disposable PostgreSQL schema."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from credit_cabinet.api.errors import APIError
from credit_cabinet.models import ApplicationEvent, Decision, InformationRequest
from credit_cabinet.schemas.bank import ManualDecision, ManualInformationRequest
from credit_cabinet.services.bank_commands import decide, request_information
from tests.conftest import SEED_PASSWORD, csrf_headers, login
from tests.test_bank_commands import EXPLANATION, QUESTION
from tests.test_drafts_postgres import create
from tests.test_drafts_postgres import postgres_app as postgres_app

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="PostgreSQL URL required"
)


def submitted_for_review(client):
    draft = create(client)
    months = draft["draft_data"]["financial_months"]
    for row in months:
        row["cash_inflow"] = "1020000.00"
    response = client.patch(
        f"/api/applications/{draft['id']}",
        json={
            "expected_version": 1,
            "requested_amount": "1000000.00",
            "term_months": 12,
            "purpose_code": "INVENTORY",
            "draft_data": {
                "financial_months": months,
                "confirmations": {"data_confirmed": True, "credit_history_check_allowed": True},
            },
        },
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    response = client.post(
        f"/api/applications/{draft['id']}/submit",
        json={"expected_version": response.json()["version"], "submission_key": str(uuid4())},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["application"]["status"] == "MANUAL_REVIEW"
    return body


@pytest.mark.parametrize(
    "actions",
    [("APPROVED", "REJECTED"), ("REQUEST_INFO", "APPROVED"), ("REQUEST_INFO", "REQUEST_INFO")],
)
def test_two_employees_cannot_both_change_one_version(postgres_app, actions):
    with postgres_app() as first, postgres_app() as second:
        submitted = submitted_for_review(first)
        assert login(first, email="bank@example.com", password=SEED_PASSWORD).status_code == 200
        assert login(second, email="bank2@example.com", password=SEED_PASSWORD).status_code == 200
        cookies = [first.cookies.get("credit_session"), second.cookies.get("credit_session")]
        employee_ids = {
            first.get("/api/auth/me").json()["user"]["id"],
            second.get("/api/auth/me").json()["user"]["id"],
        }
        factory = first.app.state.session_factory
        auth = first.app.state.auth
        barrier = Barrier(2)

        def writer(item):
            cookie, action = item
            with factory() as db:
                principal = auth.authenticate(db, cookie)
                assert principal is not None
                barrier.wait(timeout=10)
                try:
                    if action == "REQUEST_INFO":
                        body = ManualInformationRequest(
                            expected_version=submitted["application"]["version"],
                            message_to_client=QUESTION,
                            requested_fields=["purpose_details"],
                        )
                        application, _revision = request_information(
                            db, principal, UUID(submitted["application"]["id"]), body, auth
                        )
                    else:
                        body = ManualDecision(
                            expected_version=submitted["application"]["version"],
                            outcome=action,
                            public_explanation=EXPLANATION,
                        )
                        application, _revision = decide(
                            db, principal, UUID(submitted["application"]["id"]), body, auth
                        )
                    return 200, application.status.value
                except APIError as exc:
                    return exc.status_code, exc.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(writer, zip(cookies, actions, strict=True)))
        assert sorted(status for status, _value in outcomes) == [200, 409]
        assert next(value for status, value in outcomes if status == 409) == "VERSION_CONFLICT"
        card = first.get(f"/api/bank/applications/{submitted['application']['id']}").json()
        with factory() as db:
            decisions = db.scalar(select(func.count()).select_from(Decision))
            requests = db.scalar(select(func.count()).select_from(InformationRequest))
            assert decisions + requests == 1
            records = list(
                db.scalars(
                    select(ApplicationEvent)
                    .where(ApplicationEvent.application_id == UUID(card["id"]))
                    .order_by(ApplicationEvent.sequence_no)
                )
            )
            assert len(records) == 4 and [row.sequence_no for row in records] == [1, 2, 3, 4]
            assert str(records[-1].actor_user_id) in employee_ids
        assert card["status"] == next(value for status, value in outcomes if status == 200)


def test_bank_decision_and_private_comment_survive_restart(postgres_app):
    with postgres_app() as client:
        submitted = submitted_for_review(client)
        login(client, email="bank@example.com", password=SEED_PASSWORD)
        response = client.post(
            f"/api/bank/applications/{submitted['application']['id']}/decision",
            json={
                "expected_version": submitted["application"]["version"],
                "outcome": "REJECTED",
                "public_explanation": EXPLANATION,
                "internal_comment": "BANK-PRIVATE-RESTART",
            },
            headers=csrf_headers(client),
        )
        assert response.status_code == 200, response.text
        card = response.json()
        cookies = dict(client.cookies)
    with postgres_app() as restarted:
        restarted.cookies.update(cookies)
        assert restarted.get(f"/api/bank/applications/{card['id']}").json() == card
        login(restarted, password=SEED_PASSWORD)
        public = restarted.get(f"/api/applications/{card['id']}")
        assert public.json()["decision"]["source"] == "MANUAL"
        assert "BANK-PRIVATE-RESTART" not in public.text
