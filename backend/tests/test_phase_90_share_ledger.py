"""Phase 90 — Share event ledger.

Covers:
  * Same-transaction property: an admin weight edit writes exactly one
    admin_set ShareEvent (delta = new - old, resulting_balance = new); a
    zero-delta edit is rejected 400 with NO event and NO weight change.
  * Feed visibility: plain member with show_event_parties off sees amounts +
    the admin_set authorizer but NO party names and NO resulting balances
    except their own; toggle on reveals parties; own events always full; a
    third member never sees others' balances; anonymous/non-members blocked.
  * Ordering (newest first), pagination, epoch line.
  * /mine returns the member's full history.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
import share_service
from database import Base, get_db
from main import app
from role_seed import seed_default_roles_for_org
from tests.conftest import make_org_membership

_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"
ON = {"enabled": True, "unit_label": "shares"}
ON_PARTIES = {"enabled": True, "unit_label": "shares", "show_event_parties": True}


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


def _org(db, slug="sh-org", weighted=ON):
    o = models.Organization(name=slug.title(), slug=slug, description="",
                            settings={"weighted_voting": weighted})
    db.add(o); db.flush(); seed_default_roles_for_org(db, o.id); return o


def _member(db, org, n, *, role="member", weight=1):
    u = _user(db, n)
    m = make_org_membership(db, org_id=org.id, user_id=u.id, role=role)
    m.voting_weight = weight
    db.flush()
    return u, m


def _set_weight(client, org, admin, target, weight):
    return client.patch(f"/api/orgs/{org.slug}/members/{target.id}/voting-weight",
                        headers=_auth(admin), json={"voting_weight": weight})


# ===========================================================================
# Same-transaction ledger property
# ===========================================================================

def test_weight_edit_writes_admin_set_event(client, test_db):
    org = _org(test_db)
    admin, _ = _member(test_db, org, "admin", role="steward", weight=1)
    target, tm = _member(test_db, org, "target", weight=10)
    test_db.commit()
    r = _set_weight(client, org, admin, target, 25)
    assert r.status_code == 200, r.text
    test_db.refresh(tm)
    assert tm.voting_weight == 25
    evs = test_db.query(models.ShareEvent).all()
    assert len(evs) == 1
    ev = evs[0]
    assert ev.event_type == "admin_set"
    assert ev.user_id == target.id
    assert ev.delta == 15  # 25 - 10
    assert ev.resulting_balance == 25
    assert ev.actor_id == admin.id


def test_zero_delta_rejected_no_event(client, test_db):
    org = _org(test_db)
    admin, _ = _member(test_db, org, "admin", role="steward", weight=1)
    target, tm = _member(test_db, org, "target", weight=7)
    test_db.commit()
    r = _set_weight(client, org, admin, target, 7)  # same value
    assert r.status_code == 400, r.text
    test_db.refresh(tm)
    assert tm.voting_weight == 7  # unchanged
    assert test_db.query(models.ShareEvent).count() == 0  # nothing logged


def test_service_zero_delta_leaves_state_untouched(test_db):
    """Unit-level same-transaction guard: the service raises and mutates
    nothing (weight + ledger both untouched)."""
    org = _org(test_db)
    _, tm = _member(test_db, org, "t", weight=5)
    test_db.commit()
    with pytest.raises(share_service.ShareServiceError):
        share_service.set_member_weight(test_db, membership=tm, new_weight=5,
                                        actor_id=None)
    test_db.refresh(tm)
    assert tm.voting_weight == 5
    assert test_db.query(models.ShareEvent).count() == 0


# ===========================================================================
# Feed visibility
# ===========================================================================

def _seed_events(client, test_db, *, parties_on):
    org = _org(test_db, weighted=ON_PARTIES if parties_on else ON)
    admin, _ = _member(test_db, org, "admin", role="steward", weight=1)
    a, am = _member(test_db, org, "alice", weight=5)
    b, bm = _member(test_db, org, "bob", weight=5)
    c, cm = _member(test_db, org, "carol", weight=5)
    test_db.commit()
    _set_weight(client, org, admin, a, 20)  # admin_set on alice
    _set_weight(client, org, admin, b, 8)   # admin_set on bob
    return org, admin, a, b, c


def test_feed_hides_parties_and_balances_when_off(client, test_db):
    org, admin, a, b, c = _seed_events(client, test_db, parties_on=False)
    # carol (a third party) reads the feed.
    r = client.get(f"/api/orgs/{org.slug}/share-events", headers=_auth(c))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["show_parties"] is False
    for ev in body["events"]:
        # amounts + the admin_set authorizer are present...
        assert ev["delta"] != 0
        assert ev["actor_display_name"] is not None  # authorizer always named
        # ...but not the affected party or any balance (carol isn't a party).
        assert ev["user_id"] is None
        assert ev["user_display_name"] is None
        assert ev["resulting_balance"] is None


def test_feed_shows_parties_when_on(client, test_db):
    org, admin, a, b, c = _seed_events(client, test_db, parties_on=True)
    r = client.get(f"/api/orgs/{org.slug}/share-events", headers=_auth(c))
    body = r.json()
    assert body["show_parties"] is True
    names = {ev["user_display_name"] for ev in body["events"]}
    assert "Alice" in names and "Bob" in names
    # but a third party still never sees others' resulting balances.
    for ev in body["events"]:
        assert ev["resulting_balance"] is None


def test_feed_own_events_always_full(client, test_db):
    org, admin, a, b, c = _seed_events(client, test_db, parties_on=False)
    # alice reads the feed: parties off, but she sees HER OWN event fully.
    r = client.get(f"/api/orgs/{org.slug}/share-events", headers=_auth(a))
    body = r.json()
    own = [ev for ev in body["events"] if ev["user_id"] == a.id]
    assert len(own) == 1
    assert own[0]["user_display_name"] == "Alice"
    assert own[0]["resulting_balance"] == 20
    # bob's event stays party-hidden + balance-hidden for alice.
    others = [ev for ev in body["events"] if ev["user_id"] != a.id]
    for ev in others:
        assert ev["user_id"] is None
        assert ev["resulting_balance"] is None


def test_mine_returns_full_history(client, test_db):
    org, admin, a, b, c = _seed_events(client, test_db, parties_on=False)
    r = client.get(f"/api/orgs/{org.slug}/share-events/mine", headers=_auth(a))
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["events"]) == 1  # only alice's own event
    assert body["events"][0]["resulting_balance"] == 20


def test_feed_newest_first_and_epoch(client, test_db):
    org, admin, a, b, c = _seed_events(client, test_db, parties_on=True)
    r = client.get(f"/api/orgs/{org.slug}/share-events", headers=_auth(admin))
    body = r.json()
    times = [ev["created_at"] for ev in body["events"]]
    assert times == sorted(times, reverse=True)
    assert body["epoch"] is not None  # ledger epoch present


def test_feed_pagination(client, test_db):
    org, admin, a, b, c = _seed_events(client, test_db, parties_on=True)
    r = client.get(f"/api/orgs/{org.slug}/share-events?limit=1", headers=_auth(admin))
    body = r.json()
    assert len(body["events"]) == 1
    assert body["has_more"] is True


def test_feed_blocks_non_members(client, test_db):
    org, admin, a, b, c = _seed_events(client, test_db, parties_on=False)
    outsider = _user(test_db, "outsider")
    test_db.commit()
    r = client.get(f"/api/orgs/{org.slug}/share-events", headers=_auth(outsider))
    assert r.status_code in (403, 404), r.text
    # anonymous
    r2 = client.get(f"/api/orgs/{org.slug}/share-events")
    assert r2.status_code in (401, 403, 404)
