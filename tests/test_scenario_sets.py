from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from credit_cabinet.models import Company
from tests.conftest import SEED_PASSWORD, csrf_headers, login
from tests.test_advisor import explain
from tests.test_drafts import patch
from tests.test_personal_pricing_api import personal as personal
from tests.test_personal_pricing_api import prepared
from tests.test_submissions import send


def endpoint(draft):
    return f"/api/applications/{draft['id']}/scenario-set"


def create_set(client, draft, refresh=False):
    return client.post(
        endpoint(draft),
        json={"expected_version": draft["version"], "refresh": refresh},
        headers=csrf_headers(client),
    )


def choose(client, draft, options, candidate):
    return client.post(
        endpoint(draft) + "/select",
        json={
            "expected_version": draft["version"],
            "scenario_set_id": options["id"],
            "candidate_id": candidate,
        },
        headers=csrf_headers(client),
    )


def fixed(client):
    draft = prepared(client, amount="2600000.00", term=20, purpose="INVENTORY", partner=False)
    response = create_set(client, draft)
    assert response.status_code == 200, response.text
    return response.json()["application"], response.json()["scenario_set"]


def check_switching(client, draft, options):
    expected = {
        "REQUESTED": ("2600000.00", 20),
        "LOWER_AMOUNT": ("2080000.00", 20),
        "LONGER_TERM": ("2600000.00", 32),
    }
    assert {
        c["candidate_id"]: (c["requested_amount"], c["term_months"]) for c in options["candidates"]
    } == expected
    for candidate in ["LOWER_AMOUNT", "LONGER_TERM", "REQUESTED"] * 4:
        response = choose(client, draft, options, candidate)
        assert response.status_code == 200, response.text
        body = response.json()
        draft = body["application"]
        selected = body["scenario_set"]
        assert (draft["requested_amount"], draft["term_months"]) == expected[candidate]
        assert selected["id"] == options["id"] and selected["created_at"] == options["created_at"]
        assert selected["candidates"] == options["candidates"]
        assert selected["is_current"] is True and selected["selected_candidate_id"] == candidate
        assert client.get(endpoint(draft)).json() == selected
    return draft


def test_switching_is_fixed_and_reopening_keeps_set(personal, client):
    draft, options = fixed(client)
    draft = check_switching(client, draft, options)
    # Initial create is idempotent, including after selections.
    again = create_set(client, draft).json()
    assert again["scenario_set"]["id"] == options["id"]
    assert again["application"]["version"] == draft["version"]
    with TestClient(personal) as reopened:
        assert login(reopened).status_code == 200
        restored = reopened.get(endpoint(draft)).json()
        assert restored["id"] == options["id"] and restored["is_current"]
        assert restored["candidates"] == options["candidates"]


def test_manual_amount_change_requires_explicit_refresh_and_rejects_old_id(personal, client):
    draft, options = fixed(client)
    draft = patch(client, draft, requested_amount="3000000.00").json()
    stale = client.get(endpoint(draft)).json()
    assert stale["is_current"] is False and stale["selected_candidate_id"] is None
    assert stale["candidates"] == options["candidates"]
    assert choose(client, draft, options, "LOWER_AMOUNT").json()["code"] == "SCENARIO_SET_STALE"
    assert create_set(client, draft).json()["scenario_set"]["id"] == options["id"]
    updated = create_set(client, draft, refresh=True).json()
    assert updated["scenario_set"]["id"] != options["id"]
    assert updated["scenario_set"]["candidates"][0]["requested_amount"] == "3000000.00"
    assert (
        choose(client, updated["application"], options, "LOWER_AMOUNT").json()["code"]
        == "SCENARIO_SET_CONFLICT"
    )


