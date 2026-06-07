"""Phase 52i — city/locality residency hash + gate tests.

Per the spec verification matrix:

  * Hash machinery — state included in the hash for cross-state
    disambiguation; reuses the same pepper + normalization;
    fail-closed on absent pepper / city / state.
  * Compute-and-discard in ``_apply_decision``; readable city
    never persisted.
  * ``user_meets_locality`` predicate — match / mismatch / no user
    hash / no gate set / misconfigured (city-without-state).
  * Two independent levels, no subsumption — a member matching the
    city but failing the state gate (and vice versa) is blocked.
  * Membership gate side-effect — non-matching-city user blocked at
    join with the locality-scoped structured 403.
  * Cardinality-floor invariant — adding a city gate does not
    auto-strip a seated incumbent.
  * Mode-3 parity — unconfigured org behaves byte-for-byte.
  * Serializer guard — ``verification_locality_hash`` NEVER on
    UserOut.
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
import schemas
import verification
import verification_hashing
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
    monkeypatch.setenv("VERIFICATION_HASH_PEPPER", "TEST_DUMMY_PEPPER_52I")
    try:
        from routes.verification import limiter as _lim
        _lim.reset()
    except Exception:
        pass
    yield


def _sign(body: bytes) -> dict[str, str]:
    ts = int(time.time())
    mac = hmac.new(b"test_secret_value", body, hashlib.sha256).hexdigest()
    return {"X-Signature": mac, "X-Timestamp": str(ts)}


def _auth(user: models.User) -> dict[str, str]:
    import auth as auth_utils
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _make_org(
    db: Session, slug: str, *,
    membership_floor: str | None = None,
    membership_jurisdiction: str | None = None,
    membership_locality: str | None = None,
) -> models.Organization:
    settings: dict = {
        "default_deliberation_days": 1, "default_voting_days": 7,
        "default_pass_threshold": 0.5, "default_quorum_threshold": 0.0,
        "allowed_voting_methods": ["binary"],
    }
    if membership_floor:
        settings["verification_membership_floor"] = membership_floor
    if membership_jurisdiction:
        settings["verification_membership_jurisdiction"] = membership_jurisdiction
    if membership_locality:
        settings["verification_membership_locality"] = membership_locality
    org = models.Organization(
        name=slug.title(), slug=slug, description="",
        join_policy="open", governance_mode="single_steward",
        settings=settings,
    )
    db.add(org); db.flush()
    from role_seed import seed_default_roles_for_org
    from org_titles import seed_system_titles_for_org
    seed_default_roles_for_org(db, org.id)
    seed_system_titles_for_org(db, org.id)
    db.commit()
    return org


def _verified_user(
    db: Session, name: str, *,
    state: str = "address_on_id",
    jurisdiction: str | None = "MA",
    locality_hash: str | None = None,
) -> models.User:
    u = make_user(db, name)
    u.verification_state = state
    u.verification_jurisdiction = jurisdiction
    u.verification_provenance = "didit"
    u.verification_updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    if locality_hash:
        u.verification_locality_hash = locality_hash
    db.commit()
    return u


# ===========================================================================
# compute_locality_hash — state-in-hash + pepper + fail-closed
# ===========================================================================

class TestComputeLocalityHash:
    def test_same_city_same_state_same_hash(self):
        a = verification_hashing.compute_locality_hash("Boston", "MA")
        b = verification_hashing.compute_locality_hash("Boston", "MA")
        assert a is not None
        assert a == b

    def test_same_city_different_state_different_hash(self):
        # Load-bearing: Springfield, MA must not collide with
        # Springfield, IL.
        a = verification_hashing.compute_locality_hash("Springfield", "MA")
        b = verification_hashing.compute_locality_hash("Springfield", "IL")
        assert a != b

    def test_normalization_consistency_with_jurisdiction(self):
        # State input is normalized — "Massachusetts" and "MA" should
        # produce the SAME hash (mirror of normalize_jurisdiction's
        # full-name handling).
        a = verification_hashing.compute_locality_hash("Boston", "MA")
        b = verification_hashing.compute_locality_hash("Boston", "Massachusetts")
        assert a == b

    def test_city_normalization_strips_case_and_punct(self):
        # ``normalize_text`` lowercases + strips punctuation, so
        # "Boston" / "boston" / "boston." all produce the same hash.
        a = verification_hashing.compute_locality_hash("Boston", "MA")
        b = verification_hashing.compute_locality_hash("boston", "MA")
        c = verification_hashing.compute_locality_hash("Boston.", "MA")
        assert a == b == c

    def test_missing_city_returns_none(self):
        assert verification_hashing.compute_locality_hash(None, "MA") is None
        assert verification_hashing.compute_locality_hash("", "MA") is None

    def test_missing_or_invalid_state_returns_none(self):
        assert verification_hashing.compute_locality_hash("Boston", None) is None
        assert verification_hashing.compute_locality_hash("Boston", "") is None
        # Non-US state codes / countries normalize to None → no hash.
        assert verification_hashing.compute_locality_hash("Toronto", "ON") is None

    def test_pepper_value_changes_hash(self, monkeypatch):
        a = verification_hashing.compute_locality_hash("Boston", "MA")
        monkeypatch.setenv("VERIFICATION_HASH_PEPPER", "DIFFERENT_DUMMY")
        b = verification_hashing.compute_locality_hash("Boston", "MA")
        assert a != b

    def test_pepper_absent_raises(self, monkeypatch):
        monkeypatch.delenv("VERIFICATION_HASH_PEPPER", raising=False)
        with pytest.raises(RuntimeError):
            verification_hashing.compute_locality_hash("Boston", "MA")


# ===========================================================================
# user_meets_locality predicate
# ===========================================================================

class TestUserMeetsLocality:
    def test_no_gate_set_returns_true(self, db: Session):
        org = _make_org(db, "o")  # no locality gate
        u = make_user(db, "u")
        assert verification.user_meets_locality(u, org) is True

    def test_matching_hash_returns_true(self, db: Session):
        org = _make_org(
            db, "o",
            membership_jurisdiction="MA",
            membership_locality="Boston",
        )
        boston_hash = verification_hashing.compute_locality_hash("Boston", "MA")
        u = _verified_user(db, "u", jurisdiction="MA", locality_hash=boston_hash)
        assert verification.user_meets_locality(u, org) is True

    def test_mismatching_hash_returns_false(self, db: Session):
        org = _make_org(
            db, "o",
            membership_jurisdiction="MA",
            membership_locality="Boston",
        )
        cambridge_hash = verification_hashing.compute_locality_hash("Cambridge", "MA")
        u = _verified_user(db, "u", jurisdiction="MA", locality_hash=cambridge_hash)
        assert verification.user_meets_locality(u, org) is False

    def test_no_user_hash_returns_false(self, db: Session):
        org = _make_org(
            db, "o",
            membership_jurisdiction="MA",
            membership_locality="Boston",
        )
        u = _verified_user(db, "u", jurisdiction="MA")  # no locality hash
        assert verification.user_meets_locality(u, org) is False

    def test_city_without_state_misconfig_acts_as_no_gate(self, db: Session):
        # Defensive default: city set without a state is ambiguous;
        # the gate fails safe to "no gate" so a misconfig doesn't
        # lock everyone out.
        org = _make_org(db, "o", membership_locality="Boston")
        u = make_user(db, "u")
        assert verification.user_meets_locality(u, org) is True


# ===========================================================================
# Independent levels — no subsumption between state and city
# ===========================================================================

class TestIndependentLevels:
    def test_city_match_alone_does_not_satisfy_state_gate(self, db: Session):
        # User is in Boston, MA. Org requires state=NY. Boston-MA
        # city match must NOT auto-satisfy the NY state gate.
        org = _make_org(
            db, "o",
            membership_floor="address_on_id",
            membership_jurisdiction="NY",
            # No city gate set, just the state.
        )
        boston_hash = verification_hashing.compute_locality_hash("Boston", "MA")
        u = _verified_user(
            db, "u",
            state="address_on_id", jurisdiction="MA",
            locality_hash=boston_hash,
        )
        # State floor fails (user is MA, gate is NY).
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            verification.check_membership_floor_for_join(u, org)
        assert exc.value.status_code == 403

    def test_state_match_alone_does_not_auto_satisfy_city_gate(self, db: Session):
        # User is in Cambridge, MA. Org requires Boston, MA. Being
        # in the right STATE doesn't auto-satisfy the CITY gate.
        org = _make_org(
            db, "o",
            membership_floor="address_on_id",
            membership_jurisdiction="MA",
            membership_locality="Boston",
        )
        cambridge_hash = verification_hashing.compute_locality_hash("Cambridge", "MA")
        u = _verified_user(
            db, "u",
            state="address_on_id", jurisdiction="MA",
            locality_hash=cambridge_hash,
        )
        # State floor passes (user is MA, gate is MA).
        verification.check_membership_floor_for_join(u, org)  # no raise
        # City floor blocks.
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            verification.check_membership_locality_for_join(u, org)
        assert exc.value.status_code == 403
        # Phase 52j J1 — old `scope="locality"` shape unified into
        # `scope="residency_scope"`. The structured-403 carries the
        # whole scope (a list) so the FE can render any combination.
        assert exc.value.detail["scope"] == "residency_scope"


# ===========================================================================
# Membership gate side-effect at join
# ===========================================================================

class TestMembershipGateSideEffect:
    def test_matching_user_passes_join(self, client: TestClient, db: Session):
        org = _make_org(
            db, "o",
            membership_floor="address_on_id",
            membership_jurisdiction="MA",
            membership_locality="Boston",
        )
        boston_hash = verification_hashing.compute_locality_hash("Boston", "MA")
        u = _verified_user(
            db, "u",
            state="address_on_id", jurisdiction="MA",
            locality_hash=boston_hash,
        )
        r = client.post(f"/api/orgs/{org.slug}/join-request", headers=_auth(u))
        assert r.status_code == 200
        m = db.query(models.OrgMembership).filter_by(
            user_id=u.id, org_id=org.id,
        ).one()
        assert m.status == "active"

    def test_mismatching_city_blocked_at_join_with_structured_403(
        self, client: TestClient, db: Session,
    ):
        org = _make_org(
            db, "o",
            membership_floor="address_on_id",
            membership_jurisdiction="MA",
            membership_locality="Boston",
        )
        cambridge_hash = verification_hashing.compute_locality_hash("Cambridge", "MA")
        u = _verified_user(
            db, "u",
            state="address_on_id", jurisdiction="MA",
            locality_hash=cambridge_hash,
        )
        r = client.post(f"/api/orgs/{org.slug}/join-request", headers=_auth(u))
        assert r.status_code == 403
        detail = r.json()["detail"]
        # Phase 52j J1 — unified residency_scope payload (an entry
        # list). The city + state are embedded inside the scope entry.
        assert detail["scope"] == "residency_scope"
        assert detail["residency_scope"] == [
            {"state": "MA", "city": "Boston"},
        ]
        # No membership row written.
        m = db.query(models.OrgMembership).filter_by(
            user_id=u.id, org_id=org.id,
        ).first()
        assert m is None

    def test_no_locality_setting_no_gate(self, client: TestClient, db: Session):
        # Mode-3 parity for the locality gate.
        org = _make_org(db, "o")
        u = make_user(db, "u")
        r = client.post(f"/api/orgs/{org.slug}/join-request", headers=_auth(u))
        assert r.status_code == 200


# ===========================================================================
# Cardinality-floor invariant on locality
# ===========================================================================

class TestCardinalityFloorInvariantLocality:
    def test_adding_city_gate_does_not_strip_seated_steward(self, db: Session):
        org = _make_org(
            db, "o",
            membership_floor="address_on_id",
            membership_jurisdiction="MA",
        )
        # Steward is in Cambridge, MA (different city from what we'll
        # gate to).
        cambridge_hash = verification_hashing.compute_locality_hash("Cambridge", "MA")
        steward = _verified_user(
            db, "steward",
            state="address_on_id", jurisdiction="MA",
            locality_hash=cambridge_hash,
        )
        make_org_membership(db, user_id=steward.id, org_id=org.id, role="steward")
        # Org admin now adds a Boston city gate.
        org.settings = dict(org.settings)
        org.settings["verification_membership_locality"] = "Boston"
        db.commit()
        # Predicate goes False for the steward.
        assert verification.user_meets_locality(steward, org) is False
        # But the seated role row is untouched (verification-status
        # change never auto-strips a role — same construction as
        # every other gate in the arc).
        m = db.query(models.OrgMembership).filter_by(
            user_id=steward.id, org_id=org.id,
        ).one()
        assert m.status == "active"
        role = db.get(models.Role, m.role_id)
        assert role.system_key == "steward"


# ===========================================================================
# Serializer guard — locality hash NEVER on UserOut
# ===========================================================================

class TestSerializerGuard:
    def test_locality_hash_not_on_userout(self):
        fields = set(schemas.UserOut.model_fields.keys())
        assert "verification_locality_hash" not in fields


# ===========================================================================
# _apply_decision — captures locality hash on a real-shape payload
# ===========================================================================

def _seed_session(db: Session, user: models.User, sid: str) -> models.VerificationSession:
    row = models.VerificationSession(
        user_id=user.id, provider_session_id=sid, status="initiated",
    )
    db.add(row); db.commit()
    return row


def _real_payload(
    session_id: str, *, city: str = "Boston", region: str = "Massachusetts",
) -> dict:
    return {
        "session_id": session_id,
        "webhook_type": "session.completed",
        "decision": {
            "session_id": session_id,
            "status": "Approved",
            "id_verifications": [{
                "status": "Approved",
                "document_number": "X9876543",
                "first_name": "Alice",
                "last_name": "Robertson",
                "date_of_birth": "1985-03-14",
                "parsed_address": {
                    "street_1": "1 Main St",
                    "city": city,
                    "region": region,
                    "postal_code": "02115",
                    "country": "US",
                },
            }],
        },
    }


class TestApplyDecisionCapturesLocalityHash:
    def test_real_shape_payload_populates_locality_hash(
        self, client: TestClient, db: Session, monkeypatch,
    ):
        monkeypatch.setattr(verification_provider, "delete_session", lambda sid: True)
        u = make_user(db, "alice")
        _seed_session(db, u, "sess_loc")
        body = json.dumps(_real_payload("sess_loc")).encode()
        r = client.post(
            "/api/webhooks/didit",
            content=body, headers={**_sign(body), "Content-Type": "application/json"},
        )
        assert r.status_code == 200
        db.refresh(u)
        assert u.verification_locality_hash is not None
        # Matches what compute_locality_hash would produce for the
        # same inputs (normalized state).
        expected = verification_hashing.compute_locality_hash("Boston", "MA")
        assert u.verification_locality_hash == expected

    def test_unparseable_address_yields_no_locality_hash(
        self, client: TestClient, db: Session, monkeypatch,
    ):
        monkeypatch.setattr(verification_provider, "delete_session", lambda sid: True)
        u = make_user(db, "alice")
        _seed_session(db, u, "sess_no_loc")
        body = json.dumps(
            _real_payload("sess_no_loc", city="", region=""),
        ).encode()
        client.post(
            "/api/webhooks/didit",
            content=body, headers={**_sign(body), "Content-Type": "application/json"},
        )
        db.refresh(u)
        assert u.verification_locality_hash is None
