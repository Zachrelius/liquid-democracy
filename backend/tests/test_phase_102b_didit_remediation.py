from __future__ import annotations

import hashlib
import hmac
import json
import time
from argparse import Namespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
import verification
import verification_provider
from database import Base, get_db
from main import app
from role_seed import seed_default_roles_for_org
from scripts import audit_didit_verification_integrity as audit_script
from tests.conftest import make_org_membership, make_user


FEATURES = ["ID_VERIFICATION", "LIVENESS", "FACE_MATCH", "IP_ANALYSIS"]


def provider_payload(
    *,
    session_id="session-opaque-102b",
    status="Approved",
    decision_status="Approved",
    features=None,
    ids=None,
    liveness=None,
    faces=None,
):
    return {
        "session_id": session_id,
        "webhook_type": "status.updated",
        "status": status,
        "features": FEATURES if features is None else features,
        "decision": {
            "session_id": session_id,
            "status": decision_status,
            "id_verifications": [{
                "status": "Approved",
                "first_name": "Test",
                "last_name": "Person",
                "date_of_birth": "1980-01-01",
                "parsed_address": {"region": "Massachusetts", "country": "US"},
            }] if ids is None else ids,
            "liveness_checks": [{"status": "Approved"}] if liveness is None else liveness,
            "face_matches": [{"status": "Approved"}] if faces is None else faces,
        },
    }


def retrieval_payload(**kwargs):
    webhook = provider_payload(**kwargs)
    return {
        "session_id": webhook["session_id"],
        "status": webhook["status"],
        "features": webhook["features"],
        "id_verifications": webhook["decision"]["id_verifications"],
        "liveness_checks": webhook["decision"]["liveness_checks"],
        "face_matches": webhook["decision"]["face_matches"],
    }


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"status": "Abandoned", "decision_status": "Abandoned", "liveness": [], "faces": []}, "overall_not_approved"),
        ({"status": "Abandoned"}, "overall_not_approved"),
        ({"decision_status": "Abandoned"}, "decision_not_approved"),
        ({"decision_status": "In Review"}, "decision_not_approved"),
        ({"ids": []}, "missing_id_verifications"),
        ({"ids": [{"status": "Declined"}]}, "unapproved_id_verifications"),
        ({"liveness": []}, "missing_liveness_checks"),
        ({"liveness": [{"status": "In Progress"}]}, "unapproved_liveness_checks"),
        ({"faces": []}, "missing_face_matches"),
        ({"faces": [{"status": "Declined"}]}, "unapproved_face_matches"),
        ({"features": ["ID_VERIFICATION"]}, "missing_required_features"),
    ],
)
def test_strict_decision_matrix_fails_closed(kwargs, reason):
    result = verification_provider.classify_provider_decision(provider_payload(**kwargs))
    assert result.approved is False
    assert result.reason == reason


def test_strict_approved_maps_only_after_all_v3_features_pass():
    payload = provider_payload()
    result = verification_provider.classify_provider_decision(payload)
    assert result.approved is True
    assert set(verification_provider.EXPECTED_IDENTITY_FEATURES) == {
        "ID_VERIFICATION", "LIVENESS", "FACE_MATCH",
    }
    mapped = verification_provider.map_decision_to_state(payload, result)
    assert mapped["verification_state"] == verification.ADDRESS_ON_ID
    assert mapped["verification_jurisdiction"] == "MA"


def test_singular_v2_payload_never_promotes():
    payload = {
        "status": "Approved",
        "features": FEATURES,
        "decision": {
            "status": "Approved",
            "id_verification": {"status": "Approved"},
            "liveness_check": {"status": "Approved"},
            "face_match": {"status": "Approved"},
        },
    }
    assert not verification_provider.classify_provider_decision(payload).approved
    assert verification_provider.map_decision_to_state(payload)["verification_state"] == verification.EMAIL_ONLY


def test_flat_retrieval_shape_is_strict_without_becoming_a_webhook_bypass():
    flat = retrieval_payload()
    assert verification_provider.classify_provider_decision(flat).approved is False
    assert verification_provider.classify_retrieved_session_decision(flat).approved is True
    abandoned = retrieval_payload(status="Abandoned", decision_status="Abandoned", liveness=[], faces=[])
    result = verification_provider.classify_retrieved_session_decision(abandoned)
    assert result.approved is False
    assert result.normalized_status == "abandoned"


@pytest.fixture
def webhook_client(db, monkeypatch):
    monkeypatch.setenv("DIDIT_WEBHOOK_SECRET", "phase102b-secret")
    monkeypatch.setenv("VERIFICATION_HASH_PEPPER", "phase102b-pepper")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def signed(payload):
    body = json.dumps(payload).encode()
    ts = int(time.time())
    signature = hmac.new(b"phase102b-secret", body, hashlib.sha256).hexdigest()
    return body, {"X-Signature": signature, "X-Timestamp": str(ts), "Content-Type": "application/json"}


