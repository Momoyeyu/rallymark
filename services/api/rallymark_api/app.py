import asyncio
import hashlib
import os
import re
import secrets
import time
import threading
import subprocess
from contextlib import asynccontextmanager, suppress
from datetime import UTC, timedelta
from pathlib import Path
from uuid import UUID, uuid4
from typing import Literal

from fastapi import FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .availability import CapacityUnavailable, check_capacity
from .config import Settings
from .db import ACTIVE, Analysis, Maintenance, Video, connect, now
from .dispatcher import run_dispatcher
from .logging import configure
from .media import InvalidVideo, probe, public_metadata, MAX_PIXELS
from .preparation import run_preparer

COOKIE = "rallymark_session"


class ApiError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


class Rally(BaseModel):
    id: str
    start_s: float
    end_s: float
    score: str | None = None
    score_status: Literal["observed", "inferred", "unknown"] = "unknown"


class Progress(BaseModel):
    completed: int
    total: int


class ErrorInfo(BaseModel):
    code: str
    message: str
    request_id: str | None = None


class AnalysisResponse(BaseModel):
    id: str
    video_id: str
    status: str
    progress: Progress | None
    rallies: list[Rally]
    warnings: list[str]
    error: ErrorInfo | None
    created_at: str
    config_hash: str
    algorithm_version: str


class VideoResponse(BaseModel):
    id: str
    title: str
    duration_s: float
    width: int
    height: int
    size_bytes: int
    created_at: str
    expires_at: str
    latest_analysis: AnalysisResponse | None


class UploadPolicy(BaseModel):
    max_upload_bytes: int
    max_duration_seconds: int
    max_pixels: int
    formats: list[str]
    video_codecs: list[str]
    audio_codecs: list[str]


class VideoList(BaseModel):
    items: list[VideoResponse]


class Event(BaseModel):
    name: str = Field(pattern=r"^[a-z_]{1,60}$")
    video_id: UUID | None = None
    analysis_id: UUID | None = None
    properties: dict = Field(default_factory=dict, max_length=12)


class EventBatch(BaseModel):
    events: list[Event] = Field(max_length=30)


def analysis_json(item):
    return {
        key: getattr(item, key)
        for key in (
            "id",
            "video_id",
            "status",
            "progress",
            "rallies",
            "warnings",
            "error",
            "config_hash",
            "algorithm_version",
        )
    } | {"created_at": item.created_at.isoformat()}


def video_json(db, item):
    latest = db.scalar(
        select(Analysis)
        .where(Analysis.video_id == item.id)
        .order_by(Analysis.created_at.desc())
        .limit(1)
    )
    return {
        key: getattr(item, key)
        for key in ("id", "title", "duration_s", "width", "height", "size_bytes")
    } | {
        "created_at": item.created_at.isoformat(),
        "expires_at": item.expires_at.isoformat(),
        "latest_analysis": analysis_json(latest) if latest else None,
    }


def new_analysis(video, config, key=None):
    return Analysis(
        id=str(uuid4()),
        video_id=video.id,
        status="queued",
        config=config.snapshot(),
        config_hash=config.digest(),
        algorithm_version=config.algorithm.version,
        idempotency_key=key,
        rallies=[],
        warnings=[],
    )


