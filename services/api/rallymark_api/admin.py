"""Authenticated storage operations; public demo ownership stays anonymous."""

import logging
import secrets
import shutil
from datetime import UTC, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from .db import ACTIVE, Analysis, AuditEvent, LoginLimit, User, UserSession, Video, now
from .errors import ApiError
from .identity import password_hash, token_hash, verify_password
from .ops import cleanup

COOKIE = "rallymark_admin"
COOKIE_PATH = "/api/v1/admin"


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserCreate(Login):
    username: str = Field(pattern=r"^[a-zA-Z0-9_.-]{3,64}$")
    password: str = Field(min_length=8, max_length=128)
    role: Literal["admin", "member"] = "member"


class UserUpdate(BaseModel):
    password: str | None = Field(default=None, min_length=8, max_length=128)
    role: Literal["admin", "member"] | None = None
    active: bool | None = None


class UserView(BaseModel):
    id: str
    username: str
    role: str
    active: bool
    created_at: str


def user_view(user):
    return {key: getattr(user, key) for key in ("id", "username", "role", "active")} | {
        "created_at": user.created_at.isoformat()
    }


def management_router(factory, settings, config, video_json, video_model, logger=None):
    router = APIRouter(prefix=COOKIE_PATH, tags=["management"])
    logger = logger or logging.getLogger("rallymark")
    dummy_hash = password_hash(secrets.token_urlsafe(32))

    def current(request: Request):
        with factory() as db:
            session = db.get(UserSession, token_hash(request.cookies.get(COOKIE, "")))
            if session is None or session.expires_at.replace(tzinfo=UTC) <= now():
                raise ApiError(401, "login_required", "请登录管理面板。")
            user = db.get(User, session.user_id)
            if user is None or not user.active:
                raise ApiError(401, "login_required", "请重新登录。")
            return user

    def administrator(user=Depends(current)):
        if user.role != "admin":
            raise ApiError(403, "admin_required", "需要管理员权限。")
        return user

    def audit(db, actor, action, request, target=None):
        db.add(
            AuditEvent(
                id=str(uuid4()),
                user_id=actor.id,
                action=action,
                target_id=target,
                request_id=request.state.request_id,
            )
        )
        logger.info(
            action,
            extra={
                "fields": {
                    "user_id": actor.id,
                    "target_id": target,
                    "request_id": request.state.request_id,
                }
            },
        )

    @router.post("/login", response_model=UserView)
    def login(body: Login, request: Request, response: Response):
        username = body.username.lower()
        key = token_hash((request.client.host if request.client else "unknown") + ":" + username)
        failure = False
        with factory.begin() as db:
            limit = db.scalar(select(LoginLimit).where(LoginLimit.key == key).with_for_update())
            if limit and limit.until.replace(tzinfo=UTC) > now() and limit.failures >= 5:
                raise ApiError(429, "login_limited", "尝试过多，请稍后再试。")
            user = db.scalar(select(User).where(User.username == username))
            valid = verify_password(body.password, user.password_hash if user else dummy_hash)
            if not valid or user is None or not user.active:
                if limit is None:
                    limit = LoginLimit(key=key, failures=0, until=now() + timedelta(minutes=15))
                    db.add(limit)
                elif limit.until.replace(tzinfo=UTC) <= now():
                    limit.failures, limit.until = 0, now() + timedelta(minutes=15)
                limit.failures += 1
                failure = True
            else:
                if limit:
                    db.delete(limit)
                # Rotate the browser session and prune expired tokens at login.
                db.execute(delete(UserSession).where(UserSession.expires_at < now()))
                db.execute(
                    delete(UserSession).where(
                        UserSession.token_hash == token_hash(request.cookies.get(COOKIE, ""))
                    )
                )
                token = secrets.token_urlsafe(32)
                db.add(
                    UserSession(
                        token_hash=token_hash(token),
                        user_id=user.id,
                        expires_at=now() + timedelta(hours=12),
                    )
                )
                audit(db, user, "admin_login", request)
                result = user_view(user)
        if failure:
            raise ApiError(401, "login_failed", "用户名或密码不正确。")
        response.set_cookie(
            COOKIE,
            token,
            max_age=43200,
            path=COOKIE_PATH,
            httponly=True,
            samesite="strict",
            secure=config.application.session_cookie_secure,
        )
        response.headers["Cache-Control"] = "no-store"
        return result

    @router.get("/me", response_model=UserView)
    def me(user=Depends(current)):
        return user_view(user)

    @router.post("/logout", status_code=204)
    def logout(request: Request, response: Response):
        with factory.begin() as db:
            db.execute(
                delete(UserSession).where(
                    UserSession.token_hash == token_hash(request.cookies.get(COOKIE, ""))
                )
            )
        response.delete_cookie(COOKIE, path=COOKIE_PATH)

    @router.get("/users", response_model=list[UserView])
    def users(actor=Depends(administrator)):
        with factory() as db:
            return [user_view(u) for u in db.scalars(select(User).order_by(User.created_at))]

    @router.post("/users", response_model=UserView, status_code=201)
    def create_user(body: UserCreate, request: Request, actor=Depends(administrator)):
        try:
            with factory.begin() as db:
                u = User(
                    id=str(uuid4()),
                    username=body.username.lower(),
                    password_hash=password_hash(body.password),
                    role=body.role,
                    active=True,
                )
                db.add(u)
                db.flush()
                audit(db, actor, "user_created", request, u.id)
                return user_view(u)
        except IntegrityError:
            raise ApiError(409, "username_exists", "用户名已存在。") from None

    @router.patch("/users/{identifier}", response_model=UserView)
    def update_user(
        identifier: UUID, body: UserUpdate, request: Request, actor=Depends(administrator)
    ):
        with factory.begin() as db:
            # Serialize role changes so concurrent requests cannot remove all admins.
            admins = db.scalars(
                select(User)
                .where(User.role == "admin", User.active.is_(True))
                .order_by(User.id)
                .with_for_update()
            ).all()
            u = db.get(User, str(identifier))
            if not u:
                raise ApiError(404, "not_found", "用户不存在。")
            if (
                u.role == "admin"
                and u.active
                and len(admins) == 1
                and (body.active is False or body.role == "member")
            ):
                raise ApiError(409, "last_admin", "至少保留一位启用的管理员。")
            for name in ("active", "role"):
                value = getattr(body, name)
                if value is not None:
                    setattr(u, name, value)
            if body.password is not None:
                u.password_hash = password_hash(body.password)
            db.execute(delete(UserSession).where(UserSession.user_id == u.id))
            audit(db, actor, "user_updated", request, u.id)
            return user_view(u)

    @router.get("/storage")
    def storage(actor=Depends(administrator)):
        usage = shutil.disk_usage(settings.media_root)
        with factory() as db:
            count, size = db.execute(
                select(func.count(Video.id), func.coalesce(func.sum(Video.size_bytes), 0))
            ).one()
            trash = db.scalar(
                select(func.count()).select_from(Video).where(Video.trashed_at.is_not(None))
            )
            expired = db.scalar(
                select(func.count()).select_from(Video).where(Video.expires_at < now())
            )
        return dict(
            disk_total_bytes=usage.total,
            disk_free_bytes=usage.free,
            disk_used_bytes=usage.used,
            video_count=count,
            video_bytes=size,
            trashed_count=trash,
            expired_count=expired,
            retention_days=config.application.retention_days,
        )

    @router.get("/videos")
    def videos(q: str = "", trashed: bool = False, page: int = 1, actor=Depends(administrator)):
        if not 1 <= page <= 100000 or len(q) > 100:
            raise ApiError(422, "invalid_request", "查询参数无效。")
        with factory() as db:
            query = select(Video).where(Video.deleting.is_(False))
            query = query.where(
                Video.trashed_at.is_not(None) if trashed else Video.trashed_at.is_(None)
            )
            if q:
                query = query.where(Video.title.icontains(q, autoescape=True))
            total = db.scalar(select(func.count()).select_from(query.subquery()))
            rows = db.scalars(
                query.order_by(Video.created_at.desc()).offset((page - 1) * 20).limit(20)
            )
            return {
                "items": [
                    video_json(db, v)
                    | {
                        "user_id": v.user_id,
                        "trashed_at": v.trashed_at.isoformat() if v.trashed_at else None,
                    }
                    for v in rows
                ],
                "total": total,
                "page": page,
            }

    def managed(db, identifier):
        v = db.scalar(
            select(Video)
            .where(Video.id == str(identifier), Video.deleting.is_(False))
            .with_for_update()
        )
        if v is None:
            raise ApiError(404, "not_found", "视频不存在。")
        return v

    @router.get("/videos/{identifier}", response_model=video_model)
    def detail(identifier: UUID, actor=Depends(administrator)):
        with factory() as db:
            return video_json(db, managed(db, identifier))

    @router.get("/videos/{identifier}/media")
    def media(identifier: UUID, actor=Depends(administrator)):
        with factory() as db:
            v = managed(db, identifier)
            path = settings.media_root / (v.id + ".mp4")
            if not path.is_file():
                raise ApiError(404, "not_found", "视频尚未准备完成。")
        return FileResponse(
            path, media_type="video/mp4", headers={"Cache-Control": "private, no-store"}
        )

    @router.post("/videos/{identifier}/{action}", status_code=204)
    def change_video(
        identifier: UUID,
        action: Literal["trash", "restore"],
        request: Request,
        actor=Depends(administrator),
    ):
        with factory.begin() as db:
            v = managed(db, identifier)
            if db.scalar(
                select(Analysis.id)
                .where(Analysis.video_id == v.id, Analysis.status.in_(ACTIVE))
                .limit(1)
            ):
                raise ApiError(409, "video_active", "视频正在处理中，请稍后操作。")
            if action == "restore" and v.expires_at.replace(tzinfo=UTC) <= now():
                raise ApiError(409, "video_expired", "视频已过期，无法恢复。")
            v.trashed_at = now() if action == "trash" else None
            audit(db, actor, "video_" + action, request, v.id)

    @router.post("/cleanup")
    def clean(request: Request, actor=Depends(administrator)):
        result = cleanup(factory, settings.media_root, apply=True)
        with factory.begin() as db:
            audit(db, actor, "storage_cleanup", request)
        return {"removed": len(result["video_ids"])}

    return router
