"""The shipped dataset is exercised as data, through real rules and API commands."""

import csv
import hashlib
import io
import json
from decimal import Decimal
from uuid import uuid5

from sqlalchemy import func, select

from credit_cabinet.core.demo import CALCULATION_DATE, DEMO_NAMESPACE
from credit_cabinet.integrations.documents import DocumentStore
from credit_cabinet.integrations.fixtures import FixtureSources
from credit_cabinet.models import Company, CompanyMembership, User
from credit_cabinet.models.enums import CheckSource
from credit_cabinet.services.policy import evaluate
from credit_cabinet.services.seed import import_bundle, load_bundle
from tests.conftest import PASSWORD, ROOT, SEED_PASSWORD, csrf_headers, login
from tests.test_drafts import patch
from tests.test_submissions import send

DATA = ROOT / "demo_data/demo_0_3"


def test_full_dataset_documents_match_finances_and_legal_identity(settings):
    bundle = load_bundle(DATA)
    assert bundle.manifest.subset == "FULL"
    assert len(bundle.companies) == len(bundle.memberships) == 144
    assert len(bundle.users) == 146 and len(bundle.financials) == 862
    assert len(bundle.products) == 1 and bundle.products[0].version == 3
    settings.demo_dataset_dir = DATA
    store, sources = DocumentStore(settings), FixtureSources(DATA)
    for company in bundle.companies:
        templates = store.templates(company.inn)
        assert len(templates) == 1
        template, content = templates[0]
        assert hashlib.sha256(content).hexdigest() == template.content_sha256
        actual = list(csv.DictReader(io.StringIO(content.decode("utf-8"))))
        expected = [
            row.model_dump(mode="json")
            for row in bundle.financials
            if row.company_key == company.company_key
        ]
        # Money JSON serialization already uses exactly two decimal places.
        assert actual == expected, company.company_key
        legal = sources.check(company.inn, CheckSource.FNS, 1, 1)
        assert legal.status == "SUCCESS"
        for key in ("inn", "legal_form", "registered_on"):
            assert legal.normalized_data[key] == company.model_dump(mode="json")[key]
    assert len([row for row in bundle.financials if row.company_key == "C04"]) == 5
    assert len([row for row in bundle.financials if row.company_key == "C09"]) == 5
    assert {
        row.company_key for row in bundle.bank_relationships if row.has_active_loan_in_our_bank
    } == {"C01"}


def test_all_profiles_and_scenario_expectations_use_actual_policy():
    bundle = load_bundle(DATA)
    sources = FixtureSources(DATA)
    companies = {row.company_key: row.model_dump(mode="json") for row in bundle.companies}
    bank = {row.company_key: row.has_active_loan_in_our_bank for row in bundle.bank_relationships}

    def run(key, amount="1000000.00", term=12, purpose="INVENTORY", partner=False, attempt=1):
        return evaluate(
            company={**companies[key], "has_active_loan_in_our_bank": bank[key]},
            financials=[
                r.model_dump(mode="json") for r in bundle.financials if r.company_key == key
            ],
            amount=Decimal(amount),
            term=term,
            annual_rate=Decimal("20"),
            calculation_date=CALCULATION_DATE,
            source=lambda kind: sources.check(companies[key]["inn"], kind, 1, attempt),
            personal_pricing=True,
            purpose=purpose,
            partner_purchase=partner,
        )

    for key in companies:
        result = run(key)
        assert result.reason_codes
        assert not {
            "COMPANY_DATA_MISMATCH",
            "SOURCE_RESPONSE_INVALID",
            "DEBT_PAYMENT_MISMATCH",
        } & set(result.reason_codes), key
    scenarios = json.loads((DATA / "scenarios.json").read_text(encoding="utf-8"))
    assert len(scenarios) == 18
    for scenario in scenarios:
        result = run(
            scenario["company_key"],
            scenario["requested_amount"],
            scenario["term_months"],
            scenario["purpose_code"],
            scenario.get("purchase_from_bank_partner", False),
            2 if "RETRY_PROCESSING" in scenario["sequence"] else 1,
        )
        expected = scenario["expected_result"]
        assert result.routing == expected["routing"], scenario["scenario_key"]
        assert result.risk_score == expected["risk_score"]
        assert result.reason_codes == expected["reason_codes"]
        for key in ("monthly_payment", "annual_rate_percent", "pricing"):
            assert result.calculation_details.get(key) == expected[key]


