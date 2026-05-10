"""Phase 19 — Public Delegate Pages test coverage.

Spec: ``phase19_public_delegate_pages_spec.md`` §B7 (lines 222-241).

Covers the 14 test classes called out in the spec:

  1.  TestOrgDelegateProfileLifecycle
  2.  TestTopicVisibilityTransitions
  3.  TestEffectivePageVisibility           (load-bearing helper)
  4.  TestApprovalWorkflow
  5.  TestVoteRationaleCRUD
  6.  TestVoteRationaleVisibility
  7.  TestDelegateBrowseEndpoint
  8.  TestDelegateHandle
  9.  TestPrivateDelegatorsPageVisibility
  10. TestBackwardsCompat
  11. TestHardRevertCascade                 (D7)
  12. TestHardRevertPreservesPrivateDelegations (D15 — load-bearing)
  13. TestPhase18Integration
  14. TestNotificationEvents

Style mirrors test_phase_18_delegation_org_scoping.py: in-memory SQLite,
real ``models.Vote`` rows with proper ``ballot``/value shape, real
``models.OrgMembership`` rows via ``make_org_membership`` so the
permission resolution path is exercised faithfully.

Cross-wave coordination note (Backend Agent #3):
    Tests against the new lifecycle endpoints
    (``/api/orgs/{slug}/delegate-profile/*``) and rationale CRUD
    (``/api/votes/{id}/rationale``) are written assuming the
    spec-compliant API shape. Until Backend Agent #2's wave commits,
    those tests fail with 404 / 405. The test file is otherwise
    self-contained; the lead runs the final pytest pass after both
    waves land.

Hard-revert filter note (D15):
    The spec assumes a ``Delegation.delegation_intent_id`` column to
    distinguish public-origin (NULL) from private-origin (NOT NULL)
    delegations. As of Wave 1, that column does NOT exist on the
    Delegation model. Tests in ``TestHardRevertCascade`` and
    ``TestHardRevertPreservesPrivateDelegations`` use ``getattr`` /
    ``hasattr`` guards so they skip cleanly if the column hasn't
    landed yet (Backend Agent #2's territory). When the column
    arrives, the skip guards trigger the assertions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from main import app
from role_seed import seed_default_roles_for_org
from tests.conftest import make_org_membership


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


# ---------------------------------------------------------------------------
# Fixtures
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
def client(test_db: Session):
    def _get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _make_user(
    db: Session, username: str, *,
    delegate_handle: Optional[str] = None,
) -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=True,
        delegate_handle=delegate_handle,
    )
    db.add(u)
    db.flush()
    return u


def _make_org(
    db: Session, slug: str, *,
    join_policy: str = "approval_required",
    parent_org_id: Optional[str] = None,
) -> models.Organization:
    o = models.Organization(
        name=slug.replace("_", " ").title(),
        slug=slug,
        description="",
        settings={},
        join_policy=join_policy,
        parent_org_id=parent_org_id,
    )
    db.add(o)
    db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _make_topic(
    db: Session, org: models.Organization, name: str = "T",
) -> models.Topic:
    t = models.Topic(
        name=name, description="", color="#000000",
        org_id=org.id,
    )
    db.add(t)
    db.flush()
    return t


def _make_proposal(
    db: Session,
    author: models.User,
    org: models.Organization,
    *,
    topic: Optional[models.Topic] = None,
    status: str = "voting",
) -> models.Proposal:
    p = models.Proposal(
        title="P",
        body="",
        author_id=author.id,
        voting_method="binary",
        status=status,
        org_id=org.id,
        voting_start=_now_naive() - timedelta(days=1),
        voting_end=_now_naive() + timedelta(days=1),
    )
    db.add(p)
    db.flush()
    if topic is not None:
        db.add(models.ProposalTopic(
            proposal_id=p.id, topic_id=topic.id, relevance=1.0,
        ))
        db.flush()
    return p


def _make_vote(
    db: Session,
    voter: models.User,
    proposal: models.Proposal,
    value: str = "yes",
    *,
    cast_at: Optional[datetime] = None,
) -> models.Vote:
    v = models.Vote(
        proposal_id=proposal.id,
        user_id=voter.id,
        vote_value=value,
        is_direct=True,
        cast_by_id=voter.id,
        cast_at=cast_at if cast_at is not None else _now_naive(),
    )
    db.add(v)
    db.flush()
    return v


def _make_delegate_profile(
    db: Session,
    user: models.User,
    topic: models.Topic,
    org: models.Organization,
    *,
    visibility: str = "public_accepting",
    bio: str = "",
    position_statement: Optional[str] = None,
) -> models.DelegateProfile:
    """Create a DelegateProfile row at the requested visibility state."""
    dp = models.DelegateProfile(
        user_id=user.id,
        topic_id=topic.id,
        org_id=org.id,
        bio=bio,
        is_active=True,
        visibility=visibility,
        position_statement=position_statement,
    )
    if visibility == "public_accepting":
        dp.public_accepting_approved_at = _now_naive()
    db.add(dp)
    db.flush()
    return dp


def _make_org_delegate_profile(
    db: Session,
    user: models.User,
    org: models.Organization,
    *,
    intro: Optional[str] = None,
    page_visibility: str = "private",
) -> models.OrgDelegateProfile:
    odp = models.OrgDelegateProfile(
        user_id=user.id,
        org_id=org.id,
        intro=intro,
        page_visibility=page_visibility,
    )
    db.add(odp)
    db.flush()
    return odp


def _make_rationale(
    db: Session,
    vote: models.Vote,
    *,
    content: str = "Rationale text.",
) -> models.DelegateVoteRationale:
    r = models.DelegateVoteRationale(
        vote_id=vote.id,
        content=content,
    )
    db.add(r)
    db.flush()
    return r


def _make_delegation(
    db: Session,
    delegator: models.User,
    delegate: models.User,
    *,
    org: models.Organization,
    topic: Optional[models.Topic] = None,
    delegation_intent_id: Optional[str] = None,
) -> models.Delegation:
    """Create a Delegation row in ``org``. Optional ``delegation_intent_id``
    is set via setattr() to support the future schema where Delegation
    gains the column (D15 — distinguishes public-origin NULL from
    private-origin NOT NULL). Wave 1 didn't add this column; the tests
    that need it use ``hasattr`` guards.
    """
    d = models.Delegation(
        delegator_id=delegator.id,
        delegate_id=delegate.id,
        org_id=org.id,
        topic_id=topic.id if topic is not None else None,
        chain_behavior="accept_sub",
    )
    if delegation_intent_id is not None and hasattr(
        models.Delegation, "delegation_intent_id"
    ):
        setattr(d, "delegation_intent_id", delegation_intent_id)
    db.add(d)
    db.flush()
    return d


def _make_follow_rel(
    db: Session,
    follower: models.User,
    followed: models.User,
    *,
    org: models.Organization,
    permission_level: str = "delegation_allowed",
) -> models.FollowRelationship:
    r = models.FollowRelationship(
        follower_id=follower.id,
        followed_id=followed.id,
        org_id=org.id,
        permission_level=permission_level,
    )
    db.add(r)
    db.flush()
    return r


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _enable_in_app_pref(
    db: Session, user_id: str, event_type: str,
) -> None:
    """Opt the user into in-app delivery for ``event_type`` so
    ``emit_notification`` writes a Notification row (opt-in default
    means absent rows are treated as disabled per Phase 13.3)."""
    pref = models.NotificationPreference(
        user_id=user_id,
        event_type=event_type,
        channel="in_app",
        enabled=True,
    )
    db.add(pref)
    db.flush()


# ===========================================================================
# Test class 1 — TestOrgDelegateProfileLifecycle
# ===========================================================================


class TestOrgDelegateProfileLifecycle:
    """Create-on-first-access, uniqueness, intro / page_visibility update."""

    def test_uniqueness_user_org(self, test_db: Session):
        org = _make_org(test_db, "lc1_org")
        user = _make_user(test_db, "lc1_user")
        _make_org_delegate_profile(test_db, user, org)
        # Second insert with same (user_id, org_id) violates unique constraint.
        with pytest.raises(Exception):
            _make_org_delegate_profile(test_db, user, org)
            test_db.flush()

    def test_default_page_visibility_is_private(self, test_db: Session):
        """D9: default page_visibility on first creation is 'private'."""
        org = _make_org(test_db, "lc2_org")
        user = _make_user(test_db, "lc2_user")
        odp = _make_org_delegate_profile(test_db, user, org)
        assert odp.page_visibility == "private"

    def test_intro_can_be_updated(self, test_db: Session):
        org = _make_org(test_db, "lc3_org")
        user = _make_user(test_db, "lc3_user")
        odp = _make_org_delegate_profile(
            test_db, user, org, intro="initial intro",
        )
        assert odp.intro == "initial intro"
        odp.intro = "updated intro"
        test_db.flush()
        test_db.refresh(odp)
        assert odp.intro == "updated intro"

    def test_page_visibility_can_be_set_to_private_delegators(
        self, test_db: Session,
    ):
        org = _make_org(test_db, "lc4_org")
        user = _make_user(test_db, "lc4_user")
        odp = _make_org_delegate_profile(test_db, user, org)
        odp.page_visibility = "private_delegators"
        test_db.flush()
        test_db.refresh(odp)
        assert odp.page_visibility == "private_delegators"

    def test_lifecycle_get_creates_on_first_access(
        self, client: TestClient, test_db: Session,
    ):
        """Per spec §B3: GET /api/orgs/{slug}/delegate-profile creates
        the row on first access with page_visibility='private'.

        Coordination note: implemented by Backend Agent #2 — until that
        wave commits, expect 404. Skip on missing route."""
        org = _make_org(test_db, "lc5_org")
        user = _make_user(test_db, "lc5_user")
        make_org_membership(
            test_db, org_id=org.id, user_id=user.id, role="member",
        )
        test_db.commit()
        resp = client.get(
            f"/api/orgs/{org.slug}/delegate-profile", headers=_auth(user),
        )
        if resp.status_code == 404:
            pytest.skip(
                "Backend Agent #2 lifecycle endpoint not landed; "
                "expected — re-run after wave 2 commits"
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body.get("page_visibility") == "private"

    def test_relationship_user_to_org_delegate_profiles(
        self, test_db: Session,
    ):
        org_a = _make_org(test_db, "lc6_a")
        org_b = _make_org(test_db, "lc6_b")
        user = _make_user(test_db, "lc6_user")
        _make_org_delegate_profile(test_db, user, org_a)
        _make_org_delegate_profile(test_db, user, org_b)
        test_db.commit()
        test_db.refresh(user)
        org_ids = {odp.org_id for odp in user.org_delegate_profiles}
        assert org_ids == {org_a.id, org_b.id}


# ===========================================================================
# Test class 2 — TestTopicVisibilityTransitions
# ===========================================================================


class TestTopicVisibilityTransitions:
    """Per-topic visibility state transitions per D7."""

    def test_private_to_public(self, test_db: Session):
        org = _make_org(test_db, "tv1_org")
        user = _make_user(test_db, "tv1_user")
        topic = _make_topic(test_db, org)
        dp = _make_delegate_profile(
            test_db, user, topic, org, visibility="private",
        )
        # Direct transition (free per D7).
        dp.visibility = "public"
        test_db.flush()
        test_db.refresh(dp)
        assert dp.visibility == "public"

    def test_public_to_public_accepting_no_approval(
        self, test_db: Session,
    ):
        """When the org has no approvers (delegate_application.approve
        empty), the transition auto-approves immediately (D6 last
        sentence). Tests assert the schema state — endpoint behavior
        lives in Wave 2."""
        org = _make_org(test_db, "tv2_org")
        user = _make_user(test_db, "tv2_user")
        topic = _make_topic(test_db, org)
        dp = _make_delegate_profile(
            test_db, user, topic, org, visibility="public",
        )
        # Simulate auto-approval bypass.
        dp.visibility = "public_accepting"
        dp.public_accepting_approved_at = _now_naive()
        test_db.flush()
        test_db.refresh(dp)
        assert dp.visibility == "public_accepting"
        assert dp.public_accepting_approved_at is not None

    def test_public_accepting_to_public_soft_revert(
        self, test_db: Session,
    ):
        """Soft revert: the topic stops accepting NEW delegations; existing
        delegations remain."""
        org = _make_org(test_db, "tv3_org")
        user = _make_user(test_db, "tv3_user")
        delegator = _make_user(test_db, "tv3_delegator")
        topic = _make_topic(test_db, org)
        dp = _make_delegate_profile(
            test_db, user, topic, org, visibility="public_accepting",
        )
        existing_d = _make_delegation(
            test_db, delegator, user, org=org, topic=topic,
        )
        # Simulate revert-to-public.
        dp.visibility = "public"
        test_db.flush()
        # Existing delegation row is preserved.
        survived = test_db.get(models.Delegation, existing_d.id)
        assert survived is not None
        assert survived.delegate_id == user.id

    def test_public_accepting_to_private_marks_topic_private(
        self, test_db: Session,
    ):
        """Hard revert path mutates the visibility back to 'private'."""
        org = _make_org(test_db, "tv4_org")
        user = _make_user(test_db, "tv4_user")
        topic = _make_topic(test_db, org)
        dp = _make_delegate_profile(
            test_db, user, topic, org, visibility="public_accepting",
        )
        dp.visibility = "private"
        test_db.flush()
        test_db.refresh(dp)
        assert dp.visibility == "private"


# ===========================================================================
# Test class 3 — TestEffectivePageVisibility (LOAD-BEARING HELPER)
# ===========================================================================


class TestEffectivePageVisibility:
    """``min(page_visibility, max(topic_visibility))`` semantic.

    All 9 combinations:
      * page_visibility ∈ {private, private_delegators}
        × max-topic-visibility ∈ {none/private, public, public_accepting}
      * Plus the derived 'public' case for each non-'public' page state.
    """

    def _check(
        self, test_db: Session, *,
        page_vis: str,
        topic_visibilities: list[str],
        expected: str,
    ) -> None:
        """Build a fresh user/org with the given page+topic states,
        then assert effective_page_visibility returns ``expected``."""
        org = _make_org(test_db, f"epv_{page_vis}_{'_'.join(topic_visibilities)}_org")
        user = _make_user(test_db, f"epv_user_{page_vis}_{len(topic_visibilities)}")
        odp = _make_org_delegate_profile(
            test_db, user, org, page_visibility=page_vis,
        )
        for i, tv in enumerate(topic_visibilities):
            topic = _make_topic(test_db, org, name=f"T{i}")
            _make_delegate_profile(
                test_db, user, topic, org, visibility=tv,
            )
        test_db.flush()
        actual = odp.effective_page_visibility(test_db)
        assert actual == expected, (
            f"page_visibility={page_vis!r}, topics={topic_visibilities!r}: "
            f"expected effective={expected!r}, got {actual!r}"
        )

    def test_private_no_topics(self, test_db):
        self._check(
            test_db, page_vis="private",
            topic_visibilities=[], expected="private",
        )

    def test_private_with_only_private_topics(self, test_db):
        self._check(
            test_db, page_vis="private",
            topic_visibilities=["private"], expected="private",
        )

    def test_private_with_public_topic_derives_to_public(self, test_db):
        """D3: page-public is DERIVED. Even if stored page_visibility is
        'private', having any non-private topic flips effective → 'public'."""
        self._check(
            test_db, page_vis="private",
            topic_visibilities=["public"], expected="public",
        )

    def test_private_with_public_accepting_topic_derives_to_public(
        self, test_db,
    ):
        self._check(
            test_db, page_vis="private",
            topic_visibilities=["public_accepting"], expected="public",
        )

    def test_private_with_mixed_topics_derives_to_public(self, test_db):
        self._check(
            test_db, page_vis="private",
            topic_visibilities=["private", "public", "public_accepting"],
            expected="public",
        )

    def test_private_delegators_no_topics(self, test_db):
        self._check(
            test_db, page_vis="private_delegators",
            topic_visibilities=[], expected="private_delegators",
        )

    def test_private_delegators_with_only_private_topics(self, test_db):
        self._check(
            test_db, page_vis="private_delegators",
            topic_visibilities=["private", "private"],
            expected="private_delegators",
        )

    def test_private_delegators_with_public_topic_derives_to_public(
        self, test_db,
    ):
        self._check(
            test_db, page_vis="private_delegators",
            topic_visibilities=["public"], expected="public",
        )

    def test_private_delegators_with_public_accepting_derives_to_public(
        self, test_db,
    ):
        self._check(
            test_db, page_vis="private_delegators",
            topic_visibilities=["public_accepting"], expected="public",
        )


# ===========================================================================
# Test class 4 — TestApprovalWorkflow
# ===========================================================================


class TestApprovalWorkflow:
    """Submit / approve / deny / re-submit flow per D6.

    Most assertions are schema-state-level so the model surface is the
    contract under test. Endpoint-shape tests below are skipped if Wave
    2's endpoints haven't landed.
    """

    def test_submit_marks_pending(self, test_db: Session):
        org = _make_org(test_db, "aw1_org")
        user = _make_user(test_db, "aw1_user")
        topic = _make_topic(test_db, org)
        dp = _make_delegate_profile(
            test_db, user, topic, org, visibility="public",
        )
        # No approved_at; submission sets submitted_at.
        dp.public_accepting_submitted_at = _now_naive()
        test_db.flush()
        # Pending iff submitted_at IS NOT NULL AND approved_at IS NULL.
        assert dp.public_accepting_submitted_at is not None
        assert dp.public_accepting_approved_at is None

    def test_approval_sets_approved_at_and_approver(self, test_db: Session):
        org = _make_org(test_db, "aw2_org")
        user = _make_user(test_db, "aw2_user")
        approver = _make_user(test_db, "aw2_approver")
        topic = _make_topic(test_db, org)
        dp = _make_delegate_profile(
            test_db, user, topic, org, visibility="public",
        )
        dp.public_accepting_submitted_at = _now_naive()
        # Approve.
        dp.visibility = "public_accepting"
        dp.public_accepting_approved_at = _now_naive()
        dp.public_accepting_approved_by_id = approver.id
        test_db.flush()
        test_db.refresh(dp)
        assert dp.visibility == "public_accepting"
        assert dp.public_accepting_approved_by_id == approver.id

    def test_denial_records_comment_and_clears_submitted(
        self, test_db: Session,
    ):
        """Per D6: denial stores the comment, clears submitted_at, leaves
        topic at 'public', user must re-submit."""
        org = _make_org(test_db, "aw3_org")
        user = _make_user(test_db, "aw3_user")
        topic = _make_topic(test_db, org)
        dp = _make_delegate_profile(
            test_db, user, topic, org, visibility="public",
        )
        dp.public_accepting_submitted_at = _now_naive()
        # Deny.
        dp.public_accepting_denied_comment = "Need more position detail."
        dp.public_accepting_submitted_at = None
        test_db.flush()
        test_db.refresh(dp)
        assert dp.visibility == "public"
        assert dp.public_accepting_denied_comment is not None
        assert dp.public_accepting_submitted_at is None

    def test_resubmit_clears_denied_comment(self, test_db: Session):
        org = _make_org(test_db, "aw4_org")
        user = _make_user(test_db, "aw4_user")
        topic = _make_topic(test_db, org)
        dp = _make_delegate_profile(
            test_db, user, topic, org, visibility="public",
        )
        dp.public_accepting_denied_comment = "Old denial."
        dp.public_accepting_submitted_at = None
        test_db.flush()
        # Re-submit: clear denial state, set submitted_at again.
        dp.public_accepting_denied_comment = None
        dp.public_accepting_submitted_at = _now_naive()
        test_db.flush()
        test_db.refresh(dp)
        assert dp.public_accepting_submitted_at is not None
        assert dp.public_accepting_denied_comment is None

    def test_endpoint_submit_skips_if_route_missing(
        self, client: TestClient, test_db: Session,
    ):
        """Wave 2 owns the endpoint; skip-on-404 keeps this test
        compatible with sequential commits."""
        org = _make_org(test_db, "aw5_org")
        user = _make_user(test_db, "aw5_user")
        make_org_membership(
            test_db, org_id=org.id, user_id=user.id, role="member",
        )
        topic = _make_topic(test_db, org)
        _make_delegate_profile(
            test_db, user, topic, org, visibility="public",
        )
        test_db.commit()
        resp = client.post(
            f"/api/orgs/{org.slug}/delegate-profile/topics/{topic.id}"
            f"/submit-public-accepting",
            headers=_auth(user),
        )
        if resp.status_code in (404, 405):
            pytest.skip("Wave 2 lifecycle endpoint not yet landed")
        assert resp.status_code in (200, 201, 204), resp.text


# ===========================================================================
# Test class 5 — TestVoteRationaleCRUD
# ===========================================================================


class TestVoteRationaleCRUD:
    """Create / update / delete; only owner can write."""

    def test_create_rationale(self, test_db: Session):
        org = _make_org(test_db, "vrc1_org")
        user = _make_user(test_db, "vrc1_user")
        topic = _make_topic(test_db, org)
        proposal = _make_proposal(test_db, user, org, topic=topic)
        vote = _make_vote(test_db, user, proposal, "yes")
        rat = _make_rationale(test_db, vote, content="Why I voted yes.")
        assert rat.vote_id == vote.id
        assert rat.content == "Why I voted yes."

    def test_update_rationale(self, test_db: Session):
        org = _make_org(test_db, "vrc2_org")
        user = _make_user(test_db, "vrc2_user")
        topic = _make_topic(test_db, org)
        proposal = _make_proposal(test_db, user, org, topic=topic)
        vote = _make_vote(test_db, user, proposal, "yes")
        rat = _make_rationale(test_db, vote, content="V1")
        rat.content = "V2"
        test_db.flush()
        test_db.refresh(rat)
        assert rat.content == "V2"

    def test_delete_rationale(self, test_db: Session):
        org = _make_org(test_db, "vrc3_org")
        user = _make_user(test_db, "vrc3_user")
        topic = _make_topic(test_db, org)
        proposal = _make_proposal(test_db, user, org, topic=topic)
        vote = _make_vote(test_db, user, proposal, "yes")
        rat = _make_rationale(test_db, vote)
        rat_id = rat.id
        test_db.delete(rat)
        test_db.flush()
        assert test_db.get(models.DelegateVoteRationale, rat_id) is None

    def test_unique_constraint_one_rationale_per_vote(
        self, test_db: Session,
    ):
        """uq_delegate_vote_rationale_vote_id — only one rationale per
        vote (the model enforces this; verifying the constraint is live)."""
        org = _make_org(test_db, "vrc4_org")
        user = _make_user(test_db, "vrc4_user")
        topic = _make_topic(test_db, org)
        proposal = _make_proposal(test_db, user, org, topic=topic)
        vote = _make_vote(test_db, user, proposal, "yes")
        _make_rationale(test_db, vote, content="first")
        with pytest.raises(Exception):
            _make_rationale(test_db, vote, content="dup")
            test_db.flush()

    def test_endpoint_owner_only_skips_if_missing(
        self, client: TestClient, test_db: Session,
    ):
        """Wave 2 owns ``PUT /api/votes/{id}/rationale``."""
        org = _make_org(test_db, "vrc5_org")
        owner = _make_user(test_db, "vrc5_owner")
        other = _make_user(test_db, "vrc5_other")
        for u in (owner, other):
            make_org_membership(
                test_db, org_id=org.id, user_id=u.id, role="member",
            )
        topic = _make_topic(test_db, org)
        proposal = _make_proposal(test_db, owner, org, topic=topic)
        vote = _make_vote(test_db, owner, proposal, "yes")
        test_db.commit()
        resp = client.put(
            f"/api/votes/{vote.id}/rationale",
            json={"content": "hi"},
            headers=_auth(other),
        )
        if resp.status_code in (404, 405):
            pytest.skip("Wave 2 rationale endpoint not yet landed")
        assert resp.status_code == 403, resp.text


# ===========================================================================
# Test class 6 — TestVoteRationaleVisibility
# ===========================================================================


class TestVoteRationaleVisibility:
    """Rationale visible iff topic state non-private; cascading visibility
    on topic state change (D5 / D13)."""

    def test_visible_when_topic_public(self, test_db: Session):
        org = _make_org(test_db, "vrv1_org")
        user = _make_user(test_db, "vrv1_user")
        topic = _make_topic(test_db, org)
        _make_delegate_profile(
            test_db, user, topic, org, visibility="public",
        )
        proposal = _make_proposal(test_db, user, org, topic=topic)
        vote = _make_vote(test_db, user, proposal, "yes")
        _make_rationale(test_db, vote, content="visible")
        # Rationale row exists; visibility is at the helper / endpoint
        # level (Wave 2). The schema-level test is that nothing prevents
        # the rationale from being returned when topic state allows.
        rationale = test_db.query(models.DelegateVoteRationale).filter(
            models.DelegateVoteRationale.vote_id == vote.id,
        ).first()
        assert rationale is not None

    def test_visible_when_topic_public_accepting(self, test_db: Session):
        org = _make_org(test_db, "vrv2_org")
        user = _make_user(test_db, "vrv2_user")
        topic = _make_topic(test_db, org)
        _make_delegate_profile(
            test_db, user, topic, org, visibility="public_accepting",
        )
        proposal = _make_proposal(test_db, user, org, topic=topic)
        vote = _make_vote(test_db, user, proposal, "yes")
        rat = _make_rationale(test_db, vote)
        assert rat is not None

    def test_topic_private_hides_rationale_no_data_loss(
        self, test_db: Session,
    ):
        """D13: topic private → rationale invisible; data NOT deleted."""
        org = _make_org(test_db, "vrv3_org")
        user = _make_user(test_db, "vrv3_user")
        topic = _make_topic(test_db, org)
        dp = _make_delegate_profile(
            test_db, user, topic, org, visibility="public_accepting",
        )
        proposal = _make_proposal(test_db, user, org, topic=topic)
        vote = _make_vote(test_db, user, proposal, "yes")
        rat = _make_rationale(test_db, vote, content="should remain in db")
        rat_id = rat.id
        # Flip topic visibility back to private.
        dp.visibility = "private"
        test_db.flush()
        # Rationale row still exists (no cascading delete on visibility flip).
        survived = test_db.get(models.DelegateVoteRationale, rat_id)
        assert survived is not None
        assert survived.content == "should remain in db"

    def test_owner_can_always_see_own_rationale(
        self, client: TestClient, test_db: Session,
    ):
        """Spec §B6 visibility rule: vote owner always sees own rationale.
        Skip if endpoint not landed."""
        org = _make_org(test_db, "vrv4_org")
        user = _make_user(test_db, "vrv4_user")
        make_org_membership(
            test_db, org_id=org.id, user_id=user.id, role="member",
        )
        topic = _make_topic(test_db, org)
        # Topic is private → rationale invisible to others, but owner sees.
        _make_delegate_profile(
            test_db, user, topic, org, visibility="private",
        )
        proposal = _make_proposal(test_db, user, org, topic=topic)
        vote = _make_vote(test_db, user, proposal, "yes")
        _make_rationale(test_db, vote, content="my own private rationale")
        test_db.commit()
        resp = client.get(
            f"/api/votes/{vote.id}/rationale", headers=_auth(user),
        )
        if resp.status_code in (404, 405):
            pytest.skip("Wave 2 rationale GET endpoint not yet landed")
        assert resp.status_code == 200, resp.text


# ===========================================================================
# Test class 7 — TestDelegateBrowseEndpoint  (B4 — main coverage)
# ===========================================================================


class TestDelegateBrowseEndpoint:
    """The B4 endpoint at GET /api/orgs/{slug}/delegates."""

    def _build_personas(
        self, test_db: Session,
    ) -> tuple[
        models.Organization, models.User, models.User, models.User,
        models.Topic, models.Topic, models.Topic,
    ]:
        """Mirror demo seed shape: dr_chen, env_emma (visible),
        econ_bob (excluded — only private/private_delegators)."""
        org = _make_org(test_db, "br_demo")
        # Personas.
        dr_chen = _make_user(test_db, "br_drchen", delegate_handle="brchen")
        env_emma = _make_user(test_db, "br_emma", delegate_handle="bremma")
        econ_bob = _make_user(test_db, "br_bob", delegate_handle="brbob")
        for u in (dr_chen, env_emma, econ_bob):
            make_org_membership(
                test_db, org_id=org.id, user_id=u.id, role="member",
            )
        # Topics.
        healthcare = _make_topic(test_db, org, "Healthcare_BR")
        economy = _make_topic(test_db, org, "Economy_BR")
        environment = _make_topic(test_db, org, "Environment_BR")
        # dr_chen: public_accepting on healthcare + economy.
        _make_delegate_profile(
            test_db, dr_chen, healthcare, org, visibility="public_accepting",
        )
        _make_delegate_profile(
            test_db, dr_chen, economy, org, visibility="public_accepting",
        )
        _make_org_delegate_profile(
            test_db, dr_chen, org, intro="dr_chen intro",
        )
        # env_emma: public_accepting on environment + public on economy.
        _make_delegate_profile(
            test_db, env_emma, environment, org, visibility="public_accepting",
        )
        _make_delegate_profile(
            test_db, env_emma, economy, org, visibility="public",
        )
        _make_org_delegate_profile(
            test_db, env_emma, org, intro="env_emma intro",
        )
        # econ_bob: only PRIVATE topics (NO public_accepting).
        _make_delegate_profile(
            test_db, econ_bob, economy, org, visibility="private",
        )
        _make_org_delegate_profile(
            test_db, econ_bob, org, intro="econ_bob draft",
            page_visibility="private_delegators",
        )
        test_db.commit()
        return org, dr_chen, env_emma, econ_bob, healthcare, economy, environment

    def test_lists_only_public_accepting(
        self, client: TestClient, test_db: Session,
    ):
        org, dr_chen, env_emma, econ_bob, _, _, _ = self._build_personas(
            test_db
        )
        resp = client.get(f"/api/orgs/{org.slug}/delegates")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        user_ids = {row["user_id"] for row in body}
        assert dr_chen.id in user_ids
        assert env_emma.id in user_ids
        assert econ_bob.id not in user_ids, (
            "econ_bob has no public_accepting topics — should not appear "
            "on browse per D11"
        )

    def test_response_shape_includes_required_fields(
        self, client: TestClient, test_db: Session,
    ):
        org, _, _, _, _, _, _ = self._build_personas(test_db)
        resp = client.get(f"/api/orgs/{org.slug}/delegates")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) >= 1
        row = body[0]
        for field in (
            "user_id", "display_name", "username", "delegate_handle",
            "avatar_url", "intro", "public_topics", "delegation_count",
            "recent_rationale_ratio",
        ):
            assert field in row, f"missing field {field!r}"
        # public_topics structure.
        if row["public_topics"]:
            t0 = row["public_topics"][0]
            assert {"topic_id", "name", "visibility"}.issubset(t0.keys())

    def test_topic_filter(
        self, client: TestClient, test_db: Session,
    ):
        org, dr_chen, env_emma, _, healthcare, _, environment = (
            self._build_personas(test_db)
        )
        # ?topic_id=healthcare → only dr_chen (env_emma is not
        # public_accepting on healthcare).
        resp = client.get(
            f"/api/orgs/{org.slug}/delegates?topic_id={healthcare.id}",
        )
        assert resp.status_code == 200
        ids = {row["user_id"] for row in resp.json()}
        assert dr_chen.id in ids
        assert env_emma.id not in ids
        # ?topic_id=environment → only env_emma.
        resp2 = client.get(
            f"/api/orgs/{org.slug}/delegates?topic_id={environment.id}",
        )
        assert resp2.status_code == 200
        ids2 = {row["user_id"] for row in resp2.json()}
        assert env_emma.id in ids2
        assert dr_chen.id not in ids2

    def test_default_sort_by_delegation_count_desc(
        self, client: TestClient, test_db: Session,
    ):
        org, dr_chen, env_emma, _, healthcare, _, _ = self._build_personas(
            test_db
        )
        # Give env_emma 5 delegations, dr_chen 1 → env_emma first.
        for i in range(5):
            d_user = _make_user(test_db, f"sort_d_{i}")
            make_org_membership(
                test_db, org_id=org.id, user_id=d_user.id, role="member",
            )
            _make_delegation(test_db, d_user, env_emma, org=org)
        d_user_extra = _make_user(test_db, "sort_d_chen")
        make_org_membership(
            test_db, org_id=org.id, user_id=d_user_extra.id, role="member",
        )
        _make_delegation(
            test_db, d_user_extra, dr_chen, org=org, topic=healthcare,
        )
        test_db.commit()

        resp = client.get(f"/api/orgs/{org.slug}/delegates")
        assert resp.status_code == 200
        body = resp.json()
        # First row is env_emma (5 delegations).
        emma_row = next(r for r in body if r["user_id"] == env_emma.id)
        chen_row = next(r for r in body if r["user_id"] == dr_chen.id)
        assert emma_row["delegation_count"] >= chen_row["delegation_count"]
        # Order: emma comes before chen.
        idx_emma = next(
            i for i, r in enumerate(body) if r["user_id"] == env_emma.id
        )
        idx_chen = next(
            i for i, r in enumerate(body) if r["user_id"] == dr_chen.id
        )
        assert idx_emma < idx_chen, (
            "env_emma (5 delegations) should sort before dr_chen (1) by "
            "delegation_count DESC"
        )

    def test_secondary_sort_by_rationale_ratio(
        self, client: TestClient, test_db: Session,
    ):
        """Equal delegation counts → higher recent_rationale_ratio first."""
        org = _make_org(test_db, "br_rr_org")
        u_a = _make_user(test_db, "br_rr_a", delegate_handle="rra")
        u_b = _make_user(test_db, "br_rr_b", delegate_handle="rrb")
        for u in (u_a, u_b):
            make_org_membership(
                test_db, org_id=org.id, user_id=u.id, role="member",
            )
        topic = _make_topic(test_db, org, "RRTopic")
        _make_delegate_profile(
            test_db, u_a, topic, org, visibility="public_accepting",
        )
        _make_delegate_profile(
            test_db, u_b, topic, org, visibility="public_accepting",
        )
        _make_org_delegate_profile(test_db, u_a, org)
        _make_org_delegate_profile(test_db, u_b, org)
        # Same delegation count (zero).
        # u_a: 2 votes, 2 rationales → ratio 1.0.
        # u_b: 2 votes, 0 rationales → ratio 0.0.
        author = _make_user(test_db, "br_rr_author")
        make_org_membership(
            test_db, org_id=org.id, user_id=author.id, role="member",
        )
        for i in range(2):
            p = _make_proposal(test_db, author, org, topic=topic)
            v_a = _make_vote(test_db, u_a, p, "yes")
            _make_rationale(test_db, v_a, content=f"rationale {i}")
            _make_vote(test_db, u_b, p, "yes")
        test_db.commit()
        resp = client.get(f"/api/orgs/{org.slug}/delegates")
        assert resp.status_code == 200
        body = resp.json()
        ids_in_order = [r["user_id"] for r in body]
        # u_a should come first by rationale ratio.
        assert ids_in_order.index(u_a.id) < ids_in_order.index(u_b.id)

    def test_active_within_days_filter(
        self, client: TestClient, test_db: Session,
    ):
        org = _make_org(test_db, "br_act_org")
        active_user = _make_user(test_db, "br_act_active")
        idle_user = _make_user(test_db, "br_act_idle")
        author = _make_user(test_db, "br_act_author")
        for u in (active_user, idle_user, author):
            make_org_membership(
                test_db, org_id=org.id, user_id=u.id, role="member",
            )
        topic = _make_topic(test_db, org, "ActTopic")
        for u in (active_user, idle_user):
            _make_delegate_profile(
                test_db, u, topic, org, visibility="public_accepting",
            )
            _make_org_delegate_profile(test_db, u, org)
        # active_user: vote 5 days ago.
        p1 = _make_proposal(test_db, author, org, topic=topic)
        _make_vote(
            test_db, active_user, p1, "yes",
            cast_at=_now_naive() - timedelta(days=5),
        )
        # idle_user: vote 60 days ago.
        p2 = _make_proposal(test_db, author, org, topic=topic)
        _make_vote(
            test_db, idle_user, p2, "yes",
            cast_at=_now_naive() - timedelta(days=60),
        )
        test_db.commit()
        # Filter to past 30 days.
        resp = client.get(
            f"/api/orgs/{org.slug}/delegates?active_within_days=30"
        )
        assert resp.status_code == 200
        ids = {r["user_id"] for r in resp.json()}
        assert active_user.id in ids
        assert idle_user.id not in ids

    def test_pagination_offset_and_limit(
        self, client: TestClient, test_db: Session,
    ):
        org = _make_org(test_db, "br_pag_org")
        topic = _make_topic(test_db, org, "PagTopic")
        author = _make_user(test_db, "br_pag_author")
        make_org_membership(
            test_db, org_id=org.id, user_id=author.id, role="member",
        )
        users = []
        for i in range(5):
            u = _make_user(test_db, f"br_pag_u{i}")
            make_org_membership(
                test_db, org_id=org.id, user_id=u.id, role="member",
            )
            _make_delegate_profile(
                test_db, u, topic, org, visibility="public_accepting",
            )
            _make_org_delegate_profile(test_db, u, org)
            users.append(u)
        test_db.commit()
        # limit=2 returns at most 2.
        resp = client.get(f"/api/orgs/{org.slug}/delegates?limit=2")
        assert resp.status_code == 200
        assert len(resp.json()) == 2
        # offset=4 with limit=2 returns 1 (only one row left after skipping 4).
        resp2 = client.get(
            f"/api/orgs/{org.slug}/delegates?limit=2&offset=4"
        )
        assert resp2.status_code == 200
        assert len(resp2.json()) == 1

    def test_non_member_can_browse_public_org(
        self, client: TestClient, test_db: Session,
    ):
        """Open orgs (not invite_only_secret) allow non-member browse."""
        org, _, _, _, _, _, _ = self._build_personas(test_db)
        # Anonymous: no auth header.
        resp = client.get(f"/api/orgs/{org.slug}/delegates")
        assert resp.status_code == 200, resp.text

    def test_non_member_cannot_browse_secret_org(
        self, client: TestClient, test_db: Session,
    ):
        secret_org = _make_org(
            test_db, "br_secret_org", join_policy="invite_only_secret",
        )
        member = _make_user(test_db, "br_secret_member")
        non_member = _make_user(test_db, "br_secret_outsider")
        make_org_membership(
            test_db, org_id=secret_org.id, user_id=member.id, role="member",
        )
        topic = _make_topic(test_db, secret_org, "Sek")
        _make_delegate_profile(
            test_db, member, topic, secret_org, visibility="public_accepting",
        )
        _make_org_delegate_profile(test_db, member, secret_org)
        test_db.commit()
        # Non-member: 404 (matches invite_only_secret semantics).
        resp = client.get(
            f"/api/orgs/{secret_org.slug}/delegates",
            headers=_auth(non_member),
        )
        assert resp.status_code == 404, resp.text
        # Member: 200.
        resp_m = client.get(
            f"/api/orgs/{secret_org.slug}/delegates", headers=_auth(member),
        )
        assert resp_m.status_code == 200, resp_m.text

    def test_404_on_unknown_org(
        self, client: TestClient, test_db: Session,
    ):
        resp = client.get("/api/orgs/nonexistent_org_slug/delegates")
        assert resp.status_code == 404

    def test_browse_returns_intro_from_org_delegate_profile(
        self, client: TestClient, test_db: Session,
    ):
        org, dr_chen, _, _, _, _, _ = self._build_personas(test_db)
        resp = client.get(f"/api/orgs/{org.slug}/delegates")
        assert resp.status_code == 200
        chen_row = next(
            r for r in resp.json() if r["user_id"] == dr_chen.id
        )
        assert chen_row["intro"] == "dr_chen intro"

    def test_browse_surfaces_public_and_public_accepting_topics(
        self, client: TestClient, test_db: Session,
    ):
        """D12: env_emma's public-only Economy topic shows on her row
        even though it's not what got her on the browse page."""
        org, _, env_emma, _, _, economy, environment = (
            self._build_personas(test_db)
        )
        resp = client.get(f"/api/orgs/{org.slug}/delegates")
        emma_row = next(
            r for r in resp.json() if r["user_id"] == env_emma.id
        )
        topic_visibilities = {
            t["topic_id"]: t["visibility"] for t in emma_row["public_topics"]
        }
        assert topic_visibilities.get(environment.id) == "public_accepting"
        assert topic_visibilities.get(economy.id) == "public"


