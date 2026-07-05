"""Phase 89 — Delegated Budget Voting.

Lifts the Phase 73 §5 direct-vote-only restriction: budget_allocation and
budget_project tallies now resolve delegation per user via resolve_vote_pure,
exactly like approval/RCV. A delegator's resolved budget ballot IS their
delegate's budget ballot (copied whole).

Matrix (spec: phase89_delegated_budget_voting_spec.md §6):
  * Delegation resolution shifts the allocation median / project priority.
  * Chain behavior: accept_sub one hop resolves; revert_direct / abstain with a
    non-voting delegate → delegator not_cast.
  * Phase 65 gates: org master switch off, or a topic with allow_delegation
    False → budget delegation inert (direct ballots only).
  * Relevance-weighted strategy: highest-relevance delegate's budget ballot used
    whole; no blending.
  * Quorum: delegated ballots count toward total_ballots_cast (status flips).
  * Cycle guard: A→B→A delegation doesn't infinite-loop.
  * Notification: a delegate's budget vote emits delegate.voted to delegators.
  * Eligibility: a non-eligible delegate's ballot never leaks into resolution.
  * my-vote reflects a delegated budget ballot (is_direct False, cast_by set).
  * _format_vote_value_for_payload budget shapes (unit).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import delegation_engine
import models
from database import Base, get_db
from main import app
from role_seed import seed_default_roles_for_org
from tests.conftest import make_org_membership

_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


# ===========================================================================
# Fixtures + helpers
# ===========================================================================

@pytest.fixture(scope="function")
def test_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
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


def _auth(user):
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _user(db, username, *, is_admin=False):
    u = models.User(
        username=username, display_name=username, password_hash=_DUMMY_HASH,
        email=f"{username}@t.ex", email_verified=True, is_admin=is_admin,
    )
    db.add(u)
    db.flush()
    return u


def _org(db, slug="budget-org", *, settings=None):
    base = {
        "default_voting_days": 7,
        "allowed_voting_methods": [
            "binary", "approval", "budget_allocation", "budget_project",
        ],
    }
    if settings:
        base.update(settings)
    o = models.Organization(name=slug.title(), slug=slug, description="", settings=base)
    db.add(o)
    db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _topic(db, org, name="Budget", *, allow_delegation=True):
    t = models.Topic(name=name, color="#000000", org_id=org.id,
                     allow_delegation=allow_delegation)
    db.add(t)
    db.flush()
    return t


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _alloc_proposal(db, author, org, *, topic=None, quorum=0.4, envelope=100000,
                    labels=("A", "B")):
    p = models.Proposal(
        title="Alloc", body="", author_id=author.id, org_id=org.id,
        voting_method="budget_allocation", num_winners=1, status="voting",
        voting_start=_now(), voting_end=_now() + timedelta(days=7),
        quorum_threshold=quorum, pass_threshold=0.5,
        budget_config={"mode": "allocation", "envelope": envelope,
                       "currency": "USD", "aggregation": "median"},
    )
    db.add(p)
    db.flush()
    opts = []
    for i, label in enumerate(labels):
        o = models.ProposalOption(proposal_id=p.id, label=label, description="",
                                  display_order=i)
        db.add(o)
        opts.append(o)
    db.flush()
    if topic is not None:
        db.add(models.ProposalTopic(proposal_id=p.id, topic_id=topic.id, relevance=1.0))
        db.flush()
    return p, opts


def _project_proposal(db, author, org, *, topic=None, quorum=0.4, envelope=100000,
                      items=(("A", 60000), ("B", 60000))):
    p = models.Proposal(
        title="Project", body="", author_id=author.id, org_id=org.id,
        voting_method="budget_project", num_winners=1, status="voting",
        voting_start=_now(), voting_end=_now() + timedelta(days=7),
        quorum_threshold=quorum, pass_threshold=0.5,
        budget_config={"mode": "project", "envelope": envelope, "currency": "USD",
                       "min_spend": 0, "max_spend": envelope},
    )
    db.add(p)
    db.flush()
    opts = []
    for i, (label, floor) in enumerate(items):
        o = models.ProposalOption(proposal_id=p.id, label=label, description="",
                                  display_order=i, budget_floor_amount=floor)
        db.add(o)
        opts.append(o)
    db.flush()
    if topic is not None:
        db.add(models.ProposalTopic(proposal_id=p.id, topic_id=topic.id, relevance=1.0))
        db.flush()
    return p, opts


def _deleg(db, delegator, delegate, org, *, topic=None, chain="revert_direct"):
    d = models.Delegation(
        delegator_id=delegator.id, delegate_id=delegate.id, org_id=org.id,
        topic_id=topic.id if topic else None, chain_behavior=chain,
    )
    db.add(d)
    db.flush()
    return d


def _members(db, org, n):
    users = []
    for i in range(n):
        u = _user(db, f"{org.slug}-u{i}")
        make_org_membership(db, org_id=org.id, user_id=u.id, role="member")
        users.append(u)
    return users


def _author(db, org):
    a = _user(db, f"{org.slug}-author")
    make_org_membership(db, org_id=org.id, user_id=a.id, role="steward")
    return a


def _ranked(*oids):
    return {"ranked": [{"option_id": o} for o in oids]}


# ===========================================================================
# Delegation resolution shifts the tally
# ===========================================================================

def test_allocation_topic_delegation_shifts_median(client, test_db):
    """A topic delegation carries the delegate's allocation into the tally,
    shifting the per-bucket median. v1 all-A, v3 all-B: two ballots split 50/50;
    v2 delegating to v1 makes A the majority → A gets the whole envelope."""
    org = _org(test_db)
    author = _author(test_db, org)
    v1, v2, v3 = _members(test_db, org, 3)
    topic = _topic(test_db, org)
    p, opts = _alloc_proposal(test_db, author, org, topic=topic)
    a, b = opts[0].id, opts[1].id
    _deleg(test_db, v2, v1, org, topic=topic)
    test_db.commit()

    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v1),
                json={"allocations": {a: 100000, b: 0}})
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v3),
                json={"allocations": {a: 0, b: 100000}})

    tally = delegation_engine.engine.compute_tally(p, test_db)
    # v1 direct + v2 delegated (copy of v1) + v3 direct = 3 resolved ballots.
    assert tally.total_ballots_cast == 3
    # A median over [100000, 100000, 0] = 100000; B median over [0, 0, 100000] = 0.
    assert tally.amounts[a] == 100000
    assert tally.amounts[b] == 0


def test_allocation_no_delegation_is_byte_identical(client, test_db):
    """Parity: with no delegation rows the same two direct ballots tally to the
    even-count midpoint split (delegation adds nothing)."""
    org = _org(test_db)
    author = _author(test_db, org)
    v1, v2, v3 = _members(test_db, org, 3)
    topic = _topic(test_db, org)
    p, opts = _alloc_proposal(test_db, author, org, topic=topic)
    a, b = opts[0].id, opts[1].id
    test_db.commit()

    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v1),
                json={"allocations": {a: 100000, b: 0}})
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v3),
                json={"allocations": {a: 0, b: 100000}})

    tally = delegation_engine.engine.compute_tally(p, test_db)
    assert tally.total_ballots_cast == 2
    # even count → midpoint median 50000 each → 50/50 split.
    assert tally.amounts[a] == 50000
    assert tally.amounts[b] == 50000


def test_project_topic_delegation_shifts_priority(client, test_db):
    """A topic delegation carries the delegate's project ranking, shifting the
    funding walk. Only one 60k item fits the 100k envelope; v2's delegation to
    v1 (ranks A) breaks the A-vs-B contest toward A."""
    org = _org(test_db)
    author = _author(test_db, org)
    v1, v2, v3 = _members(test_db, org, 3)
    topic = _topic(test_db, org)
    p, opts = _project_proposal(test_db, author, org, topic=topic)
    a, b = opts[0].id, opts[1].id
    _deleg(test_db, v2, v1, org, topic=topic)
    test_db.commit()

    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v1), json=_ranked(a))
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v3), json=_ranked(b))

    tally = delegation_engine.engine.compute_tally(p, test_db)
    assert tally.total_ballots_cast == 3
    # A ranked by v1 + v2 (delegated), B by v3 → A funds, B does not fit.
    funded_ids = [f["option_id"] for f in tally.funded]
    assert a in funded_ids
    assert b not in funded_ids


# ===========================================================================
# Chain behavior
# ===========================================================================

def test_accept_sub_one_hop_resolves(client, test_db):
    """v3 →(accept_sub) v2 →(revert_direct) v1. v2 is silent (no direct ballot)
    but its delegate v1 voted, so v2 resolves to v1; v3 accepts v2's sub-delegate
    v1 one hop. All three resolve to v1's ballot → 3 ballots counted, and v3's
    resolution is cast_by v1 (the accept_sub one-hop target)."""
    org = _org(test_db)
    author = _author(test_db, org)
    v1, v2, v3 = _members(test_db, org, 3)
    topic = _topic(test_db, org)
    p, opts = _alloc_proposal(test_db, author, org, topic=topic)
    a, b = opts[0].id, opts[1].id
    _deleg(test_db, v3, v2, org, topic=topic, chain="accept_sub")
    _deleg(test_db, v2, v1, org, topic=topic, chain="revert_direct")
    test_db.commit()

    # only v1 casts
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v1),
                json={"allocations": {a: 70000, b: 30000}})

    # v3 accept_sub resolves one hop to v1's ballot.
    v3_result = delegation_engine.engine.resolve_vote(v3.id, p.id, test_db)
    assert v3_result is not None
    assert v3_result.is_direct is False
    assert v3_result.cast_by_id == v1.id
    assert v3_result.ballot.allocations == {a: 70000, b: 30000}

    tally = delegation_engine.engine.compute_tally(p, test_db)
    # v1 direct + v2 (delegate voted) + v3 (accept_sub → v1) = 3.
    assert tally.total_ballots_cast == 3


def test_revert_direct_nonvoting_delegate_is_not_cast(client, test_db):
    """v2 →(revert_direct) v1; v1 never votes → v2 resolves to nothing."""
    org = _org(test_db)
    author = _author(test_db, org)
    v1, v2, v3 = _members(test_db, org, 3)
    topic = _topic(test_db, org)
    p, opts = _alloc_proposal(test_db, author, org, topic=topic)
    a, b = opts[0].id, opts[1].id
    _deleg(test_db, v2, v1, org, topic=topic, chain="revert_direct")
    test_db.commit()

    # only v3 casts directly; v1 (v2's delegate) stays silent.
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v3),
                json={"allocations": {a: 50000, b: 50000}})

    tally = delegation_engine.engine.compute_tally(p, test_db)
    assert tally.total_ballots_cast == 1  # only v3


# ===========================================================================
# Phase 65 gates
# ===========================================================================

def test_org_master_switch_off_inerts_budget_delegation(client, test_db):
    """Org delegation master switch off → budget delegation never resolves."""
    org = _org(test_db, settings={"delegation": {"enabled": False}})
    author = _author(test_db, org)
    v1, v2, v3 = _members(test_db, org, 3)
    topic = _topic(test_db, org)
    p, opts = _alloc_proposal(test_db, author, org, topic=topic)
    a, b = opts[0].id, opts[1].id
    _deleg(test_db, v2, v1, org, topic=topic)
    test_db.commit()

    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v1),
                json={"allocations": {a: 60000, b: 40000}})

    tally = delegation_engine.engine.compute_tally(p, test_db)
    assert tally.total_ballots_cast == 1  # v2's delegation is inert


def test_topic_allow_delegation_false_inerts_budget_delegation(client, test_db):
    """A tagged topic with allow_delegation=False gates the whole proposal."""
    org = _org(test_db)
    author = _author(test_db, org)
    v1, v2, v3 = _members(test_db, org, 3)
    topic = _topic(test_db, org, allow_delegation=False)
    p, opts = _alloc_proposal(test_db, author, org, topic=topic)
    a, b = opts[0].id, opts[1].id
    _deleg(test_db, v2, v1, org, topic=topic)
    test_db.commit()

    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v1),
                json={"allocations": {a: 60000, b: 40000}})

    tally = delegation_engine.engine.compute_tally(p, test_db)
    assert tally.total_ballots_cast == 1  # delegation gated → inert


# ===========================================================================
# Relevance-weighted strategy
# ===========================================================================

def test_relevance_weighted_uses_highest_relevance_delegate_whole(client, test_db):
    """A relevance_weighted delegator with two topic delegates uses the
    highest-relevance delegate's budget ballot whole (no blending)."""
    org = _org(test_db)
    author = _author(test_db, org)
    v1, v2, deleg_lo, deleg_hi = _members(test_db, org, 4)
    t_hi = _topic(test_db, org, name="High")
    t_lo = _topic(test_db, org, name="Low")
    p, opts = _alloc_proposal(test_db, author, org)
    a, b = opts[0].id, opts[1].id
    # proposal tagged with both topics, t_hi more relevant.
    test_db.add(models.ProposalTopic(proposal_id=p.id, topic_id=t_hi.id, relevance=0.9))
    test_db.add(models.ProposalTopic(proposal_id=p.id, topic_id=t_lo.id, relevance=0.1))
    test_db.flush()
    # v1 uses relevance_weighted, delegates High→deleg_hi, Low→deleg_lo.
    v1.delegation_strategy = "relevance_weighted"
    test_db.flush()
    _deleg(test_db, v1, deleg_hi, org, topic=t_hi)
    _deleg(test_db, v1, deleg_lo, org, topic=t_lo)
    test_db.commit()

    # The two delegates cast opposite allocations.
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(deleg_hi),
                json={"allocations": {a: 100000, b: 0}})
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(deleg_lo),
                json={"allocations": {a: 0, b: 100000}})

    result = delegation_engine.engine.resolve_vote(v1.id, p.id, test_db)
    assert result is not None
    assert result.is_direct is False
    # highest-relevance delegate is deleg_hi → v1 inherits {a:100000, b:0} whole.
    assert result.ballot.allocations == {a: 100000, b: 0}


