import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from credit_cabinet.api import auth, health
from credit_cabinet.api.errors import install_error_handlers
from credit_cabinet.core.config import Settings
from credit_cabinet.core.logging import configure_logging
from credit_cabinet.db.session import build_engine, build_session_factory
from credit_cabinet.schemas.errors import ErrorResponse
from credit_cabinet.services.auth import AuthService

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging()
        app.state.settings = settings
        app.state.engine = build_engine(settings)
        app.state.session_factory = build_session_factory(app.state.engine)
        app.state.auth = AuthService(settings)
        try:
            yield
        finally:
            app.state.engine.dispose()

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
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error(
                "unhandled_error request_id=%s type=%s",
                request.state.request_id,
                type(exc).__name__,
            )
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
        return response

    app.include_router(auth.router)
    app.include_router(health.router)
    return app
