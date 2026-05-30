"""WA2 P1 — planner-continuity-at-planning-scale harness.

Drives a sequence of FRESH `claude -p --resume <session-id>` subprocess
invocations (one process per round) carrying PLANNING-SCALE context:
real workflow-automation specs are loaded into the session as the seed
context, then each round poses a substantive planning task that
references material from earlier rounds. Tests whether `--resume` holds
coherent planning judgment across the rounds (Phase 42 only tested
small-fact recall).

Phase 42 lineage: ``backend/scripts/workflow_resume_spike.py`` is the
template — same env hygiene, same per-process invocation, same JSON-
output telemetry capture. Differences:

* Seed is real specs/closeouts (~10-15k tokens of repo content), not
  three small facts.
* Each round prompt is a planning task (e.g. "given the decision from
  round N about X, draft the next step on Y"), not "recite the facts."
* Grading is two-axis: structured recall (substring matches on
  facts established in earlier rounds) PLUS a coherence note from the
  human running the script (printed inline; eyeballed). Recall is
  programmatic; coherence is a judgment call by the operator.
* Rotation demo: after the last round, render a WA1-style digest via
  ``planner_state.bootstrap.render_bootstrap``, start a FRESH session
  (no --resume), feed only the digest, ask the same kind of planning
  task. Confirm the fresh session reaches the same conclusions.

Usage::

    python -m workflow-automation.spike.p1_planner_continuity_harness \\
        --rounds 10 \\
        --cwd /tmp/wa2_p1_cwd \\
        --out /tmp/wa2_p1_out

Non-negotiables enforced:
- ``ANTHROPIC_API_KEY`` is unset in subprocess env (Max OAuth path).
- One process per round; no long-lived parent. Stability is what
  ``--resume`` survives, not in-RAM continuity.
- The session id from round 1's output is what's `--resume`d in 2-N.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# Force stdout to UTF-8 on Windows. Default cp1252 crashes on em-dashes /
# arrows the model produces and that the seed docs contain. WA1 hit this
# the same way; mirror its `_emit` pattern for safety.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# This file: workflow-automation/spike/p1_planner_continuity_harness.py
# parents[0]=spike/, parents[1]=workflow-automation/, parents[2]=<repo root>.
# A prior version used parents[3] and silently loaded zero bytes — assert
# the seed dir actually exists so a future move can't silently regress.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_WA_DIR = _REPO_ROOT / "workflow-automation"
assert _WA_DIR.is_dir(), (
    f"P1 seed dir missing: {_WA_DIR}. Path math drifted; the harness "
    "would otherwise feed empty seed context and produce a meaningless "
    "test result."
)


# -----------------------------------------------------------------------------
# Seed context — real workflow-automation track docs
# -----------------------------------------------------------------------------

SEED_FILES = [
    _WA_DIR / "workflow_automation_overview.md",
    _WA_DIR / "wa1_state_and_ipc_foundation_spec.md",
    _WA_DIR / "wa2_architecture_validation_spike_spec.md",
    _WA_DIR / "README.md",
]


def _load_seed_context() -> str:
    """Concatenate the seed docs with section headers so the session has
    real planning-scale context to reason over."""
    parts: list[str] = []
    for p in SEED_FILES:
        if not p.exists():
            continue
        parts.append(f"\n\n=========== FILE: {p.relative_to(_REPO_ROOT)} ===========\n")
        parts.append(p.read_text(encoding="utf-8"))
    return "".join(parts)


SEED_PROMPT_TEMPLATE = """\
You are the persistent workflow-automation planner for the Liquid
Democracy project. You will be resumed in many separate processes; each
resume re-enters this session with full prior context. Your job is to
plan and coordinate the workflow-automation track (WA1, WA2, WA3 ...).

I will now hand you the current track documentation as your starting
context. READ IT but do not summarize unless asked. After reading, your
ONLY output for this round is:

  - One short paragraph confirming you've absorbed the context.
  - A "TRACKER" line of the form:
        TRACKER: WA1_status=<status>, WA2_status=<status>, next_pass=<name>
    Fill those values from what you just read. This TRACKER line is the
    load-bearing signal — every future round will check that you can
    reproduce + update it correctly.

Do NOT modify any files. Do NOT propose actions outside this prompt.

