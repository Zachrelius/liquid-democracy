"""Phase 12.5 B2 — get_default_proposal_thresholds helper tests.

Covers the defaults-if-absent fallback (no migration backfill per spec
line 122) and override-from-settings behavior, plus the org-is-None
short-circuit used by the global-proposal POST path.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from org_config import get_default_proposal_thresholds


@pytest.fixture(scope="function")
def db() -> Session:
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


def _make_org(db: Session, slug: str, settings: dict | None) -> models.Organization:
    org = models.Organization(
        name=slug.title(), slug=slug, description="",
        settings=settings,
    )
    db.add(org)
    db.flush()
    return org


def test_returns_platform_defaults_when_settings_absent(db):
    """Spec line 122: NO migration backfill of these keys; the helper's
    defaults-if-absent behavior covers every existing org transparently.
    A freshly-created org with empty settings reads (0.50, 0.40)."""
    org = _make_org(db, "freshorg", {})
    assert get_default_proposal_thresholds(org) == (0.50, 0.40)


def test_returns_platform_defaults_when_settings_is_none(db):
    """Defensive: org.settings can be None on legacy rows. Helper still
    returns (0.50, 0.40) without raising."""
    org = _make_org(db, "noneorg", None)
    assert get_default_proposal_thresholds(org) == (0.50, 0.40)


def test_returns_persisted_pass_threshold_when_set(db):
    """When a Steward customises default_pass_threshold via the Org
    Settings UI, that value is reflected in the helper output. Quorum
    falls back to the platform default (the two keys are independent)."""
    org = _make_org(db, "passcustom", {"default_pass_threshold": 0.66})
    assert get_default_proposal_thresholds(org) == (0.66, 0.40)


def test_returns_persisted_quorum_threshold_when_set(db):
    """Same shape as the pass-threshold case but for quorum: pass falls
    back to 0.50 when only quorum is customised."""
    org = _make_org(db, "quorumcustom", {"default_quorum_threshold": 0.33})
    assert get_default_proposal_thresholds(org) == (0.50, 0.33)


def test_returns_both_persisted_values_when_both_set(db):
    """Both keys customised: helper reads both verbatim (no rounding,
    no clamping; spec Q2 explicitly says no hard floor)."""
    org = _make_org(db, "bothcustom", {
        "default_pass_threshold": 0.75,
        "default_quorum_threshold": 0.20,
    })
    assert get_default_proposal_thresholds(org) == (0.75, 0.20)


def test_short_circuits_when_org_is_none():
    """The helper accepts None (used by the global-proposal POST path
    where there is no org context). Returns the platform defaults."""
    assert get_default_proposal_thresholds(None) == (0.50, 0.40)


def test_does_not_walk_parent_chain(db):
    """Sub-org inheritance is explicitly out of scope (spec "Per-sub-org
    thresholds" deferred). The helper only reads its own org's settings;
    it does NOT walk up to a parent's settings. Verified here so a future
    refactor doesn't accidentally regress this contract."""
    parent = models.Organization(
        name="Parent", slug="parent125", description="",
        settings={"default_pass_threshold": 0.66},
    )
    db.add(parent)
    db.flush()
    sub = models.Organization(
        name="Sub", slug="sub125", description="",
        parent_org_id=parent.id, settings={},
    )
    db.add(sub)
    db.flush()
    # Sub-org with empty settings reads platform defaults — NOT parent's
    # 0.66. This is the documented contract today; sub-org inheritance is
    # a future-pass concern.
    assert get_default_proposal_thresholds(sub) == (0.50, 0.40)
