"""Quota detection + per-session telemetry tests (WA3 B5)."""
from __future__ import annotations

from dashboard.quota import (
    QuotaState,
    clear_throttle,
    detect_quota_wall,
    update_from_claude_result,
)


# ---------------------------------------------------------------------------
# Quota-wall detection
# ---------------------------------------------------------------------------

def test_detect_quota_wall_matches_wa2_observed_string():
    """The exact string WA2 P1 captured at R5."""
    s = "You're out of extra usage · resets 12:30pm (America/Port-au-Prince)"
    throttled, reset = detect_quota_wall(s)
    assert throttled is True
    assert "12:30" in reset
    assert "America/Port-au-Prince" in reset


def test_detect_quota_wall_other_phrasings():
    """The model occasionally varies wording; the loose regex covers
    common variants."""
    cases = [
        "You're out of extra credit; resets at 9:00am",
        "Out of usage. Resets 5:45 pm.",
        "Out of capacity for now",   # no reset clause — still throttled
    ]
    for s in cases:
        throttled, _ = detect_quota_wall(s)
        assert throttled, f"Expected throttle hit for {s!r}"


def test_detect_quota_wall_returns_false_for_unrelated_text():
    assert detect_quota_wall("All checks PASS.") == (False, "")
    assert detect_quota_wall("") == (False, "")
    assert detect_quota_wall("Phase 42 SHIPPED 2026-05-29.") == (False, "")


# ---------------------------------------------------------------------------
# update_from_claude_result
# ---------------------------------------------------------------------------

def test_update_session_telemetry_first_round():
    state = QuotaState()
    result = {
        "session_id": "sess-A",
        "model": "claude-opus-4-7",
        "duration_ms": 12345,
        "total_cost_usd": 0.0427,
        "usage": {
            "input_tokens": 42,
            "output_tokens": 1000,
            "cache_read_input_tokens": 43_639,
            "cache_creation_input_tokens": 478,
        },
        "result": "TRACKER: WA1_status=shipped, WA2_status=in_progress",
    }
    diff = update_from_claude_result(state, result)
    assert diff["throttled"] is False
    assert diff["session_id"] == "sess-A"
    snap = state.snapshot()
    assert "sess-A" in snap["sessions"]
    sess = snap["sessions"]["sess-A"]
    assert sess["model"] == "claude-opus-4-7"
    assert sess["rounds"] == 1
    assert sess["input_tokens"] == 42
    assert sess["output_tokens"] == 1000
    assert sess["cache_read_input_tokens"] == 43_639
    assert sess["total_cost_usd_telemetry"] == 0.0427


def test_session_accumulates_across_rounds():
    state = QuotaState()
    base = {"session_id": "sess-B", "model": "m"}
    for r in range(3):
        result = {
            **base,
            "usage": {"input_tokens": 1, "output_tokens": 100,
                      "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 50},
            "total_cost_usd": 0.10,
        }
        update_from_claude_result(state, result)
    snap = state.snapshot()["sessions"]["sess-B"]
    assert snap["rounds"] == 3
    assert snap["input_tokens"] == 3
    assert snap["output_tokens"] == 300
    assert snap["cache_read_input_tokens"] == 3000
    assert snap["cache_creation_input_tokens"] == 150
    assert abs(snap["total_cost_usd_telemetry"] - 0.30) < 1e-6


def test_throttled_flag_set_on_quota_wall_result():
    state = QuotaState()
    result = {
        "session_id": "sess-C",
        "model": "m",
        "result": "You're out of extra usage · resets 9:15pm (America/New_York)",
        "exit_code": 1,
    }
    diff = update_from_claude_result(state, result)
    assert diff["throttled"] is True
    assert "9:15" in diff["reset_at_text"]
    snap = state.snapshot()
    assert snap["throttled"] is True
    assert snap["reset_at_text"]
    assert snap["throttle_message"]


def test_quota_wall_detection_reads_payload_nested():
    """Some callers wrap the claude -p result under a 'payload' key
    (eg the WA2 P1 harness does). The detector should look there too.
    """
    state = QuotaState()
    result = {
        "exit_code": 1,
        "payload": {
            "session_id": "sess-D",
            "result": "out of extra usage; resets 6:00am",
            "model": "m",
        },
    }
    diff = update_from_claude_result(state, result)
    assert diff["throttled"] is True


def test_clear_throttle_resets_flag():
    state = QuotaState()
    state.throttled = True
    state.throttle_message = "x"
    state.reset_at_text = "y"
    clear_throttle(state)
    assert state.throttled is False
    assert state.throttle_message == ""
    assert state.reset_at_text == ""


def test_snapshot_caps_sessions_at_16():
    state = QuotaState()
    for i in range(25):
        update_from_claude_result(state, {
            "session_id": f"sess-{i:02d}",
            "model": "m",
            "usage": {"input_tokens": 1, "output_tokens": 1,
                      "cache_read_input_tokens": 1, "cache_creation_input_tokens": 1},
        })
    snap = state.snapshot()
    assert len(snap["sessions"]) == 16
