"""End-to-end tests for the dashboard server (WA3 B2 + B4 + B5
asserting side effects, not just API contract).

Uses FastAPI's TestClient to exercise the HTTP surface + the IPC
round-trip + the quota observation pipeline. The IPC round-trip
test is the load-bearing one — it asserts that
``POST /api/chat`` actually lands a spec + .ready marker in the
IPC inbox per WA1 contract v1.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dashboard.server import init_app
from planner_state import (
    IPCLayout,
    PlannerState,
    StateStore,
    SCHEMA_VERSION,
)
from planner_state.schema import Decision, LoopState, Project
from planner_state.ipc import READY_SUFFIX, CLOSEOUT_MARKER_SUFFIX
from dashboard.stub_responder import drain_once


@pytest.fixture
def dirs(tmp_path: Path):
    state_dir = tmp_path / "state"
    ipc_root = tmp_path / "ipc"
    state_dir.mkdir()
    ipc_root.mkdir()
    return state_dir, ipc_root


@pytest.fixture
def client(dirs):
    state_dir, ipc_root = dirs
    app = init_app(state_dir, ipc_root)
    return TestClient(app)


def _write_sample_state(state_dir: Path) -> PlannerState:
    store = StateStore(state_dir)
    state = PlannerState(
        schema_version=SCHEMA_VERSION,
        project=Project(
            name="WA3-test",
            current_pointer="WA3 dashboard tests in flight",
        ),
        loop_state=LoopState(
            current_pass="WA3 — At-Desk Dashboard",
            current_pass_status="in_progress",
            pending=["B6 verify"],
            blocked=[{"item": "BlockedX", "reason": "Z input needed"}],
        ),
        decisions=[
            Decision(
                date="2026-05-30T15:00:00Z",
                topic="UI framework",
                decision="Vanilla JS only",
                rationale="No bundler; small surface",
            ),
        ],
        working_context_digest="Spike to validate dashboard surface.",
    )
    store.write(state)
    return state


# ---------------------------------------------------------------------------
# State panel (B2)
# ---------------------------------------------------------------------------

def test_state_endpoint_returns_empty_marker_when_no_state(client, dirs):
    r = client.get("/api/state")
    assert r.status_code == 200
    data = r.json()
    assert data["_state"] == "empty"


def test_state_endpoint_returns_full_state_when_present(client, dirs):
    state_dir, _ = dirs
    _write_sample_state(state_dir)
    r = client.get("/api/state")
    assert r.status_code == 200
    data = r.json()
    assert data["project"]["name"] == "WA3-test"
    assert data["loop_state"]["current_pass"] == "WA3 — At-Desk Dashboard"
    assert len(data["decisions"]) == 1
    assert data["decisions"][0]["topic"] == "UI framework"


def test_state_markdown_endpoint_renders_bootstrap(client, dirs):
    state_dir, _ = dirs
    _write_sample_state(state_dir)
    r = client.get("/api/state/markdown")
    assert r.status_code == 200
    body = r.text
    assert "WA3-test" in body
    assert "Planner state" in body or "Loop state" in body  # render headers
    assert "UI framework" in body  # decision body
    assert "Vanilla JS" in body


# ---------------------------------------------------------------------------
# Hook ingest (B1)
# ---------------------------------------------------------------------------

def test_hook_ingest_stores_event_and_is_pollable(client):
    payload = {
        "hook_event_name": "PreToolUse",
        "session_id": "sess-T",
        "tool_name": "Read",
        "tool_input": {"file_path": "/tmp/x.txt"},
    }
    r = client.post("/api/hook", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert isinstance(body["id"], int)

    r2 = client.get("/api/events?limit=10")
    events = r2.json()["events"]
    assert len(events) == 1
    assert events[0]["hook_event_name"] == "PreToolUse"
    assert events[0]["tool_name"] == "Read"
    assert events[0]["id"] == body["id"]


def test_hook_ingest_rejects_invalid_json(client):
    r = client.post("/api/hook", content=b"{not-json", headers={"Content-Type": "application/json"})
    assert r.status_code == 400


def test_hook_ingest_redacts_secrets_at_ingest(client):
    raw = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {
            "env": {"ANTHROPIC_API_KEY": "sk-ant-fake-leak-value-1234567890"},
        },
    }
    client.post("/api/hook", json=raw)
    events = client.get("/api/events?limit=1").json()["events"]
    assert events[0]["tool_input"]["env"]["ANTHROPIC_API_KEY"] == "<REDACTED>"


# ---------------------------------------------------------------------------
# Chat + IPC round-trip (B4) — the load-bearing side-effect test
# ---------------------------------------------------------------------------

def test_chat_post_writes_spec_to_ipc_inbox_per_contract(client, dirs):
    """POST /api/chat must land a spec .md + .ready marker in the
    IPC inbox per WA1 contract v1. Asserts the side effect (file on
    disk in the right place), not just the API ack.
    """
    _, ipc_root = dirs
    ipc = IPCLayout(ipc_root)

    r = client.post("/api/chat", json={"text": "hello from the dashboard"})
    assert r.status_code == 200
    spec_id = r.json()["spec_id"]
    assert spec_id.startswith("chat_")

    # The spec .md + .ready marker exist per the contract.
    assert (ipc.inbox / f"{spec_id}.md").is_file()
    assert (ipc.inbox / f"{spec_id}{READY_SUFFIX}").is_file()
    body = (ipc.inbox / f"{spec_id}.md").read_text(encoding="utf-8")
    assert "hello from the dashboard" in body

    # The IPC layer's list_ready_specs sees it (proves the marker
    # convention works end-to-end, not just file presence).
    assert spec_id in ipc.list_ready_specs()


def test_chat_rejects_empty_text(client):
    r = client.post("/api/chat", json={"text": ""})
    assert r.status_code == 400


def test_chat_outbox_round_trip_with_stub_responder(client, dirs):
    """End-to-end: dashboard writes chat → stub_responder drains +
    writes a reply → dashboard sees it via /api/outbox.
    """
    _, ipc_root = dirs
    ipc = IPCLayout(ipc_root)

    r = client.post("/api/chat", json={"text": "ping the responder"})
    assert r.status_code == 200
    spec_id = r.json()["spec_id"]

    n = drain_once(ipc)
    assert n == 1

    # Outbox now has a .closeout.done marker for our spec_id.
    assert spec_id in ipc.list_completed_closeouts()

    r2 = client.get("/api/outbox")
    replies = r2.json()["replies"]
    matching = [m for m in replies if m["spec_id"] == spec_id]
    assert len(matching) == 1
    assert "Stub-responder ack" in matching[0]["body"]
    assert "ping the responder" in matching[0]["body"]


# ---------------------------------------------------------------------------
# Quota panel (B5)
# ---------------------------------------------------------------------------

def test_quota_endpoint_initial_state(client):
    r = client.get("/api/quota")
    assert r.status_code == 200
    data = r.json()
    assert data["throttled"] is False
    assert data["sessions"] == {}


def test_quota_observation_records_session(client):
    obs = {
        "session_id": "sess-Q",
        "model": "claude-opus-4-7",
        "usage": {
            "input_tokens": 50,
            "output_tokens": 200,
            "cache_read_input_tokens": 43_639,
            "cache_creation_input_tokens": 478,
        },
        "total_cost_usd": 0.1234,
        "result": "all good",
    }
    r = client.post("/api/quota/observation", json=obs)
    assert r.status_code == 200
    snap = client.get("/api/quota").json()
    assert "sess-Q" in snap["sessions"]
    assert snap["sessions"]["sess-Q"]["model"] == "claude-opus-4-7"
    assert snap["sessions"]["sess-Q"]["rounds"] == 1
    assert snap["sessions"]["sess-Q"]["cache_read_input_tokens"] == 43_639


def test_quota_observation_detects_throttle_string(client):
    obs = {
        "session_id": "sess-R",
        "model": "claude-opus-4-7",
        "result": "You're out of extra usage · resets 11:15am (America/New_York)",
        "exit_code": 1,
    }
    r = client.post("/api/quota/observation", json=obs)
    assert r.status_code == 200
    assert r.json()["diff"]["throttled"] is True

    snap = client.get("/api/quota").json()
    assert snap["throttled"] is True
    assert "11:15" in snap["reset_at_text"]
    assert "out of extra usage" in snap["throttle_message"]


def test_quota_clear_resets_flag(client):
    client.post("/api/quota/observation", json={
        "session_id": "s",
        "result": "out of extra usage",
    })
    assert client.get("/api/quota").json()["throttled"] is True

    client.post("/api/quota/clear")
    snap = client.get("/api/quota").json()
    assert snap["throttled"] is False
    assert snap["throttle_message"] == ""
