"""Bounded synchronous HTTP, used by FastAPI's worker thread, never its event loop."""

import http.client
import json
import re
from dataclasses import dataclass
from threading import BoundedSemaphore
from time import monotonic
from urllib.parse import urlsplit

from pydantic import ValidationError

from credit_cabinet.schemas.advisor import ModelNarrative

PROMPT_VERSION = "advisor-priority-0.3.0"
GENERATION_CONFIG = {"temperature": 0, "seed": 42, "num_ctx": 2048, "num_predict": 384}
SYSTEM_PROMPT = """Ты объясняешь предпринимателю заявку на банковский кредит.
Объясни два переданных факта простым русским языком для клиента.
Верни JSON: benefit — одно предложение о пользе, tradeoff — одно предложение о цене
компромисса или ограничении. Не выбирай другой вариант, не выдумывай условия.
Раскрой практический смысл для бюджета бизнеса. Не используй числа.
Только два предложения, без вступления. Сравнения только с исходным запросом.
"""


@dataclass
class Generation:
    selection: ModelNarrative | None
    error_code: str | None
    model_id: str | None = None
    model_digest: str | None = None


class ModelFailure(Exception):
    pass


class OllamaAdvisor:
    def __init__(self, settings):
        self.settings = settings
        self.slots = BoundedSemaphore(settings.llm_max_parallel)

    def request(self, method, path, body, deadline, max_bytes):
        target = urlsplit(self.settings.llm_base_url)
        connection = http.client.HTTPConnection(target.hostname, target.port or 80)
        try:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError
            connection.timeout = remaining
            payload = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
            if payload and len(payload) > 32 * 1024:
                raise ModelFailure("LLM_CONTEXT_TOO_LARGE")
            connection.request(method, path, payload, {"Content-Type": "application/json"})
            connection.sock.settimeout(max(0.001, deadline - monotonic()))
            response = connection.getresponse()
            if response.status == 404:
                raise ModelFailure("LLM_MODEL_UNAVAILABLE")
            if response.status != 200:
                raise ModelFailure("LLM_UNAVAILABLE")
            chunks = []
            size = 0
            while True:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise TimeoutError
                if connection.sock:
                    connection.sock.settimeout(remaining)
                chunk = response.read1(min(4096, max_bytes + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > max_bytes:
                    raise ModelFailure("LLM_RESPONSE_INVALID")
            return json.loads(b"".join(chunks))
        finally:
            connection.close()

    def cache_matches(self, report):
        if not self.settings.llm_enabled or report.model_id != self.settings.llm_model:
            return False
        try:
            data = self.request("GET", "/api/tags", None, monotonic() + 3, 256 * 1024)
            rows = [row for row in data["models"] if row["name"] == self.settings.llm_model]
            if len(rows) != 1 or not isinstance(rows[0]["digest"], str):
                return False
            digest = "sha256:" + rows[0]["digest"].removeprefix("sha256:")
            return digest == report.model_digest and (
                not self.settings.llm_model_digest or digest == self.settings.llm_model_digest
            )
        except (
            ModelFailure,
            OSError,
            http.client.HTTPException,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
        ):
            return False

    def generate(self, context):
        if not self.settings.llm_enabled:
            return Generation(None, "LLM_DISABLED")
        if not self.slots.acquire(blocking=False):
            return Generation(None, "LLM_BUSY")
        model = self.settings.llm_model
        digest = None
        try:
            deadline = monotonic() + self.settings.llm_timeout_seconds
            metadata = self.request("GET", "/api/tags", None, deadline, 256 * 1024)
            models = [row for row in metadata["models"] if row["name"] == model]
            if len(models) != 1:
                raise ModelFailure("LLM_MODEL_UNAVAILABLE")
            raw_digest = models[0]["digest"]
            if not isinstance(raw_digest, str) or not re.fullmatch(
                r"(?:sha256:)?[a-f0-9]{64}", raw_digest
            ):
                raise ModelFailure("LLM_RESPONSE_INVALID")
            digest = "sha256:" + raw_digest.removeprefix("sha256:")
            if self.settings.llm_model_digest and digest != self.settings.llm_model_digest:
                raise ModelFailure("LLM_MODEL_MISMATCH")
            schema = ModelNarrative.model_json_schema()
            result = self.request(
                "POST",
                "/api/chat",
                {
                    "model": model,
                    "stream": False,
                    "keep_alive": "5m",
                    "options": GENERATION_CONFIG,
                    "format": schema,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": json.dumps(context["brief"], ensure_ascii=False),
                        },
                    ],
                },
                deadline,
                16 * 1024,
            )
            if (
                result.get("done") is not True
                or result.get("done_reason") != "stop"
                or result.get("model") != model
                or result["message"].get("role") != "assistant"
                or result["message"].get("tool_calls")
            ):
                raise ModelFailure("LLM_RESPONSE_INVALID")
            selection = ModelNarrative.model_validate_json(result["message"]["content"])
            return Generation(selection, None, model, digest)
        except ModelFailure as exc:
            return Generation(None, exc.args[0], model, digest)
        except TimeoutError:
            return Generation(None, "LLM_TIMEOUT", model, digest)
        except (OSError, http.client.HTTPException):
            return Generation(None, "LLM_UNAVAILABLE", model, digest)
        except (ValueError, TypeError, KeyError, AttributeError, ValidationError):
            return Generation(None, "LLM_RESPONSE_INVALID", model, digest)
        finally:
            self.slots.release()
