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
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

from .scores import enrich_scores


class AnalysisFailure(Exception):
    def __init__(self, code, message, retryable=False):
        super().__init__(message)
        self.code, self.retryable = code, retryable


def parallel_branches(tad, ocr, check):
    cancelled = threading.Event()

    def checked():
        check()
        if cancelled.is_set():
            raise AnalysisFailure("peer_cancelled", "Analysis branch cancelled")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(branch, checked) for branch in (tad, ocr)]
        try:
            for future in as_completed(futures):
                future.result()
        except BaseException:
            cancelled.set()
            raise
    return tuple(future.result() for future in futures)


def process(command, log_path, deadline, check, progress=None, env=None):
    lines = queue.Queue()
    tail = deque(maxlen=64)
    with log_path.open("a") as log:
        child = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
            env=env,
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
                tail.append(line)
                log.write(line)
                log.flush()
                match = re.match(r"INFER_WINDOW\s+(\d+)\s+(\d+)", line)
                if match and progress:
                    progress("tad", int(match[1]), int(match[2]))
            if child.returncode:
                if "out of memory" in "".join(tail).lower():
                    raise AnalysisFailure(
                        "gpu_out_of_memory", "GPU capacity changed during analysis", retryable=True
                    )
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


def load_ftt(settings, relative):
    spec = importlib.util.spec_from_file_location(
        "ftt_" + relative.replace("/", "_"), settings.ftt_root / relative
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fuse_predictions(settings, config, tad, ocr, duration, observations=None):
    module = load_ftt(settings, "code/postprocess_rallies.py")
    # Missing fields belong to legacy snapshots; never apply new defaults to them.
    return module.postprocess(
        tad,
        ocr,
        top_k=config["tad_top_k"],
        nearby_seconds=config["nearby_seconds"],
        protect_top_m=config.get("protect_top_m", 0),
        min_duration_s=config.get("min_duration_s", 0),
        score_filter=config.get("score_filter", False),
        fragment_gap_s=config.get("fragment_gap_s", 1),
        score_confidence=config.get("score_confidence", 0.8),
        edge_window_s=config.get("edge_window_s", 30),
        video_duration_s=duration,
        score_observations=observations,
    )


def ocr_environment(config, device=None):
    env = dict(os.environ)
    if device is not None:
        env["CUDA_VISIBLE_DEVICES"] = device
    if config.get("ocr_execution_provider", "cpu") == "cuda":
        libraries = [str(path) for root in sys.path if root for path in Path(root).glob("nvidia/*/lib")]
        if env.get("LD_LIBRARY_PATH"):
            libraries.append(env["LD_LIBRARY_PATH"])
        env["LD_LIBRARY_PATH"] = ":".join(libraries)
    return env


def run_tad(video, attempt, settings, config, deadline, check, progress, devices=None):
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
    command.extend(
        [
            "--decoder-mode",
            config.get("decoder_mode", "fresh"),
            "--decode-workers",
            str(config.get("decode_workers", 1)),
            "--prefetch-depth",
            str(config.get("prefetch_depth", 2)),
        ]
    )
    env = dict(os.environ, WEIGHTS_ROOT=str(settings.weights_root))
    if devices:
        if len(devices) > 1:
            command[1] = str(settings.ftt_root / "code/scripts/infer_multigpu.py")
            position = command.index("--device")
            command[position : position + 2] = ["--devices", ",".join(devices)]
        else:
            env["CUDA_VISIBLE_DEVICES"] = devices[0]
    process(command, attempt / "tad.log", deadline, check, progress, env=env)
    return json.loads((tad_dir / "predictions.json").read_text())["rallies"]


def run_ocr(video, attempt, stream, settings, config, deadline, check, device=None):
    ocr = []
    warnings = []
    observations = None
    if (stream["width"], stream["height"]) == (config["ocr_width"], config["ocr_height"]):
        filters = "fps=2,crop=" + config["ocr_crop"]
        if config["ocr_crop"] == "auto":
            layout_module = load_ftt(settings, "ocr/scoreboard_layout.py")
            layout = layout_module.detect_video_layout(video)
            (attempt / "layout.json").write_text(json.dumps(layout))
            filters = layout_module.crop_filter(layout["crop_xywh"][0])
            if layout["warning"]:
                warnings.append(layout["warning"])
            check()
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
                filters,
                "-q:v",
                "2",
                str(frames / "%06d.jpg"),
            ],
            attempt / "ocr.log",
            deadline,
            check,
        )
        requested = config.get("ocr_execution_provider", "cpu")
        providers = [requested, "cpu"] if requested == "cuda" else [requested]
        for provider in providers:
            try:
                process(
                    [
                        sys.executable,
                        str(settings.ftt_root / "ocr/run_scoreboard_ocr.py"),
                        "--frames",
                        str(frames),
                        "--out",
                        str(attempt / "ocr"),
                        "--execution-provider",
                        provider,
                    ],
                    attempt / "ocr.log",
                    deadline,
                    check,
                    env=ocr_environment({"ocr_execution_provider": provider}, device),
                )
                ocr = json.loads((attempt / "ocr/predictions.json").read_text())["rallies"]
                observations = json.loads((attempt / "ocr/observations.json").read_text())
                break
            except AnalysisFailure as error:
                if error.code != "inference_failed":
                    raise
                warnings.append(
                    "OCR accelerator unavailable; used CPU fallback"
                    if provider == "cuda"
                    else "OCR failed; results use TAD only"
                )
        if not ocr:
            warnings.append("No reliable scoreboard detected; results use TAD only")
    else:
        warnings.append("Video layout is outside the supported OCR dimensions; results use TAD only")
    return ocr, observations, warnings


def run_analysis(job, settings, progress, check, devices=None):
    config = job.config
    started = time.monotonic()
    deadline = started + config["timeout_seconds"]
    attempt = settings.work_root / job.id / (f"attempt-{job.attempt}")
    attempt.mkdir(parents=True, exist_ok=False)
    (attempt / "allocation.json").write_text(
        json.dumps({"gpu_devices": devices or [], "policy": settings.gpu_pool.model_dump()})
    )
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
                    if size > 1_000_000_000:
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
        ocr_finished = threading.Event()

        def tad_branch(branch_check):
            result = run_tad(video, attempt, settings, config, deadline, branch_check, progress, devices)
            if not ocr_finished.is_set():
                progress("ocr")
            return result

        def ocr_branch(branch_check):
            result = run_ocr(
                video,
                attempt,
                stream,
                settings,
                config,
                deadline,
                branch_check,
                devices[0] if devices else None,
            )
            ocr_finished.set()
            return result

        if config.get("parallel_inference", False):
            tad, (ocr, observations, ocr_warnings) = parallel_branches(tad_branch, ocr_branch, check)
        else:
            tad = tad_branch(check)
            ocr, observations, ocr_warnings = ocr_branch(check)
        warnings.extend(ocr_warnings)
        progress("postprocessing")
        fused = fuse_predictions(settings, config, tad, ocr, duration, observations)
        warnings.extend(fused.get("score_constraints", {}).get("warnings", []))
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
