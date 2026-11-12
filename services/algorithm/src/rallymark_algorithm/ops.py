"""Maintenance commands for the algorithm service."""

import argparse
import json
import shutil
from datetime import timedelta

from sqlalchemy import select

from .db import database
from .models import Job, utcnow
from .settings import Settings


def cleanup(settings, sessions, apply=False, video_id=None):
    cutoff = utcnow() - timedelta(days=settings.retention_days)
    with sessions.begin() as session:
        query = select(Job).where(Job.status.in_(("succeeded", "failed")))
        query = query.where(Job.video_id == video_id) if video_id else query.where(Job.created_at < cutoff)
        jobs = session.scalars(query.with_for_update(skip_locked=True)).all()
        ids = [job.id for job in jobs]
        if apply:
            root = settings.work_root.resolve()
            for job in jobs:
                directory = root / job.id
                if directory.parent != root or directory.is_symlink():
                    raise ValueError("Unsafe algorithm work directory")
                if directory.exists():
                    shutil.rmtree(directory)
                session.delete(job)
    return {"apply": apply, "jobs": ids, "count": len(ids)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["cleanup"])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--video-id")
    args = parser.parse_args()
    settings = Settings.load()
    _, sessions = database(settings.database_url)
    print(json.dumps(cleanup(settings, sessions, args.apply, args.video_id)))


if __name__ == "__main__":
    main()
