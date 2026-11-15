import asyncio
import logging
import re
import time
from datetime import UTC, timedelta
from uuid import uuid4

import httpx
from sqlalchemy import or_, select

from .db import ALGORITHM_ACTIVE, Analysis, Video, now

logger = logging.getLogger("rallymark")


def validate_result(result, duration):
    rallies = result.get("rallies", [])
    end = 0.0
    normalized = []
    for row in rallies:
        start, stop = float(row["start_s"]), float(row["end_s"])
        if not 0 <= end <= start < stop <= duration + 0.05:
            raise ValueError("Algorithm returned invalid or overlapping intervals")
        score = row.get("score")
        status = row.get("score_status", "unknown")
        if score is not None and (
            not isinstance(score, str) or not re.fullmatch(r"\d{1,3}:\d{1,3}", score)
        ):
            raise ValueError("Invalid rally score")
        if status not in ("observed", "inferred", "unknown"):
            raise ValueError("Invalid score status")
        normalized.append(dict(row, score=score, score_status=status))
        end = stop
    return normalized


async def dispatch_once(factory, settings, config, client):
    token = str(uuid4())
    timestamp = now()
    with factory.begin() as db:
        query = select(Analysis).where(
            Analysis.status.in_(ALGORITHM_ACTIVE),
            Analysis.next_poll_at <= timestamp,
            or_(Analysis.lease_until.is_(None), Analysis.lease_until < timestamp),
        )
        item = db.scalar(
            query.order_by(Analysis.next_poll_at).with_for_update(skip_locked=True).limit(1)
        )
        if item is None:
            return False
        item.lease_token = token
        item.lease_until = timestamp + timedelta(seconds=60)
        job_id, video_id, submitted = item.id, item.video_id, item.submitted
        video = db.get(Video, video_id)
        payload = {
            "id": job_id,
            "video_id": video_id,
            "sha256": video.sha256,
            "config": item.config,
            "config_hash": item.config_hash,
            "algorithm_version": item.algorithm_version,
        }
        duration = video.duration_s
        created_at = (item.ready_at or item.created_at).replace(tzinfo=UTC)
        timeout = item.config.get("timeout_seconds", 2700)
    headers = {"Authorization": "Bearer " + settings.internal_token.get_secret_value()}
    try:
        if (now() - created_at).total_seconds() > timeout:
            raise ValueError("Analysis deadline exceeded")
        url = settings.algorithm_url.rstrip("/") + "/internal/v1/jobs"
        response = (
            await client.get(f"{url}/{job_id}", headers=headers)
            if submitted
            else await client.post(url, json=payload, headers=headers)
        )
        if submitted and response.status_code == 404:
            response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        status = response.json()
        if status["id"] != job_id or status["status"] not in (
            *ALGORITHM_ACTIVE,
            "succeeded",
            "failed",
        ):
            raise ValueError("Invalid algorithm status")
        result = status.get("result") or {}
        rallies = validate_result(result, duration) if status["status"] == "succeeded" else []
        with factory.begin() as db:
            item = db.get(Analysis, job_id)
            if item is None or item.lease_token != token:
                return True
            changed = item.status != status["status"]
            item.status = status["status"]
            item.submitted = True
            item.progress = status.get("progress")
            item.rallies = rallies
            item.warnings = result.get("warnings", [])
            internal_error = status.get("error")
            if internal_error:
                logger.warning(
                    "analysis_failed",
                    extra={
                        "fields": {
                            "analysis_id": job_id,
                            "error_code": internal_error.get("code"),
                            "request_id": token,
                        }
                    },
                )
            item.error = (
                {
                    "code": "analysis_failed",
                    "message": "分析未完成，请稍后重试。",
                    "request_id": token,
                }
                if status["status"] == "failed"
                else None
            )
            item.lease_until = None
            item.lease_token = None
            item.next_poll_at = now() + timedelta(seconds=config.application.poll_seconds)
            if changed:
                logger.info(
                    "analysis_stage",
                    extra={
                        "fields": {
                            "analysis_id": job_id,
                            "video_id": video_id,
                            "stage": item.status,
                        }
                    },
                )
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        logger.warning(
            "algorithm_poll_failed",
            extra={
                "fields": {
                    "analysis_id": job_id,
                    "error_type": type(error).__name__,
                    "request_id": token,
                }
            },
        )
        with factory.begin() as db:
            item = db.get(Analysis, job_id)
            if item and item.lease_token == token:
                item.lease_until = None
                item.lease_token = None
                item.next_poll_at = now() + timedelta(seconds=5)
                permanent = not isinstance(error, httpx.HTTPError) or (
                    isinstance(error, httpx.HTTPStatusError)
                    and error.response.status_code in (400, 401, 403, 409, 422)
                )
                if permanent:
                    item.status = "failed"
                    item.error = {
                        "code": "invalid_algorithm_response",
                        "message": "分析未完成，请稍后重试。",
                        "request_id": token,
                    }
    return True


async def run_dispatcher(factory, settings, config):
    async with httpx.AsyncClient(timeout=20) as client:
        last_cleanup = 0.0
        while True:
            try:
                if time.monotonic() - last_cleanup >= 3600:
                    from .ops import cleanup

                    result = await asyncio.to_thread(cleanup, factory, settings.media_root, True)
                    logger.info(
                        "retention_cleanup",
                        extra={"fields": {"removed_count": len(result["video_ids"])}},
                    )
                    last_cleanup = time.monotonic()
                worked = await dispatch_once(factory, settings, config, client)
                await asyncio.sleep(0.1 if worked else config.application.poll_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("dispatcher_error")
                await asyncio.sleep(5)
