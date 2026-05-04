"""Phase 12.5 B3 — proposal.set_thresholds enforcement tests.

Covers POST /api/orgs/{slug}/proposals and PATCH /api/proposals/{id}:

  - 200 happy: caller WITH `proposal.set_thresholds` sets non-default
    thresholds; persisted with those values.
  - 200 happy: caller WITHOUT `proposal.set_thresholds` omits threshold
    fields; persisted with org defaults (NOT pydantic schema defaults).
  - 200 happy: caller WITHOUT `proposal.set_thresholds` explicitly
    passes thresholds matching org defaults; persisted with org defaults.
  - 400 deny: caller WITHOUT `proposal.set_thresholds` passes
    non-default thresholds; HTTP 400 with the spec's error message.

Same shape applied to PATCH. Edge cases covered:
  - Org-default override path: when org's default_pass_threshold itself
    is 0.55, a Member passing 0.55 succeeds; passing 0.50 fails (it
    differs from the org's customised default).
  - Global proposal POST (no org) skips the gate entirely.
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


@pytest.fixture(scope="function")
def test_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
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


def _make_user(db: Session, username: str) -> models.User:
    u = models.User(
        username=username,
        display_name=username,
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=True,
    )
    db.add(u)
    db.flush()
    return u


def _make_org(
    db: Session, slug: str, *, settings: dict | None = None,
) -> models.Organization:
    o = models.Organization(
        name=slug.title(), slug=slug, description="",
        settings=settings if settings is not None else {},
    )
    db.add(o)
    db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _seed_topic(db: Session, org: models.Organization) -> models.Topic:
    t = models.Topic(name="T", description="", color="#000000", org_id=org.id)
    db.add(t)
    db.flush()
    return t


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


# ---------------------------------------------------------------------------
# B3 POST /api/orgs/{slug}/proposals
# ---------------------------------------------------------------------------


def test_post_steward_can_set_non_default_thresholds(client, test_db):
    """Happy path: a Steward (default `proposal.set_thresholds=True`)
    creates a proposal with custom 0.66 / 0.30 thresholds; persisted
    verbatim."""
    user = _make_user(test_db, "steward_thresh")
    org = _make_org(test_db, "steward-thresh")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    topic = _seed_topic(test_db, org)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals",
        json={
            "title": "P", "body": "B",
            "topics": [{"topic_id": topic.id}],
            "voting_method": "binary",
            "pass_threshold": 0.66,
            "quorum_threshold": 0.30,
        },
        headers=_auth(user),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["pass_threshold"] == 0.66
    assert body["quorum_threshold"] == 0.30


def test_post_member_omitting_thresholds_uses_org_defaults(client, test_db):
    """A Member granted `proposal.create` (via custom matrix grant)
    omits the threshold fields entirely; the proposal lands on the
    org's defaults (not pydantic's schema defaults). With no custom
    org-level defaults set, this is 0.50 / 0.40 — but the path that
    matters is that the helper resolves org defaults, not Pydantic's."""
    user = _make_user(test_db, "member_thresh")
    org = _make_org(test_db, "member-thresh")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="member")
    # Grant Member proposal.create so they can submit at all (matrix-grant).
    role = test_db.query(models.Role).filter_by(
        org_id=org.id, system_key="member",
    ).first()
    test_db.add(models.RolePermission(
        role_id=role.id, permission_key="proposal.create", enabled=True,
    ))
    topic = _seed_topic(test_db, org)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals",
        json={
            "title": "P", "body": "B",
            "topics": [{"topic_id": topic.id}],
            "voting_method": "binary",
            # threshold fields intentionally omitted
        },
        headers=_auth(user),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["pass_threshold"] == 0.50
    assert body["quorum_threshold"] == 0.40


