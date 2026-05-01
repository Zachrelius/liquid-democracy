"""Phase 9 — schema-level tests for `polises` and `polis_xids` tables.

Exercises:
  - default values (status='active', archived_at NULL, JSON column NULL)
  - unique constraint on PolisXid (user_id, org_id)
  - unique constraint on PolisXid.polis_xid
  - status string accepts 'active' / 'archived'
  - Proposal.linked_polis_ids JSON round-trip and NULL-default
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

import models
from tests.conftest import make_user


def _org(db, name: str = "Acme", slug: str = "acme") -> models.Organization:
    o = models.Organization(name=name, slug=slug, settings={})
    db.add(o)
    db.flush()
    return o


def _proposal(db, author: models.User, org: models.Organization) -> models.Proposal:
    p = models.Proposal(
        title="P1", body="", author_id=author.id, org_id=org.id, status="draft",
    )
    db.add(p)
    db.flush()
    return p


# ---------------------------------------------------------------------------
# Polis schema
# ---------------------------------------------------------------------------

def test_polis_defaults_and_persistence(db):
    alice = make_user(db, "alice")
    org = _org(db)
    polis = models.Polis(
        org_id=org.id,
        title="Annual priorities",
        prompt="What should we focus on?",
        created_by=alice.id,
    )
    db.add(polis)
    db.flush()

    assert polis.status == "active"
    assert polis.archived_at is None
    assert polis.sub_org_id is None
    assert polis.polis_conversation_id is None
    assert polis.created_at is not None
    assert polis.updated_at is not None


def test_polis_archive_flow(db):
    alice = make_user(db, "alice")
    org = _org(db)
    polis = models.Polis(
        org_id=org.id, title="P", prompt="Q", created_by=alice.id,
    )
    db.add(polis)
    db.flush()

    polis.status = "archived"
    polis.archived_at = datetime.now(timezone.utc)
    db.flush()

    refreshed = db.query(models.Polis).filter(models.Polis.id == polis.id).one()
    assert refreshed.status == "archived"
    assert refreshed.archived_at is not None


def test_polis_with_sub_org_id(db):
    alice = make_user(db, "alice")
    parent = _org(db, name="Acme", slug="acme")
    sub = models.Organization(
        name="Eng", slug="acme-eng", parent_org_id=parent.id, settings={},
    )
    db.add(sub)
    db.flush()

    polis = models.Polis(
        org_id=parent.id, sub_org_id=sub.id, title="t", prompt="p",
        created_by=alice.id,
    )
    db.add(polis)
    db.flush()

    assert polis.sub_org_id == sub.id
    assert polis.sub_organization is not None
    assert polis.sub_organization.id == sub.id


# ---------------------------------------------------------------------------
# PolisXid schema
# ---------------------------------------------------------------------------

def test_polis_xid_unique_per_user_org(db):
    alice = make_user(db, "alice")
    org = _org(db)
    db.add(models.PolisXid(
        user_id=alice.id, org_id=org.id, polis_xid="abc123",
    ))
    db.flush()

    # Same (user_id, org_id) — should fail.
    db.add(models.PolisXid(
        user_id=alice.id, org_id=org.id, polis_xid="def456",
    ))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_polis_xid_unique_value(db):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    org_a = _org(db, name="A", slug="org-a")
    org_b = _org(db, name="B", slug="org-b")
    db.add(models.PolisXid(
        user_id=alice.id, org_id=org_a.id, polis_xid="shared-token",
    ))
    db.flush()

    # Different (user, org), but same xid value — should fail (xid is global UQ).
    db.add(models.PolisXid(
        user_id=bob.id, org_id=org_b.id, polis_xid="shared-token",
    ))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_polis_xid_per_org_isolation(db):
    """Same user, different orgs -> different xids allowed."""
    alice = make_user(db, "alice")
    org_a = _org(db, name="A", slug="org-a")
    org_b = _org(db, name="B", slug="org-b")
    db.add(models.PolisXid(
        user_id=alice.id, org_id=org_a.id, polis_xid="xid-a",
    ))
    db.add(models.PolisXid(
        user_id=alice.id, org_id=org_b.id, polis_xid="xid-b",
    ))
    db.flush()

    rows = db.query(models.PolisXid).filter(
        models.PolisXid.user_id == alice.id,
    ).all()
    assert len(rows) == 2
    assert {r.polis_xid for r in rows} == {"xid-a", "xid-b"}


# ---------------------------------------------------------------------------
# Proposal.linked_polis_ids
# ---------------------------------------------------------------------------

def test_proposal_linked_polis_ids_default_null(db):
    alice = make_user(db, "alice")
    org = _org(db)
    p = _proposal(db, alice, org)
    assert p.linked_polis_ids is None


def test_proposal_linked_polis_ids_round_trip(db):
    alice = make_user(db, "alice")
    org = _org(db)
    p = _proposal(db, alice, org)
    p.linked_polis_ids = ["uuid-1", "uuid-2"]
    db.flush()

    refreshed = db.query(models.Proposal).filter(models.Proposal.id == p.id).one()
    assert refreshed.linked_polis_ids == ["uuid-1", "uuid-2"]


def test_proposal_linked_polis_ids_empty_list_distinguished_from_null(db):
    alice = make_user(db, "alice")
    org = _org(db)
    p = _proposal(db, alice, org)
    p.linked_polis_ids = []
    db.flush()

    refreshed = db.query(models.Proposal).filter(models.Proposal.id == p.id).one()
    assert refreshed.linked_polis_ids == []
    assert refreshed.linked_polis_ids is not None
