"""Phase 8.5 — eligible_voter_ids_for_proposal helper tests.

The helper dispatches on proposal scope:
  - sub-org-scoped: active SubOrgMembership in the sub-org.
  - parent-org-scoped or no-org-scoped: every user in the DB (legacy
    behavior preserved bit-for-bit so single-org installs don't regress).
"""

from __future__ import annotations

import models
from delegation_engine import eligible_voter_ids_for_proposal
from tests.conftest import make_user


def _make_org(db, slug: str, parent_org_id: str | None = None) -> models.Organization:
    org = models.Organization(
        name=slug, slug=slug, description="",
        parent_org_id=parent_org_id, settings={},
    )
    db.add(org)
    db.flush()
    return org


def _add_membership(db, user, org, status: str = "active"):
    m = models.OrgMembership(
        user_id=user.id, org_id=org.id, role="member", status=status,
    )
    db.add(m)
    db.flush()
    return m


def _add_sub_membership(db, user, sub_org, status: str = "active"):
    m = models.SubOrgMembership(
        user_id=user.id, sub_org_id=sub_org.id, role="member", status=status,
    )
    db.add(m)
    db.flush()
    return m


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
# Parent-org-scoped proposals (legacy behavior preserved)
# ---------------------------------------------------------------------------

def test_parent_org_proposal_returns_all_users(db):
    """Legacy behavior: parent-org-scoped proposals (sub_org_id IS NULL)
    eligibility = every user in the DB. Phase 8.5 deliberately preserves this
    so existing single-org tests don't regress; tightening to org-only is a
    Session 2 route-layer concern."""
    parent = _make_org(db, "parent")
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    _add_membership(db, alice, parent)
    # bob is NOT a parent-org member but should still be 'eligible' under
    # the legacy "all users" semantic.
    proposal = _make_proposal(db, alice, org_id=parent.id, sub_org_id=None)

    eligible = eligible_voter_ids_for_proposal(db, proposal)
    assert alice.id in eligible
    assert bob.id in eligible


def test_proposal_with_no_org_returns_all_users(db):
    """Pre-multitenancy proposals (org_id IS NULL) keep the all-users behavior."""
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    proposal = _make_proposal(db, alice, org_id=None, sub_org_id=None)

    eligible = eligible_voter_ids_for_proposal(db, proposal)
    assert eligible == {alice.id, bob.id}
