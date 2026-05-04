"""Phase 12.7 Cluster B — org branding endpoint tests.

Covers:

  B1 (POST /api/orgs/{slug}/logo):
    - PNG happy path → 200, both bounding-box files written, settings
      branding.logo_url updated, audit emitted.
    - JPEG happy path → 200, both files written.
    - WEBP happy path → 200, both files written.
    - Replace flow: upload PNG, then upload JPEG → old PNG files removed,
      new JPEG files in place, branding.logo_url ext changed.
    - Invalid content type (text/plain) → 415.
    - Oversized body (> 6 MB) → 413.
    - Empty body → 400.
    - 403: caller is a member without org.edit_branding.
    - 404: unknown org slug.
    - 403: caller is not a member at all (has_permission returns False).

  B1 (DELETE /api/orgs/{slug}/logo):
    - 204 + files removed + branding.logo_url null + audit emitted.
    - 204 idempotent re-call (no audit on second call).
    - 403 without org.edit_branding.

  B2 (PATCH /api/orgs/{slug}/branding):
    - Happy path: both colors + auto_derived → 200, settings persisted,
      audit fires with diff.
    - Partial update: only primary_color → accent_color unchanged.
    - Clear: explicit null → previous value cleared.
    - Invalid hex → 400 (Pydantic 422 surfaces as 422 by default but
      we accept either; spec says "reject malformed").
    - 403 without org.edit_branding.
    - No-op PATCH (same values): no audit emitted.

  B4 (response shape):
    - GET /api/orgs/{slug} on a fresh org returns branding object with
      all-null fields.
    - GET /api/orgs/{slug} after a logo + color set returns populated
      branding object.

The LOGOS_BASE_DIR module constant is monkeypatched to a tmp_path so
tests never write into the real ``backend/uploads/`` (or, post-12.7,
the Railway Volume) tree.
"""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from main import app
from role_seed import seed_default_roles_for_org
from routes import avatars as avatars_module
from tests.conftest import make_org_membership


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
def client(test_db: Session):
    def _get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def tmp_logos_dir(tmp_path, monkeypatch):
    """Redirect LOGOS_BASE_DIR to a tmp_path for the duration of one test.

    The org_logos module reads through ``avatars_module.LOGOS_BASE_DIR``
    on every request (via the helper functions in routes/org_logos.py),
    so a single monkeypatch on the source module flows through.
    """
    logos_root = tmp_path / "logos"
    logos_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(avatars_module, "LOGOS_BASE_DIR", logos_root)
    return logos_root


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


def _make_org(db: Session, slug: str, *, settings: dict | None = None) -> models.Organization:
    o = models.Organization(
        name=slug.title(),
        slug=slug,
        description="",
        join_policy="open",
        settings=settings if settings is not None else {},
    )
    db.add(o)
    db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _make_image_bytes(fmt: str, size: tuple[int, int] = (800, 320), color="red") -> bytes:
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def _audit_events(db: Session, action: str) -> list[models.AuditLog]:
    return (
        db.query(models.AuditLog)
        .filter(models.AuditLog.action == action)
        .all()
    )


# ===========================================================================
# B1 — POST /logo happy paths (PNG, JPEG, WEBP)
# ===========================================================================

