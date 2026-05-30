# workflow-automation/

Workflow-automation track. Separate from the website's `phaseXX_*` sequence; everything for this initiative lives under this directory. See `workflow_automation_overview.md` for the project anchor doc.

## What's in this directory

| Path | What it is |
|---|---|
| `workflow_automation_overview.md` | Anchor doc — goals, architecture, gates, roadmap. Read first. |
| `wa1_state_and_ipc_foundation_spec.md` | WA1 spec (this pass). |
| `wa2_architecture_validation_spike_spec.md` | WA2 spec (next pass). |
| `ipc_contract.md` | The orchestrator↔Code-wrapper file-IPC contract (WA1 B4). Stable contract; bumps version on incompatible change. |
| `planner_state/` | Python package — versioned state schema, atomic checkpoint writer, bootstrap/passdown renderers, IPC scaffolding, CLI. |
| `tests/` | Pytest suite. Run from this directory: `python -m pytest tests/` |
| `examples/sample_state.json` | Reference state used by docs + cold-start validation. |
| `ipc_scaffold/` | Empty IPC root directory (created on-demand by `IPCLayout.ensure()`). |

## Install / run

The package is plain Python — no install needed. The repo's existing `backend/.venv` works:

```bash
# from workflow-automation/
../backend/.venv/Scripts/python.exe -m pytest tests/
../backend/.venv/Scripts/python.exe -m planner_state.cli bootstrap path/to/state_dir
../backend/.venv/Scripts/python.exe -m planner_state.cli passdown path/to/state_dir
../backend/.venv/Scripts/python.exe -m planner_state.cli cold-start path/to/state_dir
```

The `cold-start` subcommand requires the `claude` CLI on PATH and runs on Max (Phase 42 lesson — `ANTHROPIC_API_KEY` is unset in the subprocess env).

## Public API

```python
from planner_state import (
    PlannerState,        # the schema (dataclass + JSON I/O)
    StateStore,          # atomic checkpoint writer + reader
    SCHEMA_VERSION,
    render_bootstrap,    # Markdown a fresh planner reads
    render_passdown,     # human-readable passdown
    IPCLayout,           # the daemon↔Code-wrapper file contract
)

# Typical flow
store = StateStore(state_dir)
state = store.load_or_init(project_name="Liquid Democracy")
store.update_loop_state(current_pass="WA1", current_pass_status="in_progress")
store.append_decision(
    topic="Auth model",
    decision="Shell out to claude -p; no Agent SDK",
    rationale="Max OAuth incompatible with Agent SDK",
)
# Render Markdown views
print(render_bootstrap(state))
print(render_passdown(state))
```

## Convention reminders

- This track does NOT touch website app code (`backend/`, `frontend/`). A WA pass needing to touch it is out of scope.
- No Alembic migrations, no Railway deploy, no PG smoke, no frontend bundle. The track's verification is its own pytest suite + per-spec validation.
- Branches: `wa-N/short-name`. Merge `--no-ff` to master.
- Co-located in this repo through WA1/WA2 (validation passes); splits to a dedicated repo before WA4 (live daemon).

## Status

| Pass | Status | Notes |
|---|---|---|
| WA1 | DONE — this pass | State + checkpoint + bootstrap + passdown + IPC contract + tests + cold-start validation. |
| WA2 | Specced; next | Architecture validation spike (planner continuity at scale, Playwright MCP from `claude -p`, dashboard hook pattern, Slack bridge feasibility). |
| WA3 | Spec TBD | At-desk dashboard. Gated on WA2's hook-pattern findings. |
| WA4 | Spec TBD | Orchestrator daemon + planner-session core + Code dispatch. Binds to WA1 state + IPC contract. |
| WA5 | Spec TBD | Autonomous QA agent (Playwright MCP). |
| WA6 | Spec TBD | Phone channel (Slack via cc-connect-style bridge). |
| WA7 | Spec TBD | Full loop + failure handling + checkpoint/rotation hardening. |
