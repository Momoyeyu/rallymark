import hashlib
import importlib.util
import json
import math
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time

import httpx

from .scores import enrich_scores


class AnalysisFailure(Exception):
    def __init__(self, code, message, retryable=False):
        super().__init__(message)
        self.code, self.retryable = code, retryable


def process(command, log_path, deadline, check, progress=None):
    lines = queue.Queue()
    with log_path.open("a") as log:
        child = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True
        )

        def read():
            for line in child.stdout:
                lines.put(line)

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        try:
            while child.poll() is None or reader.is_alive() or not lines.empty():
                check()
                if time.monotonic() > deadline:
                    raise AnalysisFailure("analysis_timeout", "Analysis exceeded its time limit")
                try:
                    line = lines.get(timeout=0.25)
                except queue.Empty:
                    continue
                log.write(line)
                log.flush()
                match = re.match(r"INFER_WINDOW\s+(\d+)\s+(\d+)", line)
                if match and progress:
                    progress("tad", int(match[1]), int(match[2]))
            if child.returncode:
                raise AnalysisFailure("inference_failed", "Algorithm process failed; see task log")
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
            child.stdout.close()


def validate_rallies(rows, duration):
    normalized = []
    previous_end = 0.0
    for i, row in enumerate(rows, 1):
        start, end = row["start_s"], row["end_s"]
        if not all(
            isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in (start, end)
        ):
            raise AnalysisFailure("invalid_result", "Algorithm returned invalid timestamps")
        if start < previous_end or start >= duration or end <= start or end > duration + 0.05:
            raise AnalysisFailure(
                "invalid_result", "Algorithm returned overlapping or out-of-bounds intervals"
            )
        end = min(end, duration)
        normalized.append({"id": str(i), "start_s": float(start), "end_s": float(end)})
        previous_end = end
    return normalized


def run_analysis(job, settings, progress, check):
    config = job.config
    started = time.monotonic()
    deadline = started + config["timeout_seconds"]
    attempt = settings.work_root / job.id / (f"attempt-{job.attempt}")
    attempt.mkdir(parents=True, exist_ok=False)
    video = attempt / "input.mp4"
    digest = hashlib.sha256()
    try:
        with (
            httpx.Client(timeout=httpx.Timeout(60, connect=10)) as client,
            client.stream(
                "GET",
                settings.business_internal_url + "/internal/media/" + job.video_id,
                headers={"Authorization": "Bearer " + settings.internal_token},
            ) as response,
        ):
            response.raise_for_status()
            size = 0
            with video.open("wb") as stream:
                for block in response.iter_bytes(1024 * 1024):
                    check()
                    if time.monotonic() > deadline:
                        raise AnalysisFailure("analysis_timeout", "Video download timed out")
                    size += len(block)
                    if size > 500000000:
                        raise AnalysisFailure("invalid_media", "Video exceeds maximum size")
                    digest.update(block)
                    stream.write(block)
    except httpx.HTTPError as error:
        raise AnalysisFailure(
            "media_download_failed", "Cannot download source media", retryable=True
        ) from error
    if digest.hexdigest() != job.sha256:
        raise AnalysisFailure("media_checksum_mismatch", "Source video checksum does not match")
    probe = json.loads(
        subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(video)],
            text=True,
            timeout=30,
        )
    )
    duration = float(probe["format"]["duration"])
    stream = next(x for x in probe["streams"] if x["codec_type"] == "video")
    warnings = []
    fused_rows, ocr_rows = [], []
    if settings.algorithm.runner == "fake":
        for stage in ("tad", "ocr", "postprocessing"):
            progress(stage)
            check()
        rallies = [
            {"start_s": duration * 0.1, "end_s": duration * 0.3},
            {"start_s": duration * 0.6, "end_s": duration * 0.8},
        ]
    else:
        progress("tad")
        tad_dir = attempt / "tad"
        command = [
            sys.executable,
            str(settings.ftt_root / "code/scripts/infer_ftt_single_video_20261110.py"),
            "--video",
            str(video),
            "--output",
            str(tad_dir),
            "--checkpoint",
            str(settings.weights_root / "ftt_dual_adapter_seed42_epoch35_trainable.pth"),
            "--device",
            "cuda:0",
        ]
        os.environ["WEIGHTS_ROOT"] = str(settings.weights_root)
        process(command, attempt / "pipeline.log", deadline, check, progress)
        tad = json.loads((tad_dir / "predictions.json").read_text())["rallies"]
        ocr = []
        if (stream["width"], stream["height"]) == (config["ocr_width"], config["ocr_height"]):
            progress("ocr")
            frames = attempt / "ocr/frames"
            frames.mkdir(parents=True)
            process(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-nostdin",
                    "-i",
                    str(video),
                    "-vf",
                    "fps=2,crop=" + config["ocr_crop"],
                    "-q:v",
                    "2",
                    str(frames / "%06d.jpg"),
                ],
                attempt / "pipeline.log",
                deadline,
                check,
            )
            try:
                process(
                    [
                        sys.executable,
                        str(settings.ftt_root / "ocr/run_scoreboard_ocr.py"),
                        "--frames",
                        str(frames),
                        "--out",
                        str(attempt / "ocr"),
                    ],
                    attempt / "pipeline.log",
                    deadline,
                    check,
                )
                ocr = json.loads((attempt / "ocr/predictions.json").read_text())["rallies"]
            except AnalysisFailure as error:
                if error.code != "inference_failed":
                    raise
                warnings.append("OCR failed; results use TAD only")
            if not ocr:
                warnings.append("No reliable scoreboard detected; results use TAD only")
        else:
            warnings.append("Video layout is outside the supported OCR dimensions; results use TAD only")
        progress("postprocessing")
        spec = importlib.util.spec_from_file_location(
            "ftt_postprocess", settings.ftt_root / "code/postprocess_rallies.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fused = module.postprocess(
            tad, ocr, nearby_seconds=config["nearby_seconds"], top_k=config["tad_top_k"]
        )
        (attempt / "postprocessed.json").write_text(json.dumps(fused, ensure_ascii=False))
        rallies = fused["rallies"]
        fused_rows, ocr_rows = rallies, ocr
    normalized = validate_rallies(rallies, duration)
    if not fused_rows:
        fused_rows = [{} for _ in normalized]
    result = {"rallies": enrich_scores(normalized, fused_rows, ocr_rows), "warnings": warnings}
    temporary = attempt / "result.json.tmp"
    temporary.write_text(json.dumps(result, ensure_ascii=False))
    temporary.replace(attempt / "result.json")
    return result
