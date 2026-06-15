"""Phase 74b — Cost tiers (mutually-exclusive item variants).

Coverage (spec §3.6):
Pure tally (budget_tally.tally_project, new tier-aware signature):
  - Group-preferred tier funded when it fits.
  - Fallback: preferred doesn't fit, cheaper does, tier_allow_fallback=True →
    cheaper funded; result records the fallback tier.
  - No fallback: same situation, tier_allow_fallback=False → whole item not
    funded, walk hard-stops; lower-priority items not funded.
  - At most one tier per parent ever funded.
  - Plurality tier selection: most-selected wins; lower-cost tiebreak;
    deterministic id final tiebreak.
  - Cumulative-position-with-tiers: a tier parent before another item
    contributes the voter's SELECTED tier cost to that item's position.
  - Backward-compat: a non-tiered (core) fixture through the new signature
    produces the identical outcome.

Route / integration:
  - Create a tiered proposal (nested tiers → parent + child rows).
  - Vote with a tier selection; advance; results record funded tier.
  - Validation: two tiers of one parent rejected; tier_id not of parent
    rejected; tier parent with its own cost rejected; top-level
    budget_tier_parent_id rejected; ranking a tier child directly rejected.
  - Serializer: funded[].tier_id + tier columns surface.
"""
from __future__ import annotations

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
_T = bt.TierSpec


# ===========================================================================
# Part A — pure tally tier behavior
# ===========================================================================

def _pool(tiers, fallback=True):
    return _I("pool", kind="tier_parent",
              tiers=[_T(tid, cost) for tid, cost in tiers],
              tier_allow_fallback=fallback)


def test_group_preferred_tier_funded_when_fits():
    items = [_pool([("t3", 200000), ("t6", 300000)])]
    # all 3 voters prefer the 6ft tier; it fits a 400k envelope
    ballots = [[("pool", "t6")], [("pool", "t6")], [("pool", "t6")]]
    t = bt.tally_project(envelope=400000, min_spend=400000, max_spend=400000,
                         items=items, ballots=ballots)
    assert t.funded == [{"option_id": "pool", "tier_id": "t6", "amount": 300000}]


def test_fallback_to_cheaper_affordable_tier():
    items = [_pool([("t3", 200000), ("t6", 300000)], fallback=True)]
    ballots = [[("pool", "t6")], [("pool", "t6")], [("pool", "t3")]]
    # envelope 250k: 6ft (300k) doesn't fit; fall back to 3ft (200k)
    t = bt.tally_project(envelope=250000, min_spend=250000, max_spend=250000,
                         items=items, ballots=ballots)
    assert t.funded == [{"option_id": "pool", "tier_id": "t3", "amount": 200000}]
    assert t.halt_reason in ("queue_exhausted", "stop_point")


def test_no_fallback_hard_stops():
    items = [
        _pool([("t3", 200000), ("t6", 300000)], fallback=False),
        _I("bench", 10000),  # cheap lower-priority item
    ]
    # pool ranked first (pos 0) by all; bench second. 6ft preferred, doesn't fit
    # 250k, fallback off → hard stop; bench (which would fit) NOT funded.
    ballots = [[("pool", "t6"), "bench"]] * 3
    t = bt.tally_project(envelope=250000, min_spend=250000, max_spend=250000,
                         items=items, ballots=ballots)
    assert t.funded == []
    assert t.halt_reason == "item_did_not_fit"
    assert "bench" in t.unfunded


def test_at_most_one_tier_per_parent():
    items = [_pool([("t3", 200000), ("t6", 300000)])]
    ballots = [[("pool", "t3")], [("pool", "t6")]]
    t = bt.tally_project(envelope=1000000, min_spend=1000000, max_spend=1000000,
                         items=items, ballots=ballots)
    # Exactly one funded entry for the parent (never two tiers).
    pool_funded = [f for f in t.funded if f["option_id"] == "pool"]
    assert len(pool_funded) == 1


def test_plurality_then_lower_cost_then_id():
    # 2 voters want t6, 2 want t3 → tie on count → lower cost (t3) wins.
    items = [_pool([("t3", 200000), ("t6", 300000)])]
    ballots = [[("pool", "t6")], [("pool", "t6")], [("pool", "t3")], [("pool", "t3")]]
    t = bt.tally_project(envelope=1000000, min_spend=1000000, max_spend=1000000,
                         items=items, ballots=ballots)
    assert t.funded[0]["tier_id"] == "t3"  # tie broken by lower cost


def test_plurality_most_selected_wins():
    items = [_pool([("t3", 200000), ("t6", 300000)])]
    ballots = [[("pool", "t6")], [("pool", "t6")], [("pool", "t6")], [("pool", "t3")]]
    t = bt.tally_project(envelope=1000000, min_spend=1000000, max_spend=1000000,
                         items=items, ballots=ballots)
    assert t.funded[0]["tier_id"] == "t6"  # most-selected wins despite higher cost


