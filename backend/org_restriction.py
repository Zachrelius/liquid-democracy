"""Phase 87 (B-10) — platform-moderation takedown helpers.

Two tools, both platform-admin controlled via ``Organization.platform_restriction``:

  * ``delisted``  — org keeps working for members but is forced out of every
    PUBLIC surface. Enforced at read/serve time (never by overwriting the
    org's stored discoverability), so a revert restores the prior config.
  * ``suspended`` — org inaccessible to everyone except platform admins. All
    rows stay intact; a revert fully restores access.

These helpers are the single source of truth for "is this org restricted and
what does that mean at this surface". Keep enforcement here rather than
scattering string comparisons across the routes.
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException

import models


RESTRICTION_NONE = None
RESTRICTION_DELISTED = "delisted"
RESTRICTION_SUSPENDED = "suspended"

VALID_RESTRICTIONS = {RESTRICTION_DELISTED, RESTRICTION_SUSPENDED}

# Shown to an org's own admins when they view settings on a delisted org.
DELISTED_ADMIN_NOTICE = (
    "This organization has been restricted from public listing by platform "
    "moderation."
)


def is_delisted(org: "models.Organization") -> bool:
    return getattr(org, "platform_restriction", None) == RESTRICTION_DELISTED


def is_suspended(org: "models.Organization") -> bool:
    return getattr(org, "platform_restriction", None) == RESTRICTION_SUSPENDED


def effective_discoverability(org: "models.Organization") -> str:
    """The discoverability a PUBLIC surface should honor. A delisted org is
    forced to ``hidden`` regardless of its stored value; otherwise the stored
    value stands. (Suspension is handled separately — a suspended org 404s
    everywhere, not just publicly.)"""
    if is_delisted(org) or is_suspended(org):
        return "hidden"
    return getattr(org, "discoverability", "listed")


def _is_platform_admin(user: Optional["models.User"]) -> bool:
    return bool(user is not None and getattr(user, "is_admin", False))


def assert_org_accessible(
    org: Optional["models.Organization"],
    current_user: Optional["models.User"],
) -> None:
    """Raise a clean 404 when ``org`` is suspended and the caller is not a
    platform admin. Suspension makes the org indistinguishable from a
    non-existent one for members and non-members alike; platform admins pass
    through so they can review + revert. No-op for non-suspended orgs.
    """
    if org is None:
        return
    if is_suspended(org) and not _is_platform_admin(current_user):
        raise HTTPException(status_code=404, detail="Organization not found")
