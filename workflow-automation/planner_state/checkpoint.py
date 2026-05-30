"""Atomic checkpoint writer (WA1 B2).

State persistence with crash-safety: writes go to a sibling temp file
and ``os.replace`` atomically swaps it into place. The prior good
state survives any mid-write interruption (process crash, power loss,
OS reboot under the daemon).

Concurrency stance — this layer is single-writer. The orchestrator
daemon owns the state dir; nothing else should be writing into it
concurrently. We don't take a lock here because (a) the daemon is the
sole writer, and (b) advisory locks differ painfully between Unix and
Windows and aren't worth the dependency for the no-concurrency case.
If a future WA pass introduces a second writer, it grows a
``filelock`` dependency at that point — not preemptively.

Reads are tolerant of being interleaved with writes because the
``os.replace`` swap is atomic on POSIX and Windows-same-volume (which
is our deployment shape — the state dir is a single subtree).

The class API mirrors the spec's sketched surface
(``state.update(...)``, ``state.append_decision(...)``,
``state.snapshot()``) — kept small. ``snapshot()`` returns an
in-memory copy; ``flush()`` is the explicit "write to disk now" call.
``update_loop_state`` is exposed because the daemon will hit it on
every tick.
"""
from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from .schema import (
    Decision,
    LoopState,
    PlannerState,
    Project,
    SchemaVersionMismatch,
    now_iso,
    validate_schema,
)


STATE_FILENAME = "planner_state.json"


class StateCorruptionError(RuntimeError):
    """Raised when the on-disk state file exists but can't be parsed —
    most often because a *previous* writer was killed before the
    ``os.replace`` swap (the temp file is left behind but the
    canonical file is unchanged — that's the design). If this fires
    on the canonical file itself, something has gone wrong outside
    the writer's control (manual edit, disk corruption, etc.).
    """