def test_cumulative_position_uses_selected_tier_cost():
    items = [_pool([("t3", 200000), ("t6", 300000)]), _I("roof", 40000)]
    # one voter: pool(6ft=300k) then roof → roof position = 300k
    t = bt.tally_project(envelope=10**9, min_spend=10**9, max_spend=10**9,
                         items=items, ballots=[[("pool", "t6"), "roof"]])
    assert t.group_positions["roof"] == 300000
    # another voter choosing 3ft → roof position = 200k
    t2 = bt.tally_project(envelope=10**9, min_spend=10**9, max_spend=10**9,
                          items=items, ballots=[[("pool", "t3"), "roof"]])
    assert t2.group_positions["roof"] == 200000


def test_backward_compat_core_fixture_unchanged():
    """A non-tiered fixture through the new signature produces the same outcome
    as the shipped core (§4 worked example). The signature change is the
    riskiest edit; this is the guard."""
    items = [_I("roof", 40000), _I("pool", 80000), _I("land", 30000)]
    ballots_bare = [["roof", "land"], ["roof", "pool"], ["land"], ["roof"], ["land", "roof"]]
    ballots_tuple = [[(o, None) for o in b] for b in ballots_bare]
    t_bare = bt.tally_project(envelope=100000, min_spend=0, max_spend=100000,
                              items=items, ballots=ballots_bare)
    t_tuple = bt.tally_project(envelope=100000, min_spend=0, max_spend=100000,
                               items=items, ballots=ballots_tuple)
    # bare-string and (id, None) ballots are equivalent
    assert t_bare.funded == t_tuple.funded
    # and the §4 outcome is unchanged
    assert {f["option_id"] for f in t_bare.funded} == {"roof", "land"}
    assert t_bare.stop_point == 70000 and t_bare.total_committed == 70000
    assert t_bare.halt_reason == "stop_point"
    assert all(f["tier_id"] is None for f in t_bare.funded)


# ===========================================================================
# Part B — route / integration
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


def _user(db, username):
    u = models.User(username=username, display_name=username, password_hash=_DUMMY_HASH,
                    email=f"{username}@t.ex", email_verified=True)
    db.add(u)
    db.flush()
    return u


def _org(db, slug):
    o = models.Organization(name=slug.title(), slug=slug, description="",
                            settings={"default_voting_days": 7,
                                      "allowed_voting_methods": ["binary", "budget_project"]})
    db.add(o)
    db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _auth(user):
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _setup(db):
    org = _org(db, "tier-org")
    author = _user(db, "t-author")
    v1, v2, v3 = _user(db, "tv1"), _user(db, "tv2"), _user(db, "tv3")
    make_org_membership(db, org_id=org.id, user_id=author.id, role="steward")
    for u in (v1, v2, v3):
        make_org_membership(db, org_id=org.id, user_id=u.id, role="member")
    db.commit()
    return org, author, v1, v2, v3


def _tier_proposal_payload(envelope=400000, fallback=True):
    return {
        "title": "Pool plan", "voting_method": "budget_project",
        "budget_config": {"mode": "project", "envelope": envelope,
                          "min_spend": envelope, "max_spend": envelope},
        "options": [
            {"label": "Pool", "budget_kind": "tier_parent",
             "tier_allow_fallback": fallback,
             "tiers": [
                 {"label": "3ft pool", "budget_floor_amount": 200000},
                 {"label": "6ft pool", "budget_floor_amount": 300000},
             ]},
            {"label": "Bench", "budget_floor_amount": 10000},
        ],
    }


def test_create_tiered_proposal_expands_children(client, test_db):
    org, author, *_ = _setup(test_db)
    r = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author),
                    json=_tier_proposal_payload())
    assert r.status_code in (200, 201), r.text
    opts = r.json()["options"]
    parent = next(o for o in opts if o["budget_kind"] == "tier_parent")
    children = [o for o in opts if o.get("budget_tier_parent_id") == parent["id"]]
    assert parent["budget_floor_amount"] is None  # parent carries no cost
    assert len(children) == 2
    assert {c["budget_floor_amount"] for c in children} == {200000, 300000}