def test_upload_png_logo_writes_both_sizes_and_updates_settings(
    client, test_db, tmp_logos_dir,
):
    """PNG happy path: 200, both bounding-box files written, branding
    logo_url persisted, audit emitted, response payload shaped correctly."""
    user = _make_user(test_db, "steward_png")
    org = _make_org(test_db, "png-org")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    payload = _make_image_bytes("PNG", size=(800, 320))
    resp = client.post(
        f"/api/orgs/{org.slug}/logo",
        files={"file": ("logo.png", payload, "image/png")},
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["logo_url"] == f"/uploads/logos/{org.id}/large.png"
    assert body["logo_url_small"] == f"/uploads/logos/{org.id}/small.png"
    assert body["ext"] == "png"
    assert sorted(body["sizes"]) == ["large", "small"]

    # Files exist on disk and fit within their bounding boxes.
    p_large = tmp_logos_dir / org.id / "large.png"
    p_small = tmp_logos_dir / org.id / "small.png"
    assert p_large.exists()
    assert p_small.exists()
    with Image.open(p_large) as im:
        assert im.format == "PNG"
        assert im.size[0] <= 400 and im.size[1] <= 160
    with Image.open(p_small) as im:
        assert im.format == "PNG"
        assert im.size[0] <= 200 and im.size[1] <= 80

    # Settings updated.
    test_db.refresh(org)
    assert org.settings["branding"]["logo_url"] == f"/uploads/logos/{org.id}/large.png"

    # Audit event written.
    events = _audit_events(test_db, "org.logo_uploaded")
    assert len(events) == 1
    assert events[0].actor_id == user.id
    assert events[0].target_id == org.id
    assert events[0].details["content_type"] == "image/png"
    assert events[0].details["ext"] == "png"


def test_upload_jpeg_logo_writes_both_sizes(client, test_db, tmp_logos_dir):
    """JPEG happy path: files written as .jpg, format preserved."""
    user = _make_user(test_db, "steward_jpeg")
    org = _make_org(test_db, "jpeg-org")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    payload = _make_image_bytes("JPEG", size=(600, 240))
    resp = client.post(
        f"/api/orgs/{org.slug}/logo",
        files={"file": ("logo.jpg", payload, "image/jpeg")},
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text

    p_large = tmp_logos_dir / org.id / "large.jpg"
    p_small = tmp_logos_dir / org.id / "small.jpg"
    assert p_large.exists()
    assert p_small.exists()
    with Image.open(p_large) as im:
        assert im.format == "JPEG"
    with Image.open(p_small) as im:
        assert im.format == "JPEG"

    test_db.refresh(org)
    assert org.settings["branding"]["logo_url"] == f"/uploads/logos/{org.id}/large.jpg"


def test_upload_webp_logo_writes_both_sizes(client, test_db, tmp_logos_dir):
    """WEBP happy path: files written as .webp, format preserved."""
    user = _make_user(test_db, "steward_webp")
    org = _make_org(test_db, "webp-org")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    payload = _make_image_bytes("WEBP", size=(500, 200))
    resp = client.post(
        f"/api/orgs/{org.slug}/logo",
        files={"file": ("logo.webp", payload, "image/webp")},
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text

    p_large = tmp_logos_dir / org.id / "large.webp"
    p_small = tmp_logos_dir / org.id / "small.webp"
    assert p_large.exists()
    assert p_small.exists()
    with Image.open(p_large) as im:
        assert im.format == "WEBP"


def test_upload_logo_proportional_resize_preserves_aspect(
    client, test_db, tmp_logos_dir,
):
    """A 1000x200 input (5:1) shrinks proportionally — width capped first
    so the small file is e.g. 200x40, large 400x80, NOT stretched to fill
    the bounding box."""
    user = _make_user(test_db, "steward_aspect")
    org = _make_org(test_db, "aspect-org")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    payload = _make_image_bytes("PNG", size=(1000, 200))
    resp = client.post(
        f"/api/orgs/{org.slug}/logo",
        files={"file": ("wide.png", payload, "image/png")},
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text

    p_large = tmp_logos_dir / org.id / "large.png"
    with Image.open(p_large) as im:
        # 1000x200 fit into 400x160 → width-capped at 400, height = 80.
        assert im.size == (400, 80)


# ===========================================================================
# B1 — Replace flow
# ===========================================================================

def test_upload_logo_replace_removes_old_files_and_updates_settings(
    client, test_db, tmp_logos_dir,
):
    """Upload PNG, then upload JPEG → old PNG files removed, new JPEG
    files in place, branding.logo_url ext switched."""
    user = _make_user(test_db, "steward_replace")
    org = _make_org(test_db, "replace-org")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    # First upload: PNG
    png_payload = _make_image_bytes("PNG", size=(800, 320), color="red")
    r1 = client.post(
        f"/api/orgs/{org.slug}/logo",
        files={"file": ("a.png", png_payload, "image/png")},
        headers=_auth(user),
    )
    assert r1.status_code == 200

    p_large_png = tmp_logos_dir / org.id / "large.png"
    p_small_png = tmp_logos_dir / org.id / "small.png"
    assert p_large_png.exists()
    assert p_small_png.exists()

    # Second upload: JPEG (different format)
    jpeg_payload = _make_image_bytes("JPEG", size=(600, 240), color="blue")
    r2 = client.post(
        f"/api/orgs/{org.slug}/logo",
        files={"file": ("b.jpg", jpeg_payload, "image/jpeg")},
        headers=_auth(user),
    )
    assert r2.status_code == 200

    # Old PNG files gone, new JPEG files in place.
    assert not p_large_png.exists()
    assert not p_small_png.exists()
    p_large_jpg = tmp_logos_dir / org.id / "large.jpg"
    p_small_jpg = tmp_logos_dir / org.id / "small.jpg"
    assert p_large_jpg.exists()
    assert p_small_jpg.exists()

    # Settings updated.
    test_db.refresh(org)
    assert org.settings["branding"]["logo_url"] == f"/uploads/logos/{org.id}/large.jpg"

    # Two upload-audit events.
    events = _audit_events(test_db, "org.logo_uploaded")
    assert len(events) == 2


# ===========================================================================
# B1 — Validation failures
# ===========================================================================

def test_upload_logo_invalid_content_type_rejected(client, test_db, tmp_logos_dir):
    """text/plain (or any non-image) is rejected with 415."""
    user = _make_user(test_db, "steward_badmime")
    org = _make_org(test_db, "badmime-org")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/logo",
        files={"file": ("x.txt", b"hello", "text/plain")},
        headers=_auth(user),
    )
    assert resp.status_code == 415
    assert "Unsupported image type" in resp.json()["detail"]
    assert not (tmp_logos_dir / org.id).exists()


def test_upload_logo_oversized_rejected(client, test_db, tmp_logos_dir):
    """File body exceeding 6 MB rejected with 413."""
    user = _make_user(test_db, "steward_oversize")
    org = _make_org(test_db, "oversize-org")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    oversize = b"x" * (6 * 1024 * 1024 + 100 * 1024)  # ~6.1 MB
    resp = client.post(
        f"/api/orgs/{org.slug}/logo",
        files={"file": ("big.png", oversize, "image/png")},
        headers=_auth(user),
    )
    assert resp.status_code == 413
    assert "6 MB" in resp.json()["detail"]


def test_upload_logo_empty_body_rejected(client, test_db, tmp_logos_dir):
    """Zero-byte upload rejected with 400."""
    user = _make_user(test_db, "steward_empty")
    org = _make_org(test_db, "empty-org")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/logo",
        files={"file": ("a.png", b"", "image/png")},
        headers=_auth(user),
    )
    assert resp.status_code == 400


# ===========================================================================
# B1 — Permission gating
# ===========================================================================

def test_upload_logo_member_without_permission_403(client, test_db, tmp_logos_dir):
    """Member role lacks org.edit_branding (default member set is empty)
    → 403."""
    user = _make_user(test_db, "plain_member")
    org = _make_org(test_db, "member-org")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="member")
    test_db.commit()

    payload = _make_image_bytes("PNG")
    resp = client.post(
        f"/api/orgs/{org.slug}/logo",
        files={"file": ("a.png", payload, "image/png")},
        headers=_auth(user),
    )
    assert resp.status_code == 403


def test_upload_logo_non_member_403(client, test_db, tmp_logos_dir):
    """User who has no membership at all on the org → 403 (has_permission
    returns False uniformly)."""
    user = _make_user(test_db, "outsider")
    org = _make_org(test_db, "outsider-org")
    test_db.commit()

    payload = _make_image_bytes("PNG")
    resp = client.post(
        f"/api/orgs/{org.slug}/logo",
        files={"file": ("a.png", payload, "image/png")},
        headers=_auth(user),
    )
    assert resp.status_code == 403


def test_upload_logo_unknown_org_404(client, test_db, tmp_logos_dir):
    """Unknown slug → 404 before the permission check."""
    user = _make_user(test_db, "any_user")
    test_db.commit()

    payload = _make_image_bytes("PNG")
    resp = client.post(
        "/api/orgs/no-such-org/logo",
        files={"file": ("a.png", payload, "image/png")},
        headers=_auth(user),
    )
    assert resp.status_code == 404


def test_upload_logo_admin_role_allowed(client, test_db, tmp_logos_dir):
    """Admin (default org.edit_branding=True) can upload — 200."""
    user = _make_user(test_db, "admin_logo")
    org = _make_org(test_db, "admin-logo-org")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="admin")
    test_db.commit()

    payload = _make_image_bytes("PNG")
    resp = client.post(
        f"/api/orgs/{org.slug}/logo",
        files={"file": ("a.png", payload, "image/png")},
        headers=_auth(user),
    )
    assert resp.status_code == 200


