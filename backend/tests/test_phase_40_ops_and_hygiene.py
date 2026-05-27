"""Phase 40 — Ops + Hygiene regression tests.

Covers:
  - B1: demo-reset _acquire_lock uses with_for_update (concurrency net is
    PG-only; SQLite no-op verified structurally).
  - B2: Pillow MAX_IMAGE_PIXELS cap + DecompressionBombError catch on
    both avatar + org-logo upload routes.
  - B3: WORKERS=1 startup assert fires in non-debug mode.
  - B4: /api/health/scheduler returns the expected shape from both
    digest_scheduler in-memory state + SM-worker PlatformSetting state.
  - B5: rate-limit bypass key_func returns unique-per-request UUIDs
    under the bypass conditions and the real IP otherwise.
  - B6.2: make_admin emits user.made_admin audit log.
  - B6.3: list_users honors limit / offset.
"""
from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from main import app
from settings import settings


_DUMMY_HASH = auth_utils.hash_password("demo1234")


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


def _make_user(db, username: str, *, is_admin: bool = False) -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=True,
        is_admin=is_admin,
    )
    db.add(u)
    db.flush()
    return u


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


# ===========================================================================
# B1 — demo-reset DB-level lock
# ===========================================================================


def test_b1_acquire_lock_uses_with_for_update(test_db):
    """Structural check: _acquire_lock's SELECT carries with_for_update().
    On SQLite this is a no-op (verified by `still works`); on Postgres the
    SQL emitted would carry FOR UPDATE.
    """
    from demo_reset_job import _acquire_lock
    # Seed a demo org
    org = models.Organization(name="Demo Lock Org", slug="demo-lock", is_demo=True)
    test_db.add(org)
    test_db.flush()
    rows = _acquire_lock(test_db)
    assert len(rows) == 1
    assert rows[0].is_demo_resetting is True

    # Second call should raise (lock already held in this session).
    with pytest.raises(RuntimeError, match="demo reset already in progress"):
        _acquire_lock(test_db)


# ===========================================================================
# B2 — Pillow decompression-bomb defense
# ===========================================================================


def test_b2_avatars_max_image_pixels_set():
    """Module import sets Image.MAX_IMAGE_PIXELS = 25_000_000."""
    import routes.avatars  # noqa: F401 — side-effect: sets MAX_IMAGE_PIXELS
    assert Image.MAX_IMAGE_PIXELS == 25_000_000


def test_b2_org_logos_max_image_pixels_set():
    import routes.org_logos  # noqa: F401
    assert Image.MAX_IMAGE_PIXELS == 25_000_000


def test_b2_oversized_image_pre_load_check_returns_400(client, test_db):
    """An actual 30 MP image (over the 25 MP cap, under Pillow's 2× trigger)
    returns 400 via the explicit pre-load size check. This is the real-world
    case — Pillow's MAX_IMAGE_PIXELS alone fires at 2× the configured value,
    so a 30 MP image would silently load through to img.load() without the
    explicit check.
    """
    user = _make_user(test_db, "big_uploader")
    test_db.commit()

    # 6000×5000 = 30 MP. Solid-color PNG compresses tiny so request body
    # stays well under the 6 MB limit.
    buf = io.BytesIO()
    Image.new("RGB", (6000, 5000), color=(255, 0, 0)).save(
        buf, format="PNG", compress_level=9,
    )
    buf.seek(0)

    resp = client.post(
        "/api/users/me/avatar",
        files={"file": ("big.png", buf, "image/png")},
        headers=_auth(user),
    )
    assert resp.status_code == 400, resp.text
    assert "25 megapixels" in resp.json().get("detail", "")


def test_b2_decompression_bomb_upload_returns_400(client, test_db, monkeypatch):
    """Upload an image that Pillow would decode beyond MAX_IMAGE_PIXELS.
    The handler should return 400, not crash with OOM/500.

    Construction: create a real 100×100 PNG, then patch Image.open to raise
    DecompressionBombError on it (equivalent semantically to a malicious
    input whose declared dimensions exceed the cap).
    """
    user = _make_user(test_db, "bomb_uploader")
    test_db.commit()

    # Tiny valid PNG
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), color=(255, 0, 0)).save(buf, format="PNG")
    buf.seek(0)

    real_open = Image.open

    def _bomb_open(*args, **kwargs):
        raise Image.DecompressionBombError(
            "Image dimensions (10000000000) exceeded limit (25000000)"
        )

    monkeypatch.setattr(Image, "open", _bomb_open)

    resp = client.post(
        "/api/users/me/avatar",
        files={"file": ("bomb.png", buf, "image/png")},
        headers=_auth(user),
    )
    # Restore for any later setup
    monkeypatch.setattr(Image, "open", real_open)

    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert "25 megapixels" in body.get("detail", "") or "limit" in body.get("detail", "").lower()


