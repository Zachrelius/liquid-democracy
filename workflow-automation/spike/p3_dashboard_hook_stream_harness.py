"""WA2 P3 — Claude Code hook event-stream probe (best-effort).

Confirms the `disler/claude-code-hooks-multi-agent-observability` seam
is the right mechanism for the WA3 at-desk dashboard. Goal is NOT to
build a dashboard — only to confirm that:

  1. Claude Code hooks can be configured in a project-local
     ``.claude/settings.local.json`` and they fire on tool use.
  2. Hook scripts can receive event JSON on stdin and write it to a
     persistent stream (file, here — a WebSocket in WA3).
  3. A dispatched `claude -p` run produces a meaningful event stream
     a downstream UI could render live.

If the seam works, WA3 builds the WebSocket + HTML on top of this
pattern. If it doesn't, we need a different observability seam
(streaming-JSON output parsing from -p stdout is the fallback per
the headless docs).

The harness writes hook config + a tiny hook handler script to a
scratch cwd, runs `claude -p` with a small "read a file" task there,
collects the emitted events from the log file, and reports:

  * Number of PreToolUse + PostToolUse events emitted.
  * Tool names observed (e.g. Read, Bash).
  * Round-trip latency hint.
  * Sample event JSON for inspection.

Usage::

    python -m workflow-automation.spike.p3_dashboard_hook_stream_harness \\
        --cwd /tmp/wa2_p3_cwd --out /tmp/wa2_p3_out/result.json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


CLAUDE_TIMEOUT_S = 120


def _claude_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    return env


def _setup(cwd: Path) -> tuple[Path, Path]:
    """Write the .claude/settings.local.json hook config + the hook
    handler script. The handler appends event JSON (one per line) to
    a log file so the test can read back what fired.

    Returns (settings_path, events_log_path).
    """
    cwd.mkdir(parents=True, exist_ok=True)
    (cwd / ".claude").mkdir(parents=True, exist_ok=True)

    events_log = cwd / "hook_events.jsonl"
    handler_script = cwd / "hook_handler.py"

    # Hook handler: read JSON from stdin, append a single JSONL line
    # to the events log, exit 0 (non-blocking — no decision).
    handler_script.write_text(
        '"""Append hook event JSON (read from stdin) to a JSONL log."""\n'
        "import json, sys, time\n"
        "from pathlib import Path\n"
        f"LOG = Path(r'{events_log}')\n"
        "try:\n"
        "    raw = sys.stdin.read()\n"
        "    event = json.loads(raw) if raw.strip() else {}\n"
        "except Exception as e:\n"
        "    event = {'_parse_error': str(e), '_raw': raw[:500]}\n"
        "event['_received_at'] = time.time()\n"
        "with LOG.open('a', encoding='utf-8') as f:\n"
        "    f.write(json.dumps(event) + '\\n')\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )

    # Settings: emit PreToolUse + PostToolUse for ALL tools. matcher
    # left out → matches everything (per the hooks doc).
    py = sys.executable.replace("\\", "/")
    handler_str = str(handler_script).replace("\\", "/")
    settings = {
        "hooks": {
            "PreToolUse": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"\"{py}\" \"{handler_str}\"",
                            "timeout": 30,
                        }
                    ]
                }
            ],
            "PostToolUse": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"\"{py}\" \"{handler_str}\"",
                            "timeout": 30,
                        }
                    ]
                }
            ],
        }
    }
    settings_path = cwd / ".claude" / "settings.local.json"
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")

    # Also create a tiny file for the agent to read (the tool-call
    # target — gives us a deterministic PreToolUse/PostToolUse).
    (cwd / "sample.txt").write_text(
        "Hello from the P3 hook-stream probe. This file exists so the "
        "dispatched claude -p has something to read with the Read tool, "
        "which gives us a deterministic tool-call event to observe.\n",
        encoding="utf-8",
    )

    # Clear any previous log.
    if events_log.exists():
        events_log.unlink()
    return settings_path, events_log


def _run_claude(cwd: Path, prompt: str) -> dict:
    cmd = [
        "claude", "-p", "--dangerously-skip-permissions",
        "--output-format", "json",
    ]
    started_at = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=_claude_env(),
            input=prompt,
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT_S,
            encoding="utf-8",
            errors="replace",
        )
        elapsed = round(time.time() - started_at, 2)
        try:
            payload = json.loads(proc.stdout) if proc.stdout else {}
        except json.JSONDecodeError:
            payload = {"_parse_error": True, "_stdout_head": proc.stdout[:500]}
        return {
            "exit_code": proc.returncode,
            "elapsed_s": elapsed,
            "stderr_tail": proc.stderr[-1500:] if proc.stderr else "",
            "payload": payload,
        }
    except subprocess.TimeoutExpired:
        return {
            "exit_code": -1,
            "elapsed_s": round(time.time() - started_at, 2),
            "stderr_tail": f"TIMEOUT after {CLAUDE_TIMEOUT_S}s",
            "payload": {},
        }


def _read_events(log: Path) -> list[dict]:
    if not log.is_file():
        return []
    events = []
    for line in log.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            events.append({"_unparseable": line[:200]})
    return events


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cwd", type=str, required=True)
    parser.add_argument("--out", type=str, required=True)
    args = parser.parse_args()

    cwd = Path(args.cwd)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    if os.environ.get("ANTHROPIC_API_KEY"):
        print("[p3] ABORT: ANTHROPIC_API_KEY set.")
        return 2

    print(f"[p3] cwd={cwd}")
    print(f"[p3] out={out}")
    settings_path, events_log = _setup(cwd)
    print(f"[p3] wrote settings={settings_path}")
    print(f"[p3] events log={events_log}")

    prompt = (
        "Read the file `sample.txt` in the current directory and quote "
        "the first sentence. Then stop. Don't run any other tool."
    )
    print("[p3] dispatching claude -p with a small Read-tool task...")
    rec = _run_claude(cwd, prompt)
    print(f"[p3] exit={rec['exit_code']} elapsed_s={rec['elapsed_s']}")
    if rec["stderr_tail"]:
        print(f"[p3] stderr tail:\n{rec['stderr_tail']}")

    events = _read_events(events_log)
    print(f"[p3] events captured: {len(events)}")

    # Surface event-name + tool-name counts.
    counts: dict[str, int] = {}
    tool_counts: dict[str, int] = {}
    for ev in events:
        name = ev.get("hook_event_name", "?")
        counts[name] = counts.get(name, 0) + 1
        tn = ev.get("tool_name", "")
        if tn:
            tool_counts[tn] = tool_counts.get(tn, 0) + 1
    print(f"[p3] event_name counts: {counts}")
    print(f"[p3] tool_name counts: {tool_counts}")

    record = {
        "scenario": "hook_stream_probe",
        "elapsed_s": rec["elapsed_s"],
        "exit_code": rec["exit_code"],
        "agent_response_head": (
            ((rec.get("payload") or {}).get("result", "") or "")[:300]
        ),
        "events_captured": len(events),
        "event_name_counts": counts,
        "tool_name_counts": tool_counts,
        "sample_events": events[:3],  # first 3 for inspection
        "events_log_path": str(events_log),
        "stderr_tail": rec["stderr_tail"],
    }
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[p3] wrote {out}")

    # Verdict: hooks fired + we captured at least one PreToolUse +
    # PostToolUse event = the seam works.
    if counts.get("PreToolUse", 0) > 0 and counts.get("PostToolUse", 0) > 0:
        print("[p3] VERDICT: PASS — hooks emit tool-call events; disler seam viable for WA3")
        return 0
    print("[p3] VERDICT: PARTIAL/FAIL — hooks did not produce the expected event types")
    return 1


if __name__ == "__main__":
    sys.exit(main())