# ===========================================================================
# Quorum — side effect on Proposal.status
# ===========================================================================

def test_delegated_ballot_flips_quorum(client, test_db):
    """A delegated budget ballot counts toward quorum: without it the proposal
    fails quorum; with it the proposal passes. Asserts the Proposal.status row."""
    org = _org(test_db)
    author = _author(test_db, org)
    # 4 members + author (steward) = 5 eligible. quorum 0.5 → need >= 3 ballots.
    v1, v2, v3, v4 = _members(test_db, org, 4)
    topic = _topic(test_db, org)
    p, opts = _alloc_proposal(test_db, author, org, topic=topic, quorum=0.5)
    a, b = opts[0].id, opts[1].id
    # v4 delegates to v1. Direct casters: v1, v2 (2). Plus v4's delegated = 3.
    _deleg(test_db, v4, v1, org, topic=topic)
    test_db.commit()

    for u in (v1, v2):
        client.post(f"/api/proposals/{p.id}/vote", headers=_auth(u),
                    json={"allocations": {a: 60000, b: 40000}})

    r = client.post(f"/api/proposals/{p.id}/advance", headers=_auth(author), json={})
    assert r.status_code == 200, r.text
    test_db.refresh(p)
    # 3 of 5 = 0.6 >= 0.5 quorum → passed (budget passes on quorum).
    assert p.status == "passed"


