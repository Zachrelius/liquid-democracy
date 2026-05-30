"""Event normalization + redaction tests (WA3 B1)."""
from __future__ import annotations

from dashboard.events import normalize_event


def test_normalize_pretooluse_minimal():
    raw = {
        "hook_event_name": "PreToolUse",
        "session_id": "sess-1",
        "tool_name": "Read",
        "tool_input": {"file_path": "/tmp/x.txt"},
        "cwd": "/tmp",
    }
    ev = normalize_event(raw, event_id=1, raw_size_bytes=100)
    assert ev["id"] == 1
    assert ev["hook_event_name"] == "PreToolUse"
    assert ev["tool_name"] == "Read"
    assert ev["tool_input"] == {"file_path": "/tmp/x.txt"}
    assert ev["tool_response_excerpt"] is None
    assert ev["ts"].endswith("Z")
    assert ev["raw_size_bytes"] == 100


def test_normalize_posttooluse_extracts_response_excerpt():
    raw = {
        "hook_event_name": "PostToolUse",
        "session_id": "sess-1",
        "tool_name": "Read",
        "tool_input": {"file_path": "/tmp/x.txt"},
        "tool_response": {
            "type": "text",
            "file": {"filePath": "/tmp/x.txt", "content": "hello there\n"},
        },
        "duration_ms": 42,
    }
    ev = normalize_event(raw, event_id=2, raw_size_bytes=500)
    assert ev["duration_ms"] == 42
    assert ev["tool_response_excerpt"] is not None
    assert "hello there" in ev["tool_response_excerpt"]


def test_redacts_anthropic_api_key():
    raw = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {
            "command": "curl https://api.example.com",
            "env": {"ANTHROPIC_API_KEY": "sk-ant-secret123abc"},
        },
    }
    ev = normalize_event(raw, event_id=3, raw_size_bytes=200)
    redacted_env = ev["tool_input"]["env"]
    # The key name is in _SECRET_KEY_NAMES (lowercased) — value should be wholly redacted.
    assert redacted_env["ANTHROPIC_API_KEY"] == "<REDACTED>"


def test_redacts_bearer_token_in_command_string():
    raw = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {
            "command": "curl -H 'Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig' https://x"
        },
    }
    ev = normalize_event(raw, event_id=4, raw_size_bytes=300)
    cmd = ev["tool_input"]["command"]
    assert "REDACTED" in cmd
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in cmd


def test_redacts_long_hex_string():
    """Key 'secret' isn't in the _SECRET_KEY_NAMES tuple (only
    'secret_key' is). But the long-hex regex on the VALUE side still
    redacts it after the first 6 chars."""
    raw = {
        "hook_event_name": "PreToolUse",
        "tool_input": {"description": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"},
    }
    ev = normalize_event(raw, event_id=5, raw_size_bytes=100)
    val = ev["tool_input"]["description"]
    assert val.startswith("deadbe") and "REDACTED" in val
    assert "deadbeefdeadbeefdeadbeefdeadbeef" not in val


def test_secret_key_named_value_fully_redacted():
    """When the KEY name matches _SECRET_KEY_NAMES, the whole value
    is replaced regardless of contents — even a non-secret-looking
    value."""
    raw = {
        "hook_event_name": "PreToolUse",
        "tool_input": {"secret_key": "ABC"},
    }
    ev = normalize_event(raw, event_id=5, raw_size_bytes=100)
    assert ev["tool_input"]["secret_key"] == "<REDACTED>"


def test_long_string_value_is_truncated():
    big = "x" * 6000
    raw = {
        "hook_event_name": "PreToolUse",
        "tool_input": {"description": big},
    }
    ev = normalize_event(raw, event_id=6, raw_size_bytes=10000)
    assert ev["tool_input"]["description"].endswith("...<TRUNCATED>")
    assert len(ev["tool_input"]["description"]) < 5000


def test_normalize_handles_missing_fields():
    """Truly minimal event (eg SessionStart with just core fields)
    must not crash."""
    raw = {"hook_event_name": "SessionStart", "session_id": "s"}
    ev = normalize_event(raw, event_id=7, raw_size_bytes=50)
    assert ev["hook_event_name"] == "SessionStart"
    assert ev["tool_name"] is None
    assert ev["tool_input"] is None
    assert ev["tool_response_excerpt"] is None
    assert ev["duration_ms"] is None
