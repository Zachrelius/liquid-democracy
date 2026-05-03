"""Phase 10.2 W-FIX-A — public-delegates browse sub-org scope filter.

Per docs/test_depth_audit_2026-05.md (Class B, Phase 8.5 Decision-5):
  * test_public_delegates_filtered_by_sub_org_scope_for_authenticated_viewer
    — a delegate whose only active profile is on a sub-org topic the
    authenticated viewer can't see should be excluded from the browse
    response. Anonymous viewers still see them per the route's design.
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


_DUMMY_HASH = auth_utils.hash_password("demo1234")


@pytest.fixture(scope="function")
def test_db():
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
def client(test_db):
    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_user(db, username: str) -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=True,
    )
    db.add(u)
    db.flush()
    return u


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def test_public_delegates_filtered_by_sub_org_scope_for_authenticated_viewer(
    client, test_db,
):
    """Phase 10.2 audit: Class B, GET /api/delegates/public — a delegate
    whose only active profile is on a sub-org topic the viewer can't see
    is suppressed from the authenticated-viewer browse default. The same
    response shows them when the topic is parent-org-wide."""
    parent_org = models.Organization(
        name="Parent", slug="parent-pd", description="",
        join_policy="approval_required",
    )
    sub_org = models.Organization(
        name="Sub Engineering", slug="sub-engineering-pd", description="",
        join_policy="approval_required",
    )
    test_db.add_all([parent_org, sub_org])
    test_db.flush()

    viewer = _make_user(test_db, "pd_viewer")
    sub_only_delegate = _make_user(test_db, "pd_sub_only")
    parent_delegate = _make_user(test_db, "pd_parent")
    test_db.flush()

    # Topics: parent-wide (sub_org_id=None) and sub-org-scoped.
    parent_topic = models.Topic(
        name="parent_topic_pd", description="", color="#000000",
        sub_org_id=None,
    )
    sub_topic = models.Topic(
        name="sub_topic_pd", description="", color="#000000",
        sub_org_id=sub_org.id,
    )
    test_db.add_all([parent_topic, sub_topic])
    test_db.flush()

    # parent_delegate has a parent-org-wide profile (visible to everyone).
    test_db.add(models.DelegateProfile(
        user_id=parent_delegate.id,
        topic_id=parent_topic.id,
        org_id=parent_org.id,
        bio="",
        is_active=True,
    ))
    # sub_only_delegate ONLY has a profile on the sub-org topic.
    test_db.add(models.DelegateProfile(
        user_id=sub_only_delegate.id,
        topic_id=sub_topic.id,
        org_id=parent_org.id,
        bio="",
        is_active=True,
    ))
    test_db.commit()

    # Viewer is NOT a member of sub_org → sub_only_delegate must be hidden.
    resp = client.get(
        "/api/delegates/public",
        headers=_auth(viewer),
    )
    assert resp.status_code == 200, resp.text
    visible_ids = {entry["user"]["id"] for entry in resp.json()}
    assert parent_delegate.id in visible_ids
    assert sub_only_delegate.id not in visible_ids

    # Now make viewer an active sub-org member → sub_only_delegate becomes
    # visible.
    test_db.add(models.SubOrgMembership(
        user_id=viewer.id,
        sub_org_id=sub_org.id,
        role="member",
        status="active",
    ))
    test_db.commit()

    resp_member = client.get(
        "/api/delegates/public",
        headers=_auth(viewer),
    )
    assert resp_member.status_code == 200
    visible_ids_member = {
        entry["user"]["id"] for entry in resp_member.json()
    }
    assert sub_only_delegate.id in visible_ids_member
