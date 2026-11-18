from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

ALGORITHM_ACTIVE = ("queued", "downloading", "tad", "ocr", "postprocessing")

ACTIVE = ("preparing", *ALGORITHM_ACTIVE)


def now():
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    __table_args__ = {"schema": "business"}


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="member")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class UserSession(Base):
    __tablename__ = "user_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("business.users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    scope: Mapped[str] = mapped_column(String(16), default="admin", server_default="admin")


class GuestSession(Base):
    __tablename__ = "guest_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class LoginLimit(Base):
    __tablename__ = "login_limits"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    until: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    action: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    request_id: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Video(Base):
    __tablename__ = "videos"
    __table_args__ = (UniqueConstraint("owner", "upload_key"), {"schema": "business"})
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("business.users.id"), nullable=True, index=True
    )
    trashed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    upload_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    duration_s: Mapped[float]
    width: Mapped[int]
    height: Mapped[int]
    size_bytes: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    deleting: Mapped[bool] = mapped_column(Boolean, default=False)


class Analysis(Base):
    __tablename__ = "analyses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    video_id: Mapped[str] = mapped_column(ForeignKey("business.videos.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    progress: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    queue: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    rallies: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    config: Mapped[dict] = mapped_column(JSON)
    config_hash: Mapped[str] = mapped_column(String(64))
    algorithm_version: Mapped[str] = mapped_column(String(100))
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    submitted: Mapped[bool] = mapped_column(Boolean, default=False)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_poll_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Maintenance(Base):
    __tablename__ = "maintenance"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draining: Mapped[bool] = mapped_column(Boolean, default=False)


def connect(url):
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    engine = create_engine(url, pool_pre_ping=True, **kwargs)
    if url.startswith("sqlite"):
        engine = engine.execution_options(schema_translate_map={"business": None})
    return engine, sessionmaker(engine, expire_on_commit=False)
