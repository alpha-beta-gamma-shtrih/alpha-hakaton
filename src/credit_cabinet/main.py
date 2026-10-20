import logging
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from credit_cabinet.api import auth, business, health
from credit_cabinet.api.errors import install_error_handlers
from credit_cabinet.core.config import Settings
from credit_cabinet.core.logging import configure_logging, exception_fields, request_id_context
from credit_cabinet.db.session import build_engine, build_session_factory
from credit_cabinet.schemas.errors import ErrorResponse
from credit_cabinet.services.auth import AuthService

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging(settings.log_level)
        app.state.settings = settings
        app.state.engine = build_engine(settings)
        app.state.session_factory = build_session_factory(app.state.engine)
        app.state.auth = AuthService(settings)
        try:
            logger.info("app.started")
            yield
        finally:
            app.state.engine.dispose()
            logger.info("app.stopped")

    app = FastAPI(
        title="Умный кредитный кабинет — demo-0.2",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    install_error_handlers(app)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = str(uuid4())
        context_token = request_id_context.set(request.state.request_id)
        started = perf_counter()
        try:
            try:
                response = await call_next(request)
            except Exception as exc:
                logger.error("request.failed", extra=exception_fields(exc))
                request.state.error_code = "INTERNAL_ERROR"
                response = JSONResponse(
                    status_code=500,
                    content=ErrorResponse(
                        code="INTERNAL_ERROR",
                        message="Внутренняя ошибка сервера",
                        request_id=request.state.request_id,
                    ).model_dump(),
                )
            response.headers["X-Request-ID"] = request.state.request_id
            response.headers["X-Content-Type-Options"] = "nosniff"
            if request.url.path.startswith("/api/"):
                response.headers["Cache-Control"] = "no-store"
            fields = {
                "method": request.method,
                "route": getattr(request.scope.get("route"), "path", "<unmatched>"),
                "status_code": response.status_code,
                "duration_ms": round((perf_counter() - started) * 1000, 3),
            }
            for key in ("error_code", "user_id", "role"):
                value = getattr(request.state, key, None)
                if value is not None:
                    fields[key] = value
            level = (
                logging.ERROR
                if response.status_code >= 500
                else (logging.WARNING if response.status_code >= 400 else logging.INFO)
            )
            logger.log(level, "http.request_completed", extra=fields)
            return response
        finally:
            request_id_context.reset(context_token)

    app.include_router(auth.router)
    app.include_router(business.router)
    app.include_router(health.router)
    return app
