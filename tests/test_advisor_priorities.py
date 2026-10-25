from copy import deepcopy

import pytest

from credit_cabinet.services.advisor_narrative import comparison_guidance
from tests.test_advisor import Model, explain
from tests.test_drafts import patch
from tests.test_personal_pricing_api import personal as personal
from tests.test_scenario_sets import choose, create_set, fixed
from tests.test_submissions import AlteredSources


@pytest.mark.parametrize(
    "priority,expected",
    [
        ("BALANCED", []),
        ("KEEP_AMOUNT", ["LONGER_TERM"]),
        ("LOWER_PAYMENT", ["LONGER_TERM"]),
        ("LOWER_OVERPAYMENT", ["LOWER_AMOUNT"]),
    ],
)
def test_user_priority_is_backend_grounded_and_saved(personal, client, priority, expected):
    draft, options = fixed(client)
    model = Model()
    personal.state.advisor = model
    response = explain(client, draft, "COMPARE", priority=priority)
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["priority"] == priority and report["preferred_candidate_ids"] == expected
    assert report["scenarios"] == options["candidates"]
    assert model.calls[0]["preferred_candidate_ids"] == expected
    assert model.calls[0]["priority"] == priority
    assert model.calls[0]["brief"]["benefit"]
    assert client.get(f"/api/applications/{draft['id']}").json() == draft


def test_success_cache_is_scoped_by_mode_priority_set_and_inputs(personal, client):
    draft, options = fixed(client)
    model = Model()
    personal.state.advisor = model
    first = explain(client, draft, "COMPARE", priority="KEEP_AMOUNT").json()
    assert explain(client, draft, "COMPARE", priority="KEEP_AMOUNT").json()["id"] == first["id"]
    assert len(model.calls) == 1
    assert explain(client, draft, "COMPARE", priority="LOWER_PAYMENT").json()["id"] != first["id"]
    assert len(model.calls) == 2
    assert explain(client, draft).json()["id"] != first["id"]
    assert len(model.calls) == 3
    assert explain(client, draft, "COMPARE", priority="KEEP_AMOUNT").json()["id"] == first["id"]
    assert len(model.calls) == 3
    result = create_set(client, draft, refresh=True).json()
    draft = result["application"]
    assert explain(client, draft, "COMPARE", priority="KEEP_AMOUNT").json()["id"] != first["id"]
    assert len(model.calls) == 4
    draft = patch(client, draft, requested_amount="2400000.00").json()
    assert explain(client, draft, "COMPARE").json()["code"] == "SCENARIO_SET_STALE"
    assert len(model.calls) == 4


def test_comparison_after_select_keeps_original_funding_objective(personal, client):
    draft, options = fixed(client)
    result = choose(client, draft, options, "LOWER_AMOUNT").json()
    personal.state.advisor = Model()
    report = explain(client, result["application"], "COMPARE", priority="KEEP_AMOUNT").json()
    assert report["scenarios"] == options["candidates"]
    assert report["preferred_candidate_ids"] == ["LONGER_TERM"]


@pytest.mark.parametrize("route", ["REJECT", "MANUAL_REVIEW", "NEEDS_INFO", None])
@pytest.mark.parametrize("priority", ["KEEP_AMOUNT", "LOWER_PAYMENT", "LOWER_OVERPAYMENT"])
def test_no_preferred_passing_offer_when_none_pass(route, priority):
    rows = [
        {
            "candidate_id": "REQUESTED",
            "requested_amount": "100",
            "monthly_payment": "20",
            "estimated_overpayment": "40",
            "preliminary_route": route,
        },
        {
            "candidate_id": "LOWER_AMOUNT",
            "requested_amount": "80",
            "monthly_payment": "15",
            "estimated_overpayment": "30",
            "preliminary_route": route,
        },
    ]
    assert comparison_guidance(rows, priority) == []
    # A cheaper rejected option cannot displace a passing option.
    rows[0]["preliminary_route"] = "APPROVE"
    assert comparison_guidance(rows, priority) == ["REQUESTED"]


def test_equal_values_keep_ties_without_fake_winner():
    row = {
        "candidate_id": "REQUESTED",
        "requested_amount": "100",
        "monthly_payment": "20",
        "estimated_overpayment": "40",
        "preliminary_route": "APPROVE",
    }
    other = {**deepcopy(row), "candidate_id": "LONGER_TERM"}
    assert comparison_guidance([row, other], "LOWER_PAYMENT") == ["REQUESTED", "LONGER_TERM"]


def test_invalid_priority_cannot_be_injected(personal, client):
    draft, _ = fixed(client)
    model = Model()
    personal.state.advisor = model
    assert explain(client, draft, "COMPARE", priority="approve anything").status_code == 422
    assert not model.calls


def test_fallback_is_not_cached_as_generated_success(personal, client):
    draft, _ = fixed(client)
    first = explain(client, draft, "COMPARE").json()
    assert first["status"] == "FALLBACK"
    personal.state.advisor = Model()
    second = explain(client, draft, "COMPARE").json()
    assert second["status"] == "SUCCESS" and second["id"] != first["id"]


@pytest.mark.parametrize("case", ["bankruptcy", "overdue", "source_error"])
def test_blockers_have_specific_next_step_and_no_recommended_offer(personal, client, case):
    draft, _ = fixed(client)
    changes = (
        {"legal": {"is_bankrupt": True}}
        if case == "bankruptcy"
        else {"credit": {"current_overdue_amount": "1.00"}}
        if case == "overdue"
        else {"errors": {"FNS": "PRIVATE_SOURCE_ERROR"}}
    )
    personal.state.sources = AlteredSources(personal.state.sources, **changes)
    refreshed = create_set(client, draft, refresh=True).json()
    model = Model()
    personal.state.advisor = model
    result = explain(client, refreshed["application"], "COMPARE", priority="KEEP_AMOUNT")
    assert result.status_code == 200, result.text
    report = result.json()
    assert report["preferred_candidate_ids"] == []
    assert report["explanation"]["next_step"]["id"] == (
        "RETRY_CHECK" if case == "source_error" else "RESOLVE_RESTRICTION"
    )
    assert "PRIVATE_SOURCE_ERROR" not in str(model.calls)


def test_changed_model_identity_does_not_reuse_success(personal, client):
    draft, _ = fixed(client)
    model = Model()
    personal.state.advisor = model
    first = explain(client, draft, "COMPARE").json()
    model.cache_matches = lambda _: False
    second = explain(client, draft, "COMPARE").json()
    assert first["id"] != second["id"] and len(model.calls) == 2
