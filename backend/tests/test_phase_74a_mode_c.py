"""Phase 74a — Mode C (continuous-as-discrete) + drop dead budget_is_mandatory.

Coverage (spec §2.4):
- Continuous-as-discrete funds at full cost when it clears priority + fits;
  funds $0 when it loses priority or doesn't fit (hard-stop still applies).
- Mixed ballot: discrete + continuous-as-discrete compete in one queue.
- Cost resolution: budget_max_amount preferred over budget_floor_amount;
  reject a continuous-as-discrete option with no positive cost.
- Column-drop: ProposalOption has no budget_is_mandatory; round-trips clean.
- Serializer/additive parity: dropping the column changes no response schema.

The column-drop migration cycle lives in test_phase_74a_migration_cycle.py.
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
from delegation_engine import _resolve_project_item_cost
from main import app
from role_seed import seed_default_roles_for_org
from tests.conftest import make_org_membership

_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"
_I = bt.ProjectItemSpec


# ===========================================================================
# Part A — Mode C at the tally level (continuous-as-discrete = plain discrete)
# ===========================================================================

def test_continuous_as_discrete_funds_full_when_it_fits():
    # 'land' is continuous-as-discrete with cost 30k (resolved at the adapter).
    items = [_I("roof", 40000), _I("land", 30000, kind="continuous-as-discrete")]
    ballots = [["roof", "land"], ["roof", "land"], ["land", "roof"]]
    t = bt.tally_project(envelope=100000, min_spend=100000, max_spend=100000,
                         items=items, ballots=ballots)
    funded = {f["option_id"]: f["amount"] for f in t.funded}
    assert funded.get("land") == 30000  # funded at full cost, not partial


def test_continuous_as_discrete_funds_zero_when_it_loses_priority():
    items = [_I("roof", 40000), _I("land", 30000, kind="continuous-as-discrete")]
    # Everyone ranks only roof; land omitted -> median position max_spend.
    ballots = [["roof"], ["roof"], ["roof"]]
    t = bt.tally_project(envelope=100000, min_spend=0, max_spend=100000,
                         items=items, ballots=ballots)
    funded = {f["option_id"] for f in t.funded}
    assert "land" not in funded  # $0 — lost priority, accepted behavior
    assert "land" in t.unfunded


def test_mixed_discrete_and_continuous_one_queue():
    items = [
        _I("roof", 40000),
        _I("land", 30000, kind="continuous-as-discrete"),
        _I("pool", 80000),
    ]
    ballots = [["roof", "land"], ["roof", "land"], ["land", "roof"], ["roof"]]
    t = bt.tally_project(envelope=100000, min_spend=100000, max_spend=100000,
                         items=items, ballots=ballots)
    funded = {f["option_id"] for f in t.funded}
    # roof + land = 70k fit; pool (80k) would push to 150k > envelope -> halt.
    assert "roof" in funded and "land" in funded
    assert "pool" not in funded


# ===========================================================================
# Part B — cost resolution at the route adapter
# ===========================================================================

class _Opt:
    def __init__(self, **kw):
        self.budget_kind = kw.get("budget_kind")
        self.budget_floor_amount = kw.get("budget_floor_amount")
        self.budget_max_amount = kw.get("budget_max_amount")


def test_cost_resolution_prefers_max_amount_for_continuous():
    opt = _Opt(budget_kind="continuous-as-discrete",
               budget_max_amount=30000, budget_floor_amount=99999)
    assert _resolve_project_item_cost(opt) == 30000


def test_cost_resolution_falls_back_to_floor_for_continuous():
    opt = _Opt(budget_kind="continuous-as-discrete", budget_floor_amount=25000)
    assert _resolve_project_item_cost(opt) == 25000


def test_cost_resolution_discrete_uses_floor():
    opt = _Opt(budget_kind="discrete", budget_floor_amount=40000,
               budget_max_amount=99999)
    assert _resolve_project_item_cost(opt) == 40000


# ===========================================================================
# Part C — HTTP create validation + serializer parity
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
    org = _org(db, "modec-org")
    author = _user(db, "mc-author")
    make_org_membership(db, org_id=org.id, user_id=author.id, role="steward")
    db.commit()
    return org, author


def test_create_continuous_as_discrete_round_trips(client, test_db):
    org, author = _setup(test_db)
    r = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author), json={
        "title": "Capital plan", "voting_method": "budget_project",
        "budget_config": {"mode": "project", "envelope": 100000},
        "options": [
            {"label": "Roof", "budget_floor_amount": 40000, "budget_kind": "discrete"},
            {"label": "Landscaping", "budget_max_amount": 30000,
             "budget_kind": "continuous-as-discrete"},
        ],
    })
    assert r.status_code in (200, 201), r.text
    opts = {o["label"]: o for o in r.json()["options"]}
    assert opts["Landscaping"]["budget_kind"] == "continuous-as-discrete"
    assert opts["Landscaping"]["budget_max_amount"] == 30000
    # The dropped column must not appear on the response.
    assert "budget_is_mandatory" not in opts["Landscaping"]


def test_continuous_without_cost_rejected(client, test_db):
    org, author = _setup(test_db)
    r = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author), json={
        "title": "x", "voting_method": "budget_project",
        "budget_config": {"mode": "project", "envelope": 100000},
        "options": [
            {"label": "Roof", "budget_floor_amount": 40000},
            {"label": "Vague", "budget_kind": "continuous-as-discrete"},  # no cost
        ],
    })
    assert r.status_code == 400, r.text
    assert "continuous" in r.json()["detail"].lower()


def test_tier_still_rejected_in_74a(client, test_db):
    """Cost tiers are 74b — still rejected after 74a."""
    org, author = _setup(test_db)
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


def test_proposaloption_has_no_mandatory_column():
    """The dead column is gone from the model."""
    cols = {c.name for c in models.ProposalOption.__table__.columns}
    assert "budget_is_mandatory" not in cols
    # The other Phase-74 columns remain.
    assert {"budget_floor_amount", "budget_kind", "budget_tier_parent_id",
            "tier_allow_fallback"} <= cols


def test_optionout_has_no_mandatory_field():
    import schemas
    assert "budget_is_mandatory" not in schemas.OptionOut.model_fields
    assert "budget_is_mandatory" not in schemas.OptionCreate.model_fields


def test_end_to_end_continuous_funds_full_via_http(client, test_db):
    """A continuous-as-discrete item that clears priority funds at its full
    ceiling through the real tally + results endpoint."""
    org, author = _setup(test_db)
    v1, v2, v3 = _user(test_db, "v1"), _user(test_db, "v2"), _user(test_db, "v3")
    for u in (v1, v2, v3):
        make_org_membership(test_db, org_id=org.id, user_id=u.id, role="member")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    p = models.Proposal(
        title="P", body="", author_id=author.id, org_id=org.id,
        voting_method="budget_project", num_winners=1, status="voting",
        voting_start=now, voting_end=now + timedelta(days=7),
        quorum_threshold=0.4, pass_threshold=0.5,
        budget_config={"mode": "project", "envelope": 100000, "currency": "USD",
                       "min_spend": 100000, "max_spend": 100000},
    )
    test_db.add(p)
    test_db.flush()
    roof = models.ProposalOption(proposal_id=p.id, label="Roof", description="",
                                 display_order=0, budget_floor_amount=40000,
                                 budget_kind="discrete")
    land = models.ProposalOption(proposal_id=p.id, label="Land", description="",
                                 display_order=1, budget_max_amount=30000,
                                 budget_kind="continuous-as-discrete")
    test_db.add_all([roof, land])
    test_db.commit()
    for u in (v1, v2, v3):
        client.post(f"/api/proposals/{p.id}/vote", headers=_auth(u),
                    json={"ranked": [{"option_id": roof.id}, {"option_id": land.id}]})
    client.post(f"/api/proposals/{p.id}/advance", headers=_auth(author), json={})
    res = client.get(f"/api/proposals/{p.id}/results", headers=_auth(author)).json()
    funded = {f["option_id"]: f["amount"] for f in res["project_funded"]}
    assert funded.get(land.id) == 30000
