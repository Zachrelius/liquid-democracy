"""Phase 65 — org delegation controls (disallow delegation per-topic or
org-wide).

Two independent levers:
  * Org-wide master switch — ``Organization.settings['delegation']['enabled']``
    (read-time default True; absent/invalid ⇒ enabled).
  * Per-topic flag — ``Topic.allow_delegation`` Boolean column (NOT NULL,
    default + server_default true).

Enforcement is two-layer:
  * Resolution layer (load-bearing) — ``DelegationService._build_context``
    builds an EMPTY delegation map when the proposal is gated, so no
    delegated ballot ever resolves (direct ballots only; everyone else
    not_cast). Side-effect tests below assert tally numbers, not status
    codes (CLAUDE.md testing convention).
  * Creation layer (UX) — the three delegation write paths reject new
    writes (403) when gated; intent activation SKIPS (not errors) inert
    intents.

Locked decisions covered: D1 (mixed-topic ⇒ whole proposal gated, even
global delegations), D2 (existing rows kept inert, reversible), D3
(storage), D4 (untagged proposals only affected by the org switch).

Style mirrors test_phase_18_delegation_org_scoping.py: in-memory SQLite,
real models.Vote rows with production storage shape, real OrgMembership
rows so compute_tally's eligibility path is exercised faithfully.
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
from database import Base, get_db
from delegation_engine import engine as delegation_engine_singleton
from delegation_engine import graph_store as global_graph_store
from main import app
from org_config import delegation_enabled_for_org, proposal_is_delegation_gated
from role_seed import seed_default_roles_for_org
from routes.delegations import activate_intents_for_follow
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
def fresh_graph_store():
    global_graph_store._graphs = {}
    yield global_graph_store
    global_graph_store._graphs = {}


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


def _make_org(
    db: Session, slug: str, *, settings: Optional[dict] = None,
) -> models.Organization:
    o = models.Organization(
        name=slug.replace("_", " ").title(),
        slug=slug,
        description="",
        settings=settings if settings is not None else {},
    )
    db.add(o)
    db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _make_topic(
    db: Session, org: models.Organization, name: str = "T", *,
    allow_delegation: bool = True,
) -> models.Topic:
    t = models.Topic(
        name=name, color="#000000", org_id=org.id,
        allow_delegation=allow_delegation,
    )
    db.add(t)
    db.flush()
    return t


def _make_proposal(
    db: Session,
    author: models.User,
    org: models.Organization,
    *,
    status: str = "voting",
    topics: Optional[list[models.Topic]] = None,
) -> models.Proposal:
    p = models.Proposal(
        title="P",
        body="",
        author_id=author.id,
        voting_method="binary",
        status=status,
        org_id=org.id,
        voting_start=datetime.now(timezone.utc).replace(tzinfo=None)
        - timedelta(days=1),
        voting_end=datetime.now(timezone.utc).replace(tzinfo=None)
        + timedelta(days=1),
    )
    db.add(p)
    db.flush()
    for topic in topics or []:
        db.add(models.ProposalTopic(
            proposal_id=p.id, topic_id=topic.id, relevance=1.0,
        ))
    db.flush()
    return p


def _make_delegation(
    db: Session,
    delegator: models.User,
    delegate: models.User,
    *,
    org_id: str,
    topic_id: Optional[str] = None,
) -> models.Delegation:
    d = models.Delegation(
        delegator_id=delegator.id,
        delegate_id=delegate.id,
        org_id=org_id,
        topic_id=topic_id,
        chain_behavior="accept_sub",
    )
    db.add(d)
    db.flush()
    return d


def _vote_yes(db: Session, proposal: models.Proposal, user: models.User) -> None:
    db.add(models.Vote(
        proposal_id=proposal.id,
        user_id=user.id,
        vote_value="yes",
        is_direct=True,
        cast_by_id=user.id,
    ))
    db.flush()


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _standard_org(test_db, slug: str, *, org_settings: Optional[dict] = None):
    """Org with three members: author z, delegator a, delegate b."""
    org = _make_org(test_db, slug, settings=org_settings)
    z = _make_user(test_db, f"{slug}_z")
    a = _make_user(test_db, f"{slug}_a")
    b = _make_user(test_db, f"{slug}_b")
    for u in (z, a, b):
        make_org_membership(test_db, org_id=org.id, user_id=u.id, role="member")
    return org, z, a, b


# ===========================================================================
# Resolver unit coverage
# ===========================================================================


def test_delegation_enabled_resolver_read_time_defaults(test_db):
    """Absent key / non-dict section / non-bool value / org=None ⇒ True."""
    assert delegation_enabled_for_org(None) is True

    org = _make_org(test_db, "res_defaults")
    assert delegation_enabled_for_org(org) is True

    org.settings = {"delegation": "off"}  # invalid shape
    assert delegation_enabled_for_org(org) is True

    org.settings = {"delegation": {"enabled": "nope"}}  # invalid value
    assert delegation_enabled_for_org(org) is True

    org.settings = {"delegation": {}}  # key absent inside section
    assert delegation_enabled_for_org(org) is True

    org.settings = {"delegation": {"enabled": False}}
    assert delegation_enabled_for_org(org) is False

    org.settings = {"delegation": {"enabled": True}}
    assert delegation_enabled_for_org(org) is True


def test_gating_predicate_shapes(test_db):
    org = _make_org(test_db, "pred_org")
    t_ok = _make_topic(test_db, org, "ok")
    t_off = _make_topic(test_db, org, "off", allow_delegation=False)
    z = _make_user(test_db, "pred_z")
    p = _make_proposal(test_db, z, org, topics=[t_ok])

    # Org on + unflagged topic ⇒ not gated.
    assert proposal_is_delegation_gated(p, org, [t_ok]) is False
    # Any flagged topic gates (D1).
    assert proposal_is_delegation_gated(p, org, [t_ok, t_off]) is True
    # Untagged: only the org switch matters (D4).
    assert proposal_is_delegation_gated(p, org, []) is False
    org.settings = {"delegation": {"enabled": False}}
    assert proposal_is_delegation_gated(p, org, []) is True


# ===========================================================================
# Resolution layer — side-effect tally tests (the load-bearing half)
# ===========================================================================


def test_topic_flag_gates_tally_and_unflag_restores(test_db, fresh_graph_store):
    """A→B delegation on a flagged topic; proposal tagged with it; B votes
    yes. Gated: A lands not_cast and B's weight is 1 (NOT 2). Unflag the
    topic; recompute; A's delegated ballot resolves again (weight 2)."""
    org, z, a, b = _standard_org(test_db, "tflag")
    topic = _make_topic(test_db, org, "budget", allow_delegation=False)
    _make_delegation(test_db, a, b, org_id=org.id, topic_id=topic.id)
    p = _make_proposal(test_db, z, org, topics=[topic])
    _vote_yes(test_db, p, b)
    test_db.commit()

    tally = delegation_engine_singleton.compute_tally(p, test_db)
    assert tally.yes == 1, f"delegated ballot resolved while gated: {tally}"
    assert tally.not_cast == 2  # a (inert delegation) + z
    assert tally.total_eligible == 3

    # D2 — the delegation row is KEPT, just inert.
    assert test_db.query(models.Delegation).filter(
        models.Delegation.delegator_id == a.id,
    ).count() == 1

    # Reversibility: unflag → A's delegated ballot resolves again.
    topic.allow_delegation = True
    test_db.commit()
    tally2 = delegation_engine_singleton.compute_tally(p, test_db)
    assert tally2.yes == 2, f"unflag did not restore delegation: {tally2}"
    assert tally2.not_cast == 1  # only z