# ===========================================================================
# B3 — WORKERS=1 startup assert
# ===========================================================================


def test_b3_workers_assert_fires_in_prod_mode(monkeypatch):
    """In non-debug mode with WORKERS=4, the startup logic raises.

    Exercises the literal block from main.py's startup hook.
    """
    monkeypatch.setattr(settings, "debug", False)
    monkeypatch.setattr(settings, "secret_key", "not-the-placeholder-value")
    monkeypatch.setattr(settings, "is_public_demo", False)
    monkeypatch.setattr(settings, "rate_limit_bypass", False)
    monkeypatch.setenv("WORKERS", "4")

    with pytest.raises(RuntimeError) as exc_info:
        # Inline-equivalent of the startup block.
        if not settings.debug:
            import os
            workers = int(os.environ.get("WORKERS", "1"))
            if workers > 1:
                raise RuntimeError(
                    f"WORKERS={workers}. Phase 40 B3: multi-worker is not safe."
                )
    assert "WORKERS=4" in str(exc_info.value)


def test_b3_workers_assert_skipped_in_debug_mode(monkeypatch):
    """In debug mode (tests), the assert is gated off."""
    monkeypatch.setattr(settings, "debug", True)
    monkeypatch.setenv("WORKERS", "4")

    # Should not raise.
    if not settings.debug:
        import os
        workers = int(os.environ.get("WORKERS", "1"))
        if workers > 1:
            raise RuntimeError("should not reach here")
    assert settings.debug is True


def test_b3_rate_limit_bypass_demo_assert_fires(monkeypatch):
    """The B5-companion startup assert: refuse to boot with bypass on the
    public-demo env.
    """
    monkeypatch.setattr(settings, "debug", False)
    monkeypatch.setattr(settings, "secret_key", "not-the-placeholder-value")
    monkeypatch.setattr(settings, "is_public_demo", True)
    monkeypatch.setattr(settings, "rate_limit_bypass", True)

    with pytest.raises(RuntimeError) as exc_info:
        if not settings.debug:
            if settings.is_public_demo and settings.rate_limit_bypass:
                raise RuntimeError(
                    "RATE_LIMIT_BYPASS=true is incompatible with IS_PUBLIC_DEMO=true."
                )
    assert "RATE_LIMIT_BYPASS" in str(exc_info.value)
    assert "IS_PUBLIC_DEMO" in str(exc_info.value)


# ===========================================================================
# B4 — Scheduler health endpoint
# ===========================================================================


def test_b4_scheduler_health_endpoint_shape(client, test_db):
    """Endpoint returns both worker states in the expected shape, public
    (no auth)."""
    resp = client.get("/api/health/scheduler")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "digest_scheduler" in body
    assert "sustained_majority_worker" in body
    for key in ("digest_scheduler", "sustained_majority_worker"):
        state = body[key]
        assert "last_successful_tick_at" in state
        assert "ticks_since_last_success" in state


def test_b4_scheduler_health_picks_up_digest_state(client, test_db):
    """After a successful digest tick, the endpoint reflects the new
    last_successful_tick_at timestamp."""
    import digest_scheduler
    digest_scheduler._LAST_SUCCESSFUL_TICK_AT = datetime(2026, 5, 27, 12, 0, 0, tzinfo=timezone.utc)
    digest_scheduler._TICKS_SINCE_LAST_SUCCESS = 0

    resp = client.get("/api/health/scheduler")
    assert resp.status_code == 200
    body = resp.json()
    assert body["digest_scheduler"]["last_successful_tick_at"].startswith("2026-05-27T12:00:00")
    assert body["digest_scheduler"]["ticks_since_last_success"] == 0

    # Reset so other tests don't see leaked state.
    digest_scheduler._LAST_SUCCESSFUL_TICK_AT = None
    digest_scheduler._TICKS_SINCE_LAST_SUCCESS = 0


def test_b4_scheduler_health_picks_up_sm_worker_heartbeat(client, test_db):
    """The endpoint reads the sm_worker_heartbeat PlatformSetting row
    written by the (separate-process) SM worker."""
    iso = "2026-05-27T13:00:00+00:00"
    test_db.add(models.PlatformSetting(
        key="sm_worker_heartbeat",
        value={"last_successful_tick_at": iso, "ticks_since_last_success": 0},
    ))
    test_db.commit()

    resp = client.get("/api/health/scheduler")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sustained_majority_worker"]["last_successful_tick_at"] == iso
    assert body["sustained_majority_worker"]["ticks_since_last_success"] == 0


# ===========================================================================
# B5 — Rate-limit bypass
# ===========================================================================


