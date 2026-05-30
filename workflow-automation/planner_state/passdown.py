"""Passdown generator (WA1 B3 — second half).

Goal-5 deliverable: an automated, human-readable passdown doc that
replaces today's hand-written passdown effort. The planning agent
hands this to a fresh planner instance (or to Z, between sessions);
it should read like the planning-agent passdowns already in the repo.

The shape is deliberately similar to the bootstrap render but framed
for human consumption first, with brevity prioritized. The two outputs
overlap in source data but diverge in tone:

* **bootstrap** — "you are a fresh agent; here is everything you need
  before doing anything else." Long-form, includes the decisions log
  in full, includes a pointer to the on-disk state.

* **passdown** — "here is the state of play at the moment of handoff."
  Shorter, summarizes decisions instead of listing them all, focuses
  on what's in flight and what's blocked. Suitable for Z to skim on
  phone or for a fresh planner to read inline rather than reload.

The two functions live in separate modules so that downstream consumers
(WA3 dashboard, WA6 phone-channel) can pull the passdown rendering
without dragging the bootstrap doc's verbosity.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .schema import PlannerState


def render_passdown(
    state: PlannerState,
    *,
    max_decisions: int = 6,
) -> str:
    """Return a Markdown passdown doc summarizing ``state``.

    ``max_decisions`` caps how many recent decisions are inlined; older
    ones are summarized as a count. The default (6) is tuned for "fits
    on a phone screen / readable in 30 seconds." Pass a larger number
    for a richer passdown.
    """
    lines: list[str] = []

    title = state.project.name or "Project"
    lines.append(f"# Passdown — {title}")
    lines.append("")
    lines.append(f"*Generated {_now_human()}.*")
    lines.append("")

    if state.project.current_pointer:
        lines.append(f"**Current platform state:** {state.project.current_pointer}")
        lines.append("")

    # ----- What's in flight -----
    ls = state.loop_state
    lines.append("## In flight")
    lines.append("")
    if ls.current_pass:
        lines.append(
            f"- **{ls.current_pass}** — status `{ls.current_pass_status}`"
        )
    else:
        lines.append(f"- No pass in flight (status `{ls.current_pass_status}`).")
    lines.append("")

    # ----- Pending -----
    lines.append("## Pending")
    lines.append("")
    if ls.pending:
        for item in ls.pending:
            lines.append(f"- {item}")
    else:
        lines.append("- (none)")
    lines.append("")

    # ----- Blocked -----
    lines.append("## Blocked")
    lines.append("")
    if ls.blocked:
        for entry in ls.blocked:
            item = entry.get("item", "(unspecified)")
            reason = entry.get("reason", "")
            if reason:
                lines.append(f"- {item} — *{reason}*")
            else:
                lines.append(f"- {item}")
    else:
        lines.append("- (none)")
    lines.append("")

    # ----- Last Code activity (short) -----
    if ls.last_code_activity:
        lines.append("## Last Code activity")
        lines.append("")
        lca = ls.last_code_activity
        bits: list[str] = []
        if "pass" in lca:
            bits.append(f"**{lca['pass']}**")
        if "result" in lca:
            bits.append(f"({lca['result']})")
        if "timestamp" in lca:
            bits.append(f"at {lca['timestamp']}")
        if bits:
            lines.append("- " + " ".join(bits))
        if "summary" in lca and lca["summary"]:
            lines.append(f"  {lca['summary']}")
        lines.append("")

    # ----- Recent decisions (capped) -----
    lines.append("## Recent locked decisions")
    lines.append("")
    if not state.decisions:
        lines.append("- (none recorded)")
    else:
        recent = list(state.decisions[-max_decisions:])
        older_count = max(0, len(state.decisions) - max_decisions)
        for d in recent:
            lines.append(f"- **{d.topic}** *({d.date})* — {d.decision}")
        if older_count:
            lines.append(
                f"- *(plus {older_count} earlier decision"
                f"{'s' if older_count != 1 else ''}; "
                "see the bootstrap doc or `decisions[]` in state for the full log.)*"
            )
    lines.append("")

    # ----- Working-context digest (verbatim if short, summary-pointer if long) -----
    digest = state.working_context_digest.strip()
    if digest:
        lines.append("## Working-context digest")
        lines.append("")
        lines.append(digest)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _now_human() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
