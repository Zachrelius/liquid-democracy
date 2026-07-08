"""Phase 90d — issuance authorization ladder (direct | multi_admin) + cap.

Verification matrix (spec: phase90c_90e_corporate_completion_spec.md §2.5):
  * Ratification side effects: weight PATCH under multi_admin submits a pending
    action (no mutation yet); a second approval executes it → weight row +
    ShareEvent carrying authorization_ref='pending_action:<id>' + audit. Decline
    leaves everything untouched. Drift (target left the org) → failed, no mutation.
  * Ladder invariant: strengthening (direct→multi_admin) is a unilateral settings
    PATCH; weakening (multi_admin→direct) via the direct PATCH → 400 (route to the
    share.issuance_mode_weaken pending action, which executes on ratification).
  * Degenerate approver set: mode-select 409 (fewer than two holders) + submit-time
    409 (holders dropped to one).
  * Cap: exactly-at-cap succeeds; over-cap 400; lowering below outstanding 400;
    transfers ignore the cap; the distribution sweep skips over-cap grants without
    consuming the period_key (retries when headroom appears) + one batched audit.
  * Existing-org parity: the new action types resolve approver sets correctly.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

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


def _org(db, slug, *, mode="direct", cap=None, enabled=True):
    wv = {"enabled": enabled, "unit_label": "shares", "issuance_mode": mode}
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


def _weight_patch(client, org, actor, target_id, w):
    return client.patch(f"/api/orgs/{org.slug}/members/{target_id}/voting-weight",
                        headers=_auth(actor), json={"voting_weight": w})


def _approve(client, org, actor, pending_id):
    return client.post(
        f"/api/orgs/{org.slug}/admin/pending-actions/{pending_id}/approve",
        headers=_auth(actor), json={})


# ===========================================================================
# Direct mode — status quo (no ratification)
# ===========================================================================

def test_direct_mode_executes_immediately(client, test_db):
    org = _org(test_db, "d1", mode="direct")
    steward, _ = _member(test_db, org, "stew", role="steward", weight=1)
    _, tm = _member(test_db, org, "t", weight=1)
    test_db.commit()
    r = _weight_patch(client, org, steward, tm.user_id, 5)
    assert r.status_code == 200, r.text
    assert r.json().get("voting_weight") == 5
    test_db.refresh(tm)
    assert tm.voting_weight == 5


# ===========================================================================
# Multi-admin ratification side effects
# ===========================================================================

def test_multi_admin_weight_set_needs_two(client, test_db):
    org = _org(test_db, "m1", mode="multi_admin")
    steward, _ = _member(test_db, org, "stew", role="steward", weight=1)
    a2, _ = _member(test_db, org, "adm2", role="admin", weight=1)
    _, tm = _member(test_db, org, "t", weight=1)
    test_db.commit()
    # First submit → pending, no mutation.
    r = _weight_patch(client, org, steward, tm.user_id, 9)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "pending", body
    pid = body["pending_action"]["id"]
    test_db.refresh(tm)
    assert tm.voting_weight == 1  # unchanged

    # Second approval executes.
    r2 = _approve(client, org, a2, pid)
    assert r2.status_code == 200, r2.text
    test_db.refresh(tm)
    assert tm.voting_weight == 9
    # ShareEvent carries authorization_ref='pending_action:<id>'.
    ev = test_db.query(models.ShareEvent).filter(
        models.ShareEvent.org_id == org.id,
        models.ShareEvent.event_type == "admin_set").first()
    assert ev is not None
    assert ev.authorization_ref == f"pending_action:{pid}"
    # Executed audit row present.
    assert test_db.query(models.AuditLog).filter(
        models.AuditLog.action == "pending_admin_action.executed").count() == 1


def test_multi_admin_decline_no_mutation(client, test_db):
    org = _org(test_db, "m2", mode="multi_admin")
    steward, _ = _member(test_db, org, "stew", role="steward", weight=1)
    a2, _ = _member(test_db, org, "adm2", role="admin", weight=1)
    _, tm = _member(test_db, org, "t", weight=2)
    test_db.commit()
    pid = _weight_patch(client, org, steward, tm.user_id, 20).json()["pending_action"]["id"]
    r = client.post(f"/api/orgs/{org.slug}/admin/pending-actions/{pid}/decline",
                    headers=_auth(a2), json={"reason": "no"})
    assert r.status_code == 200, r.text
    test_db.refresh(tm)
    assert tm.voting_weight == 2  # untouched
    assert test_db.query(models.ShareEvent).filter(
        models.ShareEvent.org_id == org.id).count() == 0


def test_multi_admin_drift_target_left_fails(client, test_db):
    org = _org(test_db, "m3", mode="multi_admin")
    steward, _ = _member(test_db, org, "stew", role="steward", weight=1)
    a2, _ = _member(test_db, org, "adm2", role="admin", weight=1)
    tuser, tm = _member(test_db, org, "t", weight=2)
    test_db.commit()
    pid = _weight_patch(client, org, steward, tm.user_id, 15).json()["pending_action"]["id"]
    # Target leaves the org between submit and ratify.
    test_db.delete(tm)
    test_db.commit()
    r = _approve(client, org, a2, pid)
    assert r.status_code == 200, r.text
    pa = test_db.get(models.PendingAdminAction, pid)
    assert pa.status == "failed"
    assert test_db.query(models.ShareEvent).filter(
        models.ShareEvent.org_id == org.id).count() == 0


# ===========================================================================
# Degenerate approver set
# ===========================================================================

def test_mode_select_requires_two_holders(client, test_db):
    org = _org(test_db, "deg1", mode="direct")
    steward, _ = _member(test_db, org, "stew", role="steward", weight=1)  # sole holder
    test_db.commit()
    r = client.patch(f"/api/orgs/{org.slug}", headers=_auth(steward),
                     json={"settings": {"weighted_voting": {"issuance_mode": "multi_admin"}}})
    assert r.status_code == 409, r.text


def test_submit_time_requires_two_holders(client, test_db):
    org = _org(test_db, "deg2", mode="multi_admin")
    steward, _ = _member(test_db, org, "stew", role="steward", weight=1)  # sole holder
    _, tm = _member(test_db, org, "t", weight=1)
    test_db.commit()
    r = _weight_patch(client, org, steward, tm.user_id, 5)
    assert r.status_code == 409, r.text


# ===========================================================================
# Ladder invariant — strengthen unilateral, weaken via ratification only
# ===========================================================================

def test_strengthen_is_unilateral(client, test_db):
    org = _org(test_db, "lad1", mode="direct")
    steward, _ = _member(test_db, org, "stew", role="steward", weight=1)
    a2, _ = _member(test_db, org, "adm2", role="admin", weight=1)
    test_db.commit()
    r = client.patch(f"/api/orgs/{org.slug}", headers=_auth(steward),
                     json={"settings": {"weighted_voting": {"issuance_mode": "multi_admin"}}})
    assert r.status_code == 200, r.text
    test_db.refresh(org)
    from org_config import get_weighted_voting_config
    assert get_weighted_voting_config(org)["issuance_mode"] == "multi_admin"


def test_direct_weaken_rejected(client, test_db):
    org = _org(test_db, "lad2", mode="multi_admin")
    steward, _ = _member(test_db, org, "stew", role="steward", weight=1)
    a2, _ = _member(test_db, org, "adm2", role="admin", weight=1)
    test_db.commit()
    r = client.patch(f"/api/orgs/{org.slug}", headers=_auth(steward),
                     json={"settings": {"weighted_voting": {"issuance_mode": "direct"}}})
    assert r.status_code == 400, r.text


def test_weaken_via_ratification(client, test_db):
    org = _org(test_db, "lad3", mode="multi_admin")
    a1, _ = _member(test_db, org, "adm1", role="admin", weight=1)
    a2, _ = _member(test_db, org, "adm2", role="admin", weight=1)
    test_db.commit()
    # Submit share.issuance_mode_weaken via the generic pending endpoint.
    r = client.post(f"/api/orgs/{org.slug}/admin/pending-actions", headers=_auth(a1),
                    json={"action_type": "share.issuance_mode_weaken",
                          "payload": {"new_mode": "direct"}})
    assert r.status_code == 200, r.text
    pid = r.json()["pending_action"]["id"]
    r2 = _approve(client, org, a2, pid)
    assert r2.status_code == 200, r2.text
    test_db.refresh(org)
    from org_config import get_weighted_voting_config
    assert get_weighted_voting_config(org)["issuance_mode"] == "direct"


# ===========================================================================
# Authorized-total cap
# ===========================================================================

def test_cap_boundary_and_breach(client, test_db):
    org = _org(test_db, "cap1", mode="direct", cap=10)
    steward, _ = _member(test_db, org, "stew", role="steward", weight=1)
    _, tm = _member(test_db, org, "t", weight=1)
    # outstanding = 2. Raise tm to 9 → outstanding 10 == cap → OK.
    test_db.commit()
    r = _weight_patch(client, org, steward, tm.user_id, 9)
    assert r.status_code == 200, r.text
    # Now raise steward to 3 → outstanding 12 > cap 10 → 400.
    r2 = _weight_patch(client, org, steward, steward.id, 3)
    assert r2.status_code == 400, r2.text


def test_cap_lower_below_outstanding_rejected(client, test_db):
    org = _org(test_db, "cap2", mode="direct", cap=100)
    steward, _ = _member(test_db, org, "stew", role="steward", weight=40)
    _, tm = _member(test_db, org, "t", weight=40)  # outstanding = 80
    test_db.commit()
    r = client.patch(f"/api/orgs/{org.slug}", headers=_auth(steward),
                     json={"settings": {"weighted_voting": {"authorized_total": 50}}})
    assert r.status_code == 400, r.text
    # Lowering to exactly outstanding (80) is allowed.
    r2 = client.patch(f"/api/orgs/{org.slug}", headers=_auth(steward),
                      json={"settings": {"weighted_voting": {"authorized_total": 80}}})
    assert r2.status_code == 200, r2.text


def test_transfers_ignore_cap(client, test_db):
    org = _org(test_db, "cap3", mode="direct", cap=10)
    # enable transfers
    s = dict(org.settings); wv = dict(s["weighted_voting"]); wv["transfers_enabled"] = True
    s["weighted_voting"] = wv; org.settings = s
    steward, sm = _member(test_db, org, "stew", role="steward", weight=1)
    sender, sendm = _member(test_db, org, "sender", weight=6)
    recipient, recm = _member(test_db, org, "recip", weight=3)  # outstanding = 10 == cap
    test_db.commit()
    # Transfer conserves the total, so it must succeed even AT the cap.
    r = client.post(f"/api/orgs/{org.slug}/shares/transfer", headers=_auth(sender),
                    json={"to_user_id": recipient.id, "amount": 2})
    assert r.status_code == 200, r.text


def test_sweep_skips_over_cap_and_retries(client, test_db):
    import share_distribution as sd
    org = _org(test_db, "cap4", mode="direct", cap=5)
    steward, _ = _member(test_db, org, "stew", role="steward", weight=1)
    _, tm = _member(test_db, org, "t", weight=1)  # outstanding = 2
    # A rule granting 10/period would breach cap 5 → must be skipped.
    rule = models.ShareDistributionRule(
        org_id=org.id, created_by_id=steward.id, status="active", amount=10,
        interval_months=1, schedule_mode="anniversary", targeting_mode="all_members",
        title_ids=[])
    test_db.add(rule)
    for m in test_db.query(models.OrgMembership).filter(
            models.OrgMembership.org_id == org.id).all():
        m.share_start_date = date.today() - timedelta(days=40)
    test_db.commit()

    granted = sd.run_rule(test_db, org, rule, today=date.today())
    test_db.commit()
    assert granted == 0  # all grants skipped by the cap
    # period_key NOT consumed → no auto_distribution events.
    assert test_db.query(models.ShareEvent).filter(
        models.ShareEvent.org_id == org.id,
        models.ShareEvent.event_type == "auto_distribution").count() == 0
    # One batched cap-blocked audit event.
    assert test_db.query(models.AuditLog).filter(
        models.AuditLog.action == "share.cap_blocked_distribution").count() == 1

    # Raise the cap → headroom → next sweep grants (retry, period_key was free).
    s = dict(org.settings); wv = dict(s["weighted_voting"]); wv["authorized_total"] = 1000
    s["weighted_voting"] = wv; org.settings = s
    test_db.commit()
    granted2 = sd.run_rule(test_db, org, rule, today=date.today())
    test_db.commit()
    assert granted2 >= 1  # now grants land


# ===========================================================================
# Existing-org parity — action types resolve approver sets
# ===========================================================================

def test_action_types_registered_and_resolve(client, test_db):
    from pending_actions import registry
    org = _org(test_db, "par1", mode="multi_admin")
    steward, _ = _member(test_db, org, "stew", role="steward", weight=1)
    a2, _ = _member(test_db, org, "adm2", role="admin", weight=1)
    test_db.commit()
    d = registry.get_action_definition("share.set_weight")
    approvers = d.approver_set_resolver(test_db, org)
    assert steward.id in approvers and a2.id in approvers  # both hold the key
    # issuance_mode_weaken resolves to admins only.
    dw = registry.get_action_definition("share.issuance_mode_weaken")
    weaken_approvers = dw.approver_set_resolver(test_db, org)
    assert a2.id in weaken_approvers
    assert steward.id not in weaken_approvers  # steward is not an admin
