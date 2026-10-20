import argparse
from getpass import getpass

from pydantic import EmailStr, TypeAdapter
from sqlalchemy import select

from credit_cabinet.core.config import Settings
from credit_cabinet.core.security import hash_password
from credit_cabinet.db.session import build_engine, build_session_factory
from credit_cabinet.models import User
from credit_cabinet.models.enums import Role


def create_user() -> None:
    parser = argparse.ArgumentParser(
        description="Create a demo user without exposing the password in argv"
    )
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--role", choices=[role.value for role in Role], required=True)
    args = parser.parse_args()
    email = str(TypeAdapter(EmailStr).validate_python(args.email.strip().lower()))
    password = getpass("Password (12+ characters): ")
    if len(password) < 12 or len(password) > 1024 or password != getpass("Repeat password: "):
        parser.error("Password must contain 12–1024 characters and match confirmation")
    engine = build_engine(Settings())
    try:
        with build_session_factory(engine)() as db:
            if db.scalar(select(User.id).where(User.email == email)):
                parser.error("User already exists; password was not changed")
            db.add(
                User(
                    email=email,
                    display_name=args.name,
                    role=Role(args.role),
                    password_hash=hash_password(password),
                    is_active=True,
                    ui_context={},
                )
            )
            db.commit()
        print("User created")
    finally:
        engine.dispose()
