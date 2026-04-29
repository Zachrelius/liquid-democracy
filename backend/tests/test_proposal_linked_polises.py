"""Phase 9 — `Proposal.linked_polis_ids` JSON column behavior + structural-link
validation helpers.

Validation lives in the data layer for now (Session 1 scope). Routes will
call `validate_linked_polis_ids` in Session 2 before persisting a proposal.
The function is pure-DB; no service layer required.
"""
from typing import Optional

import pytest

import models
from tests.conftest import make_user


def _org(db, name="Acme", slug="acme", *, parent_id=None):
    o = models.Organization(name=name, slug=slug, parent_org_id=parent_id, settings={})
    db.add(o); db.flush()
    return o


def _membership(db, user, org, *, role="member"):
    m = models.OrgMembership(user_id=user.id, org_id=org.id, role=role, status="active")
    db.add(m); db.flush()
    return m


def _polis(db, org, sub_org, creator, *, status="active") -> models.Polis:
    p = models.Polis(
        org_id=org.id, sub_org_id=sub_org.id if sub_org else None,
        title="P", prompt="Q", created_by=creator.id, status=status,
    )
    db.add(p); db.flush()
    return p


def _proposal(
    db,
    author,
    org,
    *,
    sub_org_id: Optional[str] = None,
    linked_polis_ids: Optional[list] = None,
) -> models.Proposal:
    p = models.Proposal(
        title="P1", body="", author_id=author.id, org_id=org.id,
        sub_org_id=sub_org_id, status="draft",
        linked_polis_ids=linked_polis_ids,
    )
    db.add(p); db.flush()
    return p


# ---------------------------------------------------------------------------
# Schema round-trip
# ---------------------------------------------------------------------------

def test_proposal_linked_polis_ids_persists_uuids(db):
    alice = make_user(db, "alice")
    org = _org(db)
    polis_a = _polis(db, org, None, alice)
    polis_b = _polis(db, org, None, alice)
    p = _proposal(db, alice, org, linked_polis_ids=[polis_a.id, polis_b.id])
    refreshed = db.query(models.Proposal).filter(models.Proposal.id == p.id).one()
    assert set(refreshed.linked_polis_ids) == {polis_a.id, polis_b.id}


# ---------------------------------------------------------------------------
# Validation helper (in data layer — used by routes in Session 2).
# ---------------------------------------------------------------------------

def _validate_linked_polis_ids(
    db,
    polis_ids: list[str],
    proposal_org_id: str,
    proposal_sub_org_id: Optional[str],
) -> tuple[list[str], list[str]]:
    """Helper used by test_proposal_linked_polises in Session 1 + by routes
    in Session 2.

    Returns (valid_ids, error_messages). For each ID:
      - must exist
      - must be in scope (same org_id; if proposal is sub-org-scoped, the
        Polis must be parent-org-wide OR scoped to the same sub-org)
      - must be `active` (not archived)
    """
    errors: list[str] = []
    valid: list[str] = []
    for pid in polis_ids:
        polis = db.query(models.Polis).filter(models.Polis.id == pid).first()
        if polis is None:
            errors.append(f"Polis {pid} does not exist")
            continue
        if polis.status != "active":
            errors.append(f"Polis {pid} is not active (status={polis.status})")
            continue
        if polis.org_id != proposal_org_id:
            errors.append(f"Polis {pid} belongs to a different org")
            continue
        # Scope check: org-wide Polis is always linkable; sub-org Polis only
        # linkable from a proposal in the same sub-org (or not linkable from
        # a parent-org-wide proposal).
        if polis.sub_org_id is not None:
            if polis.sub_org_id != proposal_sub_org_id:
                errors.append(
                    f"Polis {pid} is sub-org-scoped and cannot be linked "
                    "from a proposal in a different scope"
                )
                continue
        valid.append(pid)
    return valid, errors


def test_validation_accepts_active_org_wide_polis(db):
    alice = make_user(db, "alice")
    org = _org(db)
    polis = _polis(db, org, None, alice)
    valid, errors = _validate_linked_polis_ids(db, [polis.id], org.id, None)
    assert valid == [polis.id]
    assert errors == []


def test_validation_rejects_nonexistent(db):
    alice = make_user(db, "alice")
    org = _org(db)
    valid, errors = _validate_linked_polis_ids(db, ["nope"], org.id, None)
    assert valid == []
    assert any("does not exist" in e for e in errors)


def test_validation_rejects_archived(db):
    alice = make_user(db, "alice")
    org = _org(db)
    polis = _polis(db, org, None, alice, status="archived")
    valid, errors = _validate_linked_polis_ids(db, [polis.id], org.id, None)
    assert valid == []
    assert any("not active" in e for e in errors)


def test_validation_rejects_cross_org(db):
    alice = make_user(db, "alice")
    org_a = _org(db, name="A", slug="a")
    org_b = _org(db, name="B", slug="b")
    polis_b = _polis(db, org_b, None, alice)
    valid, errors = _validate_linked_polis_ids(db, [polis_b.id], org_a.id, None)
    assert valid == []
    assert any("different org" in e for e in errors)


def test_validation_rejects_sub_org_polis_from_org_wide_proposal(db):
    alice = make_user(db, "alice")
    parent = _org(db, name="P", slug="p")
    sub = _org(db, name="S", slug="p-sub", parent_id=parent.id)
    polis_sub = _polis(db, parent, sub, alice)
    # Proposal is parent-org-wide (sub_org_id=None). Sub-org Polis isn't linkable.
    valid, errors = _validate_linked_polis_ids(db, [polis_sub.id], parent.id, None)
    assert valid == []
    assert any("different scope" in e for e in errors)


def test_validation_accepts_org_wide_polis_from_sub_org_proposal(db):
    alice = make_user(db, "alice")
    parent = _org(db, name="P", slug="p")
    sub = _org(db, name="S", slug="p-sub", parent_id=parent.id)
    polis_org_wide = _polis(db, parent, None, alice)
    valid, errors = _validate_linked_polis_ids(db, [polis_org_wide.id], parent.id, sub.id)
    assert valid == [polis_org_wide.id]
    assert errors == []


def test_validation_partial_returns_per_id_errors(db):
    alice = make_user(db, "alice")
    org = _org(db)
    polis_ok = _polis(db, org, None, alice)
    polis_archived = _polis(db, org, None, alice, status="archived")
    valid, errors = _validate_linked_polis_ids(
        db, [polis_ok.id, polis_archived.id, "nope"], org.id, None,
    )
    assert valid == [polis_ok.id]
    assert len(errors) == 2