def test_without_delegation_quorum_fails(client, test_db):
    """Control for the quorum test: the same 2 direct ballots without the
    delegation fall under quorum → failed."""
    org = _org(test_db)
    author = _author(test_db, org)
    v1, v2, v3, v4 = _members(test_db, org, 4)
    topic = _topic(test_db, org)
    p, opts = _alloc_proposal(test_db, author, org, topic=topic, quorum=0.5)
    a, b = opts[0].id, opts[1].id
    test_db.commit()

    for u in (v1, v2):
        client.post(f"/api/proposals/{p.id}/vote", headers=_auth(u),
                    json={"allocations": {a: 60000, b: 40000}})

    r = client.post(f"/api/proposals/{p.id}/advance", headers=_auth(author), json={})
    assert r.status_code == 200, r.text
    test_db.refresh(p)
    # 2 of 5 = 0.4 < 0.5 → failed.
    assert p.status == "failed"


# ===========================================================================
# Cycle guard
# ===========================================================================

def test_cycle_guard_no_infinite_loop(client, test_db):
    """A→B→A topic delegation on a budget proposal resolves without hanging.
    (The graph store prevents cycles at insert; the resolver's _visited guard is
    the defensive backstop.)"""
    org = _org(test_db)
    author = _author(test_db, org)
    v1, v2, v3 = _members(test_db, org, 3)
    topic = _topic(test_db, org)
    p, opts = _alloc_proposal(test_db, author, org, topic=topic)
    a, b = opts[0].id, opts[1].id
    _deleg(test_db, v1, v2, org, topic=topic)
    _deleg(test_db, v2, v1, org, topic=topic)
    test_db.commit()

    # neither casts; resolution must terminate and count zero ballots.
    tally = delegation_engine.engine.compute_tally(p, test_db)
    assert tally.total_ballots_cast == 0


