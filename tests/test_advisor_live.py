"""Opt-in real inference; the default suite needs neither Ollama nor downloaded weights."""

import json
import os

import pytest

from credit_cabinet.integrations.ollama import OllamaAdvisor
from tests.test_advisor import explain
from tests.test_drafts import patch
from tests.test_personal_pricing_api import personal as personal
from tests.test_scenario_sets import fixed
from tests.test_submissions import ready

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_OLLAMA_URL"), reason="Set TEST_OLLAMA_URL for real Ollama inference"
)


class RecordingOllama(OllamaAdvisor):
    def generate(self, context):
        result = super().generate(context)
        self.last_generation = result
        print(
            json.dumps(
                {
                    "raw_model": result.selection.model_dump()
                    if result.selection
                    else result.error_code
                },
                ensure_ascii=False,
            )
        )
        return result


@pytest.mark.parametrize(
    "mode,incomplete", [("EXPLAIN", False), ("COMPARE", False), ("EXPLAIN", True)]
)
def test_real_model_explains_grounded_facts(seeded, client, mode, incomplete):
    settings = type(seeded.state.settings).model_validate(
        {
            **seeded.state.settings.model_dump(),
            "llm_enabled": True,
            "llm_base_url": os.environ["TEST_OLLAMA_URL"],
            "llm_model": os.environ.get("TEST_OLLAMA_MODEL", "qwen2.5:1.5b"),
        }
    )
    seeded.state.advisor = RecordingOllama(settings)
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
    assert result["status"] == "SUCCESS", (
        result["error_code"],
        seeded.state.advisor.last_generation,
    )
    assert result["is_current"] is True
    assert result["explanation"]["comparisons"] == []
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
                    "summary": result["explanation"]["summary"]["text"],
                }
            }
        )
    )


@pytest.mark.parametrize(
    "priority,expected",
    [
        ("BALANCED", []),
        ("KEEP_AMOUNT", ["LONGER_TERM"]),
        ("LOWER_PAYMENT", ["LONGER_TERM"]),
        ("LOWER_OVERPAYMENT", ["LOWER_AMOUNT"]),
    ],
)
def test_real_model_compares_fixed_v3_options_by_priority(personal, client, priority, expected):
    settings = personal.state.settings.model_copy(
        update={
            "llm_enabled": True,
            "llm_base_url": os.environ["TEST_OLLAMA_URL"],
            "llm_model": os.environ.get("TEST_OLLAMA_MODEL", "qwen2.5:1.5b"),
        }
    )
    personal.state.advisor = RecordingOllama(settings)
    draft, options = fixed(client)
    response = explain(client, draft, "COMPARE", priority=priority)
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["status"] == "SUCCESS", (
        report["error_code"],
        personal.state.advisor.last_generation,
    )
    assert report["scenarios"] == options["candidates"]
    assert report["preferred_candidate_ids"] == expected
    assert report["priority"] == priority
    again = explain(client, draft, "COMPARE", priority=priority).json()
    assert again["id"] == report["id"]  # verified model digest, no second inference
    print(
        json.dumps(
            {
                "live_benchmark": {
                    "case": "COMPARE_V3_" + priority,
                    "model_id": report["model_id"],
                    "model_digest": report["model_digest"],
                    "latency_ms": report["latency_ms"],
                    "status": report["status"],
                    "prompt_version": report["prompt_version"],
                    "preferred_candidate_ids": report["preferred_candidate_ids"],
                    "explanation": report["explanation"],
                }
            },
            ensure_ascii=False,
        )
    )
