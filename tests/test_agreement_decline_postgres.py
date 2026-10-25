from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from credit_cabinet.api.errors import APIError
from credit_cabinet.models import Application, ApplicationEvent
from credit_cabinet.schemas.agreements import DeclineAgreementRequest, SignAgreementRequest
from credit_cabinet.services.agreements import decline, sign
from tests.conftest import ROOT
from tests.test_advisor_postgres import ready_postgres
from tests.test_agreement_decline import decline_body
from tests.test_agreements import sign_body, url
from tests.test_drafts_postgres import postgres_app as postgres_app
from tests.test_drafts_postgres import pytestmark as pytestmark
from tests.test_submissions import send


@pytest.mark.parametrize("race", ["decline", "sign"])
def test_refusal_is_atomic_against_retry_or_signing_and_survives_restart(postgres_app, race):
    with postgres_app() as client:
        app = send(client, ready_postgres(client)).json()["application"]
        assert app["status"] == "APPROVED"
        document = client.get(url(app)).json()
        refusal = DeclineAgreementRequest.model_validate(decline_body(app))
        signature = SignAgreementRequest.model_validate(sign_body(app, document))
        cookie = client.cookies.get("credit_session")
        auth, factory = client.app.state.auth, client.app.state.session_factory
        barrier = Barrier(2)

        def writer(index):
            with factory() as db:
                principal = auth.authenticate(db, cookie)
                barrier.wait(timeout=10)
                try:
                    if index == 1 and race == "sign":
                        result = sign(db, principal, UUID(app["id"]), signature, auth)
                    else:
                        result = decline(db, principal, UUID(app["id"]), refusal, auth)
                    return result.model_dump(mode="json")
                except APIError as exc:
                    db.rollback()
                    return exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(writer, range(2)))
        saved = client.get(f"/api/applications/{app['id']}").json()
        assert saved["version"] == app["version"] + 1
        assert saved["status"] in ("REJECTED", "SIGNED")
        if race == "decline":
            assert results[0] == results[1] == saved
        else:
            assert len([item for item in results if isinstance(item, APIError)]) == 1
            assert saved in results
        assert bool(saved["signature"]) != bool(saved["decline"])
        assert saved["decision"] == app["decision"]
        with factory() as db:
            events = list(
                db.scalars(
                    select(ApplicationEvent).where(
                        ApplicationEvent.application_id == UUID(app["id"]),
                        ApplicationEvent.event_type.in_(["AGREEMENT_SIGNED", "AGREEMENT_DECLINED"]),
                    )
                )
            )
            assert len(events) == 1
            if saved["decline"]:
                with pytest.raises(IntegrityError):
                    db.execute(
                        update(Application)
                        .where(Application.id == UUID(app["id"]))
                        .values(decline_record={"tampered": True})
                    )
                db.rollback()
        if saved["decline"]:
            config = Config(str(ROOT / "alembic.ini"))
            with client.app.state.engine.begin() as connection:
                config.attributes["connection"] = connection
                with pytest.raises(RuntimeError, match="Cannot discard saved client refusals"):
                    command.downgrade(config, "0008_bank_offers")
    with postgres_app() as client:
        client.cookies.set("credit_session", cookie)
        assert client.get(f"/api/applications/{app['id']}").json() == saved
