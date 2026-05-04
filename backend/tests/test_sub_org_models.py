"""Phase 8.5 — Schema-level tests for the sub-organization model.

These tests pin the data-layer guarantees:
  - Organization.parent_org_id is nullable and self-references organizations.
  - SubOrgMembership has a unique (user_id, sub_org_id) constraint.
  - Cascade: deleting a parent org wipes its sub_orgs and their memberships.
  - sub_org_id columns on Topic/Proposal/DelegateProfile default to NULL.
  - Two-level depth (parent → sub → sub-sub) is allowed at the SCHEMA level;
    the API layer is responsible for enforcing the two-level limit
    (Decision 1 — two-level enforcement is at the API, not the schema).
  - Single-org regression: existing tables / rows are unaffected when no
    sub-org structure is present.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

import models
from tests.conftest import make_user, make_topic, make_org_membership


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_org(db, name: str, slug: str, parent_org_id: str | None = None) -> models.Organization:
    org = models.Organization(
        name=name, slug=slug, description="",
        parent_org_id=parent_org_id,
        settings={},
    )
    db.add(org)
    db.flush()
    return org


def _add_sub_org_membership(db, user, sub_org, role="member") -> models.SubOrgMembership:
    m = models.SubOrgMembership(
        user_id=user.id,
        sub_org_id=sub_org.id,
        role=role,
        status="active",
    )
    db.add(m)
    db.flush()
    return m


# ---------------------------------------------------------------------------
# Parent / sub-org relationship
# ---------------------------------------------------------------------------

def test_organization_parent_org_id_defaults_null(db):
    """Newly-created orgs have parent_org_id IS NULL by default."""
    parent = _make_org(db, "Parent", "parent")
    assert parent.parent_org_id is None
    assert parent.parent_org is None
    assert parent.sub_orgs == []


def test_create_sub_org_links_to_parent(db):
    parent = _make_org(db, "Parent", "parent")
    sub = _make_org(db, "Sub", "sub", parent_org_id=parent.id)
    assert sub.parent_org_id == parent.id
    db.refresh(parent)
    assert sub in parent.sub_orgs
    assert sub.parent_org.id == parent.id


def test_two_level_depth_allowed_at_schema_level(db):
    """Decision 1: schema permits 3+ levels; the API rejects them. This test
    pins the schema-side allowance so future enforcement at the API layer
    doesn't accidentally tighten the schema too."""
    parent = _make_org(db, "Parent", "parent")
    sub = _make_org(db, "Sub", "sub", parent_org_id=parent.id)
    sub_sub = _make_org(db, "SubSub", "sub-sub", parent_org_id=sub.id)
    assert sub_sub.parent_org_id == sub.id
    assert sub_sub.parent_org.parent_org.id == parent.id


def test_delete_parent_org_cascades_to_sub_orgs(db):
    """Cascade: orm-level delete-orphan on parent.sub_orgs removes children."""
    parent = _make_org(db, "Parent", "parent")
    sub_a = _make_org(db, "SubA", "sub-a", parent_org_id=parent.id)
    sub_b = _make_org(db, "SubB", "sub-b", parent_org_id=parent.id)
    sub_a_id = sub_a.id
    sub_b_id = sub_b.id
    db.delete(parent)
    db.flush()
    assert db.get(models.Organization, sub_a_id) is None
    assert db.get(models.Organization, sub_b_id) is None


# ---------------------------------------------------------------------------
# SubOrgMembership
# ---------------------------------------------------------------------------

def test_sub_org_membership_unique_user_sub_org(db):
    parent = _make_org(db, "Parent", "parent")
    sub = _make_org(db, "Sub", "sub", parent_org_id=parent.id)
    user = make_user(db, "alice")
    _add_sub_org_membership(db, user, sub)
    # Adding again with same (user, sub_org) should violate uniqueness
    with pytest.raises(IntegrityError):
        _add_sub_org_membership(db, user, sub, role="moderator")
    db.rollback()


