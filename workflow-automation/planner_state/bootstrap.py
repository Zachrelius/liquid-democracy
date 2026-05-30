"""Bootstrap context renderer (WA1 B3 — first half).

Given a ``PlannerState``, render the Markdown a fresh planner session
reads at start/rotation to "come up to speed" on the project.

The rendered Markdown is the load-bearing artifact for goal-1
(persistent planner) when the long-lived ``--resume`` session is
rotated: the fresh session reads this doc + the state dir, and per
Phase 42 (`docs/workflow_spike_resume_findings.md`) a cold ``claude -p``
orients from such Markdown in seconds. The WA1 B5 validation tests
exactly this: render → run claude -p → assert restatement quality.

Design notes:

* **Markdown not JSON** for the fresh-planner consumption channel.
  Phase 42 confirmed Markdown narrative is what a cold session reads
  fastest. JSON is the canonical machine format; this module is the
  human/LLM-readable view.
* **Self-contained.** The bootstrap doc should be intelligible without
  the JSON state file at hand — but cross-references to the state
  files (path-pointer) are included so the session knows where to
  look for more.
* **No hidden context.** Whatever's in this rendered output is what the
  fresh planner knows. Decisions log, pending list, etc., are
  inlined; nothing's deferred to "ask Z" — that'd defeat the goal.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .schema import PlannerState


def render_bootstrap(state: PlannerState, *, state_dir: Path | str | None = None) -> str:
    """Return the Markdown bootstrap doc for ``state``.

    ``state_dir`` (optional) — included in the rendered doc as a
    pointer to the on-disk state location so the fresh planner can
    cross-reference. Use ``None`` when generating for a context where
    the path isn't stable / shouldn't be embedded.
    """
    lines: list[str] = []

    lines.append(f"# Planner bootstrap — {state.project.name or 'Unnamed project'}")
    lines.append("")
    lines.append(
        f"Generated {_now_human()}. This is the come-up-to-speed doc "
        "for a fresh planner session — read it before doing anything "
        "else. It's auto-generated from the on-disk planner state by "
        "`workflow-automation/planner_state` (WA1)."
    )
    lines.append("")

    # ----- Project block -----
    lines.append("## Project")
    lines.append("")
    if state.project.name:
        lines.append(f"- **Name:** {state.project.name}")
    if state.project.repo_root:
        lines.append(f"- **Repo root:** `{state.project.repo_root}`")
    if state.project.prod_url:
        lines.append(f"- **Prod URL:** {state.project.prod_url}")
    if state.project.current_pointer:
        lines.append(f"- **Current platform state:** {state.project.current_pointer}")
    lines.append("")

    # ----- Loop state -----
    lines.append("## Loop state")
    lines.append("")
    ls = state.loop_state
    if ls.current_pass:
        lines.append(
            f"- **Pass in flight:** {ls.current_pass} "
            f"(status: `{ls.current_pass_status}`)"
        )
    else:
        lines.append(f"- **Pass in flight:** none (status: `{ls.current_pass_status}`)")

    if ls.pending:
        lines.append("- **Pending:**")
        for item in ls.pending:
            lines.append(f"  - {item}")
    else:
        lines.append("- **Pending:** (none)")

    if ls.blocked:
        lines.append("- **Blocked:**")
        for entry in ls.blocked:
            item = entry.get("item", "(unspecified)")
            reason = entry.get("reason", "")
            if reason:
                lines.append(f"  - {item} — *{reason}*")
            else:
                lines.append(f"  - {item}")
    else:
        lines.append("- **Blocked:** (none)")
    lines.append("")

    # ----- Last Code activity -----
    if ls.last_code_activity:
        lines.append("## Last Code activity")
        lines.append("")
        lca = ls.last_code_activity
        if "pass" in lca:
            lines.append(f"- **Pass:** {lca['pass']}")
        if "timestamp" in lca:
            lines.append(f"- **At:** {lca['timestamp']}")
        if "summary" in lca:
            lines.append(f"- **Summary:** {lca['summary']}")
        if "result" in lca:
            lines.append(f"- **Result:** {lca['result']}")
        lines.append("")

    # ----- Decisions log -----
    lines.append("## Locked decisions")
    lines.append("")
    if not state.decisions:
        lines.append("(none recorded)")
    else:
        lines.append(
            "Append-only log of decisions you must not re-litigate. "
            "Newest last."
        )
        lines.append("")
        for d in state.decisions:
            header = f"### {d.topic}  *({d.date})*"
            lines.append(header)
            lines.append("")
            lines.append(d.decision)
            if d.rationale:
                lines.append("")
                lines.append(f"*Rationale:* {d.rationale}")
            lines.append("")

    # ----- Working context digest -----
    if state.working_context_digest.strip():
        lines.append("## Working-context digest")
        lines.append("")
        lines.append(
            "Recent Z↔planner strategy that isn't yet a formal decision. "
            "Curate this; replace it as understanding firms up."
        )
        lines.append("")
        lines.append(state.working_context_digest.rstrip())
        lines.append("")

    # ----- Pointer -----
    if state_dir is not None:
        lines.append("---")
        lines.append("")
        lines.append(
            f"Canonical state on disk: `{Path(state_dir).as_posix()}/planner_state.json`. "
            "Don't edit by hand; use the `planner_state` library "
            "(`StateStore.write`, `.append_decision`, "
            "`.update_loop_state`) so writes stay atomic."
        )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _now_human() -> str:
    """Render the current time as ``YYYY-MM-DD HH:MM UTC`` for the
    bootstrap doc header. Distinct from ``schema.now_iso`` (which is
    machine-readable) — this one is for humans reading the rendered
    Markdown.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
