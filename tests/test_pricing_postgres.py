from uuid import UUID

from alembic import command
from alembic.config import Config
from sqlalchemy import select

from credit_cabinet.models import User
from credit_cabinet.services.seed import import_bundle, load_bundle
from tests.conftest import ROOT, migrate
from tests.test_drafts import patch
from tests.test_drafts_postgres import create
from tests.test_drafts_postgres import postgres_app as postgres_app
from tests.test_drafts_postgres import pytestmark as pytestmark
from tests.test_submissions import send


def test_upgrade_filled_database_preserves_old_submission_and_adds_new_pricing(postgres_app):
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
        snapshot = submitted["revision"]
        with client.app.state.session_factory() as db:
            before = dict(db.execute(select(User.email, User.password_hash)).all())
        engine = client.app.state.engine
        config = Config(str(ROOT / "alembic.ini"))
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "0004_draft_archive")
        migrate(engine)
        with client.app.state.session_factory() as db:
            import_bundle(db, load_bundle(ROOT / "demo_data/demo_0_3"))
            assert dict(db.execute(select(User.email, User.password_hash)).all()) == before
        assert client.get(f"/api/applications/{draft['id']}/revisions/1").json() == snapshot
        assert (
            client.get(f"/api/applications/{draft['id']}").json()["decision"]["annual_rate_percent"]
            == "24.000"
        )
        new = create(client)
        new = patch(
            client,
            new,
            requested_amount="1000000.00",
            term_months=60,
            purpose_code="EQUIPMENT",
            draft_data={
                "purchase_from_bank_partner": True,
                "confirmations": {"data_confirmed": True, "credit_history_check_allowed": True},
            },
        ).json()
        result = send(client, new)
        assert result.status_code == 200, result.text
        assert result.json()["application"]["decision"]["annual_rate_percent"] == "22.000"
        from credit_cabinet.models import ApplicationRevision

        with client.app.state.session_factory() as db:
            saved = db.get(ApplicationRevision, UUID(result.json()["revision"]["id"]))
            assert saved.financial_snapshot["purchase_from_bank_partner"] is True
