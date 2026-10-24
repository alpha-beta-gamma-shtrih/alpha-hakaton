from copy import deepcopy
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select

from credit_cabinet.integrations.fixtures import FixtureSources
from credit_cabinet.models import Company, User
from credit_cabinet.services.policy import annuity
from credit_cabinet.services.seed import import_bundle
from tests.conftest import ROOT, csrf_headers, login, personal_bootstrap_bundle
from tests.test_drafts import new_draft, patch
from tests.test_submissions import send


@pytest.fixture
def personal(seeded):
    directory = ROOT / "demo_data/demo_0_3"
    with seeded.state.session_factory() as db:
        before = dict(db.execute(select(User.email, User.password_hash)).all())
        import_bundle(db, personal_bootstrap_bundle())
        assert dict(db.execute(select(User.email, User.password_hash)).all()) == before
    seeded.state.settings.demo_dataset_dir = directory
    seeded.state.sources = FixtureSources(directory)
    return seeded


def prepared(
    client, *, purpose="EQUIPMENT", term=60, amount="1000000.00", partner=True, consent=True
):
    draft = new_draft(client)
    response = patch(
        client,
        draft,
        requested_amount=amount,
        term_months=term,
        purpose_code=purpose,
        draft_data={
            "purchase_from_bank_partner": partner,
            "confirmations": {"data_confirmed": True, "credit_history_check_allowed": consent},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def preview(client, draft):
    response = client.post(
        f"/api/applications/{draft['id']}/scenarios",
        json={"expected_version": draft["version"]},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_preview_submission_and_decision_share_personal_rate(personal, client):
    draft = prepared(client)
    assert draft["draft_data"]["purchase_from_bank_partner"] is True
    candidate = preview(client, draft)["candidates"][0]
    assert candidate["annual_rate_percent"] == "22.000"
    assert candidate["pricing"]["has_active_loan_in_our_bank"] is True
    payment = annuity(Decimal("1000000"), 60, Decimal(22))["monthly_payment"]
    assert candidate["monthly_payment"] == payment
    response = send(client, draft)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["application"]["decision"]["annual_rate_percent"] == "22.000"
    assert result["application"]["decision"]["monthly_payment"] == payment
    revision = result["revision"]
    assert revision["company_snapshot"]["has_active_loan_in_our_bank"] is True
    assert revision["financial_snapshot"]["purchase_from_bank_partner"] is True
    assert revision["product_snapshot"]["annual_rate_percent"] == "20.000"
    # Changing the live relationship cannot change the submitted rate or AI comparison.
    with personal.state.session_factory() as db:
        company = db.get(Company, UUID(draft["company_id"]))
        company.has_active_loan_in_our_bank = False
        db.commit()
    saved = client.get(f"/api/applications/{draft['id']}").json()
    assert preview(client, saved)["candidates"][0]["annual_rate_percent"] == "22.000"


def test_other_is_neutral_and_partner_claim_must_match_purpose(personal, client):
    draft = prepared(client, purpose="OTHER", term=36, partner=False)
    pricing = preview(client, draft)["candidates"][0]["pricing"]
    assert pricing["annual_rate_percent"] == "21.500"
    assert pricing["discounts"][0]["percentage_points"] == "0.000"
    assert patch(client, draft, draft_data={"purchase_from_bank_partner": True}).status_code == 422
    assert patch(client, draft, draft_data={"has_active_loan_in_our_bank": True}).status_code == 422
    assert patch(client, draft, annual_rate_percent="20.000").status_code == 422
    assert patch(client, draft, term_months=61).status_code == 200
    current = client.get(f"/api/applications/{draft['id']}").json()
    assert send(client, current).status_code == 422


def test_consent_and_missing_finances_do_not_claim_personal_rate(personal, client):
    draft = prepared(client, consent=False)
    result = preview(client, draft)
    assert result["mode"] == "CALCULATION_ONLY"
    assert all(c["pricing"]["status"] == "INDICATIVE" for c in result["candidates"])
    draft = patch(
        client,
        draft,
        draft_data={
            "confirmations": {"credit_history_check_allowed": True},
            "financial_months": draft["draft_data"]["financial_months"][:-1],
        },
    ).json()
    assert preview(client, draft)["candidates"][0]["pricing"]["status"] == "INDICATIVE"
    assert send(client, draft).json()["application"]["status"] == "NEEDS_INFO"


def test_each_candidate_has_own_term_rate_and_old_reports_become_stale(personal, client):
    draft = prepared(client, term=24)
    result = preview(client, draft)
    assert [c["annual_rate_percent"] for c in result["candidates"]] == [
        "20.000",
        "20.000",
        "20.000",
    ]
    draft = patch(
        client, draft, purpose_code="OTHER", draft_data={"purchase_from_bank_partner": False}
    ).json()
    result = preview(client, draft)
    assert [c["annual_rate_percent"] for c in result["candidates"]] == [
        "20.500",
        "20.500",
        "21.500",
    ]
    report = client.post(
        f"/api/applications/{draft['id']}/advisor",
        json={"expected_version": draft["version"], "mode": "COMPARE"},
        headers=csrf_headers(client),
    )
    assert report.status_code == 200, report.text
    assert any(f["factor_id"] == "REQUESTED_PRICING" for f in report.json()["factors"])
    draft = patch(client, draft, purpose_code="INVENTORY").json()
    assert client.get(f"/api/applications/{draft['id']}/advisor").json()["is_current"] is False


def test_manual_decision_uses_assessed_rate(personal, client):
    draft = prepared(client, purpose="OTHER", term=12, partner=False, amount="2500000.00")
    result = send(client, draft).json()
    assert result["application"]["status"] == "MANUAL_REVIEW"
    assert login(client, "bank@example.com").status_code == 200
    card = client.get(f"/api/bank/applications/{draft['id']}").json()
    assert "APPROVE" in card["allowed_actions"]
    response = client.post(
        f"/api/bank/applications/{draft['id']}/decision",
        json={
            "expected_version": card["version"],
            "outcome": "APPROVED",
            "public_explanation": "Показатели и условия демо-заявки проверены сотрудником.",
        },
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    assert response.json()["decision"]["annual_rate_percent"] == "20.000"


def test_legacy_submission_stays_fixed_and_legacy_draft_can_finish(seeded, client):
    legacy = prepared(client, purpose="INVENTORY", term=12, partner=False)
    submitted = send(client, legacy).json()
    old_snapshot = deepcopy(submitted["revision"])
    old_draft = prepared(client, purpose="OTHER", term=12, partner=False)
    # OTHER is outside the legacy product: draft storage is allowed, submit must validate.
    old_draft = patch(client, old_draft, purpose_code="INVENTORY").json()
    with seeded.state.session_factory() as db:
        import_bundle(db, personal_bootstrap_bundle())
    assert (
        send(client, old_draft).json()["application"]["decision"]["annual_rate_percent"] == "24.000"
    )
    assert (
        client.get(f"/api/applications/{legacy['id']}").json()["decision"]["annual_rate_percent"]
        == "24.000"
    )
    response = client.get(
        f"/api/applications/{legacy['id']}/revisions/{old_snapshot['revision_no']}"
    )
    assert response.status_code == 200
    assert response.json() == old_snapshot
    rejected = client.post(
        "/api/applications",
        json={"company_id": legacy["company_id"], "product_id": legacy["product_id"]},
        headers=csrf_headers(client),
    )
    assert rejected.status_code == 409
