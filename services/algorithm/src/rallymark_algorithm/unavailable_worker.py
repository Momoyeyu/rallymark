"""Explicit maintenance worker: reports unavailable capacity without fake inference."""

import logging
import signal
import threading
import uuid

from .db import database
from .models import WorkerStatus, utcnow
from .settings import Settings, configure_logging


def main():
    settings = Settings.load()
    configure_logging(settings.log_level)
    logging.getLogger(__name__).warning("worker_disabled", extra={"error_code": "hardware_unavailable"})
    engine, sessions = database(settings.database_url)
    identifier = str(uuid.uuid4())
    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    try:
        while not stopping.is_set():
            with sessions.begin() as session:
                session.merge(
                    WorkerStatus(
                        id=identifier,
                        heartbeat_at=utcnow(),
                        gpu_ready=False,
                        version=settings.algorithm.version,
                    )
                )
            stopping.wait(10)
    finally:
        with sessions.begin() as session:
            worker = session.get(WorkerStatus, identifier)
            if worker:
                session.delete(worker)
        engine.dispose()


if __name__ == "__main__":
    main()
