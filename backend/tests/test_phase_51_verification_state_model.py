"""Phase 51 — verification state model tests.

Layered per the spec verification matrix:

  * Pure subsumption matrix (no DB): every (current_state,
    required_floor, jurisdiction) combination — the load-bearing
    logic.
  * Org gate-config read helper: defaults-if-absent for every scope;
    valid-state sanitization; sub-org parent-chain NOT walked (phase
    constraint).
  * Existing-vs-new-org parity: pre-migration and post-migration
    orgs both resolve every verification setting to the same "not
    required" default. The no-backfill guarantee.
  * Demo seed provenance stub: demo personas carry
    ``identity_unique`` + ``demo_stub`` + jurisdiction ``DEMO``.
  * Backdoor endpoint: platform-admin only; validates state +
    jurisdiction-presence consistency; audit-logged with old + new.
  * Defaults on fresh user model: ``email_only`` / ``none``.

The (richer) ``UserOut`` surface coverage lives in
``test_phase_46a_orgout_serializer_coverage.py`` so the serializer-
gap landmine guard sits in one place.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

import models
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


@pytest.fixture()
def auth_for(db: Session):
    import auth as auth_utils

    def _headers(user: models.User) -> dict[str, str]:
        token = auth_utils.create_access_token(user.id)
        return {"Authorization": f"Bearer {token}"}
    return _headers


# ===========================================================================
# Pure subsumption matrix
# ===========================================================================

class TestSubsumptionPureMatrix:
    """Exhaustive table-test of the (current_state, required_floor,
    jurisdiction) tuple. The matrix is small and finite — enumerate
    every meaningful combination rather than spot-check."""

    def test_email_only_floor_is_satisfied_by_everyone(self):
        from verification import subsumes, ORDER
        for state in ORDER:
            assert subsumes(state, None, "email_only", None) is True

    def test_each_state_satisfies_its_own_floor(self):
        """A user at state S satisfies a floor of S (no jurisdiction)."""
        from verification import subsumes, ORDER
        for state in ORDER:
            # For address_on_id + residency_verified, no required
            # jurisdiction means jurisdiction check is skipped.
            assert subsumes(state, "CA", state, None) is True

    def test_lower_state_never_satisfies_higher_floor(self):
        from verification import subsumes, ORDER
        for i in range(len(ORDER)):
            for j in range(i + 1, len(ORDER)):
                lower = ORDER[i]
                higher = ORDER[j]
                assert subsumes(lower, "CA", higher, None) is False, (
                    f"{lower!r} should NOT satisfy {higher!r} floor"
                )

    def test_higher_state_satisfies_lower_floor(self):
        from verification import subsumes, ORDER
        for i in range(len(ORDER)):
            for j in range(0, i):
                higher = ORDER[i]
                lower = ORDER[j]
                # A higher state with a jurisdiction set satisfies a
                # lower floor that has no jurisdiction requirement
                # (jurisdiction is ignored for floors below
                # address_on_id).
                assert subsumes(higher, "CA", lower, None) is True

    def test_jurisdiction_required_exact_match(self):
        from verification import subsumes
        assert subsumes("address_on_id", "CA", "address_on_id", "CA") is True
        assert subsumes("address_on_id", "CA", "address_on_id", "NY") is False
        assert subsumes("residency_verified", "CA", "residency_verified", "CA") is True
        assert subsumes("residency_verified", "CA", "residency_verified", "NY") is False

    def test_jurisdiction_mismatch_at_higher_state_against_lower_with_jurisdiction(self):
        """``residency_verified (CA)`` does NOT satisfy
        ``address_on_id (NY)`` — jurisdiction must match exactly at
        the required-floor level."""
        from verification import subsumes
        assert subsumes("residency_verified", "CA", "address_on_id", "NY") is False
        assert subsumes("residency_verified", "CA", "address_on_id", "CA") is True

    def test_jurisdiction_ignored_below_address_on_id(self):
        """Floors below ``address_on_id`` don't carry a jurisdiction
        component; the user's jurisdiction is ignored even if set."""
        from verification import subsumes
        assert subsumes("residency_verified", "CA", "identity_unique", "NY") is True
        assert subsumes("address_on_id", "CA", "identity", "NY") is True

    def test_jurisdiction_required_but_user_has_none(self):
        from verification import subsumes
        assert subsumes("address_on_id", None, "address_on_id", "CA") is False

    def test_unknown_state_or_floor_fails_safely(self):
        from verification import subsumes
        # Unknown current state — rank -1 — fails closed.
        assert subsumes("garbage", None, "identity", None) is False
        # Unknown required floor — fails closed.
        assert subsumes("identity_unique", None, "garbage", None) is False


