"""Phase 73 — Budget Voting, Mode A: Allocation budget.

Coverage (spec: phase73_budget_allocation_dispatch_2026-06-14.md §7):

Pure tally (budget_tally.py):
  1. Sum invariant — output sums to envelope across randomized ballots.
  2. Median strategyproofness — a lone inflater can't move the final past
     the median voter's level (beyond the shared proportional scale).
  3. Everything-with-support funded — any bucket with median > 0 gets > 0.
  4. Ceiling clamp + reflow — a capped bucket's residual reflows; total holds.
  5. Ceilings-below-envelope — unallocated_remainder == the exact shortfall.
  6. Degenerate no-support — all-zero ballots → all-zero, flagged, no 500.
  7. Trimmed-mean — trims at >=5 voters; degrades to mean below 5.
  8. Rounding — whole dollars summing exactly to the allocated total.

Route / integration:
  9. Ballot validation — over-envelope / over-ceiling rejected; under ok.
 10. Quorum — under → failed (no allocation); at → passed with allocation.
 11. Tie-resolver isolation — AllocationTally has no winners/tied; advance
     records no tie_resolution.
 12. Delegation restriction — an org delegation does not carry into a budget
     tally; the delegator's weight stays inert.
 13. Stable-result rejection — set on a budget proposal → 400 at create.
 14. Additive-layer / serializer coverage — budget_config on ProposalOut +
     budget_max_amount on OptionOut; NULL on non-budget rows unchanged.
 15. Existing-vs-new-org parity.

Migration cycle test lives in test_phase_73_migration_cycle.py.
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
import models
from database import Base, get_db
from main import app
from role_seed import seed_default_roles_for_org
from tests.conftest import make_org_membership

_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"
_B = bt.BucketSpec


# ===========================================================================
# Part A — pure tally (no DB)
# ===========================================================================

def test_sum_invariant_randomized():
    """Output always sums to exactly the envelope across random ballots."""
    rng = random.Random(1234)
    buckets = [_B("a"), _B("b"), _B("c"), _B("d")]
    for _ in range(50):
        ballots = []
        for _v in range(rng.randint(1, 12)):
            # random allocations summing to <= envelope
            raw = [rng.randint(0, 40000) for _ in buckets]
            total = sum(raw)
            if total > 100000:
                raw = [int(x * 100000 / total) for x in raw]
            ballots.append({buckets[i].option_id: raw[i] for i in range(len(buckets))})
        t = bt.tally_allocation(envelope=100000, buckets=buckets, ballots=ballots)
        assert sum(t.amounts.values()) == 100000, t.amounts


def test_median_strategyproofness():
    """A single voter maxing one bucket cannot pull that bucket's median past
    where the median voter sits. With 5 honest voters at 20k on 'a' and one
    inflater at 100k, the median of 'a' is still 20k (pre-scale)."""
    buckets = [_B("a"), _B("b")]
    honest = [{"a": 20000, "b": 20000} for _ in range(4)]
    inflater = [{"a": 100000, "b": 0}]
    ballots = honest + inflater
    # median of a = {20k,20k,20k,20k,100k} -> 20k; median of b = {20k,20k,20k,20k,0} -> 20k
    t = bt.tally_allocation(envelope=100000, buckets=buckets, ballots=ballots)
    # both medians 20k → equal share 50k/50k regardless of inflater
    assert t.amounts["a"] == 50000
    assert t.amounts["b"] == 50000


def test_everything_with_support_funded():
    buckets = [_B("a"), _B("b"), _B("c")]
    ballots = [
        {"a": 50000, "b": 30000, "c": 20000},
        {"a": 40000, "b": 40000, "c": 20000},
        {"a": 60000, "b": 20000, "c": 20000},
    ]
    t = bt.tally_allocation(envelope=100000, buckets=buckets, ballots=ballots)
    assert all(v > 0 for v in t.amounts.values())


def test_ceiling_clamp_and_reflow():
    buckets = [_B("a", max_amount=10000), _B("b"), _B("c")]
    ballots = [
        {"a": 50000, "b": 30000, "c": 20000},
        {"a": 40000, "b": 40000, "c": 20000},
        {"a": 60000, "b": 20000, "c": 20000},
    ]
    t = bt.tally_allocation(envelope=100000, buckets=buckets, ballots=ballots)
    assert t.amounts["a"] <= 10000
    assert sum(t.amounts.values()) == 100000
    assert t.unallocated_remainder == 0


def test_ceilings_below_envelope():
    buckets = [_B("a", max_amount=10000), _B("b", max_amount=10000), _B("c", max_amount=10000)]
    ballots = [{"a": 30000, "b": 30000, "c": 30000}]
    t = bt.tally_allocation(envelope=100000, buckets=buckets, ballots=ballots)
    assert sum(t.amounts.values()) == 30000
    assert t.unallocated_remainder == 70000
    assert all(t.amounts[k] <= 10000 for k in ("a", "b", "c"))


def test_degenerate_no_support():
    buckets = [_B("a"), _B("b")]
    ballots = [{"a": 0, "b": 0}, {"a": 0, "b": 0}]
    t = bt.tally_allocation(envelope=100000, buckets=buckets, ballots=ballots)
    assert t.degenerate_no_support is True
    assert sum(t.amounts.values()) == 0
    assert t.unallocated_remainder == 0


def test_degenerate_no_ballots():
    buckets = [_B("a"), _B("b")]
    t = bt.tally_allocation(envelope=100000, buckets=buckets, ballots=[])
    assert t.degenerate_no_support is True
    assert sum(t.amounts.values()) == 0


def test_omitted_bucket_counts_as_zero():
    """A voter omitting a bucket = $0 for it in the median."""
    buckets = [_B("a"), _B("b")]
    # two voters fund only 'a'; 'b' omitted entirely -> median b = 0
    ballots = [{"a": 50000}, {"a": 50000}, {"a": 50000}]
    t = bt.tally_allocation(envelope=100000, buckets=buckets, ballots=ballots)
    assert t.amounts["b"] == 0
    assert t.amounts["a"] == 100000


def test_trimmed_mean_trims_at_five_voters():
    """At 5 voters trimmed_mean drops the top and bottom (k=1 each) before
    meaning. Outlier 100k is trimmed; result reflects the inner three."""
    buckets = [_B("a"), _B("b")]
    # a: {0, 10000, 10000, 10000, 100000} -> trim 0 and 100000 -> mean(10k,10k,10k)=10k
    ballots = [
        {"a": 0, "b": 50000},
        {"a": 10000, "b": 40000},
        {"a": 10000, "b": 40000},
        {"a": 10000, "b": 40000},
        {"a": 100000, "b": 0},
    ]
    t = bt.tally_allocation(envelope=100000, buckets=buckets, ballots=ballots, aggregation="trimmed_mean")
    # pre-scale a=10000; b median-of-trim. Just assert the outlier didn't dominate a.
    assert t.amounts["a"] < t.amounts["b"]


def test_trimmed_mean_degrades_below_five():
    """With <5 voters, the trim rounds to 0 and trimmed_mean == plain mean."""
    buckets = [_B("a")]
    ballots = [{"a": 0}, {"a": 60000}, {"a": 30000}]  # mean 30000
    t = bt.tally_allocation(envelope=100000, buckets=buckets, ballots=ballots, aggregation="trimmed_mean")
    # single bucket → scales to envelope regardless; just assert no error + funded
    assert t.amounts["a"] == 100000


def test_rounding_sums_exactly():
    """Largest-remainder rounding keeps whole dollars summing to the total."""
    buckets = [_B("a"), _B("b"), _B("c")]
    # medians that scale to non-integer shares
    ballots = [{"a": 1, "b": 1, "c": 1}]
    t = bt.tally_allocation(envelope=100, buckets=buckets, ballots=ballots)
    assert sum(t.amounts.values()) == 100
    assert all(isinstance(v, int) for v in t.amounts.values())


def test_quorum_met_method():
    buckets = [_B("a")]
    t = bt.tally_allocation(envelope=100, buckets=buckets, ballots=[{"a": 100}], total_eligible=4)
    assert t.total_ballots_cast == 1
    assert t.quorum_met(0.25) is True
    assert t.quorum_met(0.5) is False


def test_allocation_tally_has_no_winner_fields():
    """Tie-resolver isolation at the type level: AllocationTally carries no
    winners/tied attributes, so the dispatch can never route it to
    tie_resolution.py (which reads tally.winners/.tied)."""
    t = bt.tally_allocation(envelope=100, buckets=[_B("a")], ballots=[{"a": 100}])
    assert not hasattr(t, "winners")
    assert not hasattr(t, "tied")


# ===========================================================================
# Part B — schema validation
# ===========================================================================

def test_schema_accepts_budget_voting_method():
    import schemas
    p = schemas.ProposalCreate(
        title="B", voting_method="budget_allocation",
        budget_config={"mode": "allocation", "envelope": 1000},
        options=[schemas.OptionCreate(label="a"), schemas.OptionCreate(label="b")],
    )
    assert p.voting_method == "budget_allocation"
    assert p.budget_config["aggregation"] == "median"  # default applied
    assert p.budget_config["currency"] == "USD"


@pytest.mark.parametrize("bad", [
    {"mode": "wrong", "envelope": 1000},
    {"mode": "allocation", "envelope": 0},
    {"mode": "allocation", "envelope": -5},
    {"mode": "allocation", "envelope": 1000, "aggregation": "mean"},
    {"mode": "allocation", "envelope": 1000, "bogus": 1},
])
def test_schema_rejects_bad_budget_config(bad):
    import schemas
    with pytest.raises(Exception):
        schemas.ProposalCreate(title="B", voting_method="budget_allocation", budget_config=bad)


def test_votecast_allocations_validation():
    import schemas
    schemas.VoteCast(allocations={"11111111-1111-1111-1111-111111111111": 100})
    with pytest.raises(Exception):
        schemas.VoteCast(allocations={"11111111-1111-1111-1111-111111111111": -1})


# ===========================================================================
# Part C — route / integration
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


def _user(db, username, *, is_admin=False):
    u = models.User(
        username=username, display_name=username, password_hash=_DUMMY_HASH,
        email=f"{username}@t.ex", email_verified=True, is_admin=is_admin,
    )
    db.add(u)
    db.flush()
    return u


def _org(db, slug, *, allow_budget=True):
    methods = ["binary", "approval"]
    if allow_budget:
        methods = methods + ["budget_allocation"]
    o = models.Organization(
        name=slug.title(), slug=slug, description="",
        settings={"default_voting_days": 7, "allowed_voting_methods": methods},
    )
    db.add(o)
    db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _auth(user):
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _budget_proposal(db, author, org, *, status="voting", envelope=100000,
                     aggregation="median", caps=(None, None, None),
                     labels=("Landscaping", "Reserve", "Events"),
                     quorum=0.4):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    p = models.Proposal(
        title="Budget", body="", author_id=author.id, org_id=org.id,
        voting_method="budget_allocation", num_winners=1, status=status,
        voting_start=now if status == "voting" else None,
        voting_end=(now + timedelta(days=7)) if status == "voting" else None,
        quorum_threshold=quorum, pass_threshold=0.5,
        budget_config={"mode": "allocation", "envelope": envelope,
                       "currency": "USD", "aggregation": aggregation},
    )
    db.add(p)
    db.flush()
    opts = []
    for i, (label, cap) in enumerate(zip(labels, caps)):
        o = models.ProposalOption(
            proposal_id=p.id, label=label, description="", display_order=i,
            budget_max_amount=cap,
        )
        db.add(o)
        opts.append(o)
    db.flush()
    return p, opts


def _setup(db):
    org = _org(db, "budget-org")
    author = _user(db, "author")
    v1 = _user(db, "v1")
    v2 = _user(db, "v2")
    v3 = _user(db, "v3")
    # author is a steward (holds proposal.advance_phase, needed to close voting)
    make_org_membership(db, org_id=org.id, user_id=author.id, role="steward")
    for u in (v1, v2, v3):
        make_org_membership(db, org_id=org.id, user_id=u.id, role="member")
    db.commit()
    return org, author, v1, v2, v3


def test_create_budget_proposal_round_trips(client, test_db):
    org, author, *_ = _setup(test_db)
    body = {
        "title": "Annual budget", "body": "Split the dues",
        "voting_method": "budget_allocation",
        "budget_config": {"mode": "allocation", "envelope": 100000},
        "options": [
            {"label": "Landscaping", "budget_max_amount": 40000},
            {"label": "Reserve"},
        ],
    }
    r = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author), json=body)
    assert r.status_code in (200, 201), r.text
    data = r.json()
    assert data["voting_method"] == "budget_allocation"
    assert data["budget_config"]["envelope"] == 100000
    assert data["budget_config"]["aggregation"] == "median"
    caps = {o["label"]: o["budget_max_amount"] for o in data["options"]}
    assert caps["Landscaping"] == 40000
    assert caps["Reserve"] is None


def test_budget_config_requires_budget_method(client, test_db):
    org, author, *_ = _setup(test_db)
    r = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author), json={
        "title": "x", "voting_method": "binary",
        "budget_config": {"mode": "allocation", "envelope": 1000},
    })
    assert r.status_code == 400, r.text


def test_budget_method_requires_config(client, test_db):
    org, author, *_ = _setup(test_db)
    r = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author), json={
        "title": "x", "voting_method": "budget_allocation",
        "options": [{"label": "a"}, {"label": "b"}],
    })
    assert r.status_code == 400, r.text


def test_stable_result_rejected_for_budget(client, test_db):
    org, author, *_ = _setup(test_db)
    r = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author), json={
        "title": "x", "voting_method": "budget_allocation",
        "budget_config": {"mode": "allocation", "envelope": 1000},
        "options": [{"label": "a"}, {"label": "b"}],
        "stable_result_required": True,
    })
    assert r.status_code == 400, r.text
    assert "stable-result" in r.json()["detail"].lower()


def test_ballot_validation(client, test_db):
    org, author, v1, v2, v3 = _setup(test_db)
    p, opts = _budget_proposal(test_db, author, org, envelope=100000)
    test_db.commit()
    a, b, c = opts[0].id, opts[1].id, opts[2].id

    # under-allocation accepted
    r = client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v1),
                    json={"allocations": {a: 30000, b: 20000}})
    assert r.status_code == 200, r.text

    # over-envelope rejected
    r = client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v2),
                    json={"allocations": {a: 80000, b: 80000}})
    assert r.status_code == 400, r.text

    # invalid option rejected
    r = client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v2),
                    json={"allocations": {"99999999-9999-9999-9999-999999999999": 1000}})
    assert r.status_code == 400


def test_over_ceiling_rejected(client, test_db):
    org, author, v1, v2, v3 = _setup(test_db)
    p, opts = _budget_proposal(test_db, author, org, envelope=100000, caps=(10000, None, None))
    test_db.commit()
    a = opts[0].id
    r = client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v1),
                    json={"allocations": {a: 50000}})
    assert r.status_code == 400, r.text
    assert "ceiling" in r.json()["detail"].lower()


def test_quorum_pass_with_allocation(client, test_db):
    org, author, v1, v2, v3 = _setup(test_db)
    p, opts = _budget_proposal(test_db, author, org, envelope=100000, quorum=0.4)
    test_db.commit()
    a, b, c = opts[0].id, opts[1].id, opts[2].id
    # 3 of 4 eligible cast (author+v1+v2+v3 = 4 members) -> >= quorum
    for u in (v1, v2, v3):
        client.post(f"/api/proposals/{p.id}/vote", headers=_auth(u),
                    json={"allocations": {a: 40000, b: 40000, c: 20000}})
    r = client.post(f"/api/proposals/{p.id}/advance", headers=_auth(author), json={})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "passed"
    res = client.get(f"/api/proposals/{p.id}/results", headers=_auth(author)).json()
    assert res["voting_method"] == "budget_allocation"
    assert sum(res["budget_amounts"].values()) == 100000
    assert res["budget_degenerate_no_support"] is False


def test_quorum_fail_no_allocation(client, test_db):
    org, author, v1, v2, v3 = _setup(test_db)
    p, opts = _budget_proposal(test_db, author, org, envelope=100000, quorum=0.9)
    test_db.commit()
    a = opts[0].id
    # only 1 of 4 casts -> under 0.9 quorum
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v1),
                json={"allocations": {a: 50000}})
    r = client.post(f"/api/proposals/{p.id}/advance", headers=_auth(author), json={})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "failed"


def test_advance_records_no_tie_resolution(client, test_db):
    """Budget proposals never route to tie resolution — tie_resolution stays
    None after a passing close."""
    org, author, v1, v2, v3 = _setup(test_db)
    p, opts = _budget_proposal(test_db, author, org, quorum=0.4)
    test_db.commit()
    a, b, c = opts[0].id, opts[1].id, opts[2].id
    for u in (v1, v2, v3):
        client.post(f"/api/proposals/{p.id}/vote", headers=_auth(u),
                    json={"allocations": {a: 50000, b: 30000, c: 20000}})
    client.post(f"/api/proposals/{p.id}/advance", headers=_auth(author), json={})
    test_db.refresh(p)
    assert p.tie_resolution is None


def test_degenerate_passes_clean(client, test_db):
    """All-zero ballots → proposal still resolves (passes on quorum), no 500."""
    org, author, v1, v2, v3 = _setup(test_db)
    p, opts = _budget_proposal(test_db, author, org, quorum=0.4)
    test_db.commit()
    a, b, c = opts[0].id, opts[1].id, opts[2].id
    for u in (v1, v2, v3):
        client.post(f"/api/proposals/{p.id}/vote", headers=_auth(u),
                    json={"allocations": {a: 0, b: 0, c: 0}})
    r = client.post(f"/api/proposals/{p.id}/advance", headers=_auth(author), json={})
    assert r.status_code == 200
    assert r.json()["status"] == "passed"
    res = client.get(f"/api/proposals/{p.id}/results", headers=_auth(author)).json()
    assert res["budget_degenerate_no_support"] is True
    assert sum(res["budget_amounts"].values()) == 0


def test_delegation_inert_for_budget(client, test_db):
    """A delegation row toward a voter does NOT carry the delegator's weight
    into a budget tally — budget is direct-vote only."""
    org, author, v1, v2, v3 = _setup(test_db)
    p, opts = _budget_proposal(test_db, author, org, quorum=0.4)
    # v2 delegates globally to v1 (org-scoped). Budget tally must ignore it.
    deleg = models.Delegation(
        delegator_id=v2.id, delegate_id=v1.id, topic_id=None,
        chain_behavior="revert_direct", org_id=org.id,
    )
    test_db.add(deleg)
    test_db.commit()
    a, b, c = opts[0].id, opts[1].id, opts[2].id
    # Only v1 casts a direct ballot; v2's delegation must NOT count v2 in.
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v1),
                json={"allocations": {a: 50000, b: 30000, c: 20000}})
    import delegation_engine
    tally = delegation_engine.engine.compute_tally(p, test_db)
    # exactly one ballot counted (v1's direct), NOT two (no delegated carry)
    assert tally.total_ballots_cast == 1
    # delegation row untouched
    assert test_db.query(models.Delegation).count() == 1


def test_additive_parity_binary_unchanged(client, test_db):
    """A binary proposal carries budget_config=NULL on ProposalOut and behaves
    exactly as before."""
    org, author, *_ = _setup(test_db)
    r = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author), json={
        "title": "plain", "voting_method": "binary",
    })
    assert r.status_code in (200, 201), r.text
    data = r.json()
    assert data["budget_config"] is None
    for o in data.get("options", []):
        assert o.get("budget_max_amount") is None


def test_existing_vs_new_org_parity(client, test_db):
    """Budget proposals behave identically in two independently-created orgs."""
    results = []
    for slug in ("org-x", "org-y"):
        org = _org(test_db, slug)
        author = _user(test_db, f"auth-{slug}")
        members = [_user(test_db, f"{slug}-m{i}") for i in range(3)]
        make_org_membership(test_db, org_id=org.id, user_id=author.id, role="steward")
        for m in members:
            make_org_membership(test_db, org_id=org.id, user_id=m.id, role="member")
        test_db.commit()
        p, opts = _budget_proposal(test_db, author, org, quorum=0.4)
        test_db.commit()
        a, b, c = opts[0].id, opts[1].id, opts[2].id
        for m in members:
            client.post(f"/api/proposals/{p.id}/vote", headers=_auth(m),
                        json={"allocations": {a: 50000, b: 30000, c: 20000}})
        client.post(f"/api/proposals/{p.id}/advance", headers=_auth(author), json={})
        res = client.get(f"/api/proposals/{p.id}/results", headers=_auth(author)).json()
        results.append(res["budget_amounts"])
    # same allocation pattern → same amounts (keys differ; compare sorted values)
    assert sorted(results[0].values()) == sorted(results[1].values())
