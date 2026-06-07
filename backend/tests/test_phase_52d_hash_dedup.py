"""Phase 52d — hash-dedup infrastructure tests.

Layered per the spec verification matrix:

  * D1 — key_path_manifest is keys-only by construction (gating
    safety test).
  * D2 — compute_hashes purity, normalization, pepper fail-closed.
  * D6 — map_decision_to_state precedence fix + dead-code removal.
  * D5 — document-number hard block: different-user collision +
    same-user idempotency (the critical correctness property).
  * D4 — session purge wired in, fail-safe (purge failure doesn't
    erase the verification).
  * demo_stub sealed (no real hashes / no session / no purge).
  * Serializer: the three hashes never appear on UserOut.
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
import verification_hashing
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
    monkeypatch.setenv("DIDIT_WEBHOOK_SECRET", "test_secret_value")
    yield


@pytest.fixture(autouse=True)
def _hash_pepper(monkeypatch):
    # DUMMY pepper for tests. The real pepper is a Z-action sealed
    # Railway variable — the team never sees it. compute_hashes is
    # pepper-agnostic; "same input + same pepper → same hash" is the
    # only contract.
    monkeypatch.setenv("VERIFICATION_HASH_PEPPER", "TEST_DUMMY_PEPPER_DO_NOT_USE_IN_PROD")
    yield


def _sign(body: bytes) -> dict[str, str]:
    ts = int(time.time())
    mac = hmac.new(b"test_secret_value", body, hashlib.sha256).hexdigest()
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
# D1 — key_path_manifest (keys-only, PII-safe by construction)
# ===========================================================================

class TestKeyPathManifest:
    PII_VALUES = [
        "Alice Quincy Robertson", "Alice", "Robertson",
        "1234 Elm Street, Apt 7B", "Springfield", "94114",
        "AB1234567CD", "DL-987654321", "1985-03-14",
        "alice.robertson@example.com", "+1-415-555-0199",
    ]

    def test_no_pii_value_appears_in_manifest(self):
        payload = {
            "session_id": "61ea6065-5cd2-45a8-8f18-8d87fa9e8f9e",
            "decision": {
                "id_verification": {
                    "status": "Approved",
                    "first_name": "Alice",
                    "last_name": "Robertson",
                    "document_number": "AB1234567CD",
                    "date_of_birth": "1985-03-14",
                    "address": {"street": "1234 Elm Street, Apt 7B",
                                "city": "Springfield", "state": "CA",
                                "zip": "94114"},
                    "email": "alice.robertson@example.com",
                    "phone": "+1-415-555-0199",
                },
                "face_match": {"status": "Approved", "score": 0.97},
            },
        }
        manifest = verification_provider.key_path_manifest(payload)
        dumped = json.dumps(manifest)
        for pii in self.PII_VALUES:
            assert pii not in dumped, (
                f"PII string {pii!r} leaked into manifest. Dumped:\n{dumped}"
            )

    def test_manifest_emits_key_paths(self):
        manifest = verification_provider.key_path_manifest({
            "decision": {"id_verification": {"first_name": "Alice"}},
        })
        assert "decision" in manifest
        assert "decision.id_verification" in manifest
        assert "decision.id_verification.first_name" in manifest

    def test_manifest_emits_only_type_labels(self):
        manifest = verification_provider.key_path_manifest({
            "n": 42, "f": 0.5, "s": "Alice", "b": True, "x": None,
            "arr": ["Bob"],
            "obj": {"k": "v"},
        })
        # Output keys are strings; values are type-label strings only.
        type_labels = {"dict", "list", "str", "int", "float", "bool", "null"}
        for v in manifest.values():
            assert v.startswith("<") or v in type_labels, f"unexpected type {v!r}"


# ===========================================================================
# D2 — compute_hashes (purity, normalization, fail-closed)
# ===========================================================================

class TestComputeHashes:
    def _full_fields(self):
        return {
            "document_number": "X9876543",
            "first_name": "Alice",
            "last_name": "Robertson",
            "date_of_birth": "1985-03-14",
            "address": {"street": "1234 Elm Street",
                        "city": "Springfield",
                        "state": "CA",
                        "zip": "94114"},
        }

    def test_same_input_same_hash(self):
        a = verification_hashing.compute_hashes(self._full_fields())
        b = verification_hashing.compute_hashes(self._full_fields())
        assert a == b

    def test_two_name_hashes_present(self):
        # Phase 52h Stage 2 — doc_number_hash is no longer produced
        # (platform-wide doc-number hard block removed). The two
        # name-based hashes are what drive the org-scoped flag
        # system; ``doc_number_hash`` is always None in the output.
        h = verification_hashing.compute_hashes(self._full_fields())
        assert h["doc_number_hash"] is None
        assert h["name_dob_hash"]
        assert h["name_dob_address_hash"]
        assert h["name_dob_hash"] != h["name_dob_address_hash"]

    def test_missing_doc_number_yields_none_for_doc_hash(self):
        # Doc-number presence no longer matters — the hash is always
        # None regardless.
        f = self._full_fields()
        f.pop("document_number")
        h = verification_hashing.compute_hashes(f)
        assert h["doc_number_hash"] is None
        assert h["name_dob_hash"]
        assert h["name_dob_address_hash"]

    def test_missing_address_yields_none_for_address_hash(self):
        f = self._full_fields()
        f.pop("address")
        h = verification_hashing.compute_hashes(f)
        assert h["name_dob_address_hash"] is None
        assert h["name_dob_hash"]

    def test_missing_dob_drops_name_hashes(self):
        # Phase 52h Stage 2 — only name hashes are produced now;
        # doc_number_hash is always None whether DOB is present or not.
        f = self._full_fields()
        f.pop("date_of_birth")
        h = verification_hashing.compute_hashes(f)
        assert h["name_dob_hash"] is None
        assert h["name_dob_address_hash"] is None
        assert h["doc_number_hash"] is None

    def test_normalization_case_insensitive(self):
        f1 = self._full_fields()
        f2 = self._full_fields()
        f2["first_name"] = "ALICE"
        f2["last_name"] = "robertson"
        h1 = verification_hashing.compute_hashes(f1)
        h2 = verification_hashing.compute_hashes(f2)
        assert h1["name_dob_hash"] == h2["name_dob_hash"]

    def test_normalization_strips_punctuation(self):
        f1 = self._full_fields()
        f2 = self._full_fields()
        f2["first_name"] = "Al-ice."
        f2["last_name"] = "Robert,son"
        h1 = verification_hashing.compute_hashes(f1)
        h2 = verification_hashing.compute_hashes(f2)
        assert h1["name_dob_hash"] == h2["name_dob_hash"]

    def test_normalization_strips_accents(self):
        f1 = self._full_fields()
        f1["first_name"] = "Andre"
        f2 = self._full_fields()
        f2["first_name"] = "André"
        h1 = verification_hashing.compute_hashes(f1)
        h2 = verification_hashing.compute_hashes(f2)
        assert h1["name_dob_hash"] == h2["name_dob_hash"]

    def test_dob_format_variants_normalize_to_iso(self):
        for raw in ("1985-03-14", "1985/03/14", "14-03-1985", "14/03/1985", "19850314"):
            assert verification_hashing.normalize_dob(raw) == "1985-03-14"

    def test_different_doc_numbers_no_longer_distinguishable(self):
        # Phase 52h Stage 2 — doc_number_hash is no longer produced.
        # The historical assertion "different document_number values
        # produce different hashes" can no longer hold because the
        # hash itself is None for both. Renamed to document the new
        # contract.
        f1 = self._full_fields()
        f2 = self._full_fields()
        f2["document_number"] = "X9876544"
        h1 = verification_hashing.compute_hashes(f1)
        h2 = verification_hashing.compute_hashes(f2)
        assert h1["doc_number_hash"] is None
        assert h2["doc_number_hash"] is None

    def test_pepper_fail_closed_raises(self, monkeypatch):
        monkeypatch.delenv("VERIFICATION_HASH_PEPPER", raising=False)
        with pytest.raises(RuntimeError, match="VERIFICATION_HASH_PEPPER"):
            verification_hashing.compute_hashes(self._full_fields())

    def test_no_unsalted_fallback(self, monkeypatch):
        # With pepper missing, NO hash is ever produced — not even
        # a "weak fallback." The raise is the only outcome.
        monkeypatch.delenv("VERIFICATION_HASH_PEPPER", raising=False)
        with pytest.raises(RuntimeError):
            verification_hashing.compute_hashes(self._full_fields())

    def test_pepper_value_changes_hash(self, monkeypatch):
        f = self._full_fields()
        h1 = verification_hashing.compute_hashes(f)
        monkeypatch.setenv("VERIFICATION_HASH_PEPPER", "DIFFERENT_DUMMY_PEPPER")
        h2 = verification_hashing.compute_hashes(f)
        # Same input, different pepper → different hashes (still
        # holds for the two name hashes; doc_number_hash is None on
        # both since Phase 52h Stage 2).
        assert h1["name_dob_hash"] != h2["name_dob_hash"]
        assert h1["name_dob_address_hash"] != h2["name_dob_address_hash"]


# ===========================================================================
# D6 — map_decision_to_state precedence fix
# ===========================================================================

class TestMapDecisionToStatePrecedence:
    # Phase 52h Stage 2 — the ``doc_number_unique`` kwarg is gone
    # from ``map_decision_to_state``; the uniqueness rung was
    # removed (Z-locked Option A). These tests now exercise the
    # post-removal mapper shape: IDENTITY or ADDRESS_ON_ID.

    def test_passed_id_no_address_returns_identity(self):
        m = verification_provider.map_decision_to_state(
            {"id_verification": {"status": "Approved"}},
        )
        assert m["verification_state"] == verification.IDENTITY

    def test_passed_id_with_address_returns_address_on_id(self):
        m = verification_provider.map_decision_to_state(
            {"id_verification": {"status": "Approved", "address_state": "CA"}},
        )
        assert m["verification_state"] == verification.ADDRESS_ON_ID
        assert m["verification_jurisdiction"] == "CA"

    def test_declined_returns_email_only(self):
        m = verification_provider.map_decision_to_state(
            {"id_verification": {"status": "Declined"}},
        )
        assert m["verification_state"] == verification.EMAIL_ONLY


# ===========================================================================
# D6 — dead Didit-1:N code removed
# ===========================================================================

class TestDeadCodeRemoved:
    def test_extract_nullifier_gone(self):
        assert not hasattr(verification_provider, "_extract_nullifier")

    def test_decision_passed_1n_dedup_gone(self):
        assert not hasattr(verification_provider, "_decision_passed_1n_dedup")

    def test_map_decision_to_state_no_longer_emits_nullifier_key(self):
        m = verification_provider.map_decision_to_state(
            {"id_verification": {"status": "Approved"}},
        )
        assert "verification_nullifier" not in m


# ===========================================================================
# D5 — document-number hard block (load-bearing side-effect tests)
# ===========================================================================

class TestDocumentNumberHardBlock:
    def _seed_session(
        self, db: Session, user: models.User, session_id: str,
    ) -> models.VerificationSession:
        row = models.VerificationSession(
            user_id=user.id,
            provider_session_id=session_id,
            status="initiated",
        )
        db.add(row); db.commit()
        return row

    def _payload(self, session_id: str, *, doc_number: str = "X9876543") -> dict:
        # Phase 52e E1 — payload uses the REAL captured-shape (plural
        # id_verifications array). 52d's documented-singular shape
        # produced no hashes against the real extractor, so the
        # collision tests now use the plural form.
        return {
            "session_id": session_id,
            "webhook_type": "session.completed",
            "decision": {
                "session_id": session_id,
                "status": "Approved",
                "id_verifications": [{
                    "status": "Approved",
                    "first_name": "Alice",
                    "last_name": "Robertson",
                    "document_number": doc_number,
                    "date_of_birth": "1985-03-14",
                }],
            },
        }

    def test_first_verification_writes_name_hashes_post_stage2(
        self, client: TestClient, db: Session, monkeypatch,
    ):
        # Phase 52h Stage 2 — doc_number_hash no longer written;
        # IDENTITY_UNIQUE no longer producible. The receiver writes
        # the two name hashes + advances state to IDENTITY (no
        # parsed address in this payload).
        monkeypatch.setattr(verification_provider, "delete_session", lambda sid: True)
        alice = make_user(db, "alice")
        self._seed_session(db, alice, "sess_first")
        body = json.dumps(self._payload("sess_first")).encode()
        r = client.post(
            "/api/webhooks/didit",
            content=body,
            headers={**_sign(body), "Content-Type": "application/json"},
        )
        assert r.status_code == 200
        db.refresh(alice)
        # Phase 58 Cluster C — `doc_number_hash` column dropped.
        assert alice.uniqueness_strength is None  # not set
        assert alice.verification_state == verification.IDENTITY
        assert alice.verification_provenance == verification.PROV_DIDIT
        assert alice.name_dob_hash is not None
        assert alice.name_dob_address_hash is None  # no address in this payload

    def test_second_user_same_doc_now_succeeds_post_stage2(
        self, client: TestClient, db: Session, monkeypatch,
    ):
        # Phase 52h Stage 2 — the platform-wide doc-number hard block
        # is GONE. Two accounts with the same document number both
        # verify successfully now. (In-org dedup remains via the
        # name-based flag system; that's covered by 52e/52h Stage 1
        # tests.)
        monkeypatch.setattr(verification_provider, "delete_session", lambda sid: True)
        alice = make_user(db, "alice")
        alice.verification_state = verification.IDENTITY
        alice.verification_provenance = verification.PROV_DIDIT
        db.commit()

        bob = make_user(db, "bob")
        self._seed_session(db, bob, "sess_no_collide")
        body = json.dumps(self._payload("sess_no_collide", doc_number="X9876543")).encode()
        r = client.post(
            "/api/webhooks/didit",
            content=body,
            headers={**_sign(body), "Content-Type": "application/json"},
        )
        assert r.status_code == 200
        db.refresh(bob)
        # Bob's verification went through.
        assert bob.verification_state == verification.IDENTITY
        assert bob.verification_provenance == verification.PROV_DIDIT
        # No duplicate_document audit anywhere.
        dup_audits = (
            db.query(models.AuditLog)
            .filter_by(action="verification.duplicate_document")
            .all()
        )
        assert dup_audits == []

    def test_same_user_reverify_still_works(
        self, client: TestClient, db: Session, monkeypatch,
    ):
        # Same-user re-verify continues to work — no special
        # idempotency branch is needed now that the hard block is
        # gone (it was the block's predicate "different user_id"
        # that handled this).
        monkeypatch.setattr(verification_provider, "delete_session", lambda sid: True)
        alice = make_user(db, "alice")
        alice.verification_state = verification.IDENTITY
        alice.verification_provenance = verification.PROV_DIDIT
        db.commit()

        self._seed_session(db, alice, "sess_reverify")
        payload = self._payload("sess_reverify", doc_number="X9876543")
        payload["decision"]["id_verifications"][0]["parsed_address"] = {
            "street_1": "1 Main St", "city": "Anytown",
            "region": "California", "postal_code": "94000",
            "country": "US",
        }
        body = json.dumps(payload).encode()
        r = client.post(
            "/api/webhooks/didit",
            content=body,
            headers={**_sign(body), "Content-Type": "application/json"},
        )
        assert r.status_code == 200
        db.refresh(alice)
        # State escalated to ADDRESS_ON_ID (the address came along).
        assert alice.verification_state == verification.ADDRESS_ON_ID
        assert alice.verification_jurisdiction == "CA"


# ===========================================================================
# D4 — purge wiring + fail-safe
# ===========================================================================

class TestPurgeWiring:
    def _payload(self, session_id: str) -> dict:
        # Phase 52e E1 — plural id_verifications shape (real path).
        return {
            "session_id": session_id,
            "webhook_type": "session.completed",
            "decision": {
                "session_id": session_id,
                "status": "Approved",
                "id_verifications": [{
                    "status": "Approved",
                    "first_name": "Alice",
                    "last_name": "Robertson",
                    "document_number": "X9876543",
                    "date_of_birth": "1985-03-14",
                }],
            },
        }

    def test_purge_called_after_approved(
        self, client: TestClient, db: Session, monkeypatch,
    ):
        called = {"count": 0, "session_id": None}
        def _stub_delete(session_id):
            called["count"] += 1
            called["session_id"] = session_id
            return True
        monkeypatch.setattr(verification_provider, "delete_session", _stub_delete)

        alice = make_user(db, "alice")
        row = models.VerificationSession(
            user_id=alice.id,
            provider_session_id="sess_purge",
            status="initiated",
        )
        db.add(row); db.commit()
        body = json.dumps(self._payload("sess_purge")).encode()
        r = client.post(
            "/api/webhooks/didit",
            content=body,
            headers={**_sign(body), "Content-Type": "application/json"},
        )
        assert r.status_code == 200
        assert called["count"] == 1
        assert called["session_id"] == "sess_purge"

    def test_purge_failure_preserves_verification(
        self, client: TestClient, db: Session, monkeypatch,
    ):
        """Fail-toward-keeping-the-verification: a purge that returns
        False (or even raises) must NOT roll back the user's
        verification record."""
        def _failing_delete(session_id):
            return False
        monkeypatch.setattr(verification_provider, "delete_session", _failing_delete)

        alice = make_user(db, "alice")
        row = models.VerificationSession(
            user_id=alice.id,
            provider_session_id="sess_purge_fail",
            status="initiated",
        )
        db.add(row); db.commit()
        body = json.dumps(self._payload("sess_purge_fail")).encode()
        r = client.post(
            "/api/webhooks/didit",
            content=body,
            headers={**_sign(body), "Content-Type": "application/json"},
        )
        assert r.status_code == 200
        db.refresh(alice)
        # The verification record stands — purge failure didn't destroy it.
        # Phase 58 Cluster C — `doc_number_hash` column dropped.
        assert alice.verification_state == verification.IDENTITY
        assert alice.verification_provenance == verification.PROV_DIDIT

    def test_purge_raise_does_not_break_receiver(
        self, client: TestClient, db: Session, monkeypatch,
    ):
        def _raising_delete(session_id):
            raise RuntimeError("network exploded")
        monkeypatch.setattr(verification_provider, "delete_session", _raising_delete)

        alice = make_user(db, "alice")
        row = models.VerificationSession(
            user_id=alice.id,
            provider_session_id="sess_purge_raise",
            status="initiated",
        )
        db.add(row); db.commit()
        body = json.dumps(self._payload("sess_purge_raise")).encode()
        r = client.post(
            "/api/webhooks/didit",
            content=body,
            headers={**_sign(body), "Content-Type": "application/json"},
        )
        assert r.status_code == 200
        db.refresh(alice)
        # Phase 52h Stage 2 — IDENTITY (no IDENTITY_UNIQUE rung).
        assert alice.verification_state == verification.IDENTITY


# ===========================================================================
# demo_stub sealed: no hashes, no purge attempted
# ===========================================================================

class TestDemoStubSealedFromDiditPath:
    def test_purge_helper_short_circuits_on_demo_stub(self, db: Session, monkeypatch):
        # If the user's provenance is demo_stub, the purge helper does
        # NOT call delete_session (no real session to purge).
        from routes.verification import _purge_session_best_effort
        called = {"count": 0}
        monkeypatch.setattr(
            verification_provider,
            "delete_session",
            lambda sid: called.update(count=called["count"] + 1) or True,
        )

        u = make_user(db, "demo_persona")
        u.verification_provenance = verification.PROV_DEMO_STUB
        db.commit()

        result = _purge_session_best_effort("anything", u)
        assert result is False
        assert called["count"] == 0


# ===========================================================================
# Serializer guard — three hashes NEVER on UserOut
# ===========================================================================

class TestSerializerGuard:
    def test_hashes_not_on_userout(self):
        import schemas
        fields = set(schemas.UserOut.model_fields.keys())
        for forbidden in (
            "doc_number_hash",
            "name_dob_address_hash",
            "name_dob_hash",
            "verification_nullifier",
            "verification_attestation_id",
        ):
            assert forbidden not in fields, (
                f"{forbidden!r} must NOT be on UserOut — cross-user "
                "correlation handle."
            )
