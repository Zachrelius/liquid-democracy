"""Phase 75a — Calendar voting end date.

Coverage (spec: phase75_smart_import_dispatch_2026-06-14.md §75a):
- Advance with voting_end_date (future) → voting_end == voting_end_date.
- Advance with past voting_end_date → 400, status unchanged.
- Advance with below-floor window → 400.
- Both voting_end_date + voting_days set → voting_end_date wins.
- voting_end_date NULL, voting_days set → existing behavior.
- voting_end_date with tzinfo → stripped to naive UTC.
- Create with voting_end_date → stored, no validation error regardless of date.
- ProposalOut surfaces voting_end_date.
- Import preview accepts voting_end_date.
- Permission gate: divergent implied duration without proposal.set_durations.
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
from tests.conftest import make_org_membership

_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


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


def _user(db, username, *, is_admin=False):
    u = models.User(username=username, display_name=username, password_hash=_DUMMY_HASH,
                    email=f"{username}@t.ex", email_verified=True, is_admin=is_admin)
    db.add(u)
    db.flush()
    return u


def _org(db, slug):
    o = models.Organization(name=slug.title(), slug=slug, description="",
                            settings={"default_voting_days": 7})
    db.add(o)
    db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _auth(user):
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _compute(proposal, *, voting_start, org=None):
    from routes.proposals import _compute_voting_end_at_advance
    return _compute_voting_end_at_advance(
        voting_start=voting_start, body_voting_end=None, proposal=proposal, org=org,
    )


def _proposal(db, author, org, **kw):
    p = models.Proposal(title="P", body="", author_id=author.id, org_id=org.id,
                        voting_method="binary", num_winners=1, status="voting",
                        quorum_threshold=0.4, pass_threshold=0.5, **kw)
    db.add(p)
    db.flush()
    return p


# ---------------------------------------------------------------------------
# _compute_voting_end_at_advance precedence (side-effect assertions)
# ---------------------------------------------------------------------------

def test_voting_end_date_wins(test_db):
    org, author = _org(test_db, "o1"), _user(test_db, "a1")
    start = datetime(2026, 6, 1, 12, 0, 0)
    end = datetime(2026, 6, 20, 12, 0, 0)
    p = _proposal(test_db, author, org, voting_days=7, voting_end_date=end)
    result = _compute(p, voting_start=start, org=org)
    # voting_end_date wins over voting_days (start + 7d = Jun 8, not Jun 20)
    assert result == end


def test_voting_days_used_when_no_end_date(test_db):
    org, author = _org(test_db, "o2"), _user(test_db, "a2")
    start = datetime(2026, 6, 1, 12, 0, 0)
    p = _proposal(test_db, author, org, voting_days=5, voting_end_date=None)
    result = _compute(p, voting_start=start, org=org)
    assert result == start + timedelta(days=5)


def test_past_end_date_rejected(test_db):
    from fastapi import HTTPException
    org, author = _org(test_db, "o3"), _user(test_db, "a3")
    start = datetime(2026, 6, 10, 12, 0, 0)
    end = datetime(2026, 6, 1, 12, 0, 0)  # before start
    p = _proposal(test_db, author, org, voting_end_date=end)
    with pytest.raises(HTTPException) as ei:
        _compute(p, voting_start=start, org=org)
    assert ei.value.status_code == 400


def test_below_floor_window_rejected(test_db):
    from fastapi import HTTPException
    org, author = _org(test_db, "o4"), _user(test_db, "a4")
    start = datetime(2026, 6, 10, 12, 0, 0)
    end = start + timedelta(seconds=30)  # ~0.0003 days, below 0.05 floor
    p = _proposal(test_db, author, org, voting_end_date=end)
    with pytest.raises(HTTPException) as ei:
        _compute(p, voting_start=start, org=org)
    assert ei.value.status_code == 400


def test_tzinfo_stripped(test_db):
    org, author = _org(test_db, "o5"), _user(test_db, "a5")
    start = datetime(2026, 6, 1, 12, 0, 0)
    end_aware = datetime(2026, 6, 20, 12, 0, 0, tzinfo=timezone.utc)
    p = _proposal(test_db, author, org, voting_end_date=end_aware)
    result = _compute(p, voting_start=start, org=org)
    assert result.tzinfo is None
    assert result == datetime(2026, 6, 20, 12, 0, 0)


# ---------------------------------------------------------------------------
# HTTP — create/advance/serialize
# ---------------------------------------------------------------------------

def test_create_and_advance_with_end_date(client, test_db):
    org = _org(test_db, "horg")
    author = _user(test_db, "hauthor")
    make_org_membership(test_db, org_id=org.id, user_id=author.id, role="steward")
    test_db.commit()
    end = (datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=10))
    r = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author), json={
        "title": "Council item", "voting_method": "binary",
        "voting_end_date": end.isoformat(),
    })
    assert r.status_code in (200, 201), r.text
    pid = r.json()["id"]
    assert r.json()["voting_end_date"] is not None
    # draft -> deliberation -> voting
    client.post(f"/api/proposals/{pid}/advance", headers=_auth(author), json={})
    r2 = client.post(f"/api/proposals/{pid}/advance", headers=_auth(author), json={})
    assert r2.status_code == 200, r2.text
    p = test_db.get(models.Proposal, pid)
    test_db.refresh(p)
    assert p.voting_end is not None
    # voting_end matches the absolute date (to the minute), not start+default.
    assert abs((p.voting_end - end).total_seconds()) < 60


def test_create_with_past_end_date_succeeds(client, test_db):
    """No create-time staleness check — a past date is accepted at create."""
    org = _org(test_db, "horg2")
    author = _user(test_db, "hauthor2")
    make_org_membership(test_db, org_id=org.id, user_id=author.id, role="steward")
    test_db.commit()
    past = datetime(2020, 1, 1, 0, 0, 0)
    r = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author), json={
        "title": "x", "voting_method": "binary", "voting_end_date": past.isoformat(),
    })
    assert r.status_code in (200, 201), r.text


def test_proposalout_surfaces_field(client, test_db):
    org = _org(test_db, "horg3")
    author = _user(test_db, "hauthor3")
    make_org_membership(test_db, org_id=org.id, user_id=author.id, role="steward")
    test_db.commit()
    r = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author), json={
        "title": "x", "voting_method": "binary",
    })
    assert "voting_end_date" in r.json()
    assert r.json()["voting_end_date"] is None


def test_permission_gate_divergent_end_date(client, test_db):
    """A member without proposal.set_durations setting a voting_end_date whose
    implied duration diverges from the org default is gated (same as a
    divergent voting_days)."""
    org = _org(test_db, "horg4")
    member = _user(test_db, "plainmember")
    make_org_membership(test_db, org_id=org.id, user_id=member.id, role="member")
    test_db.commit()
    # default is 7 days; set a date ~30 days out (divergent).
    end = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=30)
    r = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(member), json={
        "title": "x", "voting_method": "binary", "voting_end_date": end.isoformat(),
    })
    assert r.status_code == 400, r.text


def test_import_preview_accepts_end_date(client, test_db):
    org = _org(test_db, "horg5")
    author = _user(test_db, "hauthor5")
    make_org_membership(test_db, org_id=org.id, user_id=author.id, role="steward")
    test_db.commit()
    end = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=10)
    r = client.post(f"/api/orgs/{org.slug}/proposals/import-preview", headers=_auth(author),
                    json={"title": "Imported", "voting_method": "binary",
                          "voting_end_date": end.isoformat()})
    assert r.status_code == 200, r.text
    body = r.json()
    # single-object preview shape: {proposal, warnings, resolved_topics}
    prop = body.get("proposal") or (body.get("items") or [{}])[0].get("proposal")
    assert prop is not None
    assert prop.get("voting_end_date") is not None
