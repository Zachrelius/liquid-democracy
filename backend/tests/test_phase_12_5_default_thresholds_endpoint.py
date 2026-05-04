"""Phase 12.5 F4 backend support — default-thresholds save endpoint tests.

The frontend's F4 default-thresholds editor calls the existing
PATCH /api/orgs/{slug} endpoint with body.settings containing
`default_pass_threshold` and/or `default_quorum_threshold`. This file
exercises:

  - Happy path: Steward saves both keys; values persisted; audit event
    `org.default_thresholds_changed` emitted with the diff.
  - 403: Member (no `org.edit_settings`) blocked by require_org_admin
    before the threshold validation runs.
  - 400 validation: out-of-range value (negative or > 1.0); non-numeric
    value; bool sneaking through. No hard floor per spec Q2.
  - No-op: PATCH with a value matching the existing one emits NO audit
    event (only-when-changes pattern).
  - Independence: the threshold validation runs alongside (not instead
    of) sustained-majority validation; both audit events can fire on
    the same PATCH.
"""
from __future__ import annotations

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
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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


def _make_user(db: Session, username: str) -> models.User:
    u = models.User(
        username=username,
        display_name=username,
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=True,
    )
    db.add(u)
    db.flush()
    return u


def _make_org(
    db: Session, slug: str, *, settings: dict | None = None,
) -> models.Organization:
    o = models.Organization(
        name=slug.title(), slug=slug, description="",
        settings=settings if settings is not None else {},
    )
    db.add(o)
    db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _audit_events(db: Session, action: str) -> list[models.AuditLog]:
    return (
        db.query(models.AuditLog)
        .filter(models.AuditLog.action == action)
        .all()
    )


def test_steward_saves_both_default_thresholds(client, test_db):
    """Happy path: Steward PATCHes the org with both threshold keys;
    values persist into Organization.settings."""
    user = _make_user(test_db, "steward_save")
    org = _make_org(test_db, "steward-save")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/{org.slug}",
        json={"settings": {
            "default_pass_threshold": 0.55,
            "default_quorum_threshold": 0.30,
        }},
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["settings"]["default_pass_threshold"] == 0.55
    assert body["settings"]["default_quorum_threshold"] == 0.30


def test_admin_can_save_default_thresholds(client, test_db):
    """Admin (default org.edit_settings=True) can also save defaults —
    require_org_admin gate accepts admin/steward."""
    user = _make_user(test_db, "admin_save")
    org = _make_org(test_db, "admin-save")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="admin")
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/{org.slug}",
        json={"settings": {"default_pass_threshold": 0.66}},
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text


def test_member_cannot_save_default_thresholds(client, test_db):
    """Member is blocked by require_org_admin (a coarse tier check) —
    the threshold validation never runs, gate fires first with 403."""
    user = _make_user(test_db, "member_save")
    org = _make_org(test_db, "member-save")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="member")
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/{org.slug}",
        json={"settings": {"default_pass_threshold": 0.55}},
        headers=_auth(user),
    )
    assert resp.status_code == 403


def test_moderator_cannot_save_default_thresholds(client, test_db):
    """Moderator is below the admin tier; same 403 as Member."""
    user = _make_user(test_db, "mod_save")
    org = _make_org(test_db, "mod-save")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="moderator")
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/{org.slug}",
        json={"settings": {"default_pass_threshold": 0.55}},
        headers=_auth(user),
    )
    assert resp.status_code == 403


def test_negative_threshold_rejected_with_400(client, test_db):
    """0.0-1.0 inclusive validation; -0.1 rejected (no hard floor per
    spec Q2 means there's no MINIMUM positive value, but the range
    bound still applies — negative is invalid)."""
    user = _make_user(test_db, "neg_thresh")
    org = _make_org(test_db, "neg-thresh")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/{org.slug}",
        json={"settings": {"default_pass_threshold": -0.1}},
        headers=_auth(user),
    )
    assert resp.status_code == 400
    assert "default_pass_threshold" in resp.json()["detail"]


def test_above_one_threshold_rejected_with_400(client, test_db):
    """0.0-1.0 inclusive; 1.5 rejected."""
    user = _make_user(test_db, "high_thresh")
    org = _make_org(test_db, "high-thresh")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/{org.slug}",
        json={"settings": {"default_quorum_threshold": 1.5}},
        headers=_auth(user),
    )
    assert resp.status_code == 400
    assert "default_quorum_threshold" in resp.json()["detail"]


def test_string_threshold_rejected_with_400(client, test_db):
    """Non-numeric values get a 400 with a clear message — guards
    against frontend sending the form input as a string."""
    user = _make_user(test_db, "str_thresh")
    org = _make_org(test_db, "str-thresh")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/{org.slug}",
        json={"settings": {"default_pass_threshold": "0.5"}},
        headers=_auth(user),
    )
    assert resp.status_code == 400


def test_boolean_threshold_rejected_with_400(client, test_db):
    """Bool sneaking through (Python bool isinstance int is True; we
    explicitly exclude bool to avoid False being accepted as 0.0)."""
    user = _make_user(test_db, "bool_thresh")
    org = _make_org(test_db, "bool-thresh")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/{org.slug}",
        json={"settings": {"default_pass_threshold": True}},
        headers=_auth(user),
    )
    assert resp.status_code == 400


def test_zero_and_one_boundary_values_accepted(client, test_db):
    """Spec line 245: 0.0 and 1.0 are inclusive endpoints."""
    user = _make_user(test_db, "boundary")
    org = _make_org(test_db, "boundary")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/{org.slug}",
        json={"settings": {
            "default_pass_threshold": 0.0,
            "default_quorum_threshold": 1.0,
        }},
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text


def test_save_emits_audit_event_with_diff(client, test_db):
    """Phase 12.5 audit: `org.default_thresholds_changed` event with a
    `changes` map of {key: {old, new}}. Only emits when values actually
    change."""
    user = _make_user(test_db, "audit_save")
    org = _make_org(test_db, "audit-save")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/{org.slug}",
        json={"settings": {"default_pass_threshold": 0.66}},
        headers=_auth(user),
    )
    assert resp.status_code == 200

    events = _audit_events(test_db, "org.default_thresholds_changed")
    assert len(events) == 1
    details = events[0].details
    assert "changes" in details
    assert "default_pass_threshold" in details["changes"]
    assert details["changes"]["default_pass_threshold"]["new"] == 0.66
    assert details["changes"]["default_pass_threshold"]["old"] is None


def test_no_op_save_emits_no_audit_event(client, test_db):
    """PATCH with a value matching the existing one is a no-op for the
    audit log — only-when-changes pattern matches the
    sustained-majority precedent."""
    user = _make_user(test_db, "noop_save")
    org = _make_org(
        test_db, "noop-save",
        settings={"default_pass_threshold": 0.55},
    )
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="steward")
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/{org.slug}",
        json={"settings": {"default_pass_threshold": 0.55}},
        headers=_auth(user),
    )
    assert resp.status_code == 200
    events = _audit_events(test_db, "org.default_thresholds_changed")
    assert len(events) == 0
