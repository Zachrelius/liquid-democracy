"""Phase 52e Stage 1 — E1 extractor rewrite + E1b purge fix.

The 52d-grounding capture revealed two real-payload gaps:

  1. **Extractor pointed at wrong keys.** ``decision.id_verification``
     (singular object) is the documented shape; Didit actually emits
     ``decision.id_verifications`` (PLURAL ARRAY). 52d's extractor
     returned all-None on the real payload → Z's row sat at
     ``identity`` with NULL hashes. E1 rewrites the extractor against
     the captured manifest.

  2. **Purge mistakenly accepted 404.** The 2026-06-05 Z portal check
     confirmed session ``66a70eb2`` is fully retained at Didit even
     though our DELETE got a 404. E1b treats 404 as failure, tries a
     candidate-path list (extendable via env without redeploy), and
     records the bookkeeping row distinctly as ``approved_purged``
     vs ``approved_purge_failed`` so a retry sweep can find the
     latter.

Tests cover:
  - E1 extractor against a representative-shape captured-style
    payload (no real PII; the key SHAPE is what's load-bearing).
  - E1 defensive behavior: empty array, missing element, missing
    sub-fields, malformed shapes all → None values, never a crash.
  - normalize_jurisdiction full-state-name acceptance.
  - E1b: 404 from the configured endpoint is NOT success;
    candidate-path list cycles to a working one; all-fail returns
    False + the bookkeeping row lands ``approved_purge_failed``.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Iterator

import httpx
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
from tests.conftest import make_user


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
def _env(monkeypatch):
    monkeypatch.setenv("DIDIT_WEBHOOK_SECRET", "test_secret_value")
    monkeypatch.setenv("VERIFICATION_HASH_PEPPER", "TEST_DUMMY_PEPPER_PHASE_52E_S1")
    yield


def _sign(body: bytes) -> dict[str, str]:
    ts = int(time.time())
    mac = hmac.new(b"test_secret_value", body, hashlib.sha256).hexdigest()
    return {"X-Signature": mac, "X-Timestamp": str(ts)}


# Representative-shape payload mirroring the 2026-06-05 captured
# manifest. No real PII — placeholder strings used at each leaf
# Didit's payload puts a value at. The KEY PATHS are what's load-
# bearing; the VALUES here are deliberately synthetic.
def _captured_shape_payload(
    *, session_id: str = "sess_e1_test_aaaaaaaaaaaaaaa",
    document_number: str = "X9876543",
    first_name: str = "Alice",
    last_name: str = "Robertson",
    full_name: str = "Alice Q Robertson",
    date_of_birth: str = "1985-03-14",
    region: str = "Massachusetts",
    street_1: str = "1234 Main St",
    city: str = "Boston",
    postal_code: str = "02115",
    country: str = "US",
) -> dict:
    return {
        "application_id": "app-uuid-aaaaaaaaaaaaaaaa",
        "created_at": 1780661519,
        "decision": {
            "session_id": session_id,
            "status": "Approved",
            "id_verifications": [
                {
                    "status": "Approved",
                    "document_number": document_number,
                    "first_name": first_name,
                    "last_name": last_name,
                    "full_name": full_name,
                    "date_of_birth": date_of_birth,
                    "issuing_state": "MA-",
                    "issuing_state_name": "Massachusetts",
                    "address": "1234 Main St, Boston, MA 02115",
                    "formatted_address": "1234 Main St, Boston, MA 02115",
                    "parsed_address": {
                        "street_1": street_1,
                        "street_2": None,
                        "city": city,
                        "region": region,
                        "postal_code": postal_code,
                        "country": country,
                    },
                    "extra_fields": {"state": "Massachusetts"},
                },
            ],
            "face_matches": [{"status": "Approved", "score": 96.04}],
            "ip_analyses": [{"status": "Approved"}],
            "liveness_checks": [{"status": "Approved"}],
        },
        "environment": "live",
        "event_id": "evt-uuid",
        "session_id": session_id,
        "status": "Approved",
        "vendor_data": "user-uuid",
        "webhook_type": "status.updated",
        "workflow_id": "wf-uuid",
        "workflow_version": 1,
    }


# ===========================================================================
# E1 — extractor rewrite against the real plural-array path
# ===========================================================================

class TestExtractorRealPaths:
    """The 52d-shipped extractor probed wrong keys and returned all-
    None on the real payload. After E1 these must extract correctly.
    """

    def test_extracts_document_number_from_plural_array(self):
        from routes.verification import _extract_ocr_fields
        payload = _captured_shape_payload(document_number="X9876543")
        fields = _extract_ocr_fields(payload["decision"])
        assert fields["document_number"] == "X9876543"

    def test_extracts_first_last_name_from_plural_array(self):
        from routes.verification import _extract_ocr_fields
        payload = _captured_shape_payload(first_name="Alice", last_name="Robertson")
        fields = _extract_ocr_fields(payload["decision"])
        assert fields["first_name"] == "Alice"
        assert fields["last_name"] == "Robertson"

    def test_extracts_date_of_birth(self):
        from routes.verification import _extract_ocr_fields
        payload = _captured_shape_payload(date_of_birth="1985-03-14")
        fields = _extract_ocr_fields(payload["decision"])
        assert fields["date_of_birth"] == "1985-03-14"

    def test_extracts_structured_address_from_parsed_address(self):
        from routes.verification import _extract_ocr_fields
        payload = _captured_shape_payload(
            street_1="1234 Main St", city="Boston",
            region="Massachusetts", postal_code="02115",
        )
        fields = _extract_ocr_fields(payload["decision"])
        assert fields["address"] == {
            "street": "1234 Main St",
            "city": "Boston",
            "state": "Massachusetts",
            "zip": "02115",
        }

    def test_compute_hashes_against_real_path_payload_succeeds(self):
        """The whole point of E1: a real-shape payload now yields
        three non-None hashes (the 52d gap)."""
        from routes.verification import _extract_ocr_fields
        payload = _captured_shape_payload()
        fields = _extract_ocr_fields(payload["decision"])
        hashes = verification_hashing.compute_hashes(fields)
        assert hashes["doc_number_hash"] is not None
        assert hashes["name_dob_hash"] is not None
        assert hashes["name_dob_address_hash"] is not None


# ===========================================================================
# E1 — defensive shape-handling (the lesson from the 52d gap)
# ===========================================================================

class TestExtractorDefensiveShapes:
    def test_empty_array_yields_all_none(self):
        from routes.verification import _extract_ocr_fields
        fields = _extract_ocr_fields({"id_verifications": []})
        for k, v in fields.items():
            assert v is None, f"{k!r} expected None, got {v!r}"

    def test_missing_array_yields_all_none(self):
        from routes.verification import _extract_ocr_fields
        fields = _extract_ocr_fields({})
        for k, v in fields.items():
            assert v is None

    def test_array_element_not_dict_yields_all_none(self):
        from routes.verification import _extract_ocr_fields
        fields = _extract_ocr_fields({"id_verifications": ["not a dict"]})
        for k, v in fields.items():
            assert v is None

    def test_missing_parsed_address_yields_no_address(self):
        from routes.verification import _extract_ocr_fields
        fields = _extract_ocr_fields({
            "id_verifications": [{
                "document_number": "X1234",
                "first_name": "A", "last_name": "B",
                "date_of_birth": "1990-01-01",
            }],
        })
        assert fields["document_number"] == "X1234"
        assert fields["address"] is None

    def test_parsed_address_all_empty_collapses_to_none(self):
        from routes.verification import _extract_ocr_fields
        fields = _extract_ocr_fields({
            "id_verifications": [{
                "parsed_address": {
                    "street_1": None, "city": None,
                    "region": None, "postal_code": None,
                },
            }],
        })
        assert fields["address"] is None

    def test_malformed_decision_yields_empty(self):
        from routes.verification import _extract_ocr_fields
        assert _extract_ocr_fields("not a dict") == {}
        assert _extract_ocr_fields(None) == {}


# ===========================================================================
# E1 — normalize_jurisdiction full-state-name acceptance
# ===========================================================================

class TestJurisdictionFullNames:
    def test_full_name_lowercased_resolves(self):
        assert verification_provider.normalize_jurisdiction("massachusetts") == "MA"

    def test_full_name_uppercased_resolves(self):
        assert verification_provider.normalize_jurisdiction("MASSACHUSETTS") == "MA"

    def test_full_name_titlecase_resolves(self):
        assert verification_provider.normalize_jurisdiction("California") == "CA"

    def test_multi_word_state_resolves(self):
        assert verification_provider.normalize_jurisdiction("new york") == "NY"
        assert verification_provider.normalize_jurisdiction("North Carolina") == "NC"

    def test_two_letter_code_still_works(self):
        assert verification_provider.normalize_jurisdiction("ca") == "CA"
        assert verification_provider.normalize_jurisdiction("MA") == "MA"

    def test_dc_via_full_name(self):
        assert verification_provider.normalize_jurisdiction("District of Columbia") == "DC"

    def test_non_us_full_name_rejected(self):
        assert verification_provider.normalize_jurisdiction("Ontario") is None

    def test_country_code_still_rejected(self):
        assert verification_provider.normalize_jurisdiction("US") is None


# ===========================================================================
# E1 — mapper now escalates to address_on_id on real shape
# ===========================================================================

class TestMapperOnRealShape:
    def test_real_shape_payload_with_region_escalates_to_address_on_id(self):
        payload = _captured_shape_payload(region="Massachusetts")
        mapped = verification_provider.map_decision_to_state(
            payload["decision"], doc_number_unique=True,
        )
        assert mapped["verification_state"] == verification.ADDRESS_ON_ID
        assert mapped["verification_jurisdiction"] == "MA"

    def test_real_shape_payload_unrecognized_region_stays_at_unique(self):
        payload = _captured_shape_payload(region="Ontario")
        mapped = verification_provider.map_decision_to_state(
            payload["decision"], doc_number_unique=True,
        )
        # Region didn't normalize; no jurisdiction, but unique was
        # supplied → IDENTITY_UNIQUE (rung 2), not ADDRESS_ON_ID.
        assert mapped["verification_state"] == verification.IDENTITY_UNIQUE
        assert mapped["verification_jurisdiction"] is None


# ===========================================================================
# E1 + E1b — end-to-end webhook landing on the captured shape
# ===========================================================================

class TestWebhookOnRealShape:
    def _seed_session(self, db: Session, user: models.User, sid: str):
        row = models.VerificationSession(
            user_id=user.id, provider_session_id=sid, status="initiated",
        )
        db.add(row); db.commit()
        return row

    def test_real_shape_writes_hashes_and_address_on_id_state(
        self, client: TestClient, db: Session, monkeypatch,
    ):
        # Stub out the purge so this test focuses on the extractor +
        # state-write path; E1b purge behavior covered separately.
        monkeypatch.setattr(verification_provider, "delete_session", lambda sid: True)

        user = make_user(db, "alice")
        self._seed_session(db, user, "sess_real_shape")
        payload = _captured_shape_payload(session_id="sess_real_shape")
        body = json.dumps(payload).encode("utf-8")
        r = client.post(
            "/api/webhooks/didit",
            content=body,
            headers={**_sign(body), "Content-Type": "application/json"},
        )
        assert r.status_code == 200
        db.refresh(user)
        assert user.verification_state == verification.ADDRESS_ON_ID
        assert user.verification_jurisdiction == "MA"
        assert user.verification_provenance == verification.PROV_DIDIT
        assert user.doc_number_hash is not None
        assert user.name_dob_hash is not None
        assert user.name_dob_address_hash is not None
        assert user.uniqueness_strength == "document_hash"


# ===========================================================================
# E1b — purge: 404 is NOT success; candidate paths; bookkeeping
# ===========================================================================

class TestPurge404IsFailure:
    def test_404_returns_false_and_marks_purge_failed(
        self, client: TestClient, db: Session, monkeypatch,
    ):
        """The exact 52d-round-trip scenario: Didit returns 404 on
        the configured endpoint. The receiver must record
        ``approved_purge_failed`` on the bookkeeping row, NOT
        ``approved_purged``. Z's portal proof: a 404'd session can
        still be fully retained at Didit."""
        calls = []
        def _stub_delete(sid):
            calls.append(sid)
            return False  # 404 / all candidates fail
        monkeypatch.setattr(verification_provider, "delete_session", _stub_delete)

        user = make_user(db, "alice")
        row = models.VerificationSession(
            user_id=user.id,
            provider_session_id="sess_purge_404",
            status="initiated",
        )
        db.add(row); db.commit()
        payload = _captured_shape_payload(session_id="sess_purge_404")
        body = json.dumps(payload).encode("utf-8")
        r = client.post(
            "/api/webhooks/didit",
            content=body,
            headers={**_sign(body), "Content-Type": "application/json"},
        )
        assert r.status_code == 200
        # Verification record stood — fail-toward-keeping.
        db.refresh(user)
        assert user.verification_state == verification.ADDRESS_ON_ID
        # Bookkeeping row marked ``approved_purge_failed`` so a sweep
        # can find it.
        db.refresh(row)
        assert row.status == "approved_purge_failed"
        # Purge was actually called.
        assert calls == ["sess_purge_404"]

    def test_successful_purge_marks_approved_purged(
        self, client: TestClient, db: Session, monkeypatch,
    ):
        monkeypatch.setattr(verification_provider, "delete_session", lambda sid: True)

        user = make_user(db, "alice")
        row = models.VerificationSession(
            user_id=user.id,
            provider_session_id="sess_purge_ok",
            status="initiated",
        )
        db.add(row); db.commit()
        payload = _captured_shape_payload(session_id="sess_purge_ok")
        body = json.dumps(payload).encode("utf-8")
        r = client.post(
            "/api/webhooks/didit",
            content=body,
            headers={**_sign(body), "Content-Type": "application/json"},
        )
        assert r.status_code == 200
        db.refresh(row)
        assert row.status == "approved_purged"


class TestPurgeCandidatePathFallback:
    """``delete_session`` should try multiple candidate endpoints
    (so an operator can extend via env without a code deploy)."""

    def test_candidate_path_list_dedupes_and_walks(self, monkeypatch):
        # Force the candidate list to a known order.
        monkeypatch.setenv("DIDIT_API_KEY", "stub_key")
        monkeypatch.delenv("DIDIT_SESSION_DELETE_PATH", raising=False)
        monkeypatch.setenv("DIDIT_SESSION_DELETE_PATHS", "/a/{id}/,/b/{id}/")

        calls: list[str] = []

        class _StubResp:
            def __init__(self, code):
                self.status_code = code

        class _StubClient:
            def __init__(self, *a, **kw): ...
            def __enter__(self): return self
            def __exit__(self, *a): ...
            def delete(self, url, headers=None):
                calls.append(url)
                # /a/ returns 404, /b/ returns 200 — verify the
                # walker tries /a/ first, then /b/, and returns True.
                if "/a/" in url:
                    return _StubResp(404)
                return _StubResp(200)

        monkeypatch.setattr(httpx, "Client", _StubClient)

        ok = verification_provider.delete_session("sess_xyz")
        assert ok is True
        # First /a/ candidate, then /b/ — walker found success.
        assert any("/a/sess_xyz/" in u for u in calls)
        assert any("/b/sess_xyz/" in u for u in calls)

    def test_all_paths_404_returns_false(self, monkeypatch):
        monkeypatch.setenv("DIDIT_API_KEY", "stub_key")
        monkeypatch.delenv("DIDIT_SESSION_DELETE_PATH", raising=False)
        monkeypatch.setenv("DIDIT_SESSION_DELETE_PATHS", "/a/{id}/,/b/{id}/")

        class _StubResp:
            def __init__(self, code):
                self.status_code = code

        class _StubClient:
            def __init__(self, *a, **kw): ...
            def __enter__(self): return self
            def __exit__(self, *a): ...
            def delete(self, url, headers=None):
                return _StubResp(404)

        monkeypatch.setattr(httpx, "Client", _StubClient)
        ok = verification_provider.delete_session("sess_xyz")
        assert ok is False

    def test_404_not_treated_as_success(self, monkeypatch):
        """The load-bearing E1b invariant — even a single configured
        path returning 404 must return False, not True. Z's portal
        proof: 404 can mean the session is fully retained, not
        deleted."""
        monkeypatch.setenv("DIDIT_API_KEY", "stub_key")
        monkeypatch.delenv("DIDIT_SESSION_DELETE_PATH", raising=False)
        monkeypatch.setenv("DIDIT_SESSION_DELETE_PATHS", "/only/{id}/")

        class _StubResp:
            def __init__(self, code):
                self.status_code = code

        class _StubClient:
            def __init__(self, *a, **kw): ...
            def __enter__(self): return self
            def __exit__(self, *a): ...
            def delete(self, url, headers=None):
                return _StubResp(404)

        monkeypatch.setattr(httpx, "Client", _StubClient)
        ok = verification_provider.delete_session("sess_xyz")
        assert ok is False
