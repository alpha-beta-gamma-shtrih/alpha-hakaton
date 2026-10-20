import secrets
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Lock
from time import monotonic

from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from credit_cabinet.api.errors import APIError
from credit_cabinet.core.config import Settings
from credit_cabinet.core.constants import PREAUTH_TTL_SECONDS
from credit_cabinet.core.security import (
    hash_password,
    new_token,
    password_hasher,
    token_hash,
    utc_now,
    verify_password,
)
from credit_cabinet.models import AuthSession, User
from credit_cabinet.models.enums import Role


@dataclass
class Principal:
    user: User
    session: AuthSession


class LoginLimiter:
    """Bounded, per-process limiter for the single-worker demo deployment."""

    def __init__(self, limit: int, window: int):
        self.limit = limit
        self.window = window
        self.entries: OrderedDict[str, deque] = OrderedDict()
        self.lock = Lock()

    def check(self, address: str, email: str) -> None:
        now = monotonic()
        with self.lock:
            for key in (f"ip:{address}", f"account:{token_hash(email)}"):
                attempts = self.entries.get(key)
                if attempts is None:
                    continue
                while attempts and attempts[0] <= now - self.window:
                    attempts.popleft()
                if len(attempts) >= self.limit:
                    retry = max(1, int(self.window - (now - attempts[0])) + 1)
                    raise APIError(
                        429,
                        "LOGIN_RATE_LIMITED",
                        "Слишком много попыток входа",
                        headers={"Retry-After": str(retry)},
                    )
            for key in (f"ip:{address}", f"account:{token_hash(email)}"):
                self.entries.setdefault(key, deque()).append(now)
                self.entries.move_to_end(key)
            while len(self.entries) > 10000:
                self.entries.popitem(last=False)


class AuthService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.signer = URLSafeTimedSerializer(
            settings.csrf_signing_key.get_secret_value(), salt="credit-login-csrf-v1"
        )
        self.limiter = LoginLimiter(settings.login_rate_limit, settings.login_rate_window_seconds)
        # Compare unknown accounts against a real Argon2id hash too.
        self.dummy_hash = hash_password(new_token())

    def preauth_context(self) -> tuple[str, str]:
        csrf = new_token()
        return csrf, self.signer.dumps({"csrf": csrf})

    def check_preauth(self, cookie: str | None, header: str | None) -> None:
        try:
            data = self.signer.loads(cookie or "", max_age=PREAUTH_TTL_SECONDS)
            expected = data["csrf"]
        except (BadSignature, KeyError, TypeError):
            raise APIError(403, "CSRF_INVALID", "Обновите защитный контекст входа") from None
        if not header or not secrets.compare_digest(expected.encode(), header.encode()):
            raise APIError(403, "CSRF_INVALID", "Некорректный CSRF-токен")

    def authenticate(self, db: Session, raw_token: str | None) -> Principal | None:
        if not raw_token or len(raw_token) > 128:
            return None
        row = db.execute(
            select(AuthSession, User)
            .join(User, AuthSession.user_id == User.id)
            .where(AuthSession.token_hash == token_hash(raw_token))
        ).first()
        if row is None:
            return None
        session, user = row
        now = utc_now()
        if (
            not user.is_active
            or session.revoked_at is not None
            or session.absolute_expires_at <= now
            or session.idle_expires_at <= now
        ):
            return None
        return Principal(user=user, session=session)

    def login(
        self,
        db: Session,
        email: str,
        password: str,
        address: str,
        previous_token: str | None,
    ) -> tuple[Principal, str]:
        self.limiter.check(address, email)
        user = db.scalar(select(User).where(User.email == email))
        valid = verify_password(user.password_hash if user else self.dummy_hash, password)
        if user is None or not valid or not user.is_active:
            raise APIError(401, "INVALID_CREDENTIALS", "Неверный логин или пароль")
        if password_hasher.check_needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        now = utc_now()
        if previous_token and len(previous_token) <= 128:
            db.execute(
                update(AuthSession)
                .where(
                    AuthSession.token_hash == token_hash(previous_token),
                    AuthSession.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
        absolute_ttl, idle_ttl = self.ttls(user.role)
        raw = new_token()
        session = AuthSession(
            user_id=user.id,
            token_hash=token_hash(raw),
            csrf_token=new_token(),
            created_at=now,
            last_activity_at=now,
            absolute_expires_at=now + timedelta(seconds=absolute_ttl),
            idle_expires_at=now + timedelta(seconds=idle_ttl),
        )
        db.add(session)
        db.commit()
        return Principal(user, session), raw

    def ttls(self, role: Role) -> tuple[int, int]:
        if role == Role.BANK_STAFF:
            return (
                self.settings.bank_session_absolute_ttl_seconds,
                self.settings.bank_session_idle_ttl_seconds,
            )
        return (
            self.settings.client_session_absolute_ttl_seconds,
            self.settings.client_session_idle_ttl_seconds,
        )

    def activity(self, db: Session, principal: Principal) -> datetime:
        now = utc_now()
        _, idle_ttl = self.ttls(principal.user.role)
        idle_until = min(now + timedelta(seconds=idle_ttl), principal.session.absolute_expires_at)
        count = db.execute(
            update(AuthSession)
            .where(
                AuthSession.id == principal.session.id,
                AuthSession.revoked_at.is_(None),
                AuthSession.absolute_expires_at > now,
                AuthSession.idle_expires_at > now,
            )
            .values(last_activity_at=now, idle_expires_at=idle_until)
        ).rowcount
        if count != 1:
            raise APIError(401, "AUTH_REQUIRED", "Требуется повторный вход")
        db.commit()
        return idle_until

    def logout(self, db: Session, principal: Principal) -> None:
        db.execute(
            update(AuthSession)
            .where(AuthSession.id == principal.session.id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=utc_now())
        )
        db.commit()
