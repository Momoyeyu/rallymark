"""Ordered schema migrations; never run migrations implicitly during API startup."""

from sqlalchemy import inspect, text, select
from uuid import uuid4
from .identity import password_hash

from .config import Settings
from .db import Base, Maintenance, User, UserSession, GuestSession, LoginLimit, AuditEvent, connect


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
        if 3 not in versions:
            for model in (User, UserSession, GuestSession, LoginLimit, AuditEvent):
                model.__table__.create(connection, checkfirst=True)
            columns = {
                column["name"]
                for column in inspect(connection).get_columns(
                    "videos", schema="business" if prefix else None
                )
            }
            if "user_id" not in columns:
                connection.execute(
                    text(
                        f"ALTER TABLE {prefix}videos ADD COLUMN user_id VARCHAR(36) REFERENCES {prefix}users(id)"
                    )
                )
                connection.execute(
                    text(f"CREATE INDEX ix_videos_user_id ON {prefix}videos(user_id)")
                )
            if "trashed_at" not in columns:
                connection.execute(
                    text(
                        f"ALTER TABLE {prefix}videos ADD COLUMN trashed_at TIMESTAMP WITH TIME ZONE"
                    )
                )
            if not connection.scalar(select(User.id).limit(1)):
                connection.execute(
                    User.__table__.insert().values(
                        id=str(uuid4()),
                        username="admin",
                        password_hash=password_hash("admin"),
                        role="admin",
                        active=True,
                    )
                )
            connection.execute(text(f"INSERT INTO {prefix}schema_versions VALUES (3)"))
        if 4 not in versions:
            GuestSession.__table__.create(connection, checkfirst=True)
            columns = inspect(connection).get_columns(
                "user_sessions", schema="business" if prefix else None
            )
            if not any(column["name"] == "scope" for column in columns):
                connection.execute(
                    text(
                        f"ALTER TABLE {prefix}user_sessions ADD COLUMN scope VARCHAR(16) DEFAULT 'admin' NOT NULL"
                    )
                )
            # Let existing browser cookies recover already-uploaded guest videos.
            connection.execute(
                text(
                    f"INSERT INTO {prefix}guest_sessions (token_hash, expires_at) "
                    f"SELECT owner, MAX(expires_at) FROM {prefix}videos "
                    "WHERE user_id IS NULL AND expires_at > CURRENT_TIMESTAMP GROUP BY owner "
                    "ON CONFLICT (token_hash) DO NOTHING"
                )
            )
            connection.execute(text(f"INSERT INTO {prefix}schema_versions VALUES (4)"))
        if 5 not in versions:
            columns = inspect(connection).get_columns(
                "analyses", schema="business" if prefix else None
            )
            if not any(column["name"] == "queue" for column in columns):
                connection.execute(text(f"ALTER TABLE {prefix}analyses ADD COLUMN queue JSON"))
            connection.execute(text(f"INSERT INTO {prefix}schema_versions VALUES (5)"))


def main():
    settings = Settings()
    engine, _ = connect(settings.database_url)
    migrate(engine)


if __name__ == "__main__":
    main()
