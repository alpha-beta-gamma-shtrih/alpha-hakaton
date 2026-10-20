import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from credit_cabinet.main import create_app


def test_health_and_readiness(app, client):
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").json()["schema_revision"] == "0002_revision_immutability"


def test_startup_does_not_create_tables(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/health/live").status_code == 200
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["code"] == "DATABASE_NOT_READY"


def test_production_rejects_http_and_insecure_cookies(settings):
    from credit_cabinet.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(
            **{
                **settings.model_dump(),
                "app_env": "production",
                "database_url": "postgresql+psycopg://unused@localhost/unused",
                "csrf_signing_key": "test-secret-more-than-32-characters",
            }
        )


def test_no_cors_credentials_are_exposed(client):
    response = client.get("/api/auth/csrf", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_unknown_route_has_error_contract(client):
    response = client.get("/api/unknown")
    assert response.status_code == 404
    assert response.json()["code"] == "HTTP_404"


def test_configuration_errors_hide_secret_input(settings):
    from credit_cabinet.core.config import Settings

    secret = "replace-secret-that-must-not-appear-in-validation-output"
    with pytest.raises(ValidationError) as exc:
        Settings.model_validate({**settings.model_dump(), "csrf_signing_key": secret})
    assert secret not in str(exc.value)