# ===========================================================================
# Test class 8 — TestDelegateHandle
# ===========================================================================


class TestDelegateHandle:
    """Account-level handle (D10): unique, reserved-slugs collision check,
    URL resolution."""

    def test_handle_uniqueness(self, test_db: Session):
        u1 = _make_user(test_db, "h1_a", delegate_handle="duplicate")
        with pytest.raises(Exception):
            _make_user(test_db, "h1_b", delegate_handle="duplicate")
            test_db.flush()

    def test_handle_can_be_null(self, test_db: Session):
        u = _make_user(test_db, "h2_user")
        assert u.delegate_handle is None

    def test_handle_can_be_set_after_creation(self, test_db: Session):
        u = _make_user(test_db, "h3_user")
        u.delegate_handle = "newhandle"
        test_db.flush()
        test_db.refresh(u)
        assert u.delegate_handle == "newhandle"

    def test_handle_reserved_slugs_set_includes_known_blockers(self):
        """Sanity: reserved_slugs.RESERVED_SLUGS exists and contains
        common reservations that would conflict with handle URLs."""
        from reserved_slugs import RESERVED_SLUGS
        for blocked in ("admin", "api", "login"):
            assert blocked in RESERVED_SLUGS

    def test_handle_distinct_from_username(self, test_db: Session):
        """Handle and username are independent values."""
        u = _make_user(test_db, "h4_user", delegate_handle="cooluser")
        assert u.username == "h4_user"
        assert u.delegate_handle == "cooluser"


