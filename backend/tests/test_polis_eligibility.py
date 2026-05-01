"""Phase 9 — Polis viewer eligibility tests.

Mirrors `test_eligible_voters.py` for the Polis artifact via Decision 5.
Org-wide Polises are visible to all parent-org members; sub-org Polises
follow Decision 7 default-visible-with-private-opt-out, with parent-org
admins always retaining implicit power per Decision 6.
"""
import models
from polis_engine import eligible_viewers_for_polis, eligible_polis_admin_ids
from tests.conftest import make_user


def _org(db, name: str, slug: str, *, parent_id=None, settings=None):
    o = models.Organization(
        name=name, slug=slug, parent_org_id=parent_id,
        settings=settings or {},
    )
    db.add(o)
    db.flush()
    return o


def _membership(db, user, org, *, role="member", status="active"):
    m = models.OrgMembership(
        user_id=user.id, org_id=org.id, role=role, status=status,
    )
    db.add(m)
    db.flush()
    return m


def _sub_membership(db, user, sub_org, *, role="member", status="active"):
    m = models.SubOrgMembership(
        user_id=user.id, sub_org_id=sub_org.id, role=role, status=status,
    )
    db.add(m)
    db.flush()
    return m


def _polis(db, org_id, sub_org_id, creator):
    p = models.Polis(
        org_id=org_id, sub_org_id=sub_org_id,
        title="P", prompt="Q", created_by=creator.id,
    )
    db.add(p)
    db.flush()
    return p


# ---------------------------------------------------------------------------
# eligible_viewers_for_polis
# ---------------------------------------------------------------------------

def test_org_wide_polis_visible_to_all_parent_members(db):
    parent = _org(db, "Acme", "acme")
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    carol = make_user(db, "carol")
    _membership(db, alice, parent, role="admin")
    _membership(db, bob, parent, role="member")
    _membership(db, carol, parent, role="member", status="suspended")

    polis = _polis(db, parent.id, None, alice)
    viewers = eligible_viewers_for_polis(db, polis)
    assert viewers == {alice.id, bob.id}
    assert carol.id not in viewers  # suspended excluded


def test_sub_org_polis_default_visible_includes_parent_members(db):
    """Decision 7 default — non-private sub-org is visible to parent-org members."""
    parent = _org(db, "Acme", "acme")
    sub = _org(db, "Eng", "acme-eng", parent_id=parent.id, settings={})

    alice = make_user(db, "alice")  # parent-org admin (not in sub)
    bob = make_user(db, "bob")      # sub-org member
    carol = make_user(db, "carol")  # parent-org member only
    dave = make_user(db, "dave")    # not a member of either

    _membership(db, alice, parent, role="admin")
    _membership(db, bob, parent, role="member")
    _membership(db, carol, parent, role="member")
    _sub_membership(db, bob, sub, role="member")

    polis = _polis(db, parent.id, sub.id, alice)
    viewers = eligible_viewers_for_polis(db, polis)
    assert alice.id in viewers
    assert bob.id in viewers
    assert carol.id in viewers  # default-visible
    assert dave.id not in viewers


def test_sub_org_polis_private_excludes_parent_only_members(db):
    """Decision 7 private opt-out — parent-org-only members lose visibility."""
    parent = _org(db, "Acme", "acme")
    sub = _org(
        db, "Eng", "acme-eng", parent_id=parent.id,
        settings={"private": True},
    )

    alice = make_user(db, "alice")  # parent-org admin (Decision 6 implicit)
    bob = make_user(db, "bob")      # sub-org member
    carol = make_user(db, "carol")  # parent-org member, NOT sub-org

    _membership(db, alice, parent, role="admin")
    _membership(db, bob, parent, role="member")
    _membership(db, carol, parent, role="member")
    _sub_membership(db, bob, sub, role="member")

    polis = _polis(db, parent.id, sub.id, alice)
    viewers = eligible_viewers_for_polis(db, polis)
    assert alice.id in viewers       # Decision 6 implicit power
    assert bob.id in viewers          # sub-org member
    assert carol.id not in viewers    # parent-only, sub-org private


def test_sub_org_polis_includes_parent_admin_even_if_not_sub_member(db):
    """Decision 6 — parent-org admin is always a viewer regardless of sub-org membership."""
    parent = _org(db, "Acme", "acme")
    sub = _org(
        db, "Eng", "acme-eng", parent_id=parent.id,
        settings={"private": True},
    )
    alice = make_user(db, "alice")
    _membership(db, alice, parent, role="admin")  # not a sub-org member
    polis = _polis(db, parent.id, sub.id, alice)
    assert alice.id in eligible_viewers_for_polis(db, polis)


def test_sub_org_polis_excludes_inactive_sub_members(db):
    parent = _org(db, "Acme", "acme")
    sub = _org(db, "Eng", "acme-eng", parent_id=parent.id, settings={"private": True})
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    _membership(db, alice, parent, role="admin")
    _membership(db, bob, parent, role="member")
    _sub_membership(db, bob, sub, role="member", status="suspended")

    polis = _polis(db, parent.id, sub.id, alice)
    viewers = eligible_viewers_for_polis(db, polis)
    assert bob.id not in viewers


# ---------------------------------------------------------------------------
# eligible_polis_admin_ids
# ---------------------------------------------------------------------------

def test_admin_set_for_org_wide_polis(db):
    parent = _org(db, "Acme", "acme")
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    carol = make_user(db, "carol")
    _membership(db, alice, parent, role="moderator")  # creator-tier
    _membership(db, bob, parent, role="admin")
    _membership(db, carol, parent, role="member")

    polis = _polis(db, parent.id, None, alice)
    admins = eligible_polis_admin_ids(db, polis)
    assert alice.id in admins   # creator + moderator
    assert bob.id in admins     # admin
    assert carol.id not in admins


def test_admin_set_for_sub_org_polis_includes_parent_admin(db):
    parent = _org(db, "Acme", "acme")
    sub = _org(db, "Eng", "acme-eng", parent_id=parent.id, settings={})
    alice = make_user(db, "alice")  # parent-org admin
    dave = make_user(db, "dave")    # sub-org admin (creator)
    bob = make_user(db, "bob")      # plain sub-org member
    _membership(db, alice, parent, role="admin")
    _sub_membership(db, dave, sub, role="admin")
    _sub_membership(db, bob, sub, role="member")

    polis = _polis(db, parent.id, sub.id, dave)
    admins = eligible_polis_admin_ids(db, polis)
    assert dave.id in admins   # creator + sub-org admin
    assert alice.id in admins  # parent-org admin (Decision 6 implicit)
    assert bob.id not in admins
