"""Phase 9 — `permissions.is_polis_admin` tests.

Decision 6 mirror: creator OR sub-org admin OR parent-org admin (implicit
power on sub-org Polises). For org-wide Polises, moderator+ tier matches
topic creation.
"""
import models
from permissions import is_polis_admin
from tests.conftest import make_user, make_org_membership


def _org(db, name, slug, *, parent_id=None):
    o = models.Organization(name=name, slug=slug, parent_org_id=parent_id, settings={})
    db.add(o); db.flush()
    return o


def _membership(db, user, org, *, role="member"):
    return make_org_membership(
        db, user_id=user.id, org_id=org.id, role=role, status="active",
    )


def _sub_membership(db, user, sub, *, role="member"):
    m = models.SubOrgMembership(user_id=user.id, sub_org_id=sub.id, role=role, status="active")
    db.add(m); db.flush()
    return m


def _polis(db, org, sub, creator):
    p = models.Polis(
        org_id=org.id, sub_org_id=sub.id if sub else None,
        title="P", prompt="Q", created_by=creator.id,
    )
    db.add(p); db.flush()
    return p


# ---------------------------------------------------------------------------
# Org-wide Polis
# ---------------------------------------------------------------------------

def test_org_wide_creator_is_admin(db):
    parent = _org(db, "Acme", "acme")
    alice = make_user(db, "alice")
    _membership(db, alice, parent, role="moderator")
    polis = _polis(db, parent, None, alice)
    assert is_polis_admin(db, alice.id, polis) is True


def test_org_wide_parent_org_admin_is_admin(db):
    parent = _org(db, "Acme", "acme")
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    _membership(db, alice, parent, role="moderator")
    _membership(db, bob, parent, role="admin")
    polis = _polis(db, parent, None, alice)
    assert is_polis_admin(db, bob.id, polis) is True


def test_org_wide_member_is_not_admin(db):
    parent = _org(db, "Acme", "acme")
    alice = make_user(db, "alice")
    carol = make_user(db, "carol")
    _membership(db, alice, parent, role="moderator")
    _membership(db, carol, parent, role="member")
    polis = _polis(db, parent, None, alice)
    assert is_polis_admin(db, carol.id, polis) is False


def test_org_wide_non_member_is_not_admin(db):
    parent = _org(db, "Acme", "acme")
    alice = make_user(db, "alice")
    eve = make_user(db, "eve")  # not in org
    _membership(db, alice, parent, role="moderator")
    polis = _polis(db, parent, None, alice)
    assert is_polis_admin(db, eve.id, polis) is False


# ---------------------------------------------------------------------------
# Sub-org Polis
# ---------------------------------------------------------------------------

def test_sub_org_creator_is_admin(db):
    parent = _org(db, "Acme", "acme")
    sub = _org(db, "Eng", "acme-eng", parent_id=parent.id)
    dave = make_user(db, "dave")
    _membership(db, dave, parent, role="member")
    _sub_membership(db, dave, sub, role="admin")
    polis = _polis(db, parent, sub, dave)
    assert is_polis_admin(db, dave.id, polis) is True


def test_sub_org_admin_is_admin(db):
    parent = _org(db, "Acme", "acme")
    sub = _org(db, "Eng", "acme-eng", parent_id=parent.id)
    dave = make_user(db, "dave")    # creator
    eve = make_user(db, "eve")      # other sub-org admin
    _membership(db, dave, parent, role="member")
    _membership(db, eve, parent, role="member")
    _sub_membership(db, dave, sub, role="admin")
    _sub_membership(db, eve, sub, role="admin")
    polis = _polis(db, parent, sub, dave)
    assert is_polis_admin(db, eve.id, polis) is True


def test_sub_org_parent_admin_is_admin_via_implicit_power(db):
    """Decision 6: parent-org admin retains implicit sub-org admin power."""
    parent = _org(db, "Acme", "acme")
    sub = _org(db, "Eng", "acme-eng", parent_id=parent.id)
    alice = make_user(db, "alice")  # parent-org admin
    dave = make_user(db, "dave")    # sub-org admin (creator)
    _membership(db, alice, parent, role="admin")
    _membership(db, dave, parent, role="member")
    _sub_membership(db, dave, sub, role="admin")
    polis = _polis(db, parent, sub, dave)
    assert is_polis_admin(db, alice.id, polis) is True


def test_sub_org_plain_member_is_not_admin(db):
    parent = _org(db, "Acme", "acme")
    sub = _org(db, "Eng", "acme-eng", parent_id=parent.id)
    dave = make_user(db, "dave")
    bob = make_user(db, "bob")
    _membership(db, dave, parent, role="member")
    _membership(db, bob, parent, role="member")
    _sub_membership(db, dave, sub, role="admin")
    _sub_membership(db, bob, sub, role="member")
    polis = _polis(db, parent, sub, dave)
    assert is_polis_admin(db, bob.id, polis) is False


def test_sub_org_outsider_is_not_admin(db):
    parent = _org(db, "Acme", "acme")
    sub = _org(db, "Eng", "acme-eng", parent_id=parent.id)
    dave = make_user(db, "dave")
    eve = make_user(db, "eve")  # not in either
    _sub_membership(db, dave, sub, role="admin")
    polis = _polis(db, parent, sub, dave)
    assert is_polis_admin(db, eve.id, polis) is False
