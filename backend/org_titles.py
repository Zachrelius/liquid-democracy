"""Phase 47 — Org titles / offices service.

The title concept is **additive** over the platform role model. Per
locked decision D2:

  * Roles (steward/admin/moderator/member) remain the source of truth
    for permissions.
  * The cardinality floor in ``governance.py`` reads roles, not titles.
  * Titles are a labeling + binding layer that optionally maps to a
    role. When a title binds a role, assigning/revoking the title flows
    through the existing 45a/45b role-assignment machinery — it does
    not reimplement permission assignment.

System titles (Steward, Admin) per D6 are seeded per-org and exist as
a label layer over the existing roles. Their "holders" are derived at
response-build time from the membership role; they are NOT recorded in
``org_title_assignments`` to avoid a role-vs-title sync problem.

Custom titles ARE recorded in ``org_title_assignments``. When a custom
title binds a role, the assignment endpoint:

  * Single-holder + bound steward: routes through the existing
    transfer-stewardship semantic (atomic swap with current steward).
  * Single-holder + bound admin/moderator: bumps the holder's role to
    the bound role.
  * Multi-holder + bound non-steward: bumps each new holder's role.
  * Bound steward in admin_council mode: rejected (no steward seat).
  * Revocation: drops the holder's role only if the floor allows
    (mirrors the 45a/45b removal guards). System titles cannot be
    revoked directly — manage steward/admin via the existing
    transfer-stewardship / change-member-role flows.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

import models


SYSTEM_TITLE_DEFINITIONS: list[dict] = [
    {
        "name": "Steward",
        "bound_role": "steward",
        "cardinality_mode": "single",
        "max_holders": None,
        "fill_method": "assigned",
        "display_order": 0,
    },
    {
        "name": "Admin",
        "bound_role": "admin",
        "cardinality_mode": "multi",
        "max_holders": None,
        "fill_method": "assigned",
        "display_order": 10,
    },
]


def seed_system_titles_for_org(db: Session, org_id: str) -> None:
    """Seed the two system titles (Steward, Admin) for ``org_id`` if
    they are missing. Idempotent — safe to call on an already-seeded
    org (does nothing).

    Used by:
      * ``create_organization`` for brand-new orgs.
      * The Phase 47 migration backfills the same set for existing
        orgs (raw SQL there, equivalent shape).
    """
    existing = (
        db.query(models.OrgTitle)
        .filter(
            models.OrgTitle.org_id == org_id,
            models.OrgTitle.is_system == True,  # noqa: E712
        )
        .all()
    )
    existing_names = {t.name for t in existing}
    for defn in SYSTEM_TITLE_DEFINITIONS:
        if defn["name"] in existing_names:
            continue
        db.add(models.OrgTitle(
            org_id=org_id,
            name=defn["name"],
            bound_role=defn["bound_role"],
            cardinality_mode=defn["cardinality_mode"],
            max_holders=defn["max_holders"],
            fill_method=defn["fill_method"],
            is_system=True,
            display_order=defn["display_order"],
        ))
    db.flush()


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_VALID_BOUND_ROLES: frozenset[str] = frozenset(
    {"steward", "admin", "moderator", "member"}
)
_VALID_CARDINALITY: frozenset[str] = frozenset({"single", "multi"})
_VALID_FILL_METHODS: frozenset[str] = frozenset(
    {"assigned", "elected", "both"}
)


def validate_title_input(
    *,
    name: Optional[str],
    bound_role: Optional[str],
    cardinality_mode: Optional[str],
    max_holders: Optional[int],
    fill_method: Optional[str],
) -> None:
    """Raise HTTPException(400) on invalid title-config values. Used
    by both CREATE and UPDATE endpoints; PATCH passes None for any
    field the client didn't touch (those are skipped)."""
    if name is not None:
        if not isinstance(name, str) or not name.strip():
            raise HTTPException(status_code=400, detail="Title name is required")
        if len(name) > 80:
            raise HTTPException(
                status_code=400, detail="Title name max 80 chars",
            )
    if bound_role is not None:
        if bound_role not in _VALID_BOUND_ROLES and bound_role != "":
            raise HTTPException(
                status_code=400,
                detail=(
                    f"bound_role must be one of {sorted(_VALID_BOUND_ROLES)} "
                    "or omitted for a pure-label title"
                ),
            )
    if cardinality_mode is not None:
        if cardinality_mode not in _VALID_CARDINALITY:
            raise HTTPException(
                status_code=400,
                detail=f"cardinality_mode must be one of {sorted(_VALID_CARDINALITY)}",
            )
    if max_holders is not None:
        if not isinstance(max_holders, int) or max_holders < 1:
            raise HTTPException(
                status_code=400,
                detail="max_holders must be a positive integer",
            )
    if fill_method is not None:
        if fill_method not in _VALID_FILL_METHODS:
            raise HTTPException(
                status_code=400,
                detail=f"fill_method must be one of {sorted(_VALID_FILL_METHODS)}",
            )


