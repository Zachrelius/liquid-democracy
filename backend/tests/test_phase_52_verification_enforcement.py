"""Phase 52 Stage 1 — verification enforcement + delegation fork tests.

Layered per the spec verification matrix:

  * C1 — PROV_DIDIT constant exists + is in VALID_PROVENANCES.
  * C2 — Proposal.verification_floor + verification_jurisdiction
    round-trip through create + serializer.
  * C3 — every enforcement point fires under the same gate predicate:
      - Membership (join, join-request, invitation-accept).
      - Role-grant (change_member_role, transfer_stewardship,
        governance-mode revert, Phase 47 _apply_bound_role_for_assign).
      - Per-vote (cast_vote route).
    Side-effect assertions (no membership row, no role bump, no vote
    row).
  * C4 — eligible_voter_ids_for_proposal narrows the set for gated
    proposals when the org's delegation-carries-weight setting is
    False (the default). Yes-mode preserves the wider set.
  * Cardinality-floor + verification interaction: blocking a role
    bump preserves the existing role-holder; the floor invariant
    holds by construction.
  * Election-winner verification failure: title row granted, role
    bind held + audit recorded (the spec's recommended split).
  * Existing-vs-new-org parity: ungated org / ungated proposal /
    no toggle = byte-for-byte today's behavior.
  * Backdoor-drives-enforcement E2E: flip state via the Phase 51
    backdoor → gate fires → flip back → gate passes.
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


def _make_org(
    db: Session, slug: str, *,
    membership_floor: str | None = None,
    membership_jurisdiction: str | None = None,
    role_floors: dict | None = None,
    delegation_carries_weight: bool = False,
    join_policy: str = "open",
    governance_mode: str = "single_steward",
) -> models.Organization:
    settings: dict = {
        "default_deliberation_days": 1,
        "default_voting_days": 7,
        "default_pass_threshold": 0.5,
        "default_quorum_threshold": 0.0,
        "allowed_voting_methods": ["binary"],
    }
    if membership_floor is not None:
        settings["verification_membership_floor"] = membership_floor
    if membership_jurisdiction is not None:
        settings["verification_membership_jurisdiction"] = membership_jurisdiction
    if role_floors is not None:
        settings["verification_role_floors"] = role_floors
    if delegation_carries_weight:
        settings["verification_delegation_carries_weight"] = True
    org = models.Organization(
        name=slug.title(), slug=slug,
        description="", join_policy=join_policy,
        governance_mode=governance_mode,
        settings=settings,
    )
    db.add(org); db.flush()
    from role_seed import seed_default_roles_for_org
    from org_titles import seed_system_titles_for_org
    seed_default_roles_for_org(db, org.id)
    seed_system_titles_for_org(db, org.id)
    db.commit()
    return org


def _verify(user: models.User, state: str = "identity_unique", jurisdiction: str | None = None):
    """Apply a backdoor-shaped verification record to a user (the
    Phase 51 backdoor is what these tests would call in a real E2E
    flow; this helper is the in-test equivalent for ergonomic
    fixture setup)."""
    user.verification_state = state
    user.verification_jurisdiction = jurisdiction
    user.verification_provenance = "backdoor"
    user.verification_updated_at = datetime.now(timezone.utc).replace(tzinfo=None)


def _user_role_key(db: Session, org_id: str, user_id: str) -> str | None:
    m = db.query(models.OrgMembership).filter_by(
        org_id=org_id, user_id=user_id, status="active",
    ).first()
    if m is None or m.role_id is None:
        return None
    return db.get(models.Role, m.role_id).system_key


# ===========================================================================
# C1 — PROV_DIDIT
# ===========================================================================

class TestProvenanceConstants:
    def test_prov_didit_constant_exists(self):
        from verification import PROV_DIDIT, VALID_PROVENANCES
        assert PROV_DIDIT == "didit"
        assert PROV_DIDIT in VALID_PROVENANCES

    def test_prov_persona_kept_for_back_compat(self):
        from verification import PROV_PERSONA, VALID_PROVENANCES
        assert PROV_PERSONA == "persona"
        assert PROV_PERSONA in VALID_PROVENANCES


# ===========================================================================
# C2 — Proposal verification gate fields
# ===========================================================================

class TestProposalVerificationFields:
    def test_create_proposal_with_verification_floor(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org(db, "p52-cfields")
        author = make_user(db, "p52-cfields-author")
        make_org_membership(db, org_id=org.id, user_id=author.id, role="admin")
        r = client.post(
            f"/api/orgs/{org.slug}/proposals",
            headers=auth_for(author),
            json={
                "title": "Verified-only vote",
                "voting_method": "binary",
                "verification_floor": "identity",
                "verification_require_residency": False,
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["verification_floor"] == "identity"
        assert body["verification_jurisdiction"] is None
        assert body["verification_require_residency"] is False

    def test_create_proposal_jurisdiction_required_at_address_on_id(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org(db, "p52-cjur")
        author = make_user(db, "p52-cjur-author")
        make_org_membership(db, org_id=org.id, user_id=author.id, role="admin")
        r = client.post(
            f"/api/orgs/{org.slug}/proposals",
            headers=auth_for(author),
            json={
                "title": "Jurisdiction-required vote",
                "voting_method": "binary",
                "verification_floor": "address_on_id",
            },
        )
        assert r.status_code == 400
        assert "none, identity, or resident" in r.json()["detail"].lower()

    def test_unknown_floor_rejected(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org(db, "p52-cunk")
        author = make_user(db, "p52-cunk-author")
        make_org_membership(db, org_id=org.id, user_id=author.id, role="admin")
        r = client.post(
            f"/api/orgs/{org.slug}/proposals",
            headers=auth_for(author),
            json={
                "title": "Garbage", "voting_method": "binary",
                "verification_floor": "garbage",
            },
        )
        assert r.status_code == 400

    def test_email_only_floor_normalizes_to_ungated(
        self, client: TestClient, db: Session, auth_for,
    ):
        """``email_only`` as a floor is a no-op. Normalize to NULL so
        the ungated path is the canonical representation."""
        org = _make_org(db, "p52-cnoop")
        author = make_user(db, "p52-cnoop-author")
        make_org_membership(db, org_id=org.id, user_id=author.id, role="admin")
        r = client.post(
            f"/api/orgs/{org.slug}/proposals",
            headers=auth_for(author),
            json={
                "title": "No-op gate", "voting_method": "binary",
                "verification_floor": "email_only",
            },
        )
        assert r.status_code == 201
        assert r.json()["verification_floor"] is None


# ===========================================================================
# C3 — Membership floor enforcement
# ===========================================================================

class TestMembershipFloorEnforcement:
    def test_unverified_user_blocked_from_open_join(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org(
            db, "p52-mblock", membership_floor="identity_unique",
            join_policy="open",
        )
        u = make_user(db, "p52-mblock-u")
        db.commit()
        r = client.post(
            f"/api/orgs/{org.slug}/join",
            headers=auth_for(u),
        )
        assert r.status_code == 403, r.text
        detail = r.json()["detail"]
        assert detail["error"] == "verification_required"
        assert detail["floor"] == "identity_unique"
        assert detail["scope"] == "membership"
        # Side effect: no membership row.
        assert db.query(models.OrgMembership).filter_by(
            org_id=org.id, user_id=u.id,
        ).count() == 0

    def test_verified_user_passes_join(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org(
            db, "p52-mok", membership_floor="identity_unique",
            join_policy="open",
        )
        u = make_user(db, "p52-mok-u")
        _verify(u)
        db.commit()
        r = client.post(
            f"/api/orgs/{org.slug}/join",
            headers=auth_for(u),
        )
        assert r.status_code == 200, r.text
        assert db.query(models.OrgMembership).filter_by(
            org_id=org.id, user_id=u.id, status="active",
        ).count() == 1

    def test_unverified_user_blocked_from_join_request(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org(
            db, "p52-mreq", membership_floor="identity",
            join_policy="approval_required",
        )
        u = make_user(db, "p52-mreq-u")
        db.commit()
        r = client.post(
            f"/api/orgs/{org.slug}/join-request",
            headers=auth_for(u),
        )
        assert r.status_code == 403
        assert db.query(models.OrgMembership).filter_by(
            org_id=org.id, user_id=u.id,
        ).count() == 0


# ===========================================================================
# C3 — Role-grant floor enforcement
# ===========================================================================

class TestRoleGrantFloorEnforcement:
    def test_change_member_role_blocked_if_target_unverified(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org(
            db, "p52-rblock",
            role_floors={"admin": "identity_unique"},
        )
        steward = make_user(db, "p52-rblock-s")
        target = make_user(db, "p52-rblock-t")  # unverified
        make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
        make_org_membership(db, org_id=org.id, user_id=target.id, role="member")
        db.commit()
        r = client.patch(
            f"/api/orgs/{org.slug}/members/{target.id}",
            headers=auth_for(steward),
            json={"role": "admin"},
        )
        assert r.status_code == 403, r.text
        detail = r.json()["detail"]
        assert detail["error"] == "verification_required"
        assert detail["scope"] == "role"
        # Side effect: target still 'member'.
        assert _user_role_key(db, org.id, target.id) == "member"

    def test_change_member_role_passes_when_target_verified(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org(
            db, "p52-rok",
            role_floors={"admin": "identity_unique"},
        )
        steward = make_user(db, "p52-rok-s")
        target = make_user(db, "p52-rok-t")
        _verify(target)
        make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
        make_org_membership(db, org_id=org.id, user_id=target.id, role="member")
        db.commit()
        r = client.patch(
            f"/api/orgs/{org.slug}/members/{target.id}",
            headers=auth_for(steward),
            json={"role": "admin"},
        )
        assert r.status_code == 200, r.text
        assert _user_role_key(db, org.id, target.id) == "admin"

    def test_transfer_stewardship_blocked_if_target_unverified(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org(
            db, "p52-tblock",
            role_floors={"steward": "identity_unique"},
        )
        steward = make_user(db, "p52-tblock-s")
        admin = make_user(db, "p52-tblock-a")  # unverified
        make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
        make_org_membership(db, org_id=org.id, user_id=admin.id, role="admin")
        db.commit()
        r = client.post(
            f"/api/orgs/{org.slug}/transfer-stewardship",
            headers=auth_for(steward),
            json={"target_user_id": admin.id},
        )
        assert r.status_code == 403
        # Side effect: existing steward still steward (cardinality
        # floor preserved naturally).
        assert _user_role_key(db, org.id, steward.id) == "steward"
        assert _user_role_key(db, org.id, admin.id) == "admin"


# ===========================================================================
# Cardinality-floor + verification interaction
# ===========================================================================

class TestCardinalityFloorPreservedOnVerificationBlock:
    """The spec invariant: a verification block on a role-grant must
    NOT let the org slip below its governance floor. The block aborts
    BEFORE any demote happens, so the existing role-holder keeps the
    seat by construction. This is the load-bearing safety property —
    test it explicitly so a future refactor that moves the check
    fails fast."""

    def test_blocked_role_change_leaves_governor_floor_intact(
        self, db: Session, client: TestClient, auth_for,
    ):
        from governance import count_active_governors
        org = _make_org(
            db, "p52-cardf",
            role_floors={"admin": "identity_unique"},
        )
        steward = make_user(db, "p52-cardf-s")
        target = make_user(db, "p52-cardf-t")
        make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
        make_org_membership(db, org_id=org.id, user_id=target.id, role="member")
        db.commit()
        # Pre-block: 1 governor (the steward).
        assert count_active_governors(db, org) == 1
        r = client.patch(
            f"/api/orgs/{org.slug}/members/{target.id}",
            headers=auth_for(steward),
            json={"role": "admin"},
        )
        assert r.status_code == 403
        # Post-block: still 1 governor (steward unchanged).
        db.expire_all()
        org = db.get(models.Organization, org.id)
        assert count_active_governors(db, org) == 1


# ===========================================================================
# C3 — Per-vote floor enforcement
# ===========================================================================

class TestVoteFloorEnforcement:
    def _make_proposal_and_voter(
        self, db: Session, *,
        floor: str | None = None,
        verify_voter: bool = False,
    ):
        org = _make_org(db, f"p52-vote-{floor or 'none'}-{verify_voter}")
        author = make_user(db, f"p52-vote-{floor}-{verify_voter}-a")
        voter = make_user(db, f"p52-vote-{floor}-{verify_voter}-v")
        if verify_voter:
            _verify(voter)
        make_org_membership(db, org_id=org.id, user_id=author.id, role="admin")
        make_org_membership(db, org_id=org.id, user_id=voter.id, role="member")
        proposal = models.Proposal(
            title="V", body="x",
            author_id=author.id, org_id=org.id,
            voting_method="binary", num_winners=1,
            status="voting",
            voting_start=datetime.now(timezone.utc).replace(tzinfo=None),
            voting_end=datetime.now(timezone.utc).replace(tzinfo=None) + (
                datetime.now(timezone.utc) - datetime.now(timezone.utc)
            ),
            pass_threshold=0.5, quorum_threshold=0.0,
            verification_floor=floor,
        )
        # voting_end above is broken; set to 7d in the future explicitly.
        from datetime import timedelta
        proposal.voting_start = datetime.now(timezone.utc).replace(tzinfo=None)
        proposal.voting_end = proposal.voting_start + timedelta(days=7)
        db.add(proposal); db.commit()
        return org, author, voter, proposal

    def test_unverified_voter_blocked_on_gated_proposal(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, author, voter, proposal = self._make_proposal_and_voter(
            db, floor="identity_unique", verify_voter=False,
        )
        # Make sure voter's email is verified (separate gate
        # unrelated to Phase 52).
        voter.email_verified = True; db.commit()
        r = client.post(
            f"/api/proposals/{proposal.id}/vote",
            headers=auth_for(voter),
            json={"vote_value": "yes"},
        )
        assert r.status_code == 403, r.text
        detail = r.json()["detail"]
        assert detail["error"] == "verification_required"
        assert detail["scope"] == "vote"
        # Side effect: no vote row.
        assert db.query(models.Vote).filter_by(
            proposal_id=proposal.id, user_id=voter.id,
        ).count() == 0

    def test_verified_voter_passes_gated_proposal(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, author, voter, proposal = self._make_proposal_and_voter(
            db, floor="identity_unique", verify_voter=True,
        )
        voter.email_verified = True; db.commit()
        r = client.post(
            f"/api/proposals/{proposal.id}/vote",
            headers=auth_for(voter),
            json={"vote_value": "yes"},
        )
        assert r.status_code == 200, r.text
        assert db.query(models.Vote).filter_by(
            proposal_id=proposal.id, user_id=voter.id,
        ).count() == 1

    def test_ungated_proposal_unaffected(
        self, client: TestClient, db: Session, auth_for,
    ):
        """The additive-layer invariant: an ungated proposal behaves
        byte-for-byte today, regardless of voter verification state."""
        org, author, voter, proposal = self._make_proposal_and_voter(
            db, floor=None, verify_voter=False,
        )
        voter.email_verified = True; db.commit()
        r = client.post(
            f"/api/proposals/{proposal.id}/vote",
            headers=auth_for(voter),
            json={"vote_value": "yes"},
        )
        assert r.status_code == 200, r.text


# ===========================================================================
# C4 — Delegation fork (the load-bearing tally test)
# ===========================================================================

class TestDelegationForkDefaultNo:
    """When a proposal is gated AND the org's
    ``verification_delegation_carries_weight`` is False (the default
    locked decision), an unverified principal's delegated weight does
    NOT carry to their verified delegate. Implementation rides
    ``eligible_voter_ids_for_proposal``."""

    def test_unverified_principal_excluded_from_eligible_set(
        self, db: Session,
    ):
        from delegation_engine import eligible_voter_ids_for_proposal
        from datetime import timedelta
        org = _make_org(db, "p52-d-no")
        verified_voter = make_user(db, "p52-d-no-v")
        _verify(verified_voter)
        unverified_voter = make_user(db, "p52-d-no-u")
        make_org_membership(db, org_id=org.id, user_id=verified_voter.id, role="member")
        make_org_membership(db, org_id=org.id, user_id=unverified_voter.id, role="member")
        proposal = models.Proposal(
            title="Gated", body="x",
            author_id=verified_voter.id, org_id=org.id,
            voting_method="binary", num_winners=1, status="voting",
            voting_start=datetime.now(timezone.utc).replace(tzinfo=None),
            voting_end=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7),
            pass_threshold=0.5, quorum_threshold=0.0,
            verification_floor="identity_unique",
        )
        db.add(proposal); db.commit()
        eligible = eligible_voter_ids_for_proposal(db, proposal)
        assert verified_voter.id in eligible
        assert unverified_voter.id not in eligible

    def test_ungated_proposal_eligible_set_unchanged(
        self, db: Session,
    ):
        """Additive-layer invariant: ungated proposal returns the
        org's whole active membership set, regardless of verification."""
        from delegation_engine import eligible_voter_ids_for_proposal
        from datetime import timedelta
        org = _make_org(db, "p52-d-noop")
        verified_voter = make_user(db, "p52-d-noop-v")
        _verify(verified_voter)
        unverified_voter = make_user(db, "p52-d-noop-u")
        make_org_membership(db, org_id=org.id, user_id=verified_voter.id, role="member")
        make_org_membership(db, org_id=org.id, user_id=unverified_voter.id, role="member")
        proposal = models.Proposal(
            title="Ungated", body="x",
            author_id=verified_voter.id, org_id=org.id,
            voting_method="binary", num_winners=1, status="voting",
            voting_start=datetime.now(timezone.utc).replace(tzinfo=None),
            voting_end=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7),
            pass_threshold=0.5, quorum_threshold=0.0,
            verification_floor=None,
        )
        db.add(proposal); db.commit()
        eligible = eligible_voter_ids_for_proposal(db, proposal)
        assert verified_voter.id in eligible
        assert unverified_voter.id in eligible


