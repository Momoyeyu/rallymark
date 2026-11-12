#!/usr/bin/env python3
"""Exercise a deployed upload -> analysis -> owned video playback flow."""

import argparse
import http.cookiejar
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gpu", action="store_true")
    args = parser.parse_args()
    base = os.environ.get("BASE_URL", "http://127.0.0.1:8080").rstrip("/")
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )

    def request(path, data=None, headers=None):
        response = opener.open(
            urllib.request.Request(base + path, data=data, headers=headers or {}),
            timeout=60,
        )
        return None if response.status == 204 else json.load(response)

    with tempfile.TemporaryDirectory() as folder:
        video = (
            Path(os.environ.get("SMOKE_VIDEO", ""))
            if args.gpu
            else Path(folder) / "sample.mp4"
        )
        if args.gpu and not video.is_file():
            raise RuntimeError(
                "Set SMOKE_VIDEO to the local validated FTT sample video"
            )
        if not args.gpu:
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=320x180:rate=24",
                    "-t",
                    "8",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(video),
                ],
                check=True,
            )
        request("/api/v1/session", b"")
        boundary = "rallymark-smoke-boundary"
        body = (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="smoke.mp4"\r\n'
                "Content-Type: video/mp4\r\n\r\n"
            ).encode()
            + video.read_bytes()
            + f"\r\n--{boundary}--\r\n".encode()
        )
        result = request(
            "/api/v1/videos",
            body,
            {"Content-Type": "multipart/form-data; boundary=" + boundary},
        )
        video_id = result["id"]
        deadline = time.monotonic() + (3000 if args.gpu else 180)
        while time.monotonic() < deadline:
            video_info = request("/api/v1/videos/" + video_id)
            analysis = video_info["latest_analysis"]
            if analysis and analysis["status"] == "failed":
                raise RuntimeError("Analysis failed: " + json.dumps(analysis["error"]))
            if analysis and analysis["status"] == "succeeded":
                break
            time.sleep(2)
        else:
            raise RuntimeError("Analysis timed out")
        response = opener.open(
            urllib.request.Request(
                base + "/api/v1/videos/" + video_id + "/media",
                headers={"Range": "bytes=0-1023"},
            )
        )
        assert response.status == 206
        assert len(response.read()) == 1024
        try:
            urllib.request.urlopen(base + "/api/v1/videos/" + video_id)
            raise RuntimeError("Anonymous ownership check failed")
        except urllib.error.HTTPError as error:
            assert error.code in (401, 404)
        rallies = analysis["rallies"]
        assert all(
            0 <= row["start_s"] < row["end_s"] <= video_info["duration_s"] + 0.05
            for row in rallies
        )
        print(
            json.dumps(
                {
                    "video_id": video_id,
                    "analysis_id": analysis["id"],
                    "rallies": len(rallies),
                    "warnings": analysis["warnings"],
                    "status": "passed",
                }
            )
        )


if __name__ == "__main__":
    main()
