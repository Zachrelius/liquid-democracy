"""Quota / model / cost telemetry (WA3 B5).

Detects the WA2 "out of extra usage · resets HH:MM" string from a
``claude -p --output-format json`` payload and surfaces per-session
model + token + cost telemetry for the dashboard's quota panel.

The dashboard never RUNS ``claude -p`` itself — that's WA4's job.
This module is what the dashboard uses when WA4 (or for now the
test harness) POSTs a `claude -p` result payload at the
``/api/quota/observation`` endpoint, OR what the hook handler does
when it sees a Stop / SessionEnd event carrying usage data.

The "out of extra usage" detection is the key signal. Per WA2 P1,
the response shape on quota exhaustion is::

    result.exit_code == 1
    result.payload.result_text contains
        "out of extra usage · resets HH:MMpm (America/<TZ>)"

We pattern-match the string + extract the reset time so the UI can
render "throttled until 12:30pm America/Port-au-Prince."
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# The exact "out of extra usage" string Phase-42/WA2-P1 observed.
# Capture the reset hh:mm + am/pm + timezone in case the UI wants
# to render countdowns. The model occasionally varies the phrasing
# (eg "extra usage limit" vs "extra usage"); match loosely.
_QUOTA_WALL_RE = re.compile(
    r"out of (?:extra )?(?:usage|credit|capacity)"
    r"(?:.{0,32}?resets?\s+(?P<reset>[0-9]{1,2}:[0-9]{2}\s*(?:am|pm)?(?:\s*\([^)]+\))?))?",
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class QuotaState:
    """Latest observed quota state. Updated incrementally; the UI
    reads a snapshot."""
    throttled: bool = False
    throttle_message: str = ""
    reset_at_text: str = ""
    last_observed_at: str = ""
    # Per-session telemetry. Keyed by session_id.
    sessions: dict[str, dict[str, Any]] = field(default_factory=dict)

    def snapshot(self) -> dict[str, Any]:
        # Limit sessions shown to the 16 most-recently-touched so
        # the API response stays bounded.
        latest = sorted(
            self.sessions.items(),
            key=lambda kv: kv[1].get("last_observed_at", ""),
            reverse=True,
        )[:16]
        return {
            "throttled": self.throttled,
            "throttle_message": self.throttle_message,
            "reset_at_text": self.reset_at_text,
            "last_observed_at": self.last_observed_at,
            "sessions": dict(latest),
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def detect_quota_wall(result_text: str) -> tuple[bool, str]:
    """Return (throttled, reset_at_text).

    ``reset_at_text`` is the parsed reset clause if present (eg
    "12:30pm (America/Port-au-Prince)"), else empty. The dashboard
    renders it verbatim — no clock math needed for v1.
    """
    if not result_text:
        return False, ""
    m = _QUOTA_WALL_RE.search(result_text)
    if not m:
        return False, ""
    reset = m.group("reset") or ""
    return True, reset.strip()


def _extract_usage(payload: dict[str, Any]) -> dict[str, Any]:
    usage = payload.get("usage") or {}
    # The Claude Code JSON output uses cache_read_input_tokens +
    # cache_creation_input_tokens + input_tokens + output_tokens.
    return {
        "input_tokens": usage.get("input_tokens", 0) or 0,
        "output_tokens": usage.get("output_tokens", 0) or 0,
        "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0) or 0,
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0) or 0,
    }


def update_from_claude_result(state: QuotaState, result: dict[str, Any]) -> dict[str, Any]:
    """Apply one ``claude -p --output-format json`` result to the
    quota state. ``result`` is the parsed payload (the dict that
    ``claude -p --output-format json`` returns); may also include a
    top-level ``exit_code`` if the wrapper records that, but we
    don't depend on it.

    Returns the changes diff (handy for the dashboard's "what
    just happened" log).
    """
    state.last_observed_at = _now_iso()

    # Quota-wall detection. We look at multiple potential fields
    # because the wrapper / harness may have placed the error
    # message under "result_text", "result", or "text".
    candidate_strings = []
    for key in ("result_text", "result", "text"):
        v = result.get(key)
        if isinstance(v, str):
            candidate_strings.append(v)
    if "payload" in result and isinstance(result["payload"], dict):
        for key in ("result_text", "result", "text"):
            v = result["payload"].get(key)
            if isinstance(v, str):
                candidate_strings.append(v)

    throttled = False
    reset = ""
    for s in candidate_strings:
        t, r = detect_quota_wall(s)
        if t:
            throttled = True
            reset = r or reset
            state.throttle_message = s.strip()
            break

    if throttled:
        state.throttled = True
        state.reset_at_text = reset
    # We never auto-clear throttled here — the dashboard caller
    # decides when to reset (e.g., on a "throttle expired" probe).

    # Per-session model + tokens. Payload location is either
    # top-level (when caller flattens) or under "payload".
    src = result.get("payload") if isinstance(result.get("payload"), dict) else result
    session_id = src.get("session_id") or result.get("session_id")
    model = (
        src.get("model")
        or (src.get("modelUsage") or {}).get("model")
        or "unknown"
    )
    duration_ms = src.get("duration_ms") or src.get("duration_api_ms")
    total_cost_usd = src.get("total_cost_usd")
    usage = _extract_usage(src)

    if session_id:
        sess = state.sessions.setdefault(session_id, {
            "session_id": session_id,
            "model": model,
            "rounds": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "total_cost_usd_telemetry": 0.0,
            "last_observed_at": "",
        })
        sess["model"] = model  # latest wins
        sess["rounds"] += 1
        sess["input_tokens"] += usage["input_tokens"]
        sess["output_tokens"] += usage["output_tokens"]
        sess["cache_read_input_tokens"] += usage["cache_read_input_tokens"]
        sess["cache_creation_input_tokens"] += usage["cache_creation_input_tokens"]
        if isinstance(total_cost_usd, (int, float)):
            sess["total_cost_usd_telemetry"] += float(total_cost_usd)
        if isinstance(duration_ms, (int, float)):
            sess["last_duration_ms"] = int(duration_ms)
        sess["last_observed_at"] = state.last_observed_at

    return {
        "throttled": throttled,
        "reset_at_text": reset,
        "session_id": session_id,
        "model": model,
        "usage_delta": usage,
        "cost_delta_usd": total_cost_usd if isinstance(total_cost_usd, (int, float)) else None,
    }


def clear_throttle(state: QuotaState) -> None:
    """Manually clear the throttled flag (eg the user hit a 'clear'
    button or the WA4 daemon's quota-recheck probe came back OK)."""
    state.throttled = False
    state.throttle_message = ""
    state.reset_at_text = ""
