"""Phase 9 — Polis pure-layer + service-layer scope helpers.

Mirrors `delegation_engine.eligible_voter_ids_for_proposal` for the Polis
artifact. Sub-org-scoped Polises follow Phase 8.5 Decision 6 (parent-org
admin implicit power) and Decision 7 (default visible-with-opt-out) —
both rules are read-time, not stored.

Kept in its own module rather than tacked onto delegation_engine.py
because Polis isn't part of the delegation graph; future consolidation
into a generic `scope.py` is fine when more artifact types arrive.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

import models


# Phase 12 — Role.system_key sets used by the SQL-bulk role-tier joins.
# Legacy string column ('admin', 'owner') is dropped; we now join through
# the Role table to access system_key. Kept as constants so the repeated
# joins below stay symmetric and self-documenting.
_ADMIN_TIER_SYSTEM_KEYS = ("admin", "steward")
_MODERATOR_TIER_SYSTEM_KEYS = ("moderator", "admin", "steward")


def eligible_viewers_for_polis(
    db: Session, polis: models.Polis,
) -> set[str]:
    """Return the set of user IDs who can view (and participate in) a Polis.

    Phase 9 Decision 5 — visibility mirrors topics/proposals via Phase 8.5
    Decisions 3, 7, 9.

    Org-wide Polis (``sub_org_id`` IS NULL):
      - All active OrgMembership members of ``polis.org_id``.

    Sub-org-scoped Polis (``sub_org_id`` IS NOT NULL):
      - All active SubOrgMembership members of ``polis.sub_org_id``.
      - PLUS active OrgMembership admins/owners of the parent org
        (Decision 6 — parent-org admin implicit power).
      - PLUS, when the sub-org's ``settings.private`` is False (default),
        all active parent-org members (Decision 7 — default visibility).

    Implementation notes:
      - The "parent-org-wide visibility unless private" rule reads
        ``polis.sub_organization.settings.private`` directly on the
        Organization row. If the sub-org has no settings or no
        ``private`` key, we treat that as "not private" (default
        visibility). This matches how the proposal-list scope filter
        treats the same flag.
      - Returns a set so callers can do membership checks in O(1).
    """
    sub_org_id = polis.sub_org_id
    if sub_org_id is None:
        # Org-wide: all parent-org members.
        rows = db.query(models.OrgMembership.user_id).filter(
            models.OrgMembership.org_id == polis.org_id,
            models.OrgMembership.status == "active",
        ).all()
        return {r.user_id for r in rows}

    # Sub-org-scoped.
    visible: set[str] = set()

    # 1. Active sub-org members.
    sub_rows = db.query(models.SubOrgMembership.user_id).filter(
        models.SubOrgMembership.sub_org_id == sub_org_id,
        models.SubOrgMembership.status == "active",
    ).all()
    visible.update(r.user_id for r in sub_rows)

    # 2. Parent-org admins/Stewards (implicit power) — join through Role.
    parent_admins = (
        db.query(models.OrgMembership.user_id)
        .join(models.Role, models.Role.id == models.OrgMembership.role_id)
        .filter(
            models.OrgMembership.org_id == polis.org_id,
            models.OrgMembership.status == "active",
            models.Role.system_key.in_(_ADMIN_TIER_SYSTEM_KEYS),
        )
        .all()
    )
    visible.update(r.user_id for r in parent_admins)

    # 3. Default visibility — parent-org members unless sub-org is private.
    sub_org = polis.sub_organization
    is_private = False
    if sub_org is not None:
        settings = sub_org.settings or {}
        is_private = bool(settings.get("private", False))
    if not is_private:
        parent_members = db.query(models.OrgMembership.user_id).filter(
            models.OrgMembership.org_id == polis.org_id,
            models.OrgMembership.status == "active",
        ).all()
        visible.update(r.user_id for r in parent_members)

    return visible


def eligible_polis_admin_ids(
    db: Session, polis: models.Polis,
) -> set[str]:
    """Return the set of user IDs who have admin powers over this Polis.

    Phase 9 Decision 6 — admin power matches topic creation:
      - The Polis creator (``polis.created_by``) — moderator+ at the time
        of creation.
      - For sub-org Polises, sub-org admins/owners AND parent-org
        admins/owners (parent-org admin implicit power).
      - For org-wide Polises, parent-org admins/owners and moderators
        (matching topic creation).

    Note: this returns the BROAD admin set (everyone who could archive
    or edit). For per-action permission gating, callers should still
    invoke ``permissions.is_polis_admin`` so the rules are consistent.
    """
    admins: set[str] = {polis.created_by}

    if polis.sub_org_id is not None:
        # Sub-org admins/owners — SubOrgMembership.role is STILL a string
        # column per Phase 12 D2 (sub-org-direct memberships keep the
        # legacy shape until Stage 2+).
        sub_admins = db.query(models.SubOrgMembership.user_id).filter(
            models.SubOrgMembership.sub_org_id == polis.sub_org_id,
            models.SubOrgMembership.status == "active",
            models.SubOrgMembership.role.in_(("admin", "owner")),
        ).all()
        admins.update(r.user_id for r in sub_admins)
        # Parent-org admins/Stewards — OrgMembership join through Role.
        parent_admins = (
            db.query(models.OrgMembership.user_id)
            .join(models.Role, models.Role.id == models.OrgMembership.role_id)
            .filter(
                models.OrgMembership.org_id == polis.org_id,
                models.OrgMembership.status == "active",
                models.Role.system_key.in_(_ADMIN_TIER_SYSTEM_KEYS),
            )
            .all()
        )
        admins.update(r.user_id for r in parent_admins)
    else:
        # Org-wide: parent-org moderator+ — join through Role.
        parent_mods = (
            db.query(models.OrgMembership.user_id)
            .join(models.Role, models.Role.id == models.OrgMembership.role_id)
            .filter(
                models.OrgMembership.org_id == polis.org_id,
                models.OrgMembership.status == "active",
                models.Role.system_key.in_(_MODERATOR_TIER_SYSTEM_KEYS),
            )
            .all()
        )
        admins.update(r.user_id for r in parent_mods)

    return admins
