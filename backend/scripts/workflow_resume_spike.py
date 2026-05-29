"""Phase 42 — `claude -p --resume` durability harness.

Drives a sequence of FRESH `claude -p --resume <session-id>` subprocess
invocations (one process per round) to test whether session state
carries forward across separate processes, and where (if anywhere)
it drifts/bloats.

Usage:
    python backend/scripts/workflow_resume_spike.py [--rounds N] [--cwd PATH] [--out DIR]

Defaults match the Phase 42 spec: 12 rounds, scratch cwd at
/tmp/p42_spike, results written to /tmp/p42_spike/.

Non-negotiables enforced by this script (per spec D2, D3):
- ANTHROPIC_API_KEY is unset in the subprocess env (so Max OAuth is used).
- --bare is NOT passed (would switch off OAuth + CLAUDE.md auto-discovery).
- Each round is its own process invocation — no long-lived parent process.

The seed round establishes three distinctive facts (codename, magic
number, liaison name). Each subsequent round asks the model to restate
all facts so far and adds one new fact. Recall is graded by string
matching against the seeded facts in the JSON result.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path


SEED_FACTS = [
    {"key": "codename", "value": "Borealis"},
    {"key": "magic_number", "value": "47"},
    {"key": "liaison_name", "value": "Quill"},
]

# Each round introduces ONE new fact. Keys ordered so a round always
# adds its key by index = round_number (1-indexed). 12 facts available
# after seed for up to 12 rounds.
ROUND_FACTS = [
    {"key": "city", "value": "Rivendell"},
    {"key": "drink", "value": "petrichor"},
    {"key": "color", "value": "vermilion"},
    {"key": "animal", "value": "axolotl"},
    {"key": "ship", "value": "Gossamer"},
    {"key": "instrument", "value": "theorbo"},
    {"key": "season", "value": "Solstinox"},
    {"key": "constellation", "value": "Cor Caroli"},
    {"key": "flower", "value": "Hellebore"},
    {"key": "library", "value": "Codex Atlanticus"},
    {"key": "month", "value": "Brumaire"},
    {"key": "river", "value": "Limmat"},
]

CLAUDE_TIMEOUT_S = 180
DEFAULT_ROUNDS = 12
DEFAULT_CWD = "/tmp/p42_spike"
DEFAULT_OUT = "/tmp/p42_spike"


def _claude_env() -> dict[str, str]:
    """Subprocess env with ANTHROPIC_API_KEY explicitly removed.

    Per spec D3: the wrapper will use Max OAuth, so this harness must too.
    A stray ANTHROPIC_API_KEY would silently switch the subprocess to API
    billing AND a different auth path than the wrapper will use, invalidating
    the test.
    """
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    return env


def _run_claude(
    cwd: str,
    prompt: str,
    *,
    resume_session_id: str | None = None,
    timeout_s: int = CLAUDE_TIMEOUT_S,
) -> dict:
    """Run `claude -p` once; return parsed JSON result + harness metadata."""
    cmd = ["claude", "-p", "--dangerously-skip-permissions",
           "--output-format", "json"]
    if resume_session_id is not None:
        cmd.extend(["--resume", resume_session_id])
    cmd.extend(["--", prompt])

    started_at = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            env=_claude_env(),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        elapsed = time.time() - started_at
        try:
            payload = json.loads(proc.stdout) if proc.stdout else {}
        except json.JSONDecodeError:
            payload = {"_parse_error": True, "_stdout_head": proc.stdout[:500]}
        return {
            "exit_code": proc.returncode,
            "elapsed_s": round(elapsed, 2),
            "stderr_tail": proc.stderr[-500:] if proc.stderr else "",
            "payload": payload,
        }
    except subprocess.TimeoutExpired:
        return {
            "exit_code": -1,
            "elapsed_s": round(time.time() - started_at, 2),
            "stderr_tail": f"TIMEOUT after {timeout_s}s",
            "payload": {},
        }


def _check_recall(result_text: str, expected_facts: list[dict]) -> dict:
    """Grade recall by case-insensitive substring match of each fact value."""
    text = (result_text or "").lower()
    hits = []
    misses = []
    for f in expected_facts:
        if f["value"].lower() in text:
            hits.append(f["key"])
        else:
            misses.append(f["key"])
    return {
        "expected_count": len(expected_facts),
        "hit_count": len(hits),
        "miss_count": len(misses),
        "hits": hits,
        "misses": misses,
        "all_recalled": len(misses) == 0,
    }


def _facts_brief(facts: list[dict]) -> str:
    """Render a compact line listing all facts for the prompt."""
    return ", ".join(f"{f['key']}={f['value']}" for f in facts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS,
                        help=f"Number of resume rounds (default {DEFAULT_ROUNDS})")
    parser.add_argument("--cwd", default=DEFAULT_CWD,
                        help=f"CWD for each claude -p run (default {DEFAULT_CWD})")
    parser.add_argument("--out", default=DEFAULT_OUT,
                        help=f"Output directory for results (default {DEFAULT_OUT})")
    args = parser.parse_args()

    cwd = Path(args.cwd)
    cwd.mkdir(parents=True, exist_ok=True)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print(f"# Phase 42 --resume durability spike")
    print(f"  rounds: {args.rounds}")
    print(f"  cwd: {cwd}")
    print(f"  out: {out}")
    print(f"  ANTHROPIC_API_KEY in env: {'YES (bad!)' if os.environ.get('ANTHROPIC_API_KEY') else 'no (ok)'}")

    # --- Seed round ---
    seed_prompt = (
        "You're being given some facts to remember across future prompts in "
        "this session. Please acknowledge each one verbatim. The facts are: "
        f"{_facts_brief(SEED_FACTS)}. "
        "Reply with a short bullet list confirming each fact."
    )
    print(f"\n=== SEED ===")
    seed = _run_claude(str(cwd), seed_prompt)
    seed_payload = seed["payload"]
    session_id = seed_payload.get("session_id")
    if not session_id:
        print(f"!!! FAILED to obtain session_id from seed: {seed}")
        return 1
    print(f"  session_id: {session_id}")
    print(f"  elapsed_s: {seed['elapsed_s']}, exit_code: {seed['exit_code']}")
    print(f"  seed result head: {(seed_payload.get('result','') or '')[:200]}")

    # --- Resume rounds ---
    rows: list[dict] = []
    rows.append({
        "round": 0,
        "label": "seed",
        "session_id": session_id,
        "exit_code": seed["exit_code"],
        "elapsed_s": seed["elapsed_s"],
        "num_turns": seed_payload.get("num_turns"),
        "input_tokens": (seed_payload.get("usage") or {}).get("input_tokens"),
        "cache_creation_input_tokens": (seed_payload.get("usage") or {}).get("cache_creation_input_tokens"),
        "cache_read_input_tokens": (seed_payload.get("usage") or {}).get("cache_read_input_tokens"),
        "output_tokens": (seed_payload.get("usage") or {}).get("output_tokens"),
        "expected_facts": len(SEED_FACTS),
        "hit_count": len(SEED_FACTS),
        "miss_count": 0,
        "all_recalled": True,
        "misses": "",
        "result_head": (seed_payload.get("result", "") or "")[:200],
    })

    cumulative_facts = list(SEED_FACTS)

    for i in range(1, args.rounds + 1):
        if i - 1 >= len(ROUND_FACTS):
            new_fact = {"key": f"extra_{i}", "value": f"extra_value_{i}"}
        else:
            new_fact = ROUND_FACTS[i - 1]

        round_prompt = (
            "Please do two things, in order:\n\n"
            "1) Restate EVERY fact you've been told so far in this session. "
            "Use a `key=value` list (one per line) with NO commentary other than "
            "the list. If any fact is missing, you must say so explicitly.\n\n"
            f"2) Remember this new fact for future rounds: {new_fact['key']}={new_fact['value']}.\n\n"
            "Then stop — no other commentary needed."
        )
        print(f"\n=== ROUND {i} (adds {new_fact['key']}={new_fact['value']}) ===")
        rd = _run_claude(str(cwd), round_prompt, resume_session_id=session_id)
        payload = rd["payload"]
        result_text = payload.get("result", "") or ""

        # Recall grade: we EXPECT all prior cumulative_facts (NOT including
        # the new fact being introduced in this round) to be present.
        grade = _check_recall(result_text, cumulative_facts)

        rows.append({
            "round": i,
            "label": f"round_{i}",
            "session_id": payload.get("session_id"),
            "exit_code": rd["exit_code"],
            "elapsed_s": rd["elapsed_s"],
            "num_turns": payload.get("num_turns"),
            "input_tokens": (payload.get("usage") or {}).get("input_tokens"),
            "cache_creation_input_tokens": (payload.get("usage") or {}).get("cache_creation_input_tokens"),
            "cache_read_input_tokens": (payload.get("usage") or {}).get("cache_read_input_tokens"),
            "output_tokens": (payload.get("usage") or {}).get("output_tokens"),
            "expected_facts": grade["expected_count"],
            "hit_count": grade["hit_count"],
            "miss_count": grade["miss_count"],
            "all_recalled": grade["all_recalled"],
            "misses": ",".join(grade["misses"]),
            "result_head": result_text[:300],
        })
        if grade["all_recalled"]:
            grade_str = "PASS"
        else:
            miss_str = ",".join(grade["misses"])
            grade_str = f"FAIL (missing {miss_str})"
        print(f"  elapsed_s: {rd['elapsed_s']}, exit: {rd['exit_code']}, "
              f"recall: {grade['hit_count']}/{grade['expected_count']} {grade_str}")

        # Append new fact AFTER grading (so this round's recall expectation
        # was based on facts known before the round).
        cumulative_facts.append(new_fact)

    # --- Write CSV results + JSON results ---
    csv_path = out / "workflow_resume_results.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    json_path = out / "workflow_resume_results.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump({"session_id": session_id, "rounds": rows}, f, indent=2)

    print(f"\nWrote {csv_path}")
    print(f"Wrote {json_path}")

    # --- Summary ---
    fail_rounds = [r for r in rows if not r["all_recalled"] and r["label"] != "seed"]
    print(f"\nSummary: {len(rows) - 1 - len(fail_rounds)}/{len(rows) - 1} rounds passed recall.")
    if fail_rounds:
        print(f"  Failing rounds: {[r['round'] for r in fail_rounds]}")
    print(f"  session_id: {session_id}")
    print(f"  (try one more manual claude -p --resume {session_id} to confirm cross-invocation resume works post-harness)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
