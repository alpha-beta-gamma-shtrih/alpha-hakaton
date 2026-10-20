import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

from credit_cabinet.core.logging import exception_fields
from credit_cabinet.schemas.errors import ErrorResponse

logger = logging.getLogger(__name__)


class APIError(Exception):
    def __init__(self, status_code: int, code: str, message: str, headers=None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers


def error_response(
    request: Request, status: int, code: str, message: str, fields=None, headers=None
):
    request.state.error_code = code
    body = ErrorResponse(
        code=code,
        message=message,
        field_errors=fields or [],
        request_id=request.state.request_id,
    )
    return JSONResponse(status_code=status, content=body.model_dump(), headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def handle_api_error(request: Request, exc: APIError):
        if exc.code in {"CSRF_INVALID", "ORIGIN_FORBIDDEN", "ROLE_FORBIDDEN"}:
            fields = {"reason": exc.code}
            if getattr(request.state, "user_id", None):
                fields["user_id"] = request.state.user_id
            logger.warning("auth.request_rejected", extra=fields)
        return error_response(request, exc.status_code, exc.code, exc.message, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, exc: RequestValidationError):
        # Never echo input values: validation bodies may contain passwords.
        fields = [
            {
                "field": ".".join(str(part) for part in error["loc"][1:]),
                "message": "Некорректное значение"
                if error["type"] != "missing"
                else "Обязательное поле",
            }
            for error in exc.errors()
        ]
        return error_response(request, 422, "VALIDATION_ERROR", "Проверьте поля запроса", fields)

    @app.exception_handler(HTTPException)
    async def handle_http(request: Request, exc: HTTPException):
        messages = {404: "Ресурс не найден", 405: "Метод не поддерживается"}
        return error_response(
            request,
            exc.status_code,
            f"HTTP_{exc.status_code}",
            messages.get(exc.status_code, "Запрос не выполнен"),
            headers=exc.headers,
        )

    @app.exception_handler(SQLAlchemyError)
    async def handle_database(request: Request, exc: SQLAlchemyError):
        logger.error("database.error", extra=exception_fields(exc))
        return error_response(
            request, 503, "DATABASE_UNAVAILABLE", "База данных временно недоступна"
        )
