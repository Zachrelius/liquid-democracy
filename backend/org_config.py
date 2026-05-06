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


def get_default_proposal_thresholds(
    org: Optional[models.Organization],
) -> tuple[float, float]:
    """Return ``(pass_threshold, quorum_threshold)`` defaults for new
    proposals in this org.

    Phase 12.5 — central helper for org-level threshold defaults. Reads
    ``Organization.settings['default_pass_threshold']`` and
    ``Organization.settings['default_quorum_threshold']`` if present;
    falls back to the platform-wide defaults (0.50 / 0.40, matching the
    pre-12.5 per-proposal defaults).

    Spec line 122 explicit: NO migration backfill of these keys into
    every existing org's settings JSON — defaults-if-absent here covers
    every existing org transparently. Only orgs whose Steward has
    customised the defaults via the new Org Settings UI will have these
    keys persisted.

    The helper does NOT walk the parent chain via ``get_org_config``:
    the spec's "What this pass is NOT" §"Per-sub-org thresholds" defers
    that to a future pass; sub-orgs inherit parent defaults today by
    virtue of new sub-org-scoped proposals reading the parent org's
    config when they don't have their own.
    """
    if org is None:
        return (0.50, 0.40)
    settings = org.settings or {}
    pass_t = settings.get("default_pass_threshold", 0.50)
    quorum_t = settings.get("default_quorum_threshold", 0.40)
    return (pass_t, quorum_t)


def get_intro_text(org: Optional[models.Organization]) -> Optional[str]:
    """Return the org's optional intro text for the public landing page.

    Phase 14 — markdown-supported text rendered on the org's public splash
    page below name + description. Lives on
    ``Organization.settings.intro_text`` (JSON key in the existing
    ``settings`` column; no schema column added).

    Empty string is treated as None (no section rendered) — the frontend
    hides the intro section entirely when the value is null/empty so
    stewards can clear the field by submitting an empty value.

    Does NOT walk the parent chain (intro is per-org self-presentation,
    not a config knob with sub-org inheritance semantics).
    """
    if org is None:
        return None
    settings = org.settings or {}
    val = settings.get("intro_text")
    if not val:
        return None
    return val


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
