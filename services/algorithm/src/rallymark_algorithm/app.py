import hmac
import logging
import time
import uuid
from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from pydantic import BaseModel, Field
from sqlalchemy import text, tuple_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .db import database
from .models import ACTIVE, Job, WorkerStatus, utcnow
from .settings import InferenceConfig, Settings, configure_logging

REQUESTS = Counter("algorithm_http_requests_total", "Algorithm requests", ["status"])
logger = logging.getLogger(__name__)


class SubmitJob(BaseModel):
    id: UUID
    video_id: UUID
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config: InferenceConfig
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    algorithm_version: str = Field(min_length=1, max_length=100)


def job_view(job):
    return {
        "id": job.id,
        "status": job.status,
        "progress": job.progress,
        "result": job.result,
        "error": job.error,
        "attempt": job.attempt,
    }


def create_app(settings=None, sessions=None):
    settings = settings or Settings.load()
    configure_logging(settings.log_level)
    if sessions is None:
        _engine, sessions = database(settings.database_url)
    app = FastAPI(title="RallyMark algorithm", version="1.0.0")
    app.state.settings = settings

    def authorize(authorization: Annotated[str | None, Header()] = None):
        expected = "Bearer " + settings.internal_token
        if authorization is None or not hmac.compare_digest(authorization, expected):
            raise HTTPException(401, "Invalid service credentials")

    def worker_capacity(session):
        workers = (
            session.query(WorkerStatus)
            .filter(
                WorkerStatus.heartbeat_at > utcnow() - timedelta(seconds=settings.algorithm.lease_seconds),
                WorkerStatus.gpu_ready.is_(True),
                WorkerStatus.version == settings.algorithm.version,
            )
            .all()
        )
        return bool(workers), sum(
            (worker.capacity or {"available": 1}).get("available", 0) for worker in workers
        )

    def status_view(session, job):
        result = job_view(job)
        if job.status == "queued":
            ahead = (
                session.query(Job)
                .filter(
                    Job.status == "queued",
                    tuple_(Job.created_at, Job.id) < (job.created_at, job.id),
                )
                .count()
            )
            _, available = worker_capacity(session)
            result["queue"] = {"ahead": ahead, "waiting_for_capacity": available == 0}
        return result

    @app.middleware("http")
    async def record_request(request, call_next):
        request_id = str(uuid.uuid4())
        started = time.monotonic()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        REQUESTS.labels(str(response.status_code)).inc()
        logger.info(
            "http_request",
            extra={"request_id": request_id, "elapsed_seconds": round(time.monotonic() - started, 4)},
        )
        return response

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready():
        try:
            with sessions() as session:
                session.execute(text("SELECT 1"))
        except SQLAlchemyError:
            return JSONResponse({"status": "database_unavailable"}, status_code=503)
        return {"status": "ready"}

    @app.get("/internal/v1/capacity", dependencies=[Depends(authorize)])
    def capacity():
        with sessions() as session:
            has_workers, available = worker_capacity(session)
            queued = session.query(Job).filter(Job.status == "queued").count()
            active = session.query(Job).filter(Job.status.in_(ACTIVE)).count()
        return {
            "state": ("busy" if active or queued or not available else "ready")
            if has_workers
            else "unavailable",
            "queued": queued,
        }

    @app.get("/metrics", dependencies=[Depends(authorize)])
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/internal/v1/jobs", dependencies=[Depends(authorize)])
    def submit(payload: SubmitJob):
        if payload.algorithm_version != settings.algorithm.version:
            raise HTTPException(409, "Requested algorithm version unavailable")
        identity = {
            "video_id": str(payload.video_id),
            "sha256": payload.sha256,
            "config": payload.config.model_dump(exclude_unset=True),
            "config_hash": payload.config_hash,
            "algorithm_version": payload.algorithm_version,
        }
        with sessions() as session:
            job = session.get(Job, str(payload.id))
            if job is None:
                job = Job(id=str(payload.id), **identity)
                session.add(job)
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    job = session.get(Job, str(payload.id))
            if any(getattr(job, key) != value for key, value in identity.items()):
                raise HTTPException(409, "Job ID already belongs to another request")
            return status_view(session, job)

    @app.get("/internal/v1/jobs/{job_id}", dependencies=[Depends(authorize)])
    def get_job(job_id: UUID):
        with sessions() as session:
            job = session.get(Job, str(job_id))
            if job is None:
                raise HTTPException(404, "Job not found")
            return status_view(session, job)

    return app