# ===========================================================================
# B1 — DELETE /logo
# ===========================================================================

def test_delete_logo_204_removes_files_and_clears_settings(
    client, test_db, tmp_logos_dir,
):
    """DELETE removes both files, sets branding.logo_url null, audits."""
    user = _make_user(test_db, "steward_del")
    org = _make_org(test_db, "delete-org")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    # Seed a logo first
    payload = _make_image_bytes("PNG")
    r1 = client.post(
        f"/api/orgs/{org.slug}/logo",
        files={"file": ("a.png", payload, "image/png")},
        headers=_auth(user),
    )
    assert r1.status_code == 200

    p_large = tmp_logos_dir / org.id / "large.png"
    p_small = tmp_logos_dir / org.id / "small.png"
    assert p_large.exists()

    # Delete
    rd = client.delete(f"/api/orgs/{org.slug}/logo", headers=_auth(user))
    assert rd.status_code == 204
    assert not p_large.exists()
    assert not p_small.exists()

    test_db.refresh(org)
    assert org.settings["branding"]["logo_url"] is None

    events = _audit_events(test_db, "org.logo_removed")
    assert len(events) == 1


def test_delete_logo_idempotent_no_audit_when_no_logo(
    client, test_db, tmp_logos_dir,
):
    """Calling DELETE on an org with no logo: 204, no audit."""
    user = _make_user(test_db, "steward_noop_del")
    org = _make_org(test_db, "noop-del-org")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    resp = client.delete(f"/api/orgs/{org.slug}/logo", headers=_auth(user))
    assert resp.status_code == 204
    events = _audit_events(test_db, "org.logo_removed")
    assert len(events) == 0


