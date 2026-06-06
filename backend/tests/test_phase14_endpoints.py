"""Phase 14 — public landing page endpoints + join-request endpoints +
intro_text + validation tests.

Covers spec §B6:

  B2 GET /api/orgs/{slug}/public:
    - 404 for invite_only_secret
    - 404 for non-existent slug
    - 200 with shape for invite_only_public, approval_required, open
    - logged-in caller gets identical response shape as logged-out
    - intro_text is surfaced when set; null when not set
    - branding object exposes primary/accent (no accent_auto_derived,
      no logo_url under branding — logo_url is at parent level)

  B3 POST /api/orgs/{slug}/join-request:
    - open + non-member -> 200 active + audit org.joined
    - approval_required + non-member -> 200 pending + audit
      org.join_requested + member.join_request notification fired
    - invite_only_public + non-member -> 403
    - invite_only_secret + non-member -> 404
    - already-active member -> 409
    - already-pending requester -> 409
    - logged-out caller -> 401 (FastAPI auth dependency)

  B3 DELETE /api/orgs/{slug}/join-request:
    - pending request -> 204 + row gone + audit org.join_request_cancelled
    - no pending request -> 404 (idempotent within the 404-on-no-pending
      behavior)
    - invite_only_secret -> 404 (consistent with B2 disambiguation)
    - logged-out caller -> 401

  B4 PATCH /api/orgs/{slug}/branding intro_text:
    - persists to settings.intro_text (top-level, not inside branding)
    - 5000 char cap; longer rejected
    - permission gate: org.edit_branding required
    - empty-string clears (treated as null by get_intro_text helper)
    - intro_text changes appear in audit diff

  B5 schema validation:
    - PATCH /api/orgs/{slug} with join_policy='invite_only' -> 4xx
      (Pydantic 422 with "no longer accepted" in detail).
    - POST /api/orgs creating with 'invite_only' -> 4xx with same hint.
    - All four new values accepted on POST/PATCH.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from main import app
from role_seed import seed_default_roles_for_org
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(db: Session, username: str, *, email_verified: bool = True) -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=email_verified,
    )
    db.add(u)
    db.flush()
    return u


def _make_org(
    db: Session, slug: str, *, join_policy: str = "open",
    settings: dict | None = None, description: str = "",
) -> models.Organization:
    o = models.Organization(
        name=slug.title(),
        slug=slug,
        description=description,
        join_policy=join_policy,
        settings=settings if settings is not None else {},
    )
    db.add(o)
    db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _audit_events(db: Session, action: str) -> list[models.AuditLog]:
    return (
        db.query(models.AuditLog)
        .filter(models.AuditLog.action == action)
        .all()
    )


def _opt_in(db: Session, user: models.User, event_type: str) -> None:
    """Opt the user in to in_app channel for an event_type (Phase 13.3
    opt-in default). Without this, emit_notification skips the in-app
    row insert because absent preference = disabled."""
    db.add(models.NotificationPreference(
        user_id=user.id, event_type=event_type,
        channel="in_app", enabled=True,
    ))
    db.flush()


# ===========================================================================
# B2 — GET /api/orgs/{slug}/public
# ===========================================================================

def test_public_endpoint_404_for_invite_only_secret(client, test_db):
    """invite_only_secret org returns 404 (indistinguishable from
    non-existent)."""
    _make_org(test_db, "secret-org", join_policy="invite_only_secret")
    test_db.commit()

    resp = client.get("/api/orgs/secret-org/public")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Organization not found"


def test_public_endpoint_404_for_nonexistent_slug(client, test_db):
    """Same 404 as the secret-org case."""
    resp = client.get("/api/orgs/no-such-org/public")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Organization not found"


def test_public_endpoint_404_response_indistinguishable_secret_vs_nonexistent(
    client, test_db,
):
    """Both branches must produce the same status + body — secret orgs
    must be indistinguishable from non-existent ones from an unauth
    probe perspective."""
    _make_org(test_db, "secret-only-here", join_policy="invite_only_secret")
    test_db.commit()

    r_secret = client.get("/api/orgs/secret-only-here/public")
    r_unused = client.get("/api/orgs/never-existed/public")
    assert r_secret.status_code == r_unused.status_code == 404
    assert r_secret.json() == r_unused.json()


def test_public_endpoint_200_invite_only_public(client, test_db):
    """invite_only_public org returns 200 with public shape."""
    _make_org(
        test_db, "iop-org", join_policy="invite_only_public",
        description="An invite-only-public org.",
        settings={
            "branding": {
                "logo_url": "/uploads/logos/abc/large.png",
                "primary_color": "#1B3A5C",
                "accent_color": "#2E75B6",
            },
            "intro_text": "## Welcome\n\nWe're invite-only.",
        },
    )
    test_db.commit()

    resp = client.get("/api/orgs/iop-org/public")
    assert resp.status_code == 200
    body = resp.json()
    assert body["slug"] == "iop-org"
    assert body["name"] == "Iop-Org"
    assert body["description"] == "An invite-only-public org."
    assert body["logo_url"] == "/uploads/logos/abc/large.png"
    assert body["branding"]["primary_color"] == "#1B3A5C"
    assert body["branding"]["accent_color"] == "#2E75B6"
    # intro_text rendered as-is.
    assert body["intro_text"] == "## Welcome\n\nWe're invite-only."
    # Phase 57 — the four old four-value vocabulary normalize at the
    # model + schema layer onto the new three-value vocabulary.
    # `invite_only_public` → `invite` (with discoverability='listed').
    assert body["join_policy"] == "invite"
    # accent_auto_derived NOT in public shape.
    assert "accent_auto_derived" not in body["branding"]


def test_public_endpoint_200_approval_required(client, test_db):
    _make_org(
        test_db, "ar-org", join_policy="approval_required",
        description="approval-required",
    )
    test_db.commit()

    resp = client.get("/api/orgs/ar-org/public")
    assert resp.status_code == 200
    body = resp.json()
    # Phase 57 — `approval_required` → `approval`.
    assert body["join_policy"] == "approval"
    assert body["intro_text"] is None
    assert body["logo_url"] is None
    assert body["branding"]["primary_color"] is None


def test_public_endpoint_200_open(client, test_db):
    _make_org(test_db, "open-org", join_policy="open")
    test_db.commit()

    resp = client.get("/api/orgs/open-org/public")
    assert resp.status_code == 200
    body = resp.json()
    assert body["join_policy"] == "open"


def test_public_endpoint_logged_in_response_identical_to_logged_out(
    client, test_db,
):
    """Authenticated caller gets the same shape as an unauthenticated one."""
    user = _make_user(test_db, "loggedin")
    _make_org(test_db, "parity-org", join_policy="open", description="parity test")
    test_db.commit()

    r_anon = client.get("/api/orgs/parity-org/public")
    r_auth = client.get("/api/orgs/parity-org/public", headers=_auth(user))

    assert r_anon.status_code == r_auth.status_code == 200
    assert r_anon.json() == r_auth.json()


def test_public_endpoint_empty_intro_text_returns_null(client, test_db):
    """Empty-string intro_text in settings is exposed as null in the
    response (matches the get_intro_text helper convention)."""
    _make_org(
        test_db, "empty-intro", join_policy="open",
        settings={"intro_text": ""},
    )
    test_db.commit()

    resp = client.get("/api/orgs/empty-intro/public")
    assert resp.status_code == 200
    assert resp.json()["intro_text"] is None


# ===========================================================================
# B3 — POST /api/orgs/{slug}/join-request
# ===========================================================================

def test_join_request_open_creates_active_membership(client, test_db):
    user = _make_user(test_db, "joiner_open")
    org = _make_org(test_db, "open-join", join_policy="open")
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/join-request", headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "active"
    assert body["member_id"]

    # Membership row inserted with status=active.
    m = test_db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == org.id,
        models.OrgMembership.user_id == user.id,
    ).first()
    assert m is not None
    assert m.status == "active"

    # Audit org.joined fired.
    events = _audit_events(test_db, "org.joined")
    assert len(events) == 1
    assert events[0].actor_id == user.id
    assert events[0].target_id == org.id
    assert events[0].details["policy"] == "open"


def test_join_request_approval_required_creates_pending_and_fires_notification(
    client, test_db,
):
    """Side-effect assertion per CLAUDE.md "assert side effects" rule:
    membership row created with pending_approval status AND
    member.join_request notification row inserted for the steward."""
    user = _make_user(test_db, "joiner_ar")
    steward = _make_user(test_db, "steward_ar")
    org = _make_org(test_db, "ar-join", join_policy="approval_required")
    make_org_membership(
        test_db, org_id=org.id, user_id=steward.id, role="steward",
    )
    # Phase 13.3 opt-in default: the steward must explicitly opt into
    # in_app for member.join_request to receive the notification row.
    _opt_in(test_db, steward, "member.join_request")
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/join-request", headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "pending"
    assert body["member_id"]

    m = test_db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == org.id,
        models.OrgMembership.user_id == user.id,
    ).first()
    assert m is not None
    assert m.status == "pending_approval"

    # Audit event.
    events = _audit_events(test_db, "org.join_requested")
    assert len(events) == 1
    assert events[0].actor_id == user.id

    # Notification fan-out to the steward — assert the side effect, not
    # just that the API returned 200. The steward holds member.approve_join
    # by default (preset Steward role); a Notification row should exist.
    notifs = test_db.query(models.Notification).filter(
        models.Notification.user_id == steward.id,
        models.Notification.event_type == "member.join_request",
    ).all()
    assert len(notifs) == 1
    assert notifs[0].org_id == org.id
    assert notifs[0].actor_id == user.id


def test_join_request_invite_only_public_403(client, test_db):
    user = _make_user(test_db, "joiner_iop")
    org = _make_org(test_db, "iop-join", join_policy="invite_only_public")
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/join-request", headers=_auth(user),
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "This organization requires an invitation."

    # No membership row created.
    m = test_db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == org.id,
        models.OrgMembership.user_id == user.id,
    ).first()
    assert m is None


def test_join_request_invite_only_secret_404(client, test_db):
    user = _make_user(test_db, "joiner_ios")
    org = _make_org(test_db, "ios-join", join_policy="invite_only_secret")
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/join-request", headers=_auth(user),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Organization not found"


def test_join_request_nonexistent_org_404(client, test_db):
    user = _make_user(test_db, "joiner_404")
    test_db.commit()

    resp = client.post(
        "/api/orgs/nope/join-request", headers=_auth(user),
    )
    assert resp.status_code == 404


def test_join_request_already_active_member_409(client, test_db):
    user = _make_user(test_db, "active_already")
    org = _make_org(test_db, "active-org", join_policy="open")
    make_org_membership(
        test_db, org_id=org.id, user_id=user.id, role="member", status="active",
    )
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/join-request", headers=_auth(user),
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "You are already a member."


def test_join_request_already_pending_409(client, test_db):
    user = _make_user(test_db, "pending_already")
    org = _make_org(test_db, "pending-org", join_policy="approval_required")
    make_org_membership(
        test_db, org_id=org.id, user_id=user.id, role="member",
        status="pending_approval",
    )
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/join-request", headers=_auth(user),
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Your request is already pending."


def test_join_request_logged_out_401(client, test_db):
    _make_org(test_db, "logged-out-org", join_policy="open")
    test_db.commit()

    resp = client.post("/api/orgs/logged-out-org/join-request")
    assert resp.status_code == 401


# ===========================================================================
# B3 — DELETE /api/orgs/{slug}/join-request
# ===========================================================================

def test_cancel_pending_join_request_204_and_row_gone(client, test_db):
    user = _make_user(test_db, "canceller")
    org = _make_org(test_db, "cancel-org", join_policy="approval_required")
    make_org_membership(
        test_db, org_id=org.id, user_id=user.id, role="member",
        status="pending_approval",
    )
    test_db.commit()

    resp = client.delete(
        f"/api/orgs/{org.slug}/join-request", headers=_auth(user),
    )
    assert resp.status_code == 204
    # No body on 204.

    # Row deleted.
    m = test_db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == org.id,
        models.OrgMembership.user_id == user.id,
    ).first()
    assert m is None

    # Audit event.
    events = _audit_events(test_db, "org.join_request_cancelled")
    assert len(events) == 1


def test_cancel_join_request_no_pending_404(client, test_db):
    user = _make_user(test_db, "no_pending")
    _make_org(test_db, "no-pending-org", join_policy="approval_required")
    test_db.commit()

    resp = client.delete(
        "/api/orgs/no-pending-org/join-request", headers=_auth(user),
    )
    assert resp.status_code == 404


def test_cancel_join_request_secret_404(client, test_db):
    """Cancellation on a secret org returns 404 (consistent with B2)."""
    user = _make_user(test_db, "secret_cancel")
    _make_org(test_db, "secret-cancel-org", join_policy="invite_only_secret")
    test_db.commit()

    resp = client.delete(
        "/api/orgs/secret-cancel-org/join-request", headers=_auth(user),
    )
    assert resp.status_code == 404


def test_cancel_join_request_idempotent_404_on_repeat(client, test_db):
    """Calling DELETE twice: second call returns 404 (no pending request)
    rather than erroring — idempotent within the 404-on-no-pending
    behavior."""
    user = _make_user(test_db, "repeat_cancel")
    org = _make_org(test_db, "repeat-cancel-org", join_policy="approval_required")
    make_org_membership(
        test_db, org_id=org.id, user_id=user.id, role="member",
        status="pending_approval",
    )
    test_db.commit()

    r1 = client.delete(
        f"/api/orgs/{org.slug}/join-request", headers=_auth(user),
    )
    assert r1.status_code == 204
    r2 = client.delete(
        f"/api/orgs/{org.slug}/join-request", headers=_auth(user),
    )
    assert r2.status_code == 404


def test_cancel_join_request_active_member_404_not_deleted(client, test_db):
    """Calling DELETE while active (not pending) returns 404 — only
    pending_approval rows are deletable via this endpoint. Active
    membership untouched."""
    user = _make_user(test_db, "active_no_cancel")
    org = _make_org(test_db, "active-no-cancel-org", join_policy="open")
    make_org_membership(
        test_db, org_id=org.id, user_id=user.id, role="member", status="active",
    )
    test_db.commit()

    resp = client.delete(
        f"/api/orgs/{org.slug}/join-request", headers=_auth(user),
    )
    assert resp.status_code == 404

    # Active membership untouched.
    m = test_db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == org.id,
        models.OrgMembership.user_id == user.id,
    ).first()
    assert m is not None
    assert m.status == "active"


def test_cancel_join_request_logged_out_401(client, test_db):
    _make_org(test_db, "logout-cancel", join_policy="approval_required")
    test_db.commit()

    resp = client.delete("/api/orgs/logout-cancel/join-request")
    assert resp.status_code == 401


# ===========================================================================
# B4 — PATCH /api/orgs/{slug}/branding intro_text
# ===========================================================================

def test_patch_branding_intro_text_persists(client, test_db):
    """intro_text persists to settings.intro_text (top-level, not inside
    settings.branding)."""
    user = _make_user(test_db, "steward_intro")
    org = _make_org(test_db, "intro-org", join_policy="open")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/{org.slug}/branding",
        json={"intro_text": "# Welcome\n\nThis is our org."},
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text

    test_db.refresh(org)
    # Lives at top level, NOT inside the branding sub-dict.
    assert org.settings["intro_text"] == "# Welcome\n\nThis is our org."
    # branding sub-dict shouldn't have intro_text leaked into it.
    assert "intro_text" not in (org.settings.get("branding") or {})


def test_patch_branding_intro_text_audit_diff(client, test_db):
    """intro_text changes appear in the audit diff alongside color
    changes."""
    user = _make_user(test_db, "steward_intro_audit")
    org = _make_org(test_db, "intro-audit-org", join_policy="open")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/{org.slug}/branding",
        json={"intro_text": "First version", "primary_color": "#abcdef"},
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text

    events = _audit_events(test_db, "org.branding_updated")
    assert len(events) == 1
    diff = events[0].details["changes"]
    assert diff["intro_text"]["new"] == "First version"
    assert diff["intro_text"]["old"] is None
    assert diff["primary_color"]["new"] == "#abcdef"


def test_patch_branding_intro_text_too_long_400(client, test_db):
    """Over 5000 chars returns 4xx (Pydantic validator surfaces as 422)."""
    user = _make_user(test_db, "steward_long")
    org = _make_org(test_db, "long-org", join_policy="open")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    too_long = "x" * 5001
    resp = client.patch(
        f"/api/orgs/{org.slug}/branding",
        json={"intro_text": too_long},
        headers=_auth(user),
    )
    assert resp.status_code in (400, 422)


def test_patch_branding_intro_text_at_limit_accepted(client, test_db):
    """Exactly 5000 chars is accepted (boundary)."""
    user = _make_user(test_db, "steward_limit")
    org = _make_org(test_db, "limit-org", join_policy="open")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    at_limit = "y" * 5000
    resp = client.patch(
        f"/api/orgs/{org.slug}/branding",
        json={"intro_text": at_limit},
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text
    test_db.refresh(org)
    assert org.settings["intro_text"] == at_limit


def test_patch_branding_intro_text_member_403(client, test_db):
    """Member without org.edit_branding cannot set intro_text."""
    user = _make_user(test_db, "intro_member")
    org = _make_org(test_db, "intro-member-org", join_policy="open")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="member")
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/{org.slug}/branding",
        json={"intro_text": "hacked"},
        headers=_auth(user),
    )
    assert resp.status_code == 403


def test_patch_branding_intro_text_clear_with_empty_string(client, test_db):
    """Submitting empty string clears the field — get_intro_text reads
    empty string as None."""
    user = _make_user(test_db, "steward_clear_intro")
    org = _make_org(
        test_db, "clear-intro-org", join_policy="open",
        settings={"intro_text": "Existing content"},
    )
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/{org.slug}/branding",
        json={"intro_text": ""},
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text
    test_db.refresh(org)
    assert org.settings["intro_text"] == ""

    # Public endpoint surfaces it as null (helper-driven).
    resp_pub = client.get(f"/api/orgs/{org.slug}/public")
    assert resp_pub.json()["intro_text"] is None


def test_patch_branding_intro_text_absent_leaves_unchanged(client, test_db):
    """PATCH without intro_text key leaves the existing value alone."""
    user = _make_user(test_db, "steward_unchanged")
    org = _make_org(
        test_db, "unchanged-org", join_policy="open",
        settings={"intro_text": "Should remain"},
    )
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/{org.slug}/branding",
        json={"primary_color": "#111111"},
        headers=_auth(user),
    )
    assert resp.status_code == 200
    test_db.refresh(org)
    assert org.settings["intro_text"] == "Should remain"


# ===========================================================================
# B5 — schemas.py validation
# ===========================================================================

def test_create_org_rejects_legacy_invite_only_400(client, test_db):
    """POST /api/orgs with join_policy='invite_only' returns 4xx with
    explicit error referencing the new value names."""
    user = _make_user(test_db, "creator_legacy")
    test_db.commit()

    resp = client.post(
        "/api/orgs",
        json={
            "name": "Legacy Pilot", "slug": "legacy-pilot",
            "description": "test",
            "join_policy": "invite_only",
        },
        headers=_auth(user),
    )
    # Pydantic v2 surfaces field-validator failures as 422.
    assert resp.status_code in (400, 422)
    body = resp.text
    assert "invite_only" in body
    assert "no longer accepted" in body


def test_create_org_accepts_invite_only_secret(client, test_db):
    user = _make_user(test_db, "creator_secret")
    test_db.commit()

    resp = client.post(
        "/api/orgs",
        json={
            "name": "Secret Org", "slug": "secret-org-create",
            "description": "secret",
            "join_policy": "invite_only_secret",
        },
        headers=_auth(user),
    )
    assert resp.status_code == 201, resp.text
    # Phase 57 — `invite_only_secret` is accepted (back-compat) but
    # normalizes to `invite` with discoverability='hidden'.
    body = resp.json()
    assert body["join_policy"] == "invite"
    assert body["discoverability"] == "hidden"


def test_create_org_accepts_invite_only_public(client, test_db):
    user = _make_user(test_db, "creator_public")
    test_db.commit()

    resp = client.post(
        "/api/orgs",
        json={
            "name": "Public Org", "slug": "public-org-create",
            "description": "public",
            "join_policy": "invite_only_public",
        },
        headers=_auth(user),
    )
    assert resp.status_code == 201, resp.text
    # Phase 57 — `invite_only_public` normalizes to `invite` +
    # discoverability='listed'.
    body = resp.json()
    assert body["join_policy"] == "invite"
    assert body["discoverability"] == "listed"


def test_create_org_accepts_approval_required(client, test_db):
    user = _make_user(test_db, "creator_ar")
    test_db.commit()

    resp = client.post(
        "/api/orgs",
        json={
            "name": "AR Org", "slug": "ar-org-create",
            "join_policy": "approval_required",
        },
        headers=_auth(user),
    )
    assert resp.status_code == 201, resp.text


def test_create_org_accepts_open(client, test_db):
    user = _make_user(test_db, "creator_open")
    test_db.commit()

    resp = client.post(
        "/api/orgs",
        json={
            "name": "Open Org", "slug": "open-org-create",
            "join_policy": "open",
        },
        headers=_auth(user),
    )
    assert resp.status_code == 201


def test_patch_org_rejects_legacy_invite_only(client, test_db):
    """PATCH /api/orgs/{slug} with join_policy='invite_only' rejected."""
    user = _make_user(test_db, "patcher_legacy")
    org = _make_org(test_db, "patch-legacy-org", join_policy="open")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="admin")
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/{org.slug}",
        json={"join_policy": "invite_only"},
        headers=_auth(user),
    )
    assert resp.status_code in (400, 422)
    assert "no longer accepted" in resp.text


def test_patch_org_accepts_all_four_new_values(client, test_db):
    """All four legacy values can be set via PATCH (back-compat per
    Phase 57). The schema validator normalizes them onto the new
    three-value vocabulary at write time."""
    user = _make_user(test_db, "patcher_all4")
    org = _make_org(test_db, "patch-all4-org", join_policy="open")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="admin")
    test_db.commit()

    # Phase 57 legacy→new normalization mapping.
    expected = {
        "invite_only_secret": "invite",
        "invite_only_public": "invite",
        "approval_required": "approval",
        "open": "open",
    }
    for new_val, expected_jp in expected.items():
        resp = client.patch(
            f"/api/orgs/{org.slug}",
            json={"join_policy": new_val},
            headers=_auth(user),
        )
        assert resp.status_code == 200, (new_val, resp.text)
        assert resp.json()["join_policy"] == expected_jp, (
            f"PATCH {new_val!r} → {resp.json()['join_policy']!r}, "
            f"expected {expected_jp!r}"
        )