def test_user_can_belong_to_multiple_sub_orgs(db):
    """Decision 2: a user can belong to multiple sub-orgs of the same parent."""
    parent = _make_org(db, "Parent", "parent")
    sub_a = _make_org(db, "SubA", "sub-a", parent_org_id=parent.id)
    sub_b = _make_org(db, "SubB", "sub-b", parent_org_id=parent.id)
    user = make_user(db, "alice")
    _add_sub_org_membership(db, user, sub_a)
    _add_sub_org_membership(db, user, sub_b)
    db.refresh(user)
    sub_org_ids = {m.sub_org_id for m in user.sub_org_memberships}
    assert sub_org_ids == {sub_a.id, sub_b.id}


def test_delete_sub_org_cascades_to_its_memberships(db):
    parent = _make_org(db, "Parent", "parent")
    sub = _make_org(db, "Sub", "sub", parent_org_id=parent.id)
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    _add_sub_org_membership(db, alice, sub)
    _add_sub_org_membership(db, bob, sub)
    membership_count_before = db.query(models.SubOrgMembership).filter(
        models.SubOrgMembership.sub_org_id == sub.id,
    ).count()
    assert membership_count_before == 2
    db.delete(sub)
    db.flush()
    membership_count_after = db.query(models.SubOrgMembership).count()
    assert membership_count_after == 0


def test_sub_org_membership_default_role_member(db):
    parent = _make_org(db, "Parent", "parent")
    sub = _make_org(db, "Sub", "sub", parent_org_id=parent.id)
    user = make_user(db, "alice")
    m = models.SubOrgMembership(
        user_id=user.id, sub_org_id=sub.id, status="active",
    )
    db.add(m)
    db.flush()
    assert m.role == "member"


# ---------------------------------------------------------------------------
# sub_org_id columns on Topic / Proposal / DelegateProfile
# ---------------------------------------------------------------------------

def test_topic_sub_org_id_defaults_null(db):
    """Existing topic creation paths don't set sub_org_id — must default to NULL."""
    topic = make_topic(db, "Healthcare")
    assert topic.sub_org_id is None


def test_topic_can_be_scoped_to_sub_org(db):
    parent = _make_org(db, "Parent", "parent")
    sub = _make_org(db, "Sub", "sub", parent_org_id=parent.id)
    topic = models.Topic(
        name="Engineering Practices", description="", color="#000",
        sub_org_id=sub.id,
    )
    db.add(topic)
    db.flush()
    assert topic.sub_org_id == sub.id


def test_proposal_sub_org_id_defaults_null(db):
    """A proposal created without sub_org_id has it as NULL — single-org default."""
    user = make_user(db, "alice")
    p = models.Proposal(
        title="t", body="", author_id=user.id, status="draft",
    )
    db.add(p)
    db.flush()
    assert p.sub_org_id is None


def test_delegate_profile_sub_org_id_defaults_null(db):
    user = make_user(db, "alice")
    topic = make_topic(db, "Healthcare")
    profile = models.DelegateProfile(
        user_id=user.id, topic_id=topic.id, bio="", is_active=True,
    )
    db.add(profile)
    db.flush()
    assert profile.sub_org_id is None


# ---------------------------------------------------------------------------
# Single-org regression
# ---------------------------------------------------------------------------

def test_single_org_topic_proposal_membership_unaffected(db):
    """Pin the bit-for-bit behavior: a parent-org-only org with no sub-org
    structure still works exactly like the pre-Phase-8.5 path. Topic/Proposal/
    OrgMembership go through their existing constructors unchanged."""
    org = _make_org(db, "Single", "single")
    user = make_user(db, "alice")
    membership = make_org_membership(
        db,
        user_id=user.id, org_id=org.id, role="member", status="active",
    )
    topic = models.Topic(
        name="Healthcare", description="", color="#000", org_id=org.id,
    )
    db.add(topic)
    db.flush()
    proposal = models.Proposal(
        title="t", body="", author_id=user.id, status="voting", org_id=org.id,
    )
    db.add(proposal)
    db.flush()
    assert org.parent_org_id is None
    assert topic.sub_org_id is None
    assert proposal.sub_org_id is None
    # No sub-org rows should exist after the parent-org-only flow runs.
    assert db.query(models.SubOrgMembership).count() == 0
