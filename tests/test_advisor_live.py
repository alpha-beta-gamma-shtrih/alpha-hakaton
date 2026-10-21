"""Opt-in real inference; the default suite needs neither Ollama nor downloaded weights."""

import json
import os

import pytest

from credit_cabinet.integrations.ollama import OllamaAdvisor
from tests.test_advisor import explain
from tests.test_drafts import patch
from tests.test_submissions import ready

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_OLLAMA_URL"), reason="Set TEST_OLLAMA_URL for real Ollama inference"
)


@pytest.mark.parametrize(
    "mode,incomplete", [("EXPLAIN", False), ("COMPARE", False), ("EXPLAIN", True)]
)
def test_real_model_selects_grounded_facts(seeded, client, mode, incomplete):
    settings = type(seeded.state.settings).model_validate(
        {
            **seeded.state.settings.model_dump(),
            "llm_enabled": True,
            "llm_base_url": os.environ["TEST_OLLAMA_URL"],
            "llm_model": os.environ.get("TEST_OLLAMA_MODEL", "qwen3:4b"),
        }
    )
    seeded.state.advisor = OllamaAdvisor(settings)
    draft = ready(client)
    if incomplete:
        draft = patch(
            client,
            draft,
            draft_data={"financial_months": draft["draft_data"]["financial_months"][:-1]},
        ).json()
    response = explain(client, draft, mode)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "SUCCESS", result["error_code"]
    assert result["is_current"] is True
    assert len(result["explanation"]["comparisons"]) == (3 if mode == "COMPARE" else 0)
    assert result["model_digest"].startswith("sha256:")
    assert result["scenarios"][0]["monthly_payment"] == "94559.60"
    assert result["explanation"]["next_step"]["id"] == (
        "COMPLETE_DATA" if incomplete else "REVIEW_SUBMISSION"
    )
    print(
        json.dumps(
            {
                "live_benchmark": {
                    "case": mode + ("_MISSING_FINANCES" if incomplete else "_C01"),
                    "model_id": result["model_id"],
                    "model_digest": result["model_digest"],
                    "latency_ms": result["latency_ms"],
                    "status": result["status"],
                    "prompt_version": result["prompt_version"],
                }
            }
        )
    )
