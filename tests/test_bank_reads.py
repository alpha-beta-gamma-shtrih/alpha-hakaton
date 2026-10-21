from copy import deepcopy
from uuid import UUID, uuid4

import pytest

from credit_cabinet.models import Company
from tests.bank_helpers import review_application
from tests.conftest import login
from tests.test_drafts import C01, SEED_PASSWORD, new_draft, patch
from tests.test_submissions import AlteredSources, counts, ready, send


def test_queue_filters_paginates_and_excludes_unsubmitted_and_final_by_default(seeded, client):
    first = review_application(client)
    second = review_application(client)
    final = send(client, ready(client)).json()
    unsubmitted = new_draft(client)
    login(client, email="bank@example.com")
    result = client.get("/api/bank/applications?limit=1").json()
    assert result["total"] == 2 and result["limit"] == 1 and result["offset"] == 0
    assert result["items"][0]["id"] == first["application"]["id"]
    assert result["items"][0]["requested_amount"] == "1000000.00"
    assert result["items"][0]["allowed_actions"] == ["REQUEST_INFO", "APPROVE", "REJECT"]
    next_page = client.get("/api/bank/applications?limit=1&offset=1").json()
    assert next_page["items"][0]["id"] == second["application"]["id"]
    completed = client.get("/api/bank/applications?status=APPROVED").json()
    assert completed["total"] == 1 and completed["items"][0]["id"] == final["application"]["id"]
    combined = client.get("/api/bank/applications?status=APPROVED&status=MANUAL_REVIEW").json()
    assert combined["total"] == 3
    assert unsubmitted["id"] not in str(combined)
    assert client.get(f"/api/bank/applications?company_id={C01}").json()["total"] == 2
    assert client.get(f"/api/bank/applications?company_id={uuid4()}").json()["total"] == 0


def test_bank_card_and_history_use_saved_checks_without_new_calls(seeded, client):
    submitted = review_application(client)
    login(client, email="bank@example.com")
    adapter = AlteredSources(seeded.state.sources, crash=True)
    seeded.state.sources = adapter
    before = counts(seeded)
    response = client.get(f"/api/bank/applications/{submitted['application']['id']}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["revision"] == submitted["revision"]
    assert body["assessment"]["id"] == submitted["assessment"]["id"]
    credit = next(row for row in body["assessment"]["checks"] if row["source"] == "BKI")
    assert credit["normalized_data"]["current_monthly_payment"] == "30000.00"
    assert body["revisions"][0]["revision_no"] == 1
    assert body["decision"] is body["open_information_request"] is None
    historical = client.get(f"/api/bank/applications/{body['id']}/revisions/1").json()
    assert historical["revision"] == submitted["revision"] and len(historical["assessments"]) == 1
    events = client.get(f"/api/bank/applications/{body['id']}/events").json()["items"]
    assert [row["sequence_no"] for row in events] == list(range(1, len(events) + 1))
    assert events[1]["actor_user_id"] == body["revision"]["submitted_by_user_id"]
    assert counts(seeded) == before and not adapter.calls


def test_bank_never_sees_unsent_finances_explanations_or_live_profile(seeded, client):
    draft = ready(client)
    months = deepcopy(draft["draft_data"]["financial_months"])
    draft = patch(client, draft, draft_data={"financial_months": months[:5]}).json()
    submitted = send(client, draft).json()
    assert submitted["application"]["status"] == "NEEDS_INFO"
    changed = patch(
        client,
        submitted["application"],
        requested_amount="2500000.00",
        purpose_details="UNSENT PURPOSE",
        draft_data={
            "financial_months": months,
            "info_response": "UNSENT ANSWER",
            "confirmations": {"credit_history_check_allowed": False},
        },
    ).json()
    with seeded.state.session_factory() as db:
        company = db.get(Company, UUID(C01))
        company.legal_name = "UNSENT COMPANY"
        db.commit()
    login(client, email="bank@example.com")
    response = client.get(f"/api/bank/applications/{draft['id']}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert "UNSENT" not in response.text
    assert body["version"] == changed["version"]
    assert body["requested_amount"] == "1000000.00"
    assert len(body["revision"]["financial_snapshot"]["financial_months"]) == 5
    assert body["open_information_request"]["answer_text"] is None
    assert body["assessment"] is not None  # Uses confirmation of the submitted version.
    assert body["allowed_actions"] == []
    queue = client.get("/api/bank/applications").json()
    assert "UNSENT" not in str(queue) and queue["items"][0]["requested_amount"] == "1000000.00"


def test_draft_and_missing_application_are_indistinguishable_to_bank(seeded, client):
    draft = new_draft(client)
    login(client, email="bank@example.com")
    for application_id in (draft["id"], str(uuid4())):
        for suffix in ("", "/events", "/revisions/1"):
            response = client.get(f"/api/bank/applications/{application_id}{suffix}")
            assert (
                response.status_code == 404 and response.json()["code"] == "APPLICATION_NOT_FOUND"
            )


def test_all_bank_reads_require_employee_role(seeded, client):
    assert client.get("/api/bank/applications").status_code == 401
    submitted = review_application(client)
    for suffix in (
        "",
        f"/{submitted['application']['id']}",
        f"/{submitted['application']['id']}/events",
        f"/{submitted['application']['id']}/revisions/1",
    ):
        assert client.get(f"/api/bank/applications{suffix}").status_code == 403
    assert login(client, email="bank2@example.com", password=SEED_PASSWORD).status_code == 200
    assert client.get(f"/api/bank/applications/{submitted['application']['id']}").status_code == 200


@pytest.mark.parametrize(
    "query",
    ["status=DRAFT", "status=unknown", "limit=0", "limit=101", "offset=-1", "company_id=C01"],
)
def test_bank_queue_validates_filters(seeded, client, query):
    login(client, email="bank@example.com")
    assert client.get(f"/api/bank/applications?{query}").status_code == 422


def test_employee_reading_does_not_extend_idle_or_change_application(seeded, client):
    submitted = review_application(client)
    login(client, email="bank@example.com")
    before = client.get("/api/auth/me").json()
    endpoint = f"/api/bank/applications/{submitted['application']['id']}"
    first = client.get(endpoint).json()
    assert client.get(endpoint).json() == first
    assert client.get("/api/auth/me").json()["idle_expires_at"] == before["idle_expires_at"]
    assert client.get(f"{endpoint}/revisions/999").json()["code"] == "REVISION_NOT_FOUND"
