"""Render tests for bootstrap + passdown (WA1 B5).

The renders must contain the load-bearing fields a fresh planner /
human passdown reader needs. Tests assert presence of specific
substrings rather than full-text equality — that lets the rendering
evolve without breaking the contract that "the rendered doc tells the
reader X" stays intact.
"""
from __future__ import annotations

from pathlib import Path

from planner_state.bootstrap import render_bootstrap
from planner_state.passdown import render_passdown
from planner_state.schema import (
    Decision,
    LoopState,
    PlannerState,
    Project,
    SCHEMA_VERSION,
)


def _state_with_everything() -> PlannerState:
    return PlannerState(
        schema_version=SCHEMA_VERSION,
        project=Project(
            name="Liquid Democracy",
            repo_root="/repo/path",
            prod_url="https://www.liquiddemocracy.us",
            current_pointer="Phase 42 SHIPPED — master 89dbc0c, bundle index-Dp3YmSzh.js",
        ),
        loop_state=LoopState(
            current_pass="WA1 — State & IPC Foundation",
            current_pass_status="in_progress",
            pending=["WA2 architecture spike", "Phase 43 frontend polish"],
            blocked=[{"item": "Cowork QA probe", "reason": "Z input needed"}],
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
                topic="Auth model",
                decision="Shell out to claude -p; no Agent SDK",
                rationale="Agent SDK incompatible with Max OAuth",
            ),
            Decision(
                date="2026-05-30T12:15:00Z",
                topic="QA browser",
                decision="Playwright MCP for autonomous QA",
                rationale="Headless-friendly; mature; Apache-2.0",
            ),
            Decision(
                date="2026-05-30T13:00:00Z",
                topic="Repo split timing",
                decision="Co-located through WA1/WA2; split before WA4",
                rationale="Validation reuses repo context; WA4 onward the daemon may orchestrate beyond LD",
            ),
        ],
        working_context_digest="Phase 42 returned a clean GO. WA1 is the no-regret bedrock.",
    )


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def test_bootstrap_contains_project_name(tmp_path: Path):
    md = render_bootstrap(_state_with_everything(), state_dir=tmp_path)
    assert "Liquid Democracy" in md


def test_bootstrap_contains_current_pointer():
    md = render_bootstrap(_state_with_everything())
    assert "Phase 42 SHIPPED" in md
    assert "89dbc0c" in md


def test_bootstrap_contains_current_pass_and_status():
    md = render_bootstrap(_state_with_everything())
    assert "WA1 — State & IPC Foundation" in md
    assert "in_progress" in md


def test_bootstrap_lists_pending_items():
    md = render_bootstrap(_state_with_everything())
    assert "WA2 architecture spike" in md
    assert "Phase 43 frontend polish" in md


def test_bootstrap_lists_blocked_items_with_reasons():
    md = render_bootstrap(_state_with_everything())
    assert "Cowork QA probe" in md
    assert "Z input needed" in md


def test_bootstrap_lists_last_code_activity():
    md = render_bootstrap(_state_with_everything())
    assert "Phase 42" in md
    assert "Workflow viability spike" in md
    assert "shipped" in md


def test_bootstrap_lists_all_decisions_in_full():
    md = render_bootstrap(_state_with_everything())
    # All three decision topics appear.
    assert "Auth model" in md
    assert "QA browser" in md
    assert "Repo split timing" in md
    # And the decision body + rationale.
    assert "Shell out to claude -p" in md
    assert "Playwright MCP" in md
    assert "Agent SDK incompatible" in md


def test_bootstrap_includes_state_dir_pointer_when_provided(tmp_path: Path):
    md = render_bootstrap(_state_with_everything(), state_dir=tmp_path)
    # The forward-slash form is what we render even on Windows.
    assert "planner_state.json" in md
    assert tmp_path.as_posix() in md


def test_bootstrap_omits_state_dir_pointer_when_absent():
    md = render_bootstrap(_state_with_everything(), state_dir=None)
    assert "planner_state.json" not in md


def test_bootstrap_works_with_empty_state():
    """An empty/fresh state still renders without error and clearly
    indicates "nothing here yet" rather than dropping sections."""
    md = render_bootstrap(PlannerState.empty("Fresh"))
    assert "Fresh" in md
    assert "Pending" in md
    assert "Blocked" in md
    assert "Locked decisions" in md
    # The fresh state has no decisions; render should say so explicitly.
    assert "(none recorded)" in md


# ---------------------------------------------------------------------------
# Passdown
# ---------------------------------------------------------------------------

def test_passdown_is_shorter_than_bootstrap_with_many_decisions():
    """Spec intent: passdown is the short-form, bootstrap is the long-form.
    With a non-trivial decisions log, passdown should be smaller because
    it caps the inlined-decision count.
    """
    state = _state_with_everything()
    # Pile on more decisions to make the size difference unambiguous.
    for i in range(10):
        state.decisions.append(Decision(
            date=f"2026-05-30T15:{i:02d}:00Z",
            topic=f"Decision {i}",
            decision=f"Body of decision {i} " * 20,
            rationale=f"Rationale for {i} " * 20,
        ))
    bootstrap_md = render_bootstrap(state)
    passdown_md = render_passdown(state, max_decisions=4)
    assert len(passdown_md) < len(bootstrap_md), (
        "Passdown should be shorter than bootstrap when there are many "
        "decisions (passdown caps inline count, bootstrap lists all)."
    )


def test_passdown_contains_current_pass():
    md = render_passdown(_state_with_everything())
    assert "WA1 — State & IPC Foundation" in md
    assert "in_progress" in md


def test_passdown_caps_decisions_at_max_decisions():
    state = _state_with_everything()
    for i in range(10):
        state.decisions.append(Decision(
            date=f"2026-05-30T15:{i:02d}:00Z",
            topic=f"D{i}",
            decision=f"Body {i}",
        ))
    md = render_passdown(state, max_decisions=3)
    # The 3 most recent decisions inline.
    assert "D9" in md
    assert "D8" in md
    assert "D7" in md
    # Older ones are summarized, not inlined verbatim.
    assert "D0" not in md
    assert "plus" in md and "earlier decision" in md


def test_passdown_renders_no_decisions_cleanly():
    state = PlannerState.empty("Fresh")
    md = render_passdown(state)
    assert "Fresh" in md
    assert "(none recorded)" in md


def test_passdown_includes_working_context_digest_when_present():
    md = render_passdown(_state_with_everything())
    assert "Phase 42 returned a clean GO" in md
    assert "Working-context digest" in md


def test_passdown_omits_working_context_section_when_digest_empty():
    state = _state_with_everything()
    state.working_context_digest = ""
    md = render_passdown(state)
    assert "Working-context digest" not in md
