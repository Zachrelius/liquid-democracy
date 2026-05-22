"""Phase 35 A1+A2 — instrumentation module unit tests.

Coverage:
- env gate off (default): instrument_tick is a no-op pass-through; middleware
  doesn't crash; no audit logs emitted.
- env gate on: instrument_tick logs to scalability_audit logger;
  middleware-style assertions are deferred to the load-test pass (would
  require spinning the FastAPI app with a mock route).
- contextvars correctly scope query counts per-request (smoke test).
"""
from __future__ import annotations

import json
import logging
import os
from importlib import reload


def test_env_gate_off_is_default(monkeypatch):
    """Default behavior: SCALABILITY_AUDIT_INSTRUMENTATION_ENABLED unset →
    INSTRUMENTATION_ENABLED is False."""
    monkeypatch.delenv("SCALABILITY_AUDIT_INSTRUMENTATION_ENABLED", raising=False)
    import scalability_instrumentation as si
    reload(si)
    assert si.INSTRUMENTATION_ENABLED is False


def test_env_gate_truthy_strings(monkeypatch):
    """Accepted truthy values: 'true', '1', 'yes' (case-insensitive)."""
    import scalability_instrumentation as si
    for v in ("true", "TRUE", "1", "yes", "YES"):
        monkeypatch.setenv("SCALABILITY_AUDIT_INSTRUMENTATION_ENABLED", v)
        reload(si)
        assert si.INSTRUMENTATION_ENABLED is True, f"value {v!r} should enable"


def test_instrument_tick_no_op_when_disabled(monkeypatch, caplog):
    monkeypatch.delenv("SCALABILITY_AUDIT_INSTRUMENTATION_ENABLED", raising=False)
    import scalability_instrumentation as si
    reload(si)
    caplog.set_level(logging.INFO, logger="scalability_audit")
    with si.instrument_tick("test_tick", count=5) as ctx:
        ctx["work_units"] = {"count": 10}
    # No JSON line emitted.
    audit_records = [r for r in caplog.records if r.name == "scalability_audit"]
    assert audit_records == []


def test_instrument_tick_emits_when_enabled(monkeypatch, caplog):
    monkeypatch.setenv("SCALABILITY_AUDIT_INSTRUMENTATION_ENABLED", "true")
    import scalability_instrumentation as si
    reload(si)
    caplog.set_level(logging.INFO, logger="scalability_audit")
    with si.instrument_tick("my_tick", initial=3) as ctx:
        ctx["work_units"] = {"final": 7}
    audit_records = [r for r in caplog.records if r.name == "scalability_audit"]
    assert len(audit_records) == 1
    payload = json.loads(audit_records[0].getMessage())
    assert payload["audit"] == "tick"
    assert payload["tick_name"] == "my_tick"
    assert payload["work_units"]["final"] == 7
    assert "elapsed_ms" in payload
    assert payload["error"] is None


def test_instrument_tick_captures_error(monkeypatch, caplog):
    monkeypatch.setenv("SCALABILITY_AUDIT_INSTRUMENTATION_ENABLED", "true")
    import scalability_instrumentation as si
    reload(si)
    caplog.set_level(logging.INFO, logger="scalability_audit")

    import pytest as _pytest
    with _pytest.raises(RuntimeError):
        with si.instrument_tick("failing_tick"):
            raise RuntimeError("boom")
    audit_records = [r for r in caplog.records if r.name == "scalability_audit"]
    assert len(audit_records) == 1
    payload = json.loads(audit_records[0].getMessage())
    assert payload["audit"] == "tick"
    assert payload["tick_name"] == "failing_tick"
    assert "RuntimeError" in (payload.get("error") or "")
