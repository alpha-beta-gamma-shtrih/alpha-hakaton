from copy import deepcopy
from uuid import UUID

from credit_cabinet.models import Application
from credit_cabinet.services.snapshots import application_input, financial_input_hash
from tests.test_drafts import new_draft, patch


def test_snapshot_is_detached_and_hash_ignores_ui_and_observation_time(seeded, client):
    draft = new_draft(client)
    draft = patch(
        client,
        draft,
        requested_amount="1000000.00",
        term_months=12,
        purpose_code="INVENTORY",
        draft_data={
            "confirmations": {"data_confirmed": True, "credit_history_check_allowed": True}
        },
    ).json()
    with seeded.state.session_factory() as db:
        application = db.get(Application, UUID(draft["id"]))
        payload = application_input(db, application)
        first_hash = financial_input_hash(payload)
        application.ui_step = "REVIEW"
        application.lock_version += 1
        assert financial_input_hash(application_input(db, application)) == first_hash
        changed_time = deepcopy(payload)
        changed_time["company_snapshot"]["provenance"]["checked_at"] = "2099-01-01T00:00:00Z"
        assert financial_input_hash(changed_time) == first_hash
        changed_consent = deepcopy(payload)
        changed_consent["financial_snapshot"]["confirmations"]["credit_history_check_allowed"] = (
            False
        )
        assert financial_input_hash(changed_consent) != first_hash
        changed_amount = deepcopy(payload)
        changed_amount["requested_amount"] = "2000000.00"
        assert financial_input_hash(changed_amount) != first_hash
        changed_source = deepcopy(payload)
        changed_source["financial_snapshot"]["provenance"]["financial_months"]["source"] = (
            "CLIENT_DECLARED"
        )
        assert financial_input_hash(changed_source) != first_hash
        application.draft_data["financial_months"][0]["cash_inflow"] = "1.00"
        assert payload["financial_snapshot"]["financial_months"][0]["cash_inflow"] == "1200000.00"
