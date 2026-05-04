"""
Phase 12.8 audit Tier 1, Item 5 — sustained-majority `floor_breached` in
the read path (`build_status`) must consult `support_ever_established`,
matching the worker's Phase 9.8 C1 fix. Pre-12.8 the read path used only
the latest snapshot and a bare `support < floor` check, so the UI banner
reported "floor breached" the moment a non-zero vote dropped below the
floor — even before any threshold-meeting consensus had ever existed in
the window.

These tests exercise `sustained_majority_service.build_status` directly
against a SQLite in-memory DB rather than going through the API layer,
because the goal is to assert behavior of the binary-branch path
specifically without spinning up the FastAPI app.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

import models
import sustained_majority_service as svc
from database import Base


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture(scope="function")
def db():
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


def _make_org_and_proposal(db: Session, *, threshold=0.6, floor=0.4):
    org = models.Organization(
        name="Floor Test Org",
        slug="floor-test",
        description="",
        join_policy="open",
        settings={
            "default_voting_days": 7,
            "sustained_majority_enabled_default": True,
            "sustained_majority_threshold": threshold,
            "sustained_majority_floor": floor,
            "sustained_majority_failure_mode": "extend",
        },
    )
    db.add(org)
    db.flush()
    user = models.User(
        username="creator",
        display_name="Creator",
        password_hash="x",
        email="creator@x.example",
        email_verified=True,
    )
    db.add(user)
    db.flush()
    p = models.Proposal(
        title="Should we?",
        body="",
        author_id=user.id,
        org_id=org.id,
        voting_method="binary",
        status="voting",
        sustained_majority_enabled=True,
        voting_start=_now() - timedelta(days=1),
        voting_end=_now() + timedelta(days=6),
    )
    db.add(p)
    db.flush()
    return org, p


def _add_snapshot(db, proposal, *, t, yes, no, abstain=0, total_eligible=10):
    snap = models.VoteSnapshot(
        proposal_id=proposal.id,
        simulated_time=t,
        yes_count=yes,
        no_count=no,
        abstain_count=abstain,
        not_cast_count=max(0, total_eligible - yes - no - abstain),
        total_eligible=total_eligible,
        multi_option_winners=None,
    )
    db.add(snap)
    db.flush()
    return snap


def test_no_breach_when_support_never_established(db):
    """Snapshot history shows support always below the threshold; even
    though the latest snapshot is below the floor, `floor_breached` must
    be False because no consensus was ever established to lose."""
    org, p = _make_org_and_proposal(db, threshold=0.6, floor=0.4)

    base = _now() - timedelta(hours=2)
    # Three snapshots, all below threshold (0.6) and the last below floor (0.4):
    _add_snapshot(db, p, t=base, yes=2, no=3, total_eligible=10)            # 0.40
    _add_snapshot(db, p, t=base + timedelta(minutes=10), yes=3, no=4, total_eligible=10)  # ~0.43
    _add_snapshot(db, p, t=base + timedelta(minutes=20), yes=2, no=6, total_eligible=10)  # 0.25 — below floor
    db.commit()

    status = svc.build_status(db, p, org)
    assert status.active is True
    assert status.floor_breached is False, (
        "floor cannot be breached before any threshold-meeting consensus "
        "has ever existed in the window"
    )


def test_breach_when_support_was_established_then_dropped(db):
    """Snapshot history crosses threshold (0.6) at least once, then drops
    below floor (0.4). `floor_breached` must be True."""
    org, p = _make_org_and_proposal(db, threshold=0.6, floor=0.4)

    base = _now() - timedelta(hours=2)
    _add_snapshot(db, p, t=base, yes=4, no=2, total_eligible=10)            # ~0.67 — establishes consensus
    _add_snapshot(db, p, t=base + timedelta(minutes=10), yes=5, no=3, total_eligible=10)  # 0.625
    _add_snapshot(db, p, t=base + timedelta(minutes=20), yes=2, no=7, total_eligible=10)  # ~0.22 — below floor
    db.commit()

    status = svc.build_status(db, p, org)
    assert status.active is True
    assert status.floor_breached is True


def test_no_breach_when_above_floor_after_establishment(db):
    """Consensus established, latest still above the floor — no breach."""
    org, p = _make_org_and_proposal(db, threshold=0.6, floor=0.4)

    base = _now() - timedelta(hours=2)
    _add_snapshot(db, p, t=base, yes=5, no=3, total_eligible=10)             # 0.625
    _add_snapshot(db, p, t=base + timedelta(minutes=10), yes=5, no=4, total_eligible=10)  # ~0.55
    db.commit()

    status = svc.build_status(db, p, org)
    assert status.active is True
    assert status.floor_breached is False
