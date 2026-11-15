import subprocess

import pytest

from rallymark_api.media import InvalidVideo, probe


def clip(tmp_path, codec="libx264", suffix=".mp4"):
    path = tmp_path / ("clip" + suffix)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=320x180:r=24:d=1",
            "-c:v",
            codec,
            "-threads",
            "1",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        timeout=30,
    )
    return path


def test_probe_accepts_h264_mov_and_missing_extension(tmp_path):
    path = clip(tmp_path, suffix=".mov")
    assert probe(path, 900)["_prepare"] == "remux"
    renamed = path.with_suffix(".upload")
    path.rename(renamed)
    assert probe(renamed, 900)["width"] == 320


def test_probe_identifies_hevc_conversion(tmp_path):
    assert probe(clip(tmp_path, codec="libx265", suffix=".mov"), 900)["_prepare"] == "transcode"


def test_probe_rejects_duration_and_malformed_input(tmp_path):
    with pytest.raises(InvalidVideo):
        probe(clip(tmp_path), 0.5)
    bad = tmp_path / "bad.mov"
    bad.write_bytes(b"not a movie")
    with pytest.raises(InvalidVideo):
        probe(bad, 900)


@pytest.mark.parametrize("codec,extension", [("libx264", ".mov"), ("libx265", ".mov")])
def test_business_preparation_is_durable_and_updates_checksum(tmp_path, codec, extension):
    import asyncio
    import hashlib
    from fastapi.testclient import TestClient
    from rallymark_api.app import create_app
    from rallymark_api.config import Settings
    from rallymark_api.db import Analysis, Video, connect
    from rallymark_api.migrate import migrate
    from rallymark_api.preparation import prepare_once
    from rallymark_api.ops import cleanup

    path = clip(tmp_path, codec=codec, suffix=extension)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/db.sqlite",
        internal_token="test-only-internal-token",
        media_root=tmp_path / "media",
        dispatcher_enabled=False,
    )
    engine, factory = connect(settings.database_url)
    migrate(engine)
    app = create_app(settings, engine, capacity_check=lambda: {"state": "ready", "queued": 0})
    with TestClient(app) as client:
        client.post("/api/v1/session")
        result = client.post(
            "/api/v1/videos", files={"file": ("15_RAW.MOV", path.read_bytes(), "video/quicktime")}
        )
        assert result.status_code == 201, result.text
        body = result.json()
        assert body["latest_analysis"]["status"] == "preparing"
        identifier = body["id"]
        assert not (settings.media_root / (identifier + ".mp4")).exists()
        assert cleanup(factory, settings.media_root, True, identifier)["video_ids"] == []
        assert asyncio.run(prepare_once(factory, settings, settings.load_config()))
        with factory() as db:
            analysis = db.get(Analysis, body["latest_analysis"]["id"])
            assert analysis.status == "queued"
            normalized = settings.media_root / (identifier + ".mp4")
            video = db.get(Video, identifier)
            assert video.sha256 == hashlib.sha256(normalized.read_bytes()).hexdigest()
            assert video.size_bytes == normalized.stat().st_size
            assert probe(normalized, 900)["_prepare"] == "none"
        response = client.get(f"/api/v1/videos/{identifier}/media", headers={"Range": "bytes=0-99"})
        assert response.status_code == 206
        if codec == "libx264":

            def frames(p):
                return subprocess.check_output(
                    ["ffmpeg", "-v", "error", "-i", str(p), "-map", "0:v:0", "-f", "framemd5", "-"]
                )

            assert frames(path) == frames(normalized)
        assert not asyncio.run(prepare_once(factory, settings, settings.load_config()))
        cleanup(factory, settings.media_root, True, identifier)  # queued jobs remain protected


def test_preparation_failure_can_retry_and_cleanup(tmp_path):
    import asyncio
    from datetime import timedelta
    from fastapi.testclient import TestClient
    from rallymark_api.app import create_app
    from rallymark_api.config import Settings
    from rallymark_api.db import Analysis, Video, connect, now
    from rallymark_api.migrate import migrate
    from rallymark_api.preparation import prepare_once
    from rallymark_api.ops import cleanup

    path = clip(tmp_path, suffix=".mov")
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/db.sqlite",
        internal_token="test-internal-key",
        media_root=tmp_path / "media",
        dispatcher_enabled=False,
    )
    engine, factory = connect(settings.database_url)
    migrate(engine)
    app = create_app(settings, engine, capacity_check=lambda: {"state": "ready", "queued": 0})
    with TestClient(app) as client:
        client.post("/api/v1/session")
        video = client.post(
            "/api/v1/videos", files={"file": ("phone.MOV", path.read_bytes())}
        ).json()
        source = settings.media_root / (video["id"] + ".source")
        source.write_bytes(b"broken")
        assert asyncio.run(prepare_once(factory, settings, settings.load_config()))
        failed = client.get("/api/v1/videos/" + video["id"]).json()["latest_analysis"]
        assert failed["status"] == "failed"
        assert failed["error"]["code"] == "media_preparation_failed"
        assert "ffprobe" not in failed["error"]["message"]
        source.write_bytes(path.read_bytes())
        retry = client.post("/api/v1/videos/" + video["id"] + "/analyses").json()
        assert retry["status"] == "preparing"
        # A crashed process's expired lease can be reclaimed.
        with factory.begin() as db:
            item = db.get(Analysis, retry["id"])
            item.lease_token, item.lease_until = "abandoned", now() - timedelta(seconds=1)
        assert asyncio.run(prepare_once(factory, settings, settings.load_config()))
        with factory.begin() as db:
            db.get(Analysis, retry["id"]).status = "succeeded"
        cleanup(factory, settings.media_root, True, video["id"])
        assert not source.exists()
        assert not (settings.media_root / (video["id"] + ".mp4")).exists()
        with factory() as db:
            assert db.get(Video, video["id"]) is None


def test_variable_frame_rate_is_normalized_to_the_video_clock(tmp_path):
    import json
    from rallymark_api.media import conversion_command

    source = tmp_path / "vfr.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=320x180:r=30:d=10",
            "-vf",
            "select='if(lt(t,5),1,not(mod(n,3)))'",
            "-fps_mode",
            "vfr",
            "-c:v",
            "libx265",
            "-x265-params",
            "pools=1:frame-threads=1:log-level=error",
            "-threads",
            "1",
            str(source),
        ],
        check=True,
        timeout=30,
    )
    info = probe(source, 900)
    assert info["_vfr"] and info["_prepare"] == "transcode"
    target = tmp_path / "normalized.mp4"
    subprocess.run(conversion_command(source, target, info, 10000000), check=True, timeout=30)
    normalized = probe(target, 900)
    assert not normalized["_vfr"]
    assert abs(normalized["duration_s"] - info["duration_s"]) < 0.25
    packets = json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "packet=pts_time",
                "-of",
                "json",
                str(target),
            ]
        )
    )["packets"]
    times = sorted(float(p["pts_time"]) for p in packets)
    assert times[150] == pytest.approx(5.0, abs=0.001)


def test_small_mux_timestamp_gap_does_not_force_h264_reencoding(tmp_path):
    source = tmp_path / "minor-gap.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=320x180:r=30:d=1",
            "-vf",
            "select=not(eq(n\\,15))",
            "-fps_mode",
            "vfr",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
        timeout=20,
    )
    info = probe(source, 900)
    assert info["_vfr"]
    assert info["_clock_drift_s"] < 0.1
    assert info["_prepare"] == "remux"
