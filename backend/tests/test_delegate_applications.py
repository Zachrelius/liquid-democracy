"""Phase 10.2 W-FIX-A — delegate-applications endpoint coverage.

Per docs/test_depth_audit_2026-05.md (Class B, delegate-applications):
  * test_list_requires_org_admin_403_for_member — member-role caller is
    rejected by require_org_admin.
  * test_approve_creates_delegate_profile — approval activates a
    DelegateProfile for (user, topic, org).
  * test_deny_records_feedback — deny stores the feedback on the row.
  * test_audit_emission_on_approve_and_deny — both flows emit the
    appropriate audit action.
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


def _make_org(db, slug: str = "appsorg") -> models.Organization:
    org = models.Organization(
        name=slug.title(),
        slug=slug,
        description="",
        join_policy="approval_required",
    )
    db.add(org)
    db.flush()
    return org


def _join(db, user, org, role="member"):
    m = models.OrgMembership(
        user_id=user.id, org_id=org.id, role=role, status="active",
    )
    db.add(m)
    db.flush()
    return m


def _make_topic(db, name: str) -> models.Topic:
    t = models.Topic(name=name, description="", color="#000000")
    db.add(t)
    db.flush()
    return t


def _make_app(db, user, org, topic, *, status="pending") -> models.DelegateApplication:
    a = models.DelegateApplication(
        user_id=user.id,
        org_id=org.id,
        topic_id=topic.id,
        bio="my bio",
        status=status,
    )
    db.add(a)
    db.flush()
    return a


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_list_requires_org_admin_403_for_member(client, test_db):
    """Phase 10.2 audit: Class B, GET /api/orgs/{slug}/delegate-applications
    — caller without admin role is rejected by require_org_admin."""
    member = _make_user(test_db, "regular_member")
    org = _make_org(test_db, slug="da-list")
    _join(test_db, member, org, role="member")
    test_db.commit()

    resp = client.get(
        f"/api/orgs/{org.slug}/delegate-applications",
        headers=_auth(member),
    )
    assert resp.status_code == 403, resp.text


def test_approve_creates_delegate_profile(client, test_db):
    """Phase 10.2 audit: Class B, POST /api/orgs/{slug}/delegate-
    applications/{id}/approve — approval activates a DelegateProfile
    for (user, topic, org)."""
    admin = _make_user(test_db, "da_admin")
    applicant = _make_user(test_db, "da_applicant")
    org = _make_org(test_db, slug="da-approve")
    _join(test_db, admin, org, role="admin")
    _join(test_db, applicant, org, role="member")
    topic = _make_topic(test_db, "climate_da")
    app_row = _make_app(test_db, applicant, org, topic)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/delegate-applications/{app_row.id}/approve",
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text

    profile = test_db.query(models.DelegateProfile).filter(
        models.DelegateProfile.user_id == applicant.id,
        models.DelegateProfile.topic_id == topic.id,
    ).first()
    assert profile is not None
    assert profile.is_active is True
    assert profile.org_id == org.id

    test_db.refresh(app_row)
    assert app_row.status == "approved"
    assert app_row.reviewed_by == admin.id


def test_deny_records_feedback(client, test_db):
    """Phase 10.2 audit: Class B, POST .../delegate-applications/{id}/deny
    — denial records feedback on the row and flips status to 'denied'."""
    admin = _make_user(test_db, "da_admin_d")
    applicant = _make_user(test_db, "da_applicant_d")
    org = _make_org(test_db, slug="da-deny")
    _join(test_db, admin, org, role="admin")
    _join(test_db, applicant, org, role="member")
    topic = _make_topic(test_db, "deny_topic")
    app_row = _make_app(test_db, applicant, org, topic)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/delegate-applications/{app_row.id}/deny",
        json={"feedback": "Not enough policy depth in your bio."},
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text

    test_db.refresh(app_row)
    assert app_row.status == "denied"
    assert app_row.feedback == "Not enough policy depth in your bio."
    assert app_row.reviewed_by == admin.id


def test_audit_emission_on_approve_and_deny(client, test_db):
    """Phase 10.2 audit: Class B, delegate-application audit emissions —
    approve emits delegate_application.approved, deny emits
    delegate_application.denied, both with target_id=app.id."""
    admin = _make_user(test_db, "da_admin_aud")
    applicant_a = _make_user(test_db, "da_app_yes")
    applicant_b = _make_user(test_db, "da_app_no")
    org = _make_org(test_db, slug="da-audit")
    _join(test_db, admin, org, role="admin")
    _join(test_db, applicant_a, org, role="member")
    _join(test_db, applicant_b, org, role="member")
    topic = _make_topic(test_db, "audit_topic")
    app_yes = _make_app(test_db, applicant_a, org, topic)
    # Different topic so the per-(user, org, topic) uniqueness constraint
    # doesn't trip.
    topic2 = _make_topic(test_db, "audit_topic_2")
    app_no = _make_app(test_db, applicant_b, org, topic2)
    test_db.commit()

    # Approve
    resp_y = client.post(
        f"/api/orgs/{org.slug}/delegate-applications/{app_yes.id}/approve",
        headers=_auth(admin),
    )
    assert resp_y.status_code == 200, resp_y.text

    # Deny
    resp_n = client.post(
        f"/api/orgs/{org.slug}/delegate-applications/{app_no.id}/deny",
        json={"feedback": "no"},
        headers=_auth(admin),
    )
    assert resp_n.status_code == 200, resp_n.text

    yes_audit = test_db.query(models.AuditLog).filter(
        models.AuditLog.action == "delegate_application.approved",
        models.AuditLog.target_id == app_yes.id,
    ).first()
    assert yes_audit is not None
    assert yes_audit.actor_id == admin.id
    assert yes_audit.details["user_id"] == applicant_a.id
    assert yes_audit.details["topic_id"] == topic.id

    no_audit = test_db.query(models.AuditLog).filter(
        models.AuditLog.action == "delegate_application.denied",
        models.AuditLog.target_id == app_no.id,
    ).first()
    assert no_audit is not None
    assert no_audit.details["feedback"] == "no"
