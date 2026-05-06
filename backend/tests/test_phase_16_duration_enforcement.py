"""Phase 16 B3 — proposal.set_durations enforcement tests.

Mirror of ``test_phase_12_5_threshold_enforcement.py`` for the new
``proposal.set_durations`` permission key (Phase 16 Q1 + B3).

Covers POST /api/orgs/{slug}/proposals, POST /api/proposals (global),
and PATCH /api/proposals/{id}:

  - 201 happy: caller WITH ``proposal.set_durations`` (Steward default)
    creates a proposal with custom durations; persisted verbatim.
  - 201 happy: caller WITHOUT permission (Member default) omits the
    duration fields; proposal lands on org defaults (NOT NULL — the
    route persists the *effective* values per spec §B3 step 4 +
    spec line 109 "existing proposals keep whatever durations they
    were created with").
  - 201 happy: caller WITHOUT permission explicitly passes durations
    matching org defaults; succeeds (the gate checks "differs from
    defaults," not "is present").
  - 400 deny: caller WITHOUT permission passes durations differing
    from org defaults; HTTP 400 with the spec's error message.
  - 400 floor: voting_days = 0.04 (below floor 0.05); deliberation_days
    = -1 (negative); each rejected with the spec's exact error message.
  - 201 happy: voting_days = 0.05 (at floor); deliberation_days = 0.

Same shape applied to PATCH. Persistence test: after a successful
POST/PATCH, the Proposal row's deliberation_days / voting_days are the
expected values.
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


def _grant_member_proposal_create(db: Session, org: models.Organization) -> None:
    """Member role has no proposal.create by default — grant it via the
    matrix so the Member can submit at all. Then the duration gate is the
    only thing the test cares about."""
    role = db.query(models.Role).filter_by(
        org_id=org.id, system_key="member",
    ).first()
    db.add(models.RolePermission(
        role_id=role.id, permission_key="proposal.create", enabled=True,
    ))


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


# ---------------------------------------------------------------------------
# B3 POST /api/orgs/{slug}/proposals
# ---------------------------------------------------------------------------


def test_post_steward_can_set_non_default_durations(client, test_db):
    """Happy path: a Steward (default ``proposal.set_durations=True``)
    creates a proposal with custom 5 / 2 durations; persisted verbatim
    on the row."""
    user = _make_user(test_db, "steward_dur")
    org = _make_org(test_db, "steward-dur")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    topic = _seed_topic(test_db, org)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals",
        json={
            "title": "P", "body": "B",
            "topics": [{"topic_id": topic.id}],
            "voting_method": "binary",
            "deliberation_days": 5,
            "voting_days": 2,
        },
        headers=_auth(user),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["deliberation_days"] == 5.0
    assert body["voting_days"] == 2.0

    # Persistence: row reflects the requested values.
    test_db.expire_all()
    row = test_db.get(models.Proposal, body["id"])
    assert row.deliberation_days == 5.0
    assert row.voting_days == 2.0


def test_post_moderator_can_set_non_default_durations(client, test_db):
    """Phase 16 Q1: Moderator (NOT Admin) is the lowest tier with
    ``proposal.set_durations=True`` by default — durations are logistics,
    not governance."""
    user = _make_user(test_db, "mod_dur")
    org = _make_org(test_db, "mod-dur")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="moderator")
    topic = _seed_topic(test_db, org)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals",
        json={
            "title": "P", "body": "B",
            "topics": [{"topic_id": topic.id}],
            "voting_method": "binary",
            "deliberation_days": 1,
            "voting_days": 0.5,
        },
        headers=_auth(user),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["deliberation_days"] == 1.0
    assert body["voting_days"] == 0.5


def test_post_member_omitting_durations_uses_org_defaults(client, test_db):
    """A Member granted ``proposal.create`` (matrix grant) omits the
    duration fields; the proposal lands on org defaults — and per spec
    line 109 the row persists those effective values rather than NULL."""
    user = _make_user(test_db, "member_omit_dur")
    org = _make_org(test_db, "member-omit-dur")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="member")
    _grant_member_proposal_create(test_db, org)
    topic = _seed_topic(test_db, org)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals",
        json={
            "title": "P", "body": "B",
            "topics": [{"topic_id": topic.id}],
            "voting_method": "binary",
            # duration fields intentionally omitted
        },
        headers=_auth(user),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # Platform defaults from org_config: 14 / 7.
    assert body["deliberation_days"] == 14.0
    assert body["voting_days"] == 7.0


def test_post_member_passing_durations_matching_defaults_succeeds(client, test_db):
    """The check is 'differs from defaults,' not 'is present.' A Member
    who explicitly passes 14 / 7 (the platform defaults) succeeds even
    without ``proposal.set_durations``."""
    user = _make_user(test_db, "member_match_dur")
    org = _make_org(test_db, "member-match-dur")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="member")
    _grant_member_proposal_create(test_db, org)
    topic = _seed_topic(test_db, org)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals",
        json={
            "title": "P", "body": "B",
            "topics": [{"topic_id": topic.id}],
            "voting_method": "binary",
            "deliberation_days": 14,
            "voting_days": 7,
        },
        headers=_auth(user),
    )
    assert resp.status_code == 201, resp.text


def test_post_member_passing_non_default_durations_returns_400(client, test_db):
    """The denial case: a Member without ``proposal.set_durations`` who
    tries 5 / 2 (differs from default 14 / 7) gets HTTP 400 with the
    spec's exact error message."""
    user = _make_user(test_db, "member_block_dur")
    org = _make_org(test_db, "member-block-dur")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="member")
    _grant_member_proposal_create(test_db, org)
    topic = _seed_topic(test_db, org)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals",
        json={
            "title": "P", "body": "B",
            "topics": [{"topic_id": topic.id}],
            "voting_method": "binary",
            "deliberation_days": 5,
        },
        headers=_auth(user),
    )
    assert resp.status_code == 400
    assert "do not have permission" in resp.json()["detail"].lower()
    assert "default durations" in resp.json()["detail"].lower()