def test_post_member_passing_thresholds_matching_defaults_succeeds(client, test_db):
    """The check is 'differs from defaults,' not 'is present' (spec
    line 133). A Member who explicitly passes 0.50 / 0.40 succeeds
    even without `proposal.set_thresholds`."""
    user = _make_user(test_db, "member_match")
    org = _make_org(test_db, "member-match")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="member")
    role = test_db.query(models.Role).filter_by(
        org_id=org.id, system_key="member",
    ).first()
    test_db.add(models.RolePermission(
        role_id=role.id, permission_key="proposal.create", enabled=True,
    ))
    topic = _seed_topic(test_db, org)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals",
        json={
            "title": "P", "body": "B",
            "topics": [{"topic_id": topic.id}],
            "voting_method": "binary",
            "pass_threshold": 0.50,
            "quorum_threshold": 0.40,
        },
        headers=_auth(user),
    )
    assert resp.status_code == 201, resp.text


def test_post_member_passing_non_default_thresholds_returns_400(client, test_db):
    """The denial case: a Member without `proposal.set_thresholds` who
    tries 0.10 (or any non-default) gets HTTP 400 with the spec's exact
    error message (line 130)."""
    user = _make_user(test_db, "member_block")
    org = _make_org(test_db, "member-block")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="member")
    role = test_db.query(models.Role).filter_by(
        org_id=org.id, system_key="member",
    ).first()
    test_db.add(models.RolePermission(
        role_id=role.id, permission_key="proposal.create", enabled=True,
    ))
    topic = _seed_topic(test_db, org)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals",
        json={
            "title": "P", "body": "B",
            "topics": [{"topic_id": topic.id}],
            "voting_method": "binary",
            "pass_threshold": 0.10,
        },
        headers=_auth(user),
    )
    assert resp.status_code == 400
    assert "do not have permission" in resp.json()["detail"].lower()
    assert "default thresholds" in resp.json()["detail"].lower()


def test_post_member_uses_org_customised_default_when_omitted(client, test_db):
    """When the org's Steward has set default_pass_threshold to 0.55
    via the Org Settings UI, a Member omitting the threshold field gets
    a proposal with pass_threshold=0.55 (the org default), not 0.50
    (the schema default)."""
    user = _make_user(test_db, "member_cust")
    org = _make_org(
        test_db, "member-cust",
        settings={"default_pass_threshold": 0.55, "default_quorum_threshold": 0.35},
    )
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="member")
    role = test_db.query(models.Role).filter_by(
        org_id=org.id, system_key="member",
    ).first()
    test_db.add(models.RolePermission(
        role_id=role.id, permission_key="proposal.create", enabled=True,
    ))
    topic = _seed_topic(test_db, org)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals",
        json={
            "title": "P", "body": "B",
            "topics": [{"topic_id": topic.id}],
            "voting_method": "binary",
        },
        headers=_auth(user),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["pass_threshold"] == 0.55
    assert body["quorum_threshold"] == 0.35


def test_post_member_passing_schema_default_when_org_overrides_returns_400(client, test_db):
    """Edge case (spec line 135): if the org's default is 0.10 and a
    Member without permission passes 0.20, the request fails because
    0.20 differs from the org default (which is the source of truth).
    This test takes the symmetric form: org default 0.55, Member passes
    0.50 — fails because 0.50 != 0.55."""
    user = _make_user(test_db, "member_diff")
    org = _make_org(
        test_db, "member-diff",
        settings={"default_pass_threshold": 0.55},
    )
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="member")
    role = test_db.query(models.Role).filter_by(
        org_id=org.id, system_key="member",
    ).first()
    test_db.add(models.RolePermission(
        role_id=role.id, permission_key="proposal.create", enabled=True,
    ))
    topic = _seed_topic(test_db, org)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals",
        json={
            "title": "P", "body": "B",
            "topics": [{"topic_id": topic.id}],
            "voting_method": "binary",
            "pass_threshold": 0.50,  # the platform default, but NOT the org's default
        },
        headers=_auth(user),
    )
    assert resp.status_code == 400


def test_post_global_proposal_no_org_skips_threshold_gate(client, test_db):
    """Global (non-org) proposals via POST /api/proposals have no org
    context for the gate; the helper short-circuits and any threshold
    value is honored. This preserves pre-12.5 behavior for the global
    path (which is rarely used)."""
    user = _make_user(test_db, "global_thresh")
    topic = models.Topic(
        name="GlobalT", description="", color="#000000",
    )
    test_db.add(topic)
    test_db.commit()

    resp = client.post(
        "/api/proposals",
        json={
            "title": "G", "body": "",
            "topics": [{"topic_id": topic.id}],
            "voting_method": "binary",
            "pass_threshold": 0.10,
        },
        headers=_auth(user),
    )
    # Global path is reachable for any authenticated user; the threshold
    # gate is the only thing this test cares about.
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["pass_threshold"] == 0.10


