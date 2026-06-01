"""Phase 45b — Governance-mode + cardinality-floor helpers.

The per-org ``governance_mode`` field (Phase 45b B1) has two values:

  * ``single_steward`` (default — pre-Phase-45b behavior preserved):
    exactly one Steward seat always exists; OWNER_ONLY_KEYS +
    STEWARD_LOCKED_PERMISSIONS resolve to the Steward; the cardinality
    floor is "≥1 active steward" (the Phase 45a invariant).

  * ``admin_council`` (opt-in): no Steward seat required; governing
    authority is the admin tier; OWNER_ONLY_KEYS + STEWARD_LOCKED_
    PERMISSIONS resolve to any admin (D4/D5); the cardinality floor is
    "≥1 active admin" (D6).

This module is the single source of truth for the mode read + the floor
check. ``role_permissions.has_permission``, the ``remove_member`` /
``change_member_role`` guards, and ``pending_actions/registry.py``'s
``execute_member_remove`` + validator all route through here so the
floor logic can't drift across call sites.

Phase 45c (elections) will read the mode field but does NOT introduce a
third mode — electing a seat-holder is orthogonal to the seat's mode.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

import models


SINGLE_STEWARD = "single_steward"
ADMIN_COUNCIL = "admin_council"

VALID_MODES: frozenset[str] = frozenset({SINGLE_STEWARD, ADMIN_COUNCIL})


def mode_of(org: models.Organization) -> str:
    """Return the org's governance_mode; defaults to single_steward if
    the column is somehow NULL or absent (defensive — the column is
    NOT NULL with a server_default, but pre-migration test fixtures or
    ad-hoc SQL inserts may slip past).
    """
    mode = getattr(org, "governance_mode", None)
    if mode in VALID_MODES:
        return mode
    return SINGLE_STEWARD


def governing_role_key(org: models.Organization) -> str:
    """The role.system_key whose holders hold the org's top-tier
    authority for this mode. Used by D4/D5 (OWNER_ONLY_KEYS +
    STEWARD_LOCKED_PERMISSIONS resolution).
    """
    return "admin" if mode_of(org) == ADMIN_COUNCIL else "steward"


def is_top_tier_role(org: models.Organization, role_system_key: str) -> bool:
    """True if ``role_system_key`` is the org's top governing tier.

    - single_steward mode: only ``steward`` is top-tier.
    - admin_council mode: ``admin`` is top-tier (there's no steward to
      compete with, but if a defensive corruption left a steward row,
      they still count — extending rather than forking is safer).
    """
    if role_system_key == governing_role_key(org):
        return True
    # In council mode, a leftover steward row (shouldn't happen on the
    # default switch path but is defensive) also counts as top-tier.
    if mode_of(org) == ADMIN_COUNCIL and role_system_key == "steward":
        return True
    return False


def count_active_governors(
    db: Session, org: models.Organization, *, exclude_user_id: Optional[str] = None,
) -> int:
    """Count active members of ``org`` whose role is the mode's
    governing tier (steward in single_steward; admin in admin_council),
    AND whose underlying ``User.is_active`` is True.

    A user with an active OrgMembership but a soft-revoked User account
    cannot actually govern (they cannot log in — Phase 39 B1's
    ``_get_user_from_token`` filters ``is_active == True``). For both
    the cardinality floor (D6) and the recovery detection (B4), they
    don't count.

    A leftover steward row in council mode is also counted as a
    governor (see ``is_top_tier_role``) to keep the count truthful
    against unexpected schema state.
    """
    target_role = governing_role_key(org)
    memberships = (
        db.query(models.OrgMembership)
        .filter(
            models.OrgMembership.org_id == org.id,
            models.OrgMembership.status == "active",
        )
        .all()
    )
    n = 0
    for m in memberships:
        if exclude_user_id is not None and m.user_id == exclude_user_id:
            continue
        if m.role_id is None:
            continue
        role = db.get(models.Role, m.role_id)
        if role is None:
            continue
        # User must be active too (can actually log in + exercise auth).
        user = db.get(models.User, m.user_id)
        if user is None or not user.is_active:
            continue
        if role.system_key == target_role:
            n += 1
            continue
        # Defensive: a leftover steward in council mode counts.
        if mode_of(org) == ADMIN_COUNCIL and role.system_key == "steward":
            n += 1
    return n


def at_risk_of_needs_rebootstrap(
    db: Session, org: models.Organization,
) -> bool:
    """True if the org currently has zero active governors.

    Used by Phase 45b B4 to detect the recovery condition. Cheap — the
    same scan as ``count_active_governors``.
    """
    return count_active_governors(db, org) == 0


def check_and_audit_rebootstrap(
    db: Session,
    org: models.Organization,
    *,
    actor_id: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> bool:
    """If ``org`` currently has zero active governors, emit a
    ``org.needs_rebootstrap`` audit event and return True. Otherwise
    return False without emitting.

    Phase 45b B4 — the explicit, audited replacement for silent lockout.
    Call this after any path that can change the active-governor count
    (membership removal, role change, suspension, account soft-revoke,
    governance-mode switch). Idempotent on the trail side — repeated
    calls in the same condition emit one entry per call, which is the
    intended granularity (each "now we've noticed it again" needs a
    timestamp). Callers should be the actor that just made the change.
    """
    if count_active_governors(db, org) > 0:
        return False
    # Late import to avoid a module-cycle with audit_utils (which imports
    # models, which is also imported here).
    from audit_utils import log_audit_event
    log_audit_event(
        db,
        action="org.needs_rebootstrap",
        target_type="organization",
        target_id=org.id,
        actor_id=actor_id,
        details={
            "org_id": org.id,
            "governance_mode": mode_of(org),
        },
        ip_address=ip_address,
    )
    return True
