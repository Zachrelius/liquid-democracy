"""Phase 9.7 W2 — backfill orphaned pending invitations.

Three branches under test:
  - Rescued: pending invitation + matching user with no membership →
    OrgMembership created with the invitation's role, invitation accepted.
  - Already member: pending invitation + matching user already in the
    inviting org → invitation accepted, no membership change.
  - Auto-join victim: pending invitation + user has a demo membership AND
    the inviting org is non-demo → counted, demo membership left intact.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from scripts.phase9_7_backfill_orphaned_invitations import backfill


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


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


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _user(db, username: str, email: str) -> models.User:
    u = models.User(
        username=username, display_name=username.title(),
        password_hash=_DUMMY_HASH, email=email, email_verified=True,
    )
    db.add(u); db.flush()
    return u


def _org(db, name: str, slug: str) -> models.Organization:
    o = models.Organization(
        name=name, slug=slug, description="", join_policy="invite_only",
    )
    db.add(o); db.flush()
    return o


def _invitation(
    db,
    org: models.Organization,
    email: str,
    inviter: models.User,
    role: str = "member",
) -> models.Invitation:
    inv = models.Invitation(
        org_id=org.id,
        email=email.lower(),
        invited_by=inviter.id,
        role=role,
        token=secrets.token_urlsafe(48),
        status="pending",
        expires_at=_now() + timedelta(days=7),
    )
    db.add(inv); db.flush()
    return inv


def test_backfill_rescued_creates_membership(db, capsys):
    inviter = _user(db, "z", "z@test.example")
    wife = _user(db, "wife", "wife@test.example")
    gamenights = _org(db, "GameNights", "gamenights")
    inv = _invitation(db, gamenights, "wife@test.example", inviter)
    db.commit()

    result = backfill(db)
    assert result.rescued == 1
    assert result.already_member == 0
    assert result.auto_join_victims == 0
    assert result.total_processed == 1

    membership = db.query(models.OrgMembership).filter(
        models.OrgMembership.user_id == wife.id,
        models.OrgMembership.org_id == gamenights.id,
    ).first()
    assert membership is not None
    assert membership.role == "member"
    assert membership.status == "active"

    db.refresh(inv)
    assert inv.status == "accepted"
    assert inv.accepted_at is not None

    out = capsys.readouterr().out
    assert "Rescued: added wife to gamenights." in out
    assert "Rescued: 1." in out
    assert "Already members: 0." in out

    # Idempotent — re-running does nothing now that the invitation is accepted.
    result2 = backfill(db)
    assert result2.total_processed == 0


def test_backfill_already_member_marks_accepted_no_dup(db, capsys):
    inviter = _user(db, "z", "z@test.example")
    wife = _user(db, "wife", "wife@test.example")
    gamenights = _org(db, "GameNights", "gamenights")
    db.add(models.OrgMembership(
        user_id=wife.id, org_id=gamenights.id, role="member", status="active",
    ))
    inv = _invitation(db, gamenights, "wife@test.example", inviter)
    db.commit()

    result = backfill(db)
    assert result.rescued == 0
    assert result.already_member == 1
    assert result.total_processed == 1

    # Membership not duplicated.
    memberships = db.query(models.OrgMembership).filter(
        models.OrgMembership.user_id == wife.id,
        models.OrgMembership.org_id == gamenights.id,
    ).all()
    assert len(memberships) == 1

    db.refresh(inv)
    assert inv.status == "accepted"

    out = capsys.readouterr().out
    assert "Already member: wife in gamenights" in out


def test_backfill_auto_join_victim_signal_does_not_remove_demo(db, capsys):
    inviter = _user(db, "z", "z@test.example")
    wife = _user(db, "wife", "wife@test.example")
    demo = _org(db, "Demo Organization", "demo")
    gamenights = _org(db, "GameNights", "gamenights")

    # Wife was caught by the auto-join bug: she's in demo and not in
    # gamenights. The invitation is for gamenights.
    db.add(models.OrgMembership(
        user_id=wife.id, org_id=demo.id, role="member", status="active",
    ))
    inv = _invitation(db, gamenights, "wife@test.example", inviter)
    db.commit()

    result = backfill(db)
    assert result.rescued == 1
    assert result.auto_join_victims == 1

    # Demo membership intact — we don't yank it (users can be in multi orgs).
    demo_membership = db.query(models.OrgMembership).filter(
        models.OrgMembership.user_id == wife.id,
        models.OrgMembership.org_id == demo.id,
    ).first()
    assert demo_membership is not None
    assert demo_membership.status == "active"

    # GameNights membership now exists.
    gn_membership = db.query(models.OrgMembership).filter(
        models.OrgMembership.user_id == wife.id,
        models.OrgMembership.org_id == gamenights.id,
    ).first()
    assert gn_membership is not None

    out = capsys.readouterr().out
    assert "Auto-join victim: wife got auto-joined to demo" in out
    assert "Rescued: 1. Already members: 0. Auto-join victims observed: 1." in out


def test_backfill_skips_invitation_with_no_matching_user(db):
    """Pending invitation whose email has no registered user is left alone."""
    inviter = _user(db, "z", "z@test.example")
    gamenights = _org(db, "GameNights", "gamenights")
    inv = _invitation(db, gamenights, "ghost@test.example", inviter)
    db.commit()

    result = backfill(db)
    assert result.total_processed == 0

    db.refresh(inv)
    assert inv.status == "pending"