def create_app(settings=None, engine=None, probe_video=probe, capacity_check=None):
    settings = settings or Settings()
    config = settings.load_config()
    if engine is None:
        engine, factory = connect(settings.database_url)
    else:
        from sqlalchemy.orm import sessionmaker

        factory = sessionmaker(engine, expire_on_commit=False)
    logger = configure(config.logging.level)
    settings.media_root.mkdir(parents=True, exist_ok=True)
    temporary = settings.media_root / "temporary"
    temporary.mkdir(exist_ok=True)

    @asynccontextmanager
    async def lifespan(app):
        logger.info(
            "configuration_loaded",
            extra={
                "fields": {
                    "config_hash": config.digest(),
                    "algorithm_version": config.algorithm.version,
                }
            },
        )
        task = (
            asyncio.create_task(run_dispatcher(factory, settings, config))
            if settings.dispatcher_enabled
            else None
        )
        preparer = (
            asyncio.create_task(run_preparer(factory, settings, config))
            if settings.dispatcher_enabled
            else None
        )
        try:
            yield
        finally:
            if preparer:
                preparer.cancel()
                with suppress(asyncio.CancelledError):
                    await preparer
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            engine.dispose()

    thumbnails = threading.BoundedSemaphore(2)

    app = FastAPI(title="RallyMark API", version="0.1.0", lifespan=lifespan)
    app.state.factory = factory
    app.state.settings = settings

    @app.middleware("http")
    async def request_context(request, call_next):
        request.state.request_id = str(uuid4())
        began = time.monotonic()
        origin = request.headers.get("origin")
        if (
            request.method not in ("GET", "HEAD", "OPTIONS")
            and origin
            and origin.rstrip("/") != str(request.base_url).rstrip("/")
        ):
            response = JSONResponse(
                {
                    "error": {
                        "code": "invalid_origin",
                        "message": "请求来源无效。",
                        "request_id": request.state.request_id,
                    }
                },
                status_code=403,
            )
        else:
            try:
                response = await call_next(request)
            except Exception:
                logger.exception(
                    "request_failed", extra={"fields": {"request_id": request.state.request_id}}
                )
                response = JSONResponse(
                    {
                        "error": {
                            "code": "internal_error",
                            "message": "服务暂时不可用，请稍后重试。",
                            "request_id": request.state.request_id,
                        }
                    },
                    status_code=500,
                )
        response.headers["X-Request-ID"] = request.state.request_id
        logger.info(
            "http_request",
            extra={
                "fields": {
                    "request_id": request.state.request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round((time.monotonic() - began) * 1000, 1),
                }
            },
        )
        return response

    @app.exception_handler(ApiError)
    async def api_error(request, error):
        return JSONResponse(
            {
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "request_id": request.state.request_id,
                }
            },
            status_code=error.status,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, error):
        return JSONResponse(
            {
                "error": {
                    "code": "not_found" if error.status_code == 404 else "request_error",
                    "message": str(error.detail),
                    "request_id": request.state.request_id,
                }
            },
            status_code=error.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return JSONResponse(
            {
                "error": {
                    "code": "invalid_request",
                    "message": "请求参数无效。",
                    "request_id": request.state.request_id,
                }
            },
            status_code=422,
        )

    def owner(request):
        token = request.cookies.get(COOKIE, "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise ApiError(401, "session_required", "请刷新页面后重试。")
        return hashlib.sha256(token.encode()).hexdigest()

    def internal(request):
        expected = "Bearer " + settings.internal_token.get_secret_value()
        if not secrets.compare_digest(request.headers.get("authorization", ""), expected):
            raise ApiError(401, "unauthorized", "未授权。")

    def owned(db, identifier, request, lock=False):
        query = select(Video).where(
            Video.id == str(identifier), Video.owner == owner(request), Video.deleting.is_(False)
        )
        video = db.scalar(query.with_for_update() if lock else query)
        if video is None:
            raise ApiError(404, "not_found", "视频不存在或已过期。")
        return video

    def capacity(request_id=None):
        try:
            if capacity_check is not None:
                return capacity_check()
            return check_capacity(
                settings.algorithm_url, settings.internal_token.get_secret_value()
            )
        except CapacityUnavailable as error:
            logger.warning(
                "analysis_unavailable",
                extra={"fields": {"error_type": str(error), "request_id": request_id}},
            )
            raise ApiError(503, "analysis_unavailable", "分析服务暂不可用，请稍后重试。") from error

    @app.get("/api/v1/availability")
    def availability(request: Request):
        owner(request)
        with factory() as db:
            admit_analysis(db)
        return capacity(request.state.request_id)

    def admit_analysis(db):
        maintenance = db.scalar(
            select(Maintenance).where(Maintenance.id == 1).with_for_update(read=True)
        )
        if maintenance is None or maintenance.draining:
            raise ApiError(503, "maintenance", "服务正在更新，请稍后重试。")

    def media_path(video):
        return settings.media_root / (video.id + ".mp4")

    @app.post("/api/v1/session", status_code=204)
    def session(request: Request, response: Response):
        token = request.cookies.get(COOKIE, "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            token = secrets.token_urlsafe(32)
        response.set_cookie(
            COOKIE,
            token,
            max_age=30 * 86400,
            httponly=True,
            secure=config.application.session_cookie_secure,
            samesite="lax",
            path="/",
        )

    @app.get("/api/v1/upload-policy", response_model=UploadPolicy)
    def upload_policy(request: Request):
        owner(request)
        return {
            "max_upload_bytes": config.application.max_upload_bytes,
            "max_duration_seconds": config.application.max_duration_seconds,
            "max_pixels": MAX_PIXELS,
            "formats": ["mp4", "mov"],
            "video_codecs": ["avc", "hevc"],
            "audio_codecs": ["aac", "pcm-s16", "pcm-s24", "pcm-s32", "pcm-f32"],
        }

    @app.post("/api/v1/videos", response_model=VideoResponse, status_code=201)
    async def upload(
        request: Request,
        file: UploadFile = File(...),
        idempotency_key: str | None = Header(default=None, max_length=200),
    ):
        identity = owner(request)
        if idempotency_key:
            with factory() as db:
                existing = db.scalar(
                    select(Video).where(
                        Video.owner == identity,
                        Video.upload_key == idempotency_key,
                        Video.deleting.is_(False),
                    )
                )
                if existing:
                    await file.close()
                    return video_json(db, existing)
        await asyncio.to_thread(capacity, request.state.request_id)
        identifier = str(uuid4())
        temp = temporary / (identifier + ".upload")
        final = settings.media_root / (identifier + ".mp4")
        digest = hashlib.sha256()
        size = 0
        committed = False
        source = settings.media_root / (identifier + ".source")
        try:
            with temp.open("xb") as target:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > config.application.max_upload_bytes:
                        raise ApiError(413, "upload_too_large", "视频大小超过上传限制。")
                    digest.update(chunk)
                    target.write(chunk)
            if not size:
                raise ApiError(422, "invalid_video", "视频文件为空，请重新选择。")
            try:
                metadata = await asyncio.to_thread(
                    probe_video, temp, config.application.max_duration_seconds
                )
            except InvalidVideo as error:
                logger.info(
                    "media_rejected",
                    extra={
                        "fields": {
                            "request_id": request.state.request_id,
                            "size_bytes": size,
                            "reason": str(error),
                        }
                    },
                )
                raise ApiError(422, "invalid_video", str(error)) from error
            preparation = metadata.get("_prepare", "none") != "none"
            metadata = public_metadata(metadata)
            await asyncio.to_thread(capacity, request.state.request_id)
            os.replace(temp, source if preparation else final)
            with factory.begin() as db:
                if idempotency_key:
                    existing = db.scalar(
                        select(Video).where(
                            Video.owner == identity,
                            Video.upload_key == idempotency_key,
                            Video.deleting.is_(False),
                        )
                    )
                    if existing:
                        return video_json(db, existing)
                admit_analysis(db)
                video = Video(
                    id=identifier,
                    owner=identity,
                    upload_key=idempotency_key,
                    title=Path((file.filename or "video.mp4").replace("\\", "/")).name[:255],
                    size_bytes=size,
                    sha256=digest.hexdigest(),
                    created_at=now(),
                    expires_at=now() + timedelta(days=config.application.retention_days),
                    **metadata,
                )
                db.add(video)
                db.flush()
                analysis = new_analysis(video, config)
                if preparation:
                    analysis.status = "preparing"
                db.add(analysis)
                db.flush()
                result = video_json(db, video)
            committed = True
            logger.info(
                "video_uploaded",
                extra={
                    "fields": {
                        "video_id": identifier,
                        "size_bytes": size,
                        "request_id": request.state.request_id,
                    }
                },
            )
            return result
        except IntegrityError:
            if idempotency_key:
                with factory() as db:
                    existing = db.scalar(
                        select(Video).where(
                            Video.owner == identity,
                            Video.upload_key == idempotency_key,
                            Video.deleting.is_(False),
                        )
                    )
                    if existing:
                        return video_json(db, existing)
            raise
        finally:
            await file.close()
            temp.unlink(missing_ok=True)
            if not committed:
                final.unlink(missing_ok=True)
                source.unlink(missing_ok=True)

    @app.get("/api/v1/videos", response_model=VideoList)
    def videos(request: Request):
        with factory() as db:
            items = db.scalars(
                select(Video)
                .where(
                    Video.owner == owner(request),
                    Video.deleting.is_(False),
                    Video.expires_at > now(),
                )
                .order_by(Video.created_at.desc())
                .limit(100)
            )
            return {"items": [video_json(db, item) for item in items]}

    @app.get("/api/v1/videos/{identifier}", response_model=VideoResponse)
    def get_video(identifier: UUID, request: Request):
        with factory() as db:
            return video_json(db, owned(db, identifier, request))

    @app.post("/api/v1/videos/{identifier}/analyses", response_model=AnalysisResponse)
    def analyze(
        identifier: UUID,
        request: Request,
        idempotency_key: str | None = Header(default=None, max_length=200),
    ):
        with factory.begin() as db:
            video = owned(db, identifier, request, lock=True)
            if idempotency_key:
                prior = db.scalar(
                    select(Analysis).where(
                        Analysis.video_id == video.id, Analysis.idempotency_key == idempotency_key
                    )
                )
                if prior:
                    return analysis_json(prior)
            existing = db.scalar(
                select(Analysis)
                .where(Analysis.video_id == video.id)
                .order_by(Analysis.created_at.desc())
                .limit(1)
            )
            if existing and (
                existing.status in ACTIVE
                or (idempotency_key and existing.idempotency_key == idempotency_key)
            ):
                return analysis_json(existing)
            capacity(request.state.request_id)
            admit_analysis(db)
            item = new_analysis(video, config, idempotency_key)
            if (
                not media_path(video).exists()
                or (existing and (existing.error or {}).get("code") == "media_preparation_failed")
            ) and (settings.media_root / (video.id + ".source")).exists():
                item.status = "preparing"
            db.add(item)
            db.flush()
            return analysis_json(item)

    @app.get("/api/v1/analyses/{identifier}", response_model=AnalysisResponse)
    def analysis(identifier: UUID, request: Request):
        with factory() as db:
            item = db.get(Analysis, str(identifier))
            if item is None:
                raise ApiError(404, "not_found", "分析任务不存在。")
            owned(db, item.video_id, request)
            return analysis_json(item)

    @app.get("/api/v1/videos/{identifier}/media")
    @app.head("/api/v1/videos/{identifier}/media")
    def media(identifier: UUID, request: Request):
        with factory() as db:
            video = owned(db, identifier, request)
            path = media_path(video)
            if not path.is_file():
                raise ApiError(404, "not_found", "视频文件不存在。")
            remaining = (video.expires_at.replace(tzinfo=UTC) - now()).total_seconds()
            if remaining <= 0:
                raise ApiError(404, "not_found", "视频不存在或已过期。")
            ttl = min(30, int(remaining))
            response = FileResponse(
                path,
                media_type="video/mp4",
                stat_result=path.stat(),
                headers={
                    "Cache-Control": f"private, max-age={ttl}, must-revalidate",
                    "Vary": "Cookie",
                },
            )
            if (
                not request.headers.get("range")
                and request.headers.get("if-none-match") == response.headers["etag"]
            ):
                return Response(
                    status_code=304,
                    headers={
                        key: response.headers[key] for key in ("etag", "cache-control", "vary")
                    },
                )
            return response

    def thumbnail(video, key, timestamp):
        directory = settings.media_root / "thumbnails" / video.id
        destination = directory / (key + ".jpg")
        if not destination.is_file():
            if not thumbnails.acquire(timeout=15):
                raise ApiError(503, "thumbnail_busy", "预览图正在生成，请稍后重试。")
            temporary_image = directory / (str(uuid4()) + ".jpg")
            try:
                if not destination.is_file():
                    directory.mkdir(parents=True, exist_ok=True)
                    subprocess.run(
                        [
                            "ffmpeg",
                            "-v",
                            "error",
                            "-nostdin",
                            "-ss",
                            str(timestamp),
                            "-i",
                            str(media_path(video)),
                            "-frames:v",
                            "1",
                            "-vf",
                            "scale=320:-2",
                            "-threads",
                            "1",
                            "-y",
                            str(temporary_image),
                        ],
                        check=True,
                        capture_output=True,
                        timeout=20,
                    )
                    os.replace(temporary_image, destination)
            except (subprocess.SubprocessError, OSError) as error:
                raise ApiError(503, "thumbnail_unavailable", "预览图暂时不可用。") from error
            finally:
                temporary_image.unlink(missing_ok=True)
                thumbnails.release()
        return FileResponse(
            destination, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"}
        )

    @app.get("/api/v1/videos/{identifier}/poster")
    def poster(identifier: UUID, request: Request):
        with factory() as db:
            video = owned(db, identifier, request)
            return thumbnail(video, "poster", min(1, video.duration_s / 2))

    @app.get("/api/v1/videos/{identifier}/rallies/{rally_id}/thumbnail")
    def rally_thumbnail(
        identifier: UUID, rally_id: str, request: Request, analysis_id: UUID | None = None
    ):
        with factory() as db:
            video = owned(db, identifier, request)
            query = select(Analysis).where(Analysis.video_id == video.id)
            query = (
                query.where(Analysis.id == str(analysis_id))
                if analysis_id
                else query.order_by(Analysis.created_at.desc()).limit(1)
            )
            analysis = db.scalar(query)
            rally = (
                next((item for item in analysis.rallies if item["id"] == rally_id), None)
                if analysis
                else None
            )
            if rally is None:
                raise ApiError(404, "not_found", "回合不存在。")
            key = hashlib.sha256((analysis.id + ":" + rally_id).encode()).hexdigest()
            return thumbnail(video, key, rally["start_s"])

    @app.get("/internal/media/{identifier}")
    @app.head("/internal/media/{identifier}")
    def internal_media(identifier: UUID, request: Request):
        internal(request)
        with factory() as db:
            video = db.get(Video, str(identifier))
            if video is None or video.deleting or not media_path(video).is_file():
                raise ApiError(404, "not_found", "视频文件不存在。")
            return FileResponse(media_path(video), media_type="video/mp4")

    @app.post("/api/v1/events", status_code=204)
    def events(batch: EventBatch, request: Request):
        owner(request)
        allowed = {"seconds", "enabled", "direction", "code", "duration_ms", "source"}
        for event in batch.events:
            properties = {
                k: v
                for k, v in event.properties.items()
                if k in allowed and isinstance(v, (str, int, float, bool)) and len(str(v)) <= 120
            }
            logger.info(
                "client_" + event.name,
                extra={
                    "fields": {
                        "request_id": request.state.request_id,
                        "video_id": str(event.video_id) if event.video_id else None,
                        "analysis_id": str(event.analysis_id) if event.analysis_id else None,
                        "properties": properties,
                    }
                },
            )

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready():
        with factory() as db:
            db.execute(text("SELECT 1"))
            if db.get(Maintenance, 1) is None:
                raise HTTPException(503, "Database migration required")
        return {"status": "ready"}

    @app.get("/internal/metrics")
    def metrics(request: Request):
        internal(request)
        with factory() as db:
            return {
                "analyses": dict(
                    db.execute(
                        select(Analysis.status, func.count()).group_by(Analysis.status)
                    ).all()
                )
            }

    return app


app = create_app() if os.environ.get("DATABASE_URL") else None
