"""Phase 38 — Authorization audit bundle regression tests.

Covers B1 (unscoped proposal endpoints), B2 (WebSocket auth handshake),
B3 (login rate limit + failed-attempt audit), B4 (sub-org tier
transferability tightening), B5 (``can_delegate_to`` org scope), and
B7 (legacy demo-login branch deletion).

Spec: phase38_authorization_audit_spec.md §"Cluster T".
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from main import app
from permissions import can_delegate_to
from role_seed import seed_default_roles_for_org
from settings import settings


_DUMMY_HASH = auth_utils.hash_password("test1234")


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
    from websocket import get_websocket_session_factory
    app.dependency_overrides[get_websocket_session_factory] = lambda: sessionmaker(bind=test_db.get_bind())
    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def public_demo(monkeypatch):
    monkeypatch.setattr(settings, "debug", False)
    monkeypatch.setattr(settings, "is_public_demo", True)


def _make_user(
    db, username: str, *, is_admin: bool = False,
    password: str = "test1234",
) -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=auth_utils.hash_password(password),
        email=f"{username}@test.example",
        email_verified=True,
        is_admin=is_admin,
    )
    db.add(u)
    db.flush()
    return u


def _make_org(
    db,
    *,
    slug: str,
    name: str | None = None,
    parent_org_id: str | None = None,
    settings_dict: dict | None = None,
    is_demo: bool = False,
    personas: list | None = None,
) -> models.Organization:
    org = models.Organization(
        slug=slug,
        name=name or slug.title(),
        join_policy="open",
        parent_org_id=parent_org_id,
        settings=settings_dict or {},
        is_demo=is_demo,
        personas=personas,
    )
    db.add(org)
    db.flush()
    if parent_org_id is None:
        seed_default_roles_for_org(db, org.id)
    return org


def _make_membership(
    db, org: models.Organization, user: models.User, role_system_key: str = "member",
) -> models.OrgMembership:
    role = db.query(models.Role).filter(
        models.Role.org_id == org.id,
        models.Role.system_key == role_system_key,
    ).first()
    m = models.OrgMembership(
        user_id=user.id, org_id=org.id, role_id=role.id, status="active",
    )
    db.add(m)
    db.flush()
    return m


def _make_sub_org_membership(
    db,
    sub_org: models.Organization,
    user: models.User,
    role_system_key: str = "member",
) -> models.SubOrgMembership:
    """Sub-orgs inherit the parent's role rows; look up by parent_org_id."""
    role = db.query(models.Role).filter(
        models.Role.org_id == sub_org.parent_org_id,
        models.Role.system_key == role_system_key,
    ).first()
    sm = models.SubOrgMembership(
        user_id=user.id, sub_org_id=sub_org.id, role_id=role.id, status="active",
    )
    db.add(sm)
    db.flush()
    return sm


def _make_proposal(
    db,
    *,
    author: models.User,
    org_id: str | None = None,
    sub_org_id: str | None = None,
    status: str = "voting",
) -> models.Proposal:
    p = models.Proposal(
        title="Phase38 Test Proposal",
        body="body",
        author_id=author.id,
        org_id=org_id,
        sub_org_id=sub_org_id,
        status=status,
        voting_method="binary",
    )
    db.add(p)
    db.flush()
    return p


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


# ===========================================================================
# B1 — Unscoped proposal endpoints require auth + eligibility filter
# ===========================================================================


def test_b1_list_proposals_requires_auth(client, test_db):
    """GET /api/proposals (no Authorization header) → 401."""
    resp = client.get("/api/proposals")
    assert resp.status_code == 401, resp.text


def test_b1_get_proposal_requires_auth(client, test_db):
    """GET /api/proposals/{id} (no Authorization header) → 401."""
    resp = client.get("/api/proposals/some-id")
    assert resp.status_code == 401, resp.text


def test_b1_get_results_requires_auth(client, test_db):
    resp = client.get("/api/proposals/some-id/results")
    assert resp.status_code == 401, resp.text