class TestDelegationForkYesOption:
    """When the org has opted in to ``verification_delegation_
    carries_weight=True``, the tally's eligible-set is NOT narrowed —
    a verified delegate can carry an unverified principal's delegated
    weight. The C3 direct-cast block still keeps the unverified
    principal from voting directly."""

    def test_eligible_set_NOT_narrowed_when_org_opted_in(
        self, db: Session,
    ):
        from delegation_engine import eligible_voter_ids_for_proposal
        from datetime import timedelta
        org = _make_org(db, "p52-d-yes", delegation_carries_weight=True)
        verified_voter = make_user(db, "p52-d-yes-v")
        _verify(verified_voter)
        unverified_voter = make_user(db, "p52-d-yes-u")
        make_org_membership(db, org_id=org.id, user_id=verified_voter.id, role="member")
        make_org_membership(db, org_id=org.id, user_id=unverified_voter.id, role="member")
        proposal = models.Proposal(
            title="Gated yes-mode", body="x",
            author_id=verified_voter.id, org_id=org.id,
            voting_method="binary", num_winners=1, status="voting",
            voting_start=datetime.now(timezone.utc).replace(tzinfo=None),
            voting_end=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7),
            pass_threshold=0.5, quorum_threshold=0.0,
            verification_floor="identity_unique",
        )
        db.add(proposal); db.commit()
        eligible = eligible_voter_ids_for_proposal(db, proposal)
        # Both users present — the unverified user's direct ballot
        # is still blocked by C3, but their delegated weight CAN
        # carry through the tally's chain resolution.
        assert verified_voter.id in eligible
        assert unverified_voter.id in eligible