--- TRACK DOCS ---
{seed_context}
"""


# -----------------------------------------------------------------------------
# Round prompts — planning tasks that build on each other
# -----------------------------------------------------------------------------

# Each round adds a substantive planning task AND expects the running
# TRACKER state to be preserved/updated. The grading harness checks
# (a) the TRACKER line is present, (b) its content is coherent with
# the prior round's intent, (c) any round-specific recall check passes.

@dataclass
class RoundSpec:
    """One round's prompt + grading hooks."""
    name: str
    prompt: str
    # Substrings the round's response MUST contain (case-insensitive).
    # Used as the structured-recall check.
    must_contain: list[str] = field(default_factory=list)
    # Substrings the TRACKER line specifically MUST contain. Empty list
    # = the tracker check is skipped this round (the seed round doesn't
    # need to re-prove the tracker; it ESTABLISHED it).
    tracker_must_contain: list[str] = field(default_factory=list)


ROUND_SPECS: list[RoundSpec] = [
    RoundSpec(
        name="R2_recall_seed",
        prompt=(
            "Round 2. First reproduce the TRACKER line exactly. Then, in 3 "
            "bullets, name the THREE goals from the overview that are most "
            "at risk if Anthropic ships a Max-OAuth-incompatible change "
            "before the workflow-automation track ships WA4. Be specific "
            "about which goal numbers (1-6) and why."
        ),
        must_contain=["TRACKER:", "goal"],
        tracker_must_contain=["WA1_status", "WA2_status"],
    ),
    RoundSpec(
        name="R3_decision_application",
        prompt=(
            "Round 3. Reproduce the TRACKER line. Then: Phase 42 found that "
            "ANTHROPIC_API_KEY must be UNSET when spawning claude -p so the "
            "subprocess uses Max OAuth. Where in the WA architecture is "
            "that invariant load-bearing (name at least two distinct code "
            "paths or pass deliverables)? Answer in 4-6 bullets."
        ),
        must_contain=["TRACKER:", "ANTHROPIC_API_KEY"],
        tracker_must_contain=["WA1_status"],
    ),
    RoundSpec(
        name="R4_cross_pass_dependency",
        prompt=(
            "Round 4. Reproduce the TRACKER line. Then: WA4 (orchestrator "
            "daemon) depends on which earlier passes' deliverables? List "
            "the dependencies explicitly. For each dependency, in one "
            "sentence, say WHY WA4 depends on it. Don't invent passes "
            "that don't exist in the roadmap."
        ),
        must_contain=["TRACKER:", "WA4"],
        tracker_must_contain=["WA1_status"],
    ),
    RoundSpec(
        name="R5_synthesis",
        prompt=(
            "Round 5. Reproduce the TRACKER line. Then synthesize: in "
            "rounds 2-4 you discussed goal-risk, the ANTHROPIC_API_KEY "
            "invariant, and WA4's dependencies. Draft a 3-bullet "
            "recommendation for WA2's findings doc on what the headline "
            "go/no-go criteria for WA4 should be. Reference your "
            "earlier rounds explicitly by content."
        ),
        must_contain=["TRACKER:", "WA4"],
        tracker_must_contain=["WA1_status"],
    ),
    RoundSpec(
        name="R6_update_tracker",
        prompt=(
            "Round 6. UPDATE the TRACKER line: WA1_status is now `shipped` "
            "(we just merged it). WA2_status is now `in_progress` (this "
            "spike is running). next_pass should be WA3 or WA4 depending "
            "on what you'd recommend given rounds 2-5. Print the UPDATED "
            "tracker line. Then justify the next_pass choice in 2 bullets."
        ),
        must_contain=["TRACKER:", "shipped", "in_progress"],
        tracker_must_contain=["WA1_status=shipped", "WA2_status=in_progress"],
    ),
    RoundSpec(
        name="R7_recall_post_update",
        prompt=(
            "Round 7. Reproduce the UPDATED tracker from round 6 verbatim. "
            "Then: someone hands you a fresh closeout from a hypothetical "
            "WA1 follow-up pass that adds a new field `pass_history` to "
            "the planner state schema. Does that require a schema version "
            "bump per the WA1 spec's locked decisions? Answer yes/no + "
            "one sentence why. Reference the specific locked decision."
        ),
        must_contain=["TRACKER:", "WA1_status=shipped", "schema_version"],
        tracker_must_contain=["WA1_status=shipped"],
    ),
    RoundSpec(
        name="R8_long_context",
        prompt=(
            "Round 8. Reproduce the tracker. Then: in 5-8 bullets, draft a "
            "PRELIMINARY outline for the WA4 spec — clusters (B1, B2, ...) "
            "the spec should have, based on what WA1+WA2 have established. "
            "This is a planning task, not a doc; aim for cluster *names* "
            "with one-line each, not full content. Reference WA1's IPC "
            "contract + state schema where relevant."
        ),
        must_contain=["TRACKER:", "WA4"],
        tracker_must_contain=["WA1_status=shipped"],
    ),
    RoundSpec(
        name="R9_recall_drift_check",
        prompt=(
            "Round 9. Reproduce the tracker exactly. Then list, in 4-6 "
            "bullets, every decision you have made or referenced across "
            "rounds 2-8 in this session. This is a drift check — if you "
            "can list them coherently we have continuity; if you can't, "
            "we have a degradation finding."
        ),
        must_contain=["TRACKER:"],
        tracker_must_contain=["WA1_status=shipped"],
    ),
    RoundSpec(
        name="R10_planning_judgment",
        prompt=(
            "Round 10 (final --resume round). Reproduce the tracker. Then "
            "apply judgment: WA2's P1 verdict turns on whether you've "
            "stayed coherent across 9 prior rounds. Self-assess in 2-3 "
            "bullets — name any place you noticed drift or had to "
            "reconstruct context from the seed rather than the conversation. "
            "Be honest; this is the test result."
        ),
        must_contain=["TRACKER:"],
        tracker_must_contain=["WA1_status=shipped"],
    ),
]