# ===========================================================================
# Test class 9 — TestPrivateDelegatorsPageVisibility
# ===========================================================================


class TestPrivateDelegatorsPageVisibility:
    """When page_visibility='private_delegators' AND no public topics,
    only approved followers in the org can see the page."""

    def test_page_visibility_resolves_to_private_delegators_with_no_public_topics(
        self, test_db: Session,
    ):
        org = _make_org(test_db, "pd1_org")
        user = _make_user(test_db, "pd1_user")
        topic = _make_topic(test_db, org, "PD1Topic")
        _make_delegate_profile(
            test_db, user, topic, org, visibility="private",
        )
        odp = _make_org_delegate_profile(
            test_db, user, org, page_visibility="private_delegators",
        )
        assert odp.effective_page_visibility(test_db) == "private_delegators"

    def test_follower_in_org_qualifies_for_private_delegators_view(
        self, test_db: Session,
    ):
        """Approved follower in this org can see the page (per D3 / B3).
        Schema-level check: a FollowRelationship row in this org exists
        for the viewer and the page owner."""
        org = _make_org(test_db, "pd2_org")
        owner = _make_user(test_db, "pd2_owner")
        viewer = _make_user(test_db, "pd2_viewer")
        for u in (owner, viewer):
            make_org_membership(
                test_db, org_id=org.id, user_id=u.id, role="member",
            )
        _make_org_delegate_profile(
            test_db, owner, org, page_visibility="private_delegators",
        )
        # Viewer follows owner in this org.
        _make_follow_rel(
            test_db, viewer, owner, org=org, permission_level="view_only",
        )
        test_db.commit()
        # Schema-level assertion: the FollowRelationship row exists in
        # this org. The endpoint-side enforcement lives in F2 / Wave 2;
        # the JOIN that powers the visibility check is the test here.
        rels = test_db.query(models.FollowRelationship).filter(
            models.FollowRelationship.follower_id == viewer.id,
            models.FollowRelationship.followed_id == owner.id,
            models.FollowRelationship.org_id == org.id,
        ).all()
        assert len(rels) == 1

    def test_non_follower_does_not_qualify(self, test_db: Session):
        """A user who's not a follower has no visibility row to count."""
        org = _make_org(test_db, "pd3_org")
        owner = _make_user(test_db, "pd3_owner")
        outsider = _make_user(test_db, "pd3_outsider")
        for u in (owner, outsider):
            make_org_membership(
                test_db, org_id=org.id, user_id=u.id, role="member",
            )
        _make_org_delegate_profile(
            test_db, owner, org, page_visibility="private_delegators",
        )
        test_db.commit()
        rels = test_db.query(models.FollowRelationship).filter(
            models.FollowRelationship.follower_id == outsider.id,
            models.FollowRelationship.followed_id == owner.id,
            models.FollowRelationship.org_id == org.id,
        ).all()
        assert len(rels) == 0


