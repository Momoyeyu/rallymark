"""Durable CPU media preparation owned by the business service."""

import asyncio
import hashlib
import logging
import os
import subprocess
import time
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import or_, select, text

from .db import Analysis, Video, now
from .media import InvalidVideo, conversion_command, inspect, public_metadata

logger = logging.getLogger("rallymark")
LOCK = 74217423


def checksum(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


async def prepare_once(factory, settings, config):
    reservation = factory.kw["bind"].connect()
    process = None
    output = None
    locked = False
    try:
        if reservation.dialect.name == "postgresql":
            locked = bool(
                reservation.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK})
            )
            reservation.commit()
            if not locked:
                return False
        token = str(uuid4())
        with factory.begin() as db:
            item = db.scalar(
                select(Analysis)
                .where(
                    Analysis.status == "preparing",
                    or_(Analysis.lease_until.is_(None), Analysis.lease_until < now()),
                )
                .order_by(Analysis.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if item is None:
                return False
            item.lease_token = token
            item.lease_until = now() + timedelta(seconds=60)
            identifier, analysis_id = item.video_id, item.id
        source = settings.media_root / (identifier + ".source")
        output = settings.media_root / (identifier + ".prepare.mp4")
        final = settings.media_root / (identifier + ".mp4")
        began = time.monotonic()
        fields = {"video_id": identifier, "analysis_id": analysis_id, "request_id": token}
        try:
            info = await asyncio.to_thread(inspect, source, config.application.max_duration_seconds)
            logger.info(
                "media_preparation_started",
                extra={"fields": fields | {"mode": info["_prepare"], "codec": info["_codec"]}},
            )
            process = await asyncio.create_subprocess_exec(
                *conversion_command(source, output, info, config.application.max_normalized_bytes),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            communication = asyncio.create_task(process.communicate())
            try:
                while True:
                    done, _ = await asyncio.wait([communication], timeout=10)
                    if done:
                        _, stderr = communication.result()
                        if process.returncode:
                            logger.warning(
                                "media_encoder_failed",
                                extra={
                                    "fields": fields
                                    | {"diagnostic": stderr.decode(errors="replace")[-1000:]}
                                },
                            )
                            raise InvalidVideo("视频转换未完成，请重试或选择兼容视频。")
                        break
                    reservation.execute(text("SELECT 1"))
                    reservation.commit()
                    with factory.begin() as db:
                        item = db.get(Analysis, analysis_id)
                        if item is None or item.lease_token != token:
                            raise InvalidVideo("Video preparation lease lost")
                        item.lease_until = now() + timedelta(seconds=60)
                    if time.monotonic() - began > config.application.conversion_timeout_seconds:
                        raise InvalidVideo("Video preparation deadline exceeded")
            finally:
                if process.returncode is None:
                    process.kill()
                await communication
            if output.stat().st_size > config.application.max_normalized_bytes:
                raise InvalidVideo("Normalized media exceeds maximum size")
            metadata = await asyncio.to_thread(
                inspect, output, config.application.max_duration_seconds
            )
            if (
                metadata["_prepare"] != "none"
                or abs(metadata["duration_s"] - info["duration_s"]) > 0.25
            ):
                raise InvalidVideo("Converted video failed validation")
            digest = await asyncio.to_thread(checksum, output)
            with factory.begin() as db:
                item = db.get(Analysis, analysis_id, with_for_update=True)
                if item is None or item.lease_token != token:
                    return True
                video = db.get(Video, identifier)
                os.replace(output, final)
                video.sha256, video.size_bytes = digest, final.stat().st_size
                for key, value in public_metadata(metadata).items():
                    setattr(video, key, value)
                item.status, item.lease_token, item.lease_until = "queued", None, None
                item.ready_at = now()
                item.next_poll_at = now()
            logger.info(
                "media_preparation_completed",
                extra={
                    "fields": fields
                    | {
                        "elapsed_seconds": round(time.monotonic() - began, 3),
                        "mode": info["_prepare"],
                    }
                },
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.exception(
                "media_preparation_failed",
                extra={"fields": fields | {"error_type": type(error).__name__}},
            )
            with factory.begin() as db:
                item = db.get(Analysis, analysis_id)
                if item and item.lease_token == token:
                    item.status = "failed"
                    item.error = {
                        "code": "media_preparation_failed",
                        "message": "视频准备未完成，请重试或选择兼容视频。",
                        "request_id": token,
                    }
                    item.lease_until, item.lease_token = None, None
        return True
    finally:
        if output:
            output.unlink(missing_ok=True)
        if locked:
            try:
                reservation.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK})
                reservation.commit()
            except Exception:
                reservation.invalidate()
        reservation.close()


async def run_preparer(factory, settings, config):
    while True:
        try:
            worked = await prepare_once(factory, settings, config)
            await asyncio.sleep(0.1 if worked else config.application.poll_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("media_preparer_error")
            await asyncio.sleep(5)
