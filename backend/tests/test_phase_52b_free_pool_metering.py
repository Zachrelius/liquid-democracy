"""Phase 52b — free-pool metering + empty-pool wall tests.

Per the spec verification matrix:

  * Counter increments on a real ``didit``-provenance completion.
  * ``demo_stub`` / ``backdoor`` provenance NEVER increment (Phase 51
    forward-constraint).
  * Capacity predicate + remaining count + reset date.
  * Gate-display check (the FE-friendly read).
  * Session-creation hard stop — exhausted pool → 503 + NO Didit
    session created (assert no provider call).
  * Monthly reset semantics — a new ``year_month`` starts fresh.
  * Per-org consumption recorded; NO per-org cap enforced (FCFS
    shared pool).
  * Admin visibility: shared total + per-org breakdown; non-admin
    refused.
  * Additive-layer parity: below the cap, behavior is unchanged.
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
import verification_metering
import verification_provider
from main import app
from database import Base, get_db
from tests.conftest import make_user


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
    monkeypatch.setenv("VERIFICATION_HASH_PEPPER", "TEST_DUMMY_PEPPER_52B")
    # Reset session-create rate limiter between tests
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


def _auth_headers(user: models.User) -> dict[str, str]:
    import auth as auth_utils
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _make_admin(db: Session, username: str) -> models.User:
    u = make_user(db, username)
    u.is_admin = True
    db.commit()
    return u


def _real_shape_payload(session_id: str, *, doc_number: str = "X9876543") -> dict:
    return {
        "session_id": session_id,
        "webhook_type": "session.completed",
        "status": "Approved",
        "features": ["ID_VERIFICATION", "LIVENESS", "FACE_MATCH"],
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
            "liveness_checks": [{"status": "Approved"}],
            "face_matches": [{"status": "Approved"}],
        },
    }


# ===========================================================================
# B1 — counter increments on real didit-provenance completion
# ===========================================================================

class TestCounterIncrement:
    def _seed_session(
        self, db: Session, user: models.User, sid: str,
        *, triggering_org_id: str | None = None,
    ):
        row = models.VerificationSession(
            user_id=user.id, provider_session_id=sid, status="initiated",
            triggering_org_id=triggering_org_id,
        )
        db.add(row); db.commit()
        return row

    def test_real_completion_inserts_consumption_row(
        self, client: TestClient, db: Session, monkeypatch,
    ):
        monkeypatch.setattr(verification_provider, "delete_session", lambda sid: True)
        user = make_user(db, "alice")
        self._seed_session(db, user, "sess_count_1")
        body = json.dumps(_real_shape_payload("sess_count_1")).encode()
        r = client.post(
            "/api/webhooks/didit",
            content=body,
            headers={**_sign(body), "Content-Type": "application/json"},
        )
        assert r.status_code == 200
        # One consumption row exists for this user.
        rows = db.query(models.VerificationConsumption).filter_by(
            user_id=user.id,
        ).all()
        assert len(rows) == 1
        assert rows[0].provenance == "didit"
        assert rows[0].provider_session_id == "sess_count_1"

    def test_demo_stub_does_not_increment(self, db: Session):
        # Direct call to the metering helper — demo_stub is a no-op
        # by contract (the Phase 51 forward-constraint).
        user = make_user(db, "demo_persona")
        row = verification_metering.record_consumption(
            db, user_id=user.id, provenance="demo_stub",
        )
        assert row is None
        assert db.query(models.VerificationConsumption).count() == 0

    def test_backdoor_does_not_increment(self, db: Session):
        # Same contract for backdoor provenance.
        user = make_user(db, "backdoored")
        row = verification_metering.record_consumption(
            db, user_id=user.id, provenance="backdoor",
        )
        assert row is None
        assert db.query(models.VerificationConsumption).count() == 0

    def test_triggering_org_id_propagates_to_consumption_row(
        self, client: TestClient, db: Session, monkeypatch,
    ):
        monkeypatch.setattr(verification_provider, "delete_session", lambda sid: True)
        # Make an org so the FK is satisfied.
        org = models.Organization(
            name="O", slug="o", description="",
            join_policy="open", governance_mode="single_steward",
            settings={"default_deliberation_days":1,"default_voting_days":7,
                      "default_pass_threshold":0.5,"default_quorum_threshold":0,
                      "allowed_voting_methods":["binary"]},
        )
        db.add(org); db.commit()
        user = make_user(db, "alice")
        self._seed_session(db, user, "sess_org_attr", triggering_org_id=org.id)
        body = json.dumps(_real_shape_payload("sess_org_attr")).encode()
        client.post(
            "/api/webhooks/didit",
            content=body,
            headers={**_sign(body), "Content-Type": "application/json"},
        )
        row = db.query(models.VerificationConsumption).filter_by(
            user_id=user.id,
        ).one()
        assert row.org_id == org.id


# ===========================================================================
# B2 — capacity predicate
# ===========================================================================

class TestCapacityPredicate:
    def _seed_consumption(self, db: Session, n: int, *, year_month: str | None = None):
        ym = year_month or verification_metering.current_year_month()
        user = make_user(db, f"u_{ym}")
        for _ in range(n):
            db.add(models.VerificationConsumption(
                year_month=ym, user_id=user.id, provenance="didit",
            ))
        db.commit()

    def test_below_cap_has_capacity(self, db: Session):
        self._seed_consumption(db, 499)
        assert verification_metering.has_capacity(db) is True
        assert verification_metering.remaining_capacity(db) == 1

    def test_at_cap_exhausted(self, db: Session):
        self._seed_consumption(db, 500)
        assert verification_metering.has_capacity(db) is False
        assert verification_metering.remaining_capacity(db) == 0

    def test_above_cap_capped_at_zero(self, db: Session):
        self._seed_consumption(db, 501)
        assert verification_metering.has_capacity(db) is False
        assert verification_metering.remaining_capacity(db) == 0

    def test_capacity_status_shape(self, db: Session):
        self._seed_consumption(db, 100)
        st = verification_metering.capacity_status(db)
        assert st["cap"] == 500
        assert st["used"] == 100
        assert st["remaining"] == 400
        assert st["has_capacity"] is True
        assert "reset_date" in st
        assert "days_until_reset" in st
        # reset_date is the 1st of the following month — ends in "-01"
        assert st["reset_date"].endswith("-01")


# ===========================================================================
# B2 — session-creation hard stop (the authoritative wall)
# ===========================================================================

class TestSessionCreateHardStop:
    def _seed_consumption(self, db: Session, n: int):
        ym = verification_metering.current_year_month()
        user = make_user(db, "u_pool_drainer")
        for _ in range(n):
            db.add(models.VerificationConsumption(
                year_month=ym, user_id=user.id, provenance="didit",
            ))
        db.commit()

    def test_exhausted_pool_blocks_with_503_and_no_provider_call(
        self, client: TestClient, db: Session, monkeypatch,
    ):
        provider_called = {"n": 0}
        def _stub_create(user_id):
            provider_called["n"] += 1
            return {"session_id": "should-not-happen", "session_url": "x"}
        monkeypatch.setattr(verification_provider, "create_session", _stub_create)

        self._seed_consumption(db, 500)
        user = make_user(db, "alice")
        r = client.post(
            "/api/verification/session", json={},
            headers=_auth_headers(user),
        )
        assert r.status_code == 503
        # Structured body with the empty-pool reason + reset date.
        detail = r.json()["detail"]
        assert detail["error"] == "pool_unavailable"
        assert detail["reset_date"].endswith("-01")
        # CRITICAL invariant — no Didit session was created. No spend.
        assert provider_called["n"] == 0
        # No bookkeeping row got written.
        assert db.query(models.VerificationSession).filter_by(
            user_id=user.id,
        ).count() == 0

    def test_below_cap_session_create_proceeds(
        self, client: TestClient, db: Session, monkeypatch,
    ):
        # Additive-layer parity — below cap, behavior unchanged.
        def _stub_create(user_id):
            return {"session_id": "sess_below_cap", "session_url": "https://x"}
        monkeypatch.setattr(verification_provider, "create_session", _stub_create)
        self._seed_consumption(db, 100)

        user = make_user(db, "alice")
        r = client.post(
            "/api/verification/session", json={},
            headers=_auth_headers(user),
        )
        assert r.status_code == 200
        assert r.json()["session_id"] == "sess_below_cap"


# ===========================================================================
# Monthly reset semantics
# ===========================================================================

class TestMonthlyReset:
    def test_prior_month_consumption_does_not_count_against_current(
        self, db: Session,
    ):
        # Seed 500 rows in "2026-05" (prior month). Current month
        # (whatever it is) has none — capacity should be full.
        user = make_user(db, "u_prior_month")
        for _ in range(500):
            db.add(models.VerificationConsumption(
                year_month="2026-05", user_id=user.id, provenance="didit",
            ))
        db.commit()
        # The current month is later than 2026-05 in any reasonable
        # test run, so current-month consumption is 0 → full capacity.
        ym_now = verification_metering.current_year_month()
        assert ym_now != "2026-05"  # safety
        assert verification_metering.has_capacity(db) is True
        assert verification_metering.remaining_capacity(db) == 500

    def test_injected_year_month_isolates_buckets(self, db: Session):
        user = make_user(db, "u_inject")
        for _ in range(100):
            db.add(models.VerificationConsumption(
                year_month="2026-05", user_id=user.id, provenance="didit",
            ))
        for _ in range(50):
            db.add(models.VerificationConsumption(
                year_month="2026-06", user_id=user.id, provenance="didit",
            ))
        db.commit()
        assert verification_metering.current_month_consumption(
            db, year_month="2026-05",
        ) == 100
        assert verification_metering.current_month_consumption(
            db, year_month="2026-06",
        ) == 50

    def test_year_month_format(self):
        # Format = "YYYY-MM".
        ym = verification_metering.current_year_month(
            datetime(2026, 6, 15, tzinfo=timezone.utc),
        )
        assert ym == "2026-06"
        ym2 = verification_metering.current_year_month(
            datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        assert ym2 == "2026-01"

    def test_next_reset_iso_date_wraps_year(self):
        d = verification_metering.next_reset_iso_date(
            datetime(2026, 12, 14, tzinfo=timezone.utc),
        )
        assert d == "2027-01-01"


# ===========================================================================
# Per-org recorded, NOT enforced (FCFS shared pool)
# ===========================================================================

class TestPerOrgRecordedNotEnforced:
    def test_one_org_can_consume_whole_pool(self, db: Session):
        # FCFS v1: no per-org cap. One org consuming all 500 is the
        # documented v1 behavior; the data is recorded so a future
        # sub-allocation policy can act on it.
        org = models.Organization(
            name="HoardOrg", slug="hoard", description="",
            join_policy="open", governance_mode="single_steward",
            settings={"default_deliberation_days":1,"default_voting_days":7,
                      "default_pass_threshold":0.5,"default_quorum_threshold":0,
                      "allowed_voting_methods":["binary"]},
        )
        db.add(org); db.commit()
        user = make_user(db, "u_hoarder")
        ym = verification_metering.current_year_month()
        for _ in range(500):
            verification_metering.record_consumption(
                db, user_id=user.id, provenance="didit", org_id=org.id,
            )
        db.commit()
        # Pool now full.
        assert verification_metering.has_capacity(db) is False
        # ONE org owns all of it in the breakdown.
        breakdown = verification_metering.per_org_breakdown(db)
        assert len(breakdown) == 1
        assert breakdown[0]["org_id"] == org.id
        assert breakdown[0]["count"] == 500

    def test_per_org_breakdown_sorted_descending(self, db: Session):
        orgs = []
        for name, count in [("A", 10), ("B", 50), ("C", 30)]:
            o = models.Organization(
                name=name, slug=name.lower(), description="",
                join_policy="open", governance_mode="single_steward",
                settings={"default_deliberation_days":1,"default_voting_days":7,
                          "default_pass_threshold":0.5,"default_quorum_threshold":0,
                          "allowed_voting_methods":["binary"]},
            )
            db.add(o); db.commit()
            orgs.append((o, count))
        user = make_user(db, "u")
        for o, count in orgs:
            for _ in range(count):
                verification_metering.record_consumption(
                    db, user_id=user.id, provenance="didit", org_id=o.id,
                )
        db.commit()
        breakdown = verification_metering.per_org_breakdown(db)
        counts = [r["count"] for r in breakdown]
        assert counts == sorted(counts, reverse=True)
        # Top is B with 50.
        assert breakdown[0]["org_name"] == "B"
        assert breakdown[0]["count"] == 50

    def test_null_org_id_bucketed_separately(self, db: Session):
        user = make_user(db, "u_no_org")
        for _ in range(5):
            verification_metering.record_consumption(
                db, user_id=user.id, provenance="didit", org_id=None,
            )
        db.commit()
        breakdown = verification_metering.per_org_breakdown(db)
        assert len(breakdown) == 1
        assert breakdown[0]["org_id"] is None
        assert breakdown[0]["count"] == 5


# ===========================================================================
# B4 — admin visibility
# ===========================================================================

class TestAdminVisibility:
    def test_admin_sees_pool_status(self, client: TestClient, db: Session):
        admin = _make_admin(db, "admin")
        # Seed a few consumptions.
        user = make_user(db, "u")
        ym = verification_metering.current_year_month()
        for _ in range(7):
            db.add(models.VerificationConsumption(
                year_month=ym, user_id=user.id, provenance="didit",
            ))
        db.commit()
        r = client.get(
            "/api/admin/verification/pool-status",
            headers=_auth_headers(admin),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["cap"] == 500
        assert body["used"] == 7
        assert body["remaining"] == 493
        assert body["has_capacity"] is True
        assert isinstance(body["per_org"], list)
        assert "year_month" in body

    def test_non_admin_refused(self, client: TestClient, db: Session):
        user = make_user(db, "u_regular")
        r = client.get(
            "/api/admin/verification/pool-status",
            headers=_auth_headers(user),
        )
        assert r.status_code in (401, 403)


# ===========================================================================
# B2 call site 1 — gate-display pool-status endpoint
# ===========================================================================

class TestGateDisplayPoolStatus:
    def test_authenticated_user_can_read_capacity_flag(
        self, client: TestClient, db: Session,
    ):
        user = make_user(db, "u")
        r = client.get(
            "/api/verification/pool-status",
            headers=_auth_headers(user),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["has_capacity"] is True
        assert body["reset_date"].endswith("-01")

    def test_pool_status_flips_when_exhausted(
        self, client: TestClient, db: Session,
    ):
        user = make_user(db, "u")
        ym = verification_metering.current_year_month()
        for _ in range(500):
            db.add(models.VerificationConsumption(
                year_month=ym, user_id=user.id, provenance="didit",
            ))
        db.commit()
        r = client.get(
            "/api/verification/pool-status",
            headers=_auth_headers(user),
        )
        assert r.status_code == 200
        assert r.json()["has_capacity"] is False

    def test_gate_status_does_not_expose_count_to_non_admin(
        self, client: TestClient, db: Session,
    ):
        # Privacy: a non-admin endpoint should not reveal exact
        # numbers, only the boolean + reset info.
        user = make_user(db, "u")
        r = client.get(
            "/api/verification/pool-status",
            headers=_auth_headers(user),
        )
        body = r.json()
        assert "used" not in body
        assert "cap" not in body
        assert "remaining" not in body
        assert "per_org" not in body