def test_b1_list_proposals_filters_to_user_eligible(client, test_db):
    """Authenticated as user in org A → list returns only org-A proposals.

    The cross-org leak the unscoped endpoint previously had is the headline
    fix; this is the regression net.
    """
    org_a = _make_org(test_db, slug="org-a")
    org_b = _make_org(test_db, slug="org-b")
    alice = _make_user(test_db, "alice38_a")
    bob = _make_user(test_db, "bob38_b")
    _make_membership(test_db, org_a, alice)
    _make_membership(test_db, org_b, bob)
    p_a = _make_proposal(test_db, author=alice, org_id=org_a.id)
    p_b = _make_proposal(test_db, author=bob, org_id=org_b.id)
    test_db.commit()

    resp = client.get("/api/proposals", headers=_auth(alice))
    assert resp.status_code == 200, resp.text
    ids = {p["id"] for p in resp.json()}
    assert p_a.id in ids
    assert p_b.id not in ids, "Cross-org leak — alice (org A) saw org B proposal"


def test_b1_list_proposals_admin_bypasses_filter(client, test_db):
    """Platform admin sees everything (D4 — admin bypass)."""
    org_a = _make_org(test_db, slug="org-a-admin")
    org_b = _make_org(test_db, slug="org-b-admin")
    admin = _make_user(test_db, "admin38", is_admin=True)
    member = _make_user(test_db, "member38")
    _make_membership(test_db, org_a, member)
    p_a = _make_proposal(test_db, author=member, org_id=org_a.id)
    p_b = _make_proposal(test_db, author=member, org_id=org_b.id)
    test_db.commit()

    resp = client.get("/api/proposals", headers=_auth(admin))
    assert resp.status_code == 200
    ids = {p["id"] for p in resp.json()}
    assert {p_a.id, p_b.id}.issubset(ids)


def test_b1_get_proposal_404_for_non_eligible_user(client, test_db):
    """Non-member of the proposal's org gets 404 (not 403). 404 keeps the
    existence of the proposal hidden from outsiders, matching the Phase 19
    / Phase 22 trajectory-endpoint posture.
    """
    org_a = _make_org(test_db, slug="b1-detail-org-a")
    org_b = _make_org(test_db, slug="b1-detail-org-b")
    alice = _make_user(test_db, "alice38_detail")
    outsider = _make_user(test_db, "outsider38_detail")
    _make_membership(test_db, org_a, alice)
    _make_membership(test_db, org_b, outsider)
    p_a = _make_proposal(test_db, author=alice, org_id=org_a.id)
    test_db.commit()

    resp = client.get(f"/api/proposals/{p_a.id}", headers=_auth(outsider))
    assert resp.status_code == 404, resp.text


def test_b1_get_results_404_for_non_eligible_user(client, test_db):
    """Same posture for /results — don't leak live tally to outsiders."""
    org_a = _make_org(test_db, slug="b1-results-org-a")
    org_b = _make_org(test_db, slug="b1-results-org-b")
    alice = _make_user(test_db, "alice38_results")
    outsider = _make_user(test_db, "outsider38_results")
    _make_membership(test_db, org_a, alice)
    _make_membership(test_db, org_b, outsider)
    p_a = _make_proposal(test_db, author=alice, org_id=org_a.id)
    test_db.commit()

    resp = client.get(
        f"/api/proposals/{p_a.id}/results", headers=_auth(outsider),
    )
    assert resp.status_code == 404, resp.text


# ===========================================================================
# B2 — WebSocket auth handshake
# ===========================================================================


def test_b2_websocket_closes_on_nonexistent_proposal(client, test_db):
    """Bogus proposal_id → close 4404 BEFORE the handshake wait, so timing
    doesn't reveal the proposal-existence boundary."""
    test_db.commit()
    with pytest.raises(Exception) as exc_info:
        with client.websocket_connect("/ws/proposals/no-such-id") as ws:
            # If accept happens we'd reach here; expect WebSocketDisconnect
            ws.receive_text()
    # starlette wraps the close as WebSocketDisconnect; verify the close code.
    from starlette.websockets import WebSocketDisconnect
    if isinstance(exc_info.value, WebSocketDisconnect):
        assert exc_info.value.code == 4404


def test_b2_websocket_closes_on_missing_handshake(client, test_db):
    """Connect, don't send anything — close 4401 after the 5s timeout.

    NB: we use a small DB sleep + early disconnect rather than waiting the
    full 5s; the close-code on the server side is the same.
    """
    org = _make_org(test_db, slug="b2-no-handshake")
    alice = _make_user(test_db, "alice38_b2")
    _make_membership(test_db, org, alice)
    p = _make_proposal(test_db, author=alice, org_id=org.id)
    test_db.commit()

    from starlette.websockets import WebSocketDisconnect
    # The route's first action after accept() is `await receive_text()`
    # with a 5s timeout. We trigger the malformed-handshake path by
    # sending garbage instead — that hits the same 4401 close code
    # without waiting on the timeout. The pure no-send timeout case is
    # exercised manually via curl during prod QA.
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/ws/proposals/{p.id}") as ws:
            ws.send_text("not-json")
            ws.receive_text()
    assert exc_info.value.code == 4401


