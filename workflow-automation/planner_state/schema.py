"""Planner-state schema (WA1 B1).

Versioned dataclasses + JSON I/O. The schema is deliberately small —
only fields the planner-daemon and the fresh-planner-bootstrap will
clearly need. Forward-compat is via ``schema_version`` (the loader
rejects unknown major versions loudly so a future migration is
forced, rather than silently mis-parsed).

Fields chosen to satisfy two concrete consumers:

  1. The fresh-planner cold-start reconstruction (the WA1 B5 validation):
     a `claude -p` reading the rendered Markdown must be able to
     restate the project's situation accurately. ``project`` +
     ``loop_state`` + recent ``decisions`` are what carry that.

  2. The passdown generator (WA1 B3): a human-readable doc replacing
     today's hand-written passdown. Same fields, rendered for human
     consumption — what's in flight, what's pending/blocked, what
     decisions are locked.

What's NOT in the schema (intentional):

  * No secrets, tokens, or credentials. State is project context only;
    auth lives in env/config (handled in WA6 / phone-channel pass).
  * No raw conversation transcripts. The ``working_context_digest``
    field carries a planner-curated rolling summary; raw transcripts
    are out of scope and would explode the state size.
  * No per-pass spec/closeout bodies. Those live as files on disk and
    are referenced by path/pointer, not embedded.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# Bump on backwards-incompatible field changes. The loader refuses to
# parse unknown majors and tells the caller to migrate explicitly.
SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Nested types
# ---------------------------------------------------------------------------

@dataclass
class Project:
    """High-level project identity + a pointer to the canonical state
    description. The cold-start planner uses this to know what project
    it's working on; the ``current_pointer`` is a one-line summary of
    "where the platform is now" (e.g., the most recent shipped phase +
    master commit + any flag-state context).
    """
    name: str
    repo_root: str = ""
    prod_url: str = ""
    current_pointer: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LoopState:
    """What's in flight + what's pending/blocked.

    ``current_pass`` is the name of the work-pass under planner attention
    (e.g., "WA1 — State & IPC Foundation" or "Phase 43 — Front Door &
    Help"). ``current_pass_status`` is one of the values in
    ``LOOP_STATUSES`` — kept as a string (not an Enum) so JSON round-trip
    stays dependency-free.

    ``last_code_activity`` is a snapshot of the most recent Code-team
    activity the planner is aware of: pass name, timestamp, one-line
    summary, result classification. Used to compute "stuck" vs "active"
    in the daemon (later WA pass) and to surface "what just happened"
    on the dashboard.
    """
    current_pass: str | None = None
    current_pass_status: str = "idle"
    pending: list[str] = field(default_factory=list)
    blocked: list[dict[str, str]] = field(default_factory=list)
    last_code_activity: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


LOOP_STATUSES = frozenset({
    "idle",
    "spec_written",
    "dispatched",
    "in_progress",
    "closing_out",
    "shipped",
    "blocked",
})


@dataclass
class Decision:
    """Append-only decision log entry. Decisions are the load-bearing
    locked choices the planner has made with Z (or autonomously) —
    things a later planner instance must not re-litigate.

    Mirrors the shape the planning-agent passdowns already use ("locked
    decisions" sections in spec docs).
    """
    date: str  # ISO-8601 UTC (e.g. "2026-05-30T14:33:00Z")
    topic: str
    decision: str
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Root state
# ---------------------------------------------------------------------------

@dataclass
class PlannerState:
    """Top-level planner state.

    Round-trip via ``to_json()`` / ``from_json()``. The JSON format is
    the canonical on-disk representation; the dataclass is the
    in-process view. ``schema_version`` is the load-time guard.
    """
    schema_version: int = SCHEMA_VERSION
    project: Project = field(default_factory=lambda: Project(name=""))
    loop_state: LoopState = field(default_factory=LoopState)
    decisions: list[Decision] = field(default_factory=list)
    working_context_digest: str = ""

    # ----- factory helpers -----

    @classmethod
    def empty(cls, project_name: str) -> "PlannerState":
        """A fresh state with just the project name set. Used when
        bootstrapping a new state dir from scratch."""
        return cls(
            schema_version=SCHEMA_VERSION,
            project=Project(name=project_name),
            loop_state=LoopState(),
            decisions=[],
            working_context_digest="",
        )

    # ----- JSON round-trip -----

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project": self.project.to_dict(),
            "loop_state": self.loop_state.to_dict(),
            "decisions": [d.to_dict() for d in self.decisions],
            "working_context_digest": self.working_context_digest,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=False)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PlannerState":
        validate_schema(raw)
        proj_raw = raw.get("project") or {}
        loop_raw = raw.get("loop_state") or {}
        return cls(
            schema_version=raw["schema_version"],
            project=Project(
                name=proj_raw.get("name", ""),
                repo_root=proj_raw.get("repo_root", ""),
                prod_url=proj_raw.get("prod_url", ""),
                current_pointer=proj_raw.get("current_pointer", ""),
            ),
            loop_state=LoopState(
                current_pass=loop_raw.get("current_pass"),
                current_pass_status=loop_raw.get("current_pass_status", "idle"),
                pending=list(loop_raw.get("pending", [])),
                blocked=list(loop_raw.get("blocked", [])),
                last_code_activity=loop_raw.get("last_code_activity"),
            ),
            decisions=[
                Decision(
                    date=d.get("date", ""),
                    topic=d.get("topic", ""),
                    decision=d.get("decision", ""),
                    rationale=d.get("rationale", ""),
                )
                for d in raw.get("decisions", [])
            ],
            working_context_digest=raw.get("working_context_digest", ""),
        )

    @classmethod
    def from_json(cls, text: str) -> "PlannerState":
        return cls.from_dict(json.loads(text))

    @classmethod
    def from_path(cls, path: Path | str) -> "PlannerState":
        return cls.from_json(Path(path).read_text(encoding="utf-8"))


class SchemaVersionMismatch(ValueError):
    """The on-disk state declares a schema_version this code can't read.

    Carries the on-disk and supported versions so the caller can either
    migrate or refuse to load.
    """

    def __init__(self, on_disk: Any, supported: int) -> None:
        super().__init__(
            f"State on-disk schema_version={on_disk!r}; this code "
            f"only reads schema_version={supported}. A migration is "
            "required; do not silently downgrade or coerce."
        )
        self.on_disk = on_disk
        self.supported = supported


def validate_schema(raw: dict[str, Any]) -> None:
    """Reject obviously-malformed state up-front so the caller doesn't
    have to defensively .get() every field. The validator is
    intentionally narrow — it asserts the load-time guarantees the
    rest of the package relies on, not full structural correctness.
    """
    if not isinstance(raw, dict):
        raise ValueError(
            f"Planner state must be a JSON object at the top level; "
            f"got {type(raw).__name__}."
        )
    if "schema_version" not in raw:
        raise ValueError(
            "Planner state is missing the required 'schema_version' "
            "field; refuse to parse rather than guess."
        )
    on_disk = raw["schema_version"]
    if not isinstance(on_disk, int):
        raise ValueError(
            f"schema_version must be an int; got {type(on_disk).__name__}."
        )
    if on_disk != SCHEMA_VERSION:
        raise SchemaVersionMismatch(on_disk, SCHEMA_VERSION)


def now_iso() -> str:
    """UTC timestamp in seconds precision, ISO 8601 with 'Z' suffix.

    Used as the default for Decision.date when the caller doesn't pass
    one explicitly. Mirrors the convention in the repo's existing
    audit-log / spec / closeout text.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
