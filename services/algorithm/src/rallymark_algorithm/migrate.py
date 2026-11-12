"""Ordered, transactional schema migrations; run before API/worker startup."""

from sqlalchemy import text

from .db import database
from .models import Base
from .settings import Settings


def migrate(engine):
    with engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(74219860)"))
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS algorithm"))
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS algorithm.schema_migrations "
                "(version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
            )
        )
        versions = set(connection.execute(text("SELECT version FROM algorithm.schema_migrations")).scalars())
        if 1 not in versions:
            Base.metadata.create_all(connection)
            connection.execute(text("INSERT INTO algorithm.schema_migrations(version) VALUES (1)"))


if __name__ == "__main__":
    engine, _ = database(Settings.load().database_url)
    migrate(engine)
