"""File-IPC contract (WA1 B4).

Documents and scaffolds the on-disk directory layout for orchestrator↔
Code-wrapper handoff. This is a CONTRACT module — it defines paths,
naming conventions, and helpers for marker files. It does NOT run a
wrapper or a daemon. WA4 (orchestrator daemon) and a future Phase-42-
descended Code wrapper both bind to this layout.

Read the companion doc ``workflow-automation/ipc_contract.md`` for the
prose description + rationale; this module is the executable
expression of the same contract.

Directory layout (relative to the IPC root passed in by the caller —
typically a sibling of the state dir)::

    ipc_root/
    ├── inbox/                     # planner → Code wrapper
    │   ├── <spec_id>.md           # spec the wrapper picks up
    │   └── <spec_id>.ready        # zero-byte marker; signals "the .md
    │                              #   above is complete + ready to pick up"
    ├── outbox/                    # Code wrapper → planner
    │   ├── <spec_id>.closeout.md  # closeout the daemon reads
    │   └── <spec_id>.closeout.done # zero-byte marker; "closeout written"
    ├── signals/                   # transient state-transition markers
    │   ├── <signal>.signal        # presence indicates the signal fired;
    │   │                          #   contents are JSON detail (optional)
    │   └── ...
    └── workdir/                   # scratch space for the Code wrapper
                                   # (per-pass cwd; mirrors Phase 42's
                                   # cwd-discipline finding)

Marker discipline:

* The planner writes a spec by (1) writing the `.md`, (2) fsyncing,
  (3) creating the `.ready` zero-byte marker. The wrapper polls for
  `.ready` files; finding one is the trigger to claim the spec. This
  avoids the wrapper picking up a half-written `.md`.

* The wrapper signals a closeout by (1) writing the `.closeout.md`,
  (2) fsync, (3) creating the `.closeout.done` marker. The daemon
  polls outbox for `.closeout.done`.

* Both sides MUST treat marker files as "carry the data file's name +
  a known suffix"; no business data is encoded in the marker file
  itself. Marker presence is the signal; contents (if any) are JSON
  for forensic / audit use only.

Concurrency stance: single-writer per direction. The planner is the
sole writer to `inbox/`; the wrapper is the sole writer to `outbox/`.
The opposing party is read-only on the other side's directory. No
locks needed.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


READY_SUFFIX = ".ready"
CLOSEOUT_DATA_SUFFIX = ".closeout.md"
CLOSEOUT_MARKER_SUFFIX = ".closeout.done"
SIGNAL_SUFFIX = ".signal"


@dataclass
class IPCLayout:
    """File-IPC root + the four subdirectory pointers.

    Instances are cheap; construct one wherever you need to write/read
    IPC files. ``ensure()`` creates the directory tree on disk; the
    constructor itself does not touch the filesystem.
    """
    root: Path

    @property
    def inbox(self) -> Path:
        return self.root / "inbox"

    @property
    def outbox(self) -> Path:
        return self.root / "outbox"

    @property
    def signals(self) -> Path:
        return self.root / "signals"

    @property
    def workdir(self) -> Path:
        return self.root / "workdir"

    # ----- setup -----

    def ensure(self) -> None:
        """Create the IPC directory tree on disk. Safe to call
        repeatedly (idempotent)."""
        for sub in (self.inbox, self.outbox, self.signals, self.workdir):
            sub.mkdir(parents=True, exist_ok=True)

    # ----- inbox (planner → wrapper) -----

    def write_spec(self, spec_id: str, body: str) -> Path:
        """Atomically write a spec into the inbox + drop the .ready
        marker. Returns the path of the spec `.md` file.

        The body is written via temp-then-replace (atomic), then the
        marker is written as a separate file. The wrapper polls for
        `.ready` files; only after the marker exists is the spec
        guaranteed to be complete.
        """
        _validate_spec_id(spec_id)
        self.inbox.mkdir(parents=True, exist_ok=True)
        spec_path = self.inbox / f"{spec_id}.md"
        _atomic_write_text(spec_path, body)
        marker_path = self.inbox / f"{spec_id}{READY_SUFFIX}"
        # Marker file is zero-byte. Touch it after the spec is durable.
        marker_path.write_bytes(b"")
        return spec_path

    def list_ready_specs(self) -> list[str]:
        """Return spec_ids whose `.ready` marker is present in inbox,
        in lexical order. The wrapper polls this.
        """
        if not self.inbox.is_dir():
            return []
        return sorted(
            p.name[: -len(READY_SUFFIX)]
            for p in self.inbox.iterdir()
            if p.name.endswith(READY_SUFFIX) and p.is_file()
        )

    def read_spec(self, spec_id: str) -> str:
        _validate_spec_id(spec_id)
        return (self.inbox / f"{spec_id}.md").read_text(encoding="utf-8")

    def claim_spec(self, spec_id: str) -> None:
        """Wrapper-side: remove the `.ready` marker so this spec
        isn't picked up twice. The `.md` file is left in place for
        the wrapper's working reference + audit.
        """
        _validate_spec_id(spec_id)
        marker = self.inbox / f"{spec_id}{READY_SUFFIX}"
        try:
            marker.unlink()
        except FileNotFoundError:
            # Already claimed (race against another reader, or the
            # planner withdrew the spec). Idempotent.
            pass

    # ----- outbox (wrapper → planner) -----

    def write_closeout(self, spec_id: str, body: str) -> Path:
        """Wrapper-side: atomically write a closeout + drop the
        `.closeout.done` marker. Returns the closeout file path.
        """
        _validate_spec_id(spec_id)
        self.outbox.mkdir(parents=True, exist_ok=True)
        closeout_path = self.outbox / f"{spec_id}{CLOSEOUT_DATA_SUFFIX}"
        _atomic_write_text(closeout_path, body)
        marker_path = self.outbox / f"{spec_id}{CLOSEOUT_MARKER_SUFFIX}"
        marker_path.write_bytes(b"")
        return closeout_path

    def list_completed_closeouts(self) -> list[str]:
        """Daemon-side: spec_ids with a fresh `.closeout.done`
        marker in outbox."""
        if not self.outbox.is_dir():
            return []
        return sorted(
            p.name[: -len(CLOSEOUT_MARKER_SUFFIX)]
            for p in self.outbox.iterdir()
            if p.name.endswith(CLOSEOUT_MARKER_SUFFIX) and p.is_file()
        )

    def read_closeout(self, spec_id: str) -> str:
        _validate_spec_id(spec_id)
        return (
            self.outbox / f"{spec_id}{CLOSEOUT_DATA_SUFFIX}"
        ).read_text(encoding="utf-8")

    def consume_closeout(self, spec_id: str) -> None:
        """Daemon-side: remove the `.closeout.done` marker once the
        closeout has been processed. The data file is left in place
        for audit; archive policy is a later WA concern.
        """
        _validate_spec_id(spec_id)
        marker = self.outbox / f"{spec_id}{CLOSEOUT_MARKER_SUFFIX}"
        try:
            marker.unlink()
        except FileNotFoundError:
            pass

    # ----- signals -----

    def post_signal(self, name: str, detail: dict[str, Any] | None = None) -> Path:
        """Drop a signal file. ``name`` is the signal identifier
        (e.g. "planner.rotated"); ``detail`` is optional JSON
        forensic content. Signals are not consumed automatically;
        the reader is expected to ``clear_signal`` after acting.
        """
        _validate_signal_name(name)
        self.signals.mkdir(parents=True, exist_ok=True)
        path = self.signals / f"{name}{SIGNAL_SUFFIX}"
        if detail is None:
            path.write_bytes(b"")
        else:
            _atomic_write_text(path, json.dumps(detail, indent=2))
        return path

    def list_signals(self) -> list[str]:
        if not self.signals.is_dir():
            return []
        return sorted(
            p.name[: -len(SIGNAL_SUFFIX)]
            for p in self.signals.iterdir()
            if p.name.endswith(SIGNAL_SUFFIX) and p.is_file()
        )

    def read_signal(self, name: str) -> dict[str, Any] | None:
        """Return the signal's JSON detail, or None if it's a
        zero-byte marker. Raises FileNotFoundError if the signal
        isn't present.
        """
        _validate_signal_name(name)
        path = self.signals / f"{name}{SIGNAL_SUFFIX}"
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return None
        return json.loads(raw)

    def clear_signal(self, name: str) -> None:
        _validate_signal_name(name)
        path = self.signals / f"{name}{SIGNAL_SUFFIX}"
        try:
            path.unlink()
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_spec_id(spec_id: str) -> None:
    """Reject spec IDs that would escape the inbox/outbox dir or
    collide with markers. Keeps paths predictable; no shell-injection
    surface."""
    if not spec_id or not isinstance(spec_id, str):
        raise ValueError(f"spec_id must be a non-empty string; got {spec_id!r}")
    if any(ch in spec_id for ch in ("/", "\\", "\x00", "..")):
        raise ValueError(
            f"spec_id {spec_id!r} contains path separators or traversal — "
            "use a flat identifier like 'wa1' or 'phase43_front_door'."
        )


def _validate_signal_name(name: str) -> None:
    if not name or not isinstance(name, str):
        raise ValueError(f"signal name must be a non-empty string; got {name!r}")
    if any(ch in name for ch in ("/", "\\", "\x00", "..")):
        raise ValueError(
            f"signal name {name!r} contains path separators or traversal."
        )


def _atomic_write_text(target: Path, text: str) -> None:
    """Atomic write via temp-then-`os.replace`. Mirrors the pattern in
    ``checkpoint.StateStore.write`` so the same crash-safety holds
    for IPC payloads.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path_str = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp_path, target)
    except BaseException:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise
