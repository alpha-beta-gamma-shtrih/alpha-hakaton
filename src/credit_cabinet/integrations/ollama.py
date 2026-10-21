"""Bounded synchronous HTTP, used by FastAPI's worker thread, never its event loop."""

import http.client
import json
import re
from dataclasses import dataclass
from threading import BoundedSemaphore
from time import monotonic
from urllib.parse import urlsplit

from pydantic import ValidationError

from credit_cabinet.schemas.advisor import ModelSelection

PROMPT_VERSION = "advisor-grounded-0.2.1"
GENERATION_CONFIG = {"temperature": 0, "seed": 42, "num_ctx": 4096, "num_predict": 384}
SYSTEM_PROMPT = """Ты помощник демонстрационного кредитного кабинета.
Выбери наиболее значимые факторы для объяснения заявки или сравнения вариантов.
Верни только JSON по заданной схеме. Используй ТОЛЬКО переданные идентификаторы.
Не добавляй текст, числа, инструменты или новые условия. Все вычисления уже выполнены.
Для EXPLAIN comparisons пустой. Для COMPARE включи каждый candidate_id ровно один раз;
у каждого варианта используй только его factor_ids. В summary_factor_ids выбери до
четырех доступных факторов. next_step_id возьми из переданного next_step.
Карточки содержат синтетические данные, предварительная оценка не гарантирует выдачу.
"""


@dataclass
class Generation:
    selection: ModelSelection | None
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
            digest = models[0]["digest"]
            if re.fullmatch(r"[a-f0-9]{64}", digest):
                digest = "sha256:" + digest
            if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
                raise ModelFailure("LLM_RESPONSE_INVALID")
            if self.settings.llm_model_digest and digest != self.settings.llm_model_digest:
                raise ModelFailure("LLM_MODEL_MISMATCH")
            schema = ModelSelection.model_json_schema()
            result = self.request(
                "POST",
                "/api/chat",
                {
                    "model": model,
                    "stream": False,
                    "think": False,
                    "keep_alive": "5m",
                    "options": GENERATION_CONFIG,
                    "format": schema,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": json.dumps(
                                {"context": context, "schema": schema}, ensure_ascii=False
                            ),
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
            selection = ModelSelection.model_validate_json(result["message"]["content"])
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
