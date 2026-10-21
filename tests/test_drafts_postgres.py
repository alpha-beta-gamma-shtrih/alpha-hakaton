"""Real PostgreSQL tests, restricted to a disposable generated schema."""

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select, update
from sqlalchemy.exc import IntegrityError

from credit_cabinet.api.errors import APIError
from credit_cabinet.core.config import Settings
from credit_cabinet.db.session import build_session_factory
from credit_cabinet.main import create_app
from credit_cabinet.models import ApplicationRevision, Assessment, Decision
from credit_cabinet.schemas.business import DraftPatch
from credit_cabinet.schemas.submissions import SubmitRequest
from credit_cabinet.services.drafts import patch_draft
from credit_cabinet.services.seed import import_bundle, load_bundle
from credit_cabinet.services.submissions import submit
from tests.conftest import ROOT, csrf_headers, login, migrate
from tests.test_drafts import SEED_PASSWORD

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="PostgreSQL URL required"
)


@pytest.fixture
def postgres_app(settings):
    url = os.environ["TEST_DATABASE_URL"]
    assert url.startswith("postgresql+psycopg://")
    schema = "test_drafts_" + uuid4().hex
    admin = create_engine(url, hide_parameters=True)
    engine = create_engine(url, hide_parameters=True)
    with admin.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')

    @event.listens_for(engine, "connect")
    def set_schema(connection, _record):
        previous = connection.autocommit
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(f'SET search_path TO "{schema}"')
            cursor.execute("SET TIME ZONE 'UTC'")
        connection.autocommit = previous

    @contextmanager
    def api():
        app = create_app(Settings.model_validate({**settings.model_dump(), "database_url": url}))
        with TestClient(app) as client:
            app.state.engine.dispose()
            app.state.engine = engine
            app.state.session_factory = build_session_factory(engine)
            yield client

    try:
        migrate(engine)
        with build_session_factory(engine)() as db:
            first = import_bundle(db, load_bundle(ROOT / "demo_data/demo_0_2"), SEED_PASSWORD)
            assert first["created"]["users"] == 4
            assert not any(
                import_bundle(db, load_bundle(ROOT / "demo_data/demo_0_2"))["created"].values()
            )
        yield api
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