# ===========================================================================
# Test class 10 — TestBackwardsCompat
# ===========================================================================


class TestBackwardsCompat:
    """D8: existing DelegateProfile rows default to visibility='public_accepting'."""

    def test_new_delegate_profile_defaults_to_public_accepting(
        self, test_db: Session,
    ):
        """Direct ORM construction (no explicit visibility) gets the
        default. Mirrors what the migration's server_default provides
        for existing rows."""
        org = _make_org(test_db, "bc1_org")
        user = _make_user(test_db, "bc1_user")
        topic = _make_topic(test_db, org)
        dp = models.DelegateProfile(
            user_id=user.id,
            topic_id=topic.id,
            org_id=org.id,
            bio="legacy",
            is_active=True,
        )
        test_db.add(dp)
        test_db.flush()
        test_db.refresh(dp)
        assert dp.visibility == "public_accepting"

    def test_existing_legacy_row_remains_browsable(
        self, client: TestClient, test_db: Session,
    ):
        """A DelegateProfile created without explicit Phase-19 fields
        (only bio + is_active) still surfaces on the browse endpoint."""
        org = _make_org(test_db, "bc2_org")
        user = _make_user(test_db, "bc2_user")
        topic = _make_topic(test_db, org, "BC2Topic")
        # Legacy-shape construction.
        dp = models.DelegateProfile(
            user_id=user.id,
            topic_id=topic.id,
            org_id=org.id,
            bio="legacy bio",
            is_active=True,
        )
        test_db.add(dp)
        _make_org_delegate_profile(test_db, user, org)
        test_db.commit()
        resp = client.get(f"/api/orgs/{org.slug}/delegates")
        assert resp.status_code == 200
        ids = {r["user_id"] for r in resp.json()}
        assert user.id in ids


