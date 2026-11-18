import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from rallymark_algorithm.app import create_app
from rallymark_algorithm.models import Base
from rallymark_algorithm.settings import Settings


@pytest.fixture
def client(tmp_path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        execution_options={"schema_translate_map": {"algorithm": None}},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    settings = Settings(
        database_url="sqlite://",
        internal_token="test-service-token",
        ftt_root=Path("."),
        environment="test",
        algorithm={"version": "test-algorithm"},
    )
    with TestClient(create_app(settings, sessions)) as client:
        client.app.state.sessions = sessions
        yield client


def payload():
    return {
        "id": str(uuid.uuid4()),
        "video_id": str(uuid.uuid4()),
        "sha256": "a" * 64,
        "config": {},
        "config_hash": "b" * 64,
        "algorithm_version": "test-algorithm",
    }


def test_service_auth_and_idempotent_identity(client):
    data = payload()
    assert client.post("/internal/v1/jobs", json=data).status_code == 401
    headers = {"Authorization": "Bearer test-service-token"}
    first = client.post("/internal/v1/jobs", json=data, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "queued"
    assert client.post("/internal/v1/jobs", json=data, headers=headers).json() == first.json()
    data["config"] = {"tad_top_k": 150}
    assert client.post("/internal/v1/jobs", json=data, headers=headers).status_code == 409
    assert client.get("/internal/v1/jobs/" + data["id"], headers=headers).json()["attempt"] == 0


def test_invalid_config_and_missing_job(client):
    headers = {"Authorization": "Bearer test-service-token"}
    data = payload()
    data["config"] = {"tad_top_k": 201}
    assert client.post("/internal/v1/jobs", json=data, headers=headers).status_code == 422
    assert client.get("/internal/v1/jobs/" + str(uuid.uuid4()), headers=headers).status_code == 404
    assert client.get("/health/ready").status_code == 200


def test_fake_cannot_start_in_production():
    with pytest.raises(ValueError):
        Settings(
            database_url="sqlite://",
            internal_token="test-service-token",
            ftt_root=Path("."),
            algorithm={"runner": "fake"},
        )


def test_api_requires_compatible_algorithm_version(client):
    data = payload()
    data["algorithm_version"] = "unknown"
    assert (
        client.post(
            "/internal/v1/jobs", json=data, headers={"Authorization": "Bearer test-service-token"}
        ).status_code
        == 409
    )


def test_capacity_requires_auth_and_reports_missing_workers(client):
    assert client.get("/internal/v1/capacity").status_code == 401
    response = client.get("/internal/v1/capacity", headers={"Authorization": "Bearer test-service-token"})
    assert response.json() == {"state": "unavailable", "queued": 0}
    assert client.get("/health/ready").status_code == 200


def test_capacity_distinguishes_busy_and_stale_workers(client):
    from datetime import timedelta

    from rallymark_algorithm.models import WorkerStatus, utcnow

    headers = {"Authorization": "Bearer test-service-token"}
    with client.app.state.sessions.begin() as session:
        session.add(
            WorkerStatus(id="worker", heartbeat_at=utcnow(), gpu_ready=True, version="test-algorithm")
        )
    assert client.get("/internal/v1/capacity", headers=headers).json()["state"] == "ready"
    client.post("/internal/v1/jobs", json=payload(), headers=headers)
    assert client.get("/internal/v1/capacity", headers=headers).json() == {"state": "busy", "queued": 1}
    with client.app.state.sessions.begin() as session:
        session.get(WorkerStatus, "worker").heartbeat_at = utcnow() - timedelta(minutes=5)
    assert client.get("/internal/v1/capacity", headers=headers).json()["state"] == "unavailable"


def test_task_snapshot_does_not_acquire_new_server_defaults(client):
    from rallymark_algorithm.models import Job

    data = payload()
    data["config"] = {"tad_top_k": 200, "timeout_seconds": 2700}
    response = client.post(
        "/internal/v1/jobs", json=data, headers={"Authorization": "Bearer test-service-token"}
    )
    assert response.status_code == 200
    with client.app.state.sessions() as session:
        assert session.get(Job, data["id"]).config == data["config"]


def test_external_gpu_saturation_queues_instead_of_becoming_unavailable(client):
    from rallymark_algorithm.models import Job, WorkerStatus, utcnow

    headers = {"Authorization": "Bearer test-service-token"}
    with client.app.state.sessions.begin() as session:
        session.add(
            WorkerStatus(
                id="scheduler",
                heartbeat_at=utcnow(),
                gpu_ready=True,
                version="test-algorithm",
                capacity={"available": 0, "total": 4},
            )
        )
    assert client.get("/internal/v1/capacity", headers=headers).json() == {"state": "busy", "queued": 0}
    first = client.post("/internal/v1/jobs", json=payload(), headers=headers).json()
    second = client.post("/internal/v1/jobs", json=payload(), headers=headers).json()
    assert first["attempt"] == second["attempt"] == 0
    assert first["queue"] == {"ahead": 0, "waiting_for_capacity": True}
    assert second["queue"] == {"ahead": 1, "waiting_for_capacity": True}
    with client.app.state.sessions.begin() as session:
        session.get(Job, first["id"]).status = "tad"
    first, second = (
        client.get(f"/internal/v1/jobs/{job['id']}", headers=headers).json() for job in (first, second)
    )
    assert "queue" not in first
    assert second["queue"] == {"ahead": 0, "waiting_for_capacity": True}


def test_worker_health_requires_fresh_compatible_dispatcher_but_allows_busy_pool(client):
    from datetime import timedelta

    from rallymark_algorithm.models import WorkerStatus, utcnow
    from rallymark_algorithm.worker_health import worker_healthy

    sessions = client.app.state.sessions
    settings = client.app.state.settings
    assert not worker_healthy(settings, sessions)
    with sessions.begin() as session:
        session.add(
            WorkerStatus(
                id="dispatcher",
                heartbeat_at=utcnow(),
                gpu_ready=True,
                version="test-algorithm",
                capacity={"available": 0, "total": 3},
            )
        )
    assert worker_healthy(settings, sessions)
    with sessions.begin() as session:
        session.get(WorkerStatus, "dispatcher").heartbeat_at = utcnow() - timedelta(minutes=5)
    assert not worker_healthy(settings, sessions)