class TestRank:
    def test_rank_orders_states_weakest_to_strongest(self):
        from verification import rank, ORDER
        for i, state in enumerate(ORDER):
            assert rank(state) == i

    def test_rank_unknown_is_negative(self):
        from verification import rank
        assert rank("garbage") == -1


# ===========================================================================
# Org gate-config read helper
# ===========================================================================

class TestOrgVerificationFloorDefaults:
    """The defaults-if-absent guarantee. An org with no verification
    settings resolves every scope to ``("email_only", None)`` — the
    no-backfill / no-existing-org-disruption invariant."""

    def test_unset_membership_resolves_to_email_only(self, db: Session):
        from verification import get_org_verification_floor
        org = models.Organization(
            name="X", slug="x", description="", join_policy="open",
            settings={},
        )
        assert get_org_verification_floor(org, "membership") == ("email_only", None)

    def test_unset_role_resolves_to_email_only(self, db: Session):
        from verification import get_org_verification_floor
        org = models.Organization(
            name="X", slug="x", description="", join_policy="open",
            settings={},
        )
        assert get_org_verification_floor(org, "role", role_key="admin") == ("email_only", None)

    def test_null_settings_resolves_to_email_only(self, db: Session):
        """A row with ``settings=None`` (legacy / never-set) must
        still resolve cleanly — no NoneType errors."""
        from verification import get_org_verification_floor
        org = models.Organization(
            name="X", slug="x", description="", join_policy="open",
            settings=None,
        )
        assert get_org_verification_floor(org, "membership") == ("email_only", None)

    def test_valid_membership_floor_round_trips(self, db: Session):
        from verification import get_org_verification_floor
        org = models.Organization(
            name="X", slug="x", description="", join_policy="open",
            settings={
                "verification_membership_floor": "identity_unique",
            },
        )
        floor, jur = get_org_verification_floor(org, "membership")
        assert (floor, jur) == ("identity_unique", None)

    def test_valid_membership_floor_with_jurisdiction(self, db: Session):
        from verification import get_org_verification_floor
        org = models.Organization(
            name="X", slug="x", description="", join_policy="open",
            settings={
                "verification_membership_floor": "address_on_id",
                "verification_membership_jurisdiction": "CA",
            },
        )
        assert get_org_verification_floor(org, "membership") == ("address_on_id", "CA")

    def test_role_floors_lookup(self, db: Session):
        from verification import get_org_verification_floor
        org = models.Organization(
            name="X", slug="x", description="", join_policy="open",
            settings={
                "verification_role_floors": {
                    "admin": "identity_unique",
                    "steward": "address_on_id",
                },
            },
        )
        assert get_org_verification_floor(org, "role", role_key="admin") == ("identity_unique", None)
        assert get_org_verification_floor(org, "role", role_key="steward") == ("address_on_id", None)
        # Missing role → default.
        assert get_org_verification_floor(org, "role", role_key="member") == ("email_only", None)

    def test_invalid_state_falls_back_to_email_only(self, db: Session):
        """An admin who somehow PATCH'd a garbage floor value must not
        be able to disable enforcement via a typo. The read helper
        sanitizes."""
        from verification import get_org_verification_floor
        org = models.Organization(
            name="X", slug="x", description="", join_policy="open",
            settings={"verification_membership_floor": "garbage"},
        )
        assert get_org_verification_floor(org, "membership") == ("email_only", None)

    def test_unknown_scope_fails_safely(self, db: Session):
        from verification import get_org_verification_floor
        org = models.Organization(
            name="X", slug="x", description="", join_policy="open",
            settings={},
        )
        assert get_org_verification_floor(org, "garbage") == ("email_only", None)


