import logging

from fastapi import APIRouter, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from credit_cabinet.api.errors import APIError
from credit_cabinet.core.constants import SCHEMA_REVISION
from credit_cabinet.core.logging import exception_fields

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/health/live")
def live():
    return {"status": "ok"}


@router.get("/health/ready")
def ready(request: Request):
    try:
        with request.app.state.engine.connect() as connection:
            versions = (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
            )
            if versions != [SCHEMA_REVISION]:
                raise APIError(503, "SCHEMA_NOT_READY", "Примените миграции базы данных")
    except SQLAlchemyError as exc:
        logger.error("database.error", extra=exception_fields(exc))
        raise APIError(503, "DATABASE_NOT_READY", "База данных или миграции не готовы") from None
    return {"status": "ready", "schema_revision": SCHEMA_REVISION}
