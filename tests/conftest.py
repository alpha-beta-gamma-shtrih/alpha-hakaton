from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from credit_cabinet.core.config import Settings
from credit_cabinet.core.security import hash_password
from credit_cabinet.main import create_app
from credit_cabinet.models import User
from credit_cabinet.models.enums import Role

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "Test-password-only-29!"
SEED_PASSWORD = "New-demo-password-only-26!"


def migrate(engine, revision="head"):
    config = Config(str(ROOT / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, revision)


@pytest.fixture(scope="session")
def password_hash():
    return hash_password(PASSWORD)


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{(tmp_path / 'test.sqlite').as_posix()}",
        csrf_signing_key="test-only-csrf-secret-with-at-least-32-characters",
        public_base_url="http://testserver",
        allowed_origins=["http://testserver"],
        cookie_secure=False,
        documents_dir=tmp_path / "documents",
        llm_enabled=False,
        demo_dataset_dir=ROOT / "demo_data/demo_0_2",
    )


@pytest.fixture
def app(settings, password_hash):
    migrate(create_engine(settings.database_url.get_secret_value()))
    app = create_app(settings)
    with TestClient(app) as client:
        with app.state.session_factory() as db:
            db.add_all(
                [
                    User(
                        email="client@example.com",
                        display_name="Client",
                        role=Role.CLIENT,
                        password_hash=password_hash,
                        is_active=True,
                        ui_context={},
                    ),
                    User(
                        email="bank@example.com",
                        display_name="Bank",
                        role=Role.BANK_STAFF,
                        password_hash=password_hash,
                        is_active=True,
                        ui_context={},
                    ),
                ]
            )
            db.commit()
        app.state.test_client = client
        yield app


@pytest.fixture
def client(app):
    return app.state.test_client


@pytest.fixture
def seeded(app):
    from credit_cabinet.services.seed import import_bundle, load_bundle

    with app.state.session_factory() as db:
        import_bundle(db, load_bundle(ROOT / "demo_data/demo_0_2"), SEED_PASSWORD)
    return app


def login(client, email="client@example.com", password=PASSWORD):
    csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    return client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
    )


def csrf_headers(client):
    return {
        "Origin": "http://testserver",
        "X-CSRF-Token": client.get("/api/auth/csrf").json()["csrf_token"],
    }
