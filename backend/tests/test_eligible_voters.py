"""Phase 8.5 — eligible_voter_ids_for_proposal helper tests.

The helper dispatches on proposal scope:
  - sub-org-scoped (``sub_org_id`` non-null): active SubOrgMembership in the
    sub-org.
  - parent-org-scoped (``org_id`` non-null, ``sub_org_id`` null): active
    OrgMembership in the parent org.
  - no-org-scoped (``org_id`` null — pre-multi-tenancy fixture): defensive
    fallback to "all users in the DB".
"""

from __future__ import annotations

import models
from delegation_engine import eligible_voter_ids_for_proposal
from tests.conftest import make_user, make_org_membership


def _make_org(db, slug: str, parent_org_id: str | None = None) -> models.Organization:
    org = models.Organization(
        name=slug, slug=slug, description="",
        parent_org_id=parent_org_id, settings={},
    )
    db.add(org)
    db.flush()
    return org


def _add_membership(db, user, org, status: str = "active"):
    m = make_org_membership(
        db,
        user_id=user.id, org_id=org.id, role="member", status=status,
    )
    return m


def _add_sub_membership(db, user, sub_org, status: str = "active"):
    from tests.conftest import make_sub_org_membership
    return make_sub_org_membership(
        db, sub_org_id=sub_org.id, user_id=user.id,
        role="member", status=status,
    )


def _make_proposal(
    db, author, org_id: str | None = None, sub_org_id: str | None = None,
) -> models.Proposal:
    p = models.Proposal(
        title="t", body="", author_id=author.id, status="voting",
        org_id=org_id, sub_org_id=sub_org_id,
    )
    db.add(p)
    db.flush()
    return p


# ---------------------------------------------------------------------------
# Sub-org-scoped proposals
# ---------------------------------------------------------------------------

def test_sub_org_proposal_returns_sub_org_members(db):
    parent = _make_org(db, "parent")
    sub = _make_org(db, "sub", parent_org_id=parent.id)
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    carol = make_user(db, "carol")
    # All three are parent-org members
    for u in (alice, bob, carol):
        _add_membership(db, u, parent)
    # Only alice and carol are sub-org members
    _add_sub_membership(db, alice, sub)
    _add_sub_membership(db, carol, sub)
    proposal = _make_proposal(db, alice, org_id=parent.id, sub_org_id=sub.id)

    eligible = eligible_voter_ids_for_proposal(db, proposal)
    assert eligible == {alice.id, carol.id}


def test_sub_org_proposal_excludes_inactive_sub_org_members(db):
    parent = _make_org(db, "parent")
    sub = _make_org(db, "sub", parent_org_id=parent.id)
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    _add_membership(db, alice, parent)
    _add_membership(db, bob, parent)
    _add_sub_membership(db, alice, sub, status="active")
    _add_sub_membership(db, bob, sub, status="suspended")
    proposal = _make_proposal(db, alice, org_id=parent.id, sub_org_id=sub.id)

    eligible = eligible_voter_ids_for_proposal(db, proposal)
    assert eligible == {alice.id}


def test_sub_org_proposal_with_no_members_returns_empty_set(db):
    parent = _make_org(db, "parent")
    sub = _make_org(db, "sub", parent_org_id=parent.id)
    alice = make_user(db, "alice")
    _add_membership(db, alice, parent)
    proposal = _make_proposal(db, alice, org_id=parent.id, sub_org_id=sub.id)

    eligible = eligible_voter_ids_for_proposal(db, proposal)
    assert eligible == set()


def test_sub_org_proposal_excludes_parent_only_members(db):
    """Parent-org members who are NOT sub-org members are NOT eligible."""
    parent = _make_org(db, "parent")
    sub = _make_org(db, "sub", parent_org_id=parent.id)
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    _add_membership(db, alice, parent)
    _add_membership(db, bob, parent)
    _add_sub_membership(db, alice, sub)
    # bob has no SubOrgMembership row
    proposal = _make_proposal(db, alice, org_id=parent.id, sub_org_id=sub.id)

    eligible = eligible_voter_ids_for_proposal(db, proposal)
    assert eligible == {alice.id}
    assert bob.id not in eligible


# ---------------------------------------------------------------------------
# Parent-org-scoped proposals (Session 2 tightened: active OrgMembership only)
# ---------------------------------------------------------------------------

def test_parent_org_proposal_returns_active_org_members(db):
    """Session 2 tightening: parent-org-scoped proposals (sub_org_id IS NULL,
    org_id non-null) restrict eligibility to active OrgMembership rows.
    Non-members are no longer eligible."""
    parent = _make_org(db, "parent")
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    _add_membership(db, alice, parent)
    # bob is NOT a parent-org member; should NOT be eligible after tightening.
    proposal = _make_proposal(db, alice, org_id=parent.id, sub_org_id=None)

    eligible = eligible_voter_ids_for_proposal(db, proposal)
    assert eligible == {alice.id}
    assert bob.id not in eligible


def test_parent_org_proposal_excludes_suspended_members(db):
    """Suspended OrgMembership rows are NOT eligible."""
    parent = _make_org(db, "parent")
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    _add_membership(db, alice, parent, status="active")
    _add_membership(db, bob, parent, status="suspended")
    proposal = _make_proposal(db, alice, org_id=parent.id, sub_org_id=None)

    eligible = eligible_voter_ids_for_proposal(db, proposal)
    assert eligible == {alice.id}


def test_proposal_with_no_org_returns_all_users(db):
    """Pre-multi-tenancy proposals (org_id IS NULL) keep the legacy
    "all users" behavior as a defensive fallback. This case should not arise
    for production rows since Phase 4 — exists for unit-test convenience."""
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    proposal = _make_proposal(db, alice, org_id=None, sub_org_id=None)

    eligible = eligible_voter_ids_for_proposal(db, proposal)
    assert eligible == {alice.id, bob.id}
