"""Org config resolution that walks the parent chain.

Used by config reads where a sub-org should inherit from its parent unless it
sets its own override. See Phase 8.5 spec Decision 9.

Resolution order for a sub-org:
  1. Sub-org's own ``settings`` if the key is present
  2. Parent org's ``settings`` if the key is present
  3. Caller-supplied ``default``

For parent orgs (``parent_org_id IS NULL``), the walk degenerates to a single
lookup followed by the default — bit-for-bit equivalent to the existing
``org.settings.get(key, default)`` pattern, so call sites that don't yet know
about sub-orgs can safely migrate without behavioral change.
"""
from __future__ import annotations

from typing import Any, Optional

import models


# Two-level hierarchy is locked in by Decision 1, but the loop walks
# ``parent_org_id`` defensively until it hits None or this safety bound. A
# cycle or schema drift past 5 hops indicates a bug worth surfacing rather
# than silently returning the default.
_MAX_PARENT_WALK_DEPTH = 5


def get_org_config(
    org: Optional[models.Organization], key: str, default: Any = None,
) -> Any:
    """Resolve a config key for an org, walking the parent chain.

    Order: org's own settings if key present -> parent's settings if key
    present -> default. Two-level only by Decision 1; the loop is bounded
    by walking ``parent_org_id`` until None to be defensive.

    A ``None`` org argument returns the default immediately — useful for
    optional-org callers (e.g., proposals with org_id IS NULL).

    Raises RuntimeError if the parent walk exceeds _MAX_PARENT_WALK_DEPTH;
    that indicates a cycle or schema drift, both of which deserve loud
    failure over silent fallback.
    """
    current: Optional[models.Organization] = org
    depth = 0
    while current is not None:
        if depth >= _MAX_PARENT_WALK_DEPTH:
            raise RuntimeError(
                f"get_org_config exceeded max parent-walk depth "
                f"({_MAX_PARENT_WALK_DEPTH}) for key={key!r} starting at "
                f"org id={getattr(org, 'id', None)}. Cycle or schema drift?"
            )
        settings = getattr(current, "settings", None)
        if isinstance(settings, dict) and key in settings:
            return settings[key]
        # ``parent_org`` is the ORM relationship; duck-typed test objects
        # without this attribute behave as if they had no parent (the walk
        # stops cleanly at the bottom of the chain).
        current = getattr(current, "parent_org", None)
        depth += 1
    return default