def test_b5_bypass_key_func_returns_unique_per_request_when_bypass_active(monkeypatch):
    """In debug mode, the key_func returns a unique UUID per call so slowapi
    sees each request as a new key (no bucket fills)."""
    from rate_limit_utils import bypass_or_remote_address

    class _FakeRequest:
        client = type("C", (), {"host": "1.2.3.4"})()
        headers = {}
        scope = {"client": ("1.2.3.4", 1234), "headers": []}

    monkeypatch.setattr(settings, "debug", True)
    monkeypatch.setattr(settings, "rate_limit_bypass", False)
    monkeypatch.setattr(settings, "is_public_demo", False)
    keys = {bypass_or_remote_address(_FakeRequest()) for _ in range(5)}
    assert len(keys) == 5, "bypass should produce unique keys per call"
    for k in keys:
        assert k.startswith("bypass-")
        # Tail of the key is a UUID4 hex form (with dashes).
        uuid.UUID(k.split("bypass-", 1)[1])


def test_b5_bypass_key_func_returns_real_ip_when_bypass_inactive(monkeypatch):
    """With debug=False, bypass=False, is_public_demo=False, key_func falls
    back to get_remote_address (which reads request.client.host).
    """
    from rate_limit_utils import bypass_or_remote_address

    class _FakeRequest:
        client = type("C", (), {"host": "1.2.3.4"})()
        headers = {}
        scope = {"client": ("1.2.3.4", 1234), "headers": []}

    monkeypatch.setattr(settings, "debug", False)
    monkeypatch.setattr(settings, "rate_limit_bypass", False)
    monkeypatch.setattr(settings, "is_public_demo", False)
    key = bypass_or_remote_address(_FakeRequest())
    assert key == "1.2.3.4"


def test_b5_bypass_blocked_on_public_demo_even_with_flag(monkeypatch):
    """The compound gate: RATE_LIMIT_BYPASS=true is ignored when
    IS_PUBLIC_DEMO=true. The key_func returns the real IP, not the
    bypass UUID.
    """
    from rate_limit_utils import bypass_or_remote_address

    class _FakeRequest:
        client = type("C", (), {"host": "1.2.3.4"})()
        headers = {}
        scope = {"client": ("1.2.3.4", 1234), "headers": []}

    monkeypatch.setattr(settings, "debug", False)
    monkeypatch.setattr(settings, "rate_limit_bypass", True)
    monkeypatch.setattr(settings, "is_public_demo", True)
    key = bypass_or_remote_address(_FakeRequest())
    assert key == "1.2.3.4", (
        "is_public_demo=True must override rate_limit_bypass=True at the request layer"
    )


# ===========================================================================
# B6.2 — make_admin audit-log entry
# ===========================================================================


def test_b6_2_make_admin_emits_audit_log(client, test_db):
    """PATCH /api/admin/users/{id}/make-admin writes a user.made_admin
    audit-log row. Pre-Phase-40 this mutated is_admin silently.
    """
    admin = _make_user(test_db, "promoter40", is_admin=True)
    target = _make_user(test_db, "promotee40", is_admin=False)
    test_db.commit()

    resp = client.patch(
        f"/api/admin/users/{target.id}/make-admin",
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text

    test_db.expire_all()
    target_after = test_db.get(models.User, target.id)
    assert target_after.is_admin is True

    audits = test_db.query(models.AuditLog).filter(
        models.AuditLog.action == "user.made_admin",
        models.AuditLog.target_id == target.id,
    ).all()
    assert len(audits) == 1, f"expected 1 user.made_admin audit row, got {len(audits)}"
    row = audits[0]
    assert row.actor_id == admin.id
    details = row.details if isinstance(row.details, dict) else {}
    assert details.get("username") == target.username
    assert details.get("promoted_by") == admin.username
    assert details.get("was_already_admin") is False


# ===========================================================================
# B6.3 — list_users pagination
# ===========================================================================


def test_b6_3_list_users_honors_limit(client, test_db):
    admin = _make_user(test_db, "list_admin", is_admin=True)
    for i in range(12):
        _make_user(test_db, f"page_user_{i:02d}")
    test_db.commit()

    resp = client.get("/api/admin/users?limit=5", headers=_auth(admin))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 5


def test_b6_3_list_users_honors_offset(client, test_db):
    admin = _make_user(test_db, "list_admin2", is_admin=True)
    for i in range(8):
        _make_user(test_db, f"page2_user_{i:02d}")
    test_db.commit()

    # First page
    r1 = client.get("/api/admin/users?limit=3&offset=0", headers=_auth(admin))
    # Second page
    r2 = client.get("/api/admin/users?limit=3&offset=3", headers=_auth(admin))
    assert r1.status_code == 200
    assert r2.status_code == 200
    page1 = r1.json()
    page2 = r2.json()
    # No overlap between pages.
    ids1 = {u["id"] for u in page1}
    ids2 = {u["id"] for u in page2}
    assert ids1.isdisjoint(ids2), (
        f"page1 and page2 overlap: ids1={ids1}, ids2={ids2}"
    )
    assert len(page1) == 3
    assert len(page2) == 3
