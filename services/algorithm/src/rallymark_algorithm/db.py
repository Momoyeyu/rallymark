from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from .models import ACTIVE, Job, utcnow


def database(url):
    engine = create_engine(url, pool_pre_ping=True)
    return engine, sessionmaker(engine, expire_on_commit=False)


def reservation_database(url):
    return create_engine(url, pool_pre_ping=True, poolclass=NullPool)


@contextmanager
def gpu_lock(engine):
    # One dispatcher per database; its jobs have independent UUID reservations.
    with engine.connect() as connection:
        acquired = connection.execute(text("SELECT pg_try_advisory_lock(74219861)")).scalar()
        if not acquired:
            raise RuntimeError("Another algorithm worker owns the GPU lock")
        try:
            yield connection
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(74219861)"))


def recover_expired(session, max_attempts):
    expired = session.query(Job).filter(Job.status.in_(ACTIVE), Job.lease_until < utcnow()).with_for_update()
    for job in expired:
        if job.attempt >= max_attempts:
            job.status = "failed"
            job.error = {"code": "worker_interrupted", "message": "Worker interrupted repeatedly"}
        else:
            job.status = "queued"
        job.progress = None
        job.worker_id = None
        job.lease_until = None
    session.flush()


def claim_job(session, worker_id, lease_seconds, max_attempts):
    from datetime import timedelta

    recover_expired(session, max_attempts)
    job = (
        session.query(Job)
        .filter(Job.status == "queued")
        .order_by(Job.created_at, Job.id)
        .with_for_update(skip_locked=True)
        .first()
    )
    if job:
        job.status = "downloading"
        job.attempt += 1
        job.worker_id = worker_id
        job.progress = None
        job.error = None
        job.lease_until = utcnow() + timedelta(seconds=lease_seconds)
    return job
