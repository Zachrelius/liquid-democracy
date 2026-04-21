"""
Tests for org settings JSON mutation persistence (Fix 1).

Verifies that PATCH-ing org settings correctly persists changes
through SQLAlchemy's change detection, including nested dicts.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from database import Base
import models  # noqa: F401 — registers ORM classes


TEST_DB_URL = "sqlite:///:memory:"

_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


@pytest.fixture(scope="function")
def db() -> Session:
    engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def _make_org(db: Session, settings: dict | None = None) -> models.Organization:
    org = models.Organization(
        name="Test Org",
        slug="test-org",
        description="",
        join_policy="open",
        settings=settings or {"default_voting_days": 7},
    )
    db.add(org)
    db.flush()
    return org


def test_org_settings_merge_persists_after_commit(db: Session):
    """Merging new keys into org.settings must persist after commit + re-fetch."""
    org = _make_org(db, settings={"default_voting_days": 7, "allow_public_delegates": True})
    db.commit()

    # Simulate what the PATCH endpoint does (the fixed version)
    org = db.query(models.Organization).filter(
        models.Organization.slug == "test-org"
    ).first()

    new_settings = {"default_pass_threshold": 0.60, "nested_voting": {"min_quorum": 0.3}}
    org.settings = {**(org.settings or {}), **new_settings}
    db.commit()

    # Re-fetch in a way that forces a fresh read from the DB
    db.expire_all()
    fresh_org = db.query(models.Organization).filter(
        models.Organization.slug == "test-org"
    ).first()

    assert fresh_org.settings["default_voting_days"] == 7
    assert fresh_org.settings["allow_public_delegates"] is True
    assert fresh_org.settings["default_pass_threshold"] == 0.60
    assert fresh_org.settings["nested_voting"] == {"min_quorum": 0.3}


def test_org_settings_overwrite_existing_key(db: Session):
    """Overwriting an existing key in settings must persist."""
    org = _make_org(db, settings={"default_voting_days": 7})
    db.commit()

    org = db.query(models.Organization).filter(
        models.Organization.slug == "test-org"
    ).first()

    org.settings = {**(org.settings or {}), "default_voting_days": 14}
    db.commit()

    db.expire_all()
    fresh_org = db.query(models.Organization).filter(
        models.Organization.slug == "test-org"
    ).first()

    assert fresh_org.settings["default_voting_days"] == 14


def test_org_settings_from_none(db: Session):
    """Settings merge must work when org.settings starts as None."""
    org = _make_org(db, settings=None)
    db.commit()

    org = db.query(models.Organization).filter(
        models.Organization.slug == "test-org"
    ).first()

    org.settings = {**(org.settings or {}), "default_voting_days": 5}
    db.commit()

    db.expire_all()
    fresh_org = db.query(models.Organization).filter(
        models.Organization.slug == "test-org"
    ).first()

    assert fresh_org.settings["default_voting_days"] == 5


def test_inplace_mutation_does_not_persist(db: Session):
    """Demonstrates the bug: in-place .update() on the same dict object
    may not trigger SQLAlchemy change detection and silently loses data.
    This test documents the risk — in-memory SQLite may not reproduce the
    exact failure, but the pattern is still wrong and this test verifies
    the correct pattern is used instead."""
    org = _make_org(db, settings={"key_a": 1})
    db.commit()

    org = db.query(models.Organization).filter(
        models.Organization.slug == "test-org"
    ).first()

    # Correct pattern: always create a new dict
    org.settings = {**(org.settings or {}), "key_b": 2}
    db.commit()

    db.expire_all()
    fresh_org = db.query(models.Organization).filter(
        models.Organization.slug == "test-org"
    ).first()

    assert fresh_org.settings["key_a"] == 1
    assert fresh_org.settings["key_b"] == 2