# -----------------------------------------------------------------------------
# Claude subprocess invocation
# -----------------------------------------------------------------------------

CLAUDE_TIMEOUT_S = 240  # planning prompts can take a beat


def _claude_env() -> dict[str, str]:
    """Subprocess env with ANTHROPIC_API_KEY explicitly removed
    (Phase 42 invariant — Max OAuth path)."""
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    return env


def _run_claude(
    *,
    cwd: Path,
    prompt: str,
    resume_session_id: str | None = None,
    timeout_s: int = CLAUDE_TIMEOUT_S,
) -> dict[str, Any]:
    """Run claude -p once. Prompt is piped via stdin (per the headless
    docs, ``-p`` reads stdin) to avoid Windows' ~32KB command-line
    length limit on positional args — P1's seed prompt is ~40-50KB."""
    cmd = [
        "claude", "-p", "--dangerously-skip-permissions",
        "--output-format", "json",
    ]
    if resume_session_id is not None:
        cmd.extend(["--resume", resume_session_id])
    # NO trailing -- <prompt>; we feed the prompt via stdin instead.

    started_at = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=_claude_env(),
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout_s,
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


def _result_text(record: dict[str, Any]) -> str:
    payload = record.get("payload") or {}
    if isinstance(payload, dict):
        return payload.get("result", "") or payload.get("text", "") or ""
    return ""


def _grade_round(spec: RoundSpec, result_text: str) -> dict[str, Any]:
    """Two-axis grade: full-text substring presence + tracker-line check."""
    text_lower = result_text.lower()
    must_hits = []
    must_misses = []
    for needle in spec.must_contain:
        if needle.lower() in text_lower:
            must_hits.append(needle)
        else:
            must_misses.append(needle)

    tracker_line = ""
    for line in result_text.splitlines():
        if "TRACKER:" in line.upper():
            tracker_line = line
            break

    tracker_hits = []
    tracker_misses = []
    if spec.tracker_must_contain:
        if not tracker_line:
            tracker_misses = list(spec.tracker_must_contain)
        else:
            tl = tracker_line.lower()
            for needle in spec.tracker_must_contain:
                if needle.lower() in tl:
                    tracker_hits.append(needle)
                else:
                    tracker_misses.append(needle)

    passed = not must_misses and not tracker_misses
    return {
        "name": spec.name,
        "passed": passed,
        "tracker_line": tracker_line,
        "must_hits": must_hits,
        "must_misses": must_misses,
        "tracker_hits": tracker_hits,
        "tracker_misses": tracker_misses,
    }


