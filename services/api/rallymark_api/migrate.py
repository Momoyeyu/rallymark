"""Ordered schema migrations; never run migrations implicitly during API startup."""

from sqlalchemy import inspect, text

from .config import Settings
from .db import Base, Maintenance, connect


def migrate(engine):
    with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(74217421)"))
            exists = connection.scalar(
                text("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = :schema)"),
                {"schema": "business"},
            )
            if not exists:
                connection.execute(text("CREATE SCHEMA business"))
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
        if 2 not in versions:
            columns = inspect(connection).get_columns(
                "analyses", schema="business" if prefix else None
            )
            if not any(column["name"] == "ready_at" for column in columns):
                connection.execute(
                    text(
                        f"ALTER TABLE {prefix}analyses ADD COLUMN ready_at TIMESTAMP WITH TIME ZONE"
                    )
                )
            connection.execute(text(f"INSERT INTO {prefix}schema_versions VALUES (2)"))


def main():
    settings = Settings()
    engine, _ = connect(settings.database_url)
    migrate(engine)


if __name__ == "__main__":
    main()
