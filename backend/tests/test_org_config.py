"""Phase 8.5 — get_org_config (parent-chain config resolution) tests.

Decision 9: sub-orgs inherit config from their parent unless they set their
own override. Resolution order:
  1. The org's own ``settings`` if the key is present.
  2. The parent org's ``settings`` if set (recursive).
  3. The caller-supplied ``default``.

The walk is bounded — a cycle or schema drift past 5 hops raises RuntimeError
rather than silently falling back.
"""

from __future__ import annotations

import pytest

import models
from org_config import get_org_config


def _make_org(db, slug: str, settings: dict | None = None,
              parent_org_id: str | None = None) -> models.Organization:
    org = models.Organization(
        name=slug, slug=slug, description="",
        parent_org_id=parent_org_id,
        settings=settings or {},
    )
    db.add(org)
    db.flush()
    return org


# ---------------------------------------------------------------------------
# Single-org (no parent)
# ---------------------------------------------------------------------------

def test_single_org_returns_own_setting(db):
    org = _make_org(db, "parent", settings={"voting_days": 7})
    assert get_org_config(org, "voting_days") == 7


def test_single_org_returns_default_when_unset(db):
    org = _make_org(db, "parent", settings={})
    assert get_org_config(org, "voting_days", 5) == 5


def test_none_org_returns_default(db):
    """Optional-org callers can pass None safely."""
    assert get_org_config(None, "voting_days", 5) == 5


# ---------------------------------------------------------------------------
# Sub-org override / inherit
# ---------------------------------------------------------------------------

def test_sub_org_uses_own_setting_when_present(db):
    parent = _make_org(db, "parent", settings={"voting_days": 7})
    sub = _make_org(db, "sub", settings={"voting_days": 3}, parent_org_id=parent.id)
    db.refresh(sub)
    # Sub-org override wins over parent value.
    assert get_org_config(sub, "voting_days") == 3


def test_sub_org_falls_back_to_parent(db):
    parent = _make_org(db, "parent", settings={"voting_days": 7})
    sub = _make_org(db, "sub", settings={}, parent_org_id=parent.id)
    db.refresh(sub)
    assert get_org_config(sub, "voting_days") == 7


def test_sub_org_falls_back_to_default(db):
    """Neither sub-org nor parent has the key → default."""
    parent = _make_org(db, "parent", settings={})
    sub = _make_org(db, "sub", settings={}, parent_org_id=parent.id)
    db.refresh(sub)
    assert get_org_config(sub, "voting_days", 5) == 5


def test_sub_org_with_falsy_value_does_not_fall_back(db):
    """A sub-org override of False (or 0) is a real override, not 'unset'."""
    parent = _make_org(db, "parent", settings={"feature_x": True})
    sub = _make_org(db, "sub", settings={"feature_x": False}, parent_org_id=parent.id)
    db.refresh(sub)
    assert get_org_config(sub, "feature_x") is False


def test_sub_org_with_explicit_none_value_uses_it(db):
    """An explicit None override is still 'present' — return None, not parent."""
    parent = _make_org(db, "parent", settings={"voting_days": 7})
    sub = _make_org(db, "sub", settings={"voting_days": None}, parent_org_id=parent.id)
    db.refresh(sub)
    assert get_org_config(sub, "voting_days", 5) is None


# ---------------------------------------------------------------------------
# Multi-level walk
# ---------------------------------------------------------------------------

def test_two_level_walk_finds_grandparent_setting(db):
    """Two-level walk — sub-sub → sub → parent (schema permits 3 levels even
    though API will reject; helper must handle whatever the schema produces)."""
    grandparent = _make_org(db, "grandparent", settings={"voting_days": 7})
    parent = _make_org(db, "parent", settings={}, parent_org_id=grandparent.id)
    sub = _make_org(db, "sub", settings={}, parent_org_id=parent.id)
    db.refresh(sub)
    assert get_org_config(sub, "voting_days") == 7


# ---------------------------------------------------------------------------
# Cycle protection
# ---------------------------------------------------------------------------

def test_cycle_protection_raises(db):
    """A schema-level cycle (org A → org B → org A) raises RuntimeError instead
    of looping forever. Two-level enforcement at the API layer should make this
    impossible in practice; the helper guards anyway."""
    # We can't create an honest cycle through the SQLAlchemy default flush
    # easily because of the FK; build via duck-typed objects to exercise the
    # depth bound directly.
    class _Org:
        def __init__(self, settings, name="ring"):
            self.settings = settings
            self.id = name
            self.parent_org = None

    a = _Org({}, "a")
    b = _Org({}, "b")
    a.parent_org = b
    b.parent_org = a  # cycle

    with pytest.raises(RuntimeError, match="exceeded max parent-walk depth"):
        get_org_config(a, "voting_days", "default")