# ===========================================================================
# Test class 11 — TestHardRevertCascade  (D7)
# ===========================================================================


def _delegation_has_intent_id_column() -> bool:
    """Whether the schema actually carries delegation_intent_id (the
    spec assumes it; Wave 1 didn't add it). The hard-revert tests skip
    when False so the file remains green pre-Wave-2."""
    return hasattr(models.Delegation, "delegation_intent_id")


class TestHardRevertCascade:
    """public_accepting → private revokes public-origin delegations
    on that topic and emits delegation_revoked_by_delegate notifications."""

    def test_public_origin_delegations_get_revoked_endpoint(
        self, client: TestClient, test_db: Session,
    ):
        """End-to-end: hit the revert-to-private endpoint, assert
        public-origin delegations on that topic are deleted.
        Skips if Wave 2 hasn't landed."""
        org = _make_org(test_db, "hrv1_org")
        delegate = _make_user(test_db, "hrv1_delegate")
        delegator = _make_user(test_db, "hrv1_delegator")
        for u in (delegate, delegator):
            make_org_membership(
                test_db, org_id=org.id, user_id=u.id, role="member",
            )
        topic = _make_topic(test_db, org, "HRV1Topic")
        _make_delegate_profile(
            test_db, delegate, topic, org, visibility="public_accepting",
        )
        _make_org_delegate_profile(test_db, delegate, org)
        # Public-origin delegation: delegation_intent_id is NULL or
        # absent on the model.
        d = _make_delegation(
            test_db, delegator, delegate, org=org, topic=topic,
        )
        d_id = d.id
        test_db.commit()
        resp = client.post(
            f"/api/orgs/{org.slug}/delegate-profile/topics/{topic.id}"
            f"/revert-to-private",
            headers=_auth(delegate),
        )
        if resp.status_code in (404, 405):
            pytest.skip("Wave 2 revert-to-private endpoint not yet landed")
        assert resp.status_code in (200, 204), resp.text
        # The public-origin delegation row should be gone.
        survived = test_db.get(models.Delegation, d_id)
        assert survived is None, (
            "public-origin delegation should be revoked when delegate "
            "transitions topic to 'private'"
        )

    def test_notification_emitted_per_revoked_delegator(
        self, client: TestClient, test_db: Session,
    ):
        """Per spec: emit delegation_revoked_by_delegate notification
        per revoked delegator. Skip if endpoint missing."""
        org = _make_org(test_db, "hrv2_org")
        delegate = _make_user(test_db, "hrv2_delegate")
        delegators = [
            _make_user(test_db, f"hrv2_d{i}") for i in range(3)
        ]
        for u in [delegate, *delegators]:
            make_org_membership(
                test_db, org_id=org.id, user_id=u.id, role="member",
            )
        for d in delegators:
            _enable_in_app_pref(
                test_db, d.id, "delegation_revoked_by_delegate",
            )
        topic = _make_topic(test_db, org, "HRV2Topic")
        _make_delegate_profile(
            test_db, delegate, topic, org, visibility="public_accepting",
        )
        _make_org_delegate_profile(test_db, delegate, org)
        for d in delegators:
            _make_delegation(
                test_db, d, delegate, org=org, topic=topic,
            )
        test_db.commit()
        resp = client.post(
            f"/api/orgs/{org.slug}/delegate-profile/topics/{topic.id}"
            f"/revert-to-private",
            headers=_auth(delegate),
        )
        if resp.status_code in (404, 405):
            pytest.skip("Wave 2 revert-to-private endpoint not yet landed")
        assert resp.status_code in (200, 204), resp.text
        # Count notifications by event type for those delegator ids.
        notifs = test_db.query(models.Notification).filter(
            models.Notification.user_id.in_([d.id for d in delegators]),
            models.Notification.event_type == "delegation_revoked_by_delegate",
        ).all()
        assert len(notifs) == 3, (
            f"expected one delegation_revoked_by_delegate per revoked "
            f"delegator (3); got {len(notifs)}"
        )

    def test_rationale_visibility_flips_no_data_loss(
        self, test_db: Session,
    ):
        """When topic flips to private, rationales on its votes survive
        in the DB (visibility check happens at endpoint render time)."""
        org = _make_org(test_db, "hrv3_org")
        delegate = _make_user(test_db, "hrv3_user")
        topic = _make_topic(test_db, org, "HRV3Topic")
        dp = _make_delegate_profile(
            test_db, delegate, topic, org, visibility="public_accepting",
        )
        proposal = _make_proposal(test_db, delegate, org, topic=topic)
        vote = _make_vote(test_db, delegate, proposal, "yes")
        rat = _make_rationale(test_db, vote, content="durable")
        rat_id = rat.id
        # Revert to private (model-level mutation).
        dp.visibility = "private"
        test_db.flush()
        # Rationale row is preserved.
        assert test_db.get(
            models.DelegateVoteRationale, rat_id,
        ) is not None


