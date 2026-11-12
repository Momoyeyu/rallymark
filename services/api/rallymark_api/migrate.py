"""Ordered schema migrations; never run migrations implicitly during API startup."""

from sqlalchemy import text

from .config import Settings
from .db import Base, Maintenance, connect


def migrate(engine):
    with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            connection.execute(text("CREATE SCHEMA IF NOT EXISTS business"))
            connection.execute(text("SELECT pg_advisory_xact_lock(74217421)"))
            prefix = "business."
        else:
            prefix = ""
        connection.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {prefix}schema_versions (version INTEGER PRIMARY KEY)"
            )
        )
        versions = set(
            connection.execute(text(f"SELECT version FROM {prefix}schema_versions")).scalars()
        )
        if 1 not in versions:
            Base.metadata.create_all(connection)
            connection.execute(Maintenance.__table__.insert().values(id=1, draining=False))
            connection.execute(text(f"INSERT INTO {prefix}schema_versions VALUES (1)"))


def main():
    settings = Settings()
    engine, _ = connect(settings.database_url)
    migrate(engine)


if __name__ == "__main__":
    main()
