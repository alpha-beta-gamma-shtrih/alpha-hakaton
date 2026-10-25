import json

import pytest

from credit_cabinet.services.seed import load_bundle
from tests.conftest import ROOT


def test_shipped_credentials_cover_every_user_and_stay_out_of_repr():
    bundle = load_bundle(ROOT / "demo_data/demo_0_3")
    passwords = [row.password.get_secret_value() for row in bundle.users]
    assert len(passwords) == len(set(passwords)) == 146
    assert all(12 <= len(password) <= 1024 for password in passwords)
    assert all(password not in repr(bundle) for password in passwords)


@pytest.mark.skipif(
    not (ROOT / "frontend/src/api/mock/dataset.json").is_file(),
    reason="Frontend sources are not included in the backend Docker image",
)
def test_shipped_credentials_stay_out_of_mock_payload():
    bundle = load_bundle(ROOT / "demo_data/demo_0_3")
    passwords = [row.password.get_secret_value() for row in bundle.users]
    mock_path = ROOT / "frontend/src/api/mock/dataset.json"
    mock_data = mock_path.read_text(encoding="utf-8")
    assert all(password not in mock_data for password in passwords)
    assert all("password" not in row for row in json.loads(mock_data)["users"])