def test_delete_logo_member_403(client, test_db, tmp_logos_dir):
    """Member without org.edit_branding → 403 on DELETE."""
    user = _make_user(test_db, "del_member")
    org = _make_org(test_db, "del-member-org")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="member")
    test_db.commit()

    resp = client.delete(f"/api/orgs/{org.slug}/logo", headers=_auth(user))
    assert resp.status_code == 403


# ===========================================================================
# B2 — PATCH /branding (colors)
# ===========================================================================

def test_patch_branding_happy_persists_colors_and_audits(client, test_db):
    """Steward sets primary + accent + auto_derived → 200, settings
    persisted, audit fires with diff."""
    user = _make_user(test_db, "steward_colors")
    org = _make_org(test_db, "colors-org")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/{org.slug}/branding",
        json={
            "primary_color": "#3F2E5C",
            "accent_color": "#5C4778",
            "accent_auto_derived": True,
        },
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["branding"]["primary_color"] == "#3F2E5C"
    assert body["branding"]["accent_color"] == "#5C4778"
    assert body["branding"]["accent_auto_derived"] is True

    test_db.refresh(org)
    branding = org.settings["branding"]
    assert branding["primary_color"] == "#3F2E5C"
    assert branding["accent_color"] == "#5C4778"
    assert branding["accent_auto_derived"] is True

    events = _audit_events(test_db, "org.branding_updated")
    assert len(events) == 1
    diff = events[0].details["changes"]
    assert diff["primary_color"]["new"] == "#3F2E5C"
    assert diff["primary_color"]["old"] is None


def test_patch_branding_partial_update_leaves_other_keys(client, test_db):
    """Set primary first, then PATCH with only accent → primary unchanged."""
    user = _make_user(test_db, "steward_partial")
    org = _make_org(
        test_db, "partial-org",
        settings={
            "branding": {
                "primary_color": "#111111",
                "accent_color": "#222222",
                "accent_auto_derived": True,
            }
        },
    )
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/{org.slug}/branding",
        json={"accent_color": "#999999"},
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text

    test_db.refresh(org)
    branding = org.settings["branding"]
    assert branding["primary_color"] == "#111111"  # unchanged
    assert branding["accent_color"] == "#999999"  # changed
    assert branding["accent_auto_derived"] is True  # unchanged


def test_patch_branding_clear_with_null(client, test_db):
    """PATCH with primary_color: null clears the value (frontend will use
    platform default)."""
    user = _make_user(test_db, "steward_clear")
    org = _make_org(
        test_db, "clear-org",
        settings={"branding": {"primary_color": "#abcdef", "accent_color": "#123456"}},
    )
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/{org.slug}/branding",
        json={"primary_color": None},
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text

    test_db.refresh(org)
    assert org.settings["branding"]["primary_color"] is None
    # accent untouched
    assert org.settings["branding"]["accent_color"] == "#123456"


def test_patch_branding_invalid_hex_rejected(client, test_db):
    """Malformed hex returns 4xx (Pydantic validation; 422 by default —
    we accept either 400 or 422 per spec wording 'reject malformed')."""
    user = _make_user(test_db, "steward_badhex")
    org = _make_org(test_db, "badhex-org")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/{org.slug}/branding",
        json={"primary_color": "not-a-hex"},
        headers=_auth(user),
    )
    assert resp.status_code in (400, 422)


