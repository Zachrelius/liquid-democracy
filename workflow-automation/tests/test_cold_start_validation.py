"""WA1 B5 cold-start reconstruction validation.

This is the load-bearing side-effect test for WA1: render a bootstrap
doc from a representative state, hand it to a fresh ``claude -p`` (no
prior session, ``--dangerously-skip-permissions``, ``ANTHROPIC_API_KEY``
unset → Max OAuth), and assert that the cold session's restatement
contains the expected load-bearing facts.

This is NOT a unit test of the renderer (those live in
test_bootstrap_and_passdown.py — they assert string contents). This
asserts the *side effect* the renderer is supposed to enable: a fresh
LLM session can actually reconstruct the project's situation from
what we emit. It pins the spec's goal-5 contract.

Skipped automatically when the ``claude`` CLI isn't available on
PATH (so CI without the CLI installed doesn't fail), or when
``WA1_SKIP_COLDSTART=1`` is set (env override for fast local cycles).
Run explicitly with::

    pytest tests/test_cold_start_validation.py -s

Pass ``-s`` to surface the cold session's full output for manual
inspection; the test asserts the load-bearing substrings programmatically.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from planner_state.bootstrap import render_bootstrap
from planner_state.checkpoint import StateStore
from planner_state.schema import (
    Decision,
    LoopState,
    PlannerState,
    Project,
    SCHEMA_VERSION,
)


CLAUDE_BIN = shutil.which("claude")
CLAUDE_TIMEOUT_S = 180

REQUIRES_CLAUDE = pytest.mark.skipif(
    CLAUDE_BIN is None or os.environ.get("WA1_SKIP_COLDSTART") == "1",
    reason=(
        "`claude` CLI not on PATH, or WA1_SKIP_COLDSTART=1 in env. "
        "Install Claude Code CLI to run this validation."
    ),
)


def _representative_state() -> PlannerState:
    """The state used for the cold-start validation. Designed to
    contain enough texture (in-flight pass, pending + blocked items,
    multiple decisions with rationales) that the cold session has
    something substantive to restate.
    """
    return PlannerState(
        schema_version=SCHEMA_VERSION,
        project=Project(
            name="Liquid Democracy",
            repo_root="C:/Users/zachk/liquid-democracy",
            prod_url="https://www.liquiddemocracy.us",
            current_pointer=(
                "Phase 42 SHIPPED 2026-05-29 — master 89dbc0c. "
                "Workflow-automation viability spike returned GO."
            ),
        ),
        loop_state=LoopState(
            current_pass="WA1 — State & IPC Foundation",
            current_pass_status="in_progress",
            pending=[
                "WA2 architecture-validation spike",
                "Phase 43 frontend polish (parallel website pass)",
            ],
            blocked=[
                {
                    "item": "Cowork-QA build (Phase 42 S3)",
                    "reason": "Requires Z to drive the Cowork-side probe",
                },
            ],
            last_code_activity={
                "pass": "Phase 42",
                "timestamp": "2026-05-29",
                "summary": "Workflow viability spike — GO recommendation",
                "result": "shipped",
            },
        ),
        decisions=[
            Decision(
                date="2026-05-30T12:00:00Z",
                topic="Workflow-automation auth model",
                decision="Shell out to claude -p CLI; do NOT embed Agent SDK",
                rationale=(
                    "Anthropic compliance docs forbid Max OAuth with the "
                    "Agent SDK; claude -p CLI on Max is explicitly sanctioned."
                ),
            ),
            Decision(
                date="2026-05-30T12:15:00Z",
                topic="Autonomous QA browser",
                decision="Playwright MCP for headless QA agents",
                rationale=(
                    "Claude-in-Chrome is desktop UX, not headless-friendly; "
                    "Playwright MCP is the de-facto agent-QA browser layer."
                ),
            ),
            Decision(
                date="2026-05-30T13:00:00Z",
                topic="Workflow-automation repo split timing",
                decision=(
                    "Stay co-located in liquid-democracy through WA1/WA2; "
                    "split before WA4 daemon"
                ),
                rationale="Lowest-friction validation; clean lift later.",
            ),
        ],
        working_context_digest=(
            "Phase 42 returned a clean GO on the wrapper architecture. "
            "WA1 is the no-regret bedrock pass (state + checkpoint + "
            "passdown + IPC contract)."
        ),
    )


COLD_START_INSTRUCTION = (
    "You are a FRESH planner session being bootstrapped. You have NEVER "
    "seen this project before this moment. Read the bootstrap document "
    "that follows and produce a SHORT (4-8 bullets) restatement of:\n\n"
    "1. What project this is.\n"
    "2. The current platform state (one bullet).\n"
    "3. What pass (if any) is currently in flight, and its status.\n"
    "4. What's pending and what's blocked.\n"
    "5. The 2-3 most consequential locked decisions.\n\n"
    "Do NOT propose actions. Do NOT modify any files. Do NOT touch the "
    "repository or its state. This is a read-only validation: your "
    "output is the test result. Be concise.\n\n---\n\n"
)


def _claude_env() -> dict[str, str]:
    """Subprocess env with ANTHROPIC_API_KEY explicitly removed (Phase
    42 invariant — Max OAuth path only). A stray key silently switches
    to API billing AND a different auth path, invalidating the test.
    """
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    return env


def _run_cold_start(prompt: str, cwd: Path) -> dict:
    """Invoke ``claude -p`` once, returning a parsed dict.

    Mirrors the shape of ``backend/scripts/workflow_resume_spike.py::
    _run_claude`` (Phase 42 harness) — same flags, same env hygiene.
    """
    cmd = [
        CLAUDE_BIN, "-p", "--dangerously-skip-permissions",
        "--output-format", "json",
        "--", prompt,
    ]
    started_at = time.time()
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=_claude_env(),
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
    result_text = ""
    if isinstance(payload, dict):
        result_text = payload.get("result", "") or payload.get("text", "") or ""
    return {
        "elapsed_s": elapsed,
        "exit_code": proc.returncode,
        "stderr_tail": proc.stderr[-500:] if proc.stderr else "",
        "payload": payload,
        "result_text": result_text,
    }


@REQUIRES_CLAUDE
def test_cold_start_reconstructs_project_situation(tmp_path: Path):
    """The headline WA1 B5 validation. Render bootstrap from a
    representative state; cold ``claude -p`` reads it; the
    restatement contains the load-bearing facts. Asserts presence
    of project name + platform-state marker + current-pass name +
    a pending item + a blocked item + decision-topic substrings.
    """
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    store = StateStore(state_dir)
    state = _representative_state()
    store.write(state)
    bootstrap_md = render_bootstrap(state, state_dir=state_dir)
    prompt = COLD_START_INSTRUCTION + bootstrap_md

    record = _run_cold_start(prompt, cwd=state_dir)

    # Persist the transcript for forensic inspection / closeout
    # evidence. The path is reported in the assertion message on
    # failure so a re-runner can find it.
    transcript_path = state_dir / "cold_start_transcript.json"
    transcript_path.write_text(
        json.dumps(record, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    assert record["exit_code"] == 0, (
        f"claude -p exited non-zero. transcript={transcript_path} "
        f"stderr={record['stderr_tail']!r}"
    )

    text = record["result_text"].lower()
    # The cold session may use case variations / paraphrases; substring
    # matches use casefold-equivalent (lower) comparison.
    must_contain = [
        ("project name", "liquid democracy"),
        ("phase-42 marker", "phase 42"),
        ("master pointer", "89dbc0c"),
        ("current-pass name", "wa1"),
        ("a pending item", "wa2"),
        ("blocked-item identifier", "cowork"),
        ("decision: auth model", "agent sdk"),
        ("decision: QA browser", "playwright"),
    ]
    missing = [
        (label, needle) for (label, needle) in must_contain
        if needle not in text
    ]
    assert not missing, (
        "Cold-start restatement missed load-bearing facts:\n"
        + "\n".join(f"  - {label!r} (looked for {needle!r})"
                    for label, needle in missing)
        + f"\n\nTranscript: {transcript_path}\n"
        + f"Result text:\n{record['result_text']}"
    )

    # Print a one-line summary on -s runs so the human can spot-check
    # the substance, not just the substring count.
    print(
        f"\n[cold-start validation] elapsed_s={record['elapsed_s']} "
        f"chars={len(record['result_text'])} transcript={transcript_path}"
    )
