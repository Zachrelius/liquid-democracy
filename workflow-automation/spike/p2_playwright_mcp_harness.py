"""WA2 P2 — Playwright MCP via `claude -p` headless QA probe.

Confirms a dispatched `claude -p` agent can:
  1. Load `microsoft/playwright-mcp` from a project-local `.mcp.json`.
  2. Drive a HEADLESS browser against https://www.liquiddemocracy.us/.
  3. Return a structured pass/fail on a read-only scenario (load
     landing page, assert expected text/element present).

This is goal-4 mechanism validation. Replaces the original
"Claude-in-Chrome from a daemon" plan — Phase 42 found Chrome MCP
is absent in `claude -p`, and the 2026-05-30 research established
Playwright MCP as the de-facto autonomous-QA browser layer.

Setup steps embedded in the script (so the closeout captures the
reproducible recipe):
  * `npx @playwright/mcp@latest` runs the server on demand.
  * The .mcp.json next to this harness scopes the MCP to this cwd
    (Phase 42 cwd-discipline carry-forward).
  * `ANTHROPIC_API_KEY` is unset in the subprocess env (Max OAuth).

Output: per-scenario JSON record at `--out`, plus a stdout summary.

Usage::

    python -m workflow-automation.spike.p2_playwright_mcp_harness \\
        --cwd /tmp/wa2_p2_cwd --out /tmp/wa2_p2_out/result.json

The script does NOT install browsers explicitly — the MCP server's
first run handles that. If install fails, the failure is recorded
+ surfaced loudly; do not retry-loop.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


CLAUDE_TIMEOUT_S = 300


# The .mcp.json the dispatched `claude -p` will auto-load. Phase 42
# proved project-local .mcp.json IS loaded in -p mode (it's in --bare
# mode that it's skipped — we explicitly don't pass --bare).
MCP_CONFIG = {
    "mcpServers": {
        "playwright": {
            "command": "npx",
            "args": ["@playwright/mcp@latest"]
        }
    }
}


# The QA prompt is read-only by design. The site is prod; we don't
# touch any auth-gated mutation surface. Assertions target stable
# text on the landing page.
QA_PROMPT = """\
You are an autonomous QA agent. Your job is to read the public landing page
of a website and report a structured pass/fail on three checks.

TARGET: https://www.liquiddemocracy.us/

Use the playwright MCP to:
  1. Navigate to the URL.
  2. Read the page's visible text content (no screenshots needed).
  3. Apply the following three checks and return a JSON object summarizing
     them as your FINAL response. Do not include anything besides the JSON.

Required JSON shape:

  {
    "scenario": "ld_landing_page_smoke",
    "url": "https://www.liquiddemocracy.us/",
    "page_loaded": true | false,
    "page_load_error": "" or "<short error message>",
    "checks": [
      {"name": "title_present", "expect": "Liquid Democracy", "found": true | false},
      {"name": "tagline_present", "expect": "Delegate your vote", "found": true | false},
      {"name": "login_link_present", "expect": "Log in or Login or Sign in (any case)", "found": true | false}
    ],
    "overall_pass": true | false,
    "evidence_excerpt": "<<<short excerpt of page text the conclusions were drawn from, <500 chars>>>"
  }

Rules:
  * READ ONLY. Do not click any button that would submit a form or
    mutate state. Do not log in. Do not register.
  * If the page fails to load, set page_loaded=false and page_load_error,
    overall_pass=false, and leave the per-check `found` fields false.
  * `overall_pass` is true iff page_loaded is true AND every check's
    `found` is true.
  * Return the JSON as your final assistant message; nothing else.
"""


def _claude_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    return env


def _setup_cwd(cwd: Path) -> None:
    """Write the project-local .mcp.json that claude -p auto-loads."""
    cwd.mkdir(parents=True, exist_ok=True)
    (cwd / ".mcp.json").write_text(
        json.dumps(MCP_CONFIG, indent=2), encoding="utf-8"
    )


def _run_claude(cwd: Path, prompt: str) -> dict:
    """Pipe prompt via stdin to dodge Windows' command-line length cap
    (P1 hit this with ~40KB seed prompts; same pattern here for safety
    even though P2's prompt is small)."""
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


def _result_text(record: dict) -> str:
    payload = record.get("payload") or {}
    if isinstance(payload, dict):
        return payload.get("result", "") or payload.get("text", "") or ""
    return ""


def _extract_json(text: str) -> dict | None:
    """Extract the JSON object the agent returned. Allows for the
    agent to wrap the JSON in a ```json fence or include some leading
    prose despite the prompt — we surface ALL such cases as soft
    failures in the record but still try to parse what's there.
    """
    if not text:
        return None
    # Try direct parse first.
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    # Try to find a ```json ... ``` fence.
    import re
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # Try first '{' through last '}' span.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cwd", type=str, required=True)
    parser.add_argument("--out", type=str, required=True)
    args = parser.parse_args()

    cwd = Path(args.cwd)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    if os.environ.get("ANTHROPIC_API_KEY"):
        print("[p2] ABORT: ANTHROPIC_API_KEY is set; refusing to spend.")
        return 2

    print(f"[p2] cwd={cwd}")
    print(f"[p2] out={out}")
    _setup_cwd(cwd)
    print(f"[p2] wrote .mcp.json with playwright server")

    print("[p2] dispatching claude -p with QA prompt...")
    rec = _run_claude(cwd, QA_PROMPT)
    text = _result_text(rec)
    print(f"[p2] exit={rec['exit_code']} elapsed_s={rec['elapsed_s']}")
    print(f"[p2] result text head:\n{text[:1500]}")
    if rec["stderr_tail"]:
        print(f"[p2] stderr tail:\n{rec['stderr_tail']}")

    parsed = _extract_json(text)

    record = {
        "scenario": "ld_landing_page_smoke",
        "elapsed_s": rec["elapsed_s"],
        "exit_code": rec["exit_code"],
        "agent_returned_json": parsed is not None,
        "agent_json": parsed,
        "result_text": text,
        "stderr_tail": rec["stderr_tail"],
        "payload_metadata": {
            k: v for k, v in (rec.get("payload") or {}).items()
            if k in ("session_id", "duration_ms", "duration_api_ms",
                     "total_cost_usd", "is_error", "num_turns", "usage")
        },
    }
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[p2] wrote {out}")

    if parsed is None:
        print("[p2] VERDICT: FAIL — agent did not return parseable JSON")
        return 1
    if not parsed.get("overall_pass"):
        print(f"[p2] VERDICT: FAIL — agent JSON overall_pass={parsed.get('overall_pass')}")
        return 1
    print("[p2] VERDICT: PASS — Playwright MCP drove headless browser successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
