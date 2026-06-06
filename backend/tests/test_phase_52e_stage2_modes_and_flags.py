"""Phase 52e Stage 2 — verification modes + derived predicate +
duplicate-flag routing.

Layered per the spec verification matrix:

  * E3 — derived ``is_org_verified`` predicate (membership floor +
    no-open-high-conf-flag).
  * E3 — public-delegate gate (``submit_public_accepting`` requires
    derived verified when the org opts in).
  * E3 — cardinality-floor invariant: a verification state change
    NEVER auto-strips a seated role below the governor floor; the
    grant-time check is the only enforcement point.
  * E4 — same-org name-hash match → flag created + routed; cross-org
    match → NO flag (computed-but-ignored at the call layer).
  * E4 — high-confidence flag with ``pending_approval`` setting →
    membership routes to ``pending_approval`` regardless of
    ``join_policy``.
  * E4 — low-confidence flag NEVER auto-blocks regardless of setting.
  * E4 — admin adjudication state machine (resolved_distinct,
    resolved_same; idempotent re-resolve).
  * E4 — adjudication surfaces no PII values, no cross-org leakage,
    no platform-admin access (admin gate is org-admin).
  * E2 — three modes orthogonality (Mode 3 unset → byte-for-byte
    today's behavior).
  * Serializer guard: hashes still NEVER on UserOut.
"""
from __future__ import annotations

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
import verification_flags
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


def _auth(user: models.User) -> dict[str, str]:
    import auth as auth_utils
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _verified_user(
    db: Session, name: str, *,
    state: str = "identity",
    jurisdiction: str | None = None,
    name_dob_hash: str | None = None,
    name_dob_address_hash: str | None = None,
    doc_number_hash: str | None = None,
) -> models.User:
    u = make_user(db, name)
    u.verification_state = state
    u.verification_jurisdiction = jurisdiction
    u.verification_provenance = "didit"
    u.verification_updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    if name_dob_hash:
        u.name_dob_hash = name_dob_hash
    if name_dob_address_hash:
        u.name_dob_address_hash = name_dob_address_hash
    if doc_number_hash:
        u.doc_number_hash = doc_number_hash
        u.uniqueness_strength = "document_hash"
    db.commit()
    return u


