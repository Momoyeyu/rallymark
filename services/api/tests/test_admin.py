import pytest
from fastapi.testclient import TestClient
from rallymark_api.app import create_app
from rallymark_api.config import Settings
from rallymark_api.db import Analysis, Video, connect
from rallymark_api.migrate import migrate


@pytest.fixture
def context(tmp_path):
    s = Settings(
        database_url=f"sqlite:///{tmp_path}/db",
        internal_token="test-admin-token",
        media_root=tmp_path / "media",
        dispatcher_enabled=False,
    )
    engine, factory = connect(s.database_url)
    migrate(engine)
    app = create_app(
        s,
        engine,
        lambda *_: dict(duration_s=12, width=1920, height=1080),
        capacity_check=lambda: {"state": "ready", "queued": 0},
    )
    with TestClient(app) as client:
        yield client, app, factory, s


def login(c, username="admin", password="admin"):
    return c.post("/api/v1/admin/login", json=dict(username=username, password=password))


def test_admin_auth_is_separate_and_sessions_are_revoked(context):
    c, app, _, _ = context
    assert c.get("/api/v1/admin/storage").status_code == 401
    assert login(c, password="bad").status_code == 401
    assert login(c).status_code == 200
    assert c.get("/api/v1/admin/storage").status_code == 200
    # An admin cookie does not establish anonymous ownership.
    assert c.get("/api/v1/videos").status_code == 401
    assert c.post("/api/v1/admin/logout").status_code == 204
    assert c.get("/api/v1/admin/me").status_code == 401
    with TestClient(app) as other:
        assert other.get("/api/v1/admin/users").status_code == 401


def test_video_trash_restore_and_active_protection(context):
    c, _, f, _ = context
    c.post("/api/v1/session")
    v = c.post("/api/v1/videos", files={"file": ("match.mp4", b"video")}).json()
    assert login(c).status_code == 200
    url = "/api/v1/admin/videos/" + v["id"]
    assert c.post(url + "/trash").status_code == 409
    with f.begin() as db:
        db.get(Analysis, v["latest_analysis"]["id"]).status = "succeeded"
    assert c.get(url + "/media", headers={"Range": "bytes=0-1"}).status_code == 206
    assert c.post(url + "/trash").status_code == 204
    assert c.get("/api/v1/videos/" + v["id"]).status_code == 404
    assert c.get("/api/v1/admin/videos?trashed=true").json()["total"] == 1
    assert c.post(url + "/restore").status_code == 204
    assert c.get("/api/v1/videos/" + v["id"]).status_code == 200
    with f() as db:
        assert db.get(Video, v["id"]).user_id is None


def test_roles_last_admin_and_password_reset(context):
    c, app, _, _ = context
    login(c)
    me = c.get("/api/v1/admin/me").json()
    assert c.patch("/api/v1/admin/users/" + me["id"], json={"active": False}).status_code == 409
    made = c.post(
        "/api/v1/admin/users",
        json={"username": "reviewer", "password": "reviewer123", "role": "member"},
    )
    assert made.status_code == 201
    user = made.json()
    assert "password" not in user and "password_hash" not in user
    with TestClient(app) as member:
        assert login(member, "reviewer", "reviewer123").status_code == 200
        assert member.get("/api/v1/admin/storage").status_code == 403
        assert (
            c.patch(
                "/api/v1/admin/users/" + user["id"], json={"password": "changed123"}
            ).status_code
            == 200
        )
        assert member.get("/api/v1/admin/me").status_code == 401
    assert (
        c.post(
            "/api/v1/admin/login",
            json={"username": "admin", "password": "admin"},
            headers={"Origin": "http://evil.invalid"},
        ).status_code
        == 403
    )


def test_login_throttles_and_migration_does_not_reset_password(context):
    c, _, f, _ = context
    for _ in range(5):
        assert login(c, password="wrong").status_code == 401
    assert login(c).status_code == 429
    migrate(f.kw["bind"])
    assert login(c).status_code == 429


def test_retry_of_trashed_upload_key_returns_conflict_without_leaking_video(context):
    c, _, factory, _ = context
    c.post("/api/v1/session")
    args = {
        "files": {"file": ("match.mp4", b"video")},
        "headers": {"Idempotency-Key": "stable-upload-key"},
    }
    video = c.post("/api/v1/videos", **args).json()
    with factory.begin() as db:
        db.get(Analysis, video["latest_analysis"]["id"]).status = "succeeded"
    login(c)
    assert c.post("/api/v1/admin/videos/" + video["id"] + "/trash").status_code == 204
    response = c.post("/api/v1/videos", **args)
    assert response.status_code == 409
    assert video["id"] not in response.text
    assert c.get("/api/v1/admin/videos?trashed=true").json()["total"] == 1
