import json
import shutil

import pytest

from credit_cabinet.core.security import utc_now
from credit_cabinet.integrations.fixtures import FixtureSources
from tests.conftest import ROOT
from tests.test_seed import rewrite


@pytest.fixture
def dataset(tmp_path):
    path = tmp_path / "data"
    shutil.copytree(ROOT / "demo_data/demo_0_2", path)
    return path


def test_real_fixture_normalizes_money_and_provenance():
    before = utc_now()
    response = FixtureSources(ROOT / "demo_data/demo_0_2").check("0000000001", "BKI", 1, 1)
    assert response.status == "SUCCESS"
    assert response.normalized_data["current_monthly_payment"] == "30000.00"
    assert response.normalized_data["provenance"] == {
        "source": "MOCK_BKI",
        "as_of_date": "2026-10-01",
        "checked_at": response.completed_at.isoformat(),
    }
    assert before <= response.started_at <= response.completed_at


def test_fixture_attempts_do_not_depend_on_http_call_count(dataset):
    rows = json.loads((dataset / "bki_responses.json").read_text(encoding="utf-8"))
    success = {**rows[0], "run_no": 2}
    rows[0] = {**rows[0], "status": "ERROR", "normalized_data": None, "error_code": "TIMEOUT"}
    rows.append(success)
    rewrite(dataset, "bki_responses.json", rows)
    adapter = FixtureSources(dataset)
    assert adapter.check("0000000001", "BKI", 1, 1).status == "ERROR"
    assert adapter.check("0000000001", "BKI", 1, 1).status == "ERROR"
    assert adapter.check("0000000001", "BKI", 1, 2).status == "SUCCESS"
    assert adapter.check("0000000001", "BKI", 1, 3).status == "SUCCESS"
    assert adapter.check("0000000001", "BKI", 2, 1).status == "ERROR"
    # A revision-specific response overrides a reusable company response.
    rows.append({**success, "revision_no": 2, "run_no": 1})
    rewrite(dataset, "bki_responses.json", rows)
    assert adapter.check("0000000001", "BKI", 2, 1).status == "SUCCESS"


@pytest.mark.parametrize(
    "change,status,error",
    [
        ("checksum", "ERROR", "SOURCE_RESPONSE_INVALID"),
        ("missing", "ERROR", "FIXTURE_UNAVAILABLE"),
        ("malformed", "ERROR", "SOURCE_RESPONSE_INVALID"),
        ("no_company", "NO_DATA", None),
    ],
)
def test_sources_fail_closed(dataset, change, status, error):
    if change == "checksum":
        (dataset / "bki_responses.json").write_text("[]", encoding="utf-8")
    if change == "missing":
        (dataset / "bki_responses.json").unlink()
    if change == "malformed":
        rows = json.loads((dataset / "bki_responses.json").read_text(encoding="utf-8"))
        rows[0]["normalized_data"]["history_present"] = False
        rewrite(dataset, "bki_responses.json", rows)
    response = FixtureSources(dataset).check(
        "not-in-demo" if change == "no_company" else "0000000001", "BKI", 1, 1
    )
    assert (response.status, response.error_code) == (status, error)
    assert response.normalized_data is None


def test_missing_bankruptcy_remains_unknown_at_runtime(dataset):
    rows = json.loads((dataset / "fns_responses.json").read_text(encoding="utf-8"))
    del rows[0]["normalized_data"]["is_bankrupt"]
    rewrite(dataset, "fns_responses.json", rows)
    response = FixtureSources(dataset).check("0000000001", "FNS", 1, 1)
    assert response.status == "SUCCESS" and response.normalized_data["is_bankrupt"] is None
