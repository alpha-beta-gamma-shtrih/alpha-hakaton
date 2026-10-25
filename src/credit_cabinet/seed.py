"""Run as python -m credit_cabinet.seed (same entry point as credit-cabinet-seed)."""

import argparse
import json
import sys
from getpass import getpass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from credit_cabinet.core.config import Settings
from credit_cabinet.db.session import build_engine, build_session_factory
from credit_cabinet.models import User
from credit_cabinet.services.seed import DatasetError, import_bundle, load_bundle


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate/import versioned synthetic data without resetting working data"
    )
    parser.add_argument("--dataset", type=Path, default=Path("demo_data/demo_0_3"))
    parser.add_argument(
        "--check-only", action="store_true", help="Validate files without connecting to DB"
    )
    args = parser.parse_args()
    try:
        bundle = load_bundle(args.dataset)
    except DatasetError as exc:
        parser.exit(1, f"Dataset error: {exc}\n")
    if args.check_only:
        print(
            json.dumps(
                {
                    "valid": True,
                    "dataset_version": bundle.manifest.dataset_version,
                    "subset": bundle.manifest.subset,
                    "companies": len(bundle.companies),
                }
            )
        )
        return
    settings = Settings()
    engine = build_engine(settings)
    try:
        with build_session_factory(engine)() as db:
            existing = set(
                db.scalars(
                    select(User.email).where(
                        User.email.in_([str(row.email) for row in bundle.users])
                    )
                )
            )
            needs_password = any(
                str(row.email) not in existing and row.password is None for row in bundle.users
            )
            password = (
                settings.demo_user_password.get_secret_value()
                if settings.demo_user_password
                else None
            )
            if needs_password and not password:
                if not sys.stdin.isatty():
                    parser.exit(
                        1, "Set DEMO_USER_PASSWORD for non-interactive seed; nothing imported\n"
                    )
                password = getpass("Password for NEW demo accounts (12+ characters): ")
                if password != getpass("Repeat password: "):
                    parser.exit(1, "Passwords do not match; nothing imported\n")
            result = import_bundle(db, bundle, password)
            print(json.dumps(result))
    except DatasetError as exc:
        parser.exit(1, f"Dataset error: {exc}\n")
    except SQLAlchemyError:
        parser.exit(
            1,
            "Database import failed; transaction rolled back. Check migrations and dataset conflicts.\n",
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