# ===========================================================================
# Existing-vs-new-org parity (the no-backfill guarantee)
# ===========================================================================

class TestExistingOrgParity:
    """Phase 48 B0 discipline carried forward. An org "created before"
    Phase 51 (no verification keys in settings) and an org "created
    after" both resolve every verification setting to the same
    "not required" defaults. This is the load-bearing
    no-existing-org-disruption assertion."""

    def test_pre_and_post_pass_orgs_resolve_to_same_defaults(self, db: Session):
        from verification import get_org_verification_floor
        pre = models.Organization(
            name="Pre", slug="pre", description="", join_policy="open",
            settings={  # pre-Phase-51-shape: no verification keys at all.
                "default_pass_threshold": 0.5,
            },
        )
        post = models.Organization(
            name="Post", slug="post", description="", join_policy="open",
            settings={},  # fresh, post-pass shape.
        )
        for scope_args in (("membership",), ("role", "admin"), ("role", "steward")):
            scope = scope_args[0]
            kwargs = {"role_key": scope_args[1]} if len(scope_args) > 1 else {}
            assert (
                get_org_verification_floor(pre, scope, **kwargs)
                == get_org_verification_floor(post, scope, **kwargs)
                == ("email_only", None)
            )


# ===========================================================================
# Defaults on the User model
# ===========================================================================

class TestUserDefaults:
    def test_fresh_user_defaults_to_email_only(self, db: Session):
        u = make_user(db, "freshie")
        assert u.verification_state == "email_only"
        assert u.verification_provenance == "none"
        assert u.verification_jurisdiction is None
        assert u.verification_attestation_id is None
        # Phase 58 — `verification_nullifier` column dropped (migration
        # c0d1e2f3a4b5). The original assertion stayed for years as
        # belt-and-suspenders that nothing accidentally wrote it; with
        # the column gone the equivalent guard is the migration itself.
        assert u.verification_updated_at is None


# ===========================================================================
# Demo seed provenance stub
# ===========================================================================

class TestDemoSeedStub:
    def test_ensure_user_stamps_demo_verification(self, db: Session):
        from demo_content.seed_pipeline import _ensure_user
        u = _ensure_user(db, "demo_persona_1", "Demo Persona One")
        db.commit()
        assert u.verification_state == "identity_unique"
        assert u.verification_provenance == "demo_stub"
        assert u.verification_jurisdiction == "DEMO"
        assert u.verification_updated_at is not None

    def test_re_calling_ensure_user_idempotent_keeps_demo_stub(self, db: Session):
        from demo_content.seed_pipeline import _ensure_user
        u1 = _ensure_user(db, "demo_persona_2", "Demo Persona Two")
        first_updated = u1.verification_updated_at
        db.commit()
        u2 = _ensure_user(db, "demo_persona_2", "Demo Persona Two")
        # Same row, still demo_stub, updated_at unchanged (we only
        # set it if it was None).
        assert u1.id == u2.id
        assert u2.verification_provenance == "demo_stub"
        assert u2.verification_updated_at == first_updated

    def test_ensure_user_does_not_overwrite_real_persona_verification(self, db: Session):
        """Defensive — if a future codepath somehow gives a demo
        username a real Persona record, re-running the seed must NOT
        downgrade it to demo_stub."""
        from demo_content.seed_pipeline import _ensure_user
        u1 = _ensure_user(db, "demo_persona_3", "Demo Persona Three")
        u1.verification_provenance = "persona"
        u1.verification_state = "residency_verified"
        u1.verification_jurisdiction = "CA"
        db.commit()
        u2 = _ensure_user(db, "demo_persona_3", "Demo Persona Three")
        assert u2.verification_provenance == "persona"
        assert u2.verification_state == "residency_verified"
        assert u2.verification_jurisdiction == "CA"


# ===========================================================================
# Backdoor endpoint
# ===========================================================================

