"""Phase 90b — Member-to-member share transfers.

Covers:
  * Happy path: sender decremented, recipient incremented, single transfer
    ShareEvent (from/to/delta + both resulting balances), total conserved.
  * Validation battery (both toggles required, self, non-member, amount<=0,
    insufficient balance at exactly-equal boundary) — balances asserted
    UNCHANGED, not just 4xx.
  * Conservation of total across a transfer storm.
  * Visibility: a third member sees amount-only when parties hidden;
    from_resulting_balance only to the sender; recipient sees resulting_balance.
  * Atomicity: the service raises before any mutation on a bad transfer.
"""
from __future__ import annotations

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
ON = {"enabled": True, "unit_label": "shares", "transfers_enabled": True}
ON_NO_TRANSFER = {"enabled": True, "unit_label": "shares", "transfers_enabled": False}
ON_PARTIES = {"enabled": True, "unit_label": "shares", "transfers_enabled": True,
              "show_event_parties": True}


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


def _org(db, slug="tr-org", weighted=ON):
    o = models.Organization(name=slug.title(), slug=slug, description="",
                            settings={"weighted_voting": weighted})
    db.add(o); db.flush(); seed_default_roles_for_org(db, o.id); return o


def _member(db, org, n, *, role="member", weight=0):
    u = _user(db, n)
    m = make_org_membership(db, org_id=org.id, user_id=u.id, role=role)
    m.voting_weight = weight
    db.flush()
    return u, m


def _transfer(client, org, sender, to_user_id, amount):
    return client.post(f"/api/orgs/{org.slug}/shares/transfer", headers=_auth(sender),
                       json={"to_user_id": to_user_id, "amount": amount})


def _total(db, org):
    return sum(m.voting_weight for m in db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == org.id).all())


# ===========================================================================
# Happy path + conservation
# ===========================================================================

def test_transfer_happy_path(client, test_db):
    org = _org(test_db)
    a, am = _member(test_db, org, "alice", weight=50)
    b, bm = _member(test_db, org, "bob", weight=10)
    test_db.commit()
    total_before = _total(test_db, org)
    r = _transfer(client, org, a, b.id, 15)
    assert r.status_code == 200, r.text
    test_db.refresh(am); test_db.refresh(bm)
    assert am.voting_weight == 35 and bm.voting_weight == 25
    assert _total(test_db, org) == total_before  # conserved
    ev = test_db.query(models.ShareEvent).filter(
        models.ShareEvent.event_type == "transfer").one()
    assert ev.from_user_id == a.id and ev.to_user_id == b.id
    assert ev.delta == 15
    assert ev.resulting_balance == 25       # recipient
    assert ev.from_resulting_balance == 35  # sender


def test_transfer_to_zero_balance_allowed(client, test_db):
    org = _org(test_db)
    a, am = _member(test_db, org, "alice", weight=20)
    b, bm = _member(test_db, org, "bob", weight=0)
    test_db.commit()
    r = _transfer(client, org, a, b.id, 20)  # sender to exactly 0
    assert r.status_code == 200, r.text
    test_db.refresh(am)
    assert am.voting_weight == 0


def test_conservation_across_storm(client, test_db):
    org = _org(test_db)
    a, _ = _member(test_db, org, "a", weight=100)
    b, _ = _member(test_db, org, "b", weight=100)
    c, _ = _member(test_db, org, "c", weight=100)
    test_db.commit()
    total = _total(test_db, org)
    _transfer(client, org, a, b.id, 30)
    _transfer(client, org, b, c.id, 50)
    _transfer(client, org, c, a.id, 10)
    _transfer(client, org, a, c.id, 5)
    assert _total(test_db, org) == total  # invariant


# ===========================================================================
# Validation battery (balances unchanged)
# ===========================================================================

def _assert_unchanged(test_db, am, bm, aw, bw):
    test_db.refresh(am); test_db.refresh(bm)
    assert am.voting_weight == aw and bm.voting_weight == bw


def test_insufficient_balance_boundary(client, test_db):
    org = _org(test_db)
    a, am = _member(test_db, org, "a", weight=10)
    b, bm = _member(test_db, org, "b", weight=0)
    test_db.commit()
    r = _transfer(client, org, a, b.id, 11)  # one over balance
    assert r.status_code == 400, r.text
    _assert_unchanged(test_db, am, bm, 10, 0)


