"""Phase 52f + 52g — combined tests.

Per the spec verification matrices:

  * 52g age band — derive from real payload + month-aligned promote
    date + ``user_meets_age`` lazy-promotion + membership + proposal
    gates + cardinality-floor invariant + ``IDENTITY_UNIQUE`` rung
    not in state ladder + Mode-3 parity + serializer guard.
  * 52f legal name + per-org display name — captured readable +
    resolver + match predicate (first / last / full) + block-vs-flag
    enforcement + Mode-3 parity + serializer guard (legal name not on
    UserOut).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

import models
import schemas
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
    monkeypatch.setenv("VERIFICATION_HASH_PEPPER", "TEST_DUMMY_PEPPER_52FG")
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
    membership_min_age: int | None = None,
    require_name_match: str | None = None,
    name_match_action: str | None = None,
) -> models.Organization:
    settings: dict = {
        "default_deliberation_days": 1, "default_voting_days": 7,
        "default_pass_threshold": 0.5, "default_quorum_threshold": 0.0,
        "allowed_voting_methods": ["binary"],
    }
    if membership_floor:
        settings["verification_membership_floor"] = membership_floor
    if membership_min_age is not None:
        settings["verification_membership_min_age"] = membership_min_age
    if require_name_match:
        settings["verification_require_name_match"] = require_name_match
    if name_match_action:
        settings["verification_name_match_action"] = name_match_action
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
    state: str = "identity",
    legal_first: str | None = None,
    legal_last: str | None = None,
    legal_full: str | None = None,
    met_thresholds: list[int] | None = None,
    promotes_at: datetime | None = None,
) -> models.User:
    u = make_user(db, name)
    u.verification_state = state
    u.verification_provenance = "didit"
    u.verification_updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    if legal_first:
        u.legal_first_name = legal_first
    if legal_last:
        u.legal_last_name = legal_last
    if legal_full:
        u.legal_full_name = legal_full
    if met_thresholds is not None:
        u.verification_age_bands = verification.serialize_age_bands(met_thresholds)
    if promotes_at is not None:
        u.verification_age_promotes_at = promotes_at
    db.commit()
    return u


# ===========================================================================
# 52g — compute_age_bands + lazy promotion
# ===========================================================================

class TestComputeAgeBands:
    def test_adult_meets_all_thresholds_no_promotion(self):
        # A 40-year-old at any 2026 ref date meets all thresholds.
        met, promotes = verification.compute_age_bands(
            "1985-03-14", as_of=date(2026, 6, 6),
        )
        assert met == [13, 16, 18, 21]
        assert promotes is None

    def test_minor_under_18_meets_lower_and_promotes_to_18(self):
        # A 16-year-old in mid-2026 meets ≥13 + ≥16; promotes to 18
        # on first-of-birth-month + 18 years from birth.
        met, promotes = verification.compute_age_bands(
            "2010-03-14", as_of=date(2026, 6, 6),
        )
        assert met == [13, 16]
        # Turn 18 on 2028-03-14 → month-aligned 2028-03-01.
        assert promotes == datetime(2028, 3, 1)

    def test_promotes_at_is_month_aligned_not_day(self):
        # Privacy-load-bearing — never expose the exact birth day.
        # User born 2008-07-15; in 2026 they're 17 → meets 13, 16;
        # next threshold is 18 → promotes 2026-07-01 (their 18th birth
        # MONTH, first of the month, not the day).
        _, promotes = verification.compute_age_bands(
            "2008-07-15", as_of=date(2026, 6, 6),
        )
        assert promotes == datetime(2026, 7, 1)

    def test_malformed_dob_returns_empty(self):
        met, promotes = verification.compute_age_bands("garbage")
        assert met == []
        assert promotes is None

    def test_none_dob_returns_empty(self):
        met, promotes = verification.compute_age_bands(None)
        assert met == []
        assert promotes is None

    def test_serialize_deserialize_round_trip(self):
        raw = verification.serialize_age_bands([13, 18, 16])
        # Sorted on the way in.
        assert raw == "[13, 16, 18]"
        out = verification.deserialize_age_bands(raw)
        assert out == [13, 16, 18]

    def test_deserialize_handles_garbage(self):
        assert verification.deserialize_age_bands("not json") == []
        assert verification.deserialize_age_bands(None) == []
        assert verification.deserialize_age_bands("") == []


class TestUserMeetsAge:
    def test_user_with_threshold_in_met_set_passes(self, db: Session):
        u = _verified_user(db, "u", met_thresholds=[13, 16, 18])
        assert verification.user_meets_age(u, 13) is True
        assert verification.user_meets_age(u, 18) is True
        assert verification.user_meets_age(u, 21) is False

    def test_user_with_no_band_fails(self, db: Session):
        u = make_user(db, "u")
        assert verification.user_meets_age(u, 18) is False

    def test_lazy_promotion_fires_after_promotes_at(self, db: Session):
        # User currently meets [13, 16] with a promotes_at of 1 day
        # ago (the lazy-promotion month has arrived).
        u = _verified_user(
            db, "u", met_thresholds=[13, 16],
            promotes_at=datetime.utcnow() - timedelta(days=1),
        )
        # Next supported is 18 (smallest unmet from the supported
        # set). After lazy-promotion, the user meets 18.
        assert verification.user_meets_age(u, 18) is True
        # 21 is still not met (lazy-promotion only advances by ONE).
        assert verification.user_meets_age(u, 21) is False

    def test_lazy_promotion_does_not_fire_before_promotes_at(self, db: Session):
        u = _verified_user(
            db, "u", met_thresholds=[13, 16],
            promotes_at=datetime.utcnow() + timedelta(days=365),
        )
        assert verification.user_meets_age(u, 18) is False


class TestMembershipMinAgeGate:
    def test_under_age_blocked_at_join(self, client: TestClient, db: Session):
        org = _make_org(db, "o", membership_min_age=18)
        u = _verified_user(db, "u", met_thresholds=[13, 16])  # <18
        r = client.post(f"/api/orgs/{org.slug}/join-request", headers=_auth(u))
        assert r.status_code == 403
        detail = r.json()["detail"]
        assert detail["scope"] == "min_age"
        assert detail["min_age"] == 18
        # No membership row written.
        m = db.query(models.OrgMembership).filter_by(
            user_id=u.id, org_id=org.id,
        ).first()
        assert m is None

    def test_over_age_passes(self, client: TestClient, db: Session):
        org = _make_org(db, "o", membership_min_age=18)
        u = _verified_user(db, "u", met_thresholds=[13, 16, 18, 21])
        r = client.post(f"/api/orgs/{org.slug}/join-request", headers=_auth(u))
        assert r.status_code == 200
        m = db.query(models.OrgMembership).filter_by(
            user_id=u.id, org_id=org.id,
        ).one()
        assert m.status == "active"

    def test_no_setting_no_gate(self, client: TestClient, db: Session):
        # Mode-3 parity for age gate — no setting → no check.
        org = _make_org(db, "o")
        u = make_user(db, "u")  # unverified, no band
        r = client.post(f"/api/orgs/{org.slug}/join-request", headers=_auth(u))
        assert r.status_code == 200


class TestVoteMinAgeGate:
    def test_under_age_blocked_at_vote(self, client: TestClient, db: Session):
        org = _make_org(db, "o")
        u = _verified_user(db, "u", met_thresholds=[13, 16])  # <18
        make_org_membership(db, user_id=u.id, org_id=org.id, role="member")
        from datetime import datetime as _dt
        proposal = models.Proposal(
            org_id=org.id, author_id=u.id,
            title="P", body="B",
            voting_method="binary", num_winners=1,
            min_age=18, status="voting",
            voting_start=_dt.utcnow() - timedelta(days=1),
            voting_end=_dt.utcnow() + timedelta(days=1),
            pass_threshold=0.5, quorum_threshold=0,
        )
        db.add(proposal); db.commit()
        r = client.post(
            f"/api/proposals/{proposal.id}/vote",
            json={"vote_value": "yes"},
            headers=_auth(u),
        )
        assert r.status_code == 403
        assert r.json()["detail"]["scope"] == "min_age"


class TestIdentityUniqueRungNotInLadder:
    def test_identity_unique_still_in_order_for_now(self):
        # Phase 52h Stage 2 retired the rung from the MAPPER, but the
        # constant + ORDER position are intentionally kept for the
        # backlog cleanup pass. This test documents the current
        # state — IDENTITY_UNIQUE remains in ORDER. (If a future
        # cleanup removes it, drop this test.)
        assert verification.IDENTITY_UNIQUE in verification.ORDER

    def test_no_new_age_rung_added(self):
        # Age is orthogonal to the identity-strength ladder.
        expected = [
            "email_only", "identity", "identity_unique",
            "address_on_id", "residency_verified",
        ]
        assert verification.ORDER == expected


# ===========================================================================
# 52f — display_name_for resolver
# ===========================================================================

class TestDisplayNameForResolver:
    def test_override_when_set_via_membership_arg(self, db: Session):
        org = _make_org(db, "o")
        u = make_user(db, "alice")
        u.display_name = "Alice Cooper"
        db.commit()
        m = models.OrgMembership(
            user_id=u.id, org_id=org.id,
            role_id=db.query(models.Role).filter_by(
                org_id=org.id, system_key="member",
            ).one().id,
            status="active",
            display_name="Alice in the Org",
        )
        db.add(m); db.commit()
        assert verification.display_name_for(u, org, membership=m) == "Alice in the Org"

    def test_fallback_when_membership_override_is_none(self, db: Session):
        org = _make_org(db, "o")
        u = make_user(db, "alice")
        u.display_name = "Alice Cooper"
        db.commit()
        m = models.OrgMembership(
            user_id=u.id, org_id=org.id,
            role_id=db.query(models.Role).filter_by(
                org_id=org.id, system_key="member",
            ).one().id,
            status="active",
            display_name=None,
        )
        db.add(m); db.commit()
        assert verification.display_name_for(u, org, membership=m) == "Alice Cooper"

    def test_fallback_when_no_membership_passed(self, db: Session):
        u = make_user(db, "alice")
        u.display_name = "Alice Cooper"
        db.commit()
        org = _make_org(db, "o")
        assert verification.display_name_for(u, org) == "Alice Cooper"


# ===========================================================================
# 52f — display_name_matches_legal predicate
# ===========================================================================

class TestDisplayNameMatchesLegal:
    def _make_user(self, db, **kw):
        return _verified_user(db, "alice", **kw)

    def test_off_mode_always_true(self, db: Session):
        org = _make_org(db, "o")  # no match setting
        u = self._make_user(db, legal_first="Alice")
        assert verification.display_name_matches_legal("Anybody", u, org) is True

    def test_no_legal_name_on_file_returns_true(self, db: Session):
        # Unverified user — no legal name. Match doesn't apply.
        org = _make_org(db, "o", require_name_match="first")
        u = make_user(db, "unv")  # no legal name set
        assert verification.display_name_matches_legal("Anybody", u, org) is True

    def test_first_mode_match(self, db: Session):
        org = _make_org(db, "o", require_name_match="first")
        u = self._make_user(db, legal_first="Alice")
        assert verification.display_name_matches_legal("Alice Cooper", u, org) is True
        assert verification.display_name_matches_legal("alice cooper", u, org) is True

    def test_first_mode_mismatch(self, db: Session):
        org = _make_org(db, "o", require_name_match="first")
        u = self._make_user(db, legal_first="Alice")
        assert verification.display_name_matches_legal("Bob Cooper", u, org) is False

    def test_last_mode_match(self, db: Session):
        org = _make_org(db, "o", require_name_match="last")
        u = self._make_user(db, legal_last="Robertson")
        assert verification.display_name_matches_legal("Alice Robertson", u, org) is True

    def test_last_mode_mismatch(self, db: Session):
        org = _make_org(db, "o", require_name_match="last")
        u = self._make_user(db, legal_last="Robertson")
        assert verification.display_name_matches_legal("Alice Cooper", u, org) is False

    def test_full_mode_match(self, db: Session):
        org = _make_org(db, "o", require_name_match="full")
        u = self._make_user(db, legal_full="Alice Q Robertson")
        assert verification.display_name_matches_legal("Alice Q Robertson", u, org) is True
        # Case + punctuation insensitive via the shared normalizer.
        assert verification.display_name_matches_legal("alice q. robertson", u, org) is True

    def test_full_mode_mismatch(self, db: Session):
        org = _make_org(db, "o", require_name_match="full")
        u = self._make_user(db, legal_full="Alice Q Robertson")
        assert verification.display_name_matches_legal("Alice Robertson", u, org) is False

    def test_empty_candidate_fails(self, db: Session):
        org = _make_org(db, "o", require_name_match="first")
        u = self._make_user(db, legal_first="Alice")
        assert verification.display_name_matches_legal("", u, org) is False
        assert verification.display_name_matches_legal(None, u, org) is False


# ===========================================================================
# 52f — PATCH /me/display-name enforcement (block vs flag)
# ===========================================================================

class TestSetDisplayNameEnforcement:
    def _seed_member(self, db, u, org):
        make_org_membership(db, user_id=u.id, org_id=org.id, role="member")

    def test_no_match_setting_any_name_allowed(
        self, client: TestClient, db: Session,
    ):
        # Mode-3 parity for the display-name path.
        org = _make_org(db, "o")
        u = _verified_user(db, "u", legal_first="Alice")
        self._seed_member(db, u, org)
        r = client.patch(
            f"/api/orgs/{org.slug}/me/display-name",
            json={"display_name": "Anything"},
            headers=_auth(u),
        )
        assert r.status_code == 200
        m = db.query(models.OrgMembership).filter_by(
            user_id=u.id, org_id=org.id,
        ).one()
        assert m.display_name == "Anything"

    def test_block_action_rejects_non_match(
        self, client: TestClient, db: Session,
    ):
        org = _make_org(
            db, "o", require_name_match="first",
            name_match_action="block",
        )
        u = _verified_user(db, "u", legal_first="Alice")
        self._seed_member(db, u, org)
        r = client.patch(
            f"/api/orgs/{org.slug}/me/display-name",
            json={"display_name": "Bob"},
            headers=_auth(u),
        )
        assert r.status_code == 422
        assert r.json()["detail"]["error"] == "name_match_required"
        # No mutation.
        m = db.query(models.OrgMembership).filter_by(
            user_id=u.id, org_id=org.id,
        ).one()
        assert m.display_name is None

    def test_flag_action_allows_and_audits(
        self, client: TestClient, db: Session,
    ):
        org = _make_org(
            db, "o", require_name_match="first",
            name_match_action="flag",
        )
        u = _verified_user(db, "u", legal_first="Alice")
        self._seed_member(db, u, org)
        r = client.patch(
            f"/api/orgs/{org.slug}/me/display-name",
            json={"display_name": "Bob"},
            headers=_auth(u),
        )
        assert r.status_code == 200
        m = db.query(models.OrgMembership).filter_by(
            user_id=u.id, org_id=org.id,
        ).one()
        assert m.display_name == "Bob"
        audit = db.query(models.AuditLog).filter_by(
            action="org.display_name_mismatch",
        ).all()
        assert len(audit) == 1
        assert audit[0].details.get("mode") == "first"

    def test_matching_name_passes_under_block_setting(
        self, client: TestClient, db: Session,
    ):
        org = _make_org(
            db, "o", require_name_match="first",
            name_match_action="block",
        )
        u = _verified_user(db, "u", legal_first="Alice")
        self._seed_member(db, u, org)
        r = client.patch(
            f"/api/orgs/{org.slug}/me/display-name",
            json={"display_name": "Alice Cooper"},
            headers=_auth(u),
        )
        assert r.status_code == 200
        m = db.query(models.OrgMembership).filter_by(
            user_id=u.id, org_id=org.id,
        ).one()
        assert m.display_name == "Alice Cooper"

    def test_empty_string_clears_override(
        self, client: TestClient, db: Session,
    ):
        org = _make_org(db, "o")
        u = _verified_user(db, "u")
        self._seed_member(db, u, org)
        m_row = db.query(models.OrgMembership).filter_by(
            user_id=u.id, org_id=org.id,
        ).one()
        m_row.display_name = "Old"
        db.commit()
        r = client.patch(
            f"/api/orgs/{org.slug}/me/display-name",
            json={"display_name": ""},
            headers=_auth(u),
        )
        assert r.status_code == 200
        db.refresh(m_row)
        assert m_row.display_name is None


# ===========================================================================
# Member list surfaces the per-org effective display name
# ===========================================================================

class TestMemberListResolvesPerOrgDisplayName:
    def test_member_list_uses_override(
        self, client: TestClient, db: Session,
    ):
        org = _make_org(db, "o")
        u = make_user(db, "alice")
        u.display_name = "Alice Cooper"
        db.commit()
        make_org_membership(db, user_id=u.id, org_id=org.id, role="member")
        m_row = db.query(models.OrgMembership).filter_by(
            user_id=u.id, org_id=org.id,
        ).one()
        m_row.display_name = "Alice in the Org"
        db.commit()
        r = client.get(f"/api/orgs/{org.slug}/members", headers=_auth(u))
        assert r.status_code == 200
        rows = r.json()
        target = [row for row in rows if row["user_id"] == u.id][0]
        assert target["display_name"] == "Alice in the Org"


# ===========================================================================
# Cardinality-floor invariant — age config change doesn't strip role
# ===========================================================================

class TestCardinalityFloorInvariantWithAgeConfig:
    def test_raising_min_age_does_not_strip_seated_steward(self, db: Session):
        # Steward joined when no age gate. Org admin later raises
        # the min age above the steward's band. The seated role must
        # NOT be auto-stripped — same construction as the
        # verification-floor cardinality-floor test.
        org = _make_org(db, "o")  # no min-age yet
        steward = _verified_user(
            db, "steward", met_thresholds=[13, 16],  # <18
        )
        make_org_membership(db, user_id=steward.id, org_id=org.id, role="steward")
        # Now flip the setting to require 18+.
        org.settings = dict(org.settings)
        org.settings["verification_membership_min_age"] = 18
        db.commit()
        # Predicate fails for the steward.
        assert verification.user_meets_age(steward, 18) is False
        # But the seated role row is untouched.
        m = db.query(models.OrgMembership).filter_by(
            user_id=steward.id, org_id=org.id,
        ).one()
        assert m.status == "active"
        role = db.get(models.Role, m.role_id)
        assert role.system_key == "steward"


# ===========================================================================
# Serializer guards — legal name + age band NOT on UserOut
# ===========================================================================

class TestSerializerGuards:
    def test_legal_name_fields_not_on_userout(self):
        fields = set(schemas.UserOut.model_fields.keys())
        for forbidden in (
            "legal_first_name", "legal_last_name", "legal_full_name",
            "verification_age_bands", "verification_age_promotes_at",
        ):
            assert forbidden not in fields, (
                f"{forbidden!r} must NOT be on UserOut"
            )


# ===========================================================================
# _apply_decision — captures legal name + age band on a real-shape payload
# ===========================================================================

def _seed_session(db: Session, user: models.User, sid: str) -> models.VerificationSession:
    row = models.VerificationSession(
        user_id=user.id, provider_session_id=sid, status="initiated",
    )
    db.add(row); db.commit()
    return row


def _real_payload(session_id: str, *, dob: str = "1985-03-14") -> dict:
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
                "document_number": "X9876543",
                "first_name": "Alice",
                "last_name": "Robertson",
                "full_name": "Alice Q Robertson",
                "date_of_birth": dob,
            }],
            "liveness_checks": [{"status": "Approved"}],
            "face_matches": [{"status": "Approved"}],
        },
    }


class TestApplyDecisionCapturesLegalNameAndAgeBand:
    def test_legal_name_persisted_on_verification(
        self, client: TestClient, db: Session, monkeypatch,
    ):
        monkeypatch.setattr(verification_provider, "delete_session", lambda sid: True)
        u = make_user(db, "alice")
        _seed_session(db, u, "sess_lf")
        body = json.dumps(_real_payload("sess_lf")).encode()
        r = client.post(
            "/api/webhooks/didit",
            content=body, headers={**_sign(body), "Content-Type": "application/json"},
        )
        assert r.status_code == 200
        db.refresh(u)
        assert u.legal_first_name == "Alice"
        assert u.legal_last_name == "Robertson"
        assert u.legal_full_name == "Alice Q Robertson"

    def test_age_band_derived_from_dob(
        self, client: TestClient, db: Session, monkeypatch,
    ):
        monkeypatch.setattr(verification_provider, "delete_session", lambda sid: True)
        # 1985-03-14 — adult, meets every supported threshold.
        u = make_user(db, "adult")
        _seed_session(db, u, "sess_adult")
        body = json.dumps(_real_payload("sess_adult", dob="1985-03-14")).encode()
        client.post(
            "/api/webhooks/didit",
            content=body, headers={**_sign(body), "Content-Type": "application/json"},
        )
        db.refresh(u)
        assert u.verification_age_bands is not None
        bands = verification.deserialize_age_bands(u.verification_age_bands)
        assert 18 in bands
        assert 21 in bands
        # Adult — no promotion.
        assert u.verification_age_promotes_at is None

    def test_minor_gets_promotes_at_month_aligned(
        self, client: TestClient, db: Session, monkeypatch,
    ):
        monkeypatch.setattr(verification_provider, "delete_session", lambda sid: True)
        # Pick a DOB that makes the user a 16-year-old as-of run time.
        # Easier: just compute from "X years ago today" so the test
        # is time-independent.
        today = date.today()
        dob = date(today.year - 16, max(1, today.month - 1 or 1), 15)
        body = json.dumps(_real_payload(
            "sess_minor", dob=dob.isoformat(),
        )).encode()
        u = make_user(db, "minor")
        _seed_session(db, u, "sess_minor")
        client.post(
            "/api/webhooks/didit",
            content=body, headers={**_sign(body), "Content-Type": "application/json"},
        )
        db.refresh(u)
        bands = verification.deserialize_age_bands(u.verification_age_bands)
        # Meets ≥13, ≥16; not yet ≥18.
        assert 13 in bands
        assert 16 in bands
        assert 18 not in bands
        # promotes_at is set and month-aligned (day == 1).
        assert u.verification_age_promotes_at is not None
        assert u.verification_age_promotes_at.day == 1