class TestBackdoorEndpoint:
    def test_platform_admin_can_set_verification_state(
        self, client: TestClient, db: Session, auth_for,
    ):
        platform_admin = make_user(db, "p51-admin")
        platform_admin.is_admin = True
        target = make_user(db, "p51-target")
        db.commit()
        r = client.post(
            f"/api/admin/users/{target.id}/verification-state",
            headers=auth_for(platform_admin),
            json={"state": "identity_unique"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["verification_state"] == "identity_unique"
        assert body["verification_provenance"] == "backdoor"
        assert body["verification_jurisdiction"] is None

    def test_jurisdiction_required_at_address_on_id(
        self, client: TestClient, db: Session, auth_for,
    ):
        platform_admin = make_user(db, "p51-admin-jur")
        platform_admin.is_admin = True
        target = make_user(db, "p51-target-jur")
        db.commit()
        r = client.post(
            f"/api/admin/users/{target.id}/verification-state",
            headers=auth_for(platform_admin),
            json={"state": "address_on_id"},
        )
        assert r.status_code == 400
        assert "jurisdiction" in r.json()["detail"].lower()

    def test_address_on_id_with_jurisdiction_succeeds(
        self, client: TestClient, db: Session, auth_for,
    ):
        platform_admin = make_user(db, "p51-admin-ok")
        platform_admin.is_admin = True
        target = make_user(db, "p51-target-ok")
        db.commit()
        r = client.post(
            f"/api/admin/users/{target.id}/verification-state",
            headers=auth_for(platform_admin),
            json={"state": "address_on_id", "jurisdiction": "CA"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["verification_state"] == "address_on_id"
        assert body["verification_jurisdiction"] == "CA"

    def test_jurisdiction_below_address_on_id_is_dropped(
        self, client: TestClient, db: Session, auth_for,
    ):
        """A lower-tier state doesn't carry a jurisdiction claim.
        Input is dropped so the persisted row stays consistent."""
        platform_admin = make_user(db, "p51-admin-drop")
        platform_admin.is_admin = True
        target = make_user(db, "p51-target-drop")
        db.commit()
        r = client.post(
            f"/api/admin/users/{target.id}/verification-state",
            headers=auth_for(platform_admin),
            json={"state": "identity", "jurisdiction": "CA"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["verification_state"] == "identity"
        assert body["verification_jurisdiction"] is None

    def test_non_admin_cannot_call_backdoor(
        self, client: TestClient, db: Session, auth_for,
    ):
        plain = make_user(db, "p51-plain")
        target = make_user(db, "p51-victim")
        db.commit()
        r = client.post(
            f"/api/admin/users/{target.id}/verification-state",
            headers=auth_for(plain),
            json={"state": "identity_unique"},
        )
        assert r.status_code == 403

    def test_audit_log_records_state_change(
        self, client: TestClient, db: Session, auth_for,
    ):
        platform_admin = make_user(db, "p51-audit-admin")
        platform_admin.is_admin = True
        target = make_user(db, "p51-audit-target")
        db.commit()
        client.post(
            f"/api/admin/users/{target.id}/verification-state",
            headers=auth_for(platform_admin),
            json={"state": "identity"},
        )
        entries = db.query(models.AuditLog).filter(
            models.AuditLog.action == "user.verification_state_set",
            models.AuditLog.target_id == target.id,
        ).all()
        assert len(entries) == 1
        details = entries[0].details or {}
        assert details["old_state"] == "email_only"
        assert details["new_state"] == "identity"
        assert details["new_provenance"] == "backdoor"

    def test_unknown_state_rejected(
        self, client: TestClient, db: Session, auth_for,
    ):
        platform_admin = make_user(db, "p51-admin-unk")
        platform_admin.is_admin = True
        target = make_user(db, "p51-target-unk")
        db.commit()
        r = client.post(
            f"/api/admin/users/{target.id}/verification-state",
            headers=auth_for(platform_admin),
            json={"state": "garbage"},
        )
        assert r.status_code == 400


# ===========================================================================
# Jurisdiction-required helper
# ===========================================================================

class TestJurisdictionRequiredFor:
    def test_lower_states_do_not_require_jurisdiction(self):
        from verification import jurisdiction_required_for
        assert jurisdiction_required_for("email_only") is False
        assert jurisdiction_required_for("identity") is False
        assert jurisdiction_required_for("identity_unique") is False

    def test_higher_states_require_jurisdiction(self):
        from verification import jurisdiction_required_for
        assert jurisdiction_required_for("address_on_id") is True
        assert jurisdiction_required_for("residency_verified") is True