# -----------------------------------------------------------------------------
# Main flow
# -----------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--cwd", type=str, required=True,
                        help="Stable cwd for every claude -p subprocess.")
    parser.add_argument("--out", type=str, required=True,
                        help="Output dir for round transcripts + summary JSON.")
    parser.add_argument("--rotation", action="store_true", default=True,
                        help="Run the rotation demo after the resume rounds.")
    args = parser.parse_args()

    cwd = Path(args.cwd)
    out = Path(args.out)
    cwd.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)

    print(f"[p1] cwd={cwd}")
    print(f"[p1] out={out}")
    print(f"[p1] rounds={args.rounds}")

    if os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "[p1] ABORT: ANTHROPIC_API_KEY is set in this shell. The "
            "subprocess env removes it, but a stray key in this script's "
            "shell hints at an unsafe wrapper config. Exit before any "
            "billable call could fire."
        )
        return 2

    seed_context = _load_seed_context()
    print(f"[p1] seed context bytes: {len(seed_context)}")

    rounds: list[dict[str, Any]] = []
    session_id: str | None = None

    # ----- Round 1 (seed) -----
    print("\n[p1] === ROUND 1 (seed) ===")
    seed_prompt = SEED_PROMPT_TEMPLATE.format(seed_context=seed_context)
    rec = _run_claude(cwd=cwd, prompt=seed_prompt)
    text = _result_text(rec)
    session_id = (rec.get("payload") or {}).get("session_id")
    cache_read = (rec.get("payload") or {}).get("usage", {}).get(
        "cache_read_input_tokens", 0
    )
    cache_create = (rec.get("payload") or {}).get("usage", {}).get(
        "cache_creation_input_tokens", 0
    )
    print(
        f"[p1] seed exit={rec['exit_code']} elapsed_s={rec['elapsed_s']} "
        f"session_id={session_id} cache_create={cache_create} "
        f"cache_read={cache_read} result_chars={len(text)}"
    )
    print(f"[p1] seed result head:\n{text[:400]}")
    rounds.append({
        "round": 1,
        "name": "R1_seed",
        "session_id": session_id,
        "elapsed_s": rec["elapsed_s"],
        "exit_code": rec["exit_code"],
        "cache_create_tokens": cache_create,
        "cache_read_tokens": cache_read,
        "result_text": text,
        "grade": {"name": "R1_seed", "passed": rec["exit_code"] == 0,
                  "note": "seed round establishes tracker; not graded"},
    })
    if rec["exit_code"] != 0 or not session_id:
        print("[p1] ABORT — seed round failed; can't --resume.")
        (out / "rounds.json").write_text(
            json.dumps(rounds, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return 1

    # ----- Resume rounds -----
    for i, spec in enumerate(ROUND_SPECS[: args.rounds - 1]):
        round_num = i + 2
        print(f"\n[p1] === ROUND {round_num} ({spec.name}) ===")
        rec = _run_claude(
            cwd=cwd, prompt=spec.prompt, resume_session_id=session_id,
        )
        text = _result_text(rec)
        cache_read = (rec.get("payload") or {}).get("usage", {}).get(
            "cache_read_input_tokens", 0
        )
        cache_create = (rec.get("payload") or {}).get("usage", {}).get(
            "cache_creation_input_tokens", 0
        )
        grade = _grade_round(spec, text)
        print(
            f"[p1] r{round_num} exit={rec['exit_code']} "
            f"elapsed_s={rec['elapsed_s']} "
            f"cache_create={cache_create} cache_read={cache_read} "
            f"PASS={grade['passed']} chars={len(text)}"
        )
        if grade["must_misses"]:
            print(f"[p1] r{round_num} must_misses={grade['must_misses']}")
        if grade["tracker_misses"]:
            print(f"[p1] r{round_num} tracker_misses={grade['tracker_misses']}")
        print(f"[p1] r{round_num} result head:\n{text[:600]}")
        rounds.append({
            "round": round_num,
            "name": spec.name,
            "session_id": session_id,
            "elapsed_s": rec["elapsed_s"],
            "exit_code": rec["exit_code"],
            "cache_create_tokens": cache_create,
            "cache_read_tokens": cache_read,
            "result_text": text,
            "grade": grade,
        })
        # Persist after every round so a crash mid-run isn't a total loss.
        (out / "rounds.json").write_text(
            json.dumps(rounds, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ----- Rotation demo -----
    if args.rotation:
        print("\n[p1] === ROTATION DEMO ===")
        # The "digest" is a synthetic WA1-style bootstrap built from
        # what the *prior* session would have written to state. We don't
        # actually require a live planner_state install for this script;
        # we hand-craft the digest from the rounds' content so the spike
        # is self-contained.
        last_tracker = ""
        for r in reversed(rounds):
            tl = r.get("grade", {}).get("tracker_line") or ""
            if "TRACKER" in tl.upper():
                last_tracker = tl.strip()
                break
        digest = _build_rotation_digest(rounds, last_tracker)
        (out / "rotation_digest.md").write_text(digest, encoding="utf-8")

        # Fresh session, NO --resume; only the digest.
        rotation_prompt = (
            "You are a FRESH workflow-automation planner instance. The prior "
            "session was rotated. Below is the WA1-style digest that carries "
            "the load-bearing state forward. Read it, then in 4-6 bullets:\n"
            "  1. Restate the current tracker line.\n"
            "  2. Name the next pass and why.\n"
            "  3. Confirm you can continue planning from this digest alone "
            "(without the prior session's full transcript).\n\n"
            f"--- DIGEST ---\n{digest}"
        )
        rec = _run_claude(cwd=cwd, prompt=rotation_prompt)
        rotation_text = _result_text(rec)
        rotation_grade = _grade_round(
            RoundSpec(
                name="rotation_demo",
                prompt="",
                must_contain=["TRACKER:", "WA1_status=shipped", "next pass"],
                tracker_must_contain=["WA1_status=shipped"],
            ),
            rotation_text,
        )
        print(
            f"[p1] rotation exit={rec['exit_code']} "
            f"elapsed_s={rec['elapsed_s']} "
            f"PASS={rotation_grade['passed']} chars={len(rotation_text)}"
        )
        print(f"[p1] rotation result head:\n{rotation_text[:600]}")
        rounds.append({
            "round": "rotation",
            "name": "rotation_demo",
            "session_id": None,
            "elapsed_s": rec["elapsed_s"],
            "exit_code": rec["exit_code"],
            "result_text": rotation_text,
            "grade": rotation_grade,
        })
        (out / "rounds.json").write_text(
            json.dumps(rounds, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ----- Summary -----
    summary = _summarize(rounds)
    summary_path = out / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("\n[p1] === SUMMARY ===")
    print(json.dumps(summary, indent=2))
    print(f"[p1] artifacts: {out}")
    return 0 if summary["all_passed"] else 1


def _build_rotation_digest(rounds: list[dict[str, Any]], last_tracker: str) -> str:
    """Render a WA1-style bootstrap-ish Markdown digest from the rounds.

    The shape mirrors what ``planner_state.render_bootstrap`` would
    produce — we synthesize it inline so the spike doesn't need the
    install path right.
    """
    lines: list[str] = []
    lines.append("# Planner rotation digest — workflow-automation")
    lines.append("")
    lines.append("This digest carries the load-bearing state from the prior")
    lines.append("`--resume` session forward into a fresh planner instance.")
    lines.append("")
    lines.append("## Current tracker")
    lines.append("")
    lines.append(f"`{last_tracker or 'TRACKER: (unknown — recover from context)'}`")
    lines.append("")
    lines.append("## Project")
    lines.append("")
    lines.append("- **Project:** Liquid Democracy + workflow-automation track")
    lines.append("- **Prod URL:** https://www.liquiddemocracy.us")
    lines.append("- **Workflow track shipped:** WA1 (State & IPC Foundation)")
    lines.append("- **In flight:** WA2 (this spike — architecture validation)")
    lines.append("")
    lines.append("## Decisions established earlier this session")
    lines.append("")
    # Pull a sample of round results' content into a recap. Trim each
    # round's result_text to fit, label by round name.
    for r in rounds:
        name = r.get("name", "?")
        text = (r.get("result_text") or "").strip()
        if not text:
            continue
        snippet = text[:400].replace("\n", " ")
        lines.append(f"- **{name}:** {snippet}")
    lines.append("")
    lines.append("## What the fresh planner should do")
    lines.append("")
    lines.append("- Confirm you can restate the tracker line.")
    lines.append("- Name the next pass + brief rationale.")
    lines.append("- Confirm you can continue planning from this digest alone.")
    return "\n".join(lines) + "\n"


def _summarize(rounds: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(1 for r in rounds if r.get("grade", {}).get("passed"))
    total = len(rounds)
    elapsed = [r.get("elapsed_s") for r in rounds if isinstance(r.get("elapsed_s"), (int, float))]
    cache_reads = [r.get("cache_read_tokens", 0) or 0 for r in rounds]
    return {
        "total_rounds": total,
        "passed": passed,
        "failed": total - passed,
        "all_passed": passed == total,
        "first_failure": next(
            (r["round"] for r in rounds if not r.get("grade", {}).get("passed")),
            None,
        ),
        "elapsed_s_min": min(elapsed) if elapsed else None,
        "elapsed_s_max": max(elapsed) if elapsed else None,
        "elapsed_s_total": round(sum(elapsed), 2) if elapsed else None,
        "cache_read_tokens_min": min(cache_reads) if cache_reads else None,
        "cache_read_tokens_max": max(cache_reads) if cache_reads else None,
        "rounds_brief": [
            {
                "round": r["round"],
                "name": r["name"],
                "elapsed_s": r.get("elapsed_s"),
                "exit_code": r.get("exit_code"),
                "cache_read_tokens": r.get("cache_read_tokens", 0),
                "passed": r.get("grade", {}).get("passed"),
                "must_misses": r.get("grade", {}).get("must_misses", []),
                "tracker_misses": r.get("grade", {}).get("tracker_misses", []),
            }
            for r in rounds
        ],
    }


if __name__ == "__main__":
    sys.exit(main())
