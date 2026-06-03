"""Phase 52c — PII-safe payload capture tests.

Two layers per the spec:

  * **C2 — redaction safety (LOAD-BEARING).** Feed a synthetic
    payload carrying fake PII (name, address, document number, DOB,
    DL number, country code, phone, email) through
    ``verification_provider.redact_payload`` and assert NONE of the
    PII strings appear in the captured output. The phase ships only
    if this test goes green.
  * **C3 — capture fires + behavior unchanged.** Hit the webhook
    receiver with a valid signed payload that mixes PII-shaped
    leaves with dedup-relevant fields; assert the receiver logs a
    redacted skeleton, that the user record is still written exactly
    as Phase 52a would have written it (state, provenance, NULL
    nullifier when no dedup block present, etc.), and the receiver
    returns 200.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
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
def _webhook_secret(monkeypatch):
    monkeypatch.setenv("DIDIT_WEBHOOK_SECRET", "test_secret_value")
    yield


def _sign(body: bytes) -> dict[str, str]:
    ts = int(time.time())
    mac = hmac.new(b"test_secret_value", body, hashlib.sha256).hexdigest()
    return {"X-Signature": mac, "X-Timestamp": str(ts)}


# ---------------------------------------------------------------------------
# C2 — redaction safety (load-bearing)
# ---------------------------------------------------------------------------
#
# This is the test the whole phase depends on. If a single PII string
# appears in the captured output, the capture is not safe to deploy.


# Fake PII values used across the test. They are deliberately
# distinctive so a literal-substring check catches any leak through
# the redactor's net.
PII_STRINGS = [
    "Alice Quincy Robertson",       # Full name
    "Alice",                        # First name
    "Robertson",                    # Last name
    "1234 Elm Street, Apt 7B",      # Street address
    "Springfield",                  # City
    "94114",                        # ZIP
    "AB1234567CD",                  # Document number
    "DL-987654321",                 # Driver's license number
    "1985-03-14",                   # DOB
    "alice.robertson@example.com",  # Email
    "+1-415-555-0199",              # Phone
    "Canada",                       # Full country name (non-US, so
                                    # NORM_JUR returns None — still PII)
    "California Drivers License",   # ID title
    "Driver License",               # Document type label
]


@pytest.fixture()
def pii_payload() -> dict:
    """Synthetic Didit-like payload with PII at every PII-shaped key.

    Mirrors plausible Didit `decision` shape with PII at every leaf a
    real ID check might surface. ALL of the strings in PII_STRINGS
    appear at least once.
    """
    return {
        "session_id": "61ea6065-5cd2-45a8-8f18-8d87fa9e8f9e",
        "webhook_type": "session.completed",
        "status": "Approved",
        "vendor_data": "user_dab7a23a-1a46-4283-986a-49dbef2f2ea0",
        "decision": {
            "session_id": "61ea6065-5cd2-45a8-8f18-8d87fa9e8f9e",
            "status": "Approved",
            "id_verification": {
                "status": "Approved",
                "first_name": "Alice",
                "last_name": "Robertson",
                "full_name": "Alice Quincy Robertson",
                "date_of_birth": "1985-03-14",
                "document_number": "AB1234567CD",
                "drivers_license_number": "DL-987654321",
                "document_type": "Driver License",
                "document_title": "California Drivers License",
                "address": {
                    "street": "1234 Elm Street, Apt 7B",
                    "city": "Springfield",
                    "state": "CA",
                    "zip": "94114",
                    "country": "Canada",
                },
                "email": "alice.robertson@example.com",
                "phone": "+1-415-555-0199",
            },
            "face_match": {
                "status": "Approved",
                "score": 0.97,
                "live": True,
            },
            "device_ip_analysis": {
                "status": "Approved",
                "risk_score": 0.12,
            },
        },
    }


class TestRedactor:
    """The load-bearing PII-safety test. None of the synthetic PII
    strings may appear in the captured output."""

    def test_no_pii_string_survives_redaction(self, pii_payload):
        skeleton = verification_provider.redact_payload(pii_payload)
        dumped = json.dumps(skeleton, sort_keys=True)
        for pii in PII_STRINGS:
            assert pii not in dumped, (
                f"PII string {pii!r} leaked through redactor. "
                f"Skeleton:\n{dumped}"
            )

    def test_status_enums_preserved(self, pii_payload):
        skeleton = verification_provider.redact_payload(pii_payload)
        # The decision shape keys + status strings must survive so
        # 52d can read the actual feature structure.
        assert skeleton["status"] == "Approved"
        assert skeleton["decision"]["status"] == "Approved"
        assert skeleton["decision"]["id_verification"]["status"] == "Approved"
        assert skeleton["decision"]["face_match"]["status"] == "Approved"

    def test_opaque_ids_preserved(self, pii_payload):
        skeleton = verification_provider.redact_payload(pii_payload)
        # Session id (UUID-like) should pass through as a known-safe
        # opaque handle so we can correlate captures to a session.
        assert skeleton["session_id"] == "61ea6065-5cd2-45a8-8f18-8d87fa9e8f9e"

    def test_key_paths_preserved(self, pii_payload):
        # The reason the capture exists at all is to learn the KEY
        # SHAPE of the decision. Every key from the input must appear
        # in the output.
        skeleton = verification_provider.redact_payload(pii_payload)
        assert "decision" in skeleton
        assert "id_verification" in skeleton["decision"]
        assert "face_match" in skeleton["decision"]
        assert "address" in skeleton["decision"]["id_verification"]
        # An address leaf-key like "state" is present — even though its
        # value redacted to a "<str:N>" placeholder.
        assert "state" in skeleton["decision"]["id_verification"]["address"]

    def test_short_pii_strings_redacted_to_type_length(self, pii_payload):
        # State codes ("CA"), zips ("94114"), names ("Alice") are all
        # < 16 chars and not on the safe-enum list, so they redact to
        # "<str:N>" — value gone, shape kept.
        skeleton = verification_provider.redact_payload(pii_payload)
        iv = skeleton["decision"]["id_verification"]
        assert iv["first_name"].startswith("<str:")
        assert iv["address"]["state"].startswith("<str:")
        assert iv["address"]["zip"].startswith("<str:")

    def test_numbers_booleans_nulls_passthrough(self):
        payload = {"score": 0.97, "live": True, "spoof": False, "blocked": None}
        skeleton = verification_provider.redact_payload(payload)
        assert skeleton == {"score": 0.97, "live": True, "spoof": False, "blocked": None}

    def test_empty_string_redacts_to_empty(self):
        assert verification_provider.redact_payload("") == ""

    def test_handles_lists(self):
        payload = {"warnings": ["Alice Robertson", "1234 Elm St", "approved"]}
        skeleton = verification_provider.redact_payload(payload)
        assert skeleton["warnings"][0].startswith("<str:")
        assert skeleton["warnings"][1].startswith("<str:")
        assert skeleton["warnings"][2] == "approved"

    def test_handles_deep_nesting_with_truncation(self):
        # Build a 25-deep nest; the redactor should truncate before
        # blowing the recursion limit.
        deep: dict | str = "Alice"
        for _ in range(25):
            deep = {"x": deep}
        skeleton = verification_provider.redact_payload(deep)
        dumped = json.dumps(skeleton)
        assert "Alice" not in dumped
        assert "<truncated>" in dumped

    def test_unknown_type_redacted_to_type_label(self):
        class Custom:
            pass
        skeleton = verification_provider.redact_payload({"x": Custom()})
        assert skeleton["x"].startswith("<")
        assert "Custom" in skeleton["x"]


# ---------------------------------------------------------------------------
# C1/C3 — capture fires on the receiver path; behavior unchanged
# ---------------------------------------------------------------------------

class TestCaptureFiresOnWebhook:
    def _seed_session(self, db: Session, user: models.User, session_id: str) -> models.VerificationSession:
        row = models.VerificationSession(
            user_id=user.id,
            provider_session_id=session_id,
            status="initiated",
        )
        db.add(row); db.commit()
        return row

    def test_capture_log_emitted_with_no_pii(
        self, client: TestClient, db: Session, pii_payload, caplog,
    ):
        # Wire the synthetic PII payload's session id to a real user.
        user = make_user(db, "alice")
        self._seed_session(db, user, pii_payload["session_id"])

        body = json.dumps(pii_payload).encode("utf-8")
        with caplog.at_level(logging.INFO, logger="routes.verification"):
            r = client.post(
                "/api/webhooks/didit",
                content=body,
                headers={**_sign(body), "Content-Type": "application/json"},
            )
        assert r.status_code == 200

        # The capture-line search has to be done across the whole
        # captured logging since FastAPI's TestClient logs go through
        # the root handler.
        capture_lines = [
            rec for rec in caplog.records
            if "didit_webhook_payload_capture" in rec.getMessage()
            and "failed" not in rec.getMessage()
        ]
        assert capture_lines, (
            "Expected a structured capture log line; saw none.\n"
            f"All records: {[r.getMessage()[:120] for r in caplog.records]}"
        )
        line = capture_lines[0].getMessage()
        for pii in PII_STRINGS:
            assert pii not in line, (
                f"PII string {pii!r} leaked into the capture log line. "
                f"Line:\n{line}"
            )

    def test_capture_does_not_change_state_write(
        self, client: TestClient, db: Session,
    ):
        # Identical-to-52a-Phase-1 webhook: ID approved, no dedup, no
        # parsed address. State should still land at ``identity`` and
        # nullifier stay NULL — capture must not change behavior.
        user = make_user(db, "bob")
        self._seed_session(db, user, "sess_no_dedup")
        payload = {
            "session_id": "sess_no_dedup",
            "webhook_type": "session.completed",
            "decision": {
                "session_id": "sess_no_dedup",
                "id_verification": {"status": "Approved"},
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
        assert user.verification_state == verification.IDENTITY
        assert user.verification_nullifier is None
        assert user.verification_provenance == verification.PROV_DIDIT

    def test_capture_failure_does_not_break_receiver(
        self, client: TestClient, db: Session, monkeypatch,
    ):
        # If the redactor itself raises for any reason, the receiver
        # must still apply the verification — capture is pure
        # instrumentation and never gates correctness.
        user = make_user(db, "carol")
        self._seed_session(db, user, "sess_redactor_oops")

        def _boom(value, _depth=0):  # noqa: ARG001
            raise RuntimeError("synthetic redactor failure")

        monkeypatch.setattr(verification_provider, "redact_payload", _boom)

        payload = {
            "session_id": "sess_redactor_oops",
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
        db.refresh(user)
        assert user.verification_state == verification.IDENTITY
