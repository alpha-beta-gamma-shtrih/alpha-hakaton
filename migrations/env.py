import os

from alembic import context
from dotenv import dotenv_values
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

import credit_cabinet.models  # noqa: F401
from credit_cabinet.db.base import Base

config = context.config
target_metadata = Base.metadata


def database_url() -> str:
    # Migrations do not require web-session secrets. Never interpolate URL into ini/logs.
    url = config.attributes.get("database_url") or os.environ.get("DATABASE_URL")
    url = url or dotenv_values(".env").get("DATABASE_URL")
    if not url:
        raise RuntimeError("Set DATABASE_URL before running migrations")
    return url


def run_with_connection(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
elif config.attributes.get("connection") is not None:
    run_with_connection(config.attributes["connection"])
else:
    engine = create_engine(database_url(), poolclass=NullPool, hide_parameters=True)
    try:
        with engine.connect() as connection:
            run_with_connection(connection)
    finally:
        engine.dispose()
