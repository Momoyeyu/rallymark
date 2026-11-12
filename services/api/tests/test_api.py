from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from rallymark_api.app import create_app
from rallymark_api.config import Settings
from rallymark_api.db import Analysis, Maintenance, Video, connect, now
from rallymark_api.dispatcher import dispatch_once
from rallymark_api.migrate import migrate
from rallymark_api.ops import cleanup


@pytest.fixture
def context(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/test.db",
        internal_token="test-internal-token",
        media_root=tmp_path / "media",
        dispatcher_enabled=False,
    )
    engine, factory = connect(settings.database_url)
    migrate(engine)
    app = create_app(
        settings, engine, lambda path, maximum: dict(duration_s=12, width=1920, height=1080)
    )
    with TestClient(app) as client:
        client.post("/api/v1/session")
        yield client, app, factory, settings


def upload(client, filename="match.mp4", body=b"video-bytes"):
    return client.post("/api/v1/videos", files={"file": (filename, body, "video/mp4")})


def test_upload_and_anonymous_isolation(context):
    client, app, factory, settings = context
    response = upload(client)
    assert response.status_code == 201
    video = response.json()
    assert video["latest_analysis"]["status"] == "queued"
    assert len(client.get("/api/v1/videos").json()["items"]) == 1
    with TestClient(app) as stranger:
        stranger.post("/api/v1/session")
        assert stranger.get(f"/api/v1/videos/{video['id']}").status_code == 404
        assert stranger.get(f"/api/v1/analyses/{video['latest_analysis']['id']}").status_code == 404
        assert stranger.get(f"/api/v1/videos/{video['id']}/media").status_code == 404
        assert stranger.get("/api/v1/videos").json() == {"items": []}


def test_range_media_and_internal_auth(context):
    client, _, _, _ = context
    video = upload(client, body=b"0123456789").json()
    url = f"/api/v1/videos/{video['id']}/media"
    result = client.get(url, headers={"Range": "bytes=2-5"})
    assert result.status_code == 206
    assert result.content == b"2345"
    assert result.headers["content-range"] == "bytes 2-5/10"
    assert client.get(url, headers={"Range": "bytes=99-100"}).status_code == 416
    assert client.head(url).content == b""
    internal = f"/internal/media/{video['id']}"
    assert client.get(internal).status_code == 401
    assert (
        client.get(internal, headers={"Authorization": "Bearer test-internal-token"}).content
        == b"0123456789"
    )


def test_invalid_file_and_request_origin(context):
    client, _, _, _ = context
    assert upload(client, filename="match.mov").status_code == 422
    assert upload(client, body=b"").status_code == 422
    assert (
        client.post("/api/v1/session", headers={"Origin": "http://another-origin"}).status_code
        == 403
    )


def test_active_analysis_and_retry_idempotency(context):
    client, _, factory, _ = context
    video = upload(client).json()
    url = f"/api/v1/videos/{video['id']}/analyses"
    assert client.post(url).json()["id"] == video["latest_analysis"]["id"]
    with factory.begin() as db:
        db.get(Analysis, video["latest_analysis"]["id"]).status = "failed"
    retried = client.post(url, headers={"Idempotency-Key": "retry-one"}).json()
    assert retried["id"] != video["latest_analysis"]["id"]
    assert client.post(url, headers={"Idempotency-Key": "retry-one"}).json()["id"] == retried["id"]


def test_cleanup_skips_running_and_supports_dry_run(context):
    client, _, factory, settings = context
    video = upload(client).json()
    with factory.begin() as db:
        item = db.get(Video, video["id"])
        item.expires_at = now() - timedelta(days=1)
    assert cleanup(factory, settings.media_root)["video_ids"] == []
    with factory.begin() as db:
        db.get(Analysis, video["latest_analysis"]["id"]).status = "failed"
    assert cleanup(factory, settings.media_root)["video_ids"] == [video["id"]]
    assert (settings.media_root / (video["id"] + ".mp4")).exists()
    cleanup(factory, settings.media_root, apply=True)
    assert not (settings.media_root / (video["id"] + ".mp4")).exists()
    with factory() as db:
        assert db.get(Video, video["id"]) is None


def test_migrations_are_idempotent(context):
    _, app, _, _ = context
    migrate(app.state.factory.kw["bind"])


