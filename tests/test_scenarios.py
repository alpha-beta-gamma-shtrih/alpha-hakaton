from copy import deepcopy
from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import event

from credit_cabinet.models import Company
from tests.conftest import csrf_headers, login
from tests.test_drafts import C01, SEED_PASSWORD, patch
from tests.test_submissions import AlteredSources, counts, ready, send


def compare(client, draft):
    return client.post(
        f"/api/applications/{draft['id']}/scenarios",
        json={"expected_version": draft["version"]},
        headers=csrf_headers(client),
    )


def test_calculation_only_never_reads_credit_or_calls_sources(seeded, client):
    draft = ready(client)
    draft = patch(
        client, draft, draft_data={"confirmations": {"credit_history_check_allowed": False}}
    ).json()
    adapter = AlteredSources(seeded.state.sources, crash=True)
    seeded.state.sources = adapter
    response = compare(client, draft)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "CALCULATION_ONLY" and len(body["candidates"]) == 3
    first = body["candidates"][0]
    assert first["monthly_payment"] == "94559.60"
    assert first["load_ratio"] is first["risk_score"] is first["preliminary_route"] is None
    assert first["provenance"]["credit_history"] is None
    assert first["is_binding"] is False
    assert first["reason_codes"] == ["CREDIT_HISTORY_CONFIRMATION_REQUIRED"]
    assert not adapter.calls and not any(counts(seeded).values())


def test_preview_uses_one_fact_set_without_persisting_or_consuming_attempts(seeded, client):
    draft = ready(client)
    adapter = AlteredSources(seeded.state.sources)
    seeded.state.sources = adapter
    first = compare(client, draft)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["mode"] == "PREVIEW"
    assert body["candidates"][0]["risk_score"] == 10
    assert body["candidates"][0]["preliminary_route"] == "APPROVE"
    assert adapter.calls == [("FNS", 1, 1), ("BKI", 1, 1)]
    assert (
        len({row["provenance"]["credit_history"]["checked_at"] for row in body["candidates"]}) == 1
    )
    repeated = compare(client, draft).json()
    assert [row["input_hash"] for row in body["candidates"]] == [
        row["input_hash"] for row in repeated["candidates"]
    ]
    assert not any(counts(seeded).values())
    assert client.get(f"/api/applications/{draft['id']}").json()["version"] == draft["version"]
    assert client.get(f"/api/applications/{draft['id']}").json()["status"] == "DRAFT"


def test_extended_term_can_improve_c03_without_promising_approval(seeded, client):
    with seeded.state.session_factory() as db:
        company = db.get(Company, UUID(C01))
        company.registered_on = date(2025, 4, 1)
        db.commit()
    seeded.state.sources = AlteredSources(
        seeded.state.sources,
        legal={"registered_on": "2025-04-01"},
        credit={"current_monthly_payment": "50000.00"},
    )
    draft = ready(client)
    months = deepcopy(draft["draft_data"]["financial_months"])
    for row in months:
        row.update(
            cash_inflow="800000.00", operating_outflow="500000.00", existing_debt_payment="50000.00"
        )
    draft = patch(
        client, draft, requested_amount="1500000.00", draft_data={"financial_months": months}
    ).json()
    body = compare(client, draft).json()
    first = body["candidates"][0]
    longer = next(row for row in body["candidates"] if row["candidate_id"] == "LONGER_TERM")
    assert first["risk_score"] == 35 and first["preliminary_route"] == "MANUAL_REVIEW"
    assert longer["risk_score"] == 20 and longer["preliminary_route"] == "APPROVE"
    assert longer["monthly_payment"] == "79306.65" and longer["is_binding"] is False
    assert longer["estimated_overpayment"] != first["estimated_overpayment"]


def test_preview_after_submission_uses_saved_official_facts(seeded, client):
    body = send(client, ready(client)).json()
    adapter = AlteredSources(seeded.state.sources, crash=True)
    seeded.state.sources = adapter
    before = counts(seeded)
    response = compare(client, body["application"])
    assert response.status_code == 200, response.text
    assert response.json()["candidates"][0]["risk_score"] == 10
    assert not adapter.calls and counts(seeded) == before


def test_withdrawn_confirmation_blocks_cached_history_and_submit_replay(seeded, client):
    draft = ready(client)
    draft = patch(
        client, draft, draft_data={"financial_months": draft["draft_data"]["financial_months"][:5]}
    ).json()
    key = uuid4()
    submitted = send(client, draft, key=key).json()
    assert submitted["application"]["status"] == "NEEDS_INFO"
    updated = patch(
        client,
        submitted["application"],
        draft_data={"confirmations": {"credit_history_check_allowed": False}},
    ).json()
    assert updated["assessment"] is None
    adapter = AlteredSources(seeded.state.sources, crash=True)
    seeded.state.sources = adapter
    queries = []

    def capture(_connection, _cursor, statement, _params, _context, _many):
        queries.append(statement.lower())

    event.listen(seeded.state.engine, "before_cursor_execute", capture)
    try:
        response = compare(client, updated)
        assert response.status_code == 200 and response.json()["mode"] == "CALCULATION_ONLY"
        assert not adapter.calls
        replay = send(client, draft, key=key).json()
        assert replay["assessment"] is None and replay["application"]["assessment"] is None
        assert client.get(f"/api/applications/{draft['id']}").json()["assessment"] is None
    finally:
        event.remove(seeded.state.engine, "before_cursor_execute", capture)
    assert not any(
        "from assessments" in query or "from check_results" in query for query in queries
    )


def test_duplicate_candidates_are_removed_at_product_bounds(seeded, client):
    draft = ready(client)
    draft = patch(client, draft, requested_amount="100000.00", term_months=24).json()
    body = compare(client, draft).json()
    assert len(body["candidates"]) == 1 and body["candidates"][0]["candidate_id"] == "REQUESTED"


def test_preview_validates_version_membership_and_csrf(seeded, client):
    draft = ready(client)
    endpoint = f"/api/applications/{draft['id']}/scenarios"
    assert client.post(endpoint, json={"expected_version": draft["version"]}).status_code == 403
    stale = {**draft, "version": draft["version"] - 1}
    assert compare(client, stale).status_code == 409
    assert login(client, email="client2@example.com", password=SEED_PASSWORD).status_code == 200
    assert compare(client, draft).status_code == 404
    assert login(client, email="bank@example.com").status_code == 200
    assert compare(client, draft).status_code == 403
