import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from pydantic import ValidationError

from credit_cabinet.integrations.ollama import ModelFailure, OllamaAdvisor

DIGEST = "a" * 64
CONTEXT = {
    "mode": "EXPLAIN",
    "candidates": [{"candidate_id": "REQUESTED"}],
    "next_step": {"id": "REVIEW_PARAMETERS"},
    "brief": {"benefit": "Демо-расчёт", "tradeoff": "Оценка предварительная"},
}
SELECTION = {
    "benefit": "Оценка предварительная. Проверьте бюджет своей компании.",
    "tradeoff": "Окончательное решение принимает банк после проверки заявки.",
}


@pytest.fixture(autouse=True)
def enable_model(settings):
    settings.llm_enabled = True


def fake_request(settings, *, content=None, **changes):
    def request(method, path, body, deadline, max_bytes):
        if path == "/api/tags":
            return {"models": [{"name": settings.llm_model, "digest": DIGEST}]}
        assert path == "/api/chat" and method == "POST"
        assert body["stream"] is False and "think" not in body
        assert "tools" not in body
        assert body["options"]["num_predict"] == 384
        assert body["format"]["additionalProperties"] is False
        return {
            "model": settings.llm_model,
            "done": True,
            "done_reason": "stop",
            "message": {"role": "assistant", "content": json.dumps(content or SELECTION)},
            **changes,
        }

    return request


def test_structured_ollama_generation_and_digest(settings, monkeypatch):
    adapter = OllamaAdvisor(settings)
    monkeypatch.setattr(adapter, "request", fake_request(settings))
    result = adapter.generate(CONTEXT)
    assert result.error_code is None
    assert result.selection.model_dump() == SELECTION
    assert result.model_digest == "sha256:" + DIGEST


@pytest.mark.parametrize(
    "change",
    [
        {"done": False},
        {"done_reason": "length"},
        {"model": "other"},
        {"message": {"role": "assistant", "content": "not-json"}},
        {"message": {"role": "assistant", "content": "{}", "tool_calls": [{"name": "sql"}]}},
    ],
)
def test_invalid_runtime_response_is_fallback(settings, monkeypatch, change):
    adapter = OllamaAdvisor(settings)
    monkeypatch.setattr(adapter, "request", fake_request(settings, **change))
    assert adapter.generate(CONTEXT).error_code == "LLM_RESPONSE_INVALID"


@pytest.mark.parametrize(
    "error,code",
    [
        (TimeoutError, "LLM_TIMEOUT"),
        (ConnectionError, "LLM_UNAVAILABLE"),
        (KeyError, "LLM_RESPONSE_INVALID"),
    ],
)
def test_model_errors_are_safe_and_slot_is_released(settings, monkeypatch, error, code):
    adapter = OllamaAdvisor(settings)

    def failure(*args):
        raise error("private content must not escape")

    monkeypatch.setattr(adapter, "request", failure)
    result = adapter.generate({})
    assert result.error_code == code
    assert adapter.slots.acquire(blocking=False)
    adapter.slots.release()


def test_disabled_and_missing_model_never_call_chat(settings, monkeypatch):
    adapter = OllamaAdvisor(settings.model_copy(update={"llm_enabled": False}))
    monkeypatch.setattr(adapter, "request", lambda *args: pytest.fail("disabled model called"))
    assert adapter.generate({}).error_code == "LLM_DISABLED"
    adapter = OllamaAdvisor(settings)
    monkeypatch.setattr(adapter, "request", lambda *args: {"models": []})
    assert adapter.generate({}).error_code == "LLM_MODEL_UNAVAILABLE"


def test_pinned_model_digest_checked_before_generation(settings, monkeypatch):
    adapter = OllamaAdvisor(settings.model_copy(update={"llm_model_digest": "sha256:" + "b" * 64}))
    monkeypatch.setattr(adapter, "request", fake_request(settings))
    assert adapter.generate({}).error_code == "LLM_MODEL_MISMATCH"


@pytest.mark.parametrize("digest", [None, {}, "private-invalid-digest"])
def test_invalid_digest_never_enters_report_metadata(settings, monkeypatch, digest):
    adapter = OllamaAdvisor(settings)
    monkeypatch.setattr(
        adapter,
        "request",
        lambda *args: {"models": [{"name": settings.llm_model, "digest": digest}]},
    )
    result = adapter.generate(CONTEXT)
    assert result.error_code == "LLM_RESPONSE_INVALID"
    assert result.model_digest is None


def test_parallel_generation_is_bounded(settings, monkeypatch):
    adapter = OllamaAdvisor(settings)
    entered, resume = Event(), Event()
    original = fake_request(settings)

    def request(*args):
        entered.set()
        assert resume.wait(timeout=5)
        return original(*args)

    monkeypatch.setattr(adapter, "request", request)
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(adapter.generate, CONTEXT)
        assert entered.wait(timeout=5)
        try:
            assert adapter.generate({}).error_code == "LLM_BUSY"
        finally:
            resume.set()
        assert pending.result().error_code is None


@pytest.mark.parametrize(
    "url", ["https://host", "http://user:password@host", "http://host/path", "http://host?secret=1"]
)
def test_runtime_url_rejects_credentials_and_paths(settings, url):
    with pytest.raises(ValidationError):
        type(settings).model_validate({**settings.model_dump(), "llm_base_url": url})


@pytest.mark.parametrize(
    "status,content,code",
    [
        (302, b"private-redirect", "LLM_UNAVAILABLE"),
        (404, b"private-error", "LLM_MODEL_UNAVAILABLE"),
        (200, b"x" * 101, "LLM_RESPONSE_INVALID"),
    ],
)
def test_http_response_limits_and_redirects(settings, monkeypatch, status, content, code):
    from io import BytesIO
    from time import monotonic
    from types import SimpleNamespace

    connection = SimpleNamespace(sock=SimpleNamespace(settimeout=lambda value: None), closed=False)
    connection.request = lambda *args: None
    response = BytesIO(content)
    response.status = status
    connection.getresponse = lambda: response

    def close():
        connection.closed = True

    connection.close = close
    monkeypatch.setattr(
        "credit_cabinet.integrations.ollama.http.client.HTTPConnection", lambda *args: connection
    )
    with pytest.raises(ModelFailure) as error:
        OllamaAdvisor(settings).request("GET", "/api/tags", None, monotonic() + 5, 100)
    assert error.value.args == (code,)
    assert connection.closed
