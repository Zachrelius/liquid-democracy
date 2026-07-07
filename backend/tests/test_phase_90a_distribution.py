"""Phase 90a — Auto-distribution rules.

Covers:
  * Pure month math (add_months) with day-clamping (Jan 31, Feb 29 leap).
  * Sweep side effects: voting_weight increments + auto_distribution ShareEvent
    rows with unique period_keys; RE-running the sweep is a no-op (idempotency
    proven, not inferred).
  * Targeting: all / titles_include / titles_exclude; system-title holders;
    a deleted title id goes inert; a member who joins mid-cadence.
  * Anniversary math: monthly / 6-monthly / yearly; catch-up of missed periods
    capped at 12.
  * Dormant when weighting disabled; resumes when re-enabled.
  * Rule CRUD gating + share-start-date PATCH.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
import share_distribution as sd
from database import Base, get_db
from main import app
from role_seed import seed_default_roles_for_org
from tests.conftest import make_org_membership

_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"
ON = {"enabled": True, "unit_label": "shares"}
OFF = {"enabled": False, "unit_label": "shares"}


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


def _org(db, slug="dist-org", weighted=ON):
    o = models.Organization(name=slug.title(), slug=slug, description="",
                            settings={"weighted_voting": weighted})
    db.add(o); db.flush(); seed_default_roles_for_org(db, o.id); return o


def _member(db, org, n, *, role="member", weight=0, joined_days_ago=None,
            start_date=None):
    u = _user(db, n)
    m = make_org_membership(db, org_id=org.id, user_id=u.id, role=role)
    m.voting_weight = weight
    if joined_days_ago is not None:
        m.joined_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=joined_days_ago)
    if start_date is not None:
        m.share_start_date = start_date
    db.flush()
    return u, m


def _rule(db, org, *, amount=10, interval_months=12, schedule_mode="anniversary",
          targeting_mode="all_members", title_ids=None, anchor_date=None):
    r = sd.create_rule(db, org=org, created_by_id=None, amount=amount,
                       interval_months=interval_months, schedule_mode=schedule_mode,
                       targeting_mode=targeting_mode, title_ids=title_ids or [],
                       anchor_date=anchor_date)
    db.flush()
    return r


# ===========================================================================
# Month math
# ===========================================================================

def test_add_months_clamping():
    assert sd.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)  # non-leap
    assert sd.add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)  # leap
    assert sd.add_months(date(2024, 2, 29), 12) == date(2025, 2, 28)  # leap->non
    assert sd.add_months(date(2026, 6, 15), 6) == date(2026, 12, 15)
    assert sd.add_months(date(2026, 12, 15), 1) == date(2027, 1, 15)  # year roll


# ===========================================================================
# Anniversary sweep + idempotency
# ===========================================================================

def test_anniversary_grant_and_idempotency(test_db):
    org = _org(test_db)
    _, m = _member(test_db, org, "alice", weight=100,
                   start_date=date(2024, 3, 1))
    rule = _rule(test_db, org, amount=25, interval_months=12,
                 schedule_mode="anniversary")
    test_db.commit()
    # Two anniversaries elapsed by 2026-06-01 (2025-03-01, 2026-03-01).
    g = sd.run_rule(test_db, org, rule, today=date(2026, 6, 1))
    test_db.commit()
    assert g == 2
    test_db.refresh(m)
    assert m.voting_weight == 150  # 100 + 25 + 25
    evs = test_db.query(models.ShareEvent).filter(
        models.ShareEvent.event_type == "auto_distribution").all()
    assert len(evs) == 2
    assert len({e.period_key for e in evs}) == 2  # unique period keys
    # RE-run is a no-op (idempotent).
    g2 = sd.run_rule(test_db, org, rule, today=date(2026, 6, 1))
    test_db.commit()
    assert g2 == 0
    test_db.refresh(m)
    assert m.voting_weight == 150


def test_anniversary_not_yet_due(test_db):
    org = _org(test_db)
    _, m = _member(test_db, org, "new", weight=5, start_date=date(2026, 5, 1))
    rule = _rule(test_db, org, amount=25, interval_months=12,
                 schedule_mode="anniversary")
    test_db.commit()
    g = sd.run_rule(test_db, org, rule, today=date(2026, 6, 1))  # <1yr
    assert g == 0


def test_anniversary_catchup_cap(test_db):
    org = _org(test_db)
    _, m = _member(test_db, org, "old", weight=0, start_date=date(2000, 1, 1))
    rule = _rule(test_db, org, amount=1, interval_months=12,
                 schedule_mode="anniversary")
    test_db.commit()
    # ~26 anniversaries elapsed, but the catch-up is capped at 12.
    g = sd.run_rule(test_db, org, rule, today=date(2026, 6, 1))
    test_db.commit()
    assert g == sd.CATCHUP_CAP
    test_db.refresh(m)
    assert m.voting_weight == sd.CATCHUP_CAP


# ===========================================================================
# Fixed cadence
# ===========================================================================

def test_fixed_cadence_grants_all_members(test_db):
    org = _org(test_db)
    _, a = _member(test_db, org, "a", weight=10)
    _, b = _member(test_db, org, "b", weight=20)
    rule = _rule(test_db, org, amount=5, interval_months=6,
                 schedule_mode="fixed_cadence", anchor_date=date(2026, 1, 1))
    test_db.commit()
    # By 2026-08-01, one 6-month period elapsed (2026-07-01).
    g = sd.run_rule(test_db, org, rule, today=date(2026, 8, 1))
    test_db.commit()
    assert g == 2  # both members, period 1
    test_db.refresh(a); test_db.refresh(b)
    assert a.voting_weight == 15 and b.voting_weight == 25


# ===========================================================================
# Targeting
# ===========================================================================

def _title(db, org, name, *, is_system=False, bound_role=None):
    t = models.OrgTitle(org_id=org.id, name=name, is_system=is_system,
                        bound_role=bound_role, display_order=0)
    db.add(t); db.flush(); return t


def _assign(db, title, user):
    db.add(models.OrgTitleAssignment(title_id=title.id, user_id=user.id))
    db.flush()


def test_targeting_include_exclude(test_db):
    org = _org(test_db)
    ua, a = _member(test_db, org, "a", weight=0)
    ub, b = _member(test_db, org, "b", weight=0)
    uc, c = _member(test_db, org, "c", weight=0)
    emp = _title(test_db, org, "Employee")
    _assign(test_db, emp, ua)
    _assign(test_db, emp, ub)  # a, b are Employees; c is not
    inc = _rule(test_db, org, amount=3, interval_months=1,
                schedule_mode="fixed_cadence", targeting_mode="titles_include",
                title_ids=[emp.id], anchor_date=date(2026, 1, 1))
    test_db.commit()
    targeted = {m.user_id for m in sd.resolve_targeted_members(test_db, org.id, inc)}
    assert targeted == {ua.id, ub.id}
    exc = _rule(test_db, org, amount=3, interval_months=1,
                schedule_mode="fixed_cadence", targeting_mode="titles_exclude",
                title_ids=[emp.id], anchor_date=date(2026, 1, 1))
    test_db.commit()
    targeted_ex = {m.user_id for m in sd.resolve_targeted_members(test_db, org.id, exc)}
    assert targeted_ex == {uc.id}


def test_targeting_system_title_by_role(test_db):
    org = _org(test_db)
    steward, sm = _member(test_db, org, "steward", role="steward", weight=0)
    plain, pm = _member(test_db, org, "plain", weight=0)
    stitle = _title(test_db, org, "Steward", is_system=True, bound_role="steward")
    rule = _rule(test_db, org, amount=1, interval_months=1,
                 schedule_mode="fixed_cadence", targeting_mode="titles_include",
                 title_ids=[stitle.id], anchor_date=date(2026, 1, 1))
    test_db.commit()
    targeted = {m.user_id for m in sd.resolve_targeted_members(test_db, org.id, rule)}
    assert targeted == {steward.id}  # role-derived system-title holder


def test_targeting_deleted_title_inert(test_db):
    org = _org(test_db)
    ua, a = _member(test_db, org, "a", weight=0)
    emp = _title(test_db, org, "Employee")
    _assign(test_db, emp, ua)
    rule = _rule(test_db, org, amount=1, interval_months=1,
                 schedule_mode="fixed_cadence", targeting_mode="titles_include",
                 title_ids=[emp.id], anchor_date=date(2026, 1, 1))
    test_db.commit()
    # Rule resolves to the holder while the title exists.
    assert {m.user_id for m in sd.resolve_targeted_members(test_db, org.id, rule)} == {ua.id}
    # Delete the title AFTER the rule was created — the id goes inert (spec 2.3).
    test_db.query(models.OrgTitleAssignment).filter(
        models.OrgTitleAssignment.title_id == emp.id).delete()
    test_db.delete(emp)
    test_db.commit()
    assert sd.resolve_targeted_members(test_db, org.id, rule) == []  # inert


# ===========================================================================
# Dormant when weighting off
# ===========================================================================

def test_sweep_dormant_when_weighting_off(test_db):
    org = _org(test_db, weighted=OFF)
    _, m = _member(test_db, org, "a", weight=0, start_date=date(2020, 1, 1))
    _rule(test_db, org, amount=10, interval_months=12, schedule_mode="anniversary")
    test_db.commit()
    out = sd.run_distribution_sweep(test_db, today=date(2026, 6, 1))
    assert out["grants"] == 0
    test_db.refresh(m)
    assert m.voting_weight == 0  # dormant, no grants


def test_sweep_fires_when_weighting_on(test_db):
    org = _org(test_db, weighted=ON)
    _, m = _member(test_db, org, "a", weight=0, start_date=date(2025, 1, 1))
    _rule(test_db, org, amount=10, interval_months=12, schedule_mode="anniversary")
    test_db.commit()
    out = sd.run_distribution_sweep(test_db, today=date(2026, 6, 1))
    assert out["grants"] == 1
    test_db.refresh(m)
    assert m.voting_weight == 10


# ===========================================================================
# Rule CRUD + share-start-date (routes)
# ===========================================================================

def test_rule_crud_gating_and_flow(client, test_db):
    org = _org(test_db)
    admin, _ = _member(test_db, org, "admin", role="steward", weight=1)
    plain, _ = _member(test_db, org, "plain", weight=1)
    test_db.commit()
    # plain member cannot create.
    r = client.post(f"/api/orgs/{org.slug}/share-distribution-rules",
                    headers=_auth(plain),
                    json={"amount": 5, "interval_months": 12,
                          "schedule_mode": "anniversary"})
    assert r.status_code == 403, r.text
    # admin creates.
    r2 = client.post(f"/api/orgs/{org.slug}/share-distribution-rules",
                     headers=_auth(admin),
                     json={"amount": 5, "interval_months": 12,
                           "schedule_mode": "anniversary"})
    assert r2.status_code == 201, r2.text
    rid = r2.json()["id"]
    # ALL members can read.
    lr = client.get(f"/api/orgs/{org.slug}/share-distribution-rules",
                    headers=_auth(plain))
    assert lr.status_code == 200 and len(lr.json()) == 1
    # pause / resume / delete.
    assert client.post(f"/api/orgs/{org.slug}/share-distribution-rules/{rid}/pause",
                       headers=_auth(admin)).json()["status"] == "paused"
    assert client.post(f"/api/orgs/{org.slug}/share-distribution-rules/{rid}/resume",
                       headers=_auth(admin)).json()["status"] == "active"
    dr = client.delete(f"/api/orgs/{org.slug}/share-distribution-rules/{rid}",
                       headers=_auth(admin))
    assert dr.status_code == 200


def test_rule_create_rejects_bad_config(client, test_db):
    org = _org(test_db)
    admin, _ = _member(test_db, org, "admin", role="steward", weight=1)
    test_db.commit()
    r = client.post(f"/api/orgs/{org.slug}/share-distribution-rules",
                    headers=_auth(admin),
                    json={"amount": 0, "interval_months": 12,
                          "schedule_mode": "anniversary"})
    assert r.status_code == 400, r.text


def test_share_start_date_patch(client, test_db):
    org = _org(test_db)
    admin, _ = _member(test_db, org, "admin", role="steward", weight=1)
    target, tm = _member(test_db, org, "target", weight=1)
    test_db.commit()
    r = client.patch(f"/api/orgs/{org.slug}/members/{target.id}/share-start-date",
                     headers=_auth(admin), json={"share_start_date": "2020-05-01"})
    assert r.status_code == 200, r.text
    test_db.refresh(tm)
    assert tm.share_start_date == date(2020, 5, 1)
    # resolver returns the explicit date.
    assert sd.share_start_date_for(tm) == date(2020, 5, 1)
