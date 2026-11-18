"""Product identity, revocable device sessions and guest video ownership."""

import re
import secrets
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

from .db import GuestSession, LoginLimit, User, UserSession, Video, as_utc, now
from .errors import ApiError
from .identity import password_hash, token_hash, verify_password

GUEST_COOKIE = "rallymark_session"
ACCOUNT_COOKIE = "rallymark_account"
PRODUCT = "product"
GUEST_LIMIT = 5
GUEST_GRACE = timedelta(minutes=5)
ACCOUNT_AGE = timedelta(days=30)


class Credentials(BaseModel):
    username: str = Field(pattern=r"^[a-zA-Z0-9_.-]{3,64}$")
    password: str = Field(min_length=1, max_length=128)


class Quota(BaseModel):
    used: int
    limit: int | None


class Account(BaseModel):
    id: str | None
    username: str | None
    quota: Quota


@dataclass(frozen=True)
class Identity:
    owner: str
    user: User | None = None

    def owns(self):
        if self.user:
            return Video.user_id == self.user.id
        return Video.user_id.is_(None) & (Video.owner == self.owner)


def cookie_hash(request, name):
    token = request.cookies.get(name, "")
    return token_hash(token) if re.fullmatch(r"[A-Za-z0-9_-]{43}", token) else None


def guest_session(db, request, *, lock=False):
    key = cookie_hash(request, GUEST_COOKIE)
    guest = db.get(GuestSession, key, with_for_update=lock) if key else None
    return guest if guest and as_utc(guest.expires_at) > now() else None


def account_user(db, request):
    key = cookie_hash(request, ACCOUNT_COOKIE)
    session = db.get(UserSession, key) if key else None
    if session and session.scope == PRODUCT and as_utc(session.expires_at) > now():
        user = db.get(User, session.user_id)
        if user and user.active:
            return user
    return None


def account_identity(user):
    return Identity(token_hash(f"account:{user.id}"), user)


def identify(db, request, *, lock_guest=False):
    if user := account_user(db, request):
        return account_identity(user)
    if guest := guest_session(db, request, lock=lock_guest):
        return Identity(guest.token_hash)
    raise ApiError(401, "session_required", "访客会话已失效，请刷新页面。")


def visible_videos(identity):
    return (
        identity.owns(),
        Video.trashed_at.is_(None),
        Video.deleting.is_(False),
        Video.expires_at > now(),
    )


def quota(db, identity):
    used = db.scalar(select(func.count()).select_from(Video).where(*visible_videos(identity)))
    return Quota(used=used, limit=None if identity.user else GUEST_LIMIT)


def require_upload_slot(db, identity):
    if not identity.user and quota(db, identity).used >= GUEST_LIMIT:
        raise ApiError(409, "guest_quota", "访客存储空间已满。请登录，或删除一个视频后再上传。")


def _set_cookie(response, name, token, secure, max_age=None):
    response.set_cookie(
        name, token, max_age=max_age, httponly=True, secure=secure, samesite="lax", path="/"
    )


def _revoke_current(db, request):
    key = cookie_hash(request, ACCOUNT_COOKIE)
    if key:
        db.execute(
            delete(UserSession).where(UserSession.token_hash == key, UserSession.scope == PRODUCT)
        )


def _limit(db, request, name):
    address = request.client.host if request.client else "unknown"
    key = token_hash(f"product:{address}:{name}")
    deadline = now() + timedelta(minutes=15)
    insert = postgres_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    db.execute(
        insert(LoginLimit)
        .values(key=key, failures=0, until=deadline)
        .on_conflict_do_nothing(index_elements=[LoginLimit.key])
    )
    row = db.get(LoginLimit, key, with_for_update=True)
    if as_utc(row.until) <= now():
        row.until, row.failures = deadline, 0
    if row.failures >= 10:
        raise ApiError(429, "login_limited", "尝试过多，请稍后再试。")
    row.failures += 1
    return row


def account_router(factory, config):
    router = APIRouter(prefix="/api/v1")
    secure = config.application.session_cookie_secure
    dummy = password_hash(secrets.token_urlsafe(32))

    @router.post("/session", status_code=204)
    def start_session(request: Request, response: Response):
        with factory.begin() as db:
            if account_user(db, request):
                return
            guest = guest_session(db, request, lock=True)
            if guest:
                guest.expires_at = now() + GUEST_GRACE
                return
            token = secrets.token_urlsafe(32)
            db.add(GuestSession(token_hash=token_hash(token), expires_at=now() + GUEST_GRACE))
        response.delete_cookie(ACCOUNT_COOKIE, path="/")
        _set_cookie(response, GUEST_COOKIE, token, secure)

    @router.get("/account", response_model=Account)
    def account(request: Request):
        with factory() as db:
            identity = identify(db, request)
            user = identity.user
            return Account(
                id=user.id if user else None,
                username=user.username if user else None,
                quota=quota(db, identity),
            )

    def grant(db, request, user):
        identity = account_identity(user)
        # Share the guest lock with upload publication so no upload can appear
        # under an invalidated guest after these videos have been bound.
        guest = guest_session(db, request, lock=True)
        if guest:
            db.execute(
                update(Video)
                .where(*visible_videos(Identity(guest.token_hash)))
                .values(user_id=user.id, owner=identity.owner, upload_key=None)
            )
            guest.expires_at = now()
        _revoke_current(db, request)
        token = secrets.token_urlsafe(32)
        db.add(
            UserSession(
                token_hash=token_hash(token),
                user_id=user.id,
                scope=PRODUCT,
                expires_at=now() + ACCOUNT_AGE,
            )
        )
        return token, Account(id=user.id, username=user.username, quota=quota(db, identity))

    def set_account(response, token):
        response.delete_cookie(GUEST_COOKIE, path="/")
        _set_cookie(response, ACCOUNT_COOKIE, token, secure, int(ACCOUNT_AGE.total_seconds()))

    @router.post("/account/register", response_model=Account, status_code=201)
    def register(body: Credentials, request: Request, response: Response):
        if len(body.password) < 8:
            raise ApiError(422, "short_password", "密码至少需要 8 个字符。")
        with factory.begin() as db:
            _limit(db, request, "register")
        try:
            with factory.begin() as db:
                user = User(
                    id=str(uuid4()),
                    username=body.username.lower(),
                    password_hash=password_hash(body.password),
                    role="member",
                )
                db.add(user)
                db.flush()
                token, result = grant(db, request, user)
        except IntegrityError as error:
            raise ApiError(409, "username_taken", "该用户名已被使用。") from error
        set_account(response, token)
        return result

    @router.post("/account/login", response_model=Account)
    def login(body: Credentials, request: Request, response: Response):
        username = body.username.lower()
        result = None
        with factory.begin() as db:
            limit = _limit(db, request, f"login:{username}")
            user = db.scalar(select(User).where(User.username == username).with_for_update())
            valid = verify_password(body.password, user.password_hash if user else dummy)
            if user and user.active and valid:
                db.delete(limit)
                token, result = grant(db, request, user)
        if result is None:
            raise ApiError(401, "login_failed", "用户名或密码不正确。")
        set_account(response, token)
        return result

    @router.post("/account/logout", status_code=204)
    def logout(request: Request, response: Response):
        with factory.begin() as db:
            _revoke_current(db, request)
        response.delete_cookie(ACCOUNT_COOKIE, path="/")

    return router
