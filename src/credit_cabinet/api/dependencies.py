import secrets
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from credit_cabinet.api.errors import APIError
from credit_cabinet.core.constants import CSRF_HEADER, SESSION_COOKIE
from credit_cabinet.models.enums import Role
from credit_cabinet.services.auth import Principal


def get_db(request: Request):
    with request.app.state.session_factory() as db:
        yield db


Database = Annotated[Session, Depends(get_db)]
CSRFToken = Annotated[str | None, Header(alias=CSRF_HEADER, max_length=128)]


def check_origin(request: Request) -> None:
    if request.headers.get("origin") not in request.app.state.settings.allowed_origins:
        raise APIError(403, "ORIGIN_FORBIDDEN", "Недопустимый источник запроса")


def require_principal(request: Request, db: Database, csrf_token: CSRFToken = None) -> Principal:
    principal = request.app.state.auth.authenticate(db, request.cookies.get(SESSION_COOKIE))
    if principal is None:
        raise APIError(401, "AUTH_REQUIRED", "Требуется повторный вход")
    request.state.user_id = str(principal.user.id)
    request.state.role = principal.user.role.value
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_origin(request)
        if not csrf_token or not secrets.compare_digest(
            csrf_token.encode(), principal.session.csrf_token.encode()
        ):
            raise APIError(403, "CSRF_INVALID", "Некорректный CSRF-токен")
    return principal


Authenticated = Annotated[Principal, Depends(require_principal)]


def require_client(principal: Authenticated) -> Principal:
    if principal.user.role != Role.CLIENT:
        raise APIError(403, "ROLE_FORBIDDEN", "Требуется клиентская учетная запись")
    return principal


def require_bank_staff(principal: Authenticated) -> Principal:
    if principal.user.role != Role.BANK_STAFF:
        raise APIError(403, "ROLE_FORBIDDEN", "Требуется учетная запись сотрудника банка")
    return principal
