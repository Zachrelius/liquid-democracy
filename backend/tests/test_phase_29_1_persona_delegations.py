"""Phase 29.1 — quick-login persona delegations + logo wiring tests.

Exercises the full HOA seed pipeline against an in-memory SQLite DB and
asserts the per-persona delegation/precedence/strategy outcomes match
the bible spec. Slower than the pure-function Phase 29 B2 tests (~3-5s
per test from running the entire seed pipeline) but the surface under
test is the seed pipeline itself, not pure functions.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from demo_content.hoa_bible import HOA_BIBLE
from demo_content.schema import PersonaDelegationSpec
from demo_content.seed_pipeline import (
    _seed_persona_delegations,
    _underlying_username,
    seed_org_from_bible,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def db_session():
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
def seeded_hoa(db_session):
    """Seed Cedar Hollow from HOA_BIBLE and return (session, org)."""
    seed_org_from_bible(
        db_session,
        HOA_BIBLE,
        now=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db_session.commit()
    org = db_session.query(models.Organization).filter_by(
        slug="demo-cedar-hollow",
    ).first()
    return db_session, org


def _user_for(db: Session, bible_uid: str) -> models.User:
    return db.query(models.User).filter_by(
        username=_underlying_username(bible_uid),
    ).first()


# ===========================================================================
# B4 — persona delegation seeding
# ===========================================================================


class TestPersonaDelegationsSeeded:
    """All 6 quick-login personas get delegation_strategy + the expected
    number of Delegation + TopicPrecedence rows from the bible spec."""

    EXPECTED = {
        "hoa_janet": ("relevance_weighted", 2, 2),
        "hoa_brenda": ("relevance_weighted", 2, 2),
        "hoa_marcus": ("relevance_weighted", 4, 4),
        "hoa_don": ("strict_precedence", 0, 0),
        "hoa_linda": ("strict_precedence", 4, 4),
        "hoa_tomas": ("relevance_weighted", 2, 2),
    }

    def test_all_personas_match_spec(self, seeded_hoa):
        db, org = seeded_hoa
        for bible_uid, (strategy, n_del, n_pre) in self.EXPECTED.items():
            user = _user_for(db, bible_uid)
            assert user is not None, f"persona {bible_uid} missing"
            assert user.delegation_strategy == strategy, (
                f"{bible_uid} strategy: expected {strategy!r}, "
                f"got {user.delegation_strategy!r}"
            )
            actual_del = db.query(models.Delegation).filter(
                models.Delegation.delegator_id == user.id,
                models.Delegation.org_id == org.id,
                models.Delegation.topic_id != None,  # noqa: E711
            ).count()
            assert actual_del == n_del, (
                f"{bible_uid} delegation count: expected {n_del}, "
                f"got {actual_del}"
            )
            actual_pre = db.query(models.TopicPrecedence).filter_by(
                user_id=user.id,
            ).count()
            assert actual_pre == n_pre, (
                f"{bible_uid} precedence count: expected {n_pre}, "
                f"got {actual_pre}"
            )


class TestDonHasNoDelegations:
    """Don is the deliberate non-delegator. Zero delegations, zero
    precedence rows, strict_precedence strategy. Empty state must
    seed cleanly without errors."""

    def test_don_empty_and_strict(self, seeded_hoa):
        db, org = seeded_hoa
        don = _user_for(db, "hoa_don")
        assert don.delegation_strategy == "strict_precedence"
        assert db.query(models.Delegation).filter_by(
            delegator_id=don.id,
        ).count() == 0
        assert db.query(models.TopicPrecedence).filter_by(
            user_id=don.id,
        ).count() == 0


class TestMarcusPrecedenceOrderingCorrect:
    """Marcus's TopicPrecedence priorities must match the bible spec:
    Budget=0 > Pool & Recreation=1 > Bylaws & Procedure=2 > Elections=3.
    """

    def test_marcus_ordering(self, seeded_hoa):
        db, org = seeded_hoa
        marcus = _user_for(db, "hoa_marcus")
        rows = (
            db.query(models.TopicPrecedence, models.Topic)
            .join(models.Topic, models.TopicPrecedence.topic_id == models.Topic.id)
            .filter(models.TopicPrecedence.user_id == marcus.id)
            .all()
        )
        # Phase 30.1 B5 — topic names are no longer prefixed.
        by_topic = {t.name: p.priority for (p, t) in rows}
        assert by_topic == {
            "Budget": 0,
            "Pool & Recreation": 1,
            "Bylaws & Procedure": 2,
            "Elections": 3,
        }


class TestPersonaDelegationValidationMissingTopicInPrecedence:
    """A delegation on a topic not in topic_precedence must raise at
    seed time with a clear error. Catches future content-authoring
    typos rather than silently producing inconsistent precedence."""

    def test_raises_on_missing_topic(self, db_session):
        # Build a minimal stand-alone seed surface.
        org = models.Organization(
            slug="test-org", name="Test Org",
            description="", join_policy="open", is_demo=True,
        )
        db_session.add(org)
        db_session.flush()

        topic_budget = models.Topic(
            name="test-org:Budget", color="#000000",
            org_id=org.id,
        )
        db_session.add(topic_budget)
        db_session.flush()

        from auth import hash_password
        user_a = models.User(
            username="user_a", display_name="A",
            password_hash=hash_password("x"),
            email="a@test.example", email_verified=True,
        )
        user_b = models.User(
            username="user_b", display_name="B",
            password_hash=hash_password("x"),
            email="b@test.example", email_verified=True,
        )
        db_session.add_all([user_a, user_b])
        db_session.flush()

        # Bad spec: Budget in delegations but precedence omits it.
        class _StubBible:
            persona_delegations = [
                PersonaDelegationSpec(
                    delegator_user_id="user_a",
                    delegation_strategy="relevance_weighted",
                    delegations=[("Budget", "user_b")],
                    topic_precedence=[],
                ),
            ]

        with pytest.raises(ValueError, match="not in topic_precedence"):
            _seed_persona_delegations(
                db=db_session,
                bible=_StubBible(),
                org=org,
                bible_uid_to_user={"user_a": user_a, "user_b": user_b},
                topics_by_name={"Budget": topic_budget},
            )


class TestLogoUrlSeededWhenPresent:
    """HOA_BIBLE.logo_path lands at settings['branding']['logo_url']."""

    def test_logo_url_lands(self, seeded_hoa):
        _, org = seeded_hoa
        branding = (org.settings or {}).get("branding") or {}
        assert branding.get("logo_url") == "/demo_assets/cedar_hollow_logo.jpg"
        # Brand color from Phase 29 C5 still there.
        assert branding.get("primary_color") == "#3B5A3B"
