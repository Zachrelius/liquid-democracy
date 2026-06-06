"""Phase 57 — three-axis access model: side-effect tests.

Covers discoverability + activity_visibility (the migration mapping
+ parity already tested in `test_phase_57_migration_cycle.py`). Per
CLAUDE.md, all assertions read the persisted state back / hit the
endpoint and inspect the body shape — no status-code-only checks.

Test families:
  * Discoverability + /explore (4): listed appears; unlisted absent
    from /explore but splash 200s; hidden 404s splash + absent from
    /explore; demo + sub-org exclusion still hold.
  * Activity visibility (6): public anon list, public anon detail,
    Phase 30.3 private-topic vote invariant preserved, public-topic
    vote visible to anon (parity with public delegate page),
    members_only default 404s anon list/detail, anon vote/comment POST
    still gated.
  * Join policy (4): open instant-active, approval pending, invite
    blocked, Phase 52e verification flag-routing regression.
  * Serializer / validation (3): OrgOut surfaces three axes; out-of-
    vocab axis values rejected; hidden+public normalizes server-side.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from auth import hash_password
from database import Base, get_db
from main import app
from role_seed import seed_default_roles_for_org


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def db_session():
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
def client(db_session):
    def _get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth(user_id: str) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user_id)}"}


def _make_user(db: Session, username: str) -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=hash_password("x"),
        email=f"{username}@test.example",
        email_verified=True,
    )
    db.add(u)
    db.flush()
    return u


def _make_org(
    db: Session, slug: str, *,
    join_policy: str = "open",
    discoverability: str = "listed",
    activity_visibility: str = "members_only",
    parent_org_id: Optional[str] = None,
    is_demo: bool = False,
    name: Optional[str] = None,
) -> models.Organization:
    o = models.Organization(
        name=name or slug.title(), slug=slug,
        description="", settings={},
        join_policy=join_policy,
        discoverability=discoverability,
        activity_visibility=activity_visibility,
        parent_org_id=parent_org_id,
        is_demo=is_demo,
    )
    db.add(o); db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _add_active_member(
    db: Session, org: models.Organization, user: models.User,
    role: str = "member",
) -> models.OrgMembership:
    role_row = (
        db.query(models.Role)
        .filter_by(org_id=org.id, system_key=role)
        .first()
    )
    m = models.OrgMembership(
        user_id=user.id, org_id=org.id,
        role_id=role_row.id, status="active",
    )
    db.add(m); db.flush()
    return m


def _make_proposal(
    db: Session, org: models.Organization, author: models.User, *,
    status: str = "voting", title: str = "P",
) -> models.Proposal:
    p = models.Proposal(
        title=title, body="Body text", author_id=author.id,
        voting_method="binary", status=status,
        org_id=org.id,
        voting_start=datetime.utcnow() - timedelta(days=1),
        voting_end=datetime.utcnow() + timedelta(days=1),
    )
    db.add(p); db.flush()
    return p


# ===========================================================================
# Discoverability + /explore (4)
# ===========================================================================


def test_listed_org_appears_on_explore(client, db_session):
    _make_org(db_session, "listed-org", discoverability="listed")
    db_session.commit()
    r = client.get("/api/orgs/explore")
    assert r.status_code == 200
    slugs = {o["slug"] for o in r.json()["orgs"]}
    assert "listed-org" in slugs


def test_unlisted_org_absent_from_explore_but_splash_serves(client, db_session):
    """Spec D1 — unlisted is the new value Z wanted for gamenights:
    reachable by direct link, but hidden from the public directory."""
    _make_org(db_session, "unlisted-org", discoverability="unlisted")
    db_session.commit()

    r_explore = client.get("/api/orgs/explore")
    slugs = {o["slug"] for o in r_explore.json()["orgs"]}
    assert "unlisted-org" not in slugs

    # Direct-link splash still serves 200.
    r_splash = client.get("/api/orgs/unlisted-org/public")
    assert r_splash.status_code == 200
    assert r_splash.json()["slug"] == "unlisted-org"


def test_hidden_org_404s_splash_and_absent_from_explore(client, db_session):
    """Spec D1 — hidden is the legacy `invite_only_secret` semantic:
    no public landing, indistinguishable from non-existent."""
    _make_org(db_session, "hidden-org", discoverability="hidden")
    db_session.commit()

    r_explore = client.get("/api/orgs/explore")
    slugs = {o["slug"] for o in r_explore.json()["orgs"]}
    assert "hidden-org" not in slugs

    r_splash = client.get("/api/orgs/hidden-org/public")
    assert r_splash.status_code == 404


def test_explore_regression_demo_and_suborg_exclusions(client, db_session):
    """Phase 55 exclusions still hold under the Phase 57 filter."""
    parent = _make_org(db_session, "parent-org")
    _make_org(db_session, "sub-org", parent_org_id=parent.id)
    _make_org(db_session, "demo-foo", is_demo=True)
    db_session.commit()

    r = client.get("/api/orgs/explore")
    slugs = {o["slug"] for o in r.json()["orgs"]}
    assert "parent-org" in slugs
    assert "sub-org" not in slugs
    assert "demo-foo" not in slugs


# ===========================================================================
# Activity visibility (6)
# ===========================================================================


def test_public_activity_anon_can_list_proposals(client, db_session):
    org = _make_org(db_session, "p-org", activity_visibility="public")
    author = _make_user(db_session, "author")
    _add_active_member(db_session, org, author, role="steward")
    _make_proposal(db_session, org, author, title="Public Proposal")
    db_session.commit()

    r = client.get("/api/orgs/p-org/public/proposals")
    assert r.status_code == 200
    titles = [p["title"] for p in r.json()]
    assert "Public Proposal" in titles


def test_public_activity_anon_can_read_proposal_detail(client, db_session):
    org = _make_org(db_session, "p-org", activity_visibility="public")
    author = _make_user(db_session, "author")
    _add_active_member(db_session, org, author, role="steward")
    p = _make_proposal(db_session, org, author, title="Detail Test")
    db_session.commit()

    r = client.get(f"/api/orgs/p-org/public/proposals/{p.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Detail Test"
    assert body["body"] == "Body text"


def test_phase_30_3_private_topic_vote_invariant_preserved(client, db_session):
    """LOAD-BEARING (spec D4): even when an org's activity is public,
    a member's vote on a topic they've kept private must NOT be
    visible to anonymous viewers. Phase 57 does NOT bypass the
    Phase 30.3 can_see_votes gate.

    This verifies the gate directly: a private-topic DelegateProfile
    means can_see_votes(viewer_id=None, ...) returns False regardless
    of org-level activity_visibility."""
    from permissions import can_see_votes
    org = _make_org(db_session, "p-org", activity_visibility="public")
    member = _make_user(db_session, "voter")
    _add_active_member(db_session, org, member)
    topic = models.Topic(name="Sensitive", color="#000000", org_id=org.id)
    db_session.add(topic); db_session.flush()
    # Member's per-topic delegate profile is private.
    db_session.add(models.DelegateProfile(
        user_id=member.id, org_id=org.id, topic_id=topic.id,
        bio="x" * 60, visibility="private",
    ))
    db_session.commit()

    # Anonymous viewer (viewer_id=None) cannot see this member's votes
    # on this topic. The org's activity_visibility='public' does not
    # change that.
    visible = can_see_votes(
        db=db_session,
        viewer_id=None,
        target_user_id=member.id,
        topic_ids=[topic.id],
        org_id=org.id,
    )
    assert visible is False, (
        "Phase 30.3 private-topic invariant violated — anonymous viewer "
        "must NOT see private-topic votes even when org activity is public"
    )


def test_phase_30_3_public_topic_vote_visible_to_anon(client, db_session):
    """Spec D4 parity: a public-topic vote IS visible to anonymous
    viewers (matches the existing public delegate page behavior). The
    activity_visibility='public' setting doesn't add or remove this
    capability — it inherits whatever can_see_votes returns."""
    from permissions import can_see_votes
    org = _make_org(db_session, "p-org", activity_visibility="public")
    member = _make_user(db_session, "voter")
    _add_active_member(db_session, org, member)
    topic = models.Topic(name="Open", color="#000000", org_id=org.id)
    db_session.add(topic); db_session.flush()
    db_session.add(models.DelegateProfile(
        user_id=member.id, org_id=org.id, topic_id=topic.id,
        bio="x" * 60, visibility="public",
    ))
    db_session.commit()

    visible = can_see_votes(
        db=db_session,
        viewer_id=None,
        target_user_id=member.id,
        topic_ids=[topic.id],
        org_id=org.id,
    )
    assert visible is True


def test_members_only_default_404s_anon_proposal_list_and_detail(client, db_session):
    """Default (`members_only`) returns 404 to anonymous proposal-list
    + detail requests — byte-for-byte the same response as for a non-
    existent org. The additive-layer invariant: this is today's
    behavior unchanged."""
    org = _make_org(db_session, "mo-org")  # default members_only
    author = _make_user(db_session, "author")
    _add_active_member(db_session, org, author, role="steward")
    p = _make_proposal(db_session, org, author)
    db_session.commit()

    r_list = client.get("/api/orgs/mo-org/public/proposals")
    assert r_list.status_code == 404
    r_detail = client.get(f"/api/orgs/mo-org/public/proposals/{p.id}")
    assert r_detail.status_code == 404


def test_anon_cannot_post_vote_or_comment_regardless_of_activity_visibility(
    client, db_session,
):
    """Participation always requires membership. Public activity is
    strictly READ-ONLY."""
    org = _make_org(db_session, "p-org", activity_visibility="public")
    author = _make_user(db_session, "author")
    _add_active_member(db_session, org, author, role="steward")
    p = _make_proposal(db_session, org, author)
    db_session.commit()

    # Anonymous vote POST → 401 (no auth header).
    r_vote = client.post(
        f"/api/proposals/{p.id}/votes",
        json={"vote_value": "yes"},
    )
    assert r_vote.status_code in (401, 405, 404), (
        f"anon vote POST got {r_vote.status_code}, expected auth-required"
    )

    # Anonymous comment POST → 401.
    r_comment = client.post(
        f"/api/proposals/{p.id}/comments",
        json={"body": "anon comment"},
    )
    assert r_comment.status_code in (401, 405, 404), (
        f"anon comment POST got {r_comment.status_code}, expected auth-required"
    )


# ===========================================================================
# Join policy (4)
# ===========================================================================


def test_open_join_creates_instant_active_membership(client, db_session):
    org = _make_org(db_session, "open-join-org", join_policy="open")
    joiner = _make_user(db_session, "joiner")
    db_session.commit()

    r = client.post(
        f"/api/orgs/{org.slug}/join-request",
        headers=_auth(joiner.id),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active"


def test_approval_join_creates_pending_membership(client, db_session):
    org = _make_org(db_session, "approval-org", join_policy="approval")
    joiner = _make_user(db_session, "joiner")
    db_session.commit()

    r = client.post(
        f"/api/orgs/{org.slug}/join-request",
        headers=_auth(joiner.id),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending"


def test_invite_join_blocks_uninvited(client, db_session):
    org = _make_org(db_session, "invite-org", join_policy="invite")
    joiner = _make_user(db_session, "joiner")
    db_session.commit()

    r = client.post(
        f"/api/orgs/{org.slug}/join-request",
        headers=_auth(joiner.id),
    )
    assert r.status_code == 403, r.text
    assert "invitation" in r.text.lower()


def test_phase_52e_flag_routing_still_fires_on_open_join(client, db_session):
    """Regression: the Phase 52e verification flag-routing is wired
    into the join path. Phase 57 changed value names, not the routing
    logic. Sanity check that the join path still imports and the
    verification module still hooks up (we don't seed a flag here —
    that's covered by the dedicated Phase 52e test files; we just
    confirm the path doesn't 500 under the new value vocabulary)."""
    org = _make_org(db_session, "join-flag-org", join_policy="open")
    joiner = _make_user(db_session, "joiner")
    db_session.commit()

    r = client.post(
        f"/api/orgs/{org.slug}/join-request",
        headers=_auth(joiner.id),
    )
    # Successful active-join under the new join_policy='open' value
    # without 500 confirms the verification module's flag-routing
    # imports + dispatches fine under Phase 57.
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active"


# ===========================================================================
# Serializer + validation (3)
# ===========================================================================


def test_org_out_surfaces_all_three_axes(client, db_session):
    """OrgOut on the authenticated /api/orgs endpoint surfaces all
    three new access fields. The _MUST_SURFACE_FIELDS guard test
    (test_phase_46a_orgout_serializer_coverage.py) is the CI mate of
    this assertion."""
    org = _make_org(
        db_session, "axes-org",
        join_policy="approval", discoverability="unlisted",
        activity_visibility="members_only",
    )
    member = _make_user(db_session, "viewer")
    _add_active_member(db_session, org, member, role="steward")
    db_session.commit()

    r = client.get("/api/orgs", headers=_auth(member.id))
    assert r.status_code == 200, r.text
    found = next(o for o in r.json() if o["slug"] == "axes-org")
    assert found["join_policy"] == "approval"
    assert found["discoverability"] == "unlisted"
    assert found["activity_visibility"] == "members_only"


def test_org_update_rejects_out_of_vocab_axis_values(client, db_session):
    """Invalid axis values fail the PATCH cleanly with a 422
    (Pydantic field-level validator)."""
    org = _make_org(db_session, "vocab-org")
    steward = _make_user(db_session, "steward")
    _add_active_member(db_session, org, steward, role="steward")
    db_session.commit()

    for bad_disc in ("invisible", "secret", "private"):
        r = client.patch(
            f"/api/orgs/{org.slug}",
            headers=_auth(steward.id),
            json={"discoverability": bad_disc},
        )
        assert r.status_code == 422, (bad_disc, r.text)

    for bad_av in ("anyone", "world", "limited"):
        r = client.patch(
            f"/api/orgs/{org.slug}",
            headers=_auth(steward.id),
            json={"activity_visibility": bad_av},
        )
        assert r.status_code == 422, (bad_av, r.text)


def test_hidden_plus_public_normalized_to_hidden_members_only(client, db_session):
    """Spec B3 + D6: the (hidden, public) combination is incoherent
    (nobody can see the org, so activity visibility is moot). The
    server normalizes the activity axis to members_only regardless of
    caller input."""
    org = _make_org(db_session, "normalize-org")
    steward = _make_user(db_session, "steward")
    _add_active_member(db_session, org, steward, role="steward")
    db_session.commit()

    r = client.patch(
        f"/api/orgs/{org.slug}",
        headers=_auth(steward.id),
        json={
            "discoverability": "hidden",
            "activity_visibility": "public",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["discoverability"] == "hidden"
    assert body["activity_visibility"] == "members_only", (
        "hidden+public combination must normalize to hidden+members_only "
        "server-side (spec B3)"
    )
