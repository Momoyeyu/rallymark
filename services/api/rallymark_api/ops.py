import argparse
import json
import time
import shutil
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, exists, func, or_, select

from .config import Settings
from .db import ACTIVE, Analysis, GuestSession, Maintenance, Video, connect, now


def cleanup(factory, root, apply=False, video_id=None):
    removed = []
    with factory.begin() as db:
        query = select(Video).with_for_update(skip_locked=True)
        query = (
            query.where(Video.id == video_id)
            if video_id
            else query.where(
                or_(
                    Video.expires_at < now(),
                    Video.deleting.is_(True),
                    Video.user_id.is_(None)
                    & exists().where(
                        GuestSession.token_hash == Video.owner, GuestSession.expires_at <= now()
                    ),
                )
            )
        )
        for video in db.scalars(query):
            active = db.scalar(
                select(Analysis.id)
                .where(Analysis.video_id == video.id, Analysis.status.in_(ACTIVE))
                .limit(1)
            )
            if active:
                continue
            removed.append(video.id)
            if apply:
                video.deleting = True
    if apply:
        for identifier in removed:
            (root / (identifier + ".mp4")).unlink(missing_ok=True)
            (root / (identifier + ".source")).unlink(missing_ok=True)
            (root / (identifier + ".prepare.mp4")).unlink(missing_ok=True)
            shutil.rmtree(root / "thumbnails" / identifier, ignore_errors=True)
            with factory.begin() as db:
                db.execute(delete(Analysis).where(Analysis.video_id == identifier))
                db.execute(delete(Video).where(Video.id == identifier, Video.deleting.is_(True)))
        if not video_id:
            with factory.begin() as db:
                db.execute(
                    delete(GuestSession).where(
                        GuestSession.expires_at <= now(),
                        ~exists().where(
                            Video.owner == GuestSession.token_hash, Video.user_id.is_(None)
                        ),
                    )
                )
        for path in (root / "temporary").glob("*.upload"):
            if path.stat().st_mtime < time.time() - timedelta(days=1).total_seconds():
                path.unlink(missing_ok=True)
    return {"apply": apply, "video_ids": removed}


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    cleaner = commands.add_parser("cleanup")
    cleaner.add_argument("--apply", action="store_true")
    cleaner.add_argument("--video-id")
    for command in ("drain", "undrain", "status", "config-check"):
        commands.add_parser(command)
    schema = commands.add_parser("export-schema")
    schema.add_argument("--out", type=Path)
    args = parser.parse_args()
    settings = Settings()
    config = settings.load_config()
    if args.command == "config-check":
        print(
            json.dumps(
                {"valid": True, "config_hash": config.digest(), "config": config.model_dump()}
            )
        )
        return
    if args.command == "export-schema":
        from .app import create_app

        result = json.dumps(create_app(settings).openapi(), ensure_ascii=False, indent=2)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(result + "\n")
        else:
            print(result)
        return
    _, factory = connect(settings.database_url)
    if args.command == "cleanup":
        result = cleanup(factory, settings.media_root, args.apply, args.video_id)
    else:
        with factory.begin() as db:
            query = select(Maintenance).where(Maintenance.id == 1)
            if args.command in ("drain", "undrain"):
                query = query.with_for_update()
            item = db.scalar(query)
            if item is None:
                raise SystemExit("Run migrations first")
            if args.command in ("drain", "undrain"):
                item.draining = args.command == "drain"
            counts = dict(
                db.execute(select(Analysis.status, func.count()).group_by(Analysis.status)).all()
            )
            result = {
                "draining": item.draining,
                "running": db.scalar(
                    select(func.count())
                    .select_from(Analysis)
                    .where(
                        Analysis.status.in_(ACTIVE),
                    )
                ),
                "queued": counts.get("queued", 0),
                "statuses": counts,
            }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
