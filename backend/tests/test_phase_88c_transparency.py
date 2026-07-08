"""Phase 88c — Weighted-org transparency (anti-stealth guarantees).

Covers:
  * Toggle guard: the voting model cannot flip while any vote is open
    (org-level, sub-org, election); flips succeed otherwise; unit_label-only
    change is allowed during open votes.
  * Notification fan-out: flipping on/off creates one notification row per
    active member with the correct payload + actor, alongside the audit row;
    delivery is forced even for members with no preference row.
  * Serialization: weighted_voting on public-landing + explore + org-selector
    (org list) + org-detail; other members' voting_weight ABSENT from the
    plain-member member-list and all anonymous responses; total_voting_weight
    present + correct for members (incl. a zero-weight member + after an edit).
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
from database import Base, get_db
from main import app
from role_seed import seed_default_roles_for_org
from tests.conftest import make_org_membership, make_sub_org_membership

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
    u = models.User(username=n, display_name=n, password_hash=_DUMMY_HASH,
                    email=f"{n}@t.ex", email_verified=True)
    db.add(u); db.flush(); return u


def _org(db, slug="tx-org", weighted=None, *, parent=None, discoverability="listed"):
    s = {"default_voting_days": 7,
         "allowed_voting_methods": ["binary", "approval"]}
    if weighted is not None:
        s["weighted_voting"] = weighted
    o = models.Organization(
        name=slug.title(), slug=slug, description="A test org.", settings=s,
        parent_org_id=parent.id if parent else None,
        discoverability=discoverability, activity_visibility="members_only",
        join_policy="open",
    )
    db.add(o); db.flush(); seed_default_roles_for_org(db, o.id); return o


def _member(db, org, n, *, role="member", weight=1):
    u = _user(db, n)
    m = make_org_membership(db, org_id=org.id, user_id=u.id, role=role)
    m.voting_weight = weight
    db.flush()
    return u, m


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _proposal(db, author, org, *, status="voting", is_election=False):
    p = models.Proposal(
        title="P", body="", author_id=author.id, org_id=org.id,
        voting_method="binary", num_winners=1, status=status,
        voting_start=_now() if status == "voting" else None,
        voting_end=_now() + timedelta(days=7) if status == "voting" else None,
        quorum_threshold=0.0, pass_threshold=0.5, is_election=is_election,
    )
    db.add(p); db.flush(); return p


# ===========================================================================
# Toggle guard
# ===========================================================================

def test_flip_blocked_with_open_org_vote(client, test_db):
    org = _org(test_db, weighted=OFF)
    author, _ = _member(test_db, org, "auth", role="steward")
    _proposal(test_db, author, org, status="voting")
    test_db.commit()
    r = client.patch(f"/api/orgs/{org.slug}", headers=_auth(author), json={
        "settings": {"weighted_voting": {"enabled": True}},
    })
    assert r.status_code == 409, r.text
    # settings unchanged (side effect asserted).
    test_db.refresh(org)
    from org_config import get_weighted_voting_config
    assert get_weighted_voting_config(org)["enabled"] is False


def test_flip_blocked_with_open_election(client, test_db):
    org = _org(test_db, weighted=OFF)
    author, _ = _member(test_db, org, "auth", role="steward")
    _proposal(test_db, author, org, status="voting", is_election=True)
    test_db.commit()
    r = client.patch(f"/api/orgs/{org.slug}", headers=_auth(author), json={
        "settings": {"weighted_voting": {"enabled": True}},
    })
    assert r.status_code == 409, r.text


def test_flip_blocked_with_open_suborg_vote(client, test_db):
    parent = _org(test_db, slug="parent", weighted=OFF)
    author, _ = _member(test_db, parent, "pauth", role="steward")
    sub = _org(test_db, slug="sub", parent=parent)
    _proposal(test_db, author, sub, status="voting")  # sub-org proposal open
    test_db.commit()
    r = client.patch(f"/api/orgs/{parent.slug}", headers=_auth(author), json={
        "settings": {"weighted_voting": {"enabled": True}},
    })
    assert r.status_code == 409, r.text


def test_flip_allowed_with_no_open_vote(client, test_db):
    org = _org(test_db, weighted=OFF)
    author, _ = _member(test_db, org, "auth", role="steward")
    _proposal(test_db, author, org, status="draft")
    _proposal(test_db, author, org, status="passed")
    test_db.commit()
    r = client.patch(f"/api/orgs/{org.slug}", headers=_auth(author), json={
        "settings": {"weighted_voting": {"enabled": True}},
    })
    assert r.status_code == 200, r.text
    assert r.json()["weighted_voting"]["enabled"] is True


def test_unit_label_change_allowed_during_open_vote(client, test_db):
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward")
    _proposal(test_db, author, org, status="voting")
    test_db.commit()
    # enabled stays True; only unit_label changes → allowed.
    r = client.patch(f"/api/orgs/{org.slug}", headers=_auth(author), json={
        "settings": {"weighted_voting": {"unit_label": "units"}},
    })
    assert r.status_code == 200, r.text
    assert r.json()["weighted_voting"]["unit_label"] == "units"


# ===========================================================================
# Notification fan-out
# ===========================================================================

def test_flip_on_notifies_all_members(client, test_db):
    org = _org(test_db, weighted=OFF)
    author, _ = _member(test_db, org, "auth", role="steward")
    m1, _ = _member(test_db, org, "m1")
    m2, _ = _member(test_db, org, "m2")
    test_db.commit()
    r = client.patch(f"/api/orgs/{org.slug}", headers=_auth(author), json={
        "settings": {"weighted_voting": {"enabled": True, "unit_label": "shares"}},
    })
    assert r.status_code == 200, r.text
    rows = test_db.query(models.Notification).filter(
        models.Notification.event_type == "org.voting_model_changed",
    ).all()
    # one per active member (author + m1 + m2 = 3), forced regardless of prefs.
    assert len(rows) == 3
    by_user = {n.user_id: n for n in rows}
    assert set(by_user) == {author.id, m1.id, m2.id}
    payload = by_user[m1.id].payload
    assert payload["enabled"] is True
    assert payload["unit_label"] == "shares"
    assert payload["actor_id"] == author.id
    assert payload["actor_display_name"] == author.display_name
    # audit row present alongside.
    audit = test_db.query(models.AuditLog).filter(
        models.AuditLog.action == "org.weighted_voting_changed",
    ).all()
    assert len(audit) == 1


def test_flip_off_notifies_all_members(client, test_db):
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward")
    _member(test_db, org, "m1")
    test_db.commit()
    r = client.patch(f"/api/orgs/{org.slug}", headers=_auth(author), json={
        "settings": {"weighted_voting": {"enabled": False}},
    })
    assert r.status_code == 200, r.text
    rows = test_db.query(models.Notification).filter(
        models.Notification.event_type == "org.voting_model_changed",
    ).all()
    assert len(rows) == 2  # author + m1
    assert rows[0].payload["enabled"] is False


def test_unit_label_only_change_does_not_fan_out(client, test_db):
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward")
    _member(test_db, org, "m1")
    test_db.commit()
    client.patch(f"/api/orgs/{org.slug}", headers=_auth(author), json={
        "settings": {"weighted_voting": {"unit_label": "points"}},
    })
    rows = test_db.query(models.Notification).filter(
        models.Notification.event_type == "org.voting_model_changed",
    ).all()
    assert len(rows) == 0  # audited but not fanned out


# ===========================================================================
# Serialization
# ===========================================================================

def test_org_detail_surfaces_total_voting_weight(client, test_db):
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    _member(test_db, org, "m1", weight=6)
    _member(test_db, org, "zero", weight=0)  # zero-weight member
    test_db.commit()
    r = client.get(f"/api/orgs/{org.slug}", headers=_auth(author))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["weighted_voting"]["enabled"] is True
    assert body["total_voting_weight"] == 7  # 1 + 6 + 0


def test_total_voting_weight_none_when_off(client, test_db):
    org = _org(test_db, weighted=OFF)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    test_db.commit()
    r = client.get(f"/api/orgs/{org.slug}", headers=_auth(author))
    assert r.json()["total_voting_weight"] is None


def test_total_voting_weight_updates_after_edit(client, test_db):
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    target, _ = _member(test_db, org, "target", weight=1)
    test_db.commit()
    client.patch(f"/api/orgs/{org.slug}/members/{target.id}/voting-weight",
                 headers=_auth(author), json={"voting_weight": 50})
    r = client.get(f"/api/orgs/{org.slug}", headers=_auth(author))
    assert r.json()["total_voting_weight"] == 51  # 1 + 50


def test_member_list_hides_weights_from_plain_member(client, test_db):
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    plain, _ = _member(test_db, org, "plain", weight=3)
    _member(test_db, org, "other", weight=9)
    test_db.commit()
    # Plain member: other members' weights are hidden (None).
    r = client.get(f"/api/orgs/{org.slug}/members", headers=_auth(plain))
    assert r.status_code == 200, r.text
    weights = {m["username"]: m["voting_weight"] for m in r.json()}
    assert all(w is None for w in weights.values())
    # Admin (steward has member.set_voting_weight): weights visible.
    r2 = client.get(f"/api/orgs/{org.slug}/members", headers=_auth(author))
    weights2 = {m["username"]: m["voting_weight"] for m in r2.json()}
    assert weights2["other"] == 9
    assert weights2["plain"] == 3


def test_public_landing_surfaces_weighted_voting_no_weights(client, test_db):
    org = _org(test_db, weighted={"enabled": True, "unit_label": "units"},
               discoverability="listed")
    _member(test_db, org, "auth", role="steward", weight=5)
    test_db.commit()
    # Anonymous (no auth) public landing.
    r = client.get(f"/api/orgs/{org.slug}/public")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["weighted_voting"] == {"enabled": True, "unit_label": "units", "show_event_parties": False, "transfers_enabled": False, "allow_per_member_proposals": True, "issuance_mode": "direct", "authorized_total": None}
    # No per-member weight data anywhere in the anonymous payload.
    assert "voting_weight" not in body
    assert "5" not in str(body.get("members", ""))


def test_explore_surfaces_weighted_voting(client, test_db):
    org = _org(test_db, weighted=ON, discoverability="listed")
    _member(test_db, org, "auth", role="steward", weight=5)
    test_db.commit()
    r = client.get("/api/orgs/explore")
    assert r.status_code == 200, r.text
    cards = {c["slug"]: c for c in r.json()["orgs"]}
    assert org.slug in cards
    assert cards[org.slug]["weighted_voting"]["enabled"] is True
    assert "voting_weight" not in cards[org.slug]


def test_org_list_surfaces_weighted_voting(client, test_db):
    """The org-selector payload (GET /api/orgs) carries weighted_voting."""
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    test_db.commit()
    r = client.get("/api/orgs", headers=_auth(author))
    assert r.status_code == 200, r.text
    entry = next(o for o in r.json() if o["slug"] == org.slug)
    assert entry["weighted_voting"]["enabled"] is True
    assert entry["total_voting_weight"] == 1
