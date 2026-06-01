"""Phase 44 — Per-org opt-in + threshold + window settings.

Stored under ``Organization.settings["multi_admin_approval"]`` per Phase
44 D1. Shape::

    {
      "enabled": bool,
      "thresholds": {
        "<action_type>": int,
        ...
      },
      "window_hours": int,
    }

Missing keys fall back to platform defaults (feature off; default
thresholds; default window). Reads are tolerant of partial or absent
configuration — any org that has never touched the feature behaves
exactly as today.
"""
from __future__ import annotations

from typing import Optional

import models


# Platform defaults — applied when an org has the feature enabled but
# hasn't customized a specific knob. Per D3 the floor is 2 across the
# board (1 = no ratification at all, which is the default-off state).
DEFAULT_THRESHOLDS: dict[str, int] = {
    "member.remove": 2,
    "topic.delete": 2,
    "role_permissions.edit": 2,
    "org.delete": 2,
    # Phase 48 Stage 3 D12 — council→single_steward revert.
    "org.governance_mode_revert": 2,
}

DEFAULT_WINDOW_HOURS: int = 72


def _config(org: models.Organization) -> dict:
    """Return the multi_admin_approval sub-config dict, or {}.

    Tolerates ``settings is None`` (legacy/seeded orgs sometimes have
    NULL) and ``settings`` of unexpected shape (returns empty dict
    rather than raising — read-side never blows up on bad config).
    """
    raw = getattr(org, "settings", None) or {}
    if not isinstance(raw, dict):
        return {}
    sub = raw.get("multi_admin_approval", {})
    if not isinstance(sub, dict):
        return {}
    return sub


def is_enabled(org: models.Organization) -> bool:
    """True if the org has opted in to multi-admin approval."""
    return bool(_config(org).get("enabled", False))


def threshold_for(org: models.Organization, action_type: str) -> int:
    """Return the configured threshold for this action type, or the
    platform default. Always ≥ 1 (callers' deadlock-guard logic relies
    on a positive integer).
    """
    cfg = _config(org)
    thresholds = cfg.get("thresholds", {})
    if isinstance(thresholds, dict):
        v = thresholds.get(action_type)
        if isinstance(v, int) and v >= 1:
            return v
    return DEFAULT_THRESHOLDS.get(action_type, 2)


def window_hours(org: models.Organization) -> int:
    """Return the configured expiry window in hours, or the platform
    default (72). Always ≥ 1.
    """
    cfg = _config(org)
    v = cfg.get("window_hours")
    if isinstance(v, int) and v >= 1:
        return v
    return DEFAULT_WINDOW_HOURS


def is_action_wrapped(org: models.Organization, action_type: str) -> bool:
    """True iff (a) the org has opted in AND (b) this action type is in
    the wrapped set. Off-org or non-wrapped action → False, and the
    direct execution path takes over.
    """
    if not is_enabled(org):
        return False
    from .registry import is_known_action_type
    return is_known_action_type(action_type)


def normalize_config_input(raw: Optional[dict]) -> dict:
    """Sanitize a settings PATCH payload before writing it into
    ``Organization.settings["multi_admin_approval"]``.

    Drops unknown keys; coerces threshold + window_hours to int with a
    floor of 1; silently drops thresholds for unknown action types.
    Returns a fresh dict safe to merge.
    """
    from .registry import is_known_action_type

    if not isinstance(raw, dict):
        return {"enabled": False, "thresholds": {}, "window_hours": DEFAULT_WINDOW_HOURS}

    out: dict = {"enabled": bool(raw.get("enabled", False))}

    thresholds_raw = raw.get("thresholds", {})
    if isinstance(thresholds_raw, dict):
        thresholds: dict[str, int] = {}
        for k, v in thresholds_raw.items():
            if not isinstance(k, str) or not is_known_action_type(k):
                continue
            if isinstance(v, bool):
                continue
            if not isinstance(v, int):
                try:
                    v = int(v)
                except (TypeError, ValueError):
                    continue
            if v < 1:
                v = 1
            thresholds[k] = v
        out["thresholds"] = thresholds
    else:
        out["thresholds"] = {}

    wh = raw.get("window_hours")
    if isinstance(wh, bool):
        wh = None
    if isinstance(wh, int) and wh >= 1:
        out["window_hours"] = wh
    elif isinstance(wh, str) and wh.isdigit() and int(wh) >= 1:
        out["window_hours"] = int(wh)
    else:
        out["window_hours"] = DEFAULT_WINDOW_HOURS

    return out
