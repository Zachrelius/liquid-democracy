"""Phase 101 trusted proposal-creation tier coverage.

These tests exercise the real organization-scoped create route and assert
persisted proposals/audits, not only the limiter helper's return value.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
import rate_limit_utils
from database import Base, get_db
from main import app
from tests.conftest import make_org_membership, make_sub_org_membership


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


@pytest.fixture()
def test_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def client(test_db, monkeypatch):
    def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(rate_limit_utils, "_bypass_active", lambda: False)
    rate_limit_utils.content_limiter.reset()
    try:
        yield TestClient(app)
    finally:
        rate_limit_utils.content_limiter.reset()
        app.dependency_overrides.clear()


def _user(db, username):
    user = models.User(
        username=username,
        display_name=username.title(),
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=True,
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _org(db, slug):
    org = models.Organization(
        name=slug.title(), slug=slug, description="", join_policy="open",
        settings={"default_voting_days": 7},
    )
    db.add(org)
    db.flush()
    return org


def _auth(user):
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _payload(index):
    return {
        "title": f"Proposal {index}",
        "body": "Created through the canonical organization route.",
        "voting_method": "binary",
        "topics": [],
    }


def _set_permission(db, org_id, role_key, permission_key, enabled):
    role = db.query(models.Role).filter_by(
        org_id=org_id, system_key=role_key,
    ).one()
    row = db.query(models.RolePermission).filter_by(
        role_id=role.id, permission_key=permission_key,
    ).one_or_none()
    if row is None:
        row = models.RolePermission(
            role_id=role.id, permission_key=permission_key, enabled=enabled,
        )
        db.add(row)
    else:
        row.enabled = enabled
    db.commit()
    db.info.pop("_permission_cache", None)


def test_ordinary_creator_gets_ten_successes_then_429_without_extra_writes(
    client, test_db,
):
    org = _org(test_db, "ordinary-limit")
    user = _user(test_db, "ordinary")
    make_org_membership(
        test_db, org_id=org.id, user_id=user.id, role="moderator",
    )
    test_db.commit()

    malformed = client.post(
        f"/api/orgs/{org.slug}/proposals",
        headers=_auth(user), json={"title": ""},
    )
    assert malformed.status_code == 422

    for index in range(10):
        response = client.post(
            f"/api/orgs/{org.slug}/proposals",
            headers=_auth(user), json=_payload(index),
        )
        assert response.status_code == 201, (index, response.text)

    rejected = client.post(
        f"/api/orgs/{org.slug}/proposals",
        headers=_auth(user), json=_payload(10),
    )
    assert rejected.status_code == 429, rejected.text
    assert isinstance(rejected.json().get("error"), str)
    assert "Rate limit exceeded" in rejected.json()["error"]
    assert test_db.query(models.Proposal).filter_by(author_id=user.id).count() == 10
    audits = test_db.query(models.AuditLog).filter_by(
        action="proposal.created", actor_id=user.id,
    ).all()
    assert len(audits) == 10
    assert all("high_volume_rate_tier" not in event.details for event in audits)


def test_high_volume_creator_completes_200_items_with_audited_side_effects(
    client, test_db,
):
    org = _org(test_db, "trusted-volume")
    user = _user(test_db, "trusted")
    make_org_membership(
        test_db, org_id=org.id, user_id=user.id, role="admin",
    )
    test_db.commit()

    for index in range(200):
        response = client.post(
            f"/api/orgs/{org.slug}/proposals",
            headers=_auth(user), json=_payload(index),
        )
        assert response.status_code == 201, (index, response.text)

    assert test_db.query(models.Proposal).filter_by(author_id=user.id).count() == 200
    audits = test_db.query(models.AuditLog).filter_by(
        action="proposal.created", actor_id=user.id,
    ).all()
    assert len(audits) == 200
    assert all(event.details.get("high_volume_rate_tier") is True for event in audits)


def test_revocation_takes_effect_and_uses_a_separate_ordinary_counter(
    client, test_db,
):
    org = _org(test_db, "revocation")
    user = _user(test_db, "revoked")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="admin")
    test_db.commit()

    first = client.post(
        f"/api/orgs/{org.slug}/proposals", headers=_auth(user), json=_payload(0),
    )
    assert first.status_code == 201, first.text
    _set_permission(
        test_db, org.id, "admin", "proposal.high_volume_create", False,
    )

    for index in range(1, 11):
        response = client.post(
            f"/api/orgs/{org.slug}/proposals",
            headers=_auth(user), json=_payload(index),
        )
        assert response.status_code == 201, (index, response.text)
    rejected = client.post(
        f"/api/orgs/{org.slug}/proposals",
        headers=_auth(user), json=_payload(11),
    )
    assert rejected.status_code == 429

    events = test_db.query(models.AuditLog).filter_by(
        action="proposal.created", actor_id=user.id,
    ).order_by(models.AuditLog.timestamp.asc()).all()
    assert len(events) == 11
    assert events[0].details.get("high_volume_rate_tier") is True
    assert all("high_volume_rate_tier" not in event.details for event in events[1:])


def test_high_volume_key_never_grants_creation_authority(client, test_db):
    org = _org(test_db, "no-create")
    user = _user(test_db, "no_create")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="admin")
    test_db.commit()
    _set_permission(test_db, org.id, "admin", "proposal.create", False)

    response = client.post(
        f"/api/orgs/{org.slug}/proposals",
        headers=_auth(user), json=_payload(0),
    )
    assert response.status_code == 403
    assert test_db.query(models.Proposal).count() == 0
    assert test_db.query(models.AuditLog).filter_by(
        action="proposal.created",
    ).count() == 0


def test_entitlement_is_resolved_against_effective_target_org(test_db):
    parent = _org(test_db, "parent")
    other = _org(test_db, "other")
    sub_org = models.Organization(
        name="Sub Org", slug="sub-org", description="",
        parent_org_id=parent.id, settings={},
    )
    test_db.add(sub_org)
    user = _user(test_db, "scoped")
    make_org_membership(
        test_db, org_id=parent.id, user_id=user.id, role="moderator",
    )
    make_org_membership(
        test_db, org_id=other.id, user_id=user.id, role="admin",
    )
    test_db.flush()

    # High-volume rights in another org cannot leak into this parent scope.
    assert rate_limit_utils.resolve_proposal_create_rate_tier(
        test_db, user.id, parent,
    ) == "ordinary"

    # An actual sub-org admin role inherits the parent matrix and qualifies.
    make_sub_org_membership(
        test_db, sub_org_id=sub_org.id, user_id=user.id, role="admin",
    )
    assert rate_limit_utils.resolve_proposal_create_rate_tier(
        test_db, user.id, sub_org,
    ) == "high_volume"


def test_matrix_grant_enables_tier_and_inactive_states_fail_closed(test_db):
    org = _org(test_db, "matrix-grant")
    moderator = _user(test_db, "matrix_moderator")
    make_org_membership(
        test_db, org_id=org.id, user_id=moderator.id, role="moderator",
    )
    test_db.commit()
    assert rate_limit_utils.resolve_proposal_create_rate_tier(
        test_db, moderator.id, org,
    ) == "ordinary"

    _set_permission(
        test_db, org.id, "moderator", "proposal.high_volume_create", True,
    )
    assert rate_limit_utils.resolve_proposal_create_rate_tier(
        test_db, moderator.id, org,
    ) == "high_volume"

    moderator.email_verified = False
    test_db.flush()
    assert rate_limit_utils.resolve_proposal_create_rate_tier(
        test_db, moderator.id, org,
    ) == "ordinary"
    moderator.email_verified = True
    moderator.is_active = False
    test_db.flush()
    assert rate_limit_utils.resolve_proposal_create_rate_tier(
        test_db, moderator.id, org,
    ) == "ordinary"
    moderator.is_active = True
    membership = test_db.query(models.OrgMembership).filter_by(
        user_id=moderator.id, org_id=org.id,
    ).one()
    membership.status = "suspended"
    test_db.flush()
    assert rate_limit_utils.resolve_proposal_create_rate_tier(
        test_db, moderator.id, org,
    ) == "ordinary"

    nonmember = _user(test_db, "matrix_nonmember")
    test_db.flush()
    assert rate_limit_utils.resolve_proposal_create_rate_tier(
        test_db, nonmember.id, org,
    ) == "ordinary"


def test_parent_role_transferability_controls_sub_org_tier(test_db):
    parent = _org(test_db, "transfer-parent")
    sub_org = models.Organization(
        name="Transfer Sub", slug="transfer-sub", description="",
        parent_org_id=parent.id, settings={},
    )
    user = _user(test_db, "transfer_admin")
    test_db.add(sub_org)
    make_org_membership(
        test_db, org_id=parent.id, user_id=user.id, role="admin",
    )
    test_db.flush()

    parent.settings = {
        "sub_org_role_transferability": {"admin": False},
    }
    test_db.flush()
    assert rate_limit_utils.resolve_proposal_create_rate_tier(
        test_db, user.id, sub_org,
    ) == "ordinary"

    parent.settings = {
        "sub_org_role_transferability": {"admin": True},
    }
    test_db.flush()
    assert rate_limit_utils.resolve_proposal_create_rate_tier(
        test_db, user.id, sub_org,
    ) == "high_volume"


def test_platform_admin_fallback_alone_does_not_receive_trusted_tier(test_db):
    from role_seed import seed_default_roles_for_org

    parent = _org(test_db, "platform-parent")
    sub_org = models.Organization(
        name="Private Sub", slug="private-sub", description="",
        parent_org_id=parent.id, settings={},
    )
    user = _user(test_db, "platform_only")
    user.is_admin = True
    test_db.add(sub_org)
    seed_default_roles_for_org(test_db, parent.id)
    test_db.flush()

    assert rate_limit_utils.resolve_proposal_create_rate_tier(
        test_db, user.id, sub_org,
    ) == "ordinary"


def test_high_volume_safety_fuse_raises_on_injected_small_bound(monkeypatch):
    monkeypatch.setattr(rate_limit_utils, "_bypass_active", lambda: False)
    rate_limit_utils.content_limiter.reset()
    request = SimpleNamespace(state=SimpleNamespace())
    try:
        for _ in range(2):
            rate_limit_utils.enforce_proposal_create_rate_limit(
                request, "safety-user", "high_volume", high_volume_limit="2/day",
            )
        with pytest.raises(RateLimitExceeded):
            rate_limit_utils.enforce_proposal_create_rate_limit(
                request, "safety-user", "high_volume", high_volume_limit="2/day",
            )
    finally:
        rate_limit_utils.content_limiter.reset()


def test_high_volume_safety_fuse_route_rejection_has_no_side_effects(
    client, test_db, monkeypatch,
):
    from routes import organizations

    original = rate_limit_utils.enforce_proposal_create_rate_limit

    def small_fuse(request, user_id, tier):
        return original(
            request, user_id, tier,
            high_volume_limit="2/day",
        )

    monkeypatch.setattr(
        organizations, "enforce_proposal_create_rate_limit", small_fuse,
    )
    org = _org(test_db, "small-fuse")
    user = _user(test_db, "small_fuse_admin")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="admin")
    test_db.commit()

    for index in range(2):
        response = client.post(
            f"/api/orgs/{org.slug}/proposals",
            headers=_auth(user), json=_payload(index),
        )
        assert response.status_code == 201, response.text
    rejected = client.post(
        f"/api/orgs/{org.slug}/proposals",
        headers=_auth(user), json=_payload(2),
    )
    assert rejected.status_code == 429
    assert test_db.query(models.Proposal).filter_by(author_id=user.id).count() == 2
    assert test_db.query(models.AuditLog).filter_by(
        action="proposal.created", actor_id=user.id,
    ).count() == 2


def test_global_create_route_retains_the_ordinary_decorator():
    from routes import proposals

    assert proposals.PROPOSAL_CREATE_LIMIT == "10/day"
    assert hasattr(proposals.create_proposal, "__wrapped__")
