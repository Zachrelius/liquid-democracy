"""Schema round-trip + validation tests (WA1 B5).

The schema is the load-bearing contract — every consumer (checkpoint,
bootstrap, passdown, IPC) reads via it. These tests pin the round-trip
+ version guard behaviors so a future schema change can't silently
regress them.
"""
from __future__ import annotations

import json

import pytest

from planner_state.schema import (
    Decision,
    LoopState,
    PlannerState,
    Project,
    SCHEMA_VERSION,
    SchemaVersionMismatch,
    now_iso,
    validate_schema,
)


def _sample_state() -> PlannerState:
    return PlannerState(
        schema_version=SCHEMA_VERSION,
        project=Project(
            name="Liquid Democracy",
            repo_root="/repo/path",
            prod_url="https://example.test",
            current_pointer="Phase 42 SHIPPED — master 89dbc0c",
        ),
        loop_state=LoopState(
            current_pass="WA1 — State & IPC Foundation",
            current_pass_status="in_progress",
            pending=["WA2 spike", "Phase 43 frontend"],
            blocked=[{"item": "Cowork QA probe", "reason": "Z input needed"}],
            last_code_activity={
                "pass": "Phase 42",
                "timestamp": "2026-05-29",
                "summary": "Spike returned GO",
                "result": "shipped",
            },
        ),
        decisions=[
            Decision(
                date="2026-05-30T12:00:00Z",
                topic="Auth model",
                decision="Shell out to claude -p; no Agent SDK",
                rationale="Max OAuth incompatible with Agent SDK",
            ),
            Decision(
                date="2026-05-30T12:15:00Z",
                topic="QA browser",
                decision="Playwright MCP for autonomous QA",
                rationale="Claude-in-Chrome not headless-friendly",
            ),
        ],
        working_context_digest="Phase 42 returned GO. WA1 is the bedrock pass.",
    )


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------

def test_round_trip_preserves_all_fields():
    original = _sample_state()
    raw = original.to_json()
    loaded = PlannerState.from_json(raw)

    assert loaded.schema_version == original.schema_version
    assert loaded.project.name == original.project.name
    assert loaded.project.repo_root == original.project.repo_root
    assert loaded.project.prod_url == original.project.prod_url
    assert loaded.project.current_pointer == original.project.current_pointer

    assert loaded.loop_state.current_pass == original.loop_state.current_pass
    assert loaded.loop_state.current_pass_status == original.loop_state.current_pass_status
    assert loaded.loop_state.pending == original.loop_state.pending
    assert loaded.loop_state.blocked == original.loop_state.blocked
    assert loaded.loop_state.last_code_activity == original.loop_state.last_code_activity

    assert len(loaded.decisions) == len(original.decisions)
    for i, d in enumerate(loaded.decisions):
        assert d.date == original.decisions[i].date
        assert d.topic == original.decisions[i].topic
        assert d.decision == original.decisions[i].decision
        assert d.rationale == original.decisions[i].rationale

    assert loaded.working_context_digest == original.working_context_digest


def test_round_trip_via_dict_equivalent_to_via_json():
    original = _sample_state()
    via_json = PlannerState.from_json(original.to_json())
    via_dict = PlannerState.from_dict(original.to_dict())
    assert via_json.to_dict() == via_dict.to_dict()


def test_empty_state_constructs_with_just_project_name():
    s = PlannerState.empty("Test Project")
    assert s.schema_version == SCHEMA_VERSION
    assert s.project.name == "Test Project"
    assert s.loop_state.current_pass is None
    assert s.loop_state.current_pass_status == "idle"
    assert s.decisions == []
    assert s.working_context_digest == ""


# ---------------------------------------------------------------------------
# Validation + version guard
# ---------------------------------------------------------------------------

def test_validate_schema_rejects_non_dict():
    with pytest.raises(ValueError, match="JSON object at the top level"):
        validate_schema([1, 2, 3])  # type: ignore[arg-type]


def test_validate_schema_rejects_missing_version():
    with pytest.raises(ValueError, match="missing the required 'schema_version'"):
        validate_schema({"project": {"name": "X"}})


def test_validate_schema_rejects_wrong_version_type():
    with pytest.raises(ValueError, match="schema_version must be an int"):
        validate_schema({"schema_version": "1"})


def test_validate_schema_raises_mismatch_for_unknown_version():
    with pytest.raises(SchemaVersionMismatch) as exc_info:
        validate_schema({"schema_version": SCHEMA_VERSION + 1})
    assert exc_info.value.on_disk == SCHEMA_VERSION + 1
    assert exc_info.value.supported == SCHEMA_VERSION


def test_validate_schema_accepts_current_version():
    # Should not raise.
    validate_schema({"schema_version": SCHEMA_VERSION})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def test_now_iso_format_is_zulu_seconds():
    s = now_iso()
    # YYYY-MM-DDTHH:MM:SSZ — 20 chars, ends with Z.
    assert len(s) == 20
    assert s.endswith("Z")
    assert s[4] == "-" and s[7] == "-" and s[10] == "T"
    assert s[13] == ":" and s[16] == ":"
