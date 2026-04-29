"""Phase 8.5 — Tests for is_sub_org_admin permission helper.

Decision 6:
  - Sub-org admins (role admin/owner in SubOrgMembership) can administer
    their own sub-org.
  - Parent-org admins (role admin/owner in OrgMembership of the parent)
    have IMPLICIT admin powers in all sub-orgs of that parent.
  - Sub-org admins do NOT have powers outside their sub-org.
  - Calling the helper on a non-sub-org (parent_org_id IS NULL) is a
    programmer error and raises ValueError.
"""

from __future__ import annotations

import pytest

import models
from permissions import is_sub_org_admin
from tests.conftest import make_user


def _make_org(db, slug: str, parent_org_id: str | None = None) -> models.Organization:
    org = models.Organization(
        name=slug, slug=slug, description="",
        parent_org_id=parent_org_id, settings={},
    )
    db.add(org)
    db.flush()
    return org


def _add_membership(db, user, org, role: str = "member", status: str = "active"):
    m = models.OrgMembership(
        user_id=user.id, org_id=org.id, role=role, status=status,
    )
    db.add(m)
    db.flush()
    return m


def _add_sub_membership(db, user, sub_org, role: str = "member", status: str = "active"):
    m = models.SubOrgMembership(
        user_id=user.id, sub_org_id=sub_org.id, role=role, status=status,
    )
    db.add(m)
    db.flush()
    return m


# ---------------------------------------------------------------------------
# Direct sub-org admin / owner
# ---------------------------------------------------------------------------

def test_sub_org_admin_returns_true(db):
    parent = _make_org(db, "parent")
    sub = _make_org(db, "sub", parent_org_id=parent.id)
    user = make_user(db, "alice")
    _add_sub_membership(db, user, sub, role="admin")
    assert is_sub_org_admin(db, user.id, sub) is True


def test_sub_org_owner_returns_true(db):
    parent = _make_org(db, "parent")
    sub = _make_org(db, "sub", parent_org_id=parent.id)
    user = make_user(db, "alice")
    _add_sub_membership(db, user, sub, role="owner")
    assert is_sub_org_admin(db, user.id, sub) is True


def test_sub_org_member_non_admin_returns_false(db):
    parent = _make_org(db, "parent")
    sub = _make_org(db, "sub", parent_org_id=parent.id)
    user = make_user(db, "alice")
    _add_sub_membership(db, user, sub, role="member")
    assert is_sub_org_admin(db, user.id, sub) is False


def test_sub_org_moderator_returns_false(db):
    """moderator is below admin/owner; should not grant admin powers."""
    parent = _make_org(db, "parent")
    sub = _make_org(db, "sub", parent_org_id=parent.id)
    user = make_user(db, "alice")
    _add_sub_membership(db, user, sub, role="moderator")
    assert is_sub_org_admin(db, user.id, sub) is False


def test_suspended_sub_org_admin_returns_false(db):
    parent = _make_org(db, "parent")
    sub = _make_org(db, "sub", parent_org_id=parent.id)
    user = make_user(db, "alice")
    _add_sub_membership(db, user, sub, role="admin", status="suspended")
    assert is_sub_org_admin(db, user.id, sub) is False


# ---------------------------------------------------------------------------
# Implicit admin via parent-org admin/owner
# ---------------------------------------------------------------------------

def test_parent_org_admin_returns_true(db):
    """Decision 6: parent-org admins have implicit sub-org admin power."""
    parent = _make_org(db, "parent")
    sub = _make_org(db, "sub", parent_org_id=parent.id)
    user = make_user(db, "alice")
    _add_membership(db, user, parent, role="admin")
    # No SubOrgMembership row at all
    assert is_sub_org_admin(db, user.id, sub) is True


def test_parent_org_owner_returns_true(db):
    parent = _make_org(db, "parent")
    sub = _make_org(db, "sub", parent_org_id=parent.id)
    user = make_user(db, "alice")
    _add_membership(db, user, parent, role="owner")
    assert is_sub_org_admin(db, user.id, sub) is True


def test_parent_org_member_returns_false(db):
    parent = _make_org(db, "parent")
    sub = _make_org(db, "sub", parent_org_id=parent.id)
    user = make_user(db, "alice")
    _add_membership(db, user, parent, role="member")
    assert is_sub_org_admin(db, user.id, sub) is False


def test_suspended_parent_org_admin_returns_false(db):
    parent = _make_org(db, "parent")
    sub = _make_org(db, "sub", parent_org_id=parent.id)
    user = make_user(db, "alice")
    _add_membership(db, user, parent, role="admin", status="suspended")
    assert is_sub_org_admin(db, user.id, sub) is False


# ---------------------------------------------------------------------------
# Negative cases
# ---------------------------------------------------------------------------

def test_unknown_user_returns_false(db):
    parent = _make_org(db, "parent")
    sub = _make_org(db, "sub", parent_org_id=parent.id)
    # No memberships at all for the made-up user id
    assert is_sub_org_admin(db, "user-does-not-exist", sub) is False


def test_user_admin_of_different_parent_org_returns_false(db):
    """Decision 6: parent-org admin powers don't bleed across parent orgs."""
    parent_a = _make_org(db, "parent-a")
    parent_b = _make_org(db, "parent-b")
    sub_a = _make_org(db, "sub-a", parent_org_id=parent_a.id)
    user = make_user(db, "alice")
    _add_membership(db, user, parent_b, role="admin")
    assert is_sub_org_admin(db, user.id, sub_a) is False


def test_passing_non_sub_org_raises_value_error(db):
    """The helper is for sub-orgs only; calling it on a parent org is a bug."""
    parent = _make_org(db, "parent")
    user = make_user(db, "alice")
    _add_membership(db, user, parent, role="admin")
    with pytest.raises(ValueError, match="non-sub-org"):
        is_sub_org_admin(db, user.id, parent)