def test_post_member_uses_org_customised_default_when_omitted(client, test_db):
    """When the org has set ``default_voting_days`` to 4 via Org Settings,
    a Member omitting the field gets a proposal with voting_days=4
    (the org default), not 7 (the platform default)."""
    user = _make_user(test_db, "member_cust_dur")
    org = _make_org(
        test_db, "member-cust-dur",
        settings={"default_deliberation_days": 10, "default_voting_days": 4},
    )
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="member")
    _grant_member_proposal_create(test_db, org)
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
    assert body["deliberation_days"] == 10.0
    assert body["voting_days"] == 4.0


def test_post_voting_days_below_floor_returns_400(client, test_db):
    """Floor check: voting_days < 0.05 fails with the spec's exact
    error message — even for a Steward with the permission."""
    user = _make_user(test_db, "steward_floor_vote")
    org = _make_org(test_db, "steward-floor-vote")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    topic = _seed_topic(test_db, org)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals",
        json={
            "title": "P", "body": "B",
            "topics": [{"topic_id": topic.id}],
            "voting_method": "binary",
            "voting_days": 0.04,
        },
        headers=_auth(user),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == (
        "Voting duration must be at least 0.05 days (72 minutes)."
    )


def test_post_deliberation_days_negative_returns_400(client, test_db):
    """Floor check: deliberation_days < 0 fails with the spec's exact
    error message."""
    user = _make_user(test_db, "steward_floor_delib")
    org = _make_org(test_db, "steward-floor-delib")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    topic = _seed_topic(test_db, org)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals",
        json={
            "title": "P", "body": "B",
            "topics": [{"topic_id": topic.id}],
            "voting_method": "binary",
            "deliberation_days": -1,
        },
        headers=_auth(user),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == (
        "Deliberation duration cannot be negative."
    )


def test_post_at_floor_values_succeed(client, test_db):
    """Boundary: voting_days=0.05 (at the floor) and
    deliberation_days=0 (zero is valid for time-pressure decisions)
    both succeed for a Steward."""
    user = _make_user(test_db, "steward_at_floor")
    org = _make_org(test_db, "steward-at-floor")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    topic = _seed_topic(test_db, org)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals",
        json={
            "title": "P", "body": "B",
            "topics": [{"topic_id": topic.id}],
            "voting_method": "binary",
            "deliberation_days": 0,
            "voting_days": 0.05,
        },
        headers=_auth(user),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["deliberation_days"] == 0.0
    assert body["voting_days"] == 0.05


def test_post_global_proposal_no_org_skips_duration_gate(client, test_db):
    """Global (non-org) proposals via POST /api/proposals have no org
    context for the gate; the helper short-circuits and any duration
    value is honored — but floor checks still apply."""
    user = _make_user(test_db, "global_dur")
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
            "deliberation_days": 0,
            "voting_days": 0.5,
        },
        headers=_auth(user),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["deliberation_days"] == 0.0
    assert body["voting_days"] == 0.5


