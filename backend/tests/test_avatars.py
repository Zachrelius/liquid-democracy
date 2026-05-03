"""Phase 9.8 W A1 — avatar upload/delete endpoint tests.

Covers:
  - Valid JPEG upload -> 200, both URLs returned, both files exist on disk
    with correct dimensions.
  - Valid PNG upload -> resized + saved as JPEG correctly.
  - Invalid content-type -> 415.
  - Oversized file (>2 MB) -> 413.
  - Replacing an existing avatar -> old files removed, new files written.
  - DELETE -> 204, files gone, ``avatar_url`` nulled.
  - Authorization: another user's avatar isn't touched when current user
    uploads (endpoint is hard-coded to current_user; no path parameter).

The PNG/JPEG fixtures are generated in-memory via Pillow so we don't carry
binary files in the repo. The AVATARS_BASE_DIR module constant is monkey-
patched to a tmp_path so the test never writes into the real
``backend/uploads/`` tree.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from main import app
from routes import avatars as avatars_module


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def test_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def client(test_db):
    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def tmp_avatars_dir(tmp_path, monkeypatch):
    """Redirect AVATARS_BASE_DIR to a tmp_path for the duration of one test.

    Tests can read files back from `tmp_path / user_id / 128.jpg` etc.
    without touching the real backend/uploads/ tree.
    """
    avatars_root = tmp_path / "avatars"
    avatars_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(avatars_module, "AVATARS_BASE_DIR", avatars_root)
    return avatars_root


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(db: Session, username: str) -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=True,
    )
    db.add(u)
    db.flush()
    return u


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _make_image_bytes(fmt: str, size: tuple[int, int] = (512, 512), color="red") -> bytes:
    """Generate an in-memory image of the given format."""
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_upload_jpeg_returns_urls_and_writes_two_files(client, test_db, tmp_avatars_dir):
    """Valid JPEG -> 200, both URLs in response, both files on disk with
    the configured dimensions, avatar_url persisted on the User."""
    user = _make_user(test_db, "alice")
    test_db.commit()

    payload = _make_image_bytes("JPEG")
    resp = client.post(
        "/api/users/me/avatar",
        files={"file": ("a.jpg", payload, "image/jpeg")},
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["avatar_url"] == f"/uploads/avatars/{user.id}/128.jpg"
    assert body["avatar_url_small"] == f"/uploads/avatars/{user.id}/48.jpg"

    # Files exist on disk at the right dimensions
    p128 = tmp_avatars_dir / user.id / "128.jpg"
    p48 = tmp_avatars_dir / user.id / "48.jpg"
    assert p128.exists()
    assert p48.exists()
    with Image.open(p128) as img:
        assert img.size == (128, 128)
        assert img.format == "JPEG"
    with Image.open(p48) as img:
        assert img.size == (48, 48)
        assert img.format == "JPEG"

    # User.avatar_url updated
    test_db.refresh(user)
    assert user.avatar_url == f"/uploads/avatars/{user.id}/128.jpg"

    # Audit recorded
    audit = (
        test_db.query(models.AuditLog)
        .filter(models.AuditLog.action == "user.avatar_uploaded")
        .all()
    )
    assert len(audit) == 1
    assert audit[0].actor_id == user.id
    assert audit[0].target_id == user.id
    assert audit[0].details["content_type"] == "image/jpeg"
    assert audit[0].details["input_bytes"] == len(payload)


def test_upload_png_resizes_to_jpeg(client, test_db, tmp_avatars_dir):
    """PNG upload still ends up as JPEG on disk (uniform serving format)."""
    user = _make_user(test_db, "bob")
    test_db.commit()

    payload = _make_image_bytes("PNG")
    resp = client.post(
        "/api/users/me/avatar",
        files={"file": ("a.png", payload, "image/png")},
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text

    p128 = tmp_avatars_dir / user.id / "128.jpg"
    assert p128.exists()
    with Image.open(p128) as img:
        # Saved as JPEG regardless of input format.
        assert img.format == "JPEG"
        assert img.size == (128, 128)


def test_upload_invalid_content_type_returns_415(client, test_db, tmp_avatars_dir):
    """text/plain (or any non-image) is rejected with 415."""
    user = _make_user(test_db, "carol")
    test_db.commit()

    resp = client.post(
        "/api/users/me/avatar",
        files={"file": ("a.txt", b"hello world", "text/plain")},
        headers=_auth(user),
    )
    assert resp.status_code == 415, resp.text
    assert "Unsupported image type" in resp.json()["detail"]
    # Nothing written to disk
    assert not (tmp_avatars_dir / user.id).exists()
    # avatar_url unchanged
    test_db.refresh(user)
    assert user.avatar_url is None


def test_upload_oversized_file_returns_413(client, test_db, tmp_avatars_dir):
    """File body exceeding 2 MB rejected with 413."""
    user = _make_user(test_db, "dave")
    test_db.commit()

    # Build a JPEG-tagged blob just over the 2 MB limit. Content-type is
    # JPEG so we'd otherwise pass that gate; the size check is what fires.
    oversize_bytes = b"x" * (avatars_module.MAX_UPLOAD_BYTES + 100)
    resp = client.post(
        "/api/users/me/avatar",
        files={"file": ("big.jpg", oversize_bytes, "image/jpeg")},
        headers=_auth(user),
    )
    assert resp.status_code == 413, resp.text
    assert not (tmp_avatars_dir / user.id).exists()


def test_replace_existing_avatar_writes_new_files(client, test_db, tmp_avatars_dir):
    """Re-uploading replaces both files and keeps avatar_url pointing
    at the canonical 128 path."""
    user = _make_user(test_db, "erin")
    test_db.commit()

    # First upload
    payload1 = _make_image_bytes("JPEG", color="red")
    r1 = client.post(
        "/api/users/me/avatar",
        files={"file": ("a.jpg", payload1, "image/jpeg")},
        headers=_auth(user),
    )
    assert r1.status_code == 200
    p128 = tmp_avatars_dir / user.id / "128.jpg"
    p48 = tmp_avatars_dir / user.id / "48.jpg"
    assert p128.exists()
    assert p48.exists()
    bytes_before_128 = p128.read_bytes()

    # Stuff a stale extra file that should be cleaned out by the replace
    stale = tmp_avatars_dir / user.id / "stale.jpg"
    stale.write_bytes(b"stale")
    assert stale.exists()

    # Second upload — different color so the encoded bytes differ
    payload2 = _make_image_bytes("JPEG", color="blue")
    r2 = client.post(
        "/api/users/me/avatar",
        files={"file": ("a.jpg", payload2, "image/jpeg")},
        headers=_auth(user),
    )
    assert r2.status_code == 200

    # Stale file is gone (full directory clean), 128 + 48 are fresh
    assert not stale.exists()
    assert p128.exists()
    assert p48.exists()
    bytes_after_128 = p128.read_bytes()
    assert bytes_after_128 != bytes_before_128

    # avatar_url didn't change shape
    test_db.refresh(user)
    assert user.avatar_url == f"/uploads/avatars/{user.id}/128.jpg"


def test_delete_returns_204_and_removes_files(client, test_db, tmp_avatars_dir):
    """DELETE removes both files, nulls avatar_url, audits the action."""
    user = _make_user(test_db, "frank")
    test_db.commit()

    # Seed an upload first.
    payload = _make_image_bytes("JPEG")
    r1 = client.post(
        "/api/users/me/avatar",
        files={"file": ("a.jpg", payload, "image/jpeg")},
        headers=_auth(user),
    )
    assert r1.status_code == 200
    p128 = tmp_avatars_dir / user.id / "128.jpg"
    p48 = tmp_avatars_dir / user.id / "48.jpg"
    assert p128.exists()

    # Delete
    rd = client.delete("/api/users/me/avatar", headers=_auth(user))
    assert rd.status_code == 204
    assert not p128.exists()
    assert not p48.exists()

    test_db.refresh(user)
    assert user.avatar_url is None

    audit = (
        test_db.query(models.AuditLog)
        .filter(models.AuditLog.action == "user.avatar_removed")
        .all()
    )
    assert len(audit) == 1
    assert audit[0].actor_id == user.id


def test_endpoint_only_touches_current_user(client, test_db, tmp_avatars_dir):
    """Authorization: an upload by user A leaves user B's avatar (if any)
    and B's User.avatar_url alone. The endpoint takes no user_id, so the
    only check is that we never write into another user's directory."""
    a = _make_user(test_db, "userone")
    b = _make_user(test_db, "usertwo")
    test_db.commit()

    # Pretend B has an avatar already (simulates a prior upload by B)
    b_dir = tmp_avatars_dir / b.id
    b_dir.mkdir(parents=True, exist_ok=True)
    (b_dir / "128.jpg").write_bytes(b"B-128-bytes")
    (b_dir / "48.jpg").write_bytes(b"B-48-bytes")
    b.avatar_url = f"/uploads/avatars/{b.id}/128.jpg"
    test_db.commit()

    # A uploads
    payload = _make_image_bytes("JPEG")
    resp = client.post(
        "/api/users/me/avatar",
        files={"file": ("a.jpg", payload, "image/jpeg")},
        headers=_auth(a),
    )
    assert resp.status_code == 200
    body = resp.json()
    # Response references A's user_id, NOT B's
    assert a.id in body["avatar_url"]
    assert b.id not in body["avatar_url"]

    # B's files untouched
    assert (b_dir / "128.jpg").read_bytes() == b"B-128-bytes"
    assert (b_dir / "48.jpg").read_bytes() == b"B-48-bytes"

    # B's avatar_url unchanged
    test_db.refresh(b)
    assert b.avatar_url == f"/uploads/avatars/{b.id}/128.jpg"

    # A now also has its own avatar
    test_db.refresh(a)
    assert a.avatar_url == f"/uploads/avatars/{a.id}/128.jpg"
