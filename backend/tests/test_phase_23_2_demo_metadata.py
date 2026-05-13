"""Phase 23.2 — demo metadata expansion + reset autonomy tests.

B0 covers ``POST /api/demo/trigger-reset`` — the bearer-token path that
lets the Code team trigger a demo reset without admin credentials. The
endpoint reuses ``run_demo_reset_if_due(db, force=True)`` so the auth
layer is the only thing under test here; the reset pipeline itself is
already covered in test_phase_23_demo_reset.py.

B1-B3 + B7 cover the metadata expansion + STV translation + wipe-order
fix added in Phase 23.2.

Tests in this file:
  - TestB0TokenAuthMissingHeader — 401 when no Authorization header.
  - TestB0TokenAuthInvalidToken — 401 when token doesn't match.
  - TestB0TokenAuthValidTokenTriggersReset — 200 + DemoResetResult shape
    when token matches; mocks the reset call to avoid full-pipeline cost.
  - TestB0NoTokenConfigured — 503 when the env var is unset on this
    environment (defensive path; the endpoint should refuse to operate
    rather than fall through to an unauthenticated reset).
  - TestProposalTopicsField — Proposal dataclass accepts topics list.
  - TestMemberPlatformRoleField — Member dataclass accepts platform_role.
  - TestSeedPipelineCreatesProposalTopicAssociations — 2 topics → 2 rows.
  - TestSeedPipelineRejectsUnknownTopic — unknown topic logs + skips.
  - TestSeedPipelinePrimaryTopicIsFirst — relevance ordering reflects
    bible-listed order.
  - TestPlatformRoleAssignment — admin platform_role → admin Role.
  - TestPlatformRoleFallback — typo → warning + 'member' fallback.
  - TestCoalitionMembersCanCreateProposals — member role has the
    proposal.create grant only in Coalition.
  - TestSTVVoteAccepted — translated voting_method='ranked_choice' +
    num_winners>1 accepts ranked ballots.
  - TestRCVStillWorks — RCV translates to ranked_choice with
    num_winners=1; ballot accepted.
  - TestWipeDeletesProposalOptionsBeforeProposals — B7 regression: no
    FK violation on second reset.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from demo_reset_job import DemoResetResult
from main import app

import auth as auth_utils
import models


# ---------------------------------------------------------------------------
# Fixtures (mirror the pattern in test_phase_23_demo_reset.py)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def test_db():
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


@pytest.fixture(scope="function")
def client(test_db):
    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _fake_reset_result() -> DemoResetResult:
    """Construct a DemoResetResult that mimics a successful reset; used to
    short-circuit the real pipeline in the success-path token test."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return DemoResetResult(
        success=True,
        started_at=now,
        completed_at=now,
        orgs_reset=[
            "demo-cedar-hollow",
            "demo-local-4021",
            "demo-westgate-coalition",
        ],
        rows_wiped=42,
        rows_seeded=99,
        error=None,
        skipped=False,
        reason=None,
    )


# ---------------------------------------------------------------------------
# B0 — token-auth on POST /api/demo/trigger-reset
# ---------------------------------------------------------------------------


class TestB0TokenAuthMissingHeader:
    """No Authorization header at all returns 401, regardless of token
    configuration on the environment."""

    def test_missing_header_returns_401(self, client, monkeypatch):
        monkeypatch.setenv("DEMO_RESET_TRIGGER_TOKEN", "test-token-xyz")
        resp = client.post("/api/demo/trigger-reset")
        assert resp.status_code == 401
        body = resp.json()
        assert "authorization" in body["detail"].lower()

    def test_malformed_header_returns_401(self, client, monkeypatch):
        """Header present but doesn't start with 'Bearer ' — still 401."""
        monkeypatch.setenv("DEMO_RESET_TRIGGER_TOKEN", "test-token-xyz")
        resp = client.post(
            "/api/demo/trigger-reset",
            headers={"Authorization": "Basic abc"},
        )
        assert resp.status_code == 401