class StateStore:
    """Filesystem-backed planner-state store with atomic checkpoint
    writes.

    The on-disk layout is one JSON file at
    ``{state_dir}/planner_state.json``. Writes are atomic via the
    temp-file + ``os.replace`` dance. Reads parse straight from the
    canonical path.

    Typical use::

        store = StateStore(state_dir)
        state = store.load_or_init(project_name="Liquid Democracy")
        state.loop_state.current_pass = "WA1 — State & IPC Foundation"
        store.write(state)
        # ...
        store.append_decision(
            topic="State format split",
            decision="JSON machine + Markdown view",
            rationale="Phase 42 showed claude -p reads Markdown fast",
        )
    """

    def __init__(self, state_dir: Path | str) -> None:
        self.state_dir = Path(state_dir)
        self.state_path = self.state_dir / STATE_FILENAME

    # ----- load -----

    def exists(self) -> bool:
        return self.state_path.is_file()

    def load(self) -> PlannerState:
        """Load the on-disk state. Raises StateCorruptionError if the
        file exists but can't be parsed; raises FileNotFoundError if
        the file isn't there.
        """
        if not self.state_path.is_file():
            raise FileNotFoundError(
                f"No planner state at {self.state_path}. Call "
                "load_or_init() to bootstrap a fresh one."
            )
        text = self.state_path.read_text(encoding="utf-8")
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as e:
            raise StateCorruptionError(
                f"Planner state at {self.state_path} is not valid JSON "
                f"({e}). Check whether a previous writer was killed "
                "before the atomic-rename step — the canonical file "
                "shouldn't be left mid-write because os.replace is "
                "atomic. If it IS mid-write, that's a bug or external "
                "interference."
            ) from e
        try:
            validate_schema(raw)
        except SchemaVersionMismatch:
            raise
        except ValueError as e:
            raise StateCorruptionError(
                f"Planner state at {self.state_path} failed schema "
                f"validation: {e}"
            ) from e
        return PlannerState.from_dict(raw)

    def load_or_init(self, *, project_name: str) -> PlannerState:
        """Load existing state, or create + persist a fresh empty
        state if none exists. Convenience for the orchestrator's
        "start up and figure out where you are" path.
        """
        if self.exists():
            return self.load()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        fresh = PlannerState.empty(project_name)
        self.write(fresh)
        return fresh

    # ----- write -----

    def write(self, state: PlannerState) -> None:
        """Atomically persist ``state`` to ``{state_dir}/planner_state.json``.

        Implementation: write to a sibling temp file in the SAME
        directory (so ``os.replace`` is same-volume → atomic on both
        POSIX and Windows), fsync the file (so the bytes are durable
        before the rename), then ``os.replace`` over the canonical
        path.

        On Windows ``os.replace`` is documented to atomically replace
        an existing file when source + dest are on the same volume.
        We don't cross volumes — the temp file is in ``state_dir``.
        """
        self.state_dir.mkdir(parents=True, exist_ok=True)
        text = state.to_json()
        # tempfile.NamedTemporaryFile would leak a file on rename-failure
        # because it auto-deletes on close; use mkstemp + manual rename so
        # the temp file is durable across the rename window.
        fd, tmp_path_str = tempfile.mkstemp(
            prefix=".planner_state.", suffix=".json.tmp",
            dir=str(self.state_dir),
        )
        tmp_path = Path(tmp_path_str)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                # fsync ensures the bytes hit disk before the rename
                # so a crash between flush and rename can't leave us
                # with a stale (but readable) target after recovery.
                try:
                    os.fsync(f.fileno())
                except OSError:
                    # Some filesystems / mocks don't support fsync;
                    # the rename is still atomic, so this is best-effort.
                    pass
            # os.replace is atomic on same-volume on POSIX + Windows.
            # The temp file's name is replaced by the canonical path
            # in a single syscall — readers see either the prior file
            # or the new one, never a half-written file.
            os.replace(tmp_path, self.state_path)
        except BaseException:
            # If anything failed before the replace, clean up the
            # orphan temp. After replace succeeds, tmp_path no longer
            # exists at this location (the rename moved it).
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            raise

    # ----- mutation helpers -----

    def snapshot(self) -> PlannerState:
        """Return a deep-copy of the current on-disk state. The caller
        can mutate it and pass it back via ``write()``; the copy
        guarantees mid-flight mutations don't accidentally land
        before the explicit write.
        """
        return deepcopy(self.load())

    def update(
        self,
        *,
        project: Project | None = None,
        loop_state: LoopState | None = None,
        working_context_digest: str | None = None,
    ) -> PlannerState:
        """Convenience: load → patch named fields → write atomically.
        Returns the new state.

        Pattern lets the daemon do tiny updates without writing the
        load/mutate/write boilerplate every tick. Pass only what
        you're changing.
        """
        state = self.load()
        if project is not None:
            state.project = project
        if loop_state is not None:
            state.loop_state = loop_state
        if working_context_digest is not None:
            state.working_context_digest = working_context_digest
        self.write(state)
        return state

    def update_loop_state(self, **kwargs: Any) -> PlannerState:
        """Patch only the loop-state sub-fields named in kwargs.
        Useful for the daemon's per-tick "I'm now on phase X" updates.

        Accepted kwargs mirror the LoopState dataclass fields:
        ``current_pass``, ``current_pass_status``, ``pending``,
        ``blocked``, ``last_code_activity``.
        """
        state = self.load()
        valid = {
            "current_pass", "current_pass_status",
            "pending", "blocked", "last_code_activity",
        }
        for key, value in kwargs.items():
            if key not in valid:
                raise TypeError(
                    f"update_loop_state(): unknown field {key!r}; "
                    f"expected one of {sorted(valid)}"
                )
            setattr(state.loop_state, key, value)
        self.write(state)
        return state

    def append_decision(
        self,
        *,
        topic: str,
        decision: str,
        rationale: str = "",
        date: str | None = None,
    ) -> PlannerState:
        """Append a Decision to the log. ``date`` defaults to now (UTC,
        ISO 8601). Decisions are append-only; this helper is the only
        sanctioned way to add one (don't mutate ``state.decisions``
        directly + write — you'd race against any concurrent reader
        for no good reason).
        """
        state = self.load()
        state.decisions.append(Decision(
            date=date or now_iso(),
            topic=topic,
            decision=decision,
            rationale=rationale,
        ))
        self.write(state)
        return state

    # ----- introspection -----

    def list_orphan_temps(self) -> list[Path]:
        """Return any leftover ``.planner_state.*.json.tmp`` files in
        the state dir. These are normally cleaned up by the writer,
        but a process kill between mkstemp and the rename can leave
        one behind. Used by recovery tooling + tests.
        """
        if not self.state_dir.is_dir():
            return []
        return sorted(
            p for p in self.state_dir.iterdir()
            if p.name.startswith(".planner_state.") and p.name.endswith(".json.tmp")
        )