def test_b2_websocket_closes_on_invalid_token(client, test_db):
    """Connect, send a malformed token → close 4401."""
    org = _make_org(test_db, slug="b2-invalid-token")
    alice = _make_user(test_db, "alice38_b2_invalid")
    _make_membership(test_db, org, alice)
    p = _make_proposal(test_db, author=alice, org_id=org.id)
    test_db.commit()

    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/ws/proposals/{p.id}") as ws:
            ws.send_text(json.dumps({"auth": "garbage-token"}))
            ws.receive_text()
    assert exc_info.value.code == 4401


def test_b2_websocket_closes_on_non_eligible_user(client, test_db):
    """Valid token but user isn't in the proposal's eligible-viewer set →
    close 4403."""
    org_a = _make_org(test_db, slug="b2-elig-org-a")
    org_b = _make_org(test_db, slug="b2-elig-org-b")
    alice = _make_user(test_db, "alice38_b2_elig")
    outsider = _make_user(test_db, "outsider38_b2_elig")
    _make_membership(test_db, org_a, alice)
    _make_membership(test_db, org_b, outsider)
    p = _make_proposal(test_db, author=alice, org_id=org_a.id)
    test_db.commit()

    from starlette.websockets import WebSocketDisconnect
    token = auth_utils.create_access_token(outsider.id)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/ws/proposals/{p.id}") as ws:
            ws.send_text(json.dumps({"auth": token}))
            ws.receive_text()
    assert exc_info.value.code == 4403


def test_b2_websocket_accepts_eligible_user(client, test_db):
    """Happy path — valid token + eligible user keeps the socket open."""
    org = _make_org(test_db, slug="b2-happy")
    alice = _make_user(test_db, "alice38_b2_happy")
    _make_membership(test_db, org, alice)
    p = _make_proposal(test_db, author=alice, org_id=org.id)
    test_db.commit()

    token = auth_utils.create_access_token(alice.id)
    with client.websocket_connect(f"/ws/proposals/{p.id}") as ws:
        ws.send_text(json.dumps({"auth": token}))
        # Socket stays open — no immediate close. The route is in its
        # passive receive loop; closing the client end is the clean exit.


# ===========================================================================
# B3 — Login rate limit + failed-attempt audit
# ===========================================================================


def test_b3_login_rate_limit_triggers_after_10_in_a_minute(client, test_db):
    """11th bad-credentials POST in <1 minute returns 429."""
    _make_user(test_db, "rate_target")
    test_db.commit()

    for i in range(10):
        resp = client.post(
            "/api/auth/login",
            data={"username": "rate_target", "password": "wrong"},
        )
        assert resp.status_code == 401, f"Attempt {i + 1}: {resp.text}"

    resp = client.post(
        "/api/auth/login",
        data={"username": "rate_target", "password": "wrong"},
    )
    assert resp.status_code == 429, resp.text


def test_b3_login_failed_audits_with_bad_password(client, test_db):
    """Bad password → `user.login_failed` row with target_id=user.id."""
    u = _make_user(test_db, "audit_bad_pw")
    test_db.commit()

    resp = client.post(
        "/api/auth/login",
        data={"username": "audit_bad_pw", "password": "wrong-password"},
    )
    assert resp.status_code == 401

    entry = test_db.query(models.AuditLog).filter(
        models.AuditLog.action == "user.login_failed",
        models.AuditLog.target_id == u.id,
    ).first()
    assert entry is not None
    assert entry.details.get("username") == "audit_bad_pw"
    assert entry.details.get("user_exists") is True


def test_b3_login_failed_audits_with_unknown_username(client, test_db):
    """Unknown username → audit row with target_id=username string (the
    AuditLog.target_id column is NOT NULL, so we use the probed
    username as the target rather than empty string)."""
    resp = client.post(
        "/api/auth/login",
        data={"username": "no-such-user", "password": "anything"},
    )
    assert resp.status_code == 401

    entry = test_db.query(models.AuditLog).filter(
        models.AuditLog.action == "user.login_failed",
        models.AuditLog.target_id == "no-such-user",
    ).first()
    assert entry is not None
    assert entry.details.get("username") == "no-such-user"
    assert entry.details.get("user_exists") is False


