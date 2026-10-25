from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID

from sqlalchemy import func, select

from credit_cabinet.models import ApplicationEvent
from credit_cabinet.schemas.agreements import SignAgreementRequest
from credit_cabinet.services.agreements import sign
from tests.conftest import SEED_PASSWORD, login
from tests.test_advisor_postgres import ready_postgres
from tests.test_agreements import sign_body, url
from tests.test_drafts_postgres import postgres_app as postgres_app
from tests.test_drafts_postgres import pytestmark as pytestmark
from tests.test_submissions import send


def test_concurrent_signature_is_idempotent_and_survives_restart(postgres_app):
    with postgres_app() as client:
        response = send(client, ready_postgres(client))
        assert response.status_code == 200, response.text
        app = response.json()["application"]
        assert app["status"] == "APPROVED"
        document = client.get(url(app)).json()
        body = SignAgreementRequest.model_validate(sign_body(app, document))
        cookie = client.cookies.get("credit_session")
        auth = client.app.state.auth
        factory = client.app.state.session_factory
        barrier = Barrier(2)

        def writer(_):
            with factory() as db:
                principal = auth.authenticate(db, cookie)
                barrier.wait(timeout=10)
                result = sign(db, principal, UUID(app["id"]), body, auth)
                return result.model_dump(mode="json")

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(writer, range(2)))
        assert results[0] == results[1]
        assert results[0]["status"] == "SIGNED" and results[0]["version"] == app["version"] + 1
        with factory() as db:
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(ApplicationEvent)
                    .where(
                        ApplicationEvent.application_id == UUID(app["id"]),
                        ApplicationEvent.event_type == "AGREEMENT_SIGNED",
                    )
                )
                == 1
            )
    with postgres_app() as client:
        client.cookies.set("credit_session", cookie)
        assert client.get(f"/api/applications/{app['id']}").json() == results[0]
        stored = client.get(url(app)).json()
        assert stored["content"] == document["content"]
        assert stored["signature"] == results[0]["signature"]
        assert login(client, "client2@example.com", SEED_PASSWORD).status_code == 200
        assert client.get(url(app)).status_code == 404
