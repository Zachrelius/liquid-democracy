"""Phase 34.2 F3 — sub-org Delegates page query regression test.

The browse_org_delegates endpoint had the same shape bug as Phase 34.1
E3 (proposals/topics): when org_slug resolves to a sub-org, the
DelegateProfile filter used `org_id == org.id` (sub's id), but
sub-org-scoped DelegateProfile rows are seeded with `org_id=parent +
sub_org_id=sub`. Result: sub-org Delegates page came back empty even
when public_accepting profiles existed.

This test ensures `/api/orgs/<sub_slug>/delegates` returns the sub-org's
public_accepting delegates.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from main import app


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_user(db, username):
    u = models.User(
        username=username, display_name=username.title(),
        email=f"{username}@example.com", email_verified=True,
        password_hash=auth_utils.hash_password("noop"),
    )
    db.add(u); db.flush(); db.commit()
    return u


def _ensure_role(db, org_id, system_key):
    r = db.query(models.Role).filter_by(org_id=org_id, system_key=system_key).first()
    if r is None:
        r = models.Role(org_id=org_id, system_key=system_key,
                        name=system_key.title(), display_order=0)
        db.add(r); db.flush()
    return r


def _setup(db):
    parent = models.Organization(name="Parent", slug="test-parent", join_policy="open")
    db.add(parent); db.flush()
    sub = models.Organization(
        name="Sub", slug="test-sub", join_policy="open",
        parent_org_id=parent.id,
    )
    db.add(sub); db.flush()

    member_role = _ensure_role(db, parent.id, "member")
    delegate = _make_user(db, "delegate1")
    viewer = _make_user(db, "viewer")
    for u in (delegate, viewer):
        db.add(models.OrgMembership(
            user_id=u.id, org_id=parent.id,
            role_id=member_role.id, status="active",
        ))
    # Sub-org topic with org_id=parent + sub_org_id=sub (Phase 34 pattern).
    topic = models.Topic(
        name="General Issues", color="#7c3aed",
        org_id=parent.id, sub_org_id=sub.id,
    )
    db.add(topic); db.flush()
    # public_accepting DelegateProfile for delegate1 with sub_org_id=sub.id.
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    dp = models.DelegateProfile(
        user_id=delegate.id,
        topic_id=topic.id,
        org_id=parent.id,
        sub_org_id=sub.id,
        bio="",
        visibility="public_accepting",
        public_accepting_submitted_at=now,
        public_accepting_approved_at=now,
    )
    db.add(dp); db.flush(); db.commit()
    return parent, sub, viewer


def _login(client, username):
    resp = client.post(
        "/api/auth/login",
        data={"username": username, "password": "noop"},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_sub_org_delegates_endpoint_returns_sub_org_public_delegates(db_session, client):
    """The regression — /api/orgs/<sub_slug>/delegates returned [] pre-fix.
    Now returns the delegate whose DelegateProfile has sub_org_id=sub.id."""
    parent, sub, viewer = _setup(db_session)
    headers = _login(client, "viewer")
    resp = client.get(f"/api/orgs/{sub.slug}/delegates", headers=headers)
    assert resp.status_code == 200, resp.text
    arr = resp.json()
    assert len(arr) == 1, f"expected 1 sub-org delegate, got {len(arr)}"
    assert arr[0]["username"] == "delegate1"


def test_main_org_delegates_endpoint_does_not_include_sub_org_public_delegates(
    db_session, client,
):
    """Defense — querying the parent slug doesn't surface sub-org-scoped
    delegates (they belong to the sub-org's listing). Keeps main-org and
    sub-org delegate browses cleanly partitioned."""
    parent, sub, viewer = _setup(db_session)
    headers = _login(client, "viewer")
    resp = client.get(f"/api/orgs/{parent.slug}/delegates", headers=headers)
    assert resp.status_code == 200, resp.text
    arr = resp.json()
    # Sub-org-scoped delegate should NOT appear on the parent's list.
    usernames = [d["username"] for d in arr]
    assert "delegate1" not in usernames
