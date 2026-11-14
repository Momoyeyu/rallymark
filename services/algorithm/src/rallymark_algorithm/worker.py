import hashlib
import json
import logging
import shutil
import signal
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from sqlalchemy import text

from .db import claim_job, database, gpu_lock
from .gpu_pool import Reservation, choose_devices, discover
from .models import Job, WorkerStatus, utcnow
from .ops import cleanup
from .runner import AnalysisFailure, run_analysis
from .settings import Settings, configure_logging

logger = logging.getLogger(__name__)


def execute(job, settings, sessions, worker_id, connection, devices=None):
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
        result = run_analysis(job, settings, progress, check, devices)
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


def validate_assets(settings):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("FFmpeg and ffprobe are required")
    import nms_1d_cpu  # noqa: F401 - validate compiled runtime before accepting jobs

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


def main():
    settings = Settings.load()
    configure_logging(settings.log_level)
    engine, sessions = database(settings.database_url)
    worker_id = str(uuid.uuid4())
    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    settings.work_root.mkdir(parents=True, exist_ok=True)
    real = settings.algorithm.runner == "real"
    if real:
        validate_assets(settings)
    pool = settings.gpu_pool
    minimum = max(settings.min_gpu_memory_gib, pool.admission_memory_gib)
    last_cleanup = 0.0
    previous_state = None
    futures = {}

    def run_reserved(job, reservation):
        try:
            devices = [device.uuid for device in reservation.devices] if real else None
            execute(job, settings, sessions, worker_id, reservation.connection, devices)
        finally:
            reservation.close()

    # Retain the original dispatcher fence across upgrades; individual devices also
    # have UUID locks whose sessions heartbeat with the running job's lease.
    with (
        gpu_lock(engine) as dispatcher,
        ThreadPoolExecutor(max_workers=pool.max_concurrent_jobs or 256) as executor,
    ):
        try:
            while not stopping.is_set():
                dispatcher.execute(text("SELECT 1"))
                for future in list(futures):
                    if future.done():
                        future.result()
                        del futures[future]
                if time.monotonic() - last_cleanup > 3600:
                    cleanup(settings, sessions, apply=True)
                    last_cleanup = time.monotonic()
                reserved = {uuid for allocation in futures.values() for uuid in allocation}
                devices = []
                ready = not real
                if real:
                    try:
                        devices = discover(settings.gpu_device)
                        ready = any(device.total_mib >= minimum * 1024 for device in devices)
                    except (OSError, ValueError, RuntimeError) as error:
                        logger.warning(
                            "gpu_telemetry_unavailable", extra={"error_code": type(error).__name__}
                        )
                    except Exception:
                        logger.exception("gpu_telemetry_failed")
                available = choose_devices(devices, reserved, 0, 1, minimum, pool.max_utilization)
                with sessions.begin() as session:
                    session.merge(
                        WorkerStatus(
                            id=worker_id,
                            heartbeat_at=utcnow(),
                            gpu_ready=ready,
                            capacity={
                                "available": len(available) if real else 1,
                                "total": len(devices) if real else 1,
                            },
                            version=settings.algorithm.version,
                        )
                    )
                    queued = session.query(Job).filter(Job.status == "queued").count()
                state = (ready, tuple(d.uuid for d in available), len(futures), queued)
                if state != previous_state:
                    logger.info(
                        "gpu_pool_state",
                        extra={
                            "available_gpus": len(available),
                            "active": len(futures),
                            "queued": queued,
                            "gpu_status": [
                                {
                                    "uuid": d.uuid,
                                    "free_mib": d.free_mib,
                                    "utilization": d.utilization,
                                    "compute_mib": d.compute_mib,
                                }
                                for d in devices
                            ],
                        },
                    )
                    previous_state = state
                if ready and len(futures) < (pool.max_concurrent_jobs or max(1, len(devices))):
                    candidates = choose_devices(
                        devices, reserved, pool.max_gpus_per_job, queued, minimum, pool.max_utilization
                    )
                    if candidates or not real:
                        reservation = Reservation(engine, candidates)
                        submitted = False
                        try:
                            if real:
                                valid = {
                                    d.uuid
                                    for d in choose_devices(
                                        discover(settings.gpu_device),
                                        set(),
                                        0,
                                        1,
                                        minimum,
                                        pool.max_utilization,
                                    )
                                }
                                if not reservation.devices or any(
                                    d.uuid not in valid for d in reservation.devices
                                ):
                                    stopping.wait(pool.poll_seconds)
                                    continue
                            # claim_job also recovers expired attempts, even with no queued rows.
                            with sessions.begin() as session:
                                job = claim_job(
                                    session,
                                    worker_id,
                                    settings.algorithm.lease_seconds,
                                    settings.algorithm.max_attempts,
                                )
                            if job:
                                allocation = [device.uuid for device in reservation.devices]
                                logger.info(
                                    "gpu_allocation", extra={"job_id": job.id, "gpu_devices": allocation}
                                )
                                future = executor.submit(run_reserved, job, reservation)
                                futures[future] = allocation
                                submitted = True
                        finally:
                            if not submitted:
                                reservation.close()
                stopping.wait(pool.poll_seconds)
        finally:
            # In-flight tasks retain their GPU locks until their process trees stop.
            executor.shutdown(wait=True)
            with sessions.begin() as session:
                worker = session.get(WorkerStatus, worker_id)
                if worker:
                    session.delete(worker)


if __name__ == "__main__":
    main()