def test_post_global_proposal_below_floor_returns_400(client, test_db):
    """Floors apply even to global proposals (no permission gate to
    skip — voting_days < 0.05 is always invalid)."""
    user = _make_user(test_db, "global_dur_floor")
    topic = models.Topic(name="GT2", description="", color="#000000")
    test_db.add(topic)
    test_db.commit()

    resp = client.post(
        "/api/proposals",
        json={
            "title": "G", "body": "",
            "topics": [{"topic_id": topic.id}],
            "voting_method": "binary",
            "voting_days": 0.04,
        },
        headers=_auth(user),
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# B3 PATCH /api/proposals/{id}
# ---------------------------------------------------------------------------


def _make_org_proposal(
    db: Session, *, author: models.User, org: models.Organization,
) -> models.Proposal:
    p = models.Proposal(
        title="P", body="", author_id=author.id, org_id=org.id,
        voting_method="binary", num_winners=1,
        pass_threshold=0.50, quorum_threshold=0.40,
        status="draft",
    )
    db.add(p)
    db.flush()
    return p


def test_patch_steward_can_change_durations(client, test_db):
    """A Steward author patches their draft proposal with non-default
    durations; persisted on the row."""
    user = _make_user(test_db, "patch_steward_dur")
    org = _make_org(test_db, "patch-steward-dur")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    p = _make_org_proposal(test_db, author=user, org=org)
    test_db.commit()

    resp = client.patch(
        f"/api/proposals/{p.id}",
        json={"deliberation_days": 3, "voting_days": 1.5},
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deliberation_days"] == 3.0
    assert body["voting_days"] == 1.5

    test_db.expire_all()
    row = test_db.get(models.Proposal, p.id)
    assert row.deliberation_days == 3.0
    assert row.voting_days == 1.5


def test_patch_member_omitting_durations_succeeds(client, test_db):
    """Patching unrelated fields (title) without touching durations
    should never trigger the gate."""
    user = _make_user(test_db, "patch_member_omit_dur")
    org = _make_org(test_db, "patch-member-omit-dur")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="member")
    p = _make_org_proposal(test_db, author=user, org=org)
    test_db.commit()

    resp = client.patch(
        f"/api/proposals/{p.id}",
        json={"title": "Renamed"},
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "Renamed"


def test_patch_member_passing_durations_matching_defaults_succeeds(client, test_db):
    """Member-author patches with the org-default duration value; succeeds
    (matches default, no override)."""
    user = _make_user(test_db, "patch_member_match_dur")
    org = _make_org(test_db, "patch-member-match-dur")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="member")
    p = _make_org_proposal(test_db, author=user, org=org)
    test_db.commit()

    resp = client.patch(
        f"/api/proposals/{p.id}",
        json={"deliberation_days": 14, "voting_days": 7},
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text


def test_patch_member_passing_non_default_durations_returns_400(client, test_db):
    """Member-author tries to patch voting_days to 1 (differs from org
    default 7); 400 with the explicit error message."""
    user = _make_user(test_db, "patch_member_block_dur")
    org = _make_org(test_db, "patch-member-block-dur")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="member")
    p = _make_org_proposal(test_db, author=user, org=org)
    test_db.commit()

    resp = client.patch(
        f"/api/proposals/{p.id}",
        json={"voting_days": 1},
        headers=_auth(user),
    )
    assert resp.status_code == 400
    assert "do not have permission" in resp.json()["detail"].lower()
    assert "default durations" in resp.json()["detail"].lower()


def test_patch_voting_days_below_floor_returns_400(client, test_db):
    """Floor check applies on PATCH too — even for a Steward."""
    user = _make_user(test_db, "patch_steward_floor")
    org = _make_org(test_db, "patch-steward-floor")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    p = _make_org_proposal(test_db, author=user, org=org)
    test_db.commit()

    resp = client.patch(
        f"/api/proposals/{p.id}",
        json={"voting_days": 0.04},
        headers=_auth(user),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == (
        "Voting duration must be at least 0.05 days (72 minutes)."
    )


def test_patch_deliberation_days_negative_returns_400(client, test_db):
    user = _make_user(test_db, "patch_steward_neg")
    org = _make_org(test_db, "patch-steward-neg")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    p = _make_org_proposal(test_db, author=user, org=org)
    test_db.commit()

    resp = client.patch(
        f"/api/proposals/{p.id}",
        json={"deliberation_days": -1},
        headers=_auth(user),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == (
        "Deliberation duration cannot be negative."
    )


def test_patch_at_floor_values_succeed(client, test_db):
    """Boundary on PATCH: voting_days=0.05, deliberation_days=0 both
    succeed for a Steward."""
    user = _make_user(test_db, "patch_steward_at_floor")
    org = _make_org(test_db, "patch-steward-at-floor")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    p = _make_org_proposal(test_db, author=user, org=org)
    test_db.commit()

    resp = client.patch(
        f"/api/proposals/{p.id}",
        json={"deliberation_days": 0, "voting_days": 0.05},
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deliberation_days"] == 0.0
    assert body["voting_days"] == 0.05


def test_patch_blocked_duration_change_does_not_persist_other_fields(client, test_db):
    """Belt-and-suspenders: when the duration gate fires, the rest of
    the PATCH body (title) does NOT get applied. This is implicit in the
    helper firing BEFORE the field writes; assert it explicitly to
    prevent regressions if someone reorders the block."""
    user = _make_user(test_db, "patch_atomic_dur")
    org = _make_org(test_db, "patch-atomic-dur")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="member")
    p = _make_org_proposal(test_db, author=user, org=org)
    original_title = p.title
    test_db.commit()

    resp = client.patch(
        f"/api/proposals/{p.id}",
        json={"title": "ChangedTitle", "voting_days": 1},
        headers=_auth(user),
    )
    assert resp.status_code == 400

    test_db.expire_all()
    p_reloaded = test_db.get(models.Proposal, p.id)
    assert p_reloaded.title == original_title, (
        "PATCH must be atomic: a 400 on duration gate must NOT persist "
        "other field changes (title)"
    )
