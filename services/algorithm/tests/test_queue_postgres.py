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
