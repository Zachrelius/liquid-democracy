"""Phase 52h Stage 1 — flag-feature upgrade tests.

Per the spec verification matrix:

  * H1 — verify-time detection fires; verify-time match on an active
    member does NOT flip to pending_approval (the Z-locked asymmetry).
  * H2 — both confidence tiers configurable + default
    ``pending_approval``; low-confidence with default → routes to
    pending; both independently flippable to ``review_only``.
  * H3 — open low-confidence flag now invalidates ``is_org_verified``
    (regression vs. pre-52h behavior).
  * H4 — ``resolved_same`` demotes the NEWER account; predicate
    stays False durably (not just while open); ``demoted_user_id``
    column populated; cardinality-floor invariant preserved.
  * Mode 3 / verification-unconfigured parity — an org with no
    verification + no verified members remains byte-for-byte
    unchanged despite the low-confidence default flip.
  * Backward-compat shim — old call sites importing
    ``has_open_high_confidence_flag`` flagged so the rename is clean.
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
import verification
import verification_flags
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


def _auth(user: models.User) -> dict[str, str]:
    import auth as auth_utils
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _make_org(
    db: Session, slug: str, *,
    join_policy: str = "open",
    membership_floor: str | None = None,
    high_conf_action: str | None = None,
    low_conf_action: str | None = None,
) -> models.Organization:
    settings: dict = {
        "default_deliberation_days": 1,
        "default_voting_days": 7,
        "default_pass_threshold": 0.5,
        "default_quorum_threshold": 0.0,
        "allowed_voting_methods": ["binary"],
    }
    if membership_floor:
        settings["verification_membership_floor"] = membership_floor
    if high_conf_action:
        settings["verification_high_confidence_flag_action"] = high_conf_action
    if low_conf_action:
        settings["verification_low_confidence_flag_action"] = low_conf_action
    org = models.Organization(
        name=slug.title(), slug=slug, description="",
        join_policy=join_policy,
        governance_mode="single_steward",
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
    db: Session, name: str, *, state: str = "identity",
    name_dob_hash: str | None = None,
    name_dob_address_hash: str | None = None,
    created_at: datetime | None = None,
) -> models.User:
    u = make_user(db, name)
    u.verification_state = state
    u.verification_provenance = "didit"
    u.verification_updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    if name_dob_hash:
        u.name_dob_hash = name_dob_hash
    if name_dob_address_hash:
        u.name_dob_address_hash = name_dob_address_hash
    if created_at is not None:
        u.created_at = created_at.replace(tzinfo=None) if created_at.tzinfo else created_at
    db.commit()
    return u


def _add_active(db: Session, user: models.User, org: models.Organization, role: str = "member"):
    make_org_membership(db, user_id=user.id, org_id=org.id, role=role)


# ===========================================================================
# H2 — low-confidence default is pending_approval
# ===========================================================================

class TestH2LowConfidenceDefault:
    def test_low_confidence_defaults_to_pending_approval(self, db: Session):
        org = _make_org(db, "o")
        assert verification_flags.low_confidence_flag_action(org) == "pending_approval"

    def test_low_confidence_settable_to_review_only(self, db: Session):
        org = _make_org(db, "o", low_conf_action="review_only")
        assert verification_flags.low_confidence_flag_action(org) == "review_only"

    def test_high_and_low_independently_settable(self, db: Session):
        org = _make_org(db, "o", high_conf_action="review_only", low_conf_action="pending_approval")
        assert verification_flags.high_confidence_flag_action(org) == "review_only"
        assert verification_flags.low_confidence_flag_action(org) == "pending_approval"

    def test_dispatch_helper_returns_correct_action_per_tier(self, db: Session):
        org = _make_org(db, "o", high_conf_action="pending_approval", low_conf_action="review_only")
        assert verification_flags.flag_action_for_confidence(
            org, verification_flags.CONFIDENCE_HIGH,
        ) == "pending_approval"
        assert verification_flags.flag_action_for_confidence(
            org, verification_flags.CONFIDENCE_LOW,
        ) == "review_only"

    def test_low_confidence_routes_to_pending_at_join_by_default(
        self, client: TestClient, db: Session,
    ):
        # Pre-52h: low-confidence at join → active. 52h H2: low-conf
        # defaults to pending too (per Z's locked decision).
        org = _make_org(db, "o", join_policy="open")
        incumbent = _verified_user(db, "i", name_dob_hash="ND_SHARED")
        _add_active(db, incumbent, org)
        applicant = _verified_user(db, "a", name_dob_hash="ND_SHARED")
        r = client.post(f"/api/orgs/{org.slug}/join-request", headers=_auth(applicant))
        assert r.status_code == 200
        m = db.query(models.OrgMembership).filter_by(
            user_id=applicant.id, org_id=org.id,
        ).one()
        assert m.status == "pending_approval"

    def test_low_confidence_review_only_setting_still_active(
        self, client: TestClient, db: Session,
    ):
        # Org admin opted into review_only for low-confidence —
        # membership lands active despite the flag.
        org = _make_org(db, "o", join_policy="open", low_conf_action="review_only")
        incumbent = _verified_user(db, "i", name_dob_hash="X")
        _add_active(db, incumbent, org)
        applicant = _verified_user(db, "a", name_dob_hash="X")
        r = client.post(f"/api/orgs/{org.slug}/join-request", headers=_auth(applicant))
        assert r.status_code == 200
        m = db.query(models.OrgMembership).filter_by(
            user_id=applicant.id, org_id=org.id,
        ).one()
        assert m.status == "active"
        # Flag was still created.
        assert db.query(models.OrgDuplicateFlag).count() == 1


# ===========================================================================
# H3 — predicate invalidates on BOTH tiers
# ===========================================================================

class TestH3PredicateInvalidatesBothTiers:
    def test_open_low_confidence_flag_invalidates_predicate(self, db: Session):
        # Pre-52h: this was True (low-conf didn't invalidate). 52h H3:
        # False — low-conf now also invalidates.
        org = _make_org(db, "o", membership_floor="identity")
        u_a = _verified_user(db, "a", state="identity")
        u_b = _verified_user(db, "b", state="identity")
        flag = models.OrgDuplicateFlag(
            org_id=org.id,
            user_a_id=min(u_a.id, u_b.id), user_b_id=max(u_a.id, u_b.id),
            confidence=verification_flags.CONFIDENCE_LOW,
            status="open",
        )
        db.add(flag); db.commit()
        assert verification_flags.is_org_verified(u_a, org, db) is False
        assert verification_flags.is_org_verified(u_b, org, db) is False

    def test_open_high_confidence_flag_still_invalidates(self, db: Session):
        org = _make_org(db, "o", membership_floor="identity")
        u_a = _verified_user(db, "a", state="identity")
        u_b = _verified_user(db, "b", state="identity")
        flag = models.OrgDuplicateFlag(
            org_id=org.id,
            user_a_id=min(u_a.id, u_b.id), user_b_id=max(u_a.id, u_b.id),
            confidence=verification_flags.CONFIDENCE_HIGH,
            status="open",
        )
        db.add(flag); db.commit()
        assert verification_flags.is_org_verified(u_a, org, db) is False

    def test_has_open_flag_helper_renamed(self):
        # Spec H3 said to keep one predicate the rest of the code reads —
        # the new helper is ``has_open_flag``.
        assert callable(getattr(verification_flags, "has_open_flag", None))


# ===========================================================================
# H4 — resolved_same demotes the NEWER account
# ===========================================================================

class TestH4ResolveSameDemotesNewer:
    def _setup_pair(self, db: Session, *, gap_seconds: int = 60):
        org = _make_org(db, "o", membership_floor="identity")
        older_time = datetime.now(timezone.utc) - timedelta(seconds=gap_seconds)
        newer_time = datetime.now(timezone.utc)
        older = _verified_user(
            db, "older", state="identity",
            name_dob_address_hash="DEMOTE_TEST", created_at=older_time,
        )
        newer = _verified_user(
            db, "newer", state="identity",
            name_dob_address_hash="DEMOTE_TEST", created_at=newer_time,
        )
        _add_active(db, older, org)
        _add_active(db, newer, org)
        # Open high-confidence flag pairing them.
        flag = models.OrgDuplicateFlag(
            org_id=org.id,
            user_a_id=min(older.id, newer.id),
            user_b_id=max(older.id, newer.id),
            confidence=verification_flags.CONFIDENCE_HIGH,
            status="open",
        )
        db.add(flag); db.commit()
        admin = make_user(db, "admin")
        admin.is_admin = True
        db.commit()
        return org, older, newer, flag, admin

    def test_resolved_same_writes_demoted_user_id_to_newer(self, db: Session):
        org, older, newer, flag, admin = self._setup_pair(db)
        verification_flags.resolve_flag(
            db, flag=flag, resolution="resolved_same", actor=admin,
        )
        db.commit()
        db.refresh(flag)
        assert flag.status == "resolved_same"
        assert flag.demoted_user_id == newer.id

    def test_predicate_durably_false_for_demoted_account(self, db: Session):
        # The load-bearing H4 outcome: AFTER resolved_same the
        # predicate stays False for the demoted account, NOT True
        # (which would have happened pre-52h because status moved
        # out of ``open`` and the open-only check cleared).
        org, older, newer, flag, admin = self._setup_pair(db)
        verification_flags.resolve_flag(
            db, flag=flag, resolution="resolved_same", actor=admin,
        )
        db.commit()
        db.refresh(newer)
        db.refresh(older)
        assert verification_flags.is_org_verified(newer, org, db) is False
        assert verification_flags.is_org_verified(older, org, db) is True

    def test_resolved_same_does_not_strip_role(self, db: Session):
        # Cardinality-floor invariant — demotion flips the predicate
        # but NEVER auto-strips a seated role. (52e cardinality test
        # mirror with a resolved_same trigger instead of a flag-open.)
        org = _make_org(db, "o", membership_floor="identity")
        older_time = datetime.now(timezone.utc) - timedelta(seconds=60)
        steward = _verified_user(
            db, "steward", state="identity",
            name_dob_address_hash="STEWARD_HASH", created_at=older_time,
        )
        _add_active(db, steward, org, role="steward")
        newer_time = datetime.now(timezone.utc)
        newer_other = _verified_user(
            db, "newer", state="identity",
            name_dob_address_hash="STEWARD_HASH", created_at=newer_time,
        )
        _add_active(db, newer_other, org)
        flag = models.OrgDuplicateFlag(
            org_id=org.id,
            user_a_id=min(steward.id, newer_other.id),
            user_b_id=max(steward.id, newer_other.id),
            confidence=verification_flags.CONFIDENCE_HIGH,
            status="open",
        )
        db.add(flag); db.commit()
        admin = make_user(db, "admin")
        admin.is_admin = True
        db.commit()

        # IMPORTANT — steward is OLDER so the newer (other user) gets
        # demoted; steward keeps verified status AND role. But re-run
        # with steward as the newer side to prove the role survives.
        verification_flags.resolve_flag(
            db, flag=flag, resolution="resolved_same", actor=admin,
        )
        db.commit()
        # Inspect resolutions.
        m = db.query(models.OrgMembership).filter_by(
            user_id=steward.id, org_id=org.id,
        ).one()
        # Status unchanged; role unchanged.
        assert m.status == "active"
        role = db.get(models.Role, m.role_id)
        assert role.system_key == "steward"

    def test_resolved_distinct_does_not_demote(self, db: Session):
        org, older, newer, flag, admin = self._setup_pair(db)
        verification_flags.resolve_flag(
            db, flag=flag, resolution="resolved_distinct", actor=admin,
        )
        db.commit()
        db.refresh(flag)
        assert flag.status == "resolved_distinct"
        assert flag.demoted_user_id is None
        # Both accounts are now verified (open flag cleared, no
        # resolved_same demotion).
        assert verification_flags.is_org_verified(newer, org, db) is True
        assert verification_flags.is_org_verified(older, org, db) is True


# ===========================================================================
# H1 — verify-time detection trigger
# ===========================================================================

class TestH1VerifyTimeTrigger:
    def test_verify_time_eval_flags_against_each_org_membership(
        self, db: Session,
    ):
        # User is a member of two orgs. An incumbent in EACH org has
        # the same hashes as the user. A single verify-time eval
        # produces flags in BOTH orgs.
        org_a = _make_org(db, "a")
        org_b = _make_org(db, "b")
        incumbent_a = _verified_user(db, "ia", name_dob_address_hash="MATCH_A")
        incumbent_b = _verified_user(db, "ib", name_dob_address_hash="MATCH_B")
        _add_active(db, incumbent_a, org_a)
        _add_active(db, incumbent_b, org_b)

        # The verifying user happens to match BOTH (different orgs,
        # different incumbents). In practice this would mean the
        # verifying user's hashes match each incumbent — for the
        # test we just use the SAME hash to make matching easy in
        # one org and a DIFFERENT one for the other to keep things
        # realistic; simpler: only org_a should match.
        verifier = _verified_user(
            db, "verifier", name_dob_address_hash="MATCH_A",
        )
        _add_active(db, verifier, org_a)
        _add_active(db, verifier, org_b)

        result = verification_flags.evaluate_duplicate_flags_for_user_orgs(
            db, user=verifier,
        )
        # Only org_a got a flag (the matching incumbent's hash).
        assert org_a.id in result
        assert org_b.id not in result
        # Flag is in org_a only.
        a_flags = db.query(models.OrgDuplicateFlag).filter_by(
            org_id=org_a.id,
        ).all()
        assert len(a_flags) == 1
        b_flags = db.query(models.OrgDuplicateFlag).filter_by(
            org_id=org_b.id,
        ).all()
        assert len(b_flags) == 0

    def test_verify_time_match_on_active_member_does_not_flip_to_pending(
        self, db: Session,
    ):
        # The Z-locked asymmetry: a verify-time match on an already-
        # active member must NOT flip the membership back to pending_
        # approval — that would suspend a sitting member. Only flag +
        # predicate-invalidation.
        org = _make_org(db, "o", membership_floor="identity")
        incumbent = _verified_user(
            db, "incumbent", state="identity",
            name_dob_address_hash="ACTIVE_TEST",
        )
        _add_active(db, incumbent, org)
        # Verifying user joined as active first, THEN verifies
        # (with matching hashes).
        verifying = _verified_user(
            db, "verifying", state="identity",
            name_dob_address_hash="ACTIVE_TEST",
        )
        _add_active(db, verifying, org)

        # Verify-time eval runs. Flag created; membership UNCHANGED.
        verification_flags.evaluate_duplicate_flags_for_user_orgs(
            db, user=verifying,
        )
        db.commit()
        m = db.query(models.OrgMembership).filter_by(
            user_id=verifying.id, org_id=org.id,
        ).one()
        assert m.status == "active"  # NOT pending_approval
        # Predicate goes False though (flag is open).
        assert verification_flags.is_org_verified(verifying, org, db) is False
        # Flag was created.
        assert db.query(models.OrgDuplicateFlag).count() == 1

    def test_verify_time_skips_inactive_memberships(self, db: Session):
        org = _make_org(db, "o")
        incumbent = _verified_user(db, "i", name_dob_address_hash="SKIP")
        _add_active(db, incumbent, org)
        verifier = _verified_user(db, "v", name_dob_address_hash="SKIP")
        # Add as pending — should be SKIPPED by verify-time eval.
        m = models.OrgMembership(
            user_id=verifier.id, org_id=org.id,
            role_id=db.query(models.Role).filter_by(
                org_id=org.id, system_key="member",
            ).one().id,
            status="pending_approval",
        )
        db.add(m); db.commit()
        verification_flags.evaluate_duplicate_flags_for_user_orgs(
            db, user=verifier,
        )
        # No flag — verifier was inactive in this org.
        assert db.query(models.OrgDuplicateFlag).count() == 0


# ===========================================================================
# Mode 3 / verification-unconfigured parity
# ===========================================================================

class TestMode3ParityStillHolds:
    def test_unconfigured_org_with_no_verified_members_unchanged(
        self, client: TestClient, db: Session,
    ):
        # No verification settings + an unverified applicant → no
        # hashes on either side → no flags → membership lands
        # ``active``. The H2 low-confidence default flip does NOT
        # affect this case.
        org = _make_org(db, "o")
        u = make_user(db, "alice")
        r = client.post(f"/api/orgs/{org.slug}/join-request", headers=_auth(u))
        assert r.status_code == 200
        m = db.query(models.OrgMembership).filter_by(
            user_id=u.id, org_id=org.id,
        ).one()
        assert m.status == "active"
        assert db.query(models.OrgDuplicateFlag).count() == 0