def _make_org(
    db: Session, slug: str, *,
    join_policy: str = "open",
    is_demo: bool = False,
    membership_floor: str | None = None,
    membership_jurisdiction: str | None = None,
    high_conf_action: str | None = None,
    require_verified_delegate: bool = False,
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
    if membership_jurisdiction:
        settings["verification_membership_jurisdiction"] = membership_jurisdiction
    if high_conf_action:
        settings["verification_high_confidence_flag_action"] = high_conf_action
    if require_verified_delegate:
        settings["verification_required_for_public_delegate"] = True
    org = models.Organization(
        name=slug.title(), slug=slug, description="",
        join_policy=join_policy,
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


def _add_active(db: Session, user: models.User, org: models.Organization, role: str = "member"):
    make_org_membership(db, user_id=user.id, org_id=org.id, role=role)


# ===========================================================================
# E3 — derived is_org_verified predicate
# ===========================================================================

class TestIsOrgVerifiedPredicate:
    def test_verified_user_no_flag_returns_true(self, db: Session):
        org = _make_org(db, "o", membership_floor="identity")
        u = _verified_user(db, "alice", state="identity")
        assert verification_flags.is_org_verified(u, org, db) is True

    def test_unverified_user_returns_false(self, db: Session):
        org = _make_org(db, "o", membership_floor="identity")
        u = make_user(db, "alice")  # state=email_only
        assert verification_flags.is_org_verified(u, org, db) is False

    def test_ungated_org_returns_true_for_anyone(self, db: Session):
        # Additive-layer parity: an org with no membership floor set
        # returns True for everyone (the floor defaults to email_only
        # which subsumes nothing).
        org = _make_org(db, "o")  # no floor
        u = make_user(db, "alice")
        assert verification_flags.is_org_verified(u, org, db) is True

    def test_high_confidence_flag_invalidates(self, db: Session):
        org = _make_org(db, "o", membership_floor="identity")
        u_a = _verified_user(db, "a", state="identity", name_dob_address_hash="H1")
        u_b = _verified_user(db, "b", state="identity", name_dob_address_hash="H1")
        _add_active(db, u_a, org)
        flag = models.OrgDuplicateFlag(
            org_id=org.id, user_a_id=min(u_a.id, u_b.id),
            user_b_id=max(u_a.id, u_b.id),
            confidence="name_dob_address", status="open",
        )
        db.add(flag); db.commit()
        # Both members of the flagged pair fail the derived predicate.
        assert verification_flags.is_org_verified(u_a, org, db) is False
        assert verification_flags.is_org_verified(u_b, org, db) is False

    def test_low_confidence_flag_does_not_invalidate(self, db: Session):
        # Low-confidence flags route to review only — they do NOT
        # invalidate verified status (birthday-paradox math).
        org = _make_org(db, "o", membership_floor="identity")
        u_a = _verified_user(db, "a", state="identity")
        u_b = _verified_user(db, "b", state="identity")
        flag = models.OrgDuplicateFlag(
            org_id=org.id, user_a_id=min(u_a.id, u_b.id),
            user_b_id=max(u_a.id, u_b.id),
            confidence="name_dob", status="open",
        )
        db.add(flag); db.commit()
        assert verification_flags.is_org_verified(u_a, org, db) is True
        assert verification_flags.is_org_verified(u_b, org, db) is True

    def test_resolved_distinct_flag_does_not_invalidate(self, db: Session):
        # Once an admin marks the pair as different people, the
        # predicate clears.
        org = _make_org(db, "o", membership_floor="identity")
        u_a = _verified_user(db, "a", state="identity")
        u_b = _verified_user(db, "b", state="identity")
        flag = models.OrgDuplicateFlag(
            org_id=org.id, user_a_id=min(u_a.id, u_b.id),
            user_b_id=max(u_a.id, u_b.id),
            confidence="name_dob_address", status="resolved_distinct",
        )
        db.add(flag); db.commit()
        assert verification_flags.is_org_verified(u_a, org, db) is True
        assert verification_flags.is_org_verified(u_b, org, db) is True


# ===========================================================================
# E4 — flag detection on join (same-org only; cross-org ignored)
# ===========================================================================

class TestFlagDetectionAtJoin:
    def test_same_org_name_dob_address_match_creates_high_flag_and_routes_pending(
        self, client: TestClient, db: Session,
    ):
        # Mode-1 routing: high-confidence match + pending_approval
        # default action → membership lands ``pending_approval``
        # even on an ``open`` org.
        org = _make_org(db, "o", join_policy="open")
        incumbent = _verified_user(
            db, "incumbent", name_dob_address_hash="SHARED_NDA",
            name_dob_hash="NDh",
        )
        _add_active(db, incumbent, org)

        applicant = _verified_user(
            db, "applicant", name_dob_address_hash="SHARED_NDA",
            name_dob_hash="NDh",
        )
        r = client.post(
            f"/api/orgs/{org.slug}/join-request",
            headers=_auth(applicant),
        )
        assert r.status_code == 200
        # Membership status — pending despite open policy.
        m = db.query(models.OrgMembership).filter_by(
            user_id=applicant.id, org_id=org.id,
        ).one()
        assert m.status == "pending_approval"
        # Flag exists, high-confidence.
        flags = db.query(models.OrgDuplicateFlag).filter_by(
            org_id=org.id,
        ).all()
        assert len(flags) == 1
        assert flags[0].confidence == "name_dob_address"
        assert flags[0].status == "open"

    def test_low_confidence_match_does_not_route_pending_on_open_join(
        self, client: TestClient, db: Session,
    ):
        org = _make_org(db, "o", join_policy="open")
        incumbent = _verified_user(db, "incumbent", name_dob_hash="ND_SHARED")
        _add_active(db, incumbent, org)
        applicant = _verified_user(db, "applicant", name_dob_hash="ND_SHARED")
        r = client.post(
            f"/api/orgs/{org.slug}/join-request",
            headers=_auth(applicant),
        )
        assert r.status_code == 200
        # Active despite the low-confidence flag (review only).
        m = db.query(models.OrgMembership).filter_by(
            user_id=applicant.id, org_id=org.id,
        ).one()
        assert m.status == "active"
        # Flag was created though.
        flags = db.query(models.OrgDuplicateFlag).filter_by(
            org_id=org.id,
        ).all()
        assert len(flags) == 1
        assert flags[0].confidence == "name_dob"

    def test_high_confidence_with_review_only_setting_does_not_route_pending(
        self, client: TestClient, db: Session,
    ):
        # Org has flipped the high-confidence default to review_only.
        org = _make_org(
            db, "o", join_policy="open", high_conf_action="review_only",
        )
        incumbent = _verified_user(
            db, "i", name_dob_address_hash="NDA",
        )
        _add_active(db, incumbent, org)
        applicant = _verified_user(
            db, "a", name_dob_address_hash="NDA",
        )
        r = client.post(
            f"/api/orgs/{org.slug}/join-request",
            headers=_auth(applicant),
        )
        assert r.status_code == 200
        m = db.query(models.OrgMembership).filter_by(
            user_id=applicant.id, org_id=org.id,
        ).one()
        # Active — admin opted out of the pending routing.
        assert m.status == "active"
        # Flag still created.
        assert db.query(models.OrgDuplicateFlag).count() == 1

    def test_cross_org_match_does_not_create_flag_in_either(
        self, client: TestClient, db: Session,
    ):
        # Two orgs. Incumbent in Org A, candidate joining Org B.
        # They have matching name_dob_address hashes but never
        # share an org — no flag is created in EITHER org.
        org_a = _make_org(db, "a", join_policy="open")
        org_b = _make_org(db, "b", join_policy="open")
        incumbent = _verified_user(
            db, "i", name_dob_address_hash="CROSS_NDA",
        )
        _add_active(db, incumbent, org_a)

        candidate = _verified_user(
            db, "c", name_dob_address_hash="CROSS_NDA",
        )
        r = client.post(
            f"/api/orgs/{org_b.slug}/join-request",
            headers=_auth(candidate),
        )
        assert r.status_code == 200
        # No flag in Org A — candidate isn't even a member there.
        assert db.query(models.OrgDuplicateFlag).filter_by(
            org_id=org_a.id,
        ).count() == 0
        # No flag in Org B — incumbent isn't a member there.
        assert db.query(models.OrgDuplicateFlag).filter_by(
            org_id=org_b.id,
        ).count() == 0

    def test_idempotent_flag_does_not_dupe_on_re_evaluation(self, db: Session):
        org = _make_org(db, "o")
        u_a = _verified_user(db, "a", name_dob_address_hash="X")
        u_b = _verified_user(db, "b", name_dob_address_hash="X")
        _add_active(db, u_a, org)
        # Evaluate twice — second call must not create a duplicate row.
        verification_flags.evaluate_duplicate_flags_for_org(
            db, candidate_user=u_b, org=org,
        )
        db.commit()
        verification_flags.evaluate_duplicate_flags_for_org(
            db, candidate_user=u_b, org=org,
        )
        db.commit()
        assert db.query(models.OrgDuplicateFlag).filter_by(
            org_id=org.id,
        ).count() == 1


# ===========================================================================
# E3 — public_delegate gate
# ===========================================================================

class TestPublicDelegateGate:
    def test_unverified_user_blocked_when_org_requires_verified(
        self, client: TestClient, db: Session,
    ):
        org = _make_org(
            db, "o", membership_floor="identity",
            require_verified_delegate=True,
        )
        # Need a topic.
        topic = models.Topic(
            org_id=org.id, name="Civic", color="#abcabc",
        )
        db.add(topic); db.commit()
        # Member is NOT verified.
        member = make_user(db, "alice")
        _add_active(db, member, org)
        r = client.post(
            f"/api/orgs/{org.slug}/delegate-profile/topics/{topic.id}/submit-public-accepting",
            headers=_auth(member),
        )
        assert r.status_code == 403
        # Structured 403 detail body for FE rendering.
        detail = r.json()["detail"]
        assert detail.get("error") == "verification_required"
        assert detail.get("scope") == "role"

    def test_verified_user_passes_gate(self, client: TestClient, db: Session):
        org = _make_org(
            db, "o", membership_floor="identity",
            require_verified_delegate=True,
        )
        topic = models.Topic(
            org_id=org.id, name="Civic", color="#abcabc",
        )
        db.add(topic); db.commit()
        member = _verified_user(db, "alice", state="identity")
        _add_active(db, member, org)
        r = client.post(
            f"/api/orgs/{org.slug}/delegate-profile/topics/{topic.id}/submit-public-accepting",
            headers=_auth(member),
        )
        # Either 200 (auto-approve when no approvers) or 200 with
        # pending approval — both are non-403 (the gate passed).
        assert r.status_code == 200

    def test_org_not_requiring_verified_delegate_skips_gate(
        self, client: TestClient, db: Session,
    ):
        # Mode 3 / setting off — unverified member can still submit.
        org = _make_org(db, "o")  # no verification_required_for_public_delegate
        topic = models.Topic(
            org_id=org.id, name="Civic", color="#abcabc",
        )
        db.add(topic); db.commit()
        member = make_user(db, "alice")
        _add_active(db, member, org)
        r = client.post(
            f"/api/orgs/{org.slug}/delegate-profile/topics/{topic.id}/submit-public-accepting",
            headers=_auth(member),
        )
        assert r.status_code == 200


# ===========================================================================
# E3 — cardinality-floor invariant
# ===========================================================================

class TestCardinalityFloorInvariant:
    """A verification-state change (or a new duplicate flag raised
    later) NEVER auto-strips a seated role below the governor floor.
    The verification gate fires at GRANT time only (Phase 52 Stage 1
    + Phase 52e Stage 2 carried this design forward); seated roles
    are unaffected by later state changes."""

    def test_seated_steward_keeps_role_when_flagged_post_grant(
        self, db: Session,
    ):
        org = _make_org(db, "o", membership_floor="identity")
        steward = _verified_user(
            db, "steward", state="identity",
            name_dob_address_hash="STEWARD_HASH",
        )
        _add_active(db, steward, org, role="steward")

        # Raise a flag against the steward AFTER they're seated.
        other = _verified_user(
            db, "other", state="identity",
            name_dob_address_hash="STEWARD_HASH",
        )
        _add_active(db, other, org)
        flag = models.OrgDuplicateFlag(
            org_id=org.id,
            user_a_id=min(steward.id, other.id),
            user_b_id=max(steward.id, other.id),
            confidence="name_dob_address",
            status="open",
        )
        db.add(flag); db.commit()

        # Predicate now reads False for steward — but that's a
        # derived-status read, NOT a stored role change. The seated
        # steward role row is untouched.
        assert verification_flags.is_org_verified(steward, org, db) is False
        m = db.query(models.OrgMembership).filter_by(
            user_id=steward.id, org_id=org.id,
        ).one()
        # Status still active; role row still steward.
        assert m.status == "active"
        # The role row didn't get stripped — role_id still points at
        # the steward Role.
        role = db.get(models.Role, m.role_id)
        assert role is not None
        assert role.system_key == "steward"


# ===========================================================================
# E4 — admin adjudication endpoints
# ===========================================================================

class TestAdminAdjudication:
    def _setup_flagged_pair(self, db: Session, client: TestClient):
        org = _make_org(db, "o", join_policy="open")
        incumbent = _verified_user(
            db, "i", name_dob_address_hash="ADJUD_HASH",
        )
        _add_active(db, incumbent, org)
        applicant = _verified_user(
            db, "a", name_dob_address_hash="ADJUD_HASH",
        )
        r = client.post(
            f"/api/orgs/{org.slug}/join-request",
            headers=_auth(applicant),
        )
        assert r.status_code == 200
        # Org admin (separate user)
        admin = make_user(db, "admin")
        _add_active(db, admin, org, role="admin")
        return org, incumbent, applicant, admin

    def test_admin_lists_open_flag(self, client: TestClient, db: Session):
        org, inc, app_user, admin = self._setup_flagged_pair(db, client)
        r = client.get(
            f"/api/orgs/{org.slug}/duplicate-flags/open",
            headers=_auth(admin),
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 1
        entry = body[0]
        assert entry["confidence"] == "name_dob_address"
        assert entry["status"] == "open"
        # Member info uses display_name + username (NOT PII values).
        assert entry["member_a"]["display_name"]
        assert entry["member_b"]["display_name"]
        # Defense: no hash / name-DOB-address payload fields leaked.
        for forbidden in ("name_dob_address_hash", "name_dob_hash", "doc_number_hash",
                          "verification_nullifier", "date_of_birth", "address"):
            assert forbidden not in entry
            assert forbidden not in entry["member_a"]
            assert forbidden not in entry["member_b"]

    def test_non_admin_cannot_list_flags(
        self, client: TestClient, db: Session,
    ):
        org, inc, app_user, admin = self._setup_flagged_pair(db, client)
        regular = make_user(db, "regular")
        _add_active(db, regular, org)
        r = client.get(
            f"/api/orgs/{org.slug}/duplicate-flags/open",
            headers=_auth(regular),
        )
        assert r.status_code in (401, 403)

    def test_admin_resolves_distinct_clears_predicate(
        self, client: TestClient, db: Session,
    ):
        org, inc, app_user, admin = self._setup_flagged_pair(db, client)
        # is_org_verified is False for the applicant (flag invalidates).
        assert verification_flags.is_org_verified(app_user, org, db) is False
        # Get the flag id.
        flag = db.query(models.OrgDuplicateFlag).filter_by(org_id=org.id).one()
        r = client.post(
            f"/api/orgs/{org.slug}/duplicate-flags/{flag.id}/resolve",
            json={"resolution": "resolved_distinct"},
            headers=_auth(admin),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "resolved_distinct"
        assert body["resolved_at"] is not None
        db.refresh(app_user)
        # Predicate now passes for the applicant.
        assert verification_flags.is_org_verified(app_user, org, db) is True

    def test_admin_resolves_same_records_only(
        self, client: TestClient, db: Session,
    ):
        org, inc, app_user, admin = self._setup_flagged_pair(db, client)
        flag = db.query(models.OrgDuplicateFlag).filter_by(org_id=org.id).one()
        r = client.post(
            f"/api/orgs/{org.slug}/duplicate-flags/{flag.id}/resolve",
            json={"resolution": "resolved_same"},
            headers=_auth(admin),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "resolved_same"
        # V1 — no automatic enforcement consequence on the membership.
        m = db.query(models.OrgMembership).filter_by(
            user_id=app_user.id, org_id=org.id,
        ).one()
        # Still pending (the original flag-routes-to-pending decision)
        # — admin can now manually deny via the existing approve/deny
        # endpoints. resolved_same is a RECORD, not an action.
        assert m.status == "pending_approval"

    def test_invalid_resolution_returns_400(
        self, client: TestClient, db: Session,
    ):
        org, inc, app_user, admin = self._setup_flagged_pair(db, client)
        flag = db.query(models.OrgDuplicateFlag).filter_by(org_id=org.id).one()
        r = client.post(
            f"/api/orgs/{org.slug}/duplicate-flags/{flag.id}/resolve",
            json={"resolution": "bogus"},
            headers=_auth(admin),
        )
        assert r.status_code == 400

    def test_admin_in_other_org_cannot_resolve(
        self, client: TestClient, db: Session,
    ):
        org_a, inc, app_user, admin_a = self._setup_flagged_pair(db, client)
        org_b = _make_org(db, "b")
        admin_b = make_user(db, "admin_b")
        _add_active(db, admin_b, org_b, role="admin")
        flag = db.query(models.OrgDuplicateFlag).filter_by(org_id=org_a.id).one()
        # admin_b tries to resolve org_a's flag.
        r = client.post(
            f"/api/orgs/{org_b.slug}/duplicate-flags/{flag.id}/resolve",
            json={"resolution": "resolved_distinct"},
            headers=_auth(admin_b),
        )
        # The /api/orgs/{org_b.slug}/duplicate-flags/... route only
        # serves flags belonging to org_b → org_a's flag is "not
        # found" in org_b's scope.
        assert r.status_code == 404


# ===========================================================================
# E2 — Mode 3 (unset → byte-for-byte parity)
# ===========================================================================

class TestMode3UnsetIsAdditiveLayer:
    def test_open_join_for_ungated_org_with_no_flag_lands_active(
        self, client: TestClient, db: Session,
    ):
        org = _make_org(db, "o")  # no verification settings at all
        u = make_user(db, "alice")
        r = client.post(
            f"/api/orgs/{org.slug}/join-request",
            headers=_auth(u),
        )
        assert r.status_code == 200
        m = db.query(models.OrgMembership).filter_by(
            user_id=u.id, org_id=org.id,
        ).one()
        assert m.status == "active"
        # No flag created (no hashes on the user).
        assert db.query(models.OrgDuplicateFlag).count() == 0


# ===========================================================================
# E3 — derived value surfaced on OrgMemberOut
# ===========================================================================

class TestMemberListVerifiedBadge:
    def test_member_list_carries_is_org_verified(
        self, client: TestClient, db: Session,
    ):
        org = _make_org(db, "o", membership_floor="identity")
        verified = _verified_user(db, "verified", state="identity")
        unverified = make_user(db, "unverified")
        _add_active(db, verified, org)
        _add_active(db, unverified, org)

        r = client.get(
            f"/api/orgs/{org.slug}/members",
            headers=_auth(verified),
        )
        assert r.status_code == 200
        rows = {m["user_id"]: m for m in r.json()}
        assert rows[verified.id]["is_org_verified"] is True
        assert rows[unverified.id]["is_org_verified"] is False


# ===========================================================================
# Serializer guard — hashes still NEVER on UserOut
# ===========================================================================

class TestSerializerGuard:
    def test_hashes_not_on_userout_post_stage2(self):
        fields = set(schemas.UserOut.model_fields.keys())
        for forbidden in (
            "doc_number_hash",
            "name_dob_address_hash",
            "name_dob_hash",
            "verification_nullifier",
            "verification_attestation_id",
        ):
            assert forbidden not in fields