def test_zero_and_negative_amount(client, test_db):
    org = _org(test_db)
    a, am = _member(test_db, org, "a", weight=10)
    b, bm = _member(test_db, org, "b", weight=0)
    test_db.commit()
    for amt in (0, -5):
        r = _transfer(client, org, a, b.id, amt)
        assert r.status_code in (400, 422), (amt, r.text)
    _assert_unchanged(test_db, am, bm, 10, 0)


def test_self_transfer_rejected(client, test_db):
    org = _org(test_db)
    a, am = _member(test_db, org, "a", weight=10)
    test_db.commit()
    r = _transfer(client, org, a, a.id, 5)
    assert r.status_code == 400, r.text
    _assert_unchanged(test_db, am, am, 10, 10)


def test_non_member_recipient_rejected(client, test_db):
    org = _org(test_db)
    a, am = _member(test_db, org, "a", weight=10)
    outsider = _user(test_db, "outsider")
    test_db.commit()
    r = _transfer(client, org, a, outsider.id, 5)
    assert r.status_code == 404, r.text
    test_db.refresh(am)
    assert am.voting_weight == 10


def test_transfers_disabled_toggle(client, test_db):
    org = _org(test_db, weighted=ON_NO_TRANSFER)
    a, am = _member(test_db, org, "a", weight=10)
    b, bm = _member(test_db, org, "b", weight=0)
    test_db.commit()
    r = _transfer(client, org, a, b.id, 5)
    assert r.status_code == 400, r.text
    _assert_unchanged(test_db, am, bm, 10, 0)


def test_weighting_disabled_blocks_transfer(client, test_db):
    org = _org(test_db, weighted={"enabled": False, "transfers_enabled": True})
    a, am = _member(test_db, org, "a", weight=10)
    b, bm = _member(test_db, org, "b", weight=0)
    test_db.commit()
    r = _transfer(client, org, a, b.id, 5)
    assert r.status_code == 400, r.text
    _assert_unchanged(test_db, am, bm, 10, 0)


# ===========================================================================
# Atomicity (service raises before mutation)
# ===========================================================================

def test_service_raises_before_mutation(test_db):
    org = _org(test_db)
    _, am = _member(test_db, org, "a", weight=5)
    _, bm = _member(test_db, org, "b", weight=0)
    test_db.commit()
    with pytest.raises(share_service.ShareServiceError):
        share_service.transfer_shares(test_db, org=org, sender_membership=am,
                                      recipient_membership=bm, amount=10,
                                      actor_id=None)
    test_db.refresh(am); test_db.refresh(bm)
    assert am.voting_weight == 5 and bm.voting_weight == 0
    assert test_db.query(models.ShareEvent).count() == 0


# ===========================================================================
# Visibility
# ===========================================================================

def test_transfer_visibility(client, test_db):
    org = _org(test_db, weighted=ON)  # parties hidden by default
    a, _ = _member(test_db, org, "alice", weight=50)
    b, _ = _member(test_db, org, "bob", weight=10)
    c, _ = _member(test_db, org, "carol", weight=5)
    test_db.commit()
    _transfer(client, org, a, b.id, 15)
    # third party (carol): amount only, no parties, no balances.
    body = client.get(f"/api/orgs/{org.slug}/share-events", headers=_auth(c)).json()
    ev = body["events"][0]
    assert ev["delta"] == 15
    assert ev["from_user_id"] is None and ev["to_user_id"] is None
    assert ev["resulting_balance"] is None and ev["from_resulting_balance"] is None
    # sender (alice): sees parties + her own from_resulting_balance, not recipient's.
    ba = client.get(f"/api/orgs/{org.slug}/share-events", headers=_auth(a)).json()
    ea = ba["events"][0]
    assert ea["from_display_name"] == "Alice" and ea["to_display_name"] == "Bob"
    assert ea["from_resulting_balance"] == 35
    assert ea["resulting_balance"] is None  # not the recipient
    # recipient (bob): sees resulting_balance, not sender's from_resulting_balance.
    bb = client.get(f"/api/orgs/{org.slug}/share-events", headers=_auth(b)).json()
    eb = bb["events"][0]
    assert eb["resulting_balance"] == 25
    assert eb["from_resulting_balance"] is None