def assignment_count(db: Session, title_id: str) -> int:
    return (
        db.query(models.OrgTitleAssignment)
        .filter(models.OrgTitleAssignment.title_id == title_id)
        .count()
    )


def is_holder(db: Session, title_id: str, user_id: str) -> bool:
    return (
        db.query(models.OrgTitleAssignment)
        .filter(
            models.OrgTitleAssignment.title_id == title_id,
            models.OrgTitleAssignment.user_id == user_id,
        )
        .first()
        is not None
    )


def system_titles_for_role(
    db: Session, org_id: str, role_system_key: Optional[str],
) -> list[models.OrgTitle]:
    """Return the system titles whose bound_role matches the user's
    role. Per D6 system titles are a label layer over the role: a
    steward sees the "Steward" system title; an admin sees the "Admin"
    one. Returns an empty list for moderator/member (no system title
    seeded for those today).
    """
    if role_system_key not in ("steward", "admin"):
        return []
    return (
        db.query(models.OrgTitle)
        .filter(
            models.OrgTitle.org_id == org_id,
            models.OrgTitle.is_system == True,  # noqa: E712
            models.OrgTitle.bound_role == role_system_key,
        )
        .all()
    )


def custom_titles_for_user(
    db: Session, org_id: str, user_id: str,
) -> list[models.OrgTitle]:
    """Return the custom (non-system) titles the user holds in this
    org via ``org_title_assignments``."""
    rows = (
        db.query(models.OrgTitle)
        .join(
            models.OrgTitleAssignment,
            models.OrgTitleAssignment.title_id == models.OrgTitle.id,
        )
        .filter(
            models.OrgTitle.org_id == org_id,
            models.OrgTitle.is_system == False,  # noqa: E712
            models.OrgTitleAssignment.user_id == user_id,
        )
        .order_by(models.OrgTitle.display_order, models.OrgTitle.name)
        .all()
    )
    return rows


def held_titles_for_member(
    db: Session, org_id: str, user_id: str,
    role_system_key: Optional[str],
) -> list[str]:
    """Return the user's held-title NAMES on this org, sorted by
    display order. Combines system titles (derived from role) +
    custom titles (from assignments).
    """
    out: list[str] = []
    for t in system_titles_for_role(db, org_id, role_system_key):
        out.append(t.name)
    for t in custom_titles_for_user(db, org_id, user_id):
        out.append(t.name)
    return out


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def grant_title(
    db: Session,
    title: models.OrgTitle,
    user_id: str,
    granted_by: Optional[str],
) -> models.OrgTitleAssignment:
    """Insert an OrgTitleAssignment row. Caller is responsible for
    cardinality + permission + floor checks BEFORE calling. Idempotent
    on (title_id, user_id) per the DB unique constraint — re-grant
    raises an HTTPException(400) so the caller can surface it.
    """
    if title.is_system:
        raise HTTPException(
            status_code=400,
            detail=(
                "System titles are derived from the member's role and "
                "cannot be assigned directly. Use the existing "
                "transfer-stewardship or change-member-role flows."
            ),
        )
    if is_holder(db, title.id, user_id):
        raise HTTPException(
            status_code=400, detail="User already holds this title",
        )
    row = models.OrgTitleAssignment(
        title_id=title.id,
        user_id=user_id,
        granted_by=granted_by,
    )
    db.add(row)
    db.flush()
    return row


def revoke_title(
    db: Session, title: models.OrgTitle, user_id: str,
) -> bool:
    """Delete the (title, user) assignment row if it exists. Returns
    True iff a row was removed.

    System titles cannot be revoked here (per D6 they reflect the
    role; demote via transfer-stewardship / change-member-role).
    Caller is responsible for floor/permission checks BEFORE calling.
    """
    if title.is_system:
        raise HTTPException(
            status_code=400,
            detail=(
                "System titles cannot be revoked directly. Use the "
                "existing role-change flows."
            ),
        )
    existing = (
        db.query(models.OrgTitleAssignment)
        .filter(
            models.OrgTitleAssignment.title_id == title.id,
            models.OrgTitleAssignment.user_id == user_id,
        )
        .first()
    )
    if existing is None:
        return False
    db.delete(existing)
    db.flush()
    return True
