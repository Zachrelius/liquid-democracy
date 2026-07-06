"""Phase 88a — Weighted ranked-choice voting (ballot duplication + cap guard).

Covers:
  * Parity: weighted-off RCV is byte-identical to the historical headcount
    tally (round counts + winners).
  * Weighted RCV: a heavier voter's ranking wins IRV via ballot duplication;
    counters are weight-denominated.
  * Zero-weight voter: excluded from the pyrankvote ballots but flows through
    the counters.
  * Cap: creation-time block when the org's total weight exceeds the cap.
  * Cap: tally returns weighted_ballot_cap_exceeded (no OOM) and the close
    routes the proposal to ``unresolved`` + audits.
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
ON = {"enabled": True, "unit_label": "shares"}


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


def _user(db, name):
    u = models.User(username=name, display_name=name, password_hash=_DUMMY_HASH,
                    email=f"{name}@t.ex", email_verified=True)
    db.add(u); db.flush(); return u


def _org(db, slug="rcv-org", weighted=None):
    s = {"default_voting_days": 7,
         "allowed_voting_methods": ["binary", "approval", "ranked_choice"]}
    if weighted is not None:
        s["weighted_voting"] = weighted
    o = models.Organization(name=slug.title(), slug=slug, description="", settings=s)
    db.add(o); db.flush(); seed_default_roles_for_org(db, o.id); return o


def _member(db, org, name, *, role="member", weight=1):
    u = _user(db, name)
    m = make_org_membership(db, org_id=org.id, user_id=u.id, role=role)
    m.voting_weight = weight
    db.flush()
    return u, m


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _rcv_proposal(db, author, org, labels=("A", "B", "C"), *, quorum=0.0):
    p = models.Proposal(
        title="RCV", body="", author_id=author.id, org_id=org.id,
        voting_method="ranked_choice", num_winners=1, status="voting",
        voting_start=_now(), voting_end=_now() + timedelta(days=7),
        quorum_threshold=quorum, pass_threshold=0.5,
    )
    db.add(p); db.flush()
    opts = []
    for i, lab in enumerate(labels):
        o = models.ProposalOption(proposal_id=p.id, label=lab, description="",
                                  display_order=i)
        db.add(o); opts.append(o)
    db.flush()
    return p, opts


def _rank(client, p, user, *oids):
    return client.post(f"/api/proposals/{p.id}/vote", headers=_auth(user),
                       json={"ranking": list(oids)})


# ---------------------------------------------------------------------------
# Parity
# ---------------------------------------------------------------------------

def test_weighted_off_rcv_parity(client, test_db):
    org = _org(test_db)  # weighted off
    author, _ = _member(test_db, org, "auth", role="steward")
    (v1, _) = _member(test_db, org, "v1", weight=9)
    (v2, _) = _member(test_db, org, "v2", weight=4)
    (v3, _) = _member(test_db, org, "v3", weight=2)
    p, opts = _rcv_proposal(test_db, author, org)
    a, b, c = [o.id for o in opts]
    test_db.commit()
    _rank(client, p, v1, a, b, c)
    _rank(client, p, v2, b, a, c)
    _rank(client, p, v3, b, c, a)
    tally = delegation_engine.engine.compute_tally(p, test_db)
    # headcount: 3 ballots cast; stored weights ignored (weighted off).
    assert tally.total_ballots_cast == 3
    assert tally.total_eligible == 4  # author + 3 voters
    assert tally.winners == [b]  # B has 2 first-choices of 3


# ---------------------------------------------------------------------------
# Weighted RCV
# ---------------------------------------------------------------------------

def test_weighted_rcv_heavy_voter_wins(client, test_db):
    """A single heavy voter's first choice wins IRV via ballot duplication."""
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    (heavy, _) = _member(test_db, org, "heavy", weight=10)
    (l1, _) = _member(test_db, org, "l1", weight=1)
    (l2, _) = _member(test_db, org, "l2", weight=1)
    p, opts = _rcv_proposal(test_db, author, org)
    a, b, c = [o.id for o in opts]
    test_db.commit()
    _rank(client, p, heavy, a, b, c)   # 10 ballots for A-first
    _rank(client, p, l1, b, c, a)       # 1 ballot for B-first
    _rank(client, p, l2, c, b, a)       # 1 ballot for C-first
    tally = delegation_engine.engine.compute_tally(p, test_db)
    assert tally.total_ballots_cast == 12  # 10 + 1 + 1 shares
    assert tally.winners == [a]           # A has majority of shares
    # Round 0 first-choice counts are share-denominated.
    assert tally.rounds[0].option_counts[a] == 10.0


def test_weighted_rcv_zero_weight_excluded(client, test_db):
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    (v1, _) = _member(test_db, org, "v1", weight=3)
    (zero, _) = _member(test_db, org, "zero", weight=0)
    p, opts = _rcv_proposal(test_db, author, org)
    a, b, c = [o.id for o in opts]
    test_db.commit()
    _rank(client, p, v1, a, b, c)
    _rank(client, p, zero, b, c, a)  # zero-weight: no ballots contributed
    tally = delegation_engine.engine.compute_tally(p, test_db)
    assert tally.total_ballots_cast == 3  # v1's 3 shares; zero adds nothing
    assert tally.winners == [a]
    assert tally.rounds[0].option_counts[a] == 3.0
    assert tally.rounds[0].option_counts.get(b, 0.0) == 0.0


# ---------------------------------------------------------------------------
# Cap guard
# ---------------------------------------------------------------------------

def test_rcv_creation_blocked_over_cap(client, test_db):
    """RCV creation 400s when the org's total weight exceeds the cap."""
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward", weight=100000)
    _member(test_db, org, "big1", weight=100000)
    _member(test_db, org, "big2", weight=100000)  # total 300000 > 200000
    test_db.commit()
    r = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author), json={
        "title": "rcv", "voting_method": "ranked_choice",
        "options": [{"label": "A"}, {"label": "B"}],
    })
    assert r.status_code == 400, r.text
    assert "cap" in r.json()["detail"].lower()


def test_rcv_tally_cap_exceeded_flag_and_unresolved(client, test_db):
    """An org that grows past the cap AFTER RCV creation: the tally skips
    tabulation (flag set, no OOM) and the close routes to unresolved + audit."""
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    (v1, m1) = _member(test_db, org, "v1", weight=1)
    p, opts = _rcv_proposal(test_db, author, org, quorum=0.0)
    a, b, c = [o.id for o in opts]
    test_db.commit()
    _rank(client, p, v1, a, b, c)
    # Grow v1's weight past the cap AFTER creation + voting.
    m1.voting_weight = delegation_engine.RCV_WEIGHTED_BALLOT_CAP + 5
    test_db.commit()
    tally = delegation_engine.engine.compute_tally(p, test_db)
    assert tally.weighted_ballot_cap_exceeded is True
    assert tally.winners == []  # tabulation skipped, no OOM
    # Close routes to unresolved + audits the cap event.
    r = client.post(f"/api/proposals/{p.id}/advance", headers=_auth(author), json={})
    assert r.status_code == 200, r.text
    test_db.refresh(p)
    assert p.status == "unresolved"
    audit = test_db.query(models.AuditLog).filter(
        models.AuditLog.action == "rcv.weighted_ballot_cap_exceeded",
    ).all()
    assert len(audit) == 1