def create(client):
    assert login(client, password=SEED_PASSWORD).status_code == 200
    company = client.get("/api/companies").json()["items"][0]["id"]
    product = client.get("/api/products").json()["items"][0]["id"]
    response = client.post(
        "/api/applications",
        headers=csrf_headers(client),
        json={
            "company_id": company,
            "product_id": product,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_postgres_draft_round_trip_restart_and_access(postgres_app):
    with postgres_app() as client:
        draft = create(client)
        saved = client.patch(
            f"/api/applications/{draft['id']}",
            headers=csrf_headers(client),
            json={
                "expected_version": 1,
                "requested_amount": "1000000.00",
                "term_months": 12,
                "purpose_code": "INVENTORY",
                "ui_step": "FINANCES",
            },
        )
        assert saved.status_code == 200 and saved.json()["version"] == 2
        cookie = client.cookies.get("credit_session")
    with postgres_app() as client:
        client.cookies.set("credit_session", cookie)
        restored = client.get(f"/api/applications/{draft['id']}").json()
        assert restored["requested_amount"] == "1000000.00"
        assert (
            client.get("/api/auth/me").json()["user"]["ui_context"]["last_application_id"]
            == draft["id"]
        )
        assert login(client, "client2@example.com", SEED_PASSWORD).status_code == 200
        assert client.get(f"/api/applications/{draft['id']}").status_code == 404


def test_postgres_two_writers_cannot_overwrite_each_other(postgres_app):
    with postgres_app() as client:
        draft = create(client)
        cookie = client.cookies.get("credit_session")
        factory = client.app.state.session_factory
        auth = client.app.state.auth
        barrier = Barrier(2)

        def writer(amount):
            with factory() as db:
                principal = auth.authenticate(db, cookie)
                barrier.wait(timeout=10)
                try:
                    result = patch_draft(
                        db,
                        principal,
                        UUID(draft["id"]),
                        DraftPatch(expected_version=1, requested_amount=amount),
                        auth,
                    )
                    return 200, result.requested_amount
                except APIError as exc:
                    return exc.status_code, exc.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(writer, ["1000000.00", "2000000.00"]))
        assert sorted(status for status, _value in outcomes) == [200, 409]
        assert next(value for status, value in outcomes if status == 409) == "VERSION_CONFLICT"
        restored = client.get(f"/api/applications/{draft['id']}").json()
        assert restored["version"] == 2
        assert restored["requested_amount"] in {"1000000.00", "2000000.00"}


@pytest.mark.parametrize("same_key", [True, False])
def test_postgres_concurrent_submissions_are_idempotent(postgres_app, same_key):
    with postgres_app() as client:
        draft = create(client)
        response = client.patch(
            f"/api/applications/{draft['id']}",
            json={
                "expected_version": 1,
                "requested_amount": "1000000.00",
                "term_months": 12,
                "purpose_code": "INVENTORY",
                "draft_data": {
                    "confirmations": {"data_confirmed": True, "credit_history_check_allowed": True}
                },
            },
            headers=csrf_headers(client),
        )
        assert response.status_code == 200, response.text
        draft = response.json()
        cookie = client.cookies.get("credit_session")
        factory = client.app.state.session_factory
        auth = client.app.state.auth
        sources = client.app.state.sources
        barrier = Barrier(2)
        first_key = uuid4()
        keys = [first_key, first_key if same_key else uuid4()]

        def writer(key):
            with factory() as db:
                principal = auth.authenticate(db, cookie)
                barrier.wait(timeout=10)
                try:
                    application, revision = submit(
                        db,
                        principal,
                        UUID(draft["id"]),
                        SubmitRequest(expected_version=draft["version"], submission_key=key),
                        auth,
                        sources,
                    )
                    return 200, str(revision.id)
                except APIError as exc:
                    return exc.status_code, exc.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(writer, keys))
        assert sorted(status for status, _ in results) == ([200, 200] if same_key else [200, 409])
        if same_key:
            assert results[0][1] == results[1][1]
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(ApplicationRevision)) == 1
            assert db.scalar(select(func.count()).select_from(Assessment)) == 1
            assert db.scalar(select(func.count()).select_from(Decision)) == 1
        restored = client.get(f"/api/applications/{draft['id']}").json()
        assert restored["status"] == "APPROVED" and restored["assessment"]["risk_score"] == 10


def test_postgres_snapshot_trigger_and_application_restart(postgres_app):
    with postgres_app() as client:
        draft = create(client)
        draft = client.patch(
            f"/api/applications/{draft['id']}",
            json={
                "expected_version": 1,
                "requested_amount": "1000000.00",
                "term_months": 12,
                "purpose_code": "INVENTORY",
                "draft_data": {
                    "confirmations": {"data_confirmed": True, "credit_history_check_allowed": True}
                },
            },
            headers=csrf_headers(client),
        ).json()
        body = client.post(
            f"/api/applications/{draft['id']}/submit",
            json={"expected_version": draft["version"], "submission_key": str(uuid4())},
            headers=csrf_headers(client),
        ).json()
        frozen = body["revision"]
        cookies = dict(client.cookies)
        with client.app.state.session_factory() as db:
            with pytest.raises(IntegrityError, match="immutable"):
                db.execute(
                    update(ApplicationRevision)
                    .where(ApplicationRevision.id == UUID(frozen["id"]))
                    .values(input_hash="c" * 64)
                )
            db.rollback()
    with postgres_app() as restarted:
        restarted.cookies.update(cookies)
        assert restarted.get(f"/api/applications/{draft['id']}/revisions/1").json() == frozen
        current = restarted.get(f"/api/applications/{draft['id']}").json()
        assert (
            current["status"] == "APPROVED"
            and current["decision"]["id"] == body["application"]["decision"]["id"]
        )
