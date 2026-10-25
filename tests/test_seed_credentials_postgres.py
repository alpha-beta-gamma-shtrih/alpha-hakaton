"""Fresh-install credentials are checked only inside a disposable PostgreSQL schema."""

import os
import sys
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, event, select

from credit_cabinet.core.security import verify_password
from credit_cabinet.db.session import build_session_factory
from credit_cabinet.main import create_app
from credit_cabinet.models import User
from credit_cabinet.services.seed import load_bundle
from tests.conftest import ROOT, login, migrate

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="PostgreSQL URL required"
)


def test_fresh_noninteractive_init_all_credentials_and_restart(settings, monkeypatch, capsys):
    from credit_cabinet import seed

    url = os.environ["TEST_DATABASE_URL"]
    assert url.startswith("postgresql+psycopg://")
    schema = "test_credentials_" + uuid4().hex
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

    settings.database_url = SecretStr(url)
    settings.demo_dataset_dir = ROOT / "demo_data/demo_0_3"
    settings.demo_user_password = None
    bundle = load_bundle(settings.demo_dataset_dir)
    try:
        migrate(engine)
        monkeypatch.setattr(seed, "Settings", lambda: settings)
        monkeypatch.setattr(seed, "build_engine", lambda _settings: engine)
        monkeypatch.setattr(sys, "argv", ["credit-cabinet-seed"])
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        seed.main()
        with build_session_factory(engine)() as db:
            before = dict(db.execute(select(User.email, User.password_hash)).all())
            assert len(before) == 146
            for row in bundle.users:
                password = row.password.get_secret_value()
                assert before[row.email] != password
                assert verify_password(before[row.email], password)
        seed.main()
        with build_session_factory(engine)() as db:
            assert dict(db.execute(select(User.email, User.password_hash)).all()) == before
        # Create the app twice: credentials survive API restart as well as repeated init.
        for _ in range(2):
            app = create_app(settings)
            with TestClient(app) as client:
                app.state.engine.dispose()
                app.state.engine = engine
                app.state.session_factory = build_session_factory(engine)
                for row in [*bundle.users[:5], bundle.users[-1]]:
                    assert (
                        login(client, str(row.email), row.password.get_secret_value()).status_code
                        == 200
                    )
                    me = client.get("/api/auth/me")
                    assert me.status_code == 200 and me.json()["user"]["role"] == row.role
                    assert "password" not in me.text
                    endpoint = (
                        "/api/companies" if row.role == "CLIENT" else "/api/bank/applications"
                    )
                    assert client.get(endpoint).status_code == 200
        output = capsys.readouterr().out
        assert all(row.password.get_secret_value() not in output for row in bundle.users)
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()
