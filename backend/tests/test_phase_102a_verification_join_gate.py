"""Phase 102a — public membership requirements and non-mutating join gates."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import auth as auth_utils
import models
import verification
from database import get_db
from main import app
from role_seed import seed_default_roles_for_org
from tests.conftest import make_user


@pytest.fixture()
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def _headers(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _org(db, slug: str, *, join_policy: str = "open", **verification_settings):
    settings = {
        "default_deliberation_days": 1,
        "default_voting_days": 7,
        "default_pass_threshold": 0.5,
        "default_quorum_threshold": 0.0,
        "allowed_voting_methods": ["binary"],
        **verification_settings,
    }
    org = models.Organization(
        name=slug.replace("-", " ").title(),
        slug=slug,
        description="",
        join_policy=join_policy,
        settings=settings,
    )
    db.add(org)
    db.flush()
    seed_default_roles_for_org(db, org.id)
    db.commit()
    return org


def _verification_settings():
    return {
        verification.SETTING_MEMBERSHIP_FLOOR: verification.ADDRESS_ON_ID,
        verification.SETTING_MEMBERSHIP_JURISDICTION: "MA",
        verification.SETTING_MEMBERSHIP_REQUIRE_RESIDENCY: True,
        verification.SETTING_RESIDENCY_SCOPE: [
            {"state": "ma"},
            {"state": "NH", "city": "Concord"},
            {"country": "ca"},
        ],
        verification.SETTING_MEMBERSHIP_MIN_AGE: 18,
    }


def test_public_requirements_normalize_rules_and_exclude_applicant_data():
    org = SimpleNamespace(settings={
        **_verification_settings(),
        "applicant_address": "must never escape",
        "verification_locality_hash": "private-hash",
        "provider_session": "private-session",
    })
    payload = verification.membership_verification_requirements(org)
    assert payload == {
        "floor": "address_on_id",
        "jurisdiction": "MA",
        "requires_residency": True,
        "residency_scope": [
            {"country": None, "state": "MA", "city": None},
            {"country": None, "state": "NH", "city": "Concord"},
            {"country": "CA", "state": None, "city": None},
        ],
        "min_age": 18,
    }
    serialized_keys = set(payload)
    serialized_keys.update(key for entry in payload["residency_scope"] for key in entry)
    assert serialized_keys.isdisjoint({
        "applicant_address", "verification_locality_hash", "legal_name",
        "dob", "document_number", "provider_session", "attestation",
        "duplicate_flags",
    })


def test_public_requirements_fail_safely_for_malformed_settings():
    assert verification.membership_verification_requirements(
        SimpleNamespace(settings="malformed")
    ) == {
        "floor": "email_only",
        "jurisdiction": None,
        "requires_residency": False,
        "residency_scope": [],
        "min_age": None,
    }
    malformed = SimpleNamespace(settings={
        verification.SETTING_MEMBERSHIP_FLOOR: "unknown",
        verification.SETTING_MEMBERSHIP_MIN_AGE: "eighteen",
        verification.SETTING_RESIDENCY_SCOPE: [{"city": "Nowhere"}, "bad"],
    })
    assert verification.membership_verification_requirements(malformed)["residency_scope"] == []
    assert verification.membership_verification_requirements(malformed)["min_age"] is None


def test_no_setting_org_keeps_the_existing_floor_contract_with_additive_parity():
    org = SimpleNamespace(settings={})
    unverified = SimpleNamespace(verification_state="email_only")

    assert verification.membership_verification_requirements(org) == {
        "floor": "email_only",
        "jurisdiction": None,
        "requires_residency": False,
        "residency_scope": [],
        "min_age": None,
    }
    verification.check_membership_floor_for_join(unverified, org)


def test_each_membership_gate_attaches_the_same_canonical_requirements():
    org = SimpleNamespace(settings=_verification_settings())
    unverified = SimpleNamespace(
        verification_state="email_only",
        verification_jurisdiction=None,
        verification_country=None,
        verification_locality_hash=None,
        verification_age_bands=None,
        verification_age_promotes_at=None,
    )
    expected = verification.membership_verification_requirements(org)

    with pytest.raises(HTTPException) as floor_exc:
        verification.check_membership_floor_for_join(unverified, org)
    assert floor_exc.value.detail["membership_requirements"] == expected
    assert floor_exc.value.detail["floor"] == "address_on_id"

    with pytest.raises(HTTPException) as age_exc:
        verification.check_membership_min_age_for_join(unverified, org)
    assert age_exc.value.detail["membership_requirements"] == expected
    assert age_exc.value.detail["min_age"] == 18

    with pytest.raises(HTTPException) as residency_exc:
        verification.check_membership_locality_for_join(unverified, org)
    assert residency_exc.value.detail["membership_requirements"] == expected
    assert residency_exc.value.detail["residency_scope"] == expected["residency_scope"]


@pytest.mark.parametrize(
    ("join_policy", "endpoint"),
    [
        ("open", "/api/orgs/{slug}/join"),
        ("approval_required", "/api/orgs/{slug}/join-request"),
    ],
)
def test_open_and_approval_join_denials_are_non_mutating(
    client, db, join_policy, endpoint,
):
    org = _org(
        db, f"phase102a-{join_policy}", join_policy=join_policy,
        **_verification_settings(),
    )
    user = make_user(db, f"phase102a-{join_policy}-user")
    db.commit()
    audit_before = db.query(models.AuditLog).count()
    notification_before = db.query(models.Notification).count()

    response = client.post(endpoint.format(slug=org.slug), headers=_headers(user))
    assert response.status_code == 403, response.text
    assert response.json()["detail"]["membership_requirements"]["residency_scope"][0] == {
        "country": None, "state": "MA", "city": None,
    }
    assert db.query(models.OrgMembership).filter_by(org_id=org.id, user_id=user.id).count() == 0
    assert db.query(models.AuditLog).count() == audit_before
    assert db.query(models.Notification).count() == notification_before


def test_invitation_denial_preserves_pending_invite_and_has_no_side_effects(client, db):
    org = _org(db, "phase102a-invite", join_policy="invite_only", **_verification_settings())
    inviter = make_user(db, "phase102a-inviter")
    invitee = make_user(db, "phase102a-invitee")
    invitation = models.Invitation(
        org_id=org.id,
        email=invitee.email,
        invited_by=inviter.id,
        role="member",
        token="phase102a-invitation-token",
        status="pending",
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7),
    )
    db.add(invitation)
    db.commit()
    audit_before = db.query(models.AuditLog).count()
    notification_before = db.query(models.Notification).count()

    response = client.post(
        f"/api/orgs/join/{invitation.token}", headers=_headers(invitee),
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"]["membership_requirements"]["requires_residency"] is True
    db.refresh(invitation)
    assert invitation.status == "pending"
    assert db.query(models.OrgMembership).filter_by(org_id=org.id, user_id=invitee.id).count() == 0
    assert db.query(models.AuditLog).count() == audit_before
    assert db.query(models.Notification).count() == notification_before


def test_matching_verified_massachusetts_resident_still_joins(client, db):
    org = _org(db, "phase102a-matching", join_policy="open", **_verification_settings())
    user = make_user(db, "phase102a-matching-user")
    user.verification_state = verification.ADDRESS_ON_ID
    user.verification_jurisdiction = "MA"
    user.verification_country = "US"
    user.verification_age_bands = verification.serialize_age_bands([13, 16, 18])
    user.verification_provenance = verification.PROV_DIDIT
    user.verification_updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()

    response = client.post(f"/api/orgs/{org.slug}/join", headers=_headers(user))
    assert response.status_code == 200, response.text
    assert db.query(models.OrgMembership).filter_by(
        org_id=org.id, user_id=user.id, status="active",
    ).count() == 1
