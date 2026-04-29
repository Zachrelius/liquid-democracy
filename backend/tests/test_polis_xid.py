"""Phase 9 — `polis_service.get_or_create_polis_xid` tests.

Per Decision 4: opaque random per-(user,org) bridging xid, idempotent on
re-invocation, isolated across orgs, audit event emitted ONLY on first
generation.
"""
import models
from polis_service import get_or_create_polis_xid
from tests.conftest import make_user


def _org(db, name, slug):
    o = models.Organization(name=name, slug=slug, settings={})
    db.add(o); db.flush()
    return o


def test_xid_generated_on_first_call(db):
    alice = make_user(db, "alice")
    org = _org(db, "Acme", "acme")
    xid = get_or_create_polis_xid(db, alice.id, org.id)
    assert xid
    assert isinstance(xid, str)
    assert len(xid) >= 16  # token_urlsafe(16) is ~22 chars

    row = db.query(models.PolisXid).filter(
        models.PolisXid.user_id == alice.id,
        models.PolisXid.org_id == org.id,
    ).one()
    assert row.polis_xid == xid


def test_xid_idempotent_returns_same_value(db):
    alice = make_user(db, "alice")
    org = _org(db, "Acme", "acme")
    xid1 = get_or_create_polis_xid(db, alice.id, org.id)
    xid2 = get_or_create_polis_xid(db, alice.id, org.id)
    xid3 = get_or_create_polis_xid(db, alice.id, org.id)
    assert xid1 == xid2 == xid3
    assert db.query(models.PolisXid).count() == 1


def test_xid_per_org_isolated(db):
    alice = make_user(db, "alice")
    org_a = _org(db, "A", "org-a")
    org_b = _org(db, "B", "org-b")
    xid_a = get_or_create_polis_xid(db, alice.id, org_a.id)
    xid_b = get_or_create_polis_xid(db, alice.id, org_b.id)
    assert xid_a != xid_b
    assert db.query(models.PolisXid).count() == 2


def test_xid_per_user_isolated_within_org(db):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    org = _org(db, "A", "org-a")
    xid_a = get_or_create_polis_xid(db, alice.id, org.id)
    xid_b = get_or_create_polis_xid(db, bob.id, org.id)
    assert xid_a != xid_b


def test_audit_event_emitted_on_first_generation_only(db):
    alice = make_user(db, "alice")
    org = _org(db, "Acme", "acme")

    get_or_create_polis_xid(db, alice.id, org.id)
    events_after_first = db.query(models.AuditLog).filter(
        models.AuditLog.action == "polis.xid_generated",
    ).all()
    assert len(events_after_first) == 1
    evt = events_after_first[0]
    assert evt.actor_id == alice.id
    assert evt.target_type == "polis_xid"
    assert evt.details["user_id"] == alice.id
    assert evt.details["org_id"] == org.id
    # Aggregate-only: the actual xid is NOT in the audit details.
    assert "polis_xid" not in evt.details

    # Subsequent calls must not emit again.
    get_or_create_polis_xid(db, alice.id, org.id)
    get_or_create_polis_xid(db, alice.id, org.id)
    events_after_repeat = db.query(models.AuditLog).filter(
        models.AuditLog.action == "polis.xid_generated",
    ).all()
    assert len(events_after_repeat) == 1


def test_xid_audit_actor_overridable(db):
    """When admin generates an xid on a user's behalf, actor differs from user."""
    alice = make_user(db, "alice")
    admin = make_user(db, "admin_user")
    org = _org(db, "Acme", "acme")

    get_or_create_polis_xid(db, alice.id, org.id, actor_id=admin.id)
    evt = db.query(models.AuditLog).filter(
        models.AuditLog.action == "polis.xid_generated",
    ).one()
    assert evt.actor_id == admin.id
    assert evt.details["user_id"] == alice.id