def test_org_switch_gates_tally_and_restore(test_db, fresh_graph_store):
    """Same pair for the org master switch (topic NOT flagged)."""
    org, z, a, b = _standard_org(
        test_db, "oswitch",
        org_settings={"delegation": {"enabled": False}},
    )
    topic = _make_topic(test_db, org, "ops")  # allow_delegation=True
    _make_delegation(test_db, a, b, org_id=org.id, topic_id=topic.id)
    p = _make_proposal(test_db, z, org, topics=[topic])
    _vote_yes(test_db, p, b)
    test_db.commit()

    tally = delegation_engine_singleton.compute_tally(p, test_db)
    assert tally.yes == 1, f"org switch off but delegation resolved: {tally}"
    assert tally.not_cast == 2

    # Flip the switch back on → delegation resolves again.
    org.settings = {"delegation": {"enabled": True}}
    test_db.commit()
    tally2 = delegation_engine_singleton.compute_tally(p, test_db)
    assert tally2.yes == 2, f"switch back on did not restore: {tally2}"


def test_mixed_topic_fully_gated_even_global_delegation(test_db, fresh_graph_store):
    """D1 — proposal tagged [flagged, unflagged] is FULLY gated: even a
    global (topic-less) delegation must not resolve."""
    org, z, a, b = _standard_org(test_db, "mixed")
    t_off = _make_topic(test_db, org, "elections", allow_delegation=False)
    t_ok = _make_topic(test_db, org, "general")
    _make_delegation(test_db, a, b, org_id=org.id, topic_id=None)  # global
    p = _make_proposal(test_db, z, org, topics=[t_off, t_ok])
    _vote_yes(test_db, p, b)
    test_db.commit()

    tally = delegation_engine_singleton.compute_tally(p, test_db)
    assert tally.yes == 1, (
        f"global delegation leaked through mixed-topic gating: {tally}"
    )
    assert tally.not_cast == 2