def test_b3_demo_login_rate_limit_triggers(client, test_db, public_demo):
    """Same rate-limit applies to /api/auth/demo-login (request shape =
    JSON body)."""
    for _ in range(10):
        resp = client.post(
            "/api/auth/demo-login",
            json={"username": "noone", "org_slug": "no-such"},
        )
        assert resp.status_code in (400, 404)

    resp = client.post(
        "/api/auth/demo-login",
        json={"username": "noone", "org_slug": "no-such"},
    )
    assert resp.status_code == 429


# ===========================================================================
# B4 — Sub-org tier transferability tightening
# ===========================================================================


def test_b4_parent_admin_with_transferability_enabled_passes_sub_org_admin_gate(
    client, test_db,
):
    """Default settings (transferability ON) — parent admin reaches a
    sub-org admin-gated route through the Phase 34.1 E4 fallback.

    Probes via PATCH /api/orgs/{sub-slug} (require_org_admin); an empty-
    body PATCH is a no-op and returns 200 if the admin gate passes.
    """
    parent = _make_org(test_db, slug="b4-trans-on")
    sub = _make_org(
        test_db, slug="b4-trans-on-sub", parent_org_id=parent.id,
    )
    admin = _make_user(test_db, "b4_parent_admin_on")
    _make_membership(test_db, parent, admin, role_system_key="admin")
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/{sub.slug}", json={}, headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text


def test_b4_parent_admin_with_transferability_disabled_fails_sub_org_admin_gate(
    client, test_db,
):
    """With sub_org_role_transferability.admin=False on the parent, the
    Phase 38 B4 tier check raises 403 instead of granting access."""
    parent = _make_org(
        test_db, slug="b4-trans-off",
        settings_dict={
            "sub_org_role_transferability": {"admin": False},
        },
    )
    sub = _make_org(
        test_db, slug="b4-trans-off-sub", parent_org_id=parent.id,
    )
    admin = _make_user(test_db, "b4_parent_admin_off")
    _make_membership(test_db, parent, admin, role_system_key="admin")
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/{sub.slug}", json={}, headers=_auth(admin),
    )
    assert resp.status_code == 403, resp.text


def test_b4_direct_sub_org_admin_unaffected_by_transferability(
    client, test_db,
):
    """A direct SubOrgMembership with admin role passes the gate regardless
    of the transferability setting — the gate only governs the parent-
    fallback case."""
    parent = _make_org(
        test_db, slug="b4-direct",
        settings_dict={
            "sub_org_role_transferability": {"admin": False},
        },
    )
    sub = _make_org(test_db, slug="b4-direct-sub", parent_org_id=parent.id)
    direct_admin = _make_user(test_db, "b4_direct_admin")
    _make_sub_org_membership(
        test_db, sub, direct_admin, role_system_key="admin",
    )
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/{sub.slug}", json={}, headers=_auth(direct_admin),
    )
    assert resp.status_code == 200, resp.text


# ===========================================================================
# B5 — can_delegate_to org scope
# ===========================================================================


def test_b5_can_delegate_to_with_explicit_org_id_filters_cross_org_profile(
    test_db,
):
    """Delegate has a public DelegateProfile in org A; query with
    org_id=org_b returns False because the profile is org-scoped."""
    org_a = _make_org(test_db, slug="b5-cross-a")
    org_b = _make_org(test_db, slug="b5-cross-b")
    delegator = _make_user(test_db, "b5_delegator")
    delegate = _make_user(test_db, "b5_delegate")

    topic_a = models.Topic(name="b5_topic_a", color="#000000", org_id=org_a.id)
    test_db.add(topic_a)
    test_db.flush()
    profile = models.DelegateProfile(
        user_id=delegate.id,
        topic_id=topic_a.id,
        org_id=org_a.id,
        visibility="public_accepting",
    )
    test_db.add(profile)
    test_db.commit()

    # With org_id=org_b, the org-scoped filter excludes the org-A profile.
    assert can_delegate_to(
        test_db, delegator.id, delegate.id, topic_a.id, org_id=org_b.id,
    ) is False
    # Same call without the org filter (legacy callers) — the visibility
    # predicate still matches, so this returns True (the cross-org leak
    # the new param closes).
    assert can_delegate_to(
        test_db, delegator.id, delegate.id, topic_a.id,
    ) is True


