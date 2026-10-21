from datetime import timedelta
from typing import Annotated

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from itsdangerous.timed import TimestampSigner
from sqlalchemy import select

from credit_cabinet.api.dependencies import require_bank_staff
from credit_cabinet.core.constants import LOGIN_COOKIE, SESSION_COOKIE
from credit_cabinet.core.security import token_hash, utc_now
from credit_cabinet.main import create_app
from credit_cabinet.models import AuthSession, User
from credit_cabinet.services.auth import Principal
from tests.conftest import PASSWORD, csrf_headers, login


def test_login_cookie_and_no_secret_in_response(app, client):
    response = login(client, " CLIENT@example.com ")
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "CLIENT"
    assert "password" not in response.text
    assert "csrf" not in response.text
    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(value for value in cookies if value.startswith(SESSION_COOKIE + "="))
    assert "HttpOnly" in session_cookie and "SameSite=lax" in session_cookie
    assert "Max-Age=28800" in session_cookie and "Path=/" in session_cookie
    raw = client.cookies.get(SESSION_COOKIE)
    assert len(raw) >= 43
    with app.state.session_factory() as db:
        session = db.scalar(select(AuthSession))
        user = db.scalar(select(User).where(User.email == "client@example.com"))
        assert session.token_hash == token_hash(raw) and session.token_hash != raw
        assert user.password_hash.startswith("$argon2id$")
        assert PASSWORD not in user.password_hash
        assert session.absolute_expires_at - session.created_at == timedelta(hours=8)
        assert session.idle_expires_at - session.created_at == timedelta(hours=1)
    assert client.get("/api/auth/me").status_code == 200


def test_unauthenticated_and_malformed_session(client):
    response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert response.headers["cache-control"] == "no-store"
    client.cookies.set(SESSION_COOKIE, "x" * 200)
    assert client.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize(
    "email,password",
    [
        ("client@example.com", "wrong-password"),
        ("missing@example.com", "wrong-password"),
    ],
)
def test_uniform_invalid_credentials(client, email, password):
    response = login(client, email, password)
    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"
    assert SESSION_COOKIE not in client.cookies


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "http://testserver"},
        {"Origin": "https://evil.example", "X-CSRF-Token": "invalid"},
        {"Origin": "null", "X-CSRF-Token": "invalid"},
    ],
)
def test_login_requires_origin_and_csrf(client, headers):
    client.get("/api/auth/csrf")
    response = client.post(
        "/api/auth/login",
        json={
            "email": "client@example.com",
            "password": PASSWORD,
        },
        headers=headers,
    )
    assert response.status_code == 403


def test_preauth_token_is_bound_to_cookie(client):
    first = client.get("/api/auth/csrf").json()["csrf_token"]
    second = client.get("/api/auth/csrf").json()["csrf_token"]
    assert first != second
    response = client.post(
        "/api/auth/login",
        json={
            "email": "client@example.com",
            "password": PASSWORD,
        },
        headers={"Origin": "http://testserver", "X-CSRF-Token": first},
    )
    assert response.status_code == 403


def test_non_ascii_csrf_is_rejected_without_server_error(client):
    client.get("/api/auth/csrf")
    response = client.post(
        "/api/auth/login",
        json={"email": "client@example.com", "password": PASSWORD},
        headers={b"Origin": b"http://testserver", b"X-CSRF-Token": b"\xff"},
    )
    assert response.status_code == 403


def test_tampered_preauth_cookie(client):
    csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    signed_cookie = client.cookies.get(LOGIN_COOKIE)
    client.cookies.clear()
    client.cookies.set(LOGIN_COOKIE, "invalid." + signed_cookie)
    response = client.post(
        "/api/auth/login",
        json={"email": "client@example.com", "password": PASSWORD},
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
    )
    assert response.status_code == 403


def test_expired_preauth(client, monkeypatch):
    original_timestamp = TimestampSigner.get_timestamp
    with monkeypatch.context() as context:
        context.setattr(
            TimestampSigner, "get_timestamp", lambda self: original_timestamp(self) - 700
        )
        csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    response = client.post(
        "/api/auth/login",
        json={
            "email": "client@example.com",
            "password": PASSWORD,
        },
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
    )
    assert response.status_code == 403


def test_login_rotates_session_and_revokes_old(app, client):
    assert login(client).status_code == 200
    old_token = client.cookies.get(SESSION_COOKIE)
    assert login(client).status_code == 200
    assert client.cookies.get(SESSION_COOKIE) != old_token
    with app.state.session_factory() as db:
        old_session = db.scalar(
            select(AuthSession).where(AuthSession.token_hash == token_hash(old_token))
        )
        assert old_session.revoked_at is not None
    client.cookies.clear()
    client.cookies.set(SESSION_COOKIE, old_token)
    assert client.get("/api/auth/me").status_code == 401


def test_logout_revokes_cookie_and_db_session(app, client):
    login(client)
    token = client.cookies.get(SESSION_COOKIE)
    headers = csrf_headers(client)
    assert client.post("/api/auth/logout").status_code == 403
    response = client.post("/api/auth/logout", headers=headers)
    assert response.status_code == 204
    assert SESSION_COOKIE not in client.cookies
    with app.state.session_factory() as db:
        session = db.scalar(select(AuthSession))
        assert session.revoked_at is not None
    client.cookies.set(SESSION_COOKIE, token)
    assert client.get("/api/auth/me").status_code == 401


