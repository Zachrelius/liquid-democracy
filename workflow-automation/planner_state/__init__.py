"""WA1 — Planner state foundation.

A versioned, on-disk state model + atomic checkpoint writer + bootstrap/
passdown renderers for the workflow-automation track's persistent planner.

This package is a LIBRARY. It does not run a daemon, does not call LLMs,
does not touch the website app code. Higher-level WA passes (WA3
dashboard, WA4 orchestrator daemon, etc.) build on this layer.

Public surface:

    from planner_state import (
        PlannerState,            # the schema (dataclass + JSON I/O)
        StateStore,              # atomic checkpoint writer + reader
        SCHEMA_VERSION,
        render_bootstrap,        # Markdown the fresh planner reads
        render_passdown,         # human-readable passdown
        IPCLayout,               # the daemon↔Code-wrapper file contract
    )

The CLI entry point is ``python -m planner_state.cli`` — see that
module for the bootstrap/passdown/cold-start subcommands.
"""
from .schema import PlannerState, SCHEMA_VERSION, Decision, LoopState, Project
from .checkpoint import StateStore, StateCorruptionError
from .bootstrap import render_bootstrap
from .passdown import render_passdown
from .ipc import IPCLayout

__all__ = [
    "PlannerState",
    "SCHEMA_VERSION",
    "Decision",
    "LoopState",
    "Project",
    "StateStore",
    "StateCorruptionError",
    "render_bootstrap",
    "render_passdown",
    "IPCLayout",
]