# ===========================================================================
# Notification
# ===========================================================================

def test_delegate_budget_vote_emits_notification(client, test_db):
    """A delegate's budget vote emits delegate.voted to an opted-in delegator
    with a renderable payload (vote_value = the allocations dict)."""
    org = _org(test_db)
    author = _author(test_db, org)
    delegate, delegator, v3 = _members(test_db, org, 3)
    topic = _topic(test_db, org)
    p, opts = _alloc_proposal(test_db, author, org, topic=topic)
    a, b = opts[0].id, opts[1].id
    _deleg(test_db, delegator, delegate, org, topic=topic)
    test_db.add(models.NotificationPreference(
        user_id=delegator.id, event_type="delegate.voted",
        channel="in_app", enabled=True,
    ))
    test_db.commit()

    r = client.post(f"/api/proposals/{p.id}/vote", headers=_auth(delegate),
                    json={"allocations": {a: 70000, b: 30000}})
    assert r.status_code == 200, r.text

    rows = (
        test_db.query(models.Notification)
        .filter(models.Notification.user_id == delegator.id,
                models.Notification.event_type == "delegate.voted",
                models.Notification.target_id == p.id)
        .all()
    )
    assert len(rows) == 1
    payload = rows[0].payload
    assert payload["delegate_user_id"] == delegate.id
    # budget payload carries the allocations dict (not a raw JSON dump).
    assert payload["vote_value"] == {a: 70000, b: 30000}