def test_session_survives_api_restart(client, settings):
    login(client)
    token = client.cookies.get(SESSION_COOKIE)
    with TestClient(create_app(settings)) as restarted:
        restarted.cookies.set(SESSION_COOKIE, token)
        assert restarted.get("/api/auth/me").status_code == 200


@pytest.mark.parametrize("absolute", [False, True])
def test_expiry_is_enforced_by_server(app, client, absolute):
    login(client)
    now = utc_now()
    with app.state.session_factory() as db:
        session = db.scalar(select(AuthSession))
        session.created_at = now - timedelta(hours=10)
        session.last_activity_at = now - timedelta(hours=9)
        session.idle_expires_at = now - timedelta(seconds=2)
        session.absolute_expires_at = (
            now - timedelta(seconds=1) if absolute else now + timedelta(hours=1)
        )
        db.commit()
    assert client.get("/api/auth/me").status_code == 401


def test_polling_does_not_refresh_idle_but_activity_does(app, client, monkeypatch):
    login(client)
    with app.state.session_factory() as db:
        before = db.scalar(select(AuthSession)).idle_expires_at
    later = utc_now() + timedelta(minutes=10)
    monkeypatch.setattr("credit_cabinet.services.auth.utc_now", lambda: later)
    for _ in range(3):
        assert client.get("/api/auth/me").status_code == 200
        client.get("/api/auth/csrf")
    with app.state.session_factory() as db:
        assert db.scalar(select(AuthSession)).idle_expires_at == before
    assert client.post("/api/auth/activity", headers=csrf_headers(client)).status_code == 200
    with app.state.session_factory() as db:
        session = db.scalar(select(AuthSession))
        assert session.idle_expires_at > before
        assert session.idle_expires_at <= session.absolute_expires_at


def test_inactive_user_is_denied_on_every_request(app, client):
    login(client)
    with app.state.session_factory() as db:
        user = db.scalar(select(User).where(User.email == "client@example.com"))
        user.is_active = False
        db.commit()
    assert client.get("/api/auth/me").status_code == 401
    assert login(client).json()["code"] == "INVALID_CREDENTIALS"


def test_bank_ttls_and_role_dependency(app, client):
    def bank_only(principal: Annotated[Principal, Depends(require_bank_staff)]):
        return {"role": principal.user.role}

    app.add_api_route("/api/test-bank", bank_only)
    login(client)
    assert client.get("/api/test-bank").status_code == 403
    response = login(client, "bank@example.com")
    assert response.status_code == 200
    assert client.get("/api/test-bank").status_code == 200
    with app.state.session_factory() as db:
        session = db.scalar(select(AuthSession).where(AuthSession.revoked_at.is_(None)))
        assert session.absolute_expires_at - session.created_at == timedelta(hours=4)
        assert session.idle_expires_at - session.created_at == timedelta(minutes=15)


def test_login_rate_limit(client, settings):
    for _ in range(settings.login_rate_limit):
        assert login(client, password="wrong").status_code == 401
    response = login(client, password="wrong")
    assert response.status_code == 429
    assert response.json()["code"] == "LOGIN_RATE_LIMITED"
    assert int(response.headers["retry-after"]) > 0


def test_validation_does_not_echo_password(client):
    secret = "never-log-this-password"
    response = client.post(
        "/api/auth/login",
        json={
            "email": "invalid",
            "password": secret,
            "role": "BANK_STAFF",
        },
    )
    assert response.status_code == 422
    assert secret not in response.text
    assert {error["field"] for error in response.json()["field_errors"]} == {"email", "role"}


def test_safe_context_filters_unknown_data(app, client):
    with app.state.session_factory() as db:
        user = db.scalar(select(User).where(User.email == "client@example.com"))
        user.ui_context = {
            "section": "applications",
            "step": "REVIEW",
            "redirect": "https://evil.example",
            "internal_comment": "secret",
        }
        db.commit()
    assert login(client).json()["user"]["ui_context"] == {
        "section": "applications",
        "step": "REVIEW",
    }


def test_secure_cookie_when_https(settings, password_hash):
    from sqlalchemy import create_engine

    from tests.conftest import migrate

    settings.cookie_secure = True
    settings.public_base_url = "https://testserver"
    settings.allowed_origins = ["https://testserver"]
    engine = create_engine(settings.database_url.get_secret_value())
    migrate(engine)
    engine.dispose()
    with TestClient(create_app(settings), base_url="https://testserver") as client:
        with client.app.state.session_factory() as db:
            db.add(
                User(
                    email="client@example.com",
                    display_name="Client",
                    role="CLIENT",
                    password_hash=password_hash,
                    is_active=True,
                    ui_context={},
                )
            )
            db.commit()
        csrf = client.get("/api/auth/csrf").json()["csrf_token"]
        assert "Secure" in client.headers.get("set-cookie", "") or LOGIN_COOKIE in client.cookies
        response = client.post(
            "/api/auth/login",
            json={"email": "client@example.com", "password": PASSWORD},
            headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
        )
        assert response.status_code == 200
        assert "Secure" in response.headers.get_list("set-cookie")[0]
        assert client.get("/api/auth/me").status_code == 200
