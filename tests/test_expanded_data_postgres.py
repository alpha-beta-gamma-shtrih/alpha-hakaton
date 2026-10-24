from copy import deepcopy

from sqlalchemy import select

from credit_cabinet.integrations.fixtures import FixtureSources
from credit_cabinet.models import User
from credit_cabinet.services.seed import import_bundle, load_bundle
from tests.conftest import SEED_PASSWORD
from tests.test_drafts import patch
from tests.test_drafts_postgres import create
from tests.test_drafts_postgres import postgres_app as postgres_app
from tests.test_drafts_postgres import pytestmark as pytestmark
from tests.test_expanded_data import DATA, exercise_scenarios
from tests.test_submissions import send


def test_full_postgres_upgrade_keeps_submission_and_imports_every_profile(postgres_app):
    with postgres_app() as client:
        draft = create(client)
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
        submitted = send(client, draft).json()
        snapshot = deepcopy(submitted["revision"])
        with client.app.state.session_factory() as db:
            before = dict(db.execute(select(User.email, User.password_hash)).all())
            bundle = load_bundle(DATA)
            result = import_bundle(db, bundle, SEED_PASSWORD)
            assert result["created"]["companies"] == 142
            assert not any(import_bundle(db, bundle)["created"].values())
            after = dict(db.execute(select(User.email, User.password_hash)).all())
            assert all(after[email] == password for email, password in before.items())
        assert client.get(f"/api/applications/{draft['id']}/revisions/1").json() == snapshot
        assert (
            client.get(f"/api/applications/{draft['id']}").json()["decision"]["annual_rate_percent"]
            == "24.000"
        )
        client.app.state.settings.demo_dataset_dir = DATA
        client.app.state.sources = FixtureSources(DATA)
        exercise_scenarios(client, original_password=SEED_PASSWORD)
