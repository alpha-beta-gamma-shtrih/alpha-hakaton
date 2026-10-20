import secrets

from fastapi import APIRouter, Request, Response

from credit_cabinet.api.dependencies import Authenticated, CSRFToken, Database, check_origin
from credit_cabinet.api.errors import APIError
from credit_cabinet.core.constants import (
    LOGIN_COOKIE,
    PREAUTH_TTL_SECONDS,
    SESSION_COOKIE,
)
from credit_cabinet.models.enums import FormStep
from credit_cabinet.schemas.auth import CSRFResponse, LoginRequest, SessionResponse, UserResponse
from credit_cabinet.schemas.errors import ErrorResponse
from credit_cabinet.services.auth import Principal

router = APIRouter(
    prefix="/api/auth",
    tags=["auth"],
    responses={status: {"model": ErrorResponse} for status in (401, 403, 422, 429, 503)},
)


def session_view(principal: Principal) -> SessionResponse:
    # Only expose known UI keys, never return a complete ORM object.
    context = principal.user.ui_context or {}
    safe_context = {}
    if context.get("section") in {"overview", "applications", "bank"}:
        safe_context["section"] = context["section"]
    if context.get("step") in {step.value for step in FormStep}:
        safe_context["step"] = context["step"]
    # Last application is resolved with ownership checks by future application APIs.
    return SessionResponse(
        user=UserResponse(
            id=principal.user.id,
            email=principal.user.email,
            display_name=principal.user.display_name,
            role=principal.user.role,
            ui_context=safe_context,
        ),
        absolute_expires_at=principal.session.absolute_expires_at,
        idle_expires_at=principal.session.idle_expires_at,
    )


@router.get("/csrf", response_model=CSRFResponse)
def csrf_context(request: Request, response: Response, db: Database):
    auth = request.app.state.auth
    principal = auth.authenticate(db, request.cookies.get(SESSION_COOKIE))
    if principal:
        request.state.user_id = str(principal.user.id)
        request.state.role = principal.user.role.value
        return CSRFResponse(csrf_token=principal.session.csrf_token)
    csrf, signed_cookie = auth.preauth_context()
    response.set_cookie(
        LOGIN_COOKIE,
        signed_cookie,
        max_age=PREAUTH_TTL_SECONDS,
        httponly=True,
        secure=request.app.state.settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return CSRFResponse(csrf_token=csrf)


@router.post("/login", response_model=SessionResponse)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Database,
    csrf_token: CSRFToken = None,
):
    check_origin(request)
    auth = request.app.state.auth
    current = auth.authenticate(db, request.cookies.get(SESSION_COOKIE))
    if current is not None:
        if not csrf_token or not secrets.compare_digest(
            csrf_token.encode(), current.session.csrf_token.encode()
        ):
            raise APIError(403, "CSRF_INVALID", "Некорректный CSRF-токен")
    else:
        auth.check_preauth(request.cookies.get(LOGIN_COOKIE), csrf_token)
    principal, raw_token = auth.login(
        db,
        str(body.email),
        body.password.get_secret_value(),
        request.client.host if request.client else "unknown",
        request.cookies.get(SESSION_COOKIE),
    )
    request.state.user_id = str(principal.user.id)
    request.state.role = principal.user.role.value
    absolute_ttl, _ = auth.ttls(principal.user.role)
    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        max_age=absolute_ttl,
        httponly=True,
        secure=request.app.state.settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    response.delete_cookie(
        LOGIN_COOKIE,
        path="/",
        secure=request.app.state.settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return session_view(principal)


@router.get("/me", response_model=SessionResponse)
def me(principal: Authenticated):
    return session_view(principal)


@router.post("/activity", response_model=SessionResponse)
def activity(request: Request, db: Database, principal: Authenticated):
    request.app.state.auth.activity(db, principal)
    return session_view(principal)


@router.post("/logout", status_code=204)
def logout(request: Request, db: Database, principal: Authenticated):
    request.app.state.auth.logout(db, principal)
    response = Response(status_code=204)
    for name in (SESSION_COOKIE, LOGIN_COOKIE):
        response.delete_cookie(
            name,
            path="/",
            httponly=True,
            secure=request.app.state.settings.cookie_secure,
            samesite="lax",
        )
    return response