def test_untagged_proposal_not_gated_by_topic_flag(test_db, fresh_graph_store):
    """D4 — a flagged topic elsewhere in the org does NOT gate an
    untagged proposal; global delegation resolves normally."""
    org, z, a, b = _standard_org(test_db, "untag")
    _make_topic(test_db, org, "flagged-elsewhere", allow_delegation=False)
    _make_delegation(test_db, a, b, org_id=org.id, topic_id=None)
    p = _make_proposal(test_db, z, org, topics=[])
    _vote_yes(test_db, p, b)
    test_db.commit()

    tally = delegation_engine_singleton.compute_tally(p, test_db)
    assert tally.yes == 2, f"untagged proposal wrongly gated: {tally}"
    assert tally.not_cast == 1


def test_untagged_proposal_gated_by_org_switch(test_db, fresh_graph_store):
    """D4 second half — untagged + org switch off ⇒ gated."""
    org, z, a, b = _standard_org(
        test_db, "untagoff",
        org_settings={"delegation": {"enabled": False}},
    )
    _make_delegation(test_db, a, b, org_id=org.id, topic_id=None)
    p = _make_proposal(test_db, z, org, topics=[])
    _vote_yes(test_db, p, b)
    test_db.commit()

    tally = delegation_engine_singleton.compute_tally(p, test_db)
    assert tally.yes == 1, f"org-off untagged proposal not gated: {tally}"
    assert tally.not_cast == 2


def test_additive_layer_defaults_unchanged(test_db, fresh_graph_store):
    """With defaults (switch on / absent, no topic flagged) an existing
    delegation tally is unchanged — the additive-layer invariant."""
    org, z, a, b = _standard_org(test_db, "addlayer")
    topic = _make_topic(test_db, org, "roads")
    _make_delegation(test_db, a, b, org_id=org.id, topic_id=topic.id)
    p = _make_proposal(test_db, z, org, topics=[topic])
    _vote_yes(test_db, p, b)
    test_db.commit()

    tally = delegation_engine_singleton.compute_tally(p, test_db)
    assert tally.yes == 2
    assert tally.not_cast == 1
    assert tally.total_eligible == 3


def test_resolve_vote_not_resolved_while_gated(test_db, fresh_graph_store):
    """resolve_vote (single-user path) goes through the same chokepoint:
    A's vote does not resolve to B's ballot while the topic is flagged."""
    org, z, a, b = _standard_org(test_db, "rvgate")
    topic = _make_topic(test_db, org, "bylaws", allow_delegation=False)
    _make_delegation(test_db, a, b, org_id=org.id, topic_id=topic.id)
    p = _make_proposal(test_db, z, org, topics=[topic])
    _vote_yes(test_db, p, b)
    test_db.commit()

    result = delegation_engine_singleton.resolve_vote(a.id, p.id, test_db)
    assert result is None or getattr(result, "vote_value", None) is None, (
        f"resolve_vote resolved a delegated ballot while gated: {result}"
    )

    topic.allow_delegation = True
    test_db.commit()
    result2 = delegation_engine_singleton.resolve_vote(a.id, p.id, test_db)
    assert result2 is not None and result2.vote_value == "yes"


# ===========================================================================
# Creation layer — write-path 403s + intent-activation skip
# ===========================================================================


def test_upsert_403_on_flagged_topic(client, test_db, fresh_graph_store):
    org, z, a, b = _standard_org(test_db, "wflag")
    topic = _make_topic(test_db, org, "budget", allow_delegation=False)
    test_db.commit()

    resp = client.put(
        f"/api/orgs/{org.slug}/delegations",
        json={"delegate_id": b.id, "topic_id": topic.id,
              "chain_behavior": "accept_sub"},
        headers=_auth(a),
    )
    assert resp.status_code == 403, resp.text
    assert "does not allow delegation" in resp.json()["detail"]
    assert test_db.query(models.Delegation).count() == 0