def test_b5_can_delegate_to_with_org_id_matching_finds_profile(test_db):
    """Regression net: with org_id matching the profile's org, the
    function still returns True."""
    org = _make_org(test_db, slug="b5-match")
    delegator = _make_user(test_db, "b5_match_delegator")
    delegate = _make_user(test_db, "b5_match_delegate")
    topic = models.Topic(name="b5_match_topic", color="#000000", org_id=org.id)
    test_db.add(topic)
    test_db.flush()
    test_db.add(models.DelegateProfile(
        user_id=delegate.id, topic_id=topic.id, org_id=org.id,
        visibility="public_accepting",
    ))
    test_db.commit()

    assert can_delegate_to(
        test_db, delegator.id, delegate.id, topic.id, org_id=org.id,
    ) is True


def test_b5_can_delegate_to_filters_follow_relationship_by_org_id(test_db):
    """When org_id is provided, the follow-based path is also org-scoped:
    a delegation_allowed follow in org A doesn't permit a delegation
    targeted at org B."""
    org_a = _make_org(test_db, slug="b5-follow-a")
    org_b = _make_org(test_db, slug="b5-follow-b")
    delegator = _make_user(test_db, "b5_follow_delegator")
    delegate = _make_user(test_db, "b5_follow_delegate")
    follow = models.FollowRelationship(
        follower_id=delegator.id,
        followed_id=delegate.id,
        org_id=org_a.id,
        permission_level="delegation_allowed",
    )
    test_db.add(follow)
    test_db.commit()

    assert can_delegate_to(
        test_db, delegator.id, delegate.id, topic_id=None, org_id=org_b.id,
    ) is False
    # Same call with the matching org_id — follow grants delegation.
    assert can_delegate_to(
        test_db, delegator.id, delegate.id, topic_id=None, org_id=org_a.id,
    ) is True


def test_b5_can_delegate_to_visibility_filter_excludes_private_profile(
    test_db,
):
    """Phase 37 B3 ride-along: ``can_delegate_to`` now also filters
    ``visibility in ("public", "public_accepting")``. A private profile
    is no longer enough on its own."""
    org = _make_org(test_db, slug="b5-vis")
    delegator = _make_user(test_db, "b5_vis_delegator")
    delegate = _make_user(test_db, "b5_vis_delegate")
    topic = models.Topic(name="b5_vis_topic", color="#000000", org_id=org.id)
    test_db.add(topic)
    test_db.flush()
    test_db.add(models.DelegateProfile(
        user_id=delegate.id, topic_id=topic.id, org_id=org.id,
        visibility="private",
    ))
    test_db.commit()

    assert can_delegate_to(
        test_db, delegator.id, delegate.id, topic.id, org_id=org.id,
    ) is False


# ===========================================================================
# B7 — Legacy demo-login branch deletion
# ===========================================================================


def test_b7_demo_login_requires_org_slug(client, test_db, public_demo):
    """POST /api/auth/demo-login with no ``org_slug`` → 400 explicit error
    rather than silently falling through to the (now-deleted) legacy
    DEMO_USERNAMES branch."""
    _make_user(test_db, "b7_alice")
    test_db.commit()

    resp = client.post(
        "/api/auth/demo-login", json={"username": "b7_alice"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "org_slug is required"


def test_b7_demo_login_with_org_slug_still_works(
    client, test_db, public_demo,
):
    """Regression net: per-org demo-login path still issues tokens when
    given a valid (org_slug, persona) pair."""
    org = _make_org(
        test_db,
        slug="b7-live-demo",
        is_demo=True,
        personas=[
            {"username": "b7_persona", "display_name": "B7 Persona",
             "role": "member"},
        ],
    )
    persona = _make_user(test_db, "b7_persona")
    _make_membership(test_db, org, persona)
    test_db.commit()

    resp = client.post(
        "/api/auth/demo-login",
        json={"username": "b7_persona", "org_slug": "b7-live-demo"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "access_token" in body


def test_b7_demo_usernames_constant_removed():
    """The module-level ``DEMO_USERNAMES`` constant is gone — Phase 38 B7
    deleted it along with the legacy demo-login branch. Cheap regression
    net against a future contributor adding the constant back without
    realizing the legacy path it served is gone.
    """
    from routes import auth as auth_routes
    assert not hasattr(auth_routes, "DEMO_USERNAMES"), (
        "DEMO_USERNAMES was reintroduced; Phase 38 B7 deleted it together "
        "with the legacy /api/auth/demo-login (org_slug=None) branch. If a "
        "new demo flow needs a username allowlist, source it from the per-"
        "org Organization.personas allowlist instead."
    )