@pytest.mark.parametrize(
    "change", ["finances", "purpose", "partner", "company", "consent", "sources"]
)
def test_calculation_changes_make_saved_set_stale(personal, client, tmp_path, change):
    draft, options = fixed(client)
    if change == "finances":
        months = deepcopy(draft["draft_data"]["financial_months"])
        months[0]["cash_inflow"] = "1200001.00"
        draft = patch(client, draft, draft_data={"financial_months": months}).json()
    elif change == "purpose":
        draft = patch(client, draft, purpose_code="EQUIPMENT").json()
    elif change == "partner":
        draft = patch(client, draft, draft_data={"purchase_from_bank_partner": True}).json()
    elif change == "consent":
        draft = patch(
            client, draft, draft_data={"confirmations": {"credit_history_check_allowed": False}}
        ).json()
    elif change == "sources":
        # Missing source files invalidate the saved response without calling the source adapter.
        personal.state.settings.demo_dataset_dir = tmp_path
    else:
        with personal.state.session_factory() as db:
            db.get(Company, UUID(draft["company_id"])).has_active_loan_in_our_bank = False
            db.commit()
    response = client.get(endpoint(draft))
    assert response.status_code == 200
    result = response.json()
    assert result["is_current"] is False
    assert result["candidates"] == ([] if change == "consent" else options["candidates"])
    assert choose(client, draft, options, "REQUESTED").json()["code"] == "SCENARIO_SET_STALE"


def test_nonfinancial_edits_and_same_option_keep_set(personal, client):
    draft, options = fixed(client)
    draft = patch(
        client,
        draft,
        ui_step="FINANCES",
        purpose_details="Пояснение назначения",
        draft_data={"confirmations": {"data_confirmed": False}},
    ).json()
    assert client.get(endpoint(draft)).json()["is_current"]
    chosen = choose(client, draft, options, "REQUESTED").json()
    assert chosen["application"]["version"] == draft["version"]
    assert chosen["scenario_set"]["id"] == options["id"]


def test_csrf_version_membership_role_and_input_guards(personal, client):
    draft, options = fixed(client)
    assert (
        client.post(endpoint(draft), json={"expected_version": draft["version"]}).status_code == 403
    )
    older = {**draft, "version": draft["version"] - 1}
    assert choose(client, older, options, "LOWER_AMOUNT").json()["code"] == "VERSION_CONFLICT"
    assert choose(client, draft, {**options, "id": str(uuid4())}, "LOWER_AMOUNT").status_code == 409
    assert patch(client, draft, scenario_set={}).status_code == 422
    assert login(client, "client2@example.com", SEED_PASSWORD).status_code == 200
    assert client.get(endpoint(draft)).status_code == 404
    assert choose(client, draft, options, "LOWER_AMOUNT").status_code == 404
    assert login(client, "bank@example.com").status_code == 200
    assert client.get(endpoint(draft)).status_code == 403
    assert create_set(client, draft).status_code == 403


def test_bounds_remove_duplicates_and_no_fictitious_third_option(personal, client):
    draft = prepared(client, amount="100000.00", term=60, purpose="OTHER", partner=False)
    response = create_set(client, draft).json()
    options, draft = response["scenario_set"], response["application"]
    assert len(options["candidates"]) == 1
    assert choose(client, draft, options, "LOWER_AMOUNT").json()["code"] == "SCENARIO_NOT_FOUND"


def test_live_calculation_and_ai_comparison_use_correct_bases(personal, client):
    draft, options = fixed(client)
    chosen = choose(client, draft, options, "LOWER_AMOUNT").json()
    draft = chosen["application"]
    calculation = client.post(
        f"/api/applications/{draft['id']}/scenarios",
        json={"expected_version": draft["version"]},
        headers=csrf_headers(client),
    ).json()
    assert calculation["candidates"][0]["requested_amount"] == "2080000.00"
    report = explain(client, draft, "COMPARE")
    assert report.status_code == 200, report.text
    assert report.json()["scenarios"] == options["candidates"]
    # Submission contains selected parameters, not the original request or cached suggestions.
    submitted = send(client, draft)
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["revision"]["requested_amount"] == "2080000.00"
    final = submitted.json()["application"]
    assert choose(client, final, options, "REQUESTED").json()["code"] == "APPLICATION_NOT_EDITABLE"


def test_read_missing_set_is_read_only(personal, client):
    draft = prepared(client)
    assert client.get(endpoint(draft)).json() is None
    assert client.get(f"/api/applications/{draft['id']}").json()["version"] == draft["version"]