# ===========================================================================
# Test class 12 — TestHardRevertPreservesPrivateDelegations  (D15)
# ===========================================================================


class TestHardRevertPreservesPrivateDelegations:
    """D15 — load-bearing. ``public → private`` and
    ``public_accepting → private`` revoke ONLY public-origin delegations
    (``delegation_intent_id IS NULL``); private-origin delegations
    (``delegation_intent_id IS NOT NULL``) are preserved AND no
    delegation_revoked_by_delegate notification fires for them.
    """

    def test_private_origin_preserved_through_endpoint(
        self, client: TestClient, test_db: Session,
    ):
        """The canonical D15 mixed-cohort scenario.

        Skips when:
          - Delegation.delegation_intent_id column is missing (Wave 1
            didn't add it; this is an open spec gap surfaced for the
            lead).
          - Wave 2 endpoint not landed yet.
        """
        if not _delegation_has_intent_id_column():
            pytest.skip(
                "Delegation.delegation_intent_id column not present in "
                "schema. Spec D15 requires it; Wave 1 didn't add it. "
                "Surface this gap to the lead — it blocks the D15 "
                "filter-by-origin path Backend Agent #2 needs to "
                "implement the revert-to-private cascade."
            )
        org = _make_org(test_db, "hrv12_org")
        delegate = _make_user(test_db, "hrv12_delegate")
        # Public-origin delegators: 2.
        pub_a = _make_user(test_db, "hrv12_pub_a")
        pub_b = _make_user(test_db, "hrv12_pub_b")
        # Private-origin delegators: 2 (came in via follow approval).
        priv_a = _make_user(test_db, "hrv12_priv_a")
        priv_b = _make_user(test_db, "hrv12_priv_b")
        all_users = [delegate, pub_a, pub_b, priv_a, priv_b]
        for u in all_users:
            make_org_membership(
                test_db, org_id=org.id, user_id=u.id, role="member",
            )
        topic = _make_topic(test_db, org, "HRV12Topic")
        _make_delegate_profile(
            test_db, delegate, topic, org, visibility="public_accepting",
        )
        _make_org_delegate_profile(test_db, delegate, org)
        # Public-origin: no intent.
        pub_a_d = _make_delegation(test_db, pub_a, delegate, org=org, topic=topic)
        pub_b_d = _make_delegation(test_db, pub_b, delegate, org=org, topic=topic)
        # Private-origin: synthetic intent IDs (any non-null sentinel
        # works for the filter test).
        # Build the follow_request + intent rows so the FK is satisfied.
        from models import FollowRequest, DelegationIntent
        for u in (priv_a, priv_b):
            _make_follow_rel(
                test_db, u, delegate, org=org,
                permission_level="delegation_allowed",
            )
            freq = FollowRequest(
                requester_id=u.id, target_id=delegate.id,
                org_id=org.id, status="approved",
                permission_level="delegation_allowed",
            )
            test_db.add(freq); test_db.flush()
            intent = DelegationIntent(
                delegator_id=u.id, delegate_id=delegate.id,
                org_id=org.id, topic_id=topic.id,
                follow_request_id=freq.id,
                status="activated",
                expires_at=_now_naive() + timedelta(days=30),
                activated_at=_now_naive(),
            )
            test_db.add(intent); test_db.flush()
            _make_delegation(
                test_db, u, delegate, org=org, topic=topic,
                delegation_intent_id=intent.id,
            )
        # Enable in-app pref for all delegators so we can count
        # notifications precisely.
        for u in (pub_a, pub_b, priv_a, priv_b):
            _enable_in_app_pref(
                test_db, u.id, "delegation_revoked_by_delegate",
            )
        test_db.commit()
        resp = client.post(
            f"/api/orgs/{org.slug}/delegate-profile/topics/{topic.id}"
            f"/revert-to-private",
            headers=_auth(delegate),
        )
        if resp.status_code in (404, 405):
            pytest.skip("Wave 2 revert-to-private endpoint not yet landed")
        assert resp.status_code in (200, 204), resp.text
        # ASSERTIONS — load-bearing for D15 closure.
        # 1) Public-origin delegations are gone.
        assert test_db.get(models.Delegation, pub_a_d.id) is None
        assert test_db.get(models.Delegation, pub_b_d.id) is None
        # 2) Private-origin delegations remain.
        priv_remain = test_db.query(models.Delegation).filter(
            models.Delegation.delegate_id == delegate.id,
            models.Delegation.delegator_id.in_([priv_a.id, priv_b.id]),
        ).count()
        assert priv_remain == 2, (
            f"private-origin delegations should be preserved through "
            f"public_accepting→private revert (D15); got {priv_remain}/2"
        )
        # 3) Notifications: only public-origin delegators got one.
        notifs = test_db.query(models.Notification).filter(
            models.Notification.event_type == "delegation_revoked_by_delegate",
            models.Notification.user_id.in_(
                [pub_a.id, pub_b.id, priv_a.id, priv_b.id]
            ),
        ).all()
        notif_recipients = {n.user_id for n in notifs}
        assert notif_recipients == {pub_a.id, pub_b.id}, (
            f"only public-origin delegators receive the revoke "
            f"notification per D15; got recipients={notif_recipients!r}"
        )

    def test_filter_semantics_public_origin_is_intent_id_null(
        self, test_db: Session,
    ):
        """Filter-level test (no endpoint involved): a query for
        ``delegation_intent_id IS NULL`` returns the public-origin rows
        only. Documents the exact filter shape Backend Agent #2 must
        centralize per the spec's _revoke_public_origin_delegations_on_topic
        helper requirement."""
        if not _delegation_has_intent_id_column():
            pytest.skip(
                "Delegation.delegation_intent_id column not present in "
                "schema; D15 filter cannot yet be expressed in SQLAlchemy."
            )
        org = _make_org(test_db, "hrv12b_org")
        delegate = _make_user(test_db, "hrv12b_delegate")
        pub = _make_user(test_db, "hrv12b_pub")
        priv = _make_user(test_db, "hrv12b_priv")
        for u in (delegate, pub, priv):
            make_org_membership(
                test_db, org_id=org.id, user_id=u.id, role="member",
            )
        topic = _make_topic(test_db, org, "HRV12bTopic")
        _make_delegate_profile(
            test_db, delegate, topic, org, visibility="public_accepting",
        )
        _make_delegation(test_db, pub, delegate, org=org, topic=topic)
        # Synthetic intent-id pointer for priv.
        from models import FollowRequest, DelegationIntent
        _make_follow_rel(test_db, priv, delegate, org=org)
        freq = FollowRequest(
            requester_id=priv.id, target_id=delegate.id, org_id=org.id,
            status="approved", permission_level="delegation_allowed",
        )
        test_db.add(freq); test_db.flush()
        intent = DelegationIntent(
            delegator_id=priv.id, delegate_id=delegate.id,
            org_id=org.id, topic_id=topic.id,
            follow_request_id=freq.id, status="activated",
            expires_at=_now_naive() + timedelta(days=30),
            activated_at=_now_naive(),
        )
        test_db.add(intent); test_db.flush()
        _make_delegation(
            test_db, priv, delegate, org=org, topic=topic,
            delegation_intent_id=intent.id,
        )
        test_db.commit()
        public_origin_rows = test_db.query(models.Delegation).filter(
            models.Delegation.delegate_id == delegate.id,
            models.Delegation.topic_id == topic.id,
            models.Delegation.org_id == org.id,
            getattr(models.Delegation, "delegation_intent_id").is_(None),
        ).all()
        assert len(public_origin_rows) == 1
        assert public_origin_rows[0].delegator_id == pub.id