def test_dispatcher_submits_and_commits_result(context):
    import asyncio

    client, _, factory, settings = context
    video = upload(client).json()
    analysis_id = video["latest_analysis"]["id"]

    def handle(request):
        assert request.headers["authorization"] == "Bearer test-internal-token"
        return httpx.Response(
            200,
            json={
                "id": analysis_id,
                "status": "succeeded",
                "progress": None,
                "error": None,
                "result": {"rallies": [{"id": "r1", "start_s": 1, "end_s": 3}], "warnings": []},
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as remote:
            return await dispatch_once(factory, settings, settings.load_config(), remote)

    assert asyncio.run(run())
    result = client.get(f"/api/v1/analyses/{analysis_id}").json()
    assert result["status"] == "succeeded"
    assert result["rallies"] == [
        {"id": "r1", "start_s": 1.0, "end_s": 3.0, "score": None, "score_status": "unknown"}
    ]
    with factory() as db:
        assert db.scalar(select(Analysis).where(Analysis.id == analysis_id)).lease_token is None


def test_upload_idempotency_does_not_create_another_task(context):
    client, _, factory, _ = context
    args = {
        "files": {"file": ("match.mp4", b"video", "video/mp4")},
        "headers": {"Idempotency-Key": "upload-once"},
    }
    first = client.post("/api/v1/videos", **args)
    second = client.post("/api/v1/videos", **args)
    assert first.json()["id"] == second.json()["id"]
    with factory() as db:
        assert len(list(db.scalars(select(Analysis)))) == 1


def test_readiness_and_config_snapshot(context):
    client, _, _, settings = context
    assert client.get("/health/ready").status_code == 200
    video = upload(client).json()
    assert video["latest_analysis"]["config_hash"] == settings.load_config().digest()
    assert video["latest_analysis"]["algorithm_version"] == "ftt-540cc9f"


def test_invalid_algorithm_result_does_not_publish(context):
    import asyncio

    client, _, factory, settings = context
    video = upload(client).json()
    analysis_id = video["latest_analysis"]["id"]

    def handle(request):
        return httpx.Response(
            200,
            json={
                "id": analysis_id,
                "status": "succeeded",
                "result": {"rallies": [{"id": "x", "start_s": 8, "end_s": 2}]},
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as remote:
            await dispatch_once(factory, settings, settings.load_config(), remote)

    asyncio.run(run())
    result = client.get(f"/api/v1/analyses/{analysis_id}").json()
    assert result["status"] != "succeeded"
    assert result["rallies"] == []


def test_private_poster_and_rally_thumbnail_cache(context, monkeypatch):
    from pathlib import Path
    import rallymark_api.app as module

    client, app, factory, _ = context
    video = upload(client).json()
    calls = []

    def render(command, **kwargs):
        calls.append(command)
        Path(command[-1]).write_bytes(b"jpeg-preview")

    monkeypatch.setattr(module.subprocess, "run", render)
    poster = f"/api/v1/videos/{video['id']}/poster"
    assert client.get(poster).content == b"jpeg-preview"
    assert client.get(poster).content == b"jpeg-preview"
    assert len(calls) == 1
    with TestClient(app) as stranger:
        stranger.post("/api/v1/session")
        assert stranger.get(poster).status_code == 404
    with factory.begin() as db:
        analysis = db.get(Analysis, video["latest_analysis"]["id"])
        analysis.status = "succeeded"
        analysis.rallies = [{"id": "r1", "start_s": 2, "end_s": 3}]
    url = f"/api/v1/videos/{video['id']}/rallies/r1/thumbnail"
    assert client.get(url).status_code == 200
    assert client.get(url.replace("r1/", "arbitrary/")).status_code == 404
    assert calls[-1][calls[-1].index("-ss") + 1] == "2"


def test_configured_upload_byte_limit(context, tmp_path):
    client, app, _, settings = context
    config_file = tmp_path / "limit.yaml"
    config_file.write_text("application:\n  max_upload_bytes: 4\n")
    limited = create_app(
        settings.model_copy(update={"config_path": config_file}), app.state.factory.kw["bind"]
    )
    with TestClient(limited) as browser:
        browser.post("/api/v1/session")
        response = upload(browser, body=b"12345")
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "upload_too_large"
        assert not list((settings.media_root / "temporary").iterdir())


@pytest.mark.parametrize(
    "codec,audio,duration", [("hevc", None, 12), ("h264", "mp3", 12), ("h264", None, 901)]
)
def test_probe_rejects_unsupported_video(monkeypatch, tmp_path, codec, audio, duration):
    import json
    import subprocess
    from rallymark_api.media import InvalidVideo, probe

    streams = [{"codec_type": "video", "codec_name": codec, "width": 1920, "height": 1080}]
    if audio:
        streams.append({"codec_type": "audio", "codec_name": audio})
    output = {
        "streams": streams,
        "format": {"duration": str(duration), "format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
    }
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 0, stdout=json.dumps(output)),
    )
    with pytest.raises(InvalidVideo):
        probe(tmp_path / "test.mp4", 900)


def test_draining_upload_rejection_cleans_files_and_preserves_idempotency(context):
    client, _, factory, settings = context
    args = {
        "files": {"file": ("match.mp4", b"video", "video/mp4")},
        "headers": {"Idempotency-Key": "existing-upload"},
    }
    original = client.post("/api/v1/videos", **args).json()
    with factory.begin() as db:
        db.get(Maintenance, 1).draining = True
    response = upload(client)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "maintenance"
    assert client.post("/api/v1/videos", **args).json()["id"] == original["id"]
    assert list((settings.media_root / "temporary").iterdir()) == []
    assert sorted(path.name for path in settings.media_root.glob("*.mp4")) == [
        original["id"] + ".mp4"
    ]
    with factory() as db:
        assert len(list(db.scalars(select(Video)))) == 1
        assert len(list(db.scalars(select(Analysis)))) == 1


def test_draining_rejects_new_retry_but_returns_existing_analysis(context):
    client, _, factory, _ = context
    video = upload(client).json()
    identifier = video["latest_analysis"]["id"]
    url = f"/api/v1/videos/{video['id']}/analyses"
    with factory.begin() as db:
        db.get(Maintenance, 1).draining = True
    assert client.post(url).json()["id"] == identifier
    with factory.begin() as db:
        item = db.get(Analysis, identifier)
        item.status = "failed"
        item.idempotency_key = "existing-retry"
    assert (
        client.post(url, headers={"Idempotency-Key": "existing-retry"}).json()["id"] == identifier
    )
    response = client.post(url, headers={"Idempotency-Key": "new-retry"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "maintenance"
    with factory() as db:
        assert len(list(db.scalars(select(Analysis)))) == 1


def test_draining_dispatches_queued_work_and_status_waits_for_completion(
    context, monkeypatch, capsys
):
    import asyncio
    import json
    import sys
    import rallymark_api.ops as ops

    client, _, factory, settings = context
    video = upload(client).json()
    identifier = video["latest_analysis"]["id"]
    with factory.begin() as db:
        db.get(Maintenance, 1).draining = True
    monkeypatch.setattr(ops, "Settings", lambda: settings)
    monkeypatch.setattr(sys, "argv", ["ops", "status"])
    ops.main()
    assert json.loads(capsys.readouterr().out)["running"] == 1

    async def run():
        def handle(request):
            return httpx.Response(
                200,
                json={
                    "id": identifier,
                    "status": "succeeded",
                    "progress": None,
                    "error": None,
                    "result": {"rallies": [], "warnings": []},
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as remote:
            return await dispatch_once(factory, settings, settings.load_config(), remote)

    assert asyncio.run(run())
    assert client.get(f"/api/v1/analyses/{identifier}").json()["status"] == "succeeded"
    ops.main()
    assert json.loads(capsys.readouterr().out)["running"] == 0


def test_upload_checks_drain_after_video_validation(context):
    _, app, factory, settings = context

    def validation(path, maximum):
        with factory.begin() as db:
            db.get(Maintenance, 1).draining = True
        return dict(duration_s=12, width=1920, height=1080)

    uploading = create_app(settings, app.state.factory.kw["bind"], validation)
    with TestClient(uploading) as browser:
        browser.post("/api/v1/session")
        response = upload(browser)
    assert response.status_code == 503
    assert not list(settings.media_root.glob("*.mp4"))
    assert not list((settings.media_root / "temporary").iterdir())
    with factory() as db:
        assert list(db.scalars(select(Analysis))) == []