# ---------------------------------------------------------------------------
# B3 PATCH /api/proposals/{id}
# ---------------------------------------------------------------------------


def _make_org_proposal(
    db: Session, *, author: models.User, org: models.Organization,
    pass_t: float = 0.50, quorum_t: float = 0.40,
) -> models.Proposal:
    p = models.Proposal(
        title="P", body="", author_id=author.id, org_id=org.id,
        voting_method="binary", num_winners=1,
        pass_threshold=pass_t, quorum_threshold=quorum_t,
        status="draft",
    )
    db.add(p)
    db.flush()
    return p


def test_patch_steward_can_change_thresholds(client, test_db):
    """A Steward author patches their draft proposal with non-default
    thresholds; persisted."""
    user = _make_user(test_db, "patch_steward")
    org = _make_org(test_db, "patch-steward")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    p = _make_org_proposal(test_db, author=user, org=org)
    test_db.commit()

    resp = client.patch(
        f"/api/proposals/{p.id}",
        json={"pass_threshold": 0.75},
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["pass_threshold"] == 0.75


def test_patch_member_omitting_thresholds_succeeds(client, test_db):
    """Patching unrelated fields (title, body) without touching
    thresholds should never trigger the gate."""
    user = _make_user(test_db, "patch_member_omit")
    org = _make_org(test_db, "patch-member-omit")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="member")
    # Grant proposal.create so they could create one. The author check
    # in PATCH is independent of the permission gate.
    p = _make_org_proposal(test_db, author=user, org=org)
    test_db.commit()

    resp = client.patch(
        f"/api/proposals/{p.id}",
        json={"title": "Renamed"},
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "Renamed"


def test_patch_member_passing_thresholds_matching_defaults_succeeds(client, test_db):
    """A Member-author patches with the org-default value (0.50);
    succeeds (matches default, no override)."""
    user = _make_user(test_db, "patch_member_match")
    org = _make_org(test_db, "patch-member-match")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="member")
    p = _make_org_proposal(test_db, author=user, org=org)
    test_db.commit()

    resp = client.patch(
        f"/api/proposals/{p.id}",
        json={"pass_threshold": 0.50, "quorum_threshold": 0.40},
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text


def test_patch_member_passing_non_default_thresholds_returns_400(client, test_db):
    """A Member-author tries to patch threshold to 0.20 (differs from
    org default 0.50); 400 with the explicit error message."""
    user = _make_user(test_db, "patch_member_block")
    org = _make_org(test_db, "patch-member-block")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="member")
    p = _make_org_proposal(test_db, author=user, org=org)
    test_db.commit()

    resp = client.patch(
        f"/api/proposals/{p.id}",
        json={"pass_threshold": 0.20},
        headers=_auth(user),
    )
    assert resp.status_code == 400
    assert "do not have permission" in resp.json()["detail"].lower()


def test_patch_blocked_threshold_change_does_not_persist_other_fields(client, test_db):
    """Belt-and-suspenders: when the threshold gate fires, the rest of
    the PATCH body (e.g. title) does NOT get applied. This is implicit
    in the helper firing BEFORE the field writes; we assert it explicitly."""
    user = _make_user(test_db, "patch_atomic")
    org = _make_org(test_db, "patch-atomic")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="member")
    p = _make_org_proposal(test_db, author=user, org=org)
    original_title = p.title
    test_db.commit()

    resp = client.patch(
        f"/api/proposals/{p.id}",
        json={"title": "ChangedTitle", "pass_threshold": 0.20},
        headers=_auth(user),
    )
    assert resp.status_code == 400

    test_db.expire_all()
    p_reloaded = test_db.get(models.Proposal, p.id)
    assert p_reloaded.title == original_title, (
        "PATCH must be atomic: a 400 on threshold gate must NOT persist "
        "other field changes (title)"
    )