def exercise_scenarios(client, original_password=PASSWORD):
    """Shared API acceptance for SQLite and a disposable PostgreSQL schema."""
    # This acceptance run logs in as many profiles from one simulated IP.
    # Production defaults and dedicated rate-limit tests remain unchanged.
    client.app.state.auth.limiter.limit = 1000
    first_document = None
    scenarios = json.loads((DATA / "scenarios.json").read_text(encoding="utf-8"))
    credentials = {row.email: row.password.get_secret_value() for row in load_bundle(DATA).users}
    for scenario in scenarios:
        key = scenario["company_key"]
        email = "client@example.com" if key == "C01" else f"client{int(key[1:])}@example.com"
        password = (
            original_password
            if key == "C01"
            else SEED_PASSWORD
            if key == "C02"
            else credentials[email]
        )
        assert login(client, email, password).status_code == 200
        companies = client.get("/api/companies").json()["items"]
        assert len(companies) == 1
        company_id = str(uuid5(DEMO_NAMESPACE, f"company:{key}"))
        assert companies[0]["id"] == company_id
        if first_document and key != "C01":
            assert client.get(first_document).status_code == 404
        product = client.get("/api/products").json()["items"][0]
        assert product["version"] == 3
        response = client.post(
            "/api/applications",
            headers=csrf_headers(client),
            json={"company_id": company_id, "product_id": product["id"]},
        )
        assert response.status_code == 201, response.text
        draft = response.json()
        document = draft["documents"][0]
        content = client.get(document["download_url"])
        assert content.status_code == 200
        assert content.content == (DATA / f"documents/{key}.csv").read_bytes()
        first_document = first_document or document["download_url"]
        response = patch(
            client,
            draft,
            requested_amount=scenario["requested_amount"],
            term_months=scenario["term_months"],
            purpose_code=scenario["purpose_code"],
            draft_data={
                "purchase_from_bank_partner": scenario.get("purchase_from_bank_partner", False),
                "confirmations": {"data_confirmed": True, "credit_history_check_allowed": True},
            },
        )
        assert response.status_code == 200, response.text
        draft = response.json()
        submitted = send(client, draft)
        assert submitted.status_code == 200, submitted.text
        body = submitted.json()
        assert body["revision"]["document_refs"] == draft["documents"]
        card = body["application"]
        assessment = body["assessment"]
        if "RETRY_PROCESSING" in scenario["sequence"]:
            assert card["status"] == "MANUAL_REVIEW"
            assert [row["code"] for row in assessment["reasons"]] == ["SOURCE_BKI_UNAVAILABLE"]
            assert card["decision"] is None
            snapshot = body["revision"]
            assert login(client, "bank@example.com", original_password).status_code == 200
            response = client.post(
                f"/api/bank/applications/{draft['id']}/retry-processing",
                json={"expected_version": card["version"]},
                headers=csrf_headers(client),
            )
            assert response.status_code == 200, response.text
            card = response.json()
            assessment = card["assessment"]
            assert assessment["run_no"] == 2 and card["revision_id"] == snapshot["id"]
            assert client.get(document["download_url"]).content == content.content
        expected = scenario["expected_result"]
        assert card["status"] == expected["status"], scenario["scenario_key"]
        assert assessment["routing"] == expected["routing"]
        assert assessment["risk_score"] == expected["risk_score"]
        assert [row["code"] for row in assessment["reasons"]] == expected["reason_codes"]
        for name in ("monthly_payment", "annual_rate_percent", "pricing"):
            assert assessment["calculation_details"].get(name) == expected[name]


def test_expansion_import_is_idempotent_preserves_passwords_and_passes_api_scenarios(
    seeded, client
):
    bundle = load_bundle(DATA)
    with seeded.state.session_factory() as db:
        before = dict(db.execute(select(User.email, User.password_hash)).all())
        created = import_bundle(db, bundle, SEED_PASSWORD)["created"]
        assert created == dict(
            users=142, companies=142, financial_months=850, memberships=142, products=1
        )
        assert not any(import_bundle(db, bundle)["created"].values())
        after = dict(db.execute(select(User.email, User.password_hash)).all())
        assert all(after[email] == password for email, password in before.items())
        assert db.scalar(select(func.count()).select_from(Company)) == 144
        assert db.scalar(select(func.count()).select_from(CompanyMembership)) == 144
    seeded.state.settings.demo_dataset_dir = DATA
    seeded.state.sources = FixtureSources(DATA)
    exercise_scenarios(client)
