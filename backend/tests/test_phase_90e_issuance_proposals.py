"""Phase 90e — vote-gated share issuance (member_vote mode).

Verification matrix (spec: phase90c_90e_corporate_completion_spec.md §3.3):
  * Close-hook side effects: a passed issuance vote executes the payload (weight
    row + ShareEvent carrying authorization_ref='proposal:<id>' + issuance_executed
    =True + audit); a failed/under-quorum vote executes nothing (issuance_executed
    =False, no ShareEvent). Drift at close (target left the org) → passed but
    issuance_executed=False + share.issuance_execution_failed audit + author notif.
    Both manual-advance and worker close paths.
  * Forced-weighted lock; creation gates (mode, permission, cap-breach 400).
  * Mode ladder: direct→multi_admin→member_vote all unilateral upward; the direct
    issuance endpoints reject under member_vote (must use an issuance proposal).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from main import app
from role_seed import seed_default_roles_for_org
from tests.conftest import make_org_membership

_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


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


def _org(db, slug, *, mode="member_vote", cap=None):
    wv = {"enabled": True, "unit_label": "shares", "issuance_mode": mode}
    if cap is not None:
        wv["authorized_total"] = cap
    o = models.Organization(name=slug.title(), slug=slug, description="",
                            settings={"default_voting_days": 7, "weighted_voting": wv})
    db.add(o); db.flush(); seed_default_roles_for_org(db, o.id); return o


def _member(db, org, n, *, role="member", weight=1):
    u = _user(db, n)
    m = make_org_membership(db, org_id=org.id, user_id=u.id, role=role)
    m.voting_weight = weight
    db.flush()
    return u, m


def _create_issuance(client, org, author, payload, **kw):
    body = {"title": "Issue shares", "body": "", "issuance_payload": payload,
            "deliberation_days": 0}
    body.update(kw)
    return client.post(f"/api/orgs/{org.slug}/issuance-proposals",
                       headers=_auth(author), json=body)


def _advance(client, org, actor, pid):
    return client.post(f"/api/orgs/{org.slug}/proposals/{pid}/advance",
                       headers=_auth(actor), json={})


# ===========================================================================
# Creation gates
# ===========================================================================

def test_create_requires_member_vote_mode(client, test_db):
    org = _org(test_db, "cg1", mode="direct")
    steward, _ = _member(test_db, org, "stew", role="steward", weight=1)
    _, tm = _member(test_db, org, "t", weight=1)
    test_db.commit()
    r = _create_issuance(client, org, steward,
                         {"action": "set_weight", "params": {"target_user_id": tm.user_id, "new_weight": 5}})
    assert r.status_code == 400, r.text


def test_create_requires_permission(client, test_db):
    org = _org(test_db, "cg2", mode="member_vote")
    steward, _ = _member(test_db, org, "stew", role="steward", weight=1)
    plain, pm = _member(test_db, org, "plain", weight=1)  # no set_voting_weight
    test_db.commit()
    r = _create_issuance(client, org, plain,
                         {"action": "set_weight", "params": {"target_user_id": steward.id, "new_weight": 5}})
    assert r.status_code == 403, r.text


def test_create_forces_weighted_and_binary(client, test_db):
    org = _org(test_db, "cg3", mode="member_vote")
    steward, _ = _member(test_db, org, "stew", role="steward", weight=1)
    _, tm = _member(test_db, org, "t", weight=1)
    test_db.commit()
    r = _create_issuance(client, org, steward,
                         {"action": "set_weight", "params": {"target_user_id": tm.user_id, "new_weight": 5}})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["is_issuance"] is True
    assert body["voting_method"] == "binary"
    assert body["count_mode"] == "weighted"
    assert body["issuance_preview"] is not None  # dilution preview present


def test_create_cap_breach_rejected(client, test_db):
    org = _org(test_db, "cg4", mode="member_vote", cap=10)
    steward, _ = _member(test_db, org, "stew", role="steward", weight=1)
    _, tm = _member(test_db, org, "t", weight=1)  # outstanding = 2
    test_db.commit()
    # Raising tm to 50 → outstanding 51 > cap 10 → creation 400.
    r = _create_issuance(client, org, steward,
                         {"action": "set_weight", "params": {"target_user_id": tm.user_id, "new_weight": 50}})
    assert r.status_code == 400, r.text


# ===========================================================================
# Close-hook side effects
# ===========================================================================

def _pass_vote(client, test_db, org, pid, voter):
    # Put in voting, cast a yes, then advance to close.
    p = test_db.get(models.Proposal, pid)
    p.status = "voting"
    p.voting_start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    test_db.commit()
    client.post(f"/api/proposals/{pid}/vote", headers=_auth(voter), json={"vote_value": "yes"})


def test_passed_vote_executes(client, test_db):
    org = _org(test_db, "ex1", mode="member_vote")
    steward, _ = _member(test_db, org, "stew", role="steward", weight=5)
    _, tm = _member(test_db, org, "t", weight=1)
    test_db.commit()
    pid = _create_issuance(client, org, steward,
                           {"action": "set_weight", "params": {"target_user_id": tm.user_id, "new_weight": 9}}).json()["id"]
    _pass_vote(client, test_db, org, pid, steward)
    r = _advance(client, org, steward, pid)
    assert r.status_code == 200, r.text
    test_db.refresh(tm)
    assert tm.voting_weight == 9  # executed
    p = test_db.get(models.Proposal, pid)
    assert p.status == "passed"
    assert p.issuance_executed is True
    ev = test_db.query(models.ShareEvent).filter(
        models.ShareEvent.org_id == org.id,
        models.ShareEvent.event_type == "admin_set").first()
    assert ev is not None and ev.authorization_ref == f"proposal:{pid}"
    assert test_db.query(models.AuditLog).filter(
        models.AuditLog.action == "share.issuance_executed").count() == 1


def test_failed_vote_no_execution(client, test_db):
    org = _org(test_db, "ex2", mode="member_vote")
    steward, _ = _member(test_db, org, "stew", role="steward", weight=1)
    _, tm = _member(test_db, org, "t", weight=1)
    test_db.commit()
    pid = _create_issuance(client, org, steward,
                           {"action": "set_weight", "params": {"target_user_id": tm.user_id, "new_weight": 9}}).json()["id"]
    # Put in voting, cast a NO, advance → failed.
    p = test_db.get(models.Proposal, pid)
    p.status = "voting"
    p.voting_start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    test_db.commit()
    client.post(f"/api/proposals/{pid}/vote", headers=_auth(steward), json={"vote_value": "no"})
    r = _advance(client, org, steward, pid)
    assert r.status_code == 200, r.text
    test_db.refresh(tm)
    assert tm.voting_weight == 1  # unchanged
    p = test_db.get(models.Proposal, pid)
    assert p.status == "failed"
    assert p.issuance_executed is False
    assert test_db.query(models.ShareEvent).filter(
        models.ShareEvent.org_id == org.id).count() == 0


def test_drift_at_close_passes_but_fails_execution(client, test_db):
    org = _org(test_db, "ex3", mode="member_vote")
    steward, _ = _member(test_db, org, "stew", role="steward", weight=5)
    tuser, tm = _member(test_db, org, "t", weight=1)
    test_db.commit()
    # Opt the author into in-app issuance-failed notifications (opt-in default).
    test_db.add(models.NotificationPreference(
        user_id=steward.id, event_type="shares.issuance_failed",
        channel="in_app", enabled=True))
    pid = _create_issuance(client, org, steward,
                           {"action": "set_weight", "params": {"target_user_id": tm.user_id, "new_weight": 9}}).json()["id"]
    _pass_vote(client, test_db, org, pid, steward)
    # Target leaves the org before close (drift).
    test_db.delete(tm)
    test_db.commit()
    r = _advance(client, org, steward, pid)
    assert r.status_code == 200, r.text
    p = test_db.get(models.Proposal, pid)
    assert p.status == "passed"           # the vote passed
    assert p.issuance_executed is False   # but execution drifted
    assert test_db.query(models.AuditLog).filter(
        models.AuditLog.action == "share.issuance_execution_failed").count() == 1
    # Author notified.
    assert test_db.query(models.Notification).filter(
        models.Notification.event_type == "shares.issuance_failed",
        models.Notification.user_id == steward.id).count() == 1


def test_worker_close_executes(client, test_db):
    """The worker close path runs the issuance hook too."""
    from sustained_majority_worker import _close_proposal_now
    org = _org(test_db, "ex4", mode="member_vote")
    steward, _ = _member(test_db, org, "stew", role="steward", weight=5)
    _, tm = _member(test_db, org, "t", weight=1)
    test_db.commit()
    pid = _create_issuance(client, org, steward,
                           {"action": "set_weight", "params": {"target_user_id": tm.user_id, "new_weight": 7}}).json()["id"]
    p = test_db.get(models.Proposal, pid)
    p.status = "voting"
    p.voting_start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    p.voting_end = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7)
    test_db.commit()
    client.post(f"/api/proposals/{pid}/vote", headers=_auth(steward), json={"vote_value": "yes"})
    # Now the window has elapsed → worker natural close.
    p.voting_end = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
    test_db.commit()
    _close_proposal_now(test_db, p)
    test_db.commit()
    test_db.refresh(tm)
    assert tm.voting_weight == 7
    assert test_db.get(models.Proposal, pid).issuance_executed is True


# ===========================================================================
# Mode ladder — member_vote unilateral upward; direct endpoints reject under it
# ===========================================================================

def test_strengthen_to_member_vote_unilateral(client, test_db):
    org = _org(test_db, "lad1", mode="multi_admin")
    steward, _ = _member(test_db, org, "stew", role="steward", weight=1)
    a2, _ = _member(test_db, org, "adm2", role="admin", weight=1)
    test_db.commit()
    r = client.patch(f"/api/orgs/{org.slug}", headers=_auth(steward),
                     json={"settings": {"weighted_voting": {"issuance_mode": "member_vote"}}})
    assert r.status_code == 200, r.text
    from org_config import get_weighted_voting_config
    test_db.refresh(org)
    assert get_weighted_voting_config(org)["issuance_mode"] == "member_vote"


def test_direct_weight_patch_rejected_under_member_vote(client, test_db):
    org = _org(test_db, "lad2", mode="member_vote")
    steward, _ = _member(test_db, org, "stew", role="steward", weight=1)
    _, tm = _member(test_db, org, "t", weight=1)
    test_db.commit()
    r = client.patch(f"/api/orgs/{org.slug}/members/{tm.user_id}/voting-weight",
                     headers=_auth(steward), json={"voting_weight": 5})
    assert r.status_code == 400, r.text