def test_patch_branding_short_hex_accepted(client, test_db):
    """The validator accepts both #RGB and #RRGGBB form."""
    user = _make_user(test_db, "steward_shorthex")
    org = _make_org(test_db, "shorthex-org")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/{org.slug}/branding",
        json={"primary_color": "#abc"},
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["branding"]["primary_color"] == "#abc"


def test_patch_branding_member_403(client, test_db):
    """Member without org.edit_branding → 403."""
    user = _make_user(test_db, "patch_member")
    org = _make_org(test_db, "patch-member-org")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="member")
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/{org.slug}/branding",
        json={"primary_color": "#abcdef"},
        headers=_auth(user),
    )
    assert resp.status_code == 403


def test_patch_branding_no_op_emits_no_audit(client, test_db):
    """PATCH with values matching existing → no audit event."""
    user = _make_user(test_db, "noop_patch")
    org = _make_org(
        test_db, "noop-patch-org",
        settings={"branding": {"primary_color": "#abcdef"}},
    )
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/{org.slug}/branding",
        json={"primary_color": "#abcdef"},
        headers=_auth(user),
    )
    assert resp.status_code == 200
    events = _audit_events(test_db, "org.branding_updated")
    assert len(events) == 0


def test_patch_branding_unknown_org_404(client, test_db):
    user = _make_user(test_db, "any")
    test_db.commit()

    resp = client.patch(
        "/api/orgs/no-such/branding",
        json={"primary_color": "#abcdef"},
        headers=_auth(user),
    )
    assert resp.status_code == 404


# ===========================================================================
# B4 — Response shape on /api/orgs/{slug}
# ===========================================================================

def test_get_org_branding_field_present_with_all_nulls_when_unconfigured(
    client, test_db,
):
    """Fresh org with no branding → branding object is present but all
    fields are null (accent_auto_derived defaults to False)."""
    user = _make_user(test_db, "fresh_org_user")
    org = _make_org(test_db, "fresh-org")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    resp = client.get(f"/api/orgs/{org.slug}", headers=_auth(user))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "branding" in body
    assert body["branding"] == {
        "logo_url": None,
        "primary_color": None,
        "accent_color": None,
        "accent_auto_derived": False,
    }


def test_get_org_branding_populated_after_logo_and_color_set(
    client, test_db, tmp_logos_dir,
):
    """After uploading a logo + setting colors, GET /orgs returns the
    populated branding object."""
    user = _make_user(test_db, "configured_user")
    org = _make_org(test_db, "configured-org")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    # Upload a logo
    payload = _make_image_bytes("PNG")
    r1 = client.post(
        f"/api/orgs/{org.slug}/logo",
        files={"file": ("a.png", payload, "image/png")},
        headers=_auth(user),
    )
    assert r1.status_code == 200

    # Set colors
    r2 = client.patch(
        f"/api/orgs/{org.slug}/branding",
        json={
            "primary_color": "#3F2E5C",
            "accent_color": "#5C4778",
            "accent_auto_derived": True,
        },
        headers=_auth(user),
    )
    assert r2.status_code == 200

    # GET
    r3 = client.get(f"/api/orgs/{org.slug}", headers=_auth(user))
    assert r3.status_code == 200
    branding = r3.json()["branding"]
    assert branding["logo_url"] == f"/uploads/logos/{org.id}/large.png"
    assert branding["primary_color"] == "#3F2E5C"
    assert branding["accent_color"] == "#5C4778"
    assert branding["accent_auto_derived"] is True


def test_org_list_includes_branding_field(client, test_db):
    """The list endpoint (GET /api/orgs) also includes the branding object
    on each org — frontend OrgSelector reads from this."""
    user = _make_user(test_db, "lister")
    o1 = _make_org(test_db, "list-a")
    o2 = _make_org(
        test_db, "list-b",
        settings={"branding": {"primary_color": "#aabbcc"}},
    )
    make_org_membership(test_db, org_id=o1.id, user_id=user.id, role="steward")
    make_org_membership(test_db, org_id=o2.id, user_id=user.id, role="steward")
    test_db.commit()

    resp = client.get("/api/orgs", headers=_auth(user))
    assert resp.status_code == 200
    body = resp.json()
    by_slug = {o["slug"]: o for o in body}
    assert "branding" in by_slug["list-a"]
    assert by_slug["list-a"]["branding"]["primary_color"] is None
    assert by_slug["list-b"]["branding"]["primary_color"] == "#aabbcc"
