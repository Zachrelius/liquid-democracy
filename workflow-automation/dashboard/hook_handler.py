"""Claude Code hook handler — forwards events to the dashboard server.

Configure in ``.claude/settings.local.json`` (or `~/.claude/settings.json`
for a user-wide hook). Example::

    {
      "hooks": {
        "PreToolUse": [
          {
            "hooks": [{
              "type": "command",
              "command": "<python> <path>/dashboard/hook_handler.py",
              "timeout": 10
            }]
          }
        ],
        "PostToolUse": [
          {
            "hooks": [{
              "type": "command",
              "command": "<python> <path>/dashboard/hook_handler.py",
              "timeout": 10
            }]
          }
        ]
      }
    }

The hook command receives event JSON on stdin. This script forwards
that JSON to the dashboard's ``/api/hook`` endpoint via a short HTTP
POST. It is deliberately tiny + best-effort: if the dashboard isn't
running, the hook handler logs and exits 0 (no decision returned,
non-blocking for the Code session).

Configurable via env var ``WA3_DASHBOARD_URL`` (default
``http://127.0.0.1:8765``). Timeout is short (1.5s) so a hung
dashboard doesn't delay the Code session.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


DEFAULT_URL = "http://127.0.0.1:8765"
TIMEOUT_S = 1.5


def main() -> int:
    base = os.environ.get("WA3_DASHBOARD_URL", DEFAULT_URL).rstrip("/")
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    # Validate the JSON so we don't ship garbage if Claude Code ever
    # sends a non-JSON payload (shouldn't happen per the docs, but
    # cheap to guard).
    try:
        json.loads(raw)
    except json.JSONDecodeError:
        # Don't block the Code session; just silently exit.
        return 0
    try:
        req = urllib.request.Request(
            f"{base}/api/hook",
            data=raw.encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            resp.read()  # drain
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        # Dashboard not running, port closed, network blip — never
        # block the Code session. Hooks should be invisible when the
        # dashboard isn't listening.
        pass
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