# ===========================================================================
# Eligibility
# ===========================================================================

def test_ineligible_delegate_ballot_never_leaks(client, test_db):
    """A delegate who is not an eligible voter for the proposal never has their
    ballot leak into a delegator's resolution."""
    org = _org(test_db)
    author = _author(test_db, org)
    v1, delegator = _members(test_db, org, 2)
    # `outsider` is NOT a member of org → not eligible.
    outsider = _user(test_db, "outsider")
    topic = _topic(test_db, org)
    p, opts = _alloc_proposal(test_db, author, org, topic=topic)
    a, b = opts[0].id, opts[1].id
    _deleg(test_db, delegator, outsider, org, topic=topic)
    test_db.commit()

    # outsider is not a member so they cannot cast through the API; even if a
    # ballot row existed the eligible_ids filter would exclude it. Resolution
    # for the delegator must yield nothing.
    result = delegation_engine.engine.resolve_vote(delegator.id, p.id, test_db)
    assert result is None
    tally = delegation_engine.engine.compute_tally(p, test_db)
    assert tally.total_ballots_cast == 0


# ===========================================================================
# my-vote reflects delegated budget ballot
# ===========================================================================

def test_my_vote_reflects_delegated_allocation(client, test_db):
    org = _org(test_db)
    author = _author(test_db, org)
    delegate, delegator, v3 = _members(test_db, org, 3)
    topic = _topic(test_db, org)
    p, opts = _alloc_proposal(test_db, author, org, topic=topic)
    a, b = opts[0].id, opts[1].id
    _deleg(test_db, delegator, delegate, org, topic=topic)
    test_db.commit()

    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(delegate),
                json={"allocations": {a: 80000, b: 20000}})

    r = client.get(f"/api/proposals/{p.id}/my-vote", headers=_auth(delegator))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["is_direct"] is False
    assert data["allocations"] == {a: 80000, b: 20000}
    assert data["cast_by"]["id"] == delegate.id


def test_my_vote_reflects_delegated_project_ranking(client, test_db):
    org = _org(test_db)
    author = _author(test_db, org)
    delegate, delegator, v3 = _members(test_db, org, 3)
    topic = _topic(test_db, org)
    p, opts = _project_proposal(test_db, author, org, topic=topic)
    a, b = opts[0].id, opts[1].id
    _deleg(test_db, delegator, delegate, org, topic=topic)
    test_db.commit()

    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(delegate), json=_ranked(a, b))

    r = client.get(f"/api/proposals/{p.id}/my-vote", headers=_auth(delegator))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["is_direct"] is False
    assert [e["option_id"] for e in data["ranked"]] == [a, b]
    assert data["cast_by"]["id"] == delegate.id


# ===========================================================================
# Payload formatter (unit)
# ===========================================================================

def test_format_vote_value_for_payload_budget():
    from routes.votes import _format_vote_value_for_payload
    alloc = {"opt-a": 500, "opt-b": 300}
    assert _format_vote_value_for_payload(
        None, {"allocations": alloc}, "budget_allocation",
    ) == alloc
    ranked = [{"option_id": "opt-a", "tier_id": None}]
    assert _format_vote_value_for_payload(
        None, {"ranked": ranked}, "budget_project",
    ) == ranked
    # missing/malformed ballot → empty container, never a crash.
    assert _format_vote_value_for_payload(None, None, "budget_allocation") == {}
    assert _format_vote_value_for_payload(None, None, "budget_project") == []