# ===========================================================================
# Transparency surface
# ===========================================================================

class TestTransparencyEndpoint:
    def test_effective_weight_reflects_floor_filter(
        self, client: TestClient, db: Session, auth_for,
    ):
        from datetime import timedelta
        org = _make_org(db, "p52-trans")
        delegate = make_user(db, "p52-trans-d")
        _verify(delegate)
        d1 = make_user(db, "p52-trans-d1"); _verify(d1)
        d2 = make_user(db, "p52-trans-d2")  # unverified
        d3 = make_user(db, "p52-trans-d3")  # unverified
        for u in (delegate, d1, d2, d3):
            make_org_membership(db, org_id=org.id, user_id=u.id, role="member")
        # All three delegate to the delegate (org-wide, no topic).
        for src in (d1, d2, d3):
            db.add(models.Delegation(
                org_id=org.id, delegator_id=src.id, delegate_id=delegate.id,
            ))
        proposal = models.Proposal(
            title="Gated", body="x",
            author_id=delegate.id, org_id=org.id,
            voting_method="binary", num_winners=1, status="voting",
            voting_start=datetime.now(timezone.utc).replace(tzinfo=None),
            voting_end=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7),
            pass_threshold=0.5, quorum_threshold=0.0,
            verification_floor="identity_unique",
        )
        db.add(proposal); db.commit()
        r = client.get(
            f"/api/proposals/{proposal.id}/verification-weight",
            headers=auth_for(delegate),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["headline_delegated_count"] == 3
        assert body["effective_delegated_count"] == 1  # only d1 (verified)
        assert body["gated_out_count"] == 2  # d2 + d3
        assert body["proposal_is_gated"] is True
        assert body["delegation_carries_unverified_weight"] is False

    def test_effective_equals_headline_when_ungated(
        self, client: TestClient, db: Session, auth_for,
    ):
        from datetime import timedelta
        org = _make_org(db, "p52-trans-ungated")
        delegate = make_user(db, "p52-tu-d")
        d1 = make_user(db, "p52-tu-d1")
        d2 = make_user(db, "p52-tu-d2")
        for u in (delegate, d1, d2):
            make_org_membership(db, org_id=org.id, user_id=u.id, role="member")
        for src in (d1, d2):
            db.add(models.Delegation(
                org_id=org.id, delegator_id=src.id, delegate_id=delegate.id,
            ))
        proposal = models.Proposal(
            title="Ungated", body="x",
            author_id=delegate.id, org_id=org.id,
            voting_method="binary", num_winners=1, status="voting",
            voting_start=datetime.now(timezone.utc).replace(tzinfo=None),
            voting_end=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7),
            pass_threshold=0.5, quorum_threshold=0.0,
        )
        db.add(proposal); db.commit()
        r = client.get(
            f"/api/proposals/{proposal.id}/verification-weight",
            headers=auth_for(delegate),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["headline_delegated_count"] == 2
        assert body["effective_delegated_count"] == 2
        assert body["gated_out_count"] == 0
        assert body["proposal_is_gated"] is False


# ===========================================================================
# Election-winner verification failure (the spec recommendation)
# ===========================================================================

class TestElectionWinnerVerificationFailure:
    """Per the spec recommendation: when a bound-role title's election
    winner fails the role floor, the title row is GRANTED but the
    role-bind is HELD with an audit event. Other failure modes still
    re-raise so finalize_election records them as failed_assignments."""

    def test_title_granted_role_bind_held_on_verification_failure(
        self, db: Session,
    ):
        from elections import _apply_election_winner
        org = _make_org(
            db, "p52-ewinfail",
            role_floors={"admin": "identity_unique"},
        )
        # Create a custom title (non-system) bound to admin.
        title = models.OrgTitle(
            org_id=org.id, name="Council Member",
            bound_role="admin", cardinality_mode="single",
            fill_method="elected", is_system=False,
        )
        db.add(title); db.commit()
        winner = make_user(db, "p52-ewinfail-w")  # unverified
        make_org_membership(db, org_id=org.id, user_id=winner.id, role="member")
        db.commit()
        # Drive the election close hook directly.
        _apply_election_winner(
            db, org, title, winner,
            actor_id=None, ip_address=None,
        )
        db.commit()
        db.expire_all()
        # Title row IS granted.
        assignment = db.query(models.OrgTitleAssignment).filter_by(
            title_id=title.id, user_id=winner.id,
        ).first()
        assert assignment is not None
        # Role bind NOT applied (winner still 'member').
        assert _user_role_key(db, org.id, winner.id) == "member"
        # Audit recorded.
        entries = db.query(models.AuditLog).filter(
            models.AuditLog.action == "election.winner_verification_required",
            models.AuditLog.target_id == title.id,
        ).all()
        assert len(entries) == 1
        assert (entries[0].details or {}).get("user_id") == winner.id


# ===========================================================================
# Existing-vs-new-org parity
# ===========================================================================

class TestExistingOrgParity:
    """Phase 48 B0 discipline. An org with NO verification settings
    behaves byte-for-byte as pre-Phase-52: every gate passes silently,
    every tally path returns today's set."""

    def test_ungated_org_join_unchanged(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org(db, "p52-parity", join_policy="open")
        u = make_user(db, "p52-parity-u")
        db.commit()
        r = client.post(
            f"/api/orgs/{org.slug}/join",
            headers=auth_for(u),
        )
        assert r.status_code == 200

    def test_ungated_org_role_change_unchanged(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org(db, "p52-parity-role")
        steward = make_user(db, "p52-parity-role-s")
        target = make_user(db, "p52-parity-role-t")
        make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
        make_org_membership(db, org_id=org.id, user_id=target.id, role="member")
        db.commit()
        r = client.patch(
            f"/api/orgs/{org.slug}/members/{target.id}",
            headers=auth_for(steward),
            json={"role": "admin"},
        )
        assert r.status_code == 200
        assert _user_role_key(db, org.id, target.id) == "admin"


# ===========================================================================
# Backdoor-drives-enforcement E2E
# ===========================================================================

class TestBackdoorDrivesEnforcement:
    """Set state via the Phase 51 backdoor → enforcement fires →
    flip state → enforcement passes. The whole chain is exercised
    end-to-end through real HTTP calls (no in-test ORM shortcuts on
    the verification record)."""

    def test_backdoor_unblocks_join(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org(
            db, "p52-bd", membership_floor="identity_unique",
            join_policy="open",
        )
        platform_admin = make_user(db, "p52-bd-admin")
        platform_admin.is_admin = True
        u = make_user(db, "p52-bd-u")
        db.commit()

        # First attempt: blocked.
        r1 = client.post(
            f"/api/orgs/{org.slug}/join",
            headers=auth_for(u),
        )
        assert r1.status_code == 403

        # Backdoor → identity_unique.
        r2 = client.post(
            f"/api/admin/users/{u.id}/verification-state",
            headers=auth_for(platform_admin),
            json={"state": "identity_unique"},
        )
        assert r2.status_code == 200, r2.text

        # Second attempt: passes.
        r3 = client.post(
            f"/api/orgs/{org.slug}/join",
            headers=auth_for(u),
        )
        assert r3.status_code == 200, r3.text
