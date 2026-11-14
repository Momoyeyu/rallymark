import os
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from rallymark_algorithm.db import claim_job
from rallymark_algorithm.models import Base, Job, utcnow


@pytest.fixture
def sessions():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL required for PostgreSQL lease integration tests")
    schema = "algorithm_test_" + uuid.uuid4().hex
    engine = create_engine(url, execution_options={"schema_translate_map": {"algorithm": schema}})
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        Base.metadata.create_all(conn)
    yield sessionmaker(engine, expire_on_commit=False)
    with engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    engine.dispose()


def job(**overrides):
    values = {
        "id": str(uuid.uuid4()),
        "video_id": str(uuid.uuid4()),
        "sha256": "a" * 64,
        "config": {},
        "config_hash": "b" * 64,
        "algorithm_version": "test",
        "status": "queued",
    }
    return Job(**(values | overrides))


def test_claim_skips_locked_and_recovers_stale_lease(sessions):
    first, second = job(), job()
    with sessions.begin() as session:
        session.add_all([first, second])
    with sessions.begin() as a, sessions.begin() as b:
        one = claim_job(a, "a", 60, 2)
        two = claim_job(b, "b", 60, 2)
        assert one.id != two.id
        assert one.attempt == two.attempt == 1
    with sessions.begin() as session:
        session.get(Job, one.id).lease_until = utcnow() - timedelta(seconds=10)
    with sessions.begin() as session:
        recovered = claim_job(session, "new", 60, 2)
        assert recovered.id == one.id
        assert recovered.attempt == 2
    with sessions.begin() as session:
        session.get(Job, one.id).lease_until = utcnow() - timedelta(seconds=10)
    with sessions.begin() as session:
        assert claim_job(session, "third", 60, 2) is None
        assert session.get(Job, one.id).status == "failed"


def test_gpu_uuid_reservation_is_exclusive_and_released(sessions):
    from rallymark_algorithm.gpu_pool import Device, Reservation

    engine = sessions.kw["bind"]
    uuid_key = "GPU-test-" + uuid.uuid4().hex
    device = Device("0", uuid_key, "test", 32760, 30000, 0)
    a = Reservation(engine, [device])
    b = Reservation(engine, [device])
    try:
        assert a.devices == [device]
        assert b.devices == []
    finally:
        a.close()
        b.close()
    c = Reservation(engine, [device])
    try:
        assert c.devices == [device]
    finally:
        c.close()


def test_recovery_without_any_gpu_requeues_or_exhausts_without_new_attempt(sessions):
    from rallymark_algorithm.db import recover_expired

    retryable = job(status="tad", attempt=1, worker_id="lost", lease_until=utcnow() - timedelta(seconds=5))
    exhausted = job(status="ocr", attempt=2, worker_id="lost", lease_until=utcnow() - timedelta(seconds=5))
    with sessions.begin() as session:
        session.add_all([retryable, exhausted])
    with sessions.begin() as session:
        recover_expired(session, 2)
    with sessions() as session:
        a, b = session.get(Job, retryable.id), session.get(Job, exhausted.id)
        assert (a.status, a.attempt, a.worker_id, a.lease_until) == ("queued", 1, None, None)
        assert (b.status, b.attempt, b.worker_id, b.lease_until) == ("failed", 2, None, None)


def test_reservations_do_not_exhaust_transaction_pool(sessions):
    from rallymark_algorithm.db import reservation_database
    from rallymark_algorithm.gpu_pool import Device, Reservation

    locks = reservation_database(sessions.kw["bind"].url)
    transactions = create_engine(sessions.kw["bind"].url, pool_size=1, max_overflow=0, pool_timeout=0.2)
    reservations = []
    pinned = transactions.connect()
    try:
        for i in range(3):
            reservations.append(
                Reservation(locks, [Device(str(i), "GPU-" + uuid.uuid4().hex, "test", 32760, 30000, 0)])
            )
        assert pinned.scalar(text("SELECT 1")) == 1
        pinned.close()
        with transactions.begin() as connection:
            assert connection.scalar(text("SELECT 1")) == 1
    finally:
        pinned.close()
        for reservation in reservations:
            reservation.close()
        transactions.dispose()
        locks.dispose()
