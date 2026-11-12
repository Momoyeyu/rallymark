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
    app = create_app(settings, engine)
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
