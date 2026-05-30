"""Hook event normalization + redaction (WA3 B1).

Claude Code hooks emit event JSON to the configured hook command's
stdin (per the headless docs). The dashboard's hook_handler.py
forwards that JSON straight to the dashboard server's /api/hook
endpoint. This module is what the server uses to:

  1. Validate the incoming JSON has the load-bearing fields.
  2. Normalize to a small UI-facing shape so the frontend doesn't
     need to know the full Claude Code event surface (30+ event
     types per the docs — we only care about a focused subset for
     a dashboard).
  3. Redact obviously-sensitive args (Bearer tokens, secrets, API
     keys) so they don't render in the UI. This is the WA3 D6
     "no secrets in the UI" rule.

The normalized shape is::

    {
      "id": "<server-assigned monotonic int>",
      "ts": "<UTC ISO timestamp the server received the event>",
      "received_at": <epoch float; sortable>,
      "hook_event_name": "PreToolUse" | "PostToolUse" | ...,
      "session_id": "<claude session uuid or None>",
      "tool_name": "<tool string or None>",
      "tool_input": {<redacted>},
      "tool_response_excerpt": "<short string or None>",
      "duration_ms": <int or None>,
      "cwd": "<cwd or None>",
      "raw_size_bytes": <int>,
    }

We INTENTIONALLY don't pass through the full ``tool_response`` —
some Read events carry whole files. The UI gets a short excerpt; if
the user wants the full payload, the hook handler's stored JSONL
log on disk is the authoritative source.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


# Patterns we redact aggressively. False-positives are fine — this is
# a local dev tool, not a sanitizer for outbound traffic. We err on
# the side of redacting more, not less.
_SECRET_KEY_NAMES = (
    "anthropic_api_key", "api_key", "apikey", "openai_api_key",
    "secret_key", "password", "passwd", "token", "auth_token",
    "bearer", "access_token", "refresh_token", "client_secret",
    "session_token", "private_key", "ssh_key", "github_token",
    "railway_token", "slack_token", "bot_token", "webhook_secret",
)
_BEARER_LINE_RE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{6,}")
_LONG_HEX_RE = re.compile(r"\b[a-fA-F0-9]{32,}\b")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]+\b")


_RESPONSE_EXCERPT_CAP = 280  # chars; tooltip-sized
_TOOL_INPUT_VALUE_CAP = 4_000  # per string value; longer values get truncated + marked


def _redact_string(value: str) -> str:
    """Redact obvious secrets in a string blob. Cheap, regex-only."""
    if not value:
        return value
    out = _BEARER_LINE_RE.sub("Bearer <REDACTED>", value)
    out = _JWT_RE.sub("<REDACTED_JWT>", out)
    out = _LONG_HEX_RE.sub(lambda m: m.group(0)[:6] + "...<REDACTED>", out)
    return out


def _redact_value(key: str, value: Any) -> Any:
    """Recursively redact secret-looking values. If the KEY looks
    secret-named, redact the whole value regardless of contents."""
    if isinstance(key, str) and key.lower() in _SECRET_KEY_NAMES:
        return "<REDACTED>"
    if isinstance(value, str):
        redacted = _redact_string(value)
        if len(redacted) > _TOOL_INPUT_VALUE_CAP:
            return redacted[:_TOOL_INPUT_VALUE_CAP] + "...<TRUNCATED>"
        return redacted
    if isinstance(value, dict):
        return {k: _redact_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(key, v) for v in value]
    return value


def _excerpt_response(resp: Any) -> str | None:
    """Render a short tooltip-sized excerpt of a PostToolUse response.
    Strings are truncated; dicts get a short keys hint; lists likewise.
    """
    if resp is None:
        return None
    if isinstance(resp, str):
        s = _redact_string(resp)
        return s[:_RESPONSE_EXCERPT_CAP] + ("..." if len(s) > _RESPONSE_EXCERPT_CAP else "")
    if isinstance(resp, dict):
        # Common Claude Code shape: {"type": "text", "file": {...}} for Read,
        # {"output": "...", "exit_code": N} for Bash, etc. Pull the most
        # interesting bit instead of dumping the whole dict.
        if "content" in resp and isinstance(resp["content"], str):
            return _excerpt_response(resp["content"])
        if "output" in resp:
            tail = f" (exit={resp['exit_code']})" if "exit_code" in resp else ""
            return _excerpt_response(resp["output"]) + tail if isinstance(resp.get("output"), str) else f"<dict keys={list(resp.keys())[:6]}>{tail}"
        if isinstance(resp.get("file"), dict) and "content" in resp["file"]:
            return _excerpt_response(resp["file"]["content"])
        keys = list(resp.keys())[:8]
        return f"<dict keys={keys}>"
    if isinstance(resp, list):
        return f"<list len={len(resp)}>"
    return str(resp)[:_RESPONSE_EXCERPT_CAP]


def normalize_event(raw: dict[str, Any], event_id: int, raw_size_bytes: int) -> dict[str, Any]:
    """Take a raw hook event from the handler, return the UI shape."""
    received_at = datetime.now(timezone.utc)
    tool_input = raw.get("tool_input")
    if isinstance(tool_input, dict):
        tool_input = _redact_value("tool_input", tool_input)
    elif tool_input is not None:
        tool_input = _redact_value("tool_input", tool_input)

    return {
        "id": event_id,
        "ts": received_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "received_at": received_at.timestamp(),
        "hook_event_name": raw.get("hook_event_name") or "?",
        "session_id": raw.get("session_id"),
        "tool_name": raw.get("tool_name"),
        "tool_input": tool_input,
        "tool_response_excerpt": _excerpt_response(raw.get("tool_response")),
        "duration_ms": raw.get("duration_ms"),
        "cwd": raw.get("cwd"),
        "permission_mode": raw.get("permission_mode"),
        "raw_size_bytes": raw_size_bytes,
    }