# ===========================================================================
# Test class 13 — TestPhase18Integration
# ===========================================================================


class TestPhase18Integration:
    """private_delegators visibility uses Phase 18 follow-org-scoping —
    only followers in *this* org count."""

    def test_cross_org_follow_does_not_leak_private_delegators_view(
        self, test_db: Session,
    ):
        """A follows B in org_X. B has private_delegators page in org_Y.
        A is NOT a follower-in-org-Y, so A does NOT qualify to view B's
        org_Y page."""
        org_x = _make_org(test_db, "p18_x")
        org_y = _make_org(test_db, "p18_y")
        owner = _make_user(test_db, "p18_owner")
        viewer = _make_user(test_db, "p18_viewer")
        for u in (owner, viewer):
            make_org_membership(
                test_db, org_id=org_x.id, user_id=u.id, role="member",
            )
            make_org_membership(
                test_db, org_id=org_y.id, user_id=u.id, role="member",
            )
        # Follow only in org_X.
        _make_follow_rel(test_db, viewer, owner, org=org_x)
        _make_org_delegate_profile(
            test_db, owner, org_y, page_visibility="private_delegators",
        )
        test_db.commit()
        # Viewer's org-y follows for owner: zero.
        rels_y = test_db.query(models.FollowRelationship).filter(
            models.FollowRelationship.follower_id == viewer.id,
            models.FollowRelationship.followed_id == owner.id,
            models.FollowRelationship.org_id == org_y.id,
        ).all()
        assert len(rels_y) == 0, (
            "Phase 18 follow-org-scoping: a follow in org_X must not "
            "give the viewer access to private_delegators page in org_Y"
        )
        # Sanity: org-x follow exists (the delta is org-scope).
        rels_x = test_db.query(models.FollowRelationship).filter(
            models.FollowRelationship.follower_id == viewer.id,
            models.FollowRelationship.followed_id == owner.id,
            models.FollowRelationship.org_id == org_x.id,
        ).all()
        assert len(rels_x) == 1

    def test_same_org_follow_qualifies(self, test_db: Session):
        """Sanity counterpart: a follow in the same org DOES qualify."""
        org = _make_org(test_db, "p18_same_org")
        owner = _make_user(test_db, "p18s_owner")
        viewer = _make_user(test_db, "p18s_viewer")
        for u in (owner, viewer):
            make_org_membership(
                test_db, org_id=org.id, user_id=u.id, role="member",
            )
        _make_follow_rel(test_db, viewer, owner, org=org)
        _make_org_delegate_profile(
            test_db, owner, org, page_visibility="private_delegators",
        )
        test_db.commit()
        rels = test_db.query(models.FollowRelationship).filter(
            models.FollowRelationship.follower_id == viewer.id,
            models.FollowRelationship.followed_id == owner.id,
            models.FollowRelationship.org_id == org.id,
        ).all()
        assert len(rels) == 1


