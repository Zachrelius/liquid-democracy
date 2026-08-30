"""Phase 52a — Didit integration tests.

Covers (per the spec verification matrix):

  * C-PROVIDER §3 — ``map_decision_to_state`` pure mapper across
    every decision shape we know how to interpret. The provider-swap
    seam; exhaustive table here keeps a provider rewrite reviewable.
  * C-PROVIDER §2 — webhook signature + freshness:
      - missing secret → False;
      - bad signature → False;
      - stale timestamp → False;
      - good triple → True.
  * C-WEBHOOK — receiver behavior:
      - bad signature → 401;
      - replay (same session_id + webhook_type) → deduped 200;
      - approved decision writes the record + audit;
      - declined decision leaves the user state untouched.
  * C-NULLIFIER — collision side-effect:
      - second user with the same nullifier is left unchanged;
      - audit row ``verification.nullifier_collision`` is written.
  * C-DEMO — ``demo_stub`` writable only on demo-only accounts:
      - ``ensure_demo_stub_writable`` raises 422 when a real-org
        membership exists;
      - passes on demo-only;
      - ``ensure_can_join_real_org`` blocks a demo_stub user from
        joining a non-demo org.
  * C-JURIS — ``normalize_jurisdiction`` accepts US two-letter
    codes, rejects everything else.
  * Serializer guard — the nullifier and attestation id are not
    exposed by ``UserOut`` (the cross-org correlation handle rule
    from Phase 51, re-asserted now that real nullifiers exist).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

import models
import verification
import verification_provider
from main import app
from database import Base, get_db
from tests.conftest import make_user, make_org_membership


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db() -> Iterator[Session]:
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


@pytest.fixture()
def client(db: Session) -> Iterator[TestClient]:
    def _override():
        try:
            yield db
        finally:
            pass
    app.dependency_overrides[get_db] = _override
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def _webhook_secret(monkeypatch):
    """Default test env: webhook secret is configured. Individual
    tests that need the "no secret" posture remove it via
    ``monkeypatch.delenv``.

    Phase 52d additionally requires VERIFICATION_HASH_PEPPER so
    ``_apply_decision`` can compute hashes — fail-closed without it.
    """
    monkeypatch.setenv("DIDIT_WEBHOOK_SECRET", "test_secret_value")
    monkeypatch.setenv("VERIFICATION_HASH_PEPPER", "TEST_DUMMY_PEPPER_PHASE_52A")
    yield


def _sign(body: bytes, secret: str = "test_secret_value", ts: int | None = None) -> dict[str, str]:
    if ts is None:
        ts = int(time.time())
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return {"X-Signature": mac, "X-Timestamp": str(ts)}


def _make_org(db: Session, slug: str, *, is_demo: bool = False) -> models.Organization:
    settings = {
        "default_deliberation_days": 1,
        "default_voting_days": 7,
        "default_pass_threshold": 0.5,
        "default_quorum_threshold": 0.0,
        "allowed_voting_methods": ["binary"],
    }
    org = models.Organization(
        name=slug.title(), slug=slug,
        description="", join_policy="open",
        governance_mode="single_steward",
        is_demo=is_demo,
        settings=settings,
    )
    db.add(org); db.flush()
    from role_seed import seed_default_roles_for_org
    from org_titles import seed_system_titles_for_org
    seed_default_roles_for_org(db, org.id)
    seed_system_titles_for_org(db, org.id)
    db.commit()
    return org


# ===========================================================================
# C-PROVIDER §3 — pure decision → state mapper
# ===========================================================================

class TestMapDecisionToState:
    """Phase 52d swapped the dedup SOURCE from Didit's 1:N face search
    to our-side document-hash dedup. The mapper no longer reads any
    ``face_search`` block; uniqueness is supplied by the webhook
    handler via ``doc_number_unique=`` after a hash lookup. These
    tests cover what the mapper still owns: address → jurisdiction
    extraction + the ordinal state ladder. The richer precedence /
    dead-code tests live in ``test_phase_52d_hash_dedup.py``."""

    def test_unrecognized_payload_returns_email_only(self):
        result = verification_provider.map_decision_to_state({})
        assert result["verification_state"] == verification.EMAIL_ONLY
        assert result["verification_jurisdiction"] is None
        assert result["verification_attestation_id"] is None

    def test_declined_decision_returns_email_only(self):
        result = verification_provider.map_decision_to_state({
            "status": "Declined",
            "id_verification": {"status": "Declined"},
        })
        assert result["verification_state"] == verification.EMAIL_ONLY

    def test_singular_v2_approved_with_address_fails_closed(self):
        result = verification_provider.map_decision_to_state({
            "session_id": "sess_addr",
            "id_verification": {
                "status": "Approved",
                "address_state": "CA",
            },
        })
        assert result["verification_state"] == verification.EMAIL_ONLY
        assert result["verification_jurisdiction"] is None

    def test_singular_v2_nested_address_fails_closed(self):
        result = verification_provider.map_decision_to_state({
            "id_verification": {
                "status": "Approved",
                "address": {"state": "ny", "country": "US"},
            },
        })
        assert result["verification_state"] == verification.EMAIL_ONLY
        assert result["verification_jurisdiction"] is None

    def test_unrecognized_jurisdiction_does_not_escalate(self):
        # Non-US-state addresses come back as None jurisdiction; the
        # state must NOT escalate to address_on_id (a jurisdiction-
        # less address_on_id record could never satisfy a gate). Without
        # doc_number_unique=True, state stays at IDENTITY.
        result = verification_provider.map_decision_to_state({
            "status": "Approved",
            "features": ["ID_VERIFICATION", "LIVENESS", "FACE_MATCH"],
            "decision": {
                "status": "Approved",
                "id_verifications": [{
                    "status": "Approved",
                    "parsed_address": {"region": "Ontario"},
                }],
                "liveness_checks": [{"status": "Approved"}],
                "face_matches": [{"status": "Approved"}],
            },
        })
        assert result["verification_state"] == verification.IDENTITY
        assert result["verification_jurisdiction"] is None

    def test_overall_approved_alone_fails_closed(self):
        result = verification_provider.map_decision_to_state({
            "session_id": "sess_overall",
            "status": "Approved",
        })
        assert result["verification_state"] == verification.EMAIL_ONLY


# ===========================================================================
# C-JURIS — jurisdiction normalization
# ===========================================================================

class TestJurisdictionNormalization:
    def test_two_letter_state_uppercased(self):
        assert verification_provider.normalize_jurisdiction("ca") == "CA"

    def test_full_state_name_accepted_and_normalized(self):
        # Phase 52e E1 — the captured-payload manifest revealed Didit
        # emits full state names (e.g. "Massachusetts") under
        # ``parsed_address.region``, so ``normalize_jurisdiction`` was
        # extended to accept both 2-letter codes and full names and
        # normalize to 2-letter. An org admin's "CA" floor IS now
        # satisfied by a "California" claim via this normalization.
        # The admin UI still presents the 2-letter-code picker so
        # admin input stays canonical.
        assert verification_provider.normalize_jurisdiction("California") == "CA"

    def test_country_code_rejected(self):
        assert verification_provider.normalize_jurisdiction("US") is None

    def test_dc_accepted(self):
        # DC is a real address-region for civic orgs.
        assert verification_provider.normalize_jurisdiction("dc") == "DC"

    def test_empty_and_none(self):
        assert verification_provider.normalize_jurisdiction("") is None
        assert verification_provider.normalize_jurisdiction(None) is None
        assert verification_provider.normalize_jurisdiction("   ") is None


# ===========================================================================
# C-PROVIDER §2 — webhook signature verification
# ===========================================================================

class TestVerifyWebhook:
    def test_missing_secret_returns_false(self, monkeypatch):
        monkeypatch.delenv("DIDIT_WEBHOOK_SECRET", raising=False)
        assert verification_provider.verify_webhook(b"{}", "deadbeef", "1234") is False

    def test_missing_signature_returns_false(self):
        assert verification_provider.verify_webhook(b"{}", None, "1234") is False

    def test_missing_timestamp_returns_false(self):
        assert verification_provider.verify_webhook(b"{}", "abc", None) is False

    def test_stale_timestamp_returns_false(self):
        body = b'{"x":1}'
        ts = int(time.time()) - 1000  # ≫ 300s
        mac = hmac.new(b"test_secret_value", body, hashlib.sha256).hexdigest()
        assert verification_provider.verify_webhook(body, mac, str(ts)) is False

    def test_wrong_signature_returns_false(self):
        body = b'{"x":1}'
        ts = int(time.time())
        assert verification_provider.verify_webhook(
            body, "0" * 64, str(ts),
        ) is False

    def test_valid_signature_returns_true(self):
        body = b'{"x":1}'
        ts = int(time.time())
        mac = hmac.new(b"test_secret_value", body, hashlib.sha256).hexdigest()
        assert verification_provider.verify_webhook(body, mac, str(ts)) is True

    def test_uppercase_signature_accepted(self):
        body = b'{"x":1}'
        ts = int(time.time())
        mac = hmac.new(b"test_secret_value", body, hashlib.sha256).hexdigest()
        assert verification_provider.verify_webhook(body, mac.upper(), str(ts)) is True


# ===========================================================================
# C-WEBHOOK — receiver
# ===========================================================================

class TestWebhookReceiver:
    def _seed_session(self, db: Session, user: models.User, session_id: str) -> models.VerificationSession:
        row = models.VerificationSession(
            user_id=user.id,
            provider_session_id=session_id,
            status="initiated",
        )
        db.add(row); db.commit()
        return row

    def test_bad_signature_returns_401(self, client: TestClient, db: Session):
        body = json.dumps({"session_id": "sess_x"}).encode("utf-8")
        r = client.post(
            "/api/webhooks/didit",
            content=body,
            headers={
                "X-Signature": "wrongsig",
                "X-Timestamp": str(int(time.time())),
                "Content-Type": "application/json",
            },
        )
        assert r.status_code == 401

    def test_approved_decision_writes_record(self, client: TestClient, db: Session):
        # Phase 52d — the dedup SOURCE is now our-side document-hash,
        # not Didit's 1:N face search. The mapper no longer reads a
        # face_search block; uniqueness comes from doc_number_hash
        # not colliding. The richer doc-hash + state-write tests live
        # in test_phase_52d_hash_dedup.py.
        user = make_user(db, "alice")
        self._seed_session(db, user, "sess_approve")
        payload = {
            "session_id": "sess_approve",
            "webhook_type": "session.completed",
            "status": "Approved",
            "features": ["ID_VERIFICATION", "LIVENESS", "FACE_MATCH"],
            "decision": {
                "session_id": "sess_approve",
                "status": "Approved",
                "id_verifications": [{
                    "status": "Approved",
                    "parsed_address": {"region": "CA", "country": "US"},
                }],
                "liveness_checks": [{"status": "Approved"}],
                "face_matches": [{"status": "Approved"}],
            },
        }
        body = json.dumps(payload).encode("utf-8")
        r = client.post(
            "/api/webhooks/didit",
            content=body,
            headers={**_sign(body), "Content-Type": "application/json"},
        )
        assert r.status_code == 200
        db.refresh(user)
        assert user.verification_state == verification.ADDRESS_ON_ID
        assert user.verification_jurisdiction == "CA"
        assert user.verification_provenance == verification.PROV_DIDIT
        assert user.verification_attestation_id == "sess_approve"

    def test_declined_decision_leaves_state_untouched(self, client: TestClient, db: Session):
        user = make_user(db, "bob")
        original_state = user.verification_state
        self._seed_session(db, user, "sess_decline")
        payload = {
            "session_id": "sess_decline",
            "webhook_type": "session.completed",
            "decision": {"status": "Declined"},
        }
        body = json.dumps(payload).encode("utf-8")
        r = client.post(
            "/api/webhooks/didit",
            content=body,
            headers={**_sign(body), "Content-Type": "application/json"},
        )
        assert r.status_code == 200
        db.refresh(user)
        assert user.verification_state == original_state
        assert user.verification_provenance != verification.PROV_DIDIT

    def test_replay_is_deduped(self, client: TestClient, db: Session):
        user = make_user(db, "carol")
        self._seed_session(db, user, "sess_replay")
        payload = {
            "session_id": "sess_replay",
            "webhook_type": "session.completed",
            "status": "Approved",
            "features": ["ID_VERIFICATION", "LIVENESS", "FACE_MATCH"],
            "decision": {
                "status": "Approved",
                "id_verifications": [{"status": "Approved"}],
                "liveness_checks": [{"status": "Approved"}],
                "face_matches": [{"status": "Approved"}],
            },
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {**_sign(body), "Content-Type": "application/json"}
        r1 = client.post("/api/webhooks/didit", content=body, headers=headers)
        assert r1.status_code == 200
        # Re-sign the SAME body fresh so timestamp is current; the
        # idempotency key is the normalized provider outcome, not the
        # signature or webhook type.
        headers2 = {**_sign(body), "Content-Type": "application/json"}
        r2 = client.post("/api/webhooks/didit", content=body, headers=headers2)
        assert r2.status_code == 200
        assert r2.json().get("deduped") is True

    def test_unknown_session_returns_200_noop(self, client: TestClient, db: Session):
        payload = {
            "session_id": "sess_never_seen",
            "webhook_type": "session.completed",
            "decision": {"id_verification": {"status": "Approved"}},
        }
        body = json.dumps(payload).encode("utf-8")
        r = client.post(
            "/api/webhooks/didit",
            content=body,
            headers={**_sign(body), "Content-Type": "application/json"},
        )
        assert r.status_code == 200
        assert r.json().get("ok") is False


# ===========================================================================
# C-NULLIFIER — collision handling
# ===========================================================================
#
# Phase 52d retired the Didit-1:N nullifier model in favor of our-side
# document-hash dedup. The collision behavior (and its side-effect
# tests — different-user blocked + same-user idempotent) now lives in
# ``test_phase_52d_hash_dedup.py::TestDocumentNumberHardBlock``. No
# Phase 52a-shape collision test remains here; the audit-action name
# changed (``verification.duplicate_document``) and the trigger field
# is ``doc_number_hash``, not ``verification_nullifier``.


# ===========================================================================
# C-DEMO — demo_stub tightening
# ===========================================================================

class TestDemoStubTightening:
    def test_ensure_demo_stub_writable_passes_on_demo_only_account(self, db: Session):
        demo_org = _make_org(db, "demo-acme", is_demo=True)
        user = make_user(db, "demo_user")
        make_org_membership(db, user_id=user.id, org_id=demo_org.id, role="member")
        # Should not raise.
        verification.ensure_demo_stub_writable(user, db)

    def test_ensure_demo_stub_writable_blocks_real_org_member(self, db: Session):
        real_org = _make_org(db, "real-acme", is_demo=False)
        user = make_user(db, "real_user")
        make_org_membership(db, user_id=user.id, org_id=real_org.id, role="member")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            verification.ensure_demo_stub_writable(user, db)
        assert exc.value.status_code == 422

    def test_ensure_can_join_real_org_blocks_demo_stub_user(self, db: Session):
        real_org = _make_org(db, "real-coop", is_demo=False)
        user = make_user(db, "demo_persona")
        user.verification_provenance = verification.PROV_DEMO_STUB
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            verification.ensure_can_join_real_org(user, real_org)
        assert exc.value.status_code == 422

    def test_ensure_can_join_real_org_allows_demo_stub_into_demo_org(self, db: Session):
        demo_org = _make_org(db, "demo-other", is_demo=True)
        user = make_user(db, "demo_persona2")
        user.verification_provenance = verification.PROV_DEMO_STUB
        # Should not raise.
        verification.ensure_can_join_real_org(user, demo_org)

    def test_ensure_can_join_real_org_allows_real_user(self, db: Session):
        real_org = _make_org(db, "real-coop-2", is_demo=False)
        user = make_user(db, "real_user_2")
        user.verification_provenance = verification.PROV_DIDIT
        # Should not raise.
        verification.ensure_can_join_real_org(user, real_org)


# ===========================================================================
# Serializer guard — nullifier + attestation NOT exposed
# ===========================================================================

class TestSerializerGuard:
    def test_nullifier_and_attestation_not_on_userout(self):
        import schemas
        fields = set(schemas.UserOut.model_fields.keys())
        # The cross-org correlation handle must never leak.
        assert "verification_nullifier" not in fields
        assert "verification_attestation_id" not in fields
