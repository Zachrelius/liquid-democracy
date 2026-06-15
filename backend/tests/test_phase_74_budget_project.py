"""Phase 74 Stage core — Budget Voting, Mode B: Project budget (discrete items).

Coverage (spec: phase74_budget_project_dispatch_2026-06-14.md §8 — CORE only;
tiers / mandatory / Mode C are 74a/74b and are rejected at create here):

Pure tally (budget_tally.tally_project):
  1. The §4 worked example verbatim — funded set, amounts, stop, halt reason.
  2. Cumulative-position correctness — same item, different position by what
     precedes it.
  3. Omission = max_spend position — an item most voters omit sinks, even with
     a passionate minority.
  4. Breadth-first tiebreak — equal group position → breadth desc.
  5. Stop point from group desired-total — stops early, not at envelope.
  6. min_spend=0 "spend nothing".
  7. Hard-stop, not skip — top unfunded item that doesn't fit halts the walk.
  8. Hard envelope / max_spend never exceeded (randomized).
  9. Quorum.

Route / integration:
 10. Create round-trips budget_config(project) + floor amounts.
 11. Ballot validation — ranked required, dup/invalid rejected.
 12. Quorum pass/fail; results surface funded/unfunded/halt.
 13. Tie-resolver isolation; delegation inert; stable-result rejection.
 14. Mandatory + tier items rejected in the core stage.
 15. Additive parity.
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
_I = bt.ProjectItemSpec


# ===========================================================================
# Part A — pure tally
# ===========================================================================

def _worked_items():
    return [_I("roof", 40000), _I("pool", 80000), _I("land", 30000)]


def _worked_ballots():
    # §4 table, encoded as ordered option_id lists (omission = absent).
    return [
        ["roof", "land"],   # V1 desired 70k
        ["roof", "pool"],   # V2 desired 120k
        ["land"],           # V3 desired 30k
        ["roof"],           # V4 desired 40k
        ["land", "roof"],   # V5 desired 70k
    ]


def test_worked_example_verbatim():
    t = bt.tally_project(
        envelope=100000, min_spend=0, max_spend=100000,
        items=_worked_items(), ballots=_worked_ballots(),
    )
    assert t.group_positions["roof"] == 0
    assert t.group_positions["pool"] == 100000
    assert t.group_positions["land"] == 40000
    assert t.stop_point == 70000
    assert t.group_desired_total == 70000
    assert {f["option_id"] for f in t.funded} == {"roof", "land"}
    assert t.total_committed == 70000
    assert "pool" in t.unfunded
    assert t.halt_reason == "stop_point"


def test_cumulative_position_depends_on_what_precedes():
    """A $10k item ranked after three $100 items → position $300; after one
    $100k item → position $100k. Same item, different position."""
    items = [_I("a", 100), _I("b", 100), _I("c", 100), _I("big", 100000), _I("x", 10000)]
    # Ballot 1: x after three $100 items -> position 300
    t1 = bt.tally_project(envelope=200000, min_spend=200000, max_spend=200000,
                          items=items, ballots=[["a", "b", "c", "x"]])
    assert t1.group_positions["x"] == 300
    # Ballot 2: x after one $100k item -> position 100000
    t2 = bt.tally_project(envelope=200000, min_spend=200000, max_spend=200000,
                          items=items, ballots=[["big", "x"]])
    assert t2.group_positions["x"] == 100000


def test_omission_equals_max_spend():
    """3 enthusiasts rank 'rare' first; 997 omit → median position = max_spend,
    item never reached."""
    items = [_I("rare", 10000), _I("common", 10000)]
    ballots = [["rare"]] * 3 + [["common"]] * 997
    t = bt.tally_project(envelope=100000, min_spend=0, max_spend=100000,
                         items=items, ballots=ballots)
    assert t.group_positions["rare"] == 100000  # omitted by the 997-majority
    assert t.group_positions["common"] == 0
    assert "rare" not in {f["option_id"] for f in t.funded}


def test_breadth_first_tiebreak():
    """When two items tie on group position, the breadth-descending tiebreak
    orders the more-ranked one first. Because omission contributes max_spend to
    the median, we set max_spend equal to the ranked position so the omission
    entries don't break the position tie — producing a genuine equal-position /
    unequal-breadth pair (the exact input the tiebreak resolves)."""
    # Preceding item 'c' (30k) puts 'wide'/'narrow' at cumulative position 30k.
    items = [_I("c", 30000), _I("wide", 30000), _I("narrow", 30000)]
    # max_spend 30k => omission position == the ranked position (30k).
    ballots = [
        ["c", "wide"], ["c", "wide"], ["c", "wide"],  # wide ranked by 3 at 30k
        ["c", "narrow"],                                # narrow ranked by 1 at 30k
        ["wide"],                                       # wide also ranked first (0)
    ]
    t = bt.tally_project(envelope=200000, min_spend=0, max_spend=30000,
                         items=items, ballots=ballots)
    # Both tie at the 30k median; breadth differs (wide=4, narrow=1).
    assert t.group_positions["wide"] == 30000
    assert t.group_positions["narrow"] == 30000
    assert t.breadth["wide"] > t.breadth["narrow"]
    # The breadth-desc tiebreak orders 'wide' ahead of 'narrow' in the
    # computed priority queue (directly exposed for audit/FE).
    assert t.priority_order.index("wide") < t.priority_order.index("narrow")


def test_stop_point_below_envelope():
    """Several items fit the envelope, but the median desired-total is low, so
    the walk stops early — NOT at the envelope."""
    items = [_I("a", 20000), _I("b", 20000), _I("c", 20000), _I("d", 20000)]
    # Everyone ranks only a+b (desired 40k); c,d omitted.
    ballots = [["a", "b"]] * 5
    t = bt.tally_project(envelope=100000, min_spend=0, max_spend=100000,
                         items=items, ballots=ballots)
    assert t.stop_point == 40000
    assert {f["option_id"] for f in t.funded} == {"a", "b"}
    assert t.total_committed == 40000


def test_min_spend_zero_spend_nothing():
    """Most voters rank almost nothing → desired-total ~0 → fund little."""
    items = [_I("a", 20000), _I("b", 20000)]
    # 4 of 5 voters rank nothing; 1 ranks a.
    ballots = [[], [], [], [], ["a"]]
    t = bt.tally_project(envelope=100000, min_spend=0, max_spend=100000,
                         items=items, ballots=ballots)
    # median desired-total of {0,0,0,0,20000} = 0 → stop at 0 → nothing funded
    assert t.stop_point == 0
    assert t.funded == []
    assert t.total_committed == 0


def test_hard_stop_not_skip():
    """The highest-priority unfunded item that doesn't fit HALTS the walk; a
    cheaper lower-priority item below it is NOT funded."""
    # big is highest priority (position 0 for all) but costs 90k; small is
    # lower priority but cheap. max_spend caps at 50k so big doesn't fit.
    items = [_I("big", 90000), _I("small", 10000)]
    ballots = [["big", "small"]] * 5  # big first (pos 0), small after (pos 90k)
    t = bt.tally_project(envelope=100000, min_spend=100000, max_spend=50000,
                         items=items, ballots=ballots)
    # big (pos 0) reached first, doesn't fit max_spend 50k -> hard stop
    assert t.halt_reason == "item_did_not_fit"
    assert "big" in t.unfunded and "small" in t.unfunded
    assert t.total_committed == 0


def test_hard_envelope_never_exceeded_randomized():
    rng = random.Random(99)
    items = [_I(f"i{i}", rng.randint(5000, 40000)) for i in range(6)]
    ids = [it.option_id for it in items]
    for _ in range(50):
        ballots = []
        for _v in range(rng.randint(1, 10)):
            k = rng.randint(0, len(ids))
            ballots.append(rng.sample(ids, k))
        t = bt.tally_project(envelope=100000, min_spend=0, max_spend=80000,
                             items=items, ballots=ballots)
        assert t.total_committed <= 100000 + 1e-9
        assert t.total_committed <= 80000 + 1e-9


def test_quorum_method():
    t = bt.tally_project(envelope=100000, min_spend=0, max_spend=100000,
                         items=_worked_items(), ballots=[["roof"]], total_eligible=4)
    assert t.quorum_met(0.25) is True
    assert t.quorum_met(0.5) is False


def test_project_tally_no_winner_fields():
    t = bt.tally_project(envelope=100000, min_spend=0, max_spend=100000,
                         items=_worked_items(), ballots=_worked_ballots())
    assert not hasattr(t, "winners")
    assert not hasattr(t, "tied")


# ===========================================================================
# Part B — schema validation
# ===========================================================================

def test_schema_accepts_project_config():
    import schemas
    p = schemas.ProposalCreate(
        title="P", voting_method="budget_project",
        budget_config={"mode": "project", "envelope": 100000, "min_spend": 0},
        options=[
            schemas.OptionCreate(label="a", budget_floor_amount=40000),
            schemas.OptionCreate(label="b", budget_floor_amount=30000),
        ],
    )
    assert p.budget_config["mode"] == "project"
    assert p.budget_config["max_spend"] == 100000  # defaults to envelope
    assert p.budget_config["min_spend"] == 0


@pytest.mark.parametrize("bad", [
    {"mode": "project", "envelope": 100000, "min_spend": 50000, "max_spend": 40000},  # min>max
    {"mode": "project", "envelope": 100000, "max_spend": 200000},  # max>envelope
    {"mode": "project", "envelope": 0},
    {"mode": "bogus", "envelope": 100000},
])
def test_schema_rejects_bad_project_config(bad):
    import schemas
    with pytest.raises(Exception):
        schemas.ProposalCreate(title="P", voting_method="budget_project", budget_config=bad)


# ===========================================================================
# Part C — route / integration
# ===========================================================================

@pytest.fixture(scope="function")
def test_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
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
    u = models.User(username=username, display_name=username, password_hash=_DUMMY_HASH,
                    email=f"{username}@t.ex", email_verified=True, is_admin=is_admin)
    db.add(u)
    db.flush()
    return u


def _org(db, slug):
    o = models.Organization(
        name=slug.title(), slug=slug, description="",
        settings={"default_voting_days": 7,
                  "allowed_voting_methods": ["binary", "approval", "budget_project"]},
    )
    db.add(o)
    db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _auth(user):
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _project_proposal(db, author, org, *, status="voting", envelope=100000,
                      min_spend=0, max_spend=100000, quorum=0.4,
                      items=(("Roof", 40000), ("Pool", 80000), ("Land", 30000))):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    p = models.Proposal(
        title="Project budget", body="", author_id=author.id, org_id=org.id,
        voting_method="budget_project", num_winners=1, status=status,
        voting_start=now if status == "voting" else None,
        voting_end=(now + timedelta(days=7)) if status == "voting" else None,
        quorum_threshold=quorum, pass_threshold=0.5,
        budget_config={"mode": "project", "envelope": envelope, "currency": "USD",
                       "min_spend": min_spend, "max_spend": max_spend},
    )
    db.add(p)
    db.flush()
    opts = []
    for i, (label, floor) in enumerate(items):
        o = models.ProposalOption(proposal_id=p.id, label=label, description="",
                                  display_order=i, budget_floor_amount=floor,
                                  budget_kind="discrete")
        db.add(o)
        opts.append(o)
    db.flush()
    return p, opts


def _setup(db):
    org = _org(db, "project-org")
    author = _user(db, "pauthor")
    v1, v2, v3 = _user(db, "pv1"), _user(db, "pv2"), _user(db, "pv3")
    make_org_membership(db, org_id=org.id, user_id=author.id, role="steward")
    for u in (v1, v2, v3):
        make_org_membership(db, org_id=org.id, user_id=u.id, role="member")
    db.commit()
    return org, author, v1, v2, v3


def _ranked(*oids):
    return {"ranked": [{"option_id": o} for o in oids]}


def test_create_project_round_trips(client, test_db):
    org, author, *_ = _setup(test_db)
    body = {
        "title": "Capital plan", "voting_method": "budget_project",
        "budget_config": {"mode": "project", "envelope": 100000, "min_spend": 0},
        "options": [
            {"label": "Roof", "budget_floor_amount": 40000},
            {"label": "Pool", "budget_floor_amount": 80000},
        ],
    }
    r = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author), json=body)
    assert r.status_code in (200, 201), r.text
    data = r.json()
    assert data["voting_method"] == "budget_project"
    assert data["budget_config"]["mode"] == "project"
    floors = {o["label"]: o["budget_floor_amount"] for o in data["options"]}
    assert floors["Roof"] == 40000 and floors["Pool"] == 80000


def test_create_requires_floor_amounts(client, test_db):
    org, author, *_ = _setup(test_db)
    r = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author), json={
        "title": "x", "voting_method": "budget_project",
        "budget_config": {"mode": "project", "envelope": 100000},
        "options": [{"label": "a"}, {"label": "b"}],
    })
    assert r.status_code == 400, r.text


def test_mandatory_field_cut_is_ignored(client, test_db):
    """Phase 74 follow-up — the mandatory-minimum feature was CUT and the
    budget_is_mandatory column dropped (74a). A stale ``budget_is_mandatory``
    key in the payload is now simply an unknown field (ignored by the schema),
    so the proposal creates normally rather than 400-ing."""
    org, author, *_ = _setup(test_db)
    r = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author), json={
        "title": "x", "voting_method": "budget_project",
        "budget_config": {"mode": "project", "envelope": 100000},
        "options": [
            {"label": "a", "budget_floor_amount": 10000, "budget_is_mandatory": True},
            {"label": "b", "budget_floor_amount": 10000},
        ],
    })
    assert r.status_code in (200, 201), r.text


def test_tier_rejected_in_core(client, test_db):
    org, author, *_ = _setup(test_db)
    r = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author), json={
        "title": "x", "voting_method": "budget_project",
        "budget_config": {"mode": "project", "envelope": 100000},
        "options": [
            {"label": "a", "budget_floor_amount": 10000, "budget_kind": "tier_parent"},
            {"label": "b", "budget_floor_amount": 10000},
        ],
    })
    assert r.status_code == 400, r.text
    assert "tier" in r.json()["detail"].lower()


def test_stable_result_rejected(client, test_db):
    org, author, *_ = _setup(test_db)
    r = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author), json={
        "title": "x", "voting_method": "budget_project",
        "budget_config": {"mode": "project", "envelope": 100000},
        "options": [{"label": "a", "budget_floor_amount": 10000},
                    {"label": "b", "budget_floor_amount": 10000}],
        "stable_result_required": True,
    })
    assert r.status_code == 400, r.text


def test_ballot_validation(client, test_db):
    org, author, v1, v2, v3 = _setup(test_db)
    p, opts = _project_proposal(test_db, author, org)
    test_db.commit()
    roof, pool, land = opts[0].id, opts[1].id, opts[2].id
    # valid
    r = client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v1), json=_ranked(roof, land))
    assert r.status_code == 200, r.text
    # ranked required
    r = client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v2), json={"vote_value": "yes"})
    assert r.status_code == 400
    # invalid option
    r = client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v2),
                    json={"ranked": [{"option_id": "99999999-9999-9999-9999-999999999999"}]})
    assert r.status_code == 400
    # duplicate option
    r = client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v2),
                    json={"ranked": [{"option_id": roof}, {"option_id": roof}]})
    assert r.status_code in (400, 422)


def test_quorum_pass_and_results(client, test_db):
    org, author, v1, v2, v3 = _setup(test_db)
    p, opts = _project_proposal(test_db, author, org, quorum=0.4)
    test_db.commit()
    roof, pool, land = opts[0].id, opts[1].id, opts[2].id
    # Encode the §4 ballots over the 3 voters we have (subset still resolves).
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v1), json=_ranked(roof, land))
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v2), json=_ranked(roof, pool))
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v3), json=_ranked(land))
    r = client.post(f"/api/proposals/{p.id}/advance", headers=_auth(author), json={})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "passed"
    res = client.get(f"/api/proposals/{p.id}/results", headers=_auth(author)).json()
    assert res["voting_method"] == "budget_project"
    assert res["project_halt_reason"] in ("stop_point", "queue_exhausted", "item_did_not_fit")
    assert res["project_total_committed"] <= 100000


def test_quorum_fail(client, test_db):
    org, author, v1, v2, v3 = _setup(test_db)
    p, opts = _project_proposal(test_db, author, org, quorum=0.9)
    test_db.commit()
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v1), json=_ranked(opts[0].id))
    r = client.post(f"/api/proposals/{p.id}/advance", headers=_auth(author), json={})
    assert r.status_code == 200
    assert r.json()["status"] == "failed"


def test_advance_records_no_tie_resolution(client, test_db):
    org, author, v1, v2, v3 = _setup(test_db)
    p, opts = _project_proposal(test_db, author, org, quorum=0.4)
    test_db.commit()
    for u in (v1, v2, v3):
        client.post(f"/api/proposals/{p.id}/vote", headers=_auth(u), json=_ranked(opts[0].id, opts[2].id))
    client.post(f"/api/proposals/{p.id}/advance", headers=_auth(author), json={})
    test_db.refresh(p)
    assert p.tie_resolution is None


def test_delegation_inert(client, test_db):
    org, author, v1, v2, v3 = _setup(test_db)
    p, opts = _project_proposal(test_db, author, org, quorum=0.4)
    test_db.add(models.Delegation(delegator_id=v2.id, delegate_id=v1.id, topic_id=None,
                                  chain_behavior="revert_direct", org_id=org.id))
    test_db.commit()
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v1), json=_ranked(opts[0].id))
    import delegation_engine
    tally = delegation_engine.engine.compute_tally(p, test_db)
    assert tally.total_ballots_cast == 1  # v2's delegation did NOT carry


def test_additive_parity_binary_unchanged(client, test_db):
    org, author, *_ = _setup(test_db)
    r = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author),
                    json={"title": "plain", "voting_method": "binary"})
    assert r.status_code in (200, 201), r.text
    data = r.json()
    assert data["budget_config"] is None
    for o in data.get("options", []):
        assert o.get("budget_floor_amount") is None
