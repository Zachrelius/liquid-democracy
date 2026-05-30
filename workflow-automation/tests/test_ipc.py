"""File-IPC contract tests (WA1 B5).

Pins the marker-discipline + atomic-write behavior the WA4 daemon and
the Code wrapper will both rely on. If these tests fail in a future
pass, the contract has drifted and both sides need to be updated in
lockstep — DON'T just patch one side to make the test pass.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from planner_state.ipc import (
    CLOSEOUT_DATA_SUFFIX,
    CLOSEOUT_MARKER_SUFFIX,
    IPCLayout,
    READY_SUFFIX,
    SIGNAL_SUFFIX,
)


def _layout(tmp_path: Path) -> IPCLayout:
    layout = IPCLayout(tmp_path / "ipc")
    layout.ensure()
    return layout


def test_ensure_creates_all_subdirs(tmp_path: Path):
    layout = _layout(tmp_path)
    assert layout.inbox.is_dir()
    assert layout.outbox.is_dir()
    assert layout.signals.is_dir()
    assert layout.workdir.is_dir()


def test_ensure_is_idempotent(tmp_path: Path):
    layout = IPCLayout(tmp_path / "ipc")
    layout.ensure()
    layout.ensure()
    assert layout.inbox.is_dir()


# ---------------------------------------------------------------------------
# inbox (planner → wrapper)
# ---------------------------------------------------------------------------

def test_write_spec_creates_data_and_marker(tmp_path: Path):
    layout = _layout(tmp_path)
    layout.write_spec("wa1", "# WA1 spec\n\nbody.")
    assert (layout.inbox / "wa1.md").is_file()
    assert (layout.inbox / f"wa1{READY_SUFFIX}").is_file()


def test_list_ready_specs_returns_marked_ids(tmp_path: Path):
    layout = _layout(tmp_path)
    layout.write_spec("wa1", "spec A")
    layout.write_spec("wa2", "spec B")
    assert layout.list_ready_specs() == ["wa1", "wa2"]


def test_list_ready_specs_ignores_unmarked_data_files(tmp_path: Path):
    """If a spec .md exists WITHOUT a .ready marker, the wrapper must
    not pick it up — that's the "writer is mid-write" case the marker
    discipline is designed to prevent.
    """
    layout = _layout(tmp_path)
    # Drop a bare .md with no marker.
    (layout.inbox / "halfwritten.md").write_text("partial body", encoding="utf-8")
    assert layout.list_ready_specs() == []


def test_read_spec_returns_body(tmp_path: Path):
    layout = _layout(tmp_path)
    layout.write_spec("wa1", "# Body content")
    assert layout.read_spec("wa1") == "# Body content"


def test_claim_spec_removes_marker_but_keeps_data(tmp_path: Path):
    layout = _layout(tmp_path)
    layout.write_spec("wa1", "spec body")
    layout.claim_spec("wa1")
    assert not (layout.inbox / f"wa1{READY_SUFFIX}").exists()
    # The data file is preserved for the wrapper's reference / audit.
    assert (layout.inbox / "wa1.md").is_file()
    # And the wrapper sees no ready-to-claim specs anymore.
    assert layout.list_ready_specs() == []


def test_claim_spec_is_idempotent(tmp_path: Path):
    layout = _layout(tmp_path)
    layout.write_spec("wa1", "spec body")
    layout.claim_spec("wa1")
    layout.claim_spec("wa1")  # No-op, no error.


# ---------------------------------------------------------------------------
# outbox (wrapper → planner)
# ---------------------------------------------------------------------------

def test_write_closeout_creates_data_and_marker(tmp_path: Path):
    layout = _layout(tmp_path)
    layout.write_closeout("wa1", "# Closeout\n\nResult: SHIPPED.")
    assert (layout.outbox / f"wa1{CLOSEOUT_DATA_SUFFIX}").is_file()
    assert (layout.outbox / f"wa1{CLOSEOUT_MARKER_SUFFIX}").is_file()


def test_list_completed_closeouts_matches_markers(tmp_path: Path):
    layout = _layout(tmp_path)
    layout.write_closeout("wa1", "co A")
    layout.write_closeout("wa2", "co B")
    assert layout.list_completed_closeouts() == ["wa1", "wa2"]


def test_read_closeout_returns_body(tmp_path: Path):
    layout = _layout(tmp_path)
    layout.write_closeout("wa1", "body of closeout")
    assert layout.read_closeout("wa1") == "body of closeout"


def test_consume_closeout_removes_marker_only(tmp_path: Path):
    layout = _layout(tmp_path)
    layout.write_closeout("wa1", "body")
    layout.consume_closeout("wa1")
    assert not (layout.outbox / f"wa1{CLOSEOUT_MARKER_SUFFIX}").exists()
    # Data file kept for audit.
    assert (layout.outbox / f"wa1{CLOSEOUT_DATA_SUFFIX}").is_file()


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

def test_post_signal_zero_byte_marker(tmp_path: Path):
    layout = _layout(tmp_path)
    path = layout.post_signal("planner.rotated")
    assert path.is_file()
    assert path.read_bytes() == b""
    assert "planner.rotated" in layout.list_signals()


def test_post_signal_with_detail_writes_json(tmp_path: Path):
    layout = _layout(tmp_path)
    layout.post_signal("planner.rotated", {"new_session_id": "abc-123"})
    detail = layout.read_signal("planner.rotated")
    assert detail == {"new_session_id": "abc-123"}


def test_read_signal_returns_none_for_zero_byte_marker(tmp_path: Path):
    layout = _layout(tmp_path)
    layout.post_signal("daemon.heartbeat")
    assert layout.read_signal("daemon.heartbeat") is None


def test_clear_signal_removes_marker(tmp_path: Path):
    layout = _layout(tmp_path)
    layout.post_signal("daemon.shutdown_requested")
    layout.clear_signal("daemon.shutdown_requested")
    assert layout.list_signals() == []


def test_clear_signal_is_idempotent(tmp_path: Path):
    layout = _layout(tmp_path)
    layout.clear_signal("never_posted")  # No-op.


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_id", [
    "",
    "wa/1",
    "wa\\1",
    "../escape",
    "wa\x00bad",
])
def test_spec_id_rejects_path_traversal_and_bad_chars(tmp_path: Path, bad_id):
    layout = _layout(tmp_path)
    with pytest.raises(ValueError):
        layout.write_spec(bad_id, "body")


@pytest.mark.parametrize("bad_name", [
    "",
    "a/b",
    "..",
])
def test_signal_name_rejects_path_traversal(tmp_path: Path, bad_name):
    layout = _layout(tmp_path)
    with pytest.raises(ValueError):
        layout.post_signal(bad_name)


# ---------------------------------------------------------------------------
# Atomic write semantics (sample one IPC path)
# ---------------------------------------------------------------------------

def test_spec_write_is_atomic_against_crash(tmp_path: Path, monkeypatch):
    """If os.replace fails mid-write, the prior spec file (if any) is
    unchanged AND no half-written spec is visible. Mirrors the
    StateStore atomicity test but for the IPC payload path.
    """
    layout = _layout(tmp_path)
    layout.write_spec("wa1", "original body")
    original_text = (layout.inbox / "wa1.md").read_text(encoding="utf-8")

    original_replace = os.replace

    def _crash(src, dst):  # type: ignore[no-untyped-def]
        # Only crash on the spec data file's replace, not on the marker
        # (the marker uses .write_bytes which doesn't go through
        # os.replace; this confines the simulated failure to the
        # atomic-data-write path).
        raise RuntimeError("simulated crash mid-write")

    monkeypatch.setattr(os, "replace", _crash)
    with pytest.raises(RuntimeError):
        layout.write_spec("wa1", "DIFFERENT body — should not land")
    monkeypatch.setattr(os, "replace", original_replace)

    # Original spec file unchanged.
    after_text = (layout.inbox / "wa1.md").read_text(encoding="utf-8")
    assert after_text == original_text
