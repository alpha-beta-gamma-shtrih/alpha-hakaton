"""Optional real-PostgreSQL smoke test, isolated in a newly created schema."""

import os
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect, select, text

from credit_cabinet.core.config import Settings
from credit_cabinet.core.security import hash_password
from credit_cabinet.db.base import Base
from credit_cabinet.db.session import build_session_factory
from credit_cabinet.main import create_app
from credit_cabinet.models import CompanyFinancialMonth, User
from tests.conftest import PASSWORD, ROOT, csrf_headers, login, migrate
from tests.test_database import business_rows

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL for PostgreSQL integration",
)


def test_postgres_migration_auth_and_restart(settings):
    url = os.environ["TEST_DATABASE_URL"]
    assert url.startswith("postgresql+psycopg://"), "Use a psycopg PostgreSQL test URL"
    schema = "test_credit_" + uuid4().hex
    admin = create_engine(url, hide_parameters=True)
    engine = create_engine(url, hide_parameters=True)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    @event.listens_for(engine, "connect")
    def set_schema(connection, _record):
        # Persist connection setup outside the next test transaction's rollback.
        previous = connection.autocommit
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(f'SET search_path TO "{schema}"')
            cursor.execute("SET TIME ZONE 'UTC'")
        connection.autocommit = previous

    @contextmanager
    def api():
        app = create_app(settings)
        with TestClient(app) as client:
            app.state.engine.dispose()
            app.state.engine = engine
            app.state.session_factory = build_session_factory(engine)
            yield client

    try:
        settings = Settings.model_validate({**settings.model_dump(), "database_url": url})
        migrate(engine)
        with engine.connect() as connection:
            assert len(inspect(connection).get_table_names()) == 16
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
            assert connection.execute(text("SHOW server_version")).scalar()
        config = Config(str(ROOT / "alembic.ini"))
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
            assert set(inspect(connection).get_table_names()) == {"alembic_version"}
            command.upgrade(config, "head")
        with build_session_factory(engine)() as db:
            db.add(
                User(
                    email="client@example.com",
                    display_name="Postgres client",
                    role="CLIENT",
                    password_hash=hash_password(PASSWORD),
                    is_active=True,
                    ui_context={},
                )
            )
            db.commit()
            _, company, _ = business_rows(db)
            db.add(
                CompanyFinancialMonth(
                    company_id=company.id,
                    month=date(2026, 9, 1),
                    cash_inflow=Decimal("12345.67"),
                    operating_outflow=Decimal("12.34"),
                    existing_debt_payment=Decimal("0"),
                    source="DEMO",
                )
            )
            db.commit()
            assert db.scalar(select(CompanyFinancialMonth)).cash_inflow == Decimal("12345.67")
        with api() as client:
            assert client.get("/health/ready").status_code == 200
            assert login(client).status_code == 200
            token = client.cookies.get("credit_session")
            assert (
                client.post("/api/auth/activity", headers=csrf_headers(client)).status_code == 200
            )
        with api() as restarted:
            restarted.cookies.set("credit_session", token)
            assert restarted.get("/api/auth/me").status_code == 200
            assert (
                restarted.post("/api/auth/logout", headers=csrf_headers(restarted)).status_code
                == 204
            )
            restarted.cookies.set("credit_session", token)
            assert restarted.get("/api/auth/me").status_code == 401
    finally:
        engine.dispose()
        # schema is generated above from uuid4, never taken from a user-provided path/name.
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