class TestB0TokenAuthInvalidToken:
    """Authorization header present and Bearer-shaped, but token mismatches
    the configured value — 401 with a generic 'invalid token' message that
    does NOT echo the provided value."""

    def test_wrong_token_returns_401(self, client, monkeypatch):
        monkeypatch.setenv("DEMO_RESET_TRIGGER_TOKEN", "correct-token-abc")
        wrong = "wrong-token-supplied"
        resp = client.post(
            "/api/demo/trigger-reset",
            headers={"Authorization": f"Bearer {wrong}"},
        )
        assert resp.status_code == 401
        body = resp.json()
        assert "invalid token" in body["detail"].lower()
        # Never echo the provided value back in the response — would help
        # an attacker confirm partial matches via timing+content side channel.
        assert wrong not in body["detail"]


class TestB0TokenAuthValidTokenTriggersReset:
    """Correct token + Bearer header — 200 with the DemoResetResult JSON
    shape. The actual reset is mocked so this test focuses on the auth
    plumbing + response serialization, not the reset pipeline itself."""

    def test_valid_token_triggers_reset_and_returns_audit_shape(
        self, client, monkeypatch
    ):
        monkeypatch.setenv("DEMO_RESET_TRIGGER_TOKEN", "valid-token-123")

        fake = _fake_reset_result()
        with mock.patch(
            "demo_reset_job.run_demo_reset_if_due", return_value=fake
        ) as mocked:
            resp = client.post(
                "/api/demo/trigger-reset",
                headers={"Authorization": "Bearer valid-token-123"},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Response shape matches the admin endpoint at /api/admin/demo/reset.
        assert body["success"] is True
        assert body["orgs_reset"] == [
            "demo-cedar-hollow",
            "demo-local-4021",
            "demo-westgate-coalition",
        ]
        assert body["rows_wiped"] == 42
        assert body["rows_seeded"] == 99
        assert body["error"] is None
        assert body["skipped"] is False
        assert body["reason"] is None
        # started_at / completed_at are ISO strings (not raw datetimes).
        datetime.fromisoformat(body["started_at"])
        datetime.fromisoformat(body["completed_at"])

        # The endpoint MUST call run_demo_reset_if_due with force=True and
        # NO actor_id (token auth has no human user).
        mocked.assert_called_once()
        call_kwargs = mocked.call_args.kwargs
        assert call_kwargs.get("force") is True
        # actor_id is either explicitly None or absent (default None).
        assert call_kwargs.get("actor_id") is None


class TestB0NoTokenConfigured:
    """Environment without DEMO_RESET_TRIGGER_TOKEN — endpoint refuses to
    operate (503), never falls through to an unauthenticated reset."""

    def test_unset_token_returns_503(self, client, monkeypatch):
        monkeypatch.delenv("DEMO_RESET_TRIGGER_TOKEN", raising=False)
        resp = client.post(
            "/api/demo/trigger-reset",
            headers={"Authorization": "Bearer anything"},
        )
        assert resp.status_code == 503
        body = resp.json()
        assert "not configured" in body["detail"].lower()


# ---------------------------------------------------------------------------
# B1 — dataclass schema additions
# ---------------------------------------------------------------------------


class TestProposalTopicsField:
    """Proposal dataclass accepts topics list; defaults empty."""

    def test_default_empty(self):
        from demo_content.schema import Proposal as BibleProposal
        bp = BibleProposal(
            proposal_id="P-X-01",
            title="x",
            proposer_user_id="u1",
            voting_method="binary",
            state_at_reset="draft",
            body="b",
        )
        assert bp.topics == []
        assert bp.num_winners == 1

    def test_accepts_topics_and_num_winners(self):
        from demo_content.schema import Proposal as BibleProposal
        bp = BibleProposal(
            proposal_id="P-X-02",
            title="x",
            proposer_user_id="u1",
            voting_method="stv",
            state_at_reset="draft",
            body="b",
            topics=["Budget", "Pool & Recreation"],
            num_winners=3,
        )
        assert bp.topics == ["Budget", "Pool & Recreation"]
        assert bp.num_winners == 3


class TestMemberPlatformRoleField:
    """Member dataclass accepts platform_role; defaults to 'member'."""

    def test_default_member(self):
        from demo_content.schema import Member
        m = Member(user_id="u1", display_name="U1", quick_login=False)
        assert m.platform_role == "member"

    def test_accepts_admin(self):
        from demo_content.schema import Member
        m = Member(
            user_id="u1", display_name="U1", quick_login=True,
            platform_role="admin",
        )
        assert m.platform_role == "admin"


# ---------------------------------------------------------------------------
# Helpers for B2/B3/B7 — share a tiny synthetic bible for unit-style tests
# ---------------------------------------------------------------------------


def _build_min_bible(slug: str, *, proposal_topics=None, member_platform_role="member",
                    proposal_voting_method="binary", num_winners=1,
                    options=None, candidate_statements=None):
    """Construct a minimal OrgBible with one delegate page + one proposal."""
    from demo_content.schema import (
        Member, TopicVisibility, PositionStatement, DelegatePage,
        Proposal as BibleProposal, OrgBible,
    )
    members = [
        Member(
            user_id="testmem_one", display_name="Test One",
            quick_login=True, role="Test",
            platform_role=member_platform_role,
        ),
    ]
    delegate_pages = [
        DelegatePage(
            member_user_id="testmem_one",
            page_visibility="public",
            intro="intro",
            topics=[
                TopicVisibility("Alpha", "public_accepting"),
                TopicVisibility("Beta", "public_accepting"),
                TopicVisibility("Gamma", "private"),
            ],
            position_statements=[
                PositionStatement(topic="Alpha", text="alpha pos"),
            ],
            vote_rationales=[],
        ),
    ]
    proposals = [
        BibleProposal(
            proposal_id="P-T-01",
            title="Test proposal",
            proposer_user_id="testmem_one",
            voting_method=proposal_voting_method,
            state_at_reset="voting, hour 12 of 72",
            body="body",
            topics=proposal_topics or [],
            num_winners=num_winners,
            options=options or [],
            candidate_statements=candidate_statements or {},
        ),
    ]
    return OrgBible(
        slug=slug,
        display_name=f"Bible {slug}",
        charter="c",
        tone_notes="t",
        recent_history="h",
        sub_orgs=[],
        voting_methods_used=[proposal_voting_method],
        approval_tie_resolution="",
        rcv_tie_resolution="",
        quorum_threshold_default=0.35,
        members=members,
        delegate_pages=delegate_pages,
        proposals=proposals,
        drafts=[],
        comments=[],
        notification_feeds=[],
    )


def _seed_min(db, bible, slug):
    """Wrap seed_pipeline.seed_org_from_bible for the test bibles."""
    from demo_content.seed_pipeline import seed_org_from_bible
    config = {"governance_type": "Test", "display_order": 99}
    return seed_org_from_bible(db, bible, config)


# ---------------------------------------------------------------------------
# B2.1 — ProposalTopic associations from bp.topics
# ---------------------------------------------------------------------------


class TestSeedPipelineCreatesProposalTopicAssociations:
    """Bible proposal with topics=['Alpha', 'Beta'] → 2 ProposalTopic rows
    with relevance descending (Alpha=primary)."""

    def test_two_topics_two_rows(self, test_db):
        bible = _build_min_bible(
            "test-org-pt-1", proposal_topics=["Alpha", "Beta"],
        )
        _seed_min(test_db, bible, "test-org-pt-1")
        org = test_db.query(models.Organization).filter(
            models.Organization.slug == "test-org-pt-1",
        ).one()
        proposal = test_db.query(models.Proposal).filter(
            models.Proposal.org_id == org.id,
        ).one()
        pts = test_db.query(models.ProposalTopic).filter(
            models.ProposalTopic.proposal_id == proposal.id,
        ).all()
        # Two topics → two rows
        assert len(pts) == 2
        # Primary topic gets relevance 1.0, secondary 0.8
        topic_names = []
        for pt in pts:
            t = test_db.query(models.Topic).filter(
                models.Topic.id == pt.topic_id,
            ).one()
            topic_names.append((t.description, pt.relevance))
        # description column holds the unscoped name; name has org-slug prefix
        topic_names_sorted = sorted(topic_names, key=lambda x: -x[1])
        assert topic_names_sorted[0][0] == "Alpha"
        assert topic_names_sorted[0][1] == 1.0
        assert topic_names_sorted[1][0] == "Beta"
        assert abs(topic_names_sorted[1][1] - 0.8) < 1e-6


class TestSeedPipelineRejectsUnknownTopic:
    """Unknown topic name logs + skips; valid topics on the same proposal
    still associate."""

    def test_unknown_skipped(self, test_db, caplog):
        bible = _build_min_bible(
            "test-org-pt-2",
            proposal_topics=["Alpha", "NotAnOrgTopic", "Beta"],
        )
        with caplog.at_level(logging.ERROR, logger="demo_content.seed_pipeline"):
            _seed_min(test_db, bible, "test-org-pt-2")

        org = test_db.query(models.Organization).filter(
            models.Organization.slug == "test-org-pt-2",
        ).one()
        proposal = test_db.query(models.Proposal).filter(
            models.Proposal.org_id == org.id,
        ).one()
        pts = test_db.query(models.ProposalTopic).filter(
            models.ProposalTopic.proposal_id == proposal.id,
        ).all()
        # Alpha + Beta associate; NotAnOrgTopic skipped.
        assert len(pts) == 2
        # Error logged with the unknown topic name.
        matching = [r for r in caplog.records if "NotAnOrgTopic" in r.message]
        assert matching, "expected an error log mentioning the unknown topic"


class TestSeedPipelinePrimaryTopicIsFirst:
    """Topics list order determines `relevance` ordering — first = primary."""

    def test_first_listed_is_highest_relevance(self, test_db):
        bible = _build_min_bible(
            "test-org-pt-3",
            proposal_topics=["Beta", "Alpha"],
        )
        _seed_min(test_db, bible, "test-org-pt-3")
        org = test_db.query(models.Organization).filter(
            models.Organization.slug == "test-org-pt-3",
        ).one()
        proposal = test_db.query(models.Proposal).filter(
            models.Proposal.org_id == org.id,
        ).one()
        pts = test_db.query(models.ProposalTopic).filter(
            models.ProposalTopic.proposal_id == proposal.id,
        ).all()
        # The topic with highest relevance should be the first one listed.
        primary_pt = max(pts, key=lambda pt: pt.relevance)
        primary_topic = test_db.query(models.Topic).filter(
            models.Topic.id == primary_pt.topic_id,
        ).one()
        assert primary_topic.description == "Beta"
        assert primary_pt.relevance == 1.0


# ---------------------------------------------------------------------------
# B2.2 — Member role assignment from platform_role
# ---------------------------------------------------------------------------


class TestPlatformRoleAssignment:
    """A member with platform_role='admin' gets the admin Role for that org."""

    def test_admin_membership(self, test_db):
        bible = _build_min_bible(
            "test-org-prole-admin", member_platform_role="admin",
        )
        _seed_min(test_db, bible, "test-org-prole-admin")
        org = test_db.query(models.Organization).filter(
            models.Organization.slug == "test-org-prole-admin",
        ).one()
        user = test_db.query(models.User).filter(
            models.User.username == "testmem_one",
        ).one()
        membership = test_db.query(models.OrgMembership).filter(
            models.OrgMembership.user_id == user.id,
            models.OrgMembership.org_id == org.id,
        ).one()
        role = test_db.query(models.Role).filter(
            models.Role.id == membership.role_id,
        ).one()
        assert role.system_key == "admin"


class TestPlatformRoleFallback:
    """A typo platform_role logs a warning and falls back to 'member'."""

    def test_typo_falls_back_to_member(self, test_db, caplog):
        bible = _build_min_bible(
            "test-org-prole-typo", member_platform_role="admni",
        )
        with caplog.at_level(logging.WARNING, logger="demo_content.seed_pipeline"):
            _seed_min(test_db, bible, "test-org-prole-typo")

        org = test_db.query(models.Organization).filter(
            models.Organization.slug == "test-org-prole-typo",
        ).one()
        user = test_db.query(models.User).filter(
            models.User.username == "testmem_one",
        ).one()
        membership = test_db.query(models.OrgMembership).filter(
            models.OrgMembership.user_id == user.id,
            models.OrgMembership.org_id == org.id,
        ).one()
        role = test_db.query(models.Role).filter(
            models.Role.id == membership.role_id,
        ).one()
        assert role.system_key == "member"
        # Warning logged.
        matching = [r for r in caplog.records if "admni" in r.message]
        assert matching, "expected warning log mentioning the typo'd role"


# ---------------------------------------------------------------------------
# B2.3 — Coalition member role gets proposal.create permission
# ---------------------------------------------------------------------------


class TestCoalitionMembersCanCreateProposals:
    """After a full demo reset, the Coalition member role has proposal.create
    enabled; HOA and Local member roles do not."""

    def test_only_coalition_member_role(self, test_db):
        from demo_reset_job import run_demo_reset_if_due
        result = run_demo_reset_if_due(test_db, force=True)
        assert result.success, result.error

        def _member_role_has_grant(slug: str) -> bool:
            org = test_db.query(models.Organization).filter(
                models.Organization.slug == slug,
            ).one()
            member_role = test_db.query(models.Role).filter(
                models.Role.org_id == org.id,
                models.Role.system_key == "member",
            ).one()
            grant = test_db.query(models.RolePermission).filter(
                models.RolePermission.role_id == member_role.id,
                models.RolePermission.permission_key == "proposal.create",
            ).first()
            return grant is not None and grant.enabled

        assert _member_role_has_grant("demo-westgate-coalition") is True
        assert _member_role_has_grant("demo-cedar-hollow") is False
        assert _member_role_has_grant("demo-local-4021") is False


# ---------------------------------------------------------------------------
# B3 — STV / RCV voting_method translation
# ---------------------------------------------------------------------------


def _make_member_for_org(db, org, username):
    """Create a verified member user with active OrgMembership."""
    from auth import hash_password
    user = models.User(
        username=username,
        display_name=username.title(),
        password_hash=hash_password("noop"),
        email=f"{username}@test.example",
        email_verified=True,
        is_admin=False,
    )
    db.add(user)
    db.flush()
    role = db.query(models.Role).filter(
        models.Role.org_id == org.id,
        models.Role.system_key == "member",
    ).one()
    db.add(models.OrgMembership(
        user_id=user.id, org_id=org.id, role_id=role.id, status="active",
    ))
    db.flush()
    return user


def _auth_for_user(user):
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


class TestSTVVoteAccepted:
    """STV bibles translate voting_method to 'ranked_choice' with num_winners>1
    so the cast_vote endpoint accepts ranked ballots (no 'Unsupported voting
    method: stv' rejection)."""

    def test_ranked_ballot_accepted(self, test_db, client):
        bible = _build_min_bible(
            "test-org-stv",
            proposal_topics=["Alpha"],
            proposal_voting_method="stv",
            num_winners=3,
            candidate_statements={
                "cand_a": "A",
                "cand_b": "B",
                "cand_c": "C",
            },
        )
        _seed_min(test_db, bible, "test-org-stv")
        test_db.commit()

        org = test_db.query(models.Organization).filter(
            models.Organization.slug == "test-org-stv",
        ).one()
        proposal = test_db.query(models.Proposal).filter(
            models.Proposal.org_id == org.id,
        ).one()

        # STV bibles → ranked_choice in DB; num_winners propagated.
        assert proposal.voting_method == "ranked_choice"
        assert proposal.num_winners == 3

        # Cast a ranked ballot; the endpoint must accept it.
        voter = _make_member_for_org(test_db, org, username="stvvoter")
        test_db.commit()
        opts = sorted(proposal.options, key=lambda o: o.display_order)
        ranking = [o.id for o in opts[:3]]
        resp = client.post(
            f"/api/proposals/{proposal.id}/vote",
            json={"ranking": ranking},
            headers=_auth_for_user(voter),
        )
        assert resp.status_code == 200, resp.text


class TestRCVStillWorks:
    """RCV bibles translate to 'ranked_choice' with num_winners=1; ballot
    still accepted."""

    def test_ranked_ballot_accepted_with_one_winner(self, test_db, client):
        bible = _build_min_bible(
            "test-org-rcv",
            proposal_topics=["Alpha"],
            proposal_voting_method="rcv",
            num_winners=1,
            candidate_statements={
                "cand_x": "X",
                "cand_y": "Y",
            },
        )
        _seed_min(test_db, bible, "test-org-rcv")
        test_db.commit()

        org = test_db.query(models.Organization).filter(
            models.Organization.slug == "test-org-rcv",
        ).one()
        proposal = test_db.query(models.Proposal).filter(
            models.Proposal.org_id == org.id,
        ).one()
        assert proposal.voting_method == "ranked_choice"
        assert proposal.num_winners == 1

        voter = _make_member_for_org(test_db, org, username="rcvvoter")
        test_db.commit()
        opts = sorted(proposal.options, key=lambda o: o.display_order)
        ranking = [o.id for o in opts]
        resp = client.post(
            f"/api/proposals/{proposal.id}/vote",
            json={"ranking": ranking},
            headers=_auth_for_user(voter),
        )
        assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# B7 — wipe-order regression: ProposalOption deleted before Proposal
# ---------------------------------------------------------------------------


class TestWipeDeletesProposalOptionsBeforeProposals:
    """A multi-option proposal must not raise FK violation on second reset.

    The Phase 23.1 wipe bug deleted Proposal rows before ProposalOption rows;
    Postgres rejected the Proposal delete because ProposalOption.proposal_id
    FKs to it. SQLite's FK enforcement is more permissive; this test
    primarily guards against regression of the explicit-delete ordering.
    """

    def test_two_resets_succeed_with_multi_option_proposal(self, test_db):
        from demo_reset_job import run_demo_reset_if_due

        # First reset — seeds the full bible content including multi-option
        # proposals (P-H-03 deferred maintenance, P-H-04 pool hours, P-H-07
        # President RCV, P-L-04 VP RCV, P-L-06 STV trustee, etc.).
        result1 = run_demo_reset_if_due(test_db, force=True)
        assert result1.success, result1.error

        # Confirm at least one ProposalOption row exists post-seed.
        opt_count_first = test_db.query(models.ProposalOption).count()
        assert opt_count_first > 0

        # Second reset — must wipe and reseed without FK violation.
        result2 = run_demo_reset_if_due(test_db, force=True)
        assert result2.success, result2.error
        # Result reports >0 rows_wiped (B7 sanity: the explicit
        # ProposalOption + ProposalTopic deletes contribute to this count).
        assert result2.rows_wiped > 0

        opt_count_second = test_db.query(models.ProposalOption).count()
        assert opt_count_second == opt_count_first, (
            f"option count after second reset ({opt_count_second}) "
            f"differs from after first ({opt_count_first})"
        )
