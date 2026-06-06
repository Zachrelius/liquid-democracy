"""Phase 52h Stage 2 — platform-wide doc-number hard block removal.

Per the spec verification matrix:

  * Doc-block gone — two accounts with the SAME document in DIFFERENT
    orgs BOTH verify successfully, NO ``verification.duplicate_
    document`` audit, NO ``collision_rejected`` bookkeeping status.
  * Same-org name-hash match STILL flags (in-org dedup is unchanged).
  * ``doc_number_hash`` is no longer written on a new verification.
  * Mapper signature no longer accepts ``doc_number_unique``;
    ``IDENTITY_UNIQUE`` is no longer producible from the mapper
    (Z-locked Option A — uniqueness rung removed).
  * Index dropped (covered by the migration cycle test).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
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
def _env(monkeypatch):
    monkeypatch.setenv("DIDIT_WEBHOOK_SECRET", "test_secret_value")
    monkeypatch.setenv("VERIFICATION_HASH_PEPPER", "TEST_DUMMY_PEPPER_52H_S2")
    try:
        from routes.verification import limiter as _ver_limiter
        _ver_limiter.reset()
    except Exception:
        pass
    yield


def _sign(body: bytes) -> dict[str, str]:
    ts = int(time.time())
    mac = hmac.new(b"test_secret_value", body, hashlib.sha256).hexdigest()
    return {"X-Signature": mac, "X-Timestamp": str(ts)}


def _real_payload(session_id: str, *, doc_number: str = "X9876543") -> dict:
    return {
        "session_id": session_id,
        "webhook_type": "session.completed",
        "decision": {
            "session_id": session_id,
            "status": "Approved",
            "id_verifications": [{
                "status": "Approved",
                "document_number": doc_number,
                "first_name": "Alice",
                "last_name": "Robertson",
                "date_of_birth": "1985-03-14",
            }],
        },
    }


# ===========================================================================
# Doc-block GONE — two accounts, same document, different orgs → both pass
# ===========================================================================

class TestDocBlockRemoved:
    def _seed_session(
        self, db: Session, user: models.User, sid: str,
    ) -> models.VerificationSession:
        row = models.VerificationSession(
            user_id=user.id, provider_session_id=sid, status="initiated",
        )
        db.add(row); db.commit()
        return row

    def test_same_document_different_users_both_verify(
        self, client: TestClient, db: Session, monkeypatch,
    ):
        # Stub the purge so it doesn't matter.
        monkeypatch.setattr(verification_provider, "delete_session", lambda sid: True)

        alice = make_user(db, "alice")
        self._seed_session(db, alice, "sess_alice")
        body = json.dumps(_real_payload("sess_alice", doc_number="SHARED-DOC-AB-12345")).encode()
        r1 = client.post(
            "/api/webhooks/didit",
            content=body, headers={**_sign(body), "Content-Type": "application/json"},
        )
        assert r1.status_code == 200
        db.refresh(alice)
        assert alice.verification_state == verification.IDENTITY  # not IDENTITY_UNIQUE
        assert alice.verification_provenance == verification.PROV_DIDIT
        assert alice.doc_number_hash is None  # NEVER written

        # Bob — same doc number, different user. Pre-52h-Stage-2 this
        # would have been rejected with verification.duplicate_document.
        # Now it succeeds.
        bob = make_user(db, "bob")
        self._seed_session(db, bob, "sess_bob")
        body2 = json.dumps(_real_payload("sess_bob", doc_number="SHARED-DOC-AB-12345")).encode()
        r2 = client.post(
            "/api/webhooks/didit",
            content=body2, headers={**_sign(body2), "Content-Type": "application/json"},
        )
        assert r2.status_code == 200
        db.refresh(bob)
        assert bob.verification_state == verification.IDENTITY
        assert bob.verification_provenance == verification.PROV_DIDIT
        assert bob.doc_number_hash is None

        # NO duplicate_document audit row written for either user.
        dup_audits = db.query(models.AuditLog).filter_by(
            action="verification.duplicate_document",
        ).all()
        assert dup_audits == []

        # Both bookkeeping rows landed at an approved state, NOT
        # collision_rejected.
        sessions = db.query(models.VerificationSession).all()
        for s in sessions:
            assert s.status != "collision_rejected"

    def test_doc_number_hash_no_longer_written(
        self, client: TestClient, db: Session, monkeypatch,
    ):
        monkeypatch.setattr(verification_provider, "delete_session", lambda sid: True)
        alice = make_user(db, "alice")
        row = models.VerificationSession(
            user_id=alice.id, provider_session_id="sess_no_doc_hash",
            status="initiated",
        )
        db.add(row); db.commit()
        body = json.dumps(_real_payload("sess_no_doc_hash")).encode()
        client.post(
            "/api/webhooks/didit",
            content=body, headers={**_sign(body), "Content-Type": "application/json"},
        )
        db.refresh(alice)
        # Doc hash column stays NULL (the column is deprecated but
        # retained; it's just no longer written).
        assert alice.doc_number_hash is None
        # uniqueness_strength also no longer set (Z-locked Option A).
        assert alice.uniqueness_strength is None
        # Name hashes ARE written — in-org dedup still works.
        assert alice.name_dob_hash is not None


# ===========================================================================
# Same-org name-hash match — still flagged (in-org dedup unchanged)
# ===========================================================================

class TestSameOrgFlagStillRaised:
    def test_same_org_same_person_still_flagged_at_join(
        self, client: TestClient, db: Session, monkeypatch,
    ):
        # The doc-block removal must NOT remove in-org dedup. The
        # name-based flag still catches same-person-same-org.
        from role_seed import seed_default_roles_for_org
        from org_titles import seed_system_titles_for_org

        org = models.Organization(
            name="O", slug="o", description="",
            join_policy="open", governance_mode="single_steward",
            settings={
                "default_deliberation_days": 1, "default_voting_days": 7,
                "default_pass_threshold": 0.5, "default_quorum_threshold": 0,
                "allowed_voting_methods": ["binary"],
            },
        )
        db.add(org); db.flush()
        seed_default_roles_for_org(db, org.id)
        seed_system_titles_for_org(db, org.id)
        db.commit()

        incumbent = make_user(db, "incumbent")
        incumbent.name_dob_address_hash = "SAME_ORG_HASH"
        make_org_membership(db, user_id=incumbent.id, org_id=org.id, role="member")

        applicant = make_user(db, "applicant")
        applicant.name_dob_address_hash = "SAME_ORG_HASH"
        db.commit()

        import auth as auth_utils
        r = client.post(
            f"/api/orgs/{org.slug}/join-request",
            headers={"Authorization": f"Bearer {auth_utils.create_access_token(applicant.id)}"},
        )
        assert r.status_code == 200
        # Flag still raised.
        flags = db.query(models.OrgDuplicateFlag).filter_by(org_id=org.id).all()
        assert len(flags) == 1
        assert flags[0].confidence == "name_dob_address"


# ===========================================================================
# Mapper — doc_number_unique signature gone; IDENTITY_UNIQUE not producible
# ===========================================================================

class TestMapperUniquenessRungRemoved:
    def test_mapper_signature_drops_doc_number_unique(self):
        # The kwarg is gone — passing it would raise TypeError.
        import inspect
        sig = inspect.signature(verification_provider.map_decision_to_state)
        assert "doc_number_unique" not in sig.parameters

    def test_mapper_passed_id_no_address_returns_identity(self):
        m = verification_provider.map_decision_to_state(
            {"id_verifications": [{"status": "Approved"}]},
        )
        # Was IDENTITY_UNIQUE-eligible pre-Stage-2 when caller passed
        # doc_number_unique=True. Post-Stage-2, no IDENTITY_UNIQUE
        # path remains.
        assert m["verification_state"] == verification.IDENTITY

    def test_mapper_passed_id_with_jurisdiction_returns_address_on_id(self):
        m = verification_provider.map_decision_to_state(
            {"id_verifications": [{
                "status": "Approved",
                "parsed_address": {"region": "Massachusetts"},
            }]},
        )
        assert m["verification_state"] == verification.ADDRESS_ON_ID
        assert m["verification_jurisdiction"] == "MA"

    def test_identity_unique_not_in_mapper_output_states(self):
        # Even with every possible decision shape, IDENTITY_UNIQUE
        # never appears.
        for payload in [
            {},
            {"status": "Declined"},
            {"id_verifications": []},
            {"id_verifications": [{"status": "Approved"}]},
            {"id_verifications": [{
                "status": "Approved",
                "parsed_address": {"region": "California"},
            }]},
        ]:
            m = verification_provider.map_decision_to_state(payload)
            assert m["verification_state"] != verification.IDENTITY_UNIQUE


# ===========================================================================
# compute_hashes — doc_number_hash no longer produced
# ===========================================================================

class TestComputeHashesNoLongerProducesDocHash:
    def test_compute_hashes_doc_number_hash_always_none(self):
        import verification_hashing
        fields = {
            "document_number": "ANYTHING",
            "first_name": "Alice", "last_name": "R",
            "date_of_birth": "1985-03-14",
            "address": {
                "street": "1 Main St", "city": "C",
                "state": "CA", "zip": "94000",
            },
        }
        h = verification_hashing.compute_hashes(fields)
        # Key still present for back-compat callers reading it
        # explicitly; value is always None now.
        assert "doc_number_hash" in h
        assert h["doc_number_hash"] is None
        # Name hashes still computed.
        assert h["name_dob_hash"] is not None
        assert h["name_dob_address_hash"] is not None


# ===========================================================================
# No orphaned references — IntegrityError import removed from receiver
# ===========================================================================

class TestNoOrphanedReferences:
    def test_receiver_no_longer_imports_IntegrityError(self):
        import routes.verification as v
        # The import was a direct ``from sqlalchemy.exc import IntegrityError``
        # to catch the now-removed doc-hash race.
        src = open(v.__file__, "r", encoding="utf-8").read()
        assert "from sqlalchemy.exc import IntegrityError" not in src

    def test_no_duplicate_document_audit_action_in_route_source(self):
        import routes.verification as v
        src = open(v.__file__, "r", encoding="utf-8").read()
        # No code path should emit verification.duplicate_document
        # anymore (the audit action is gone with the doc-block).
        assert 'action="verification.duplicate_document"' not in src
