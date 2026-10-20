import asyncio
import json
import logging
from datetime import timedelta
from io import StringIO
from uuid import UUID

import pytest
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from credit_cabinet.core.logging import JSONFormatter, configure_logging, request_id_context
from credit_cabinet.core.security import utc_now
from credit_cabinet.models import AuthSession
from tests.conftest import PASSWORD, csrf_headers, login


@pytest.fixture
def logs(app):
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JSONFormatter())
    logger = logging.getLogger("credit_cabinet")
    logger.addHandler(handler)
    try:
        yield stream
    finally:
        logger.removeHandler(handler)
        handler.close()


def entries(logs, event):
    return [
        row for line in logs.getvalue().splitlines() if (row := json.loads(line))["event"] == event
    ]


def test_http_log_uses_template_and_omits_input(app, client, logs):
    async def endpoint(request: Request, item_id: str):
        return {"ok": True}

    app.add_api_route("/api/test-items/{item_id}", endpoint, methods=["POST"])
    response = client.post(
        "/api/test-items/private-path-value?password=private-query-value",
        json={"password": "private-body-value"},
        headers={
            "X-CSRF-Token": "private-csrf-value",
            "Cookie": "credit_session=private-cookie-value",
            "Authorization": "Bearer private-header-value",
            "X-Request-ID": "forged-id",
        },
    )
    assert response.status_code == 200
    (row,) = entries(logs, "http.request_completed")
    assert row["method"] == "POST"
    assert row["route"] == "/api/test-items/{item_id}"
    assert row["status_code"] == 200 and row["duration_ms"] >= 0
    assert row["request_id"] == response.headers["x-request-id"]
    UUID(row["request_id"])
    assert "private-" not in logs.getvalue() and "forged-id" not in logs.getvalue()


def test_unknown_path_is_not_logged_verbatim(client, logs):
    response = client.get("/private-unknown-path?token=private-query")
    assert response.status_code == 404
    (row,) = entries(logs, "http.request_completed")
    assert row["route"] == "<unmatched>" and row["error_code"] == "HTTP_404"
    assert row["level"] == "WARNING"
    assert "private-" not in logs.getvalue()


def test_login_logout_logs_correlate_without_secrets(client, logs):
    response = login(client)
    assert response.status_code == 200
    cookie = client.cookies.get("credit_session")
    headers = csrf_headers(client)
    logout = client.post("/api/auth/logout", headers=headers)
    assert logout.status_code == 204
    (success,) = entries(logs, "auth.login_succeeded")
    assert success["user_id"] == response.json()["user"]["id"]
    assert success["role"] == "CLIENT"
    assert success["request_id"] == response.headers["x-request-id"]
    (closed,) = entries(logs, "auth.logout_succeeded")
    assert closed["request_id"] == logout.headers["x-request-id"]
    assert cookie not in logs.getvalue()
    assert headers["X-CSRF-Token"] not in logs.getvalue()
    assert PASSWORD not in logs.getvalue() and "client@example.com" not in logs.getvalue()


def test_failed_login_and_limit_are_logged(client, logs, settings):
    for _ in range(settings.login_rate_limit):
        assert login(client, password="private-wrong-password").status_code == 401
    response = login(client, password="private-wrong-password")
    assert response.status_code == 429
    assert len(entries(logs, "auth.login_failed")) == settings.login_rate_limit
    (limited,) = entries(logs, "auth.login_rate_limited")
    assert limited["request_id"] == response.headers["x-request-id"]
    assert limited["level"] == "WARNING"
    assert "private-wrong-password" not in logs.getvalue()


def test_csrf_failure_is_logged_without_token(client, logs):
    login(client)
    response = client.post(
        "/api/auth/logout",
        headers={
            "Origin": "http://testserver",
            "X-CSRF-Token": "private-invalid-token",
        },
    )
    assert response.status_code == 403
    (rejected,) = entries(logs, "auth.request_rejected")
    assert rejected["reason"] == "CSRF_INVALID"
    assert rejected["request_id"] == response.headers["x-request-id"]
    assert "private-invalid-token" not in logs.getvalue()