def test_upsert_403_when_org_switch_off(client, test_db, fresh_graph_store):
    """Org switch off rejects ALL delegation writes — including global
    (topic-less) ones."""
    org, z, a, b = _standard_org(
        test_db, "woff", org_settings={"delegation": {"enabled": False}},
    )
    test_db.commit()

    resp = client.put(
        f"/api/orgs/{org.slug}/delegations",
        json={"delegate_id": b.id, "topic_id": None,
              "chain_behavior": "accept_sub"},
        headers=_auth(a),
    )
    assert resp.status_code == 403, resp.text
    assert "turned off" in resp.json()["detail"]
    assert test_db.query(models.Delegation).count() == 0


def test_request_403_on_flagged_topic(client, test_db, fresh_graph_store):
    org, z, a, b = _standard_org(test_db, "rflag")
    topic = _make_topic(test_db, org, "budget", allow_delegation=False)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/delegations/request",
        json={"delegate_id": b.id, "topic_id": topic.id,
              "chain_behavior": "accept_sub"},
        headers=_auth(a),
    )
    assert resp.status_code == 403, resp.text
    assert "does not allow delegation" in resp.json()["detail"]
    assert test_db.query(models.Delegation).count() == 0
    assert test_db.query(models.DelegationIntent).count() == 0


def test_request_403_when_org_switch_off(client, test_db, fresh_graph_store):
    org, z, a, b = _standard_org(
        test_db, "roff", org_settings={"delegation": {"enabled": False}},
    )
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/delegations/request",
        json={"delegate_id": b.id, "topic_id": None,
              "chain_behavior": "accept_sub"},
        headers=_auth(a),
    )
    assert resp.status_code == 403, resp.text
    assert "turned off" in resp.json()["detail"]
    assert test_db.query(models.Delegation).count() == 0
    assert test_db.query(models.DelegationIntent).count() == 0


def _make_pending_intent(
    test_db, org, follower, followed, *, topic_id: Optional[str],
) -> models.DelegationIntent:
    freq = models.FollowRequest(
        requester_id=follower.id,
        target_id=followed.id,
        org_id=org.id,
        status="pending",
        permission_level="delegation_allowed",
    )
    test_db.add(freq)
    test_db.flush()
    intent = models.DelegationIntent(
        delegator_id=follower.id,
        delegate_id=followed.id,
        org_id=org.id,
        topic_id=topic_id,
        chain_behavior="accept_sub",
        follow_request_id=freq.id,
        status="pending",
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None)
        + timedelta(days=30),
    )
    test_db.add(intent)
    test_db.flush()
    return intent


def test_intent_activation_skips_flagged_topic_intent(test_db, fresh_graph_store):
    """Intent on a flagged topic is SKIPPED (stays pending, no error,
    no Delegation row); after unflagging the same call activates it."""
    org, z, a, b = _standard_org(test_db, "iflag")
    topic = _make_topic(test_db, org, "budget", allow_delegation=False)
    intent = _make_pending_intent(test_db, org, a, b, topic_id=topic.id)
    test_db.commit()

    activated = activate_intents_for_follow(test_db, a.id, b.id, org_id=org.id)
    assert activated == []
    test_db.refresh(intent)
    assert intent.status == "pending"
    assert test_db.query(models.Delegation).count() == 0

    # Unflag → the intent becomes activatable again (D2 reversibility).
    topic.allow_delegation = True
    test_db.commit()
    activated2 = activate_intents_for_follow(test_db, a.id, b.id, org_id=org.id)
    assert activated2 == [intent.id]
    test_db.refresh(intent)
    assert intent.status == "activated"
    assert test_db.query(models.Delegation).count() == 1


def test_intent_activation_skips_when_org_switch_off(test_db, fresh_graph_store):
    org, z, a, b = _standard_org(
        test_db, "ioff", org_settings={"delegation": {"enabled": False}},
    )
    intent = _make_pending_intent(test_db, org, a, b, topic_id=None)
    test_db.commit()

    activated = activate_intents_for_follow(test_db, a.id, b.id, org_id=org.id)
    assert activated == []
    test_db.refresh(intent)
    assert intent.status == "pending"
    assert test_db.query(models.Delegation).count() == 0


# ===========================================================================
# Surfacing — proposal response + topic admin write path + org settings
# ===========================================================================


