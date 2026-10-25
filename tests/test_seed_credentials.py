import json
import sys

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from credit_cabinet.core.security import verify_password
from credit_cabinet.models import Company, User
from credit_cabinet.services.seed import DatasetError, import_bundle, load_bundle
from tests.conftest import PASSWORD, ROOT, login


def credential_bundle():
    bundle = load_bundle(ROOT / "demo_data/demo_0_2")
    for index, row in enumerate(bundle.users):
        row.password = SecretStr(f"Public-demo-test-{index}-only!")
    return bundle


def test_individual_passwords_work_without_fallback_and_never_reset_existing_users(app, client):
    bundle = credential_bundle()
    with app.state.session_factory() as db:
        old = dict(db.execute(select(User.email, User.password_hash)).all())
        assert import_bundle(db, bundle)["created"]["users"] == 2
        assert not any(import_bundle(db, bundle, "Unused-fallback-password!")["created"].values())
        for email, password_hash in old.items():
            assert db.scalar(select(User.password_hash).where(User.email == email)) == password_hash
        for row in bundle.users:
            user = db.scalar(select(User).where(User.email == row.email))
            expected = PASSWORD if row.email in old else row.password.get_secret_value()
            assert verify_password(user.password_hash, expected)
            assert user.password_hash != expected
    assert (
        login(
            client, "client2@example.com", bundle.users[1].password.get_secret_value()
        ).status_code
        == 200
    )
    assert "password" not in client.get("/api/auth/me").text


def test_mixed_credentials_require_fallback_atomically_and_file_takes_precedence(app):
    bundle = credential_bundle()
    bundle.users[-1].password = None
    fallback = "Explicit-legacy-fallback-only!"
    with app.state.session_factory() as db:
        with pytest.raises(DatasetError, match="password is required"):
            import_bundle(db, bundle)
        assert db.scalar(select(func.count()).select_from(User)) == 2
        assert db.scalar(select(func.count()).select_from(Company)) == 0
        import_bundle(db, bundle, fallback)
        client_hash = db.scalar(
            select(User.password_hash).where(User.email == "client2@example.com")
        )
        assert verify_password(client_hash, bundle.users[1].password.get_secret_value())
        assert not verify_password(client_hash, fallback)
        bank_hash = db.scalar(select(User.password_hash).where(User.email == "bank2@example.com"))
        assert verify_password(bank_hash, fallback)


def test_cli_with_individual_passwords_needs_no_terminal_or_env_password(app, monkeypatch, capsys):
    from credit_cabinet import seed

    bundle = credential_bundle()
    app.state.settings.demo_user_password = None
    monkeypatch.setattr(seed, "Settings", lambda: app.state.settings)
    monkeypatch.setattr(seed, "build_engine", lambda _settings: app.state.engine)
    monkeypatch.setattr(seed, "load_bundle", lambda _path: bundle)
    monkeypatch.setattr(sys, "argv", ["credit-cabinet-seed"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    def unexpected_prompt(*_args):
        pytest.fail("Individual credentials must not require interactive input")

    monkeypatch.setattr(seed, "getpass", unexpected_prompt)
    seed.main()
    seed.main()
    output = capsys.readouterr().out.splitlines()
    assert json.loads(output[0])["created"]["users"] == 2
    assert not any(json.loads(output[1])["created"].values())
    assert all(row.password.get_secret_value() not in "\n".join(output) for row in bundle.users)
