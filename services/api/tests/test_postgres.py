"""Persistence checks run against a dedicated CI PostgreSQL database."""

import asyncio
import json
import os
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete

from rallymark_api.config import Settings
from rallymark_api.db import Analysis, Video, connect, now
from rallymark_api.dispatcher import dispatch_once
from rallymark_api.migrate import migrate

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="Dedicated PostgreSQL URL required"
)


def test_concurrent_dispatch_and_expired_lease_recovery(tmp_path):
    settings = Settings(
        database_url=os.environ["TEST_DATABASE_URL"],
        internal_token="integration-test-token",
        media_root=tmp_path,
    )
    engine, factory = connect(settings.database_url)
    migrate(engine)
    migrate(engine)
    video_id, analysis_id = str(uuid4()), str(uuid4())
    config = settings.load_config()
    with factory.begin() as db:
        db.add(
            Video(
                id=video_id,
                owner="integration",
                title="test.mp4",
                duration_s=10,
                width=1920,
                height=1080,
                size_bytes=10,
                sha256="0" * 64,
                expires_at=now() + timedelta(days=1),
            )
        )
        db.flush()
        db.add(
            Analysis(
                id=analysis_id,
                video_id=video_id,
                status="queued",
                config=config.snapshot(),
                config_hash=config.digest(),
                algorithm_version=config.algorithm.version,
                lease_token="old-worker",
                lease_until=now() - timedelta(seconds=1),
                next_poll_at=now() - timedelta(days=1000),
            )
        )
    calls = []

    async def run():
        started, finish = asyncio.Event(), asyncio.Event()

        async def handle(request):
            identifier = json.loads(request.content)["id"]
            calls.append(identifier)
            if identifier == analysis_id:
                started.set()
                await finish.wait()
            return httpx.Response(
                200,
                json={
                    "id": identifier,
                    "status": "succeeded",
                    "result": {"rallies": [], "warnings": []},
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            first = asyncio.create_task(dispatch_once(factory, settings, config, client))
            await asyncio.wait_for(started.wait(), timeout=5)
            await dispatch_once(factory, settings, config, client)
            finish.set()
            await first

    try:
        asyncio.run(run())
        assert calls.count(analysis_id) == 1
        with factory() as db:
            item = db.get(Analysis, analysis_id)
            assert item.status == "succeeded"
            assert item.lease_token is None
    finally:
        with factory.begin() as db:
            db.execute(delete(Analysis).where(Analysis.video_id == video_id))
            db.execute(delete(Video).where(Video.id == video_id))
        engine.dispose()


def test_postgres_private_media_thumbnail_and_cleanup(tmp_path):
    import shutil
    import subprocess

    from fastapi.testclient import TestClient

    from rallymark_api.app import create_app
    from rallymark_api.ops import cleanup

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and ffprobe required for media integration")
    settings = Settings(
        database_url=os.environ["TEST_DATABASE_URL"],
        internal_token="integration-test-token",
        media_root=tmp_path / "media",
        dispatcher_enabled=False,
    )
    engine, factory = connect(settings.database_url)
    migrate(engine)
    clip = tmp_path / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=green:s=320x180:r=24",
            "-t",
            "2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(clip),
        ],
        check=True,
        timeout=20,
    )
    app = create_app(settings, engine, capacity_check=lambda: {"state": "ready", "queued": 0})
    identifier = None
    try:
        with TestClient(app) as client:
            client.post("/api/v1/session")
            response = client.post(
                "/api/v1/videos", files={"file": ("sample.mp4", clip.read_bytes(), "video/mp4")}
            )
            assert response.status_code == 201, response.text
            video = response.json()
            identifier = video["id"]
            assert video["width"] == 320
            assert video["duration_s"] == 2
            media = f"/api/v1/videos/{identifier}/media"
            ranged = client.get(media, headers={"Range": "bytes=0-99"})
            assert ranged.status_code == 206
            assert ranged.content == clip.read_bytes()[:100]
            poster = client.get(f"/api/v1/videos/{identifier}/poster")
            assert poster.status_code == 200
            assert poster.content.startswith(b"\xff\xd8")
            with factory.begin() as db:
                analysis = db.get(Analysis, video["latest_analysis"]["id"])
                analysis.status = "succeeded"
                analysis.rallies = [
                    {
                        "id": "r1",
                        "start_s": 0.5,
                        "end_s": 1.5,
                        "score": "1:0",
                        "score_status": "observed",
                    }
                ]
            thumbnail = client.get(f"/api/v1/videos/{identifier}/rallies/r1/thumbnail")
            assert thumbnail.status_code == 200
            assert thumbnail.content.startswith(b"\xff\xd8")
            cached = client.get(f"/api/v1/videos/{identifier}/rallies/r1/thumbnail")
            assert cached.content == thumbnail.content
            with TestClient(app) as stranger:
                stranger.post("/api/v1/session")
                assert stranger.get(media).status_code == 404
                assert stranger.get(f"/api/v1/videos/{identifier}/poster").status_code == 404
            result = client.get(f"/api/v1/analyses/{video['latest_analysis']['id']}").json()
            assert result["rallies"][0]["score"] == "1:0"
            cleanup(factory, settings.media_root, apply=True, video_id=identifier)
            assert not (settings.media_root / (identifier + ".mp4")).exists()
            assert not (settings.media_root / "thumbnails" / identifier).exists()
            assert client.get(media).status_code == 404
    finally:
        if identifier:
            with factory.begin() as db:
                db.execute(delete(Analysis).where(Analysis.video_id == identifier))
                db.execute(delete(Video).where(Video.id == identifier))
        engine.dispose()


