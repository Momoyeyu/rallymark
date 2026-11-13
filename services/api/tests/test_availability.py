import httpx
import pytest

from rallymark_api.availability import CapacityUnavailable, check_capacity


def test_capacity_accepts_busy_worker_but_rejects_unavailable():
    def transport(request):
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(200, json={"state": "busy", "queued": 3})

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        assert check_capacity("http://algorithm", "secret", client)["state"] == "busy"
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, json={"state": "unavailable", "detail": "/models/private"}
            )
        )
    ) as client:
        with pytest.raises(CapacityUnavailable):
            check_capacity("http://algorithm", "secret", client)


def test_capacity_rejects_malformed_or_unreachable_service():
    for payload in ({}, {"state": "ready"}, {"state": "unknown", "queued": 0}):
        with httpx.Client(
            transport=httpx.MockTransport(lambda _, p=payload: httpx.Response(200, json=p))
        ) as client:
            with pytest.raises(CapacityUnavailable):
                check_capacity("http://algorithm", "secret", client)


def test_unavailable_api_is_sanitized_and_keeps_history_readable(tmp_path):
    from fastapi.testclient import TestClient
    from rallymark_api.app import create_app
    from rallymark_api.config import Settings
    from rallymark_api.db import connect
    from rallymark_api.migrate import migrate

    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/state.db",
        media_root=tmp_path / "media",
        internal_token="test-internal-token",
        dispatcher_enabled=False,
    )
    engine, _ = connect(settings.database_url)
    migrate(engine)

    def unavailable():
        raise CapacityUnavailable("/models/secret CUDA traceback")

    with TestClient(create_app(settings, engine, capacity_check=unavailable)) as client:
        client.post("/api/v1/session")
        for response in [
            client.get("/api/v1/availability"),
            client.post("/api/v1/videos", files={"file": ("match.mp4", b"bytes", "video/mp4")}),
        ]:
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "analysis_unavailable"
            assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
            assert "secret" not in response.text
        assert client.get("/api/v1/videos").json() == {"items": []}
        assert not list(settings.media_root.glob("*.mp4"))