def seed_session(db, user, session_id="session-opaque-102b"):
    row = models.VerificationSession(
        user_id=user.id, provider_session_id=session_id, status="initiated",
    )
    db.add(row)
    db.commit()
    return row


def test_exact_abandoned_incident_preserves_last_known_good_and_has_no_approval_side_effects(
    db, webhook_client, monkeypatch,
):
    user = make_user(db, "known_good")
    user.verification_state = verification.ADDRESS_ON_ID
    user.verification_jurisdiction = "MA"
    user.verification_provenance = verification.PROV_DIDIT
    user.name_dob_hash = "existing-derived-hash"
    session = seed_session(db, user)
    purges = []
    monkeypatch.setattr(verification_provider, "delete_session", lambda sid: purges.append(sid))

    payload = provider_payload(status="Abandoned", decision_status="Abandoned", liveness=[], faces=[])
    body, headers = signed(payload)
    response = webhook_client.post("/api/webhooks/didit", content=body, headers=headers)
    assert response.status_code == 200
    db.refresh(user); db.refresh(session)
    assert user.verification_state == verification.ADDRESS_ON_ID
    assert user.verification_jurisdiction == "MA"
    assert user.name_dob_hash == "existing-derived-hash"
    assert session.status == "provider_abandoned"
    assert db.query(models.VerificationConsumption).count() == 0
    assert db.query(models.AuditLog).filter(models.AuditLog.action == "verification.completed").count() == 0
    outcome = db.query(models.AuditLog).filter(models.AuditLog.action == "verification.provider_outcome").one()
    assert "provider_session_id" not in (outcome.details or {})
    assert purges == []


def test_transient_then_approved_and_replay_processes_once(db, webhook_client, monkeypatch):
    user = make_user(db, "transition")
    session = seed_session(db, user, "session-transition")
    purges = []
    monkeypatch.setattr(verification_provider, "delete_session", lambda sid: purges.append(sid) or True)

    transient = provider_payload(session_id="session-transition", status="In Progress", decision_status="In Progress", liveness=[], faces=[])
    body, headers = signed(transient)
    first = webhook_client.post("/api/webhooks/didit", content=body, headers=headers)
    assert first.status_code == 200
    db.refresh(session)
    assert session.status == "provider_in_progress"

    approved = provider_payload(session_id="session-transition")
    body, headers = signed(approved)
    second = webhook_client.post("/api/webhooks/didit", content=body, headers=headers)
    replay = webhook_client.post("/api/webhooks/didit", content=body, headers=signed(approved)[1])
    assert second.status_code == 200
    assert replay.json().get("deduped") is True
    db.refresh(user); db.refresh(session)
    assert user.verification_state == verification.ADDRESS_ON_ID
    assert session.status == "approved_purged"
    assert db.query(models.VerificationConsumption).count() == 1
    assert db.query(models.AuditLog).filter(models.AuditLog.action == "verification.completed").count() == 1
    assert purges == ["session-transition"]


def test_merged_proposal_policy_validation_matrix():
    invalid_cases = [
        ({"verification_proposal_policy": "always"}, "verification_proposal_floor"),
        ({"verification_proposal_policy": "always", "verification_proposal_floor": "email_only"}, "verification_proposal_floor"),
        ({"verification_proposal_policy": "always", "verification_proposal_floor": "address_on_id"}, "verification_proposal_floor"),
        ({"verification_proposal_policy": "always", "verification_proposal_floor": "residency_verified", "verification_proposal_jurisdiction": "XX"}, "verification_proposal_floor"),
    ]
    for settings, expected_field in invalid_cases:
        _, errors = verification.validate_org_proposal_settings({}, settings)
        assert expected_field in errors
    merged, errors = verification.validate_org_proposal_settings({}, {
        "verification_proposal_policy": "always",
        "verification_proposal_floor": "identity",
        "verification_proposal_jurisdiction": "MA",
    })
    assert errors == {}
    assert merged["verification_proposal_jurisdiction"] is None


def test_canonical_patch_preserves_untouched_legacy_invalid_row(db):
    user = make_user(db, "settings_steward")
    org = models.Organization(
        name="Invalid Legacy", slug="invalid-legacy", description="",
        settings={"verification_proposal_policy": "always", "verification_proposal_floor": "email_only"},
    )
    db.add(org); db.flush(); seed_default_roles_for_org(db, org.id)
    make_org_membership(db, org_id=org.id, user_id=user.id, role="steward")
    db.commit()

    def override_db():
        yield db
    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        response = client.patch(
            f"/api/orgs/{org.slug}",
            json={"settings": {"topic_categories_enabled": True}},
            headers={"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"},
        )
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert response.status_code == 200
    db.refresh(org)
    assert org.settings["topic_categories_enabled"] is True
    assert org.settings["verification_proposal_floor"] == "email_only"