def test_validation_fields_and_password_are_not_logged(client, logs):
    response = client.post(
        "/api/auth/login",
        json={
            "email": "private-invalid-email",
            "password": "private-secret-password",
        },
    )
    assert response.status_code == 422
    (row,) = entries(logs, "http.request_completed")
    assert row["error_code"] == "VALIDATION_ERROR"
    assert "private-" not in logs.getvalue()


@pytest.mark.parametrize("absolute", [False, True])
def test_expiry_event_uses_real_cause(app, client, logs, absolute):
    login(client)
    now = utc_now()
    with app.state.session_factory() as db:
        session = db.scalar(select(AuthSession))
        session.created_at = now - timedelta(hours=10)
        session.last_activity_at = now - timedelta(hours=9)
        session.idle_expires_at = now - timedelta(seconds=2)
        session.absolute_expires_at = (
            now + timedelta(hours=1) if not absolute else now - timedelta(seconds=1)
        )
        db.commit()
    response = client.get("/api/auth/me")
    assert response.status_code == 401
    (expired,) = entries(logs, "auth.session_expired")
    assert expired["reason"] == ("ABSOLUTE_TIMEOUT" if absolute else "IDLE_TIMEOUT")
    assert expired["request_id"] == response.headers["x-request-id"]


def test_unexpected_error_has_safe_stack_and_request_id(app, client, logs):
    def failing_endpoint():
        try:
            raise ValueError("private-inner-message")
        except ValueError as exc:
            raise RuntimeError("private-outer-message") from exc

    app.add_api_route("/api/test-failure", failing_endpoint)
    response = client.get("/api/test-failure")
    assert response.status_code == 500
    (error,) = entries(logs, "request.failed")
    assert error["request_id"] == response.json()["request_id"]
    assert error["error_type"] == "RuntimeError"
    assert {part["error_type"] for part in error["traceback"]} == {"RuntimeError", "ValueError"}
    assert any(
        frame["function"] == "failing_endpoint" and frame["line"] > 0
        for part in error["traceback"]
        for frame in part["frames"]
    )
    assert "private-" not in logs.getvalue() and "private-" not in response.text
    (completed,) = entries(logs, "http.request_completed")
    assert completed["error_code"] == "INTERNAL_ERROR" and completed["level"] == "ERROR"


def test_database_error_does_not_expose_sql_or_parameters(app, client, logs):
    def database_failure():
        raise OperationalError(
            "SELECT private-sql",
            {"password": "private-db-password"},
            RuntimeError("private-database-error"),
        )

    app.add_api_route("/api/test-database-failure", database_failure)
    response = client.get("/api/test-database-failure")
    assert response.status_code == 503
    (error,) = entries(logs, "database.error")
    assert error["error_type"] == "OperationalError"
    assert error["request_id"] == response.headers["x-request-id"]
    assert error["traceback"][0]["frames"]
    assert "private-" not in logs.getvalue()


def test_request_context_isolated_across_concurrent_tasks():
    async def worker(value):
        token = request_id_context.set(value)
        try:
            await asyncio.sleep(0)
            record = logging.makeLogRecord({"msg": "test.event", "levelname": "INFO"})
            return json.loads(JSONFormatter().format(record))["request_id"]
        finally:
            request_id_context.reset(token)

    async def run():
        return await asyncio.gather(worker("first"), worker("second"))

    assert asyncio.run(run()) == ["first", "second"]
    assert request_id_context.get() is None


def test_logging_configuration_is_idempotent_and_respects_level(capsys):
    configure_logging("WARNING")
    configure_logging("WARNING")
    logger = logging.getLogger("credit_cabinet.test")
    logger.info("test.hidden")
    logger.warning("test.visible", extra={"password": "private-extra-field"})
    rows = capsys.readouterr().out.splitlines()
    assert len(rows) == 1
    assert json.loads(rows[0])["event"] == "test.visible"
    assert "private-extra-field" not in rows[0]
    # Avoid leaving a handler attached to pytest's soon-to-be-closed capture stream.
    parent = logging.getLogger("credit_cabinet")
    for handler in parent.handlers[:]:
        if handler.name == "credit_cabinet.console":
            parent.removeHandler(handler)
            handler.close()
    parent.setLevel(logging.INFO)
