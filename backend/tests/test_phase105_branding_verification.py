from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event

import auth as auth_utils
import models
import schemas
import verification
from database import get_db
from main import app
from role_seed import seed_default_roles_for_org
from tests.conftest import make_org_membership, make_user


@pytest.fixture()
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def _headers(user):
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _org(db, slug="phase105", *, settings=None, parent_org_id=None):
    org = models.Organization(
        name=slug.replace("-", " ").title(),
        slug=slug,
        description="",
        join_policy="open",
        parent_org_id=parent_org_id,
        settings=settings or {},
    )
    db.add(org)
    db.flush()
    seed_default_roles_for_org(db, org.id)
    return org


def _verified_user(db, username="verified", display_name="Alice Smith"):
    user = make_user(db, username, display_name)
    user.verification_state = verification.IDENTITY
    user.verification_provenance = verification.PROV_DIDIT
    user.legal_first_name = "Alice"
    user.legal_last_name = "Smith"
    user.legal_full_name = "Alice Smith"
    return user


def test_branding_header_color_schema_validation_and_public_round_trip(client, db):
    steward = make_user(db, "brand-steward")
    org = _org(db, "brand-header")
    make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
    db.commit()

    response = client.patch(
        f"/api/orgs/{org.slug}/branding",
        headers=_headers(steward),
        json={"header_text_color": "#000", "primary_color": "#FFD700"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["branding"]["header_text_color"] == "#000"
    public = client.get(f"/api/orgs/{org.slug}/public")
    assert public.status_code == 200
    assert public.json()["branding"]["header_text_color"] == "#000"
    invalid = client.patch(
        f"/api/orgs/{org.slug}/branding",
        headers=_headers(steward),
        json={"header_text_color": "black"},
    )
    assert invalid.status_code == 422
    audit = db.query(models.AuditLog).filter_by(action="org.branding_updated").first()
    assert audit.details["changes"]["header_text_color"] == {
        "old": None, "new": "#000",
    }
    cleared = client.patch(
        f"/api/orgs/{org.slug}/branding",
        headers=_headers(steward), json={"header_text_color": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["branding"]["header_text_color"] is None


def test_header_color_inherits_into_sub_org_serializer(db):
    parent = _org(db, "brand-parent", settings={
        "branding": {"header_text_color": "#123456"},
    })
    child = _org(db, "brand-child", parent_org_id=parent.id)
    from routes.sub_organizations import _sub_org_to_out
    out = _sub_org_to_out(child, db)
    assert out.branding.header_text_color == "#123456"


@pytest.mark.parametrize(
    ("choice", "floor", "residency"),
    [("none", None, False), ("identity", "identity", False),
     ("resident", "address_on_id", True)],
)
def test_canonical_visible_requirement_mapper(choice, floor, residency):
    requirement = verification.visible_requirement(choice)
    assert requirement.floor == floor
    assert requirement.require_residency is residency
    assert requirement.jurisdiction is None


def test_merged_settings_reject_invalid_country_and_touched_address_only():
    current = {
        verification.SETTING_MEMBERSHIP_FLOOR: verification.ADDRESS_ON_ID,
        verification.SETTING_MEMBERSHIP_REQUIRE_RESIDENCY: False,
    }
    # Unrelated saves preserve legacy address-only state.
    merged, errors = verification.validate_org_verification_settings(
        current, {"unrelated": True},
    )
    assert errors == {}
    assert merged[verification.SETTING_MEMBERSHIP_FLOOR] == verification.ADDRESS_ON_ID

    _, errors = verification.validate_org_verification_settings(current, {
        verification.SETTING_MEMBERSHIP_FLOOR: verification.ADDRESS_ON_ID,
        verification.SETTING_MEMBERSHIP_REQUIRE_RESIDENCY: False,
    })
    assert verification.SETTING_MEMBERSHIP_FLOOR in errors

    _, errors = verification.validate_org_verification_settings({}, {
        verification.SETTING_MEMBERSHIP_FLOOR: verification.ADDRESS_ON_ID,
        verification.SETTING_MEMBERSHIP_REQUIRE_RESIDENCY: True,
        verification.SETTING_RESIDENCY_SCOPE: [{"country": "ZZ"}],
    })
    assert verification.SETTING_RESIDENCY_SCOPE in errors


def test_resident_settings_require_shared_scope_and_clear_old_jurisdiction():
    merged, errors = verification.validate_org_verification_settings({}, {
        verification.SETTING_PROPOSAL_POLICY: verification.PROPOSAL_POLICY_ALWAYS,
        verification.SETTING_PROPOSAL_FLOOR: verification.ADDRESS_ON_ID,
        verification.SETTING_PROPOSAL_REQUIRE_RESIDENCY: True,
        verification.SETTING_PROPOSAL_JURISDICTION: "MA",
        verification.SETTING_RESIDENCY_SCOPE: [{"country": "US", "state": "MA"}],
    })
    assert errors == {}
    assert merged[verification.SETTING_PROPOSAL_JURISDICTION] is None


def test_scope_removal_is_atomic_for_every_dependent_gate():
    current = {
        verification.SETTING_RESIDENCY_SCOPE: [{"state": "MA"}],
        verification.SETTING_MEMBERSHIP_FLOOR: verification.ADDRESS_ON_ID,
        verification.SETTING_MEMBERSHIP_REQUIRE_RESIDENCY: True,
        verification.SETTING_ROLE_FLOORS: {"admin": verification.ADDRESS_ON_ID},
        verification.SETTING_ROLE_REQUIRE_RESIDENCY: {"admin": True},
        verification.SETTING_PROPOSAL_POLICY: "always",
        verification.SETTING_PROPOSAL_FLOOR: verification.ADDRESS_ON_ID,
        verification.SETTING_PROPOSAL_REQUIRE_RESIDENCY: True,
    }
    merged, errors = verification.validate_org_verification_settings(
        current, {verification.SETTING_RESIDENCY_SCOPE: []},
    )
    assert verification.SETTING_RESIDENCY_SCOPE in errors
    assert merged[verification.SETTING_RESIDENCY_SCOPE] == []


def test_role_and_membership_three_choice_route_mapping(client, db):
    steward = make_user(db, "settings-steward")
    org = _org(db, "three-choice")
    make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
    db.commit()
    response = client.patch(
        f"/api/orgs/{org.slug}", headers=_headers(steward),
        json={"settings": {
            "verification_residency_scope": [{"state": "MA"}],
            "verification_membership_floor": "address_on_id",
            "verification_membership_require_residency": True,
            "verification_role_floors": {"admin": "identity", "steward": "address_on_id"},
            "verification_role_require_residency": {"admin": False, "steward": True},
        }},
    )
    assert response.status_code == 200, response.text
    db.refresh(org)
    assert org.settings["verification_membership_require_residency"] is True
    assert org.settings["verification_role_require_residency"] == {
        "admin": False, "steward": True,
    }


def test_typed_requirement_distinguishes_shared_scope_from_legacy_jurisdiction():
    org = SimpleNamespace(settings={verification.SETTING_PROPOSAL_POLICY: "author"})
    shared = SimpleNamespace(
        verification_floor="address_on_id",
        verification_jurisdiction=None,
        verification_require_residency=True,
    )
    legacy = SimpleNamespace(
        verification_floor="address_on_id",
        verification_jurisdiction="MA",
        verification_require_residency=None,
    )
    assert verification.effective_proposal_requirement(shared, org) == (
        verification.VerificationRequirement("address_on_id", None, True, False)
    )
    assert verification.effective_proposal_requirement(legacy, org) == (
        verification.VerificationRequirement("address_on_id", "MA", False, True)
    )


def test_resident_vote_requires_floor_and_shared_scope():
    org = SimpleNamespace(settings={
        verification.SETTING_PROPOSAL_POLICY: "author",
        verification.SETTING_RESIDENCY_SCOPE: [{"state": "MA"}],
    })
    proposal = SimpleNamespace(
        verification_floor="address_on_id",
        verification_jurisdiction=None,
        verification_require_residency=True,
    )
    wrong_state = SimpleNamespace(
        verification_state="address_on_id",
        verification_jurisdiction="NH",
        verification_country="US",
        verification_locality_hash=None,
    )
    with pytest.raises(HTTPException) as exc:
        verification.check_vote_floor_for_proposal(wrong_state, proposal, org)
    assert exc.value.detail["requires_residency"] is True


def test_org_proposal_resident_round_trip_and_address_only_rejection(client, db):
    steward = make_user(db, "proposal-steward")
    org = _org(db, "proposal-resident", settings={
        "verification_proposal_policy": "author",
        "verification_residency_scope": [{"state": "MA"}],
        "default_deliberation_days": 1,
        "default_voting_days": 7,
        "default_pass_threshold": 0.5,
        "default_quorum_threshold": 0.0,
    })
    make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
    db.commit()
    payload = {
        "title": "Resident ballot",
        "body": "Body",
        "verification_floor": "address_on_id",
        "verification_require_residency": True,
    }
    response = client.post(
        f"/api/orgs/{org.slug}/proposals", headers=_headers(steward), json=payload,
    )
    assert response.status_code == 201, response.text
    assert response.json()["verification_require_residency"] is True
    proposal = db.get(models.Proposal, response.json()["id"])
    assert proposal.verification_jurisdiction is None

    rejected = client.post(
        f"/api/orgs/{org.slug}/proposals",
        headers=_headers(steward),
        json={
            "title": "Legacy new write", "body": "Body",
            "verification_floor": "address_on_id",
            "verification_jurisdiction": "MA",
        },
    )
    assert rejected.status_code == 400


def test_global_proposal_identity_round_trip_and_resident_rejection(client, db):
    user = make_user(db, "global-author")
    user.is_admin = True
    db.commit()
    created = client.post(
        "/api/proposals", headers=_headers(user),
        json={
            "title": "Global identity", "body": "Body",
            "verification_floor": "identity",
            "verification_require_residency": False,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["verification_require_residency"] is False
    rejected = client.post(
        "/api/proposals", headers=_headers(user),
        json={
            "title": "Global resident", "body": "Body",
            "verification_floor": "address_on_id",
            "verification_require_residency": True,
        },
    )
    assert rejected.status_code == 400


def test_legacy_import_token_is_scoped_and_allows_preview_create(client, db):
    steward = make_user(db, "import-steward")
    org = _org(db, "legacy-import", settings={
        "default_deliberation_days": 1,
        "default_voting_days": 7,
        "default_pass_threshold": 0.5,
        "default_quorum_threshold": 0.0,
    })
    make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
    token = verification.make_legacy_proposal_import_token(
        org.id, "address_on_id", "MA",
    )
    db.commit()
    response = client.post(
        f"/api/orgs/{org.slug}/proposals",
        headers=_headers(steward),
        json={
            "title": "Imported legacy", "body": "Body",
            "verification_floor": "address_on_id",
            "verification_jurisdiction": "MA",
            "verification_legacy_import_token": token,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["verification_require_residency"] is None
    assert not verification.valid_legacy_proposal_import_token(
        token, "different-org", "address_on_id", "MA",
    )


def test_import_template_and_preview_emit_residency_contract_and_signed_legacy_grant(client, db):
    steward = make_user(db, "preview-steward")
    org = _org(db, "preview-import")
    make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
    db.commit()
    template = client.get(
        f"/api/orgs/{org.slug}/proposals/import-template",
        headers=_headers(steward),
    )
    assert template.status_code == 200
    assert template.json()["verification_require_residency"] is False
    preview = client.post(
        f"/api/orgs/{org.slug}/proposals/import-preview",
        headers={**_headers(steward), "content-type": "application/json"},
        json={
            "title": "Legacy preview", "body": "Body",
            "verification_floor": "address_on_id",
            "verification_jurisdiction": "MA",
        },
    )
    assert preview.status_code == 200, preview.text
    proposal = preview.json()["proposal"]
    assert proposal["verification_legacy_import_token"]
    assert verification.valid_legacy_proposal_import_token(
        proposal["verification_legacy_import_token"], org.id,
        "address_on_id", "MA",
    )


def test_orgout_and_typed_display_name_set_reset_audit_idempotency(client, db):
    user = make_user(db, "org-name-user", "Default Name")
    org = _org(db, "org-name")
    membership = make_org_membership(
        db, org_id=org.id, user_id=user.id, role="member",
    )
    db.commit()
    initial = client.get(f"/api/orgs/{org.slug}", headers=_headers(user)).json()
    assert initial["my_display_name"] == "Default Name"
    assert initial["my_display_name_override"] is None

    set_response = client.patch(
        f"/api/orgs/{org.slug}/me/display-name",
        headers=_headers(user), json={"display_name": "Committee Name"},
    )
    assert set_response.status_code == 200
    assert set_response.json() == {
        "my_display_name": "Committee Name",
        "my_display_name_override": "Committee Name",
    }
    # Exact retry is a no-op and does not duplicate audit events.
    retry = client.patch(
        f"/api/orgs/{org.slug}/me/display-name",
        headers=_headers(user), json={"display_name": "Committee Name"},
    )
    assert retry.status_code == 200
    assert db.query(models.AuditLog).filter_by(action="org.display_name_changed").count() == 1
    reset = client.patch(
        f"/api/orgs/{org.slug}/me/display-name",
        headers=_headers(user), json={"display_name": None},
    )
    assert reset.json()["my_display_name"] == "Default Name"
    db.refresh(membership)
    assert membership.display_name is None


def test_display_name_length_blank_parent_scope_and_cross_org_isolation(client, db):
    user = make_user(db, "name-boundaries", "Default")
    parent = _org(db, "name-parent")
    child = _org(db, "name-child", parent_org_id=parent.id)
    other = _org(db, "name-other")
    parent_membership = make_org_membership(db, org_id=parent.id, user_id=user.id)
    other_membership = make_org_membership(db, org_id=other.id, user_id=user.id)
    db.commit()
    eighty = "x" * 80
    accepted = client.patch(
        f"/api/orgs/{parent.slug}/me/display-name",
        headers=_headers(user), json={"display_name": eighty},
    )
    assert accepted.status_code == 200
    too_long = client.patch(
        f"/api/orgs/{parent.slug}/me/display-name",
        headers=_headers(user), json={"display_name": "x" * 81},
    )
    assert too_long.status_code == 422
    # A sub-org slug resolves to the single parent membership override.
    child_write = client.patch(
        f"/api/orgs/{child.slug}/me/display-name",
        headers=_headers(user), json={"display_name": "Parent Scoped"},
    )
    assert child_write.status_code == 200, child_write.text
    db.refresh(parent_membership)
    db.refresh(other_membership)
    assert parent_membership.display_name == "Parent Scoped"
    assert other_membership.display_name is None
    blank_reset = client.patch(
        f"/api/orgs/{parent.slug}/me/display-name",
        headers=_headers(user), json={"display_name": "   "},
    )
    assert blank_reset.status_code == 200
    assert blank_reset.json()["my_display_name_override"] is None


def test_public_delegate_name_rule_is_strict_tenant_scoped_and_reset_safe(client, db):
    user = _verified_user(db, "public-delegate")
    org = _org(db, "strict-name", settings={
        "verification_require_name_match": "full",
        "verification_name_match_scope": "public_delegates",
    })
    other = _org(db, "other-tenant", settings={
        "verification_require_name_match": "full",
        "verification_name_match_scope": "public_delegates",
    })
    membership = make_org_membership(db, org_id=org.id, user_id=user.id)
    make_org_membership(db, org_id=other.id, user_id=user.id)
    topic = models.Topic(org_id=org.id, name="Housing", color="#000")
    db.add(topic)
    db.flush()
    db.add(models.DelegateProfile(
        user_id=user.id, topic_id=topic.id, org_id=org.id, visibility="public",
    ))
    membership.display_name = "Alice Smith"
    db.commit()

    assert verification.is_org_public_delegate(db, user.id, org.id)
    assert not verification.is_org_public_delegate(db, user.id, other.id)
    mismatch = client.patch(
        f"/api/orgs/{org.slug}/me/display-name",
        headers=_headers(user), json={"display_name": "Anonymous Delegate"},
    )
    assert mismatch.status_code == 422
    assert mismatch.json()["detail"]["settings_path"] == (
        f"/settings?displayNameOrg={org.slug}#display-names"
    )
    # Clearing would reveal the nonmatching global fallback, so it is blocked.
    user.display_name = "Anonymous Default"
    db.commit()
    reset = client.patch(
        f"/api/orgs/{org.slug}/me/display-name",
        headers=_headers(user), json={"display_name": None},
    )
    assert reset.status_code == 422


def test_direct_public_and_submit_routes_share_delegate_gate(client, db):
    user = make_user(db, "route-delegate", "Public Alias")
    strict = _org(db, "direct-public", settings={
        "verification_require_name_match": "full",
        "verification_name_match_scope": "public_delegates",
    })
    checkbox = _org(db, "submit-public", settings={
        "verification_required_for_public_delegate": True,
    })
    make_org_membership(db, org_id=strict.id, user_id=user.id)
    make_org_membership(db, org_id=checkbox.id, user_id=user.id)
    strict_topic = models.Topic(org_id=strict.id, name="Strict", color="#000")
    checkbox_topic = models.Topic(org_id=checkbox.id, name="Checkbox", color="#000")
    db.add_all([strict_topic, checkbox_topic])
    db.flush()
    db.add_all([
        models.DelegateProfile(
            user_id=user.id, org_id=strict.id, topic_id=strict_topic.id,
            visibility="followers_only",
        ),
        models.DelegateProfile(
            user_id=user.id, org_id=checkbox.id, topic_id=checkbox_topic.id,
            visibility="public",
        ),
    ])
    db.commit()
    direct = client.patch(
        f"/api/orgs/{strict.slug}/delegate-profile/topics/{strict_topic.id}",
        headers=_headers(user), json={"visibility": "public"},
    )
    assert direct.status_code == 403
    assert direct.json()["detail"]["scope"] == "delegate"
    strict_profile = db.query(models.DelegateProfile).filter_by(
        user_id=user.id, org_id=strict.id,
    ).one()
    db.refresh(strict_profile)
    assert strict_profile.visibility == "followers_only"
    submit = client.post(
        f"/api/orgs/{checkbox.slug}/delegate-profile/topics/{checkbox_topic.id}/submit-public-accepting",
        headers=_headers(user),
    )
    assert submit.status_code == 403
    assert submit.json()["detail"]["floor"] == "identity"
    checkbox_profile = db.query(models.DelegateProfile).filter_by(
        user_id=user.id, org_id=checkbox.id,
    ).one()
    db.refresh(checkbox_profile)
    assert checkbox_profile.visibility == "public"
    assert checkbox_profile.public_accepting_submitted_at is None


def test_admin_approval_rechecks_strict_continuous_compliance(client, db):
    admin = make_user(db, "approve-admin")
    applicant = _verified_user(db, "approve-applicant", "Alice Smith")
    org = _org(db, "approval-recheck", settings={
        "verification_require_name_match": "full",
        "verification_name_match_scope": "public_delegates",
    })
    make_org_membership(db, org_id=org.id, user_id=admin.id, role="admin")
    make_org_membership(db, org_id=org.id, user_id=applicant.id)
    topic = models.Topic(org_id=org.id, name="Approval", color="#000")
    db.add(topic)
    db.flush()
    profile = models.DelegateProfile(
        user_id=applicant.id, org_id=org.id, topic_id=topic.id,
        visibility="public", public_accepting_submitted_at=models._now(),
    )
    db.add(profile)
    db.flush()
    # Simulate verification/name drift after submit; approval must not bypass.
    applicant.display_name = "Anonymous"
    db.commit()
    response = client.post(
        f"/api/orgs/{org.slug}/delegate-applications/{profile.id}/approve",
        headers=_headers(admin),
    )
    assert response.status_code == 422
    db.refresh(profile)
    assert profile.visibility == "public"


def test_revert_to_public_rechecks_and_preserves_markers_on_failure(client, db):
    user = make_user(db, "revert-public", "Unverified Delegate")
    org = _org(db, "revert-public-org", settings={
        "verification_required_for_public_delegate": True,
    })
    make_org_membership(db, org_id=org.id, user_id=user.id)
    topic = models.Topic(org_id=org.id, name="Revert", color="#000")
    db.add(topic)
    db.flush()
    submitted_at = models._now()
    approved_at = models._now()
    profile = models.DelegateProfile(
        user_id=user.id,
        org_id=org.id,
        topic_id=topic.id,
        visibility="public_accepting",
        public_accepting_submitted_at=submitted_at,
        public_accepting_approved_at=approved_at,
        public_accepting_approved_by_id=user.id,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    submitted_at = profile.public_accepting_submitted_at
    approved_at = profile.public_accepting_approved_at

    response = client.post(
        f"/api/orgs/{org.slug}/delegate-profile/topics/{topic.id}/revert-to-public",
        headers=_headers(user),
    )
    assert response.status_code == 403
    assert response.json()["detail"]["floor"] == "identity"
    db.refresh(profile)
    assert profile.visibility == "public_accepting"
    assert profile.public_accepting_submitted_at == submitted_at
    assert profile.public_accepting_approved_at == approved_at
    assert profile.public_accepting_approved_by_id == user.id


def test_delegate_gate_composes_stronger_floor_residency_and_duplicate_flags(db):
    org = _org(db, "delegate-composition", settings={
        "verification_required_for_public_delegate": True,
        "verification_membership_floor": "address_on_id",
        "verification_membership_require_residency": True,
        "verification_residency_scope": [{"state": "MA"}],
    })
    user = _verified_user(db, "composed", "Alice Smith")
    user.verification_state = "address_on_id"
    user.verification_jurisdiction = "NH"
    with pytest.raises(HTTPException):
        verification.enforce_public_delegate_eligibility(db, user, org)
    user.verification_jurisdiction = "MA"
    other = make_user(db, "duplicate-other")
    db.flush()
    db.add(models.OrgDuplicateFlag(
        org_id=org.id, user_a_id=min(user.id, other.id),
        user_b_id=max(user.id, other.id), confidence="name_dob", status="open",
    ))
    db.flush()
    with pytest.raises(HTTPException):
        verification.enforce_public_delegate_eligibility(db, user, org)


def test_absent_name_scope_keeps_legacy_all_member_block_and_flag(client, db):
    user = _verified_user(db, "legacy-name", "Alice Smith")
    org = _org(db, "legacy-scope", settings={
        "verification_require_name_match": "full",
        "verification_name_match_action": "block",
    })
    make_org_membership(db, org_id=org.id, user_id=user.id)
    db.commit()
    assert verification.get_org_name_match_scope(org) == "all_verified_members"
    blocked = client.patch(
        f"/api/orgs/{org.slug}/me/display-name",
        headers=_headers(user), json={"display_name": "Anonymous"},
    )
    assert blocked.status_code == 422
    org.settings = {**org.settings, "verification_name_match_action": "flag"}
    db.commit()
    allowed = client.patch(
        f"/api/orgs/{org.slug}/me/display-name",
        headers=_headers(user), json={"display_name": "Anonymous"},
    )
    assert allowed.status_code == 200
    assert db.query(models.AuditLog).filter_by(action="org.display_name_mismatch").count() == 1


def test_list_orgs_surfaces_only_callers_name_state_and_public_route_omits_it(client, db):
    user = make_user(db, "list-name", "Default")
    first = _org(db, "list-first")
    second = _org(db, "list-second")
    first_m = make_org_membership(db, org_id=first.id, user_id=user.id)
    make_org_membership(db, org_id=second.id, user_id=user.id)
    first_m.display_name = "First Override"
    db.commit()
    rows = client.get("/api/orgs", headers=_headers(user))
    assert rows.status_code == 200
    by_slug = {row["slug"]: row for row in rows.json()}
    assert by_slug[first.slug]["my_display_name"] == "First Override"
    assert by_slug[first.slug]["my_display_name_override"] == "First Override"
    assert by_slug[second.slug]["my_display_name"] == "Default"
    public = client.get(f"/api/orgs/{first.slug}/public").json()
    assert "my_display_name" not in public
    assert "my_display_name_override" not in public


def test_global_name_edit_ignores_overrides_and_blocks_only_affected_orgs(client, db):
    user = _verified_user(db, "global-name")
    blocking = _org(db, "blocking-org", settings={
        "verification_require_name_match": "full",
        "verification_name_match_scope": "public_delegates",
    })
    overridden = _org(db, "override-org", settings={
        "verification_require_name_match": "full",
        "verification_name_match_scope": "public_delegates",
    })
    m1 = make_org_membership(db, org_id=blocking.id, user_id=user.id)
    m2 = make_org_membership(db, org_id=overridden.id, user_id=user.id)
    m2.display_name = "Alice Smith"
    for org in (blocking, overridden):
        topic = models.Topic(org_id=org.id, name=f"Topic {org.slug}", color="#000")
        db.add(topic)
        db.flush()
        db.add(models.DelegateProfile(
            user_id=user.id, topic_id=topic.id, org_id=org.id, visibility="public",
        ))
    db.commit()
    response = client.patch(
        "/api/auth/me", headers=_headers(user), json={"display_name": "Anonymous"},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["total"] == 1
    assert detail["affected_orgs"][0]["org_slug"] == blocking.slug
    db.refresh(user)
    assert user.display_name == "Alice Smith"


def test_public_delegate_activation_preflight_is_bounded_and_private_names_safe(client, db):
    steward = make_user(db, "policy-steward")
    org = _org(db, "activation")
    make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
    for index in range(25):
        user = make_user(db, f"unverified-{index}", f"Public {index}")
        make_org_membership(db, org_id=org.id, user_id=user.id)
        topic = models.Topic(org_id=org.id, name=f"T{index}", color="#000")
        db.add(topic)
        db.flush()
        db.add(models.DelegateProfile(
            user_id=user.id, topic_id=topic.id, org_id=org.id, visibility="public",
        ))
    db.commit()
    response = client.patch(
        f"/api/orgs/{org.slug}",
        headers=_headers(steward),
        json={"settings": {
            "verification_require_name_match": "full",
            "verification_name_match_scope": "public_delegates",
        }},
    )
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["total"] == 25
    assert len(detail["items"]) == 20
    assert set(detail["items"][0]) == {"user_id", "display_name", "reason_code"}
    assert "legal" not in response.text.lower()


def test_global_name_preflight_query_count_is_constant_for_many_memberships(client, db):
    user = _verified_user(db, "query-budget")
    for index in range(30):
        org = _org(db, f"query-{index}", settings={
            "verification_require_name_match": "full",
            "verification_name_match_scope": "public_delegates",
        })
        make_org_membership(db, org_id=org.id, user_id=user.id)
        topic = models.Topic(org_id=org.id, name=f"Q{index}", color="#000")
        db.add(topic)
        db.flush()
        db.add(models.DelegateProfile(
            user_id=user.id, topic_id=topic.id, org_id=org.id, visibility="public",
        ))
    db.commit()
    count = 0

    def before_cursor(*_args):
        nonlocal count
        count += 1

    connection = db.connection()
    event.listen(connection, "before_cursor_execute", before_cursor)
    try:
        response = client.patch(
            "/api/auth/me", headers=_headers(user), json={"display_name": "Alice Q Smith"},
        )
    finally:
        event.remove(connection, "before_cursor_execute", before_cursor)
    assert response.status_code == 200, response.text
    assert count <= 10


def test_delegate_checkbox_always_requires_identity_and_residency(db):
    org = _org(db, "delegate-floor", settings={
        "verification_required_for_public_delegate": True,
        "verification_membership_floor": "email_only",
    })
    user = make_user(db, "email-only")
    with pytest.raises(HTTPException) as exc:
        verification.enforce_public_delegate_eligibility(db, user, org)
    assert exc.value.detail["scope"] == "delegate"
    assert exc.value.detail["floor"] == "identity"


def test_public_delegate_failure_payload_never_contains_private_identity_data(db):
    org = _org(db, "privacy", settings={
        "verification_require_name_match": "full",
        "verification_name_match_scope": "public_delegates",
    })
    user = make_user(db, "privacy-user", "Public Alias")
    user.legal_first_name = "Secret"
    user.legal_last_name = "Identity"
    user.verification_state = "identity"
    user.verification_provenance = verification.PROV_DIDIT
    with pytest.raises(HTTPException) as exc:
        verification.enforce_public_delegate_eligibility(db, user, org)
    payload = str(exc.value.detail)
    assert "Secret" not in payload
    assert "Identity" not in payload
    assert exc.value.detail["error"] == "name_match_required"


def test_branding_models_include_header_field():
    assert schemas.BrandingOut().header_text_color is None
    assert schemas.OrgPublicBrandingOut().model_dump()["header_text_color"] is None


def test_direct_seed_path_stamps_explicit_nonresident_metadata(db):
    from seed_data import _get_or_create_proposal
    user = make_user(db, "seed-author")
    topic = models.Topic(name="Seed topic", color="#000")
    db.add(topic)
    db.flush()
    proposal = _get_or_create_proposal(
        db,
        title="Phase 105 direct seed",
        body="Body",
        author_id=user.id,
        status="draft",
        topic_relevances=[(topic, 1.0)],
    )
    assert proposal.verification_require_residency is False
