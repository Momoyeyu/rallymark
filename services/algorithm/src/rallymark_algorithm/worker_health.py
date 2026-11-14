"""Container readiness follows the live dispatcher, including saturated pools."""

from datetime import timedelta

from .db import database
from .models import WorkerStatus, utcnow
from .settings import Settings


def worker_healthy(settings, sessions):
    with sessions() as session:
        return (
            session.query(WorkerStatus)
            .filter(
                WorkerStatus.heartbeat_at > utcnow() - timedelta(seconds=settings.algorithm.lease_seconds),
                WorkerStatus.version == settings.algorithm.version,
                WorkerStatus.gpu_ready.is_(True),
            )
            .first()
            is not None
        )


if __name__ == "__main__":
    settings = Settings.load()
    engine, sessions = database(settings.database_url)
    raise SystemExit(0 if worker_healthy(settings, sessions) else 1)
