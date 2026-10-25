from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import func, select

from credit_cabinet.api.errors import APIError
from credit_cabinet.db.base import Base
from credit_cabinet.models import Decision
from credit_cabinet.schemas.bank import ManualDecision
from credit_cabinet.services.bank_commands import decide
from tests.conftest import SEED_PASSWORD, login
from tests.test_bank_commands import decision_body
from tests.test_bank_offers import offered, quote
from tests.test_bank_postgres import submitted_for_review
from tests.test_drafts_postgres import postgres_app as postgres_app
from tests.test_drafts_postgres import pytestmark as pytestmark


def test_changed_offer_race_and_restart(postgres_app):
    with postgres_app() as client:
        submitted = submitted_for_review(client)
        app = submitted["application"]
        login(client, "bank@example.com", SEED_PASSWORD)
        preview = quote(client, app)
        assert preview.status_code == 200, preview.text
        body = ManualDecision.model_validate(
            decision_body(app["version"], offer=offered(preview.json()))
        )
        cookie = client.cookies.get("credit_session")
        factory, auth = client.app.state.session_factory, client.app.state.auth
        barrier = Barrier(2)

        def writer(_):
            with factory() as db:
                principal = auth.authenticate(db, cookie)
                barrier.wait(timeout=10)
                try:
                    decide(db, principal, UUID(app["id"]), body, auth)
                    return 200
                except APIError as error:
                    return error.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(writer, range(2))) == [200, 409]
        saved = client.get(f"/api/bank/applications/{app['id']}").json()
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(Decision)) == 1
            assert (
                compare_metadata(MigrationContext.configure(db.connection()), Base.metadata) == []
            )
    with postgres_app() as client:
        client.cookies.set("credit_session", cookie)
        assert client.get(f"/api/bank/applications/{app['id']}").json() == saved
        assert saved["decision"]["offer"] == preview.json()["terms"]
