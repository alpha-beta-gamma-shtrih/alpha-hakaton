"""Structured console logs; no request bodies, headers or exception messages."""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from traceback import walk_tb

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)

_CONSOLE_HANDLER = "credit_cabinet.console"
_FIELDS = (
    "method",
    "route",
    "status_code",
    "duration_ms",
    "error_code",
    "error_type",
    "user_id",
    "role",
    "reason",
    "traceback",
)


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "request_id": request_id_context.get(),
        }
        for key in _FIELDS:
            if key in record.__dict__:
                payload[key] = record.__dict__[key]
        # Deliberately do not format exc_info, stack_info, or arbitrary extra fields.
        return json.dumps(payload, ensure_ascii=False, allow_nan=False)


def exception_fields(exc: BaseException) -> dict:
    """Record useful stack locations without str(exc), source lines or local values."""
    stack = []
    pending = [exc]
    seen = set()
    while pending and len(stack) < 8:
        current = pending.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        frames = [
            {
                "file": Path(frame.f_code.co_filename).name,
                "function": frame.f_code.co_name,
                "line": line,
            }
            for frame, line in walk_tb(current.__traceback__)
        ]
        stack.append({"error_type": type(current).__name__, "frames": frames[-50:]})
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        elif not current.__suppress_context__ and current.__context__ is not None:
            pending.append(current.__context__)
        if isinstance(current, BaseExceptionGroup):
            pending.extend(current.exceptions[:8])
    return {"error_type": type(exc).__name__, "traceback": stack}


def configure_logging(level: str = "INFO") -> None:
    logger = logging.getLogger("credit_cabinet")
    # Reconfiguration (including app restarts in tests) must not duplicate output.
    for handler in logger.handlers[:]:
        if handler.name == _CONSOLE_HANDLER:
            logger.removeHandler(handler)
            handler.close()
    handler = logging.StreamHandler(sys.stdout)
    handler.name = _CONSOLE_HANDLER
    handler.setFormatter(JSONFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
