"""Phase 88b — Weighted budget voting (allocation + project).

Covers:
  * Parity: weights=None byte-for-byte, and all-weights-1 (weighted path) equals
    the unweighted result for both modes.
  * _weighted_median unit properties: equals _median at equal weights (odd/even,
    duplicates); a heavy voter pins the median; exact-half midpoint; zero skip.
  * Allocation end-to-end: two shareholders (70/30) — per-bucket result sits at
    the heavy voter's value; cap reflow + rounding still sum to the envelope.
  * Project end-to-end: weighted positions reorder the funding walk; weighted
    tier plurality flips the chosen tier.
  * Quorum boundary → resulting Proposal.status (side effects).
  * Zero-weight voter contributes nothing but their Vote row exists.
  * Creation-block removal: a weighted org can create both budget methods.
  * Delegated budget weight-carry: delegator(w=5) → delegate(w=2) allocation
    enters the weighted median at combined weight 7.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import budget_tally as bt
import delegation_engine
import models
from database import Base, get_db
from main import app
from role_seed import seed_default_roles_for_org
from tests.conftest import make_org_membership

_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"
_B = bt.BucketSpec
ON = {"enabled": True, "unit_label": "shares"}


# ===========================================================================
# Part A — pure weighted-median properties
# ===========================================================================

def test_weighted_median_equals_median_at_equal_weights():
    rng = random.Random(7)
    for _ in range(200):
        n = rng.randint(1, 9)
        vals = [rng.randint(0, 100) for _ in range(n)]
        assert bt._weighted_median(vals, [1] * n) == bt._median(vals)


def test_weighted_median_duplicates_and_even():
    assert bt._weighted_median([10, 20], [1, 1]) == bt._median([10, 20])  # 15
    assert bt._weighted_median([10, 10, 20, 20], [1, 1, 1, 1]) == 15
    assert bt._weighted_median([10, 10, 20], [1, 1, 1]) == 10


def test_weighted_median_heavy_voter_pins():
    # one w=100 voter at 100 vs three w=1 voters at 1 → median pinned at 100.
    assert bt._weighted_median([100, 1, 1, 1], [100, 1, 1, 1]) == 100


def test_weighted_median_exact_half_midpoint():
    # weights 2 and 2: exactly half at the first value → midpoint with next.
    assert bt._weighted_median([10, 30], [2, 2]) == 20


def test_weighted_median_zero_weight_skipped():
    # the zero-weight 999 is ignored entirely.
    assert bt._weighted_median([999, 10, 10, 10], [0, 1, 1, 1]) == 10
    assert bt._weighted_median([5, 5], [0, 0]) == 0.0


def test_weighted_trimmed_mean_parity_shape():
    # all-ones weighted trimmed mean is a reasonable mean of the middle; just
    # assert it lands between min and max and skips zeros.
    v = [0, 10, 20, 30, 100]
    r = bt._weighted_trimmed_mean(v, [1] * 5)
    assert 0 <= r <= 100
    assert bt._weighted_trimmed_mean([999, 10], [0, 1]) == 10


# ===========================================================================
# Part B — pure tally parity (None vs all-ones)
# ===========================================================================

def test_allocation_none_vs_all_ones_parity():
    buckets = [_B("a"), _B("b"), _B("c")]
    ballots = [
        {"a": 50000, "b": 30000, "c": 20000},
        {"a": 40000, "b": 40000, "c": 20000},
        {"a": 60000, "b": 20000, "c": 20000},
    ]
    unweighted = bt.tally_allocation(envelope=100000, buckets=buckets, ballots=ballots)
    weighted = bt.tally_allocation(envelope=100000, buckets=buckets, ballots=ballots,
                                   weights=[1, 1, 1], total_eligible=3)
    assert unweighted.amounts == weighted.amounts


def test_project_none_vs_all_ones_parity():
    items = [bt.ProjectItemSpec(option_id="a", floor_amount=40000),
             bt.ProjectItemSpec(option_id="b", floor_amount=80000),
             bt.ProjectItemSpec(option_id="c", floor_amount=30000)]
    ballots = [["a", "c", "b"], ["a", "b", "c"], ["c", "a", "b"]]
    un = bt.tally_project(envelope=100000, min_spend=0, max_spend=100000,
                          items=items, ballots=ballots)
    we = bt.tally_project(envelope=100000, min_spend=0, max_spend=100000,
                          items=items, ballots=ballots, weights=[1, 1, 1],
                          total_eligible=3)
    assert [f["option_id"] for f in un.funded] == [f["option_id"] for f in we.funded]
    assert un.priority_order == we.priority_order
    assert un.stop_point == we.stop_point


# ===========================================================================
# Part C — weighted end-to-end (pure)
# ===========================================================================

def test_allocation_two_shareholders_heavy_wins():
    buckets = [_B("a"), _B("b")]
    # w=70 voter wants all A; w=30 voter wants all B. Weighted median per bucket
    # sits at the heavy voter's value → A gets the envelope.
    ballots = [{"a": 100000, "b": 0}, {"a": 0, "b": 100000}]
    t = bt.tally_allocation(envelope=100000, buckets=buckets, ballots=ballots,
                            weights=[70, 30], total_eligible=100)
    assert t.amounts["a"] == 100000
    assert t.amounts["b"] == 0
    assert sum(t.amounts.values()) == 100000  # envelope preserved
    assert t.total_ballots_cast == 100  # weight-denominated


def test_allocation_cap_reflow_weighted_sums_to_envelope():
    buckets = [_B("a", max_amount=10000), _B("b"), _B("c")]
    ballots = [{"a": 50000, "b": 30000, "c": 20000},
               {"a": 40000, "b": 40000, "c": 20000}]
    t = bt.tally_allocation(envelope=100000, buckets=buckets, ballots=ballots,
                            weights=[70, 30], total_eligible=100)
    assert t.amounts["a"] <= 10000
    assert sum(t.amounts.values()) == 100000


def test_project_weighted_positions_reorder():
    # Two 60k items, envelope 100k (only one fits). Heavy voter ranks B first.
    items = [bt.ProjectItemSpec(option_id="a", floor_amount=60000),
             bt.ProjectItemSpec(option_id="b", floor_amount=60000)]
    ballots = [["a"], ["b"]]
    # Unweighted (headcount): a-vs-b tie broken by breadth/id → a.
    un = bt.tally_project(envelope=100000, min_spend=0, max_spend=100000,
                          items=items, ballots=ballots)
    # Weighted: heavy voter (w=10) ranks b → b funds instead.
    we = bt.tally_project(envelope=100000, min_spend=0, max_spend=100000,
                          items=items, ballots=ballots, weights=[1, 10],
                          total_eligible=11)
    assert [f["option_id"] for f in un.funded] == ["a"]
    assert [f["option_id"] for f in we.funded] == ["b"]


def test_project_weighted_tier_plurality_flips():
    # Tier parent P with two tiers cheap(20k)/lux(50k). Light voters prefer
    # cheap, one heavy voter prefers lux → weighted plurality funds lux.
    items = [bt.ProjectItemSpec(
        option_id="P", kind="tier_parent", tier_allow_fallback=False,
        tiers=[bt.TierSpec(tier_id="cheap", cost=20000),
               bt.TierSpec(tier_id="lux", cost=50000)],
    )]
    ballots = [[("P", "cheap")], [("P", "cheap")], [("P", "lux")]]
    we = bt.tally_project(envelope=100000, min_spend=0, max_spend=100000,
                          items=items, ballots=ballots, weights=[1, 1, 10],
                          total_eligible=12)
    assert we.funded and we.funded[0]["tier_id"] == "lux"


# ===========================================================================
# Part D — integration (routes + service layer)
# ===========================================================================

@pytest.fixture(scope="function")
def test_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def client(test_db):
    def _get_db():
        try:
            yield test_db
        finally:
            pass
    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _auth(u):
    return {"Authorization": f"Bearer {auth_utils.create_access_token(u.id)}"}


def _user(db, n):
    u = models.User(username=n, display_name=n, password_hash=_DUMMY_HASH,
                    email=f"{n}@t.ex", email_verified=True)
    db.add(u); db.flush(); return u


def _org(db, slug="wb-org", weighted=None):
    s = {"default_voting_days": 7,
         "allowed_voting_methods": ["binary", "budget_allocation", "budget_project"]}
    if weighted is not None:
        s["weighted_voting"] = weighted
    o = models.Organization(name=slug.title(), slug=slug, description="", settings=s)
    db.add(o); db.flush(); seed_default_roles_for_org(db, o.id); return o


def _member(db, org, n, *, role="member", weight=1):
    u = _user(db, n)
    m = make_org_membership(db, org_id=org.id, user_id=u.id, role=role)
    m.voting_weight = weight
    db.flush()
    return u, m


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _alloc_proposal(db, author, org, *, quorum=0.0, labels=("A", "B")):
    p = models.Proposal(
        title="Alloc", body="", author_id=author.id, org_id=org.id,
        voting_method="budget_allocation", num_winners=1, status="voting",
        voting_start=_now(), voting_end=_now() + timedelta(days=7),
        quorum_threshold=quorum, pass_threshold=0.5,
        budget_config={"mode": "allocation", "envelope": 100000,
                       "currency": "USD", "aggregation": "median"},
    )
    db.add(p); db.flush()
    opts = []
    for i, lab in enumerate(labels):
        o = models.ProposalOption(proposal_id=p.id, label=lab, description="",
                                  display_order=i)
        db.add(o); opts.append(o)
    db.flush()
    return p, opts


def test_weighted_allocation_integration(client, test_db):
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    (v1, _) = _member(test_db, org, "v1", weight=70)
    (v2, _) = _member(test_db, org, "v2", weight=30)
    p, opts = _alloc_proposal(test_db, author, org)
    a, b = opts[0].id, opts[1].id
    test_db.commit()
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v1),
                json={"allocations": {a: 100000, b: 0}})
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v2),
                json={"allocations": {a: 0, b: 100000}})
    tally = delegation_engine.engine.compute_tally(p, test_db)
    assert tally.amounts[a] == 100000  # heavy voter's value
    assert tally.amounts[b] == 0
    assert tally.total_ballots_cast == 100  # 70 + 30 shares


def test_weighted_budget_creation_allowed(client, test_db):
    """Phase 88b lifted the Phase 88 budget creation block in weighted orgs."""
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    test_db.commit()
    for method, cfg in (
        ("budget_allocation", {"mode": "allocation", "envelope": 100000}),
        ("budget_project", {"mode": "project", "envelope": 100000, "min_spend": 0}),
    ):
        r = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author), json={
            "title": method, "voting_method": method, "budget_config": cfg,
            "options": [{"label": "A", **({"budget_floor_amount": 40000} if method == "budget_project" else {})},
                        {"label": "B", **({"budget_floor_amount": 80000} if method == "budget_project" else {})}],
        })
        assert r.status_code in (200, 201), (method, r.text)


def test_weighted_budget_quorum_status(client, test_db):
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    (v1, _) = _member(test_db, org, "v1", weight=6)
    (v2, _) = _member(test_db, org, "v2", weight=3)
    # total eligible weight = 10; quorum 0.5 ⇒ need >= 5 cast shares.
    p, opts = _alloc_proposal(test_db, author, org, quorum=0.5)
    a, b = opts[0].id, opts[1].id
    test_db.commit()
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v1),
                json={"allocations": {a: 60000, b: 40000}})  # 6 shares cast
    r = client.post(f"/api/proposals/{p.id}/advance", headers=_auth(author), json={})
    assert r.status_code == 200, r.text
    test_db.refresh(p)
    assert p.status == "passed"  # 6 of 10 >= 0.5


def test_weighted_allocation_zero_weight_voter(client, test_db):
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    (v1, _) = _member(test_db, org, "v1", weight=5)
    (zero, _) = _member(test_db, org, "zero", weight=0)
    p, opts = _alloc_proposal(test_db, author, org)
    a, b = opts[0].id, opts[1].id
    test_db.commit()
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v1),
                json={"allocations": {a: 100000, b: 0}})
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(zero),
                json={"allocations": {a: 0, b: 100000}})
    # zero-weight ballot row exists but contributes nothing to the median.
    assert test_db.query(models.Vote).filter(models.Vote.proposal_id == p.id).count() == 2
    tally = delegation_engine.engine.compute_tally(p, test_db)
    assert tally.amounts[a] == 100000  # zero voter's B pref ignored
    assert tally.total_ballots_cast == 5


def test_delegated_budget_weight_carry(client, test_db):
    """Phase 89 + 88b: delegator(w=5) delegates to delegate(w=2) who cast an
    allocation → the allocation enters the weighted median at combined weight 7."""
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    (dele, _) = _member(test_db, org, "delegate", weight=2)
    (dor, _) = _member(test_db, org, "delegator", weight=5)
    (other, _) = _member(test_db, org, "other", weight=6)
    p, opts = _alloc_proposal(test_db, author, org)
    a, b = opts[0].id, opts[1].id
    test_db.add(models.Delegation(delegator_id=dor.id, delegate_id=dele.id,
                                  topic_id=None, chain_behavior="revert_direct",
                                  org_id=org.id))
    test_db.commit()
    # delegate allocates all to A; other (w=6) allocates all to B.
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(dele),
                json={"allocations": {a: 100000, b: 0}})
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(other),
                json={"allocations": {a: 0, b: 100000}})
    tally = delegation_engine.engine.compute_tally(p, test_db)
    # A carries delegate(2) + delegator(5) = 7 shares; B carries 6. A wins.
    assert tally.amounts[a] == 100000
    assert tally.amounts[b] == 0
    assert tally.total_ballots_cast == 13  # 2 + 5 + 6