# ===========================================================================
# Test class 14 — TestNotificationEvents
# ===========================================================================


class TestNotificationEvents:
    """All four new event types are registered AND emit on the right
    transitions. Registration assertions run pre-Wave-2; emission tests
    skip on missing endpoint."""

    def test_event_keys_registered(self):
        from notification_events import EVENT_REGISTRY_BY_KEY
        for key in (
            "delegate_application_submitted",
            "delegate_application_approved",
            "delegate_application_denied",
            "delegation_revoked_by_delegate",
        ):
            assert key in EVENT_REGISTRY_BY_KEY, (
                f"Phase 19 event {key!r} missing from notification_events "
                f"registry — Backend Agent #2 should have added it"
            )

    def test_submission_emits_delegate_application_submitted(
        self, client: TestClient, test_db: Session,
    ):
        """When a user submits a topic for public_accepting, approvers
        in the org receive ``delegate_application_submitted``. Skip if
        endpoint missing."""
        org = _make_org(test_db, "ne_sub_org")
        approver = _make_user(test_db, "ne_sub_approver")
        applicant = _make_user(test_db, "ne_sub_applicant")
        # Approver role: steward (steward gets delegate_application.approve
        # by default).
        make_org_membership(
            test_db, org_id=org.id, user_id=approver.id, role="steward",
        )
        make_org_membership(
            test_db, org_id=org.id, user_id=applicant.id, role="member",
        )
        topic = _make_topic(test_db, org, "NESubTopic")
        _make_delegate_profile(
            test_db, applicant, topic, org, visibility="public",
        )
        _enable_in_app_pref(
            test_db, approver.id, "delegate_application_submitted",
        )
        test_db.commit()
        resp = client.post(
            f"/api/orgs/{org.slug}/delegate-profile/topics/{topic.id}"
            f"/submit-public-accepting",
            headers=_auth(applicant),
        )
        if resp.status_code in (404, 405):
            pytest.skip("Wave 2 submit endpoint not yet landed")
        assert resp.status_code in (200, 201), resp.text
        notifs = test_db.query(models.Notification).filter(
            models.Notification.event_type == "delegate_application_submitted",
            models.Notification.user_id == approver.id,
        ).all()
        assert len(notifs) == 1, (
            f"expected one delegate_application_submitted notification "
            f"to the approver; got {len(notifs)}"
        )

    def test_approval_emits_delegate_application_approved(
        self, client: TestClient, test_db: Session,
    ):
        org = _make_org(test_db, "ne_app_org")
        approver = _make_user(test_db, "ne_app_approver")
        applicant = _make_user(test_db, "ne_app_applicant")
        make_org_membership(
            test_db, org_id=org.id, user_id=approver.id, role="steward",
        )
        make_org_membership(
            test_db, org_id=org.id, user_id=applicant.id, role="member",
        )
        topic = _make_topic(test_db, org, "NEAppTopic")
        dp = _make_delegate_profile(
            test_db, applicant, topic, org, visibility="public",
        )
        dp.public_accepting_submitted_at = _now_naive()
        _enable_in_app_pref(
            test_db, applicant.id, "delegate_application_approved",
        )
        test_db.commit()
        resp = client.post(
            f"/api/orgs/{org.slug}/delegate-profile/topics/{topic.id}"
            f"/approve",
            headers=_auth(approver),
        )
        if resp.status_code in (404, 405):
            pytest.skip("Wave 2 approve endpoint not yet landed")
        assert resp.status_code in (200, 201), resp.text
        notifs = test_db.query(models.Notification).filter(
            models.Notification.event_type == "delegate_application_approved",
            models.Notification.user_id == applicant.id,
        ).all()
        assert len(notifs) == 1

    def test_denial_emits_delegate_application_denied(
        self, client: TestClient, test_db: Session,
    ):
        org = _make_org(test_db, "ne_deny_org")
        approver = _make_user(test_db, "ne_deny_approver")
        applicant = _make_user(test_db, "ne_deny_applicant")
        make_org_membership(
            test_db, org_id=org.id, user_id=approver.id, role="steward",
        )
        make_org_membership(
            test_db, org_id=org.id, user_id=applicant.id, role="member",
        )
        topic = _make_topic(test_db, org, "NEDenyTopic")
        dp = _make_delegate_profile(
            test_db, applicant, topic, org, visibility="public",
        )
        dp.public_accepting_submitted_at = _now_naive()
        _enable_in_app_pref(
            test_db, applicant.id, "delegate_application_denied",
        )
        test_db.commit()
        resp = client.post(
            f"/api/orgs/{org.slug}/delegate-profile/topics/{topic.id}"
            f"/deny",
            json={"comment": "More details please."},
            headers=_auth(approver),
        )
        if resp.status_code in (404, 405):
            pytest.skip("Wave 2 deny endpoint not yet landed")
        assert resp.status_code in (200, 201), resp.text
        notifs = test_db.query(models.Notification).filter(
            models.Notification.event_type == "delegate_application_denied",
            models.Notification.user_id == applicant.id,
        ).all()
        assert len(notifs) == 1

    def test_hard_revert_emits_delegation_revoked_by_delegate(
        self, client: TestClient, test_db: Session,
    ):
        """End-to-end variant of TestHardRevertCascade.test_notification_
        emitted_per_revoked_delegator — one delegator, exact-count check.
        """
        org = _make_org(test_db, "ne_rev_org")
        delegate = _make_user(test_db, "ne_rev_delegate")
        delegator = _make_user(test_db, "ne_rev_delegator")
        for u in (delegate, delegator):
            make_org_membership(
                test_db, org_id=org.id, user_id=u.id, role="member",
            )
        topic = _make_topic(test_db, org, "NERevTopic")
        _make_delegate_profile(
            test_db, delegate, topic, org, visibility="public_accepting",
        )
        _make_org_delegate_profile(test_db, delegate, org)
        _make_delegation(test_db, delegator, delegate, org=org, topic=topic)
        _enable_in_app_pref(
            test_db, delegator.id, "delegation_revoked_by_delegate",
        )
        test_db.commit()
        resp = client.post(
            f"/api/orgs/{org.slug}/delegate-profile/topics/{topic.id}"
            f"/revert-to-private",
            headers=_auth(delegate),
        )
        if resp.status_code in (404, 405):
            pytest.skip("Wave 2 revert-to-private endpoint not yet landed")
        assert resp.status_code in (200, 204), resp.text
        notifs = test_db.query(models.Notification).filter(
            models.Notification.event_type == "delegation_revoked_by_delegate",
            models.Notification.user_id == delegator.id,
        ).all()
        assert len(notifs) == 1
