import hashlib
import json
import shutil
import subprocess
import sys
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from credit_cabinet.models import Application, Company, CompanyFinancialMonth, CreditProduct, User
from credit_cabinet.services.seed import DatasetError, import_bundle, load_bundle
from tests.conftest import ROOT
from tests.test_drafts import SEED_PASSWORD

DATA = ROOT / "demo_data/demo_0_2"


def rewrite(root, name, data):
    path = root / name
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"][name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8", newline="\n"
    )


def test_minimal_bundle_is_complete_and_password_free():
    bundle = load_bundle(DATA)
    assert bundle.manifest.subset == "C01_C02_BOOTSTRAP"
    assert len(bundle.companies) == 2 and len(bundle.financials) == 12
    assert len(bundle.users) == 4 and len(bundle.products) == 1
    assert "password" not in (DATA / "demo_users.json").read_text()
    assert bundle.financials[0].cash_inflow == Decimal("1200000.00")


def test_import_is_repeatable_and_preserves_existing_identity_password(app):
    bundle = load_bundle(DATA)
    with app.state.session_factory() as db:
        user = db.scalar(select(User).where(User.email == "client@example.com"))
        user_id, old_hash = user.id, user.password_hash
        first = import_bundle(db, bundle, SEED_PASSWORD)
        second = import_bundle(db, bundle)
        assert first["created"]["users"] == 2
        assert first["created"]["companies"] == 2
        assert first["created"]["financial_months"] == 12
        assert second["created"] == dict.fromkeys(first["created"], 0)
        db.expire_all()
        same_user = db.scalar(select(User).where(User.email == "client@example.com"))
        assert same_user.id == user_id and same_user.password_hash == old_hash
        assert same_user.display_name == "Client"
        assert db.scalar(select(func.count()).select_from(Application)) == 0


def test_repeat_import_preserves_declared_profile_and_disabled_product(app):
    bundle = load_bundle(DATA)
    with app.state.session_factory() as db:
        import_bundle(db, bundle, SEED_PASSWORD)
        finance = db.scalar(select(CompanyFinancialMonth))
        finance.cash_inflow = Decimal("42.00")
        finance.source = "DECLARED"
        product = db.scalar(select(CreditProduct))
        product.is_active = False
        db.commit()
        import_bundle(db, bundle, SEED_PASSWORD)
        db.expire_all()
        assert db.get(CompanyFinancialMonth, finance.id).cash_inflow == Decimal("42.00")
        assert db.get(CreditProduct, product.id).is_active is False


def test_role_conflict_rolls_back_everything(app):
    bundle = load_bundle(DATA)
    # Put the conflict after one new user, to prove the whole import is atomic.
    bundle.users = [*bundle.users[1:], bundle.users[0]]
    with app.state.session_factory() as db:
        user = db.scalar(select(User).where(User.email == "client@example.com"))
        user.role = "BANK_STAFF"
        db.commit()
        with pytest.raises(DatasetError, match="role"):
            import_bundle(db, bundle, SEED_PASSWORD)
        assert db.scalar(select(func.count()).select_from(User)) == 2
        assert db.scalar(select(func.count()).select_from(Company)) == 0


@pytest.mark.parametrize("password", [None, "short"])
def test_password_required_only_for_new_accounts_and_no_partial_writes(app, password):
    with app.state.session_factory() as db:
        with pytest.raises(DatasetError, match="password"):
            import_bundle(db, load_bundle(DATA), password)
        assert db.scalar(select(func.count()).select_from(Company)) == 0


def test_file_hash_is_checked_before_import(tmp_path):
    shutil.copytree(DATA, tmp_path / "dataset")
    root = tmp_path / "dataset"
    with (root / "companies.csv").open("a", encoding="utf-8") as stream:
        stream.write("tampered")
    with pytest.raises(DatasetError, match="Checksum"):
        load_bundle(root)


def test_bankruptcy_fact_cannot_silently_default_false(tmp_path):
    root = tmp_path / "dataset"
    shutil.copytree(DATA, root)
    data = json.loads((root / "fns_responses.json").read_text(encoding="utf-8"))
    del data[0]["normalized_data"]["is_bankrupt"]
    rewrite(root, "fns_responses.json", data)
    with pytest.raises(DatasetError):
        load_bundle(root)


def test_no_password_fields_allowed_in_user_file(tmp_path):
    root = tmp_path / "dataset"
    shutil.copytree(DATA, root)
    data = json.loads((root / "demo_users.json").read_text(encoding="utf-8"))
    data[0]["password"] = "private-accidental-secret"
    rewrite(root, "demo_users.json", data)
    with pytest.raises(DatasetError):
        load_bundle(root)


def test_manifest_path_escape_is_rejected(tmp_path):
    root = tmp_path / "dataset"
    shutil.copytree(DATA, root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest["document_templates"][0]["path"] = "../outside.csv"
    manifest["files"].pop("documents/C01.csv")
    manifest["files"]["../outside.csv"] = "0" * 64
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(DatasetError, match="path"):
        load_bundle(root)


def test_check_only_does_not_need_database_or_session_secret(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "not-a-database-url")
    monkeypatch.setenv("CSRF_SIGNING_KEY", "invalid")
    result = subprocess.run(
        [sys.executable, "-m", "credit_cabinet.seed", "--check-only"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["valid"] is True


def test_noninteractive_seed_without_password_exits_before_writing(app, monkeypatch):
    from credit_cabinet import seed

    monkeypatch.setattr(seed, "Settings", lambda: app.state.settings)
    monkeypatch.setattr(seed, "build_engine", lambda _settings: app.state.engine)
    monkeypatch.setattr(sys, "argv", ["credit-cabinet-seed"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(SystemExit) as error:
        seed.main()
    assert error.value.code == 1
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 2
        assert db.scalar(select(func.count()).select_from(Company)) == 0