def test_audit_classifier_categories_are_deterministic():
    approved = verification_provider.classify_provider_decision(provider_payload())
    abandoned = verification_provider.classify_provider_decision(provider_payload(status="Abandoned", decision_status="Abandoned", liveness=[], faces=[]))
    transient = verification_provider.classify_provider_decision(provider_payload(status="In Review", decision_status="In Review", liveness=[], faces=[]))
    base = dict(
        provenance=verification.PROV_DIDIT,
        verification_state=verification.ADDRESS_ON_ID,
        session_status="approved_purge_failed",
        has_completion_audit=True,
        has_consumption=True,
    )
    assert audit_script.classify_record(provider_result=approved, **base) == "confirmed_valid"
    assert audit_script.classify_record(provider_result=abandoned, **base) == "confirmed_false_positive"
    assert audit_script.classify_record(provider_result=transient, **base) == "needs_review_history_mismatch"
    assert audit_script.classify_record(provider_result=approved, **{**base, "has_consumption": False}) == "needs_review_history_mismatch"
    assert audit_script.classify_record(provider_result=approved, **{**base, "provenance": verification.PROV_DEMO_STUB}) == "not_applicable"


def test_guarded_remediation_clears_derivatives_suspends_gate_and_is_idempotent(monkeypatch, capsys):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine)
    monkeypatch.setattr(audit_script, "SessionLocal", Factory)
    incident = retrieval_payload(status="Abandoned", decision_status="Abandoned", liveness=[], faces=[])
    monkeypatch.setattr(verification_provider, "retrieve_session_decision", lambda sid: incident)
    with Factory() as db:
        user = make_user(db, "incident_user")
        user.verification_state = verification.ADDRESS_ON_ID
        user.verification_jurisdiction = "MA"
        user.verification_country = "US"
        user.verification_provenance = verification.PROV_DIDIT
        user.legal_full_name = "Sensitive Name"
        user.name_dob_hash = "derived"
        org = models.Organization(
            name="Gated", slug="gated", description="",
            settings={"verification_membership_floor": "address_on_id", "verification_membership_jurisdiction": "MA"},
        )
        db.add(org); db.flush(); seed_default_roles_for_org(db, org.id)
        membership = make_org_membership(db, org_id=org.id, user_id=user.id, role="member")
        session = models.VerificationSession(
            user_id=user.id, provider_session_id="incident-provider-session",
            status="approved_purge_failed",
        )
        db.add(session)
        db.add(models.VerificationConsumption(
            year_month="2026-08", user_id=user.id,
            provider_session_id="incident-provider-session", provenance="didit",
        ))
        db.add(models.AuditLog(
            actor_id=user.id, action="verification.completed", target_type="user",
            target_id=user.id, details={"historical": True},
        ))
        db.commit()
        user_id, membership_id = user.id, membership.id

    args = Namespace(
        user_id=user_id,
        provider_session_id="incident-provider-session",
        expected_verification_state="address_on_id",
        expected_provenance="didit",
        expected_session_status="approved_purge_failed",
        expected_provider_status="abandoned",
        confirm_remediation=True,
    )
    assert audit_script.audit_exact(args) == 0
    first_output = capsys.readouterr().out
    assert "memberships_to_suspend=1" in first_output
    for forbidden in (
        "Sensitive Name", "incident_user", "incident-provider-session",
        "derived",
    ):
        assert forbidden not in first_output
    with Factory() as db:
        user = db.get(models.User, user_id)
        membership = db.get(models.OrgMembership, membership_id)
        assert user.verification_state == verification.EMAIL_ONLY
        assert user.verification_provenance == verification.PROV_NONE
        for field in audit_script.DERIVED_USER_FIELDS:
            assert getattr(user, field) is None
        assert user.verification_updated_at is not None
        assert membership.status == "suspended"
        assert db.query(models.VerificationConsumption).count() == 1
        correction_count = db.query(models.AuditLog).filter(
            models.AuditLog.action == "verification.remediated_false_positive",
        ).count()
        assert correction_count == 1
    assert audit_script.audit_exact(args) == 0
    assert "already_remediated" in capsys.readouterr().out
    with Factory() as db:
        assert db.query(models.AuditLog).filter(
            models.AuditLog.action == "verification.remediated_false_positive",
        ).count() == 1
    Base.metadata.drop_all(engine)
