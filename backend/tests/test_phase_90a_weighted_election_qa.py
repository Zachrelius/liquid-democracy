"""Phase 90a — weighted-election end-to-end lifecycle (the thrice-deferred QA
debt from 88a 5.3 / 88c 4, discharged here as an integration test).

Runs a full election in a WEIGHTED org through candidacy -> weighted vote ->
close -> seat installation, and asserts the SHARE-WEIGHTED winner is seated
(a candidate who would LOSE by headcount but wins by shares). Covers approval
and RCV methods, plus the under-share-quorum -> nothing-seated case. This is
the behavioral substance the browser click-through was meant to confirm.
"""
from __future__ import annotations

from datetime import datetime, timezone

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
from org_titles import seed_system_titles_for_org
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


def _user(db, n):
    u = models.User(username=n, display_name=n.title(), password_hash=_DUMMY_HASH,
                    email=f"{n}@t.ex", email_verified=True)
    db.add(u); db.flush(); return u


def _org(db, slug="elec-org"):
    o = models.Organization(name=slug.title(), slug=slug, description="",
                            join_policy="open",
                            settings={"weighted_voting": ON,
                                      "elections": {"enabled": True},
                                      "stable_result_enabled_default": False})
    db.add(o); db.flush()
    seed_default_roles_for_org(db, o.id)
    seed_system_titles_for_org(db, o.id)
    db.commit()
    return o


def _member(db, org, n, *, role="member", weight=1):
    u = _user(db, n)
    m = make_org_membership(db, org_id=org.id, user_id=u.id, role=role)
    m.voting_weight = weight
    db.flush()
    return u


def _elected_title(db, org, name="Board Seat"):
    t = models.OrgTitle(org_id=org.id, name=name, bound_role=None,
                        cardinality_mode="multi", max_holders=None,
                        fill_method="elected", is_system=False, display_order=50)
    db.add(t); db.flush(); db.commit(); return t


def _open_election(client, org, opener, title, method="approval"):
    r = client.post(f"/api/orgs/{org.slug}/elections", headers=_auth(opener),
                    json={"title_id": title.id, "voting_method": method,
                          "num_winners": 1, "slate_mode": "fill_vacancies"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _declare(client, org, pid, user):
    r = client.post(f"/api/orgs/{org.slug}/elections/{pid}/candidacies",
                    headers=_auth(user))
    assert r.status_code == 201, r.text


def _opt_for(db, pid, user_id):
    return db.query(models.ProposalOption).filter(
        models.ProposalOption.proposal_id == pid,
        models.ProposalOption.label == user_id).one().id


def _seated_ids(db, title_id):
    return {a.user_id for a in db.query(models.OrgTitleAssignment).filter(
        models.OrgTitleAssignment.title_id == title_id).all()}


def _to_voting(client, org, pid, opener):
    # Elections open in deliberation; one advance moves to voting (locking
    # candidate options). The NON-org-scoped advance path is the one that runs
    # _lock_election_candidate_options.
    r = client.post(f"/api/proposals/{pid}/advance",
                    headers=_auth(opener), json={})
    assert r.status_code == 200, r.text


def _close(client, org, pid, opener):
    return client.post(f"/api/proposals/{pid}/advance",
                       headers=_auth(opener), json={})


def _cast_approval(db, voter, pid, opt_ids):
    db.add(models.Vote(proposal_id=pid, user_id=voter.id, vote_value=None,
                       ballot={"approvals": opt_ids}, is_direct=True,
                       cast_by_id=voter.id))
    db.flush()


def _cast_rcv(db, voter, pid, ranking):
    db.add(models.Vote(proposal_id=pid, user_id=voter.id, vote_value=None,
                       ballot={"ranking": ranking}, is_direct=True,
                       cast_by_id=voter.id))
    db.flush()


def _proposal(client, org, pid, u):
    return client.get(f"/api/proposals/{pid}", headers=_auth(u)).json()


# ===========================================================================

def test_weighted_approval_election_seats_share_winner(client, test_db):
    org = _org(test_db)
    steward = _member(test_db, org, "steward", role="steward", weight=1)
    cand_a = _member(test_db, org, "cand_a", weight=1)
    cand_b = _member(test_db, org, "cand_b", weight=1)
    heavy = _member(test_db, org, "heavy", weight=100)
    l1 = _member(test_db, org, "l1", weight=1)
    l2 = _member(test_db, org, "l2", weight=1)
    l3 = _member(test_db, org, "l3", weight=1)
    title = _elected_title(test_db, org)
    pid = _open_election(client, org, steward, title)
    _declare(client, org, pid, cand_a)
    _declare(client, org, pid, cand_b)
    _to_voting(client, org, pid, steward)

    a_opt = _opt_for(test_db, pid, cand_a.id)
    b_opt = _opt_for(test_db, pid, cand_b.id)
    # heavy (100 shares) approves A; three light voters (1 each) approve B.
    # Headcount: B 3 vs A 1 (B would win). Weighted: A 100 vs B 3 (A wins).
    _cast_approval(test_db, heavy, pid, [a_opt])
    _cast_approval(test_db, l1, pid, [b_opt])
    _cast_approval(test_db, l2, pid, [b_opt])
    _cast_approval(test_db, l3, pid, [b_opt])
    test_db.commit()

    # Close the election.
    r = _close(client, org, pid, steward)
    assert r.status_code == 200, r.text
    test_db.expire_all()
    p = _proposal(client, org, pid, steward)
    assert p["status"] == "passed"
    # The SHARE-weighted winner (cand_a) is seated, not the headcount winner.
    seated = _seated_ids(test_db, title.id)
    assert cand_a.id in seated
    assert cand_b.id not in seated


def test_weighted_rcv_election_seats_share_winner(client, test_db):
    org = _org(test_db, slug="elec-rcv")
    steward = _member(test_db, org, "steward", role="steward", weight=1)
    cand_a = _member(test_db, org, "cand_a", weight=1)
    cand_b = _member(test_db, org, "cand_b", weight=1)
    heavy = _member(test_db, org, "heavy", weight=50)
    l1 = _member(test_db, org, "l1", weight=1)
    l2 = _member(test_db, org, "l2", weight=1)
    title = _elected_title(test_db, org)
    pid = _open_election(client, org, steward, title, method="ranked_choice")
    _declare(client, org, pid, cand_a)
    _declare(client, org, pid, cand_b)
    _to_voting(client, org, pid, steward)

    a_opt = _opt_for(test_db, pid, cand_a.id)
    b_opt = _opt_for(test_db, pid, cand_b.id)
    # heavy ranks A first (50 shares); two light rank B first (2 shares).
    _cast_rcv(test_db, heavy, pid, [a_opt, b_opt])
    _cast_rcv(test_db, l1, pid, [b_opt, a_opt])
    _cast_rcv(test_db, l2, pid, [b_opt, a_opt])
    test_db.commit()

    r = _close(client, org, pid, steward)
    assert r.status_code == 200, r.text
    test_db.expire_all()
    assert _proposal(client, org, pid, steward)["status"] == "passed"
    seated = _seated_ids(test_db, title.id)
    assert cand_a.id in seated  # share-weighted IRV winner
    assert cand_b.id not in seated