def test_password_reset_serializes_with_inflight_login(tmp_path, monkeypatch):
    import threading
    from fastapi.testclient import TestClient
    from rallymark_api import admin
    from rallymark_api.app import create_app
    from rallymark_api.db import User, UserSession
    from rallymark_api.identity import password_hash

    settings = Settings(
        database_url=os.environ["TEST_DATABASE_URL"],
        internal_token="auth-concurrency-test-token",
        media_root=tmp_path,
        dispatcher_enabled=False,
    )
    engine, factory = connect(settings.database_url)
    migrate(engine)
    username = "race-" + uuid4().hex
    identifier = str(uuid4())
    with factory.begin() as db:
        db.add(
            User(
                id=identifier,
                username=username,
                password_hash=password_hash("oldpassword"),
                role="admin",
                active=True,
            )
        )
    app = create_app(settings, engine)
    verified, release, reset_done = threading.Event(), threading.Event(), threading.Event()
    original = admin.verify_password

    def gated(password, stored):
        valid = original(password, stored)
        if password == "oldpassword":
            verified.set()
            assert release.wait(5)
        return valid

    monkeypatch.setattr(admin, "verify_password", gated)
    with TestClient(app) as actor, TestClient(app) as pending:
        assert (
            actor.post(
                "/api/v1/admin/login", json={"username": "admin", "password": "admin"}
            ).status_code
            == 200
        )
        responses = {}

        def login():
            responses["login"] = pending.post(
                "/api/v1/admin/login", json={"username": username, "password": "oldpassword"}
            )

        def reset():
            responses["reset"] = actor.patch(
                "/api/v1/admin/users/" + identifier, json={"password": "newpassword"}
            )
            reset_done.set()

        login_thread, reset_thread = threading.Thread(target=login), threading.Thread(target=reset)
        login_thread.start()
        try:
            assert verified.wait(5)
            reset_thread.start()
            assert not reset_done.wait(0.3), (
                "Password reset must wait for the credential transaction"
            )
        finally:
            release.set()
            login_thread.join(5)
            if reset_thread.ident:
                reset_thread.join(5)
        assert responses["login"].status_code == 200
        assert responses["reset"].status_code == 200
        assert pending.get("/api/v1/admin/me").status_code == 401
    with factory.begin() as db:
        db.execute(delete(UserSession).where(UserSession.user_id == identifier))
        db.execute(delete(User).where(User.id == identifier))


def test_concurrent_guest_uploads_cannot_share_the_last_slot(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from fastapi.testclient import TestClient

    from rallymark_api.app import create_app

    settings = Settings(
        database_url=os.environ["TEST_DATABASE_URL"],
        internal_token="integration-test-token",
        media_root=tmp_path,
        dispatcher_enabled=False,
    )
    engine, _ = connect(settings.database_url)
    migrate(engine)
    gate = Barrier(2)

    def probe(path, _limit):
        if path.read_bytes() == b"contender":
            gate.wait(timeout=10)
        return {"duration_s": 12, "width": 1920, "height": 1080}

    app = create_app(settings, engine, probe, capacity_check=lambda: {"state": "ready"})

    def submit(client, body):
        return client.post("/api/v1/videos", files={"file": ("match.mp4", body, "video/mp4")})

    with TestClient(app) as phone, TestClient(app) as other_tab:
        assert phone.post("/api/v1/session").status_code == 204
        other_tab.cookies.update(phone.cookies)
        assert all(submit(phone, b"first").status_code == 201 for _ in range(4))
        with ThreadPoolExecutor(2) as pool:
            responses = list(
                pool.map(lambda client: submit(client, b"contender"), [phone, other_tab])
            )
        assert sorted(r.status_code for r in responses) == [201, 409]
        assert phone.get("/api/v1/account").json()["quota"] == {"used": 5, "limit": 5}
        registration = phone.post(
            "/api/v1/account/register",
            json={"username": "test-" + uuid4().hex, "password": "long-test-password"},
        )
        assert registration.status_code == 201
        assert registration.json()["quota"] == {"used": 5, "limit": None}
        assert other_tab.get("/api/v1/videos").status_code == 401
        assert submit(phone, b"account").status_code == 201
