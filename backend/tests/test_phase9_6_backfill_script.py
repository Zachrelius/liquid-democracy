"""Phase 9.6 Workstream 2 — backfill script validation.

Exercises the in-process logic of
``scripts.phase9_6_backfill_sub_org_creator_memberships`` against an
in-memory sqlite DB, since the script is intended to be operationally
runnable but should also have a regression test for its core branches.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from audit_utils import log_audit_event
from database import Base
from scripts.phase9_6_backfill_sub_org_creator_memberships import backfill


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


def test_backfill_creates_missing_membership(db, capsys):
    alice = models.User(
        username="alice", display_name="Alice", password_hash=_DUMMY_HASH,
        email="a@x", email_verified=True,
    )
    db.add(alice); db.flush()

    parent = models.Organization(
        name="Parent", slug="parent", join_policy="open", settings={},
    )
    db.add(parent); db.flush()

    sub = models.Organization(
        name="Sub", slug="sub", join_policy="invite_only",
        settings={}, parent_org_id=parent.id,
    )
    db.add(sub); db.flush()

    log_audit_event(
        db,
        action="sub_org.created",
        target_type="organization",
        target_id=sub.id,
        actor_id=alice.id,
    )
    db.commit()

    rows = backfill(db)
    assert rows == 1

    sm = db.query(models.SubOrgMembership).filter_by(
        user_id=alice.id, sub_org_id=sub.id,
    ).first()
    assert sm is not None
    assert sm.role == "admin"
    assert sm.status == "active"

    out = capsys.readouterr().out
    assert "Added: sub_org=sub creator=alice" in out
    assert "Total: 1 rows added" in out


def test_backfill_skips_existing_active_membership(db, capsys):
    alice = models.User(
        username="alice", display_name="Alice", password_hash=_DUMMY_HASH,
        email="a@x", email_verified=True,
    )
    db.add(alice); db.flush()

    parent = models.Organization(
        name="Parent", slug="parent", join_policy="open", settings={},
    )
    db.add(parent); db.flush()

    sub = models.Organization(
        name="Sub", slug="sub", join_policy="invite_only",
        settings={}, parent_org_id=parent.id,
    )
    db.add(sub); db.flush()

    log_audit_event(
        db,
        action="sub_org.created",
        target_type="organization",
        target_id=sub.id,
        actor_id=alice.id,
    )
    # Pre-existing active membership — backfill should skip silently.
    db.add(models.SubOrgMembership(
        user_id=alice.id, sub_org_id=sub.id, role="admin", status="active",
    ))
    db.commit()

    rows = backfill(db)
    assert rows == 0
    # And idempotent re-run also adds 0.
    rows2 = backfill(db)
    assert rows2 == 0


def test_backfill_warns_when_no_creator_audit(db, capsys):
    parent = models.Organization(
        name="Parent", slug="parent", join_policy="open", settings={},
    )
    db.add(parent); db.flush()

    sub = models.Organization(
        name="Orphan", slug="orphan", join_policy="invite_only",
        settings={}, parent_org_id=parent.id,
    )
    db.add(sub); db.flush()
    db.commit()

    rows = backfill(db)
    assert rows == 0
    out = capsys.readouterr().out
    assert "WARNING: Skipping orphan: no creator audit found" in out
    assert "Total: 0 rows added" in out