def test_delegation_gated_surfaced_on_proposal_response(
    client, test_db, fresh_graph_store,
):
    org, z, a, b = _standard_org(test_db, "surf")
    topic = _make_topic(test_db, org, "budget")
    p = _make_proposal(test_db, z, org, topics=[topic])
    test_db.commit()

    resp = client.get(
        f"/api/orgs/{org.slug}/proposals/{p.id}", headers=_auth(a),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["delegation_gated"] is False

    topic.allow_delegation = False
    test_db.commit()
    resp2 = client.get(
        f"/api/orgs/{org.slug}/proposals/{p.id}", headers=_auth(a),
    )
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["delegation_gated"] is True

    # Org switch variant.
    topic.allow_delegation = True
    org.settings = {"delegation": {"enabled": False}}
    test_db.commit()
    resp3 = client.get(
        f"/api/orgs/{org.slug}/proposals/{p.id}", headers=_auth(a),
    )
    assert resp3.status_code == 200, resp3.text
    assert resp3.json()["delegation_gated"] is True


def test_topic_admin_create_and_patch_allow_delegation(
    client, test_db, fresh_graph_store,
):
    """allow_delegation is creatable + updatable through the org topic
    admin routes and surfaced on TopicOut."""
    org = _make_org(test_db, "tadmin")
    admin = _make_user(test_db, "tadmin_admin")
    make_org_membership(test_db, org_id=org.id, user_id=admin.id, role="admin")
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/topics",
        json={"name": "Budget", "color": "#112233",
              "allow_delegation": False},
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["allow_delegation"] is False
    topic_id = body["id"]

    row = test_db.get(models.Topic, topic_id)
    assert row.allow_delegation is False

    # PATCH flips it back on.
    resp2 = client.patch(
        f"/api/orgs/{org.slug}/topics/{topic_id}",
        json={"name": "Budget", "color": "#112233",
              "allow_delegation": True},
        headers=_auth(admin),
    )
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["allow_delegation"] is True
    test_db.refresh(row)
    assert row.allow_delegation is True

    # Omitting the field on create defaults to True (today's behavior).
    resp3 = client.post(
        f"/api/orgs/{org.slug}/topics",
        json={"name": "General", "color": "#112233"},
        headers=_auth(admin),
    )
    assert resp3.status_code == 201, resp3.text
    assert resp3.json()["allow_delegation"] is True

    # Listing surfaces the flag too.
    resp4 = client.get(f"/api/orgs/{org.slug}/topics", headers=_auth(admin))
    assert resp4.status_code == 200
    flags = {t["name"]: t["allow_delegation"] for t in resp4.json()}
    assert flags == {"Budget": True, "General": True}


def test_org_settings_patch_delegation_switch(client, test_db, fresh_graph_store):
    """The nested delegation.enabled key lands through the existing org
    settings merge; invalid shapes 400 cleanly pre-merge."""
    org = _make_org(test_db, "spatch")
    admin = _make_user(test_db, "spatch_admin")
    make_org_membership(test_db, org_id=org.id, user_id=admin.id, role="admin")
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/{org.slug}",
        json={"settings": {"delegation": {"enabled": False}}},
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["settings"]["delegation"] == {"enabled": False}
    test_db.refresh(org)
    assert org.settings["delegation"] == {"enabled": False}
    assert delegation_enabled_for_org(org) is False

    # Flip back on.
    resp2 = client.patch(
        f"/api/orgs/{org.slug}",
        json={"settings": {"delegation": {"enabled": True}}},
        headers=_auth(admin),
    )
    assert resp2.status_code == 200, resp2.text
    test_db.refresh(org)
    assert delegation_enabled_for_org(org) is True

    # Invalid shapes fail the whole PATCH cleanly.
    resp3 = client.patch(
        f"/api/orgs/{org.slug}",
        json={"settings": {"delegation": "off"}},
        headers=_auth(admin),
    )
    assert resp3.status_code == 400

    resp4 = client.patch(
        f"/api/orgs/{org.slug}",
        json={"settings": {"delegation": {"enabled": "nope"}}},
        headers=_auth(admin),
    )
    assert resp4.status_code == 400
    test_db.refresh(org)
    assert delegation_enabled_for_org(org) is True  # unchanged


# ===========================================================================
# Parity — existing rows / orgs behave as if the feature never landed
# ===========================================================================


def test_existing_and_new_topic_parity_on_allow_delegation(test_db):
    """ORM-constructed topics (existing-code paths that don't know about
    the new column) default to allow_delegation=True — the per-row half
    of the existing-vs-new parity assertion. The post-upgrade SQL-layer
    half (server_default backfills pre-existing rows) is asserted in
    test_phase_65_migration_cycle.py."""
    org = _make_org(test_db, "parity")
    t = models.Topic(name="Legacy-Style", color="#000000", org_id=org.id)
    test_db.add(t)
    test_db.commit()
    test_db.refresh(t)
    assert t.allow_delegation is True

    # And an org created with empty settings (pre-65 shape) resolves
    # the master switch to enabled — read-time default, no backfill key.
    assert "delegation" not in (org.settings or {})
    assert delegation_enabled_for_org(org) is True