def test_end_to_end_tier_funded_with_fallback(client, test_db):
    org, author, v1, v2, v3 = _setup(test_db)
    # envelope 250k so 6ft (300k) doesn't fit -> fallback to 3ft (200k)
    r = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author),
                    json=_tier_proposal_payload(envelope=250000, fallback=True))
    pid = r.json()["id"]
    opts = {o["label"]: o for o in r.json()["options"]}
    pool = opts["Pool"]["id"]
    t6 = opts["6ft pool"]["id"]
    t3 = opts["3ft pool"]["id"]
    # advance to voting
    client.post(f"/api/proposals/{pid}/advance", headers=_auth(author), json={})
    client.post(f"/api/proposals/{pid}/advance", headers=_auth(author), json={})
    for u in (v1, v2, v3):
        rr = client.post(f"/api/proposals/{pid}/vote", headers=_auth(u),
                         json={"ranked": [{"option_id": pool, "tier_id": t6}]})
        assert rr.status_code == 200, rr.text
    client.post(f"/api/proposals/{pid}/advance", headers=_auth(author), json={})
    res = client.get(f"/api/proposals/{pid}/results", headers=_auth(author)).json()
    funded = res["project_funded"]
    pool_funded = [f for f in funded if f["option_id"] == pool]
    assert len(pool_funded) == 1
    assert pool_funded[0]["tier_id"] == t3  # fell back to the affordable tier
    assert pool_funded[0]["amount"] == 200000


def test_vote_rejects_two_tiers_of_one_parent(client, test_db):
    org, author, v1, *_ = _setup(test_db)
    r = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author),
                    json=_tier_proposal_payload())
    pid = r.json()["id"]
    opts = {o["label"]: o for o in r.json()["options"]}
    pool, t3, t6 = opts["Pool"]["id"], opts["3ft pool"]["id"], opts["6ft pool"]["id"]
    client.post(f"/api/proposals/{pid}/advance", headers=_auth(author), json={})
    client.post(f"/api/proposals/{pid}/advance", headers=_auth(author), json={})
    rr = client.post(f"/api/proposals/{pid}/vote", headers=_auth(v1), json={
        "ranked": [{"option_id": pool, "tier_id": t3}, {"option_id": pool, "tier_id": t6}],
    })
    # Rejected as a duplicate parent (schema 422) or at-most-one-tier (route 400).
    assert rr.status_code in (400, 422), rr.text


def test_vote_rejects_tier_id_not_of_parent(client, test_db):
    org, author, v1, *_ = _setup(test_db)
    r = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author),
                    json=_tier_proposal_payload())
    pid = r.json()["id"]
    opts = {o["label"]: o for o in r.json()["options"]}
    pool, bench = opts["Pool"]["id"], opts["Bench"]["id"]
    client.post(f"/api/proposals/{pid}/advance", headers=_auth(author), json={})
    client.post(f"/api/proposals/{pid}/advance", headers=_auth(author), json={})
    # bench is not a tier of pool
    rr = client.post(f"/api/proposals/{pid}/vote", headers=_auth(v1),
                     json={"ranked": [{"option_id": pool, "tier_id": bench}]})
    assert rr.status_code == 400, rr.text


def test_vote_rejects_ranking_tier_child_directly(client, test_db):
    org, author, v1, *_ = _setup(test_db)
    r = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author),
                    json=_tier_proposal_payload())
    pid = r.json()["id"]
    opts = {o["label"]: o for o in r.json()["options"]}
    t3 = opts["3ft pool"]["id"]
    client.post(f"/api/proposals/{pid}/advance", headers=_auth(author), json={})
    client.post(f"/api/proposals/{pid}/advance", headers=_auth(author), json={})
    rr = client.post(f"/api/proposals/{pid}/vote", headers=_auth(v1),
                     json={"ranked": [{"option_id": t3}]})
    assert rr.status_code == 400, rr.text


def test_create_rejects_tier_parent_with_own_cost(client, test_db):
    org, author, *_ = _setup(test_db)
    payload = _tier_proposal_payload()
    payload["options"][0]["budget_floor_amount"] = 50000  # parent must not have cost
    r = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author), json=payload)
    assert r.status_code == 400, r.text
    assert "cost" in r.json()["detail"].lower()


def test_create_rejects_tier_parent_with_no_tiers(client, test_db):
    org, author, *_ = _setup(test_db)
    payload = _tier_proposal_payload()
    payload["options"][0]["tiers"] = []
    r = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author), json=payload)
    assert r.status_code == 400, r.text
    assert "tier" in r.json()["detail"].lower()


def test_create_rejects_top_level_tier_parent_id(client, test_db):
    org, author, *_ = _setup(test_db)
    r = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author), json={
        "title": "x", "voting_method": "budget_project",
        "budget_config": {"mode": "project", "envelope": 100000},
        "options": [
            {"label": "a", "budget_floor_amount": 10000},
            {"label": "b", "budget_floor_amount": 10000, "budget_tier_parent_id": "deadbeef"},
        ],
    })
    assert r.status_code == 400, r.text


def test_optionout_surfaces_tier_columns(client, test_db):
    import schemas
    for f in ("budget_kind", "budget_tier_parent_id", "tier_allow_fallback"):
        assert f in schemas.OptionOut.model_fields
