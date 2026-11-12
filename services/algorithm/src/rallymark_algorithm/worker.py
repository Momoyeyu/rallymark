import hashlib
import json
import logging
import shutil
import signal
import threading
import time
import uuid
from datetime import timedelta

from sqlalchemy import text

from .db import claim_job, database, gpu_lock
from .models import Job, WorkerStatus, utcnow
from .ops import cleanup
from .runner import AnalysisFailure, run_analysis
from .settings import Settings, configure_logging

logger = logging.getLogger(__name__)


def execute(job, settings, sessions, worker_id, connection):
    lost = threading.Event()
    stopped = threading.Event()
    errors = []

    def check():
        if lost.is_set():
            raise AnalysisFailure("worker_lease_lost", "Worker lost its database lease", retryable=True)

    def heartbeat():
        while not stopped.wait(settings.algorithm.lease_seconds / 4):
            try:
                connection.execute(text("SELECT 1"))
                with sessions.begin() as session:
                    current = session.get(Job, job.id)
                    if current.worker_id != worker_id or current.attempt != job.attempt:
                        raise RuntimeError("Job ownership changed")
                    current.lease_until = utcnow() + timedelta(seconds=settings.algorithm.lease_seconds)
                    worker = session.get(WorkerStatus, worker_id)
                    worker.heartbeat_at = utcnow()
            except Exception as error:  # noqa: BLE001 - isolate each job and loss of lease
                errors.append(error)
                lost.set()
                return

    def progress(stage, completed=None, total=None):
        check()
        with sessions.begin() as session:
            current = session.get(Job, job.id)
            if current.worker_id != worker_id or current.attempt != job.attempt:
                raise AnalysisFailure("worker_lease_lost", "Worker ownership changed", retryable=True)
            current.status = stage
            current.progress = {"completed": completed, "total": total} if total is not None else None
        logger.info("stage_changed", extra={"job_id": job.id, "stage": stage, "attempt": job.attempt})

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    began = time.monotonic()
    try:
        result = run_analysis(job, settings, progress, check)
        check()
        with sessions.begin() as session:
            current = session.get(Job, job.id)
            if current.worker_id == worker_id and current.attempt == job.attempt:
                current.result = result
                current.status = "succeeded"
                current.progress = None
                current.lease_until = None
                current.worker_id = None
        logger.info("job_completed", extra={"job_id": job.id, "elapsed_seconds": time.monotonic() - began})
    except Exception as error:
        code = error.code if isinstance(error, AnalysisFailure) else "analysis_failed"
        retryable = isinstance(error, AnalysisFailure) and error.retryable
        message = str(error) if isinstance(error, AnalysisFailure) else "Analysis failed; consult task log"
        logger.error(
            "job_failed",
            extra={
                "job_id": job.id,
                "video_id": job.video_id,
                "algorithm_version": job.algorithm_version,
                "error_code": code,
                "attempt": job.attempt,
            },
            exc_info=not isinstance(error, AnalysisFailure),
        )
        with sessions.begin() as session:
            current = session.get(Job, job.id)
            if current.worker_id == worker_id and current.attempt == job.attempt:
                current.status = (
                    "queued" if retryable and job.attempt < settings.algorithm.max_attempts else "failed"
                )
                current.error = {"code": code, "message": message}
                current.worker_id = None
                current.lease_until = None
    finally:
        stopped.set()
        thread.join(timeout=5)


def main():
    settings = Settings.load()
    configure_logging(settings.log_level)
    engine, sessions = database(settings.database_url)
    worker_id = str(uuid.uuid4())
    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    settings.work_root.mkdir(parents=True, exist_ok=True)
    if settings.algorithm.runner == "real":
        import torch

        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise RuntimeError("FFmpeg and ffprobe are required")
        import nms_1d_cpu  # noqa: F401 - validate the compiled runtime before accepting jobs

        manifest = json.loads((settings.ftt_root / "SHA256_MANIFEST.json").read_text())
        for name, expected in manifest.items():
            if not name.startswith("weights/"):
                continue
            file = settings.weights_root / name.split("/", 1)[1]
            digest = hashlib.sha256()
            with file.open("rb") as stream:
                for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                    digest.update(block)
            if file.stat().st_size != expected["bytes"] or digest.hexdigest() != expected["sha256"]:
                raise RuntimeError("Model asset checksum mismatch: " + file.name)
        if not torch.cuda.is_available() or "4090" not in torch.cuda.get_device_name(0):
            raise RuntimeError("The algorithm worker requires its assigned RTX 4090")
    last_cleanup = 0.0
    with gpu_lock(engine) as connection:
        while not stopping.is_set():
            if time.monotonic() - last_cleanup > 3600:
                cleanup(settings, sessions, apply=True)
                last_cleanup = time.monotonic()
            with sessions.begin() as session:
                session.merge(
                    WorkerStatus(
                        id=worker_id,
                        heartbeat_at=utcnow(),
                        gpu_ready=True,
                        version=settings.algorithm.version,
                    )
                )
                job = claim_job(
                    session, worker_id, settings.algorithm.lease_seconds, settings.algorithm.max_attempts
                )
            if job:
                execute(job, settings, sessions, worker_id, connection)
            else:
                stopping.wait(1)
        with sessions.begin() as session:
            worker = session.get(WorkerStatus, worker_id)
            if worker:
                session.delete(worker)


if __name__ == "__main__":
    main()
