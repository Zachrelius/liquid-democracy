"""Phase 97 — production monitoring and actionable-alert regressions."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import auth as auth_utils
from database import get_db
import digest_scheduler
from main import app
import models
import ops_monitoring as monitor
from settings import settings


@pytest.fixture(autouse=True)
def clean_monitor_runtime(monkeypatch):
    monitor.reset_runtime_state_for_tests()
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(monitor, "_STARTED_AT", now)
    monkeypatch.setattr(digest_scheduler, "_LAST_SUCCESSFUL_TICK_AT", now)
    monkeypatch.setattr(digest_scheduler, "_TICKS_SINCE_LAST_SUCCESS", 0)
    yield
    monitor.reset_runtime_state_for_tests()


@pytest.fixture
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _user(db, name: str, *, admin: bool = False, verified: bool = True, active: bool = True):
    user = models.User(
        username=name,
        display_name=name.title(),
        password_hash=auth_utils.hash_password("test-password"),
        email=f"{name}@pilot.org",
        email_verified=verified,
        is_admin=admin,
        is_active=active,
    )
    db.add(user)
    db.flush()
    return user


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _seed_healthy_workers(db, now: datetime) -> None:
    digest_scheduler._LAST_SUCCESSFUL_TICK_AT = now
    digest_scheduler._TICKS_SINCE_LAST_SUCCESS = 0
    db.add(models.PlatformSetting(
        key="sm_worker_heartbeat",
        value={
            "last_successful_tick_at": now.isoformat(),
            "ticks_since_last_success": 0,
        },
    ))
    db.flush()


def _snapshot(status: str, issues: list[dict] | None = None) -> dict:
    return {
        "status": status,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "components": {},
        "issues": issues or [],
    }


def test_sanitize_path_removes_ids_tokens_and_query_strings():
    raw = "/api/orgs/123/proposals/550e8400-e29b-41d4-a716-446655440000/" + "a" * 60 + "?secret=yes"
    clean = monitor.sanitize_path(raw)
    assert clean == "/api/orgs/:id/proposals/:id/:token"
    assert "secret" not in clean
    assert "550e8400" not in clean
    assert monitor.sanitize_path("/api/orgs/private-board/proposals") == "/api/orgs/:id/proposals"


def test_repeated_5xx_threshold_is_bounded_and_health_is_excluded():
    now = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
    monitor.record_http_failure(
        method="GET", path="/api/health/monitor", request_id="health", status_code=503, now=now,
    )
    monitor.record_http_failure(
        method="GET", path="/api/proposals/1", request_id="old", status_code=500,
        now=now - timedelta(minutes=16),
    )
    for index in range(3):
        monitor.record_http_failure(
            method="POST", path=f"/api/proposals/{index}", request_id=f"req-{index}",
            status_code=500, now=now,
        )
    state = monitor._request_component(now)
    assert state["status"] == "error"
    assert state["count_15m"] == 3
    assert {row["request_id"] for row in state["samples"]} == {"req-0", "req-1", "req-2"}
    assert all(row["path"] == "/api/proposals/:id" for row in state["samples"])


def test_email_failure_streak_requires_three_and_success_recovers():
    monitor.record_email_result(False)
    monitor.record_email_result(False)
    assert monitor._email_component()["status"] == "ok"
    monitor.record_email_result(False)
    assert monitor._email_component()["status"] == "error"
    monitor.record_email_result(True)
    state = monitor._email_component()
    assert state["status"] == "ok"
    assert state["consecutive_failures"] == 0
    assert state["last_success_at"] is not None


def test_capacity_thresholds_distinguish_database_and_upload_boundaries():
    db_warning = monitor._capacity_component(
        used_bytes=81, capacity_bytes=100, guidance="db", warning_percent=80, error_percent=90,
    )
    db_error = monitor._capacity_component(
        used_bytes=91, capacity_bytes=100, guidance="db", warning_percent=80, error_percent=90,
    )
    upload_ok = monitor._capacity_component(used_bytes=84, capacity_bytes=100, guidance="uploads")
    assert db_warning["status"] == "warning"
    assert db_error["status"] == "error"
    assert upload_ok["status"] == "ok"


def test_healthy_snapshot_is_public_safe_and_ok(db):
    now = datetime.now(timezone.utc)
    _user(db, "opsadmin", admin=True)
    _seed_healthy_workers(db, now)
    snapshot = monitor.build_snapshot(db, now=now, upload_dir=Path("local-test-uploads"))
    assert snapshot["status"] == "ok"
    assert snapshot["issues"] == []
    assert snapshot["components"]["database"]["status"] == "ok"
    assert snapshot["components"]["database_capacity"]["status"] == "not_applicable"
    assert snapshot["components"]["upload_capacity"]["status"] == "not_applicable"
    serialized = str(snapshot).lower()
    assert "opsadmin@pilot.org" not in serialized
    assert "database_url" not in serialized
    assert "password" not in serialized


def test_snapshot_flags_stale_workers_and_missing_alert_recipient(db, monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(monitor, "_STARTED_AT", now - timedelta(hours=3))
    digest_scheduler._LAST_SUCCESSFUL_TICK_AT = now - timedelta(hours=3)
    digest_scheduler._TICKS_SINCE_LAST_SUCCESS = 2
    db.add(models.PlatformSetting(
        key="sm_worker_heartbeat",
        value={
            "last_successful_tick_at": (now - timedelta(hours=1)).isoformat(),
            "ticks_since_last_success": 3,
        },
    ))
    db.flush()
    snapshot = monitor.build_snapshot(db, now=now)
    assert snapshot["status"] == "error"
    assert snapshot["components"]["digest_scheduler"]["status"] == "error"
    assert snapshot["components"]["decision_worker"]["status"] == "error"
    assert snapshot["components"]["alert_delivery"]["status"] == "error"


def test_disabled_workers_are_not_false_incidents(db, monkeypatch):
    now = datetime.now(timezone.utc)
    _user(db, "admin-disabled-workers", admin=True)
    monkeypatch.setenv("DISABLE_DIGEST_SCHEDULER", "true")
    monkeypatch.setattr(settings, "sustained_majority_worker_disable", True)
    monkeypatch.setattr(monitor, "_STARTED_AT", now - timedelta(days=1))
    # Keep this worker-state regression independent of Railway's production
    # /data/uploads mount.  GitHub's Linux runner intentionally has no such
    # directory, and storage-mount behavior is covered separately.
    snapshot = monitor.build_snapshot(
        db, now=now, upload_dir=Path("local-test-uploads")
    )
    assert snapshot["components"]["digest_scheduler"]["status"] == "disabled"
    assert snapshot["components"]["decision_worker"]["status"] == "disabled"
    assert snapshot["status"] == "ok"


def test_public_monitor_endpoint_returns_200_when_healthy(client, db):
    now = datetime.now(timezone.utc)
    _user(db, "endpointadmin", admin=True)
    _seed_healthy_workers(db, now)
    response = client.get("/api/health/monitor")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ok"


def test_public_monitor_endpoint_returns_503_without_leaking_on_error(client, db, monkeypatch):
    now = datetime.now(timezone.utc)
    _user(db, "staleadmin", admin=True)
    monkeypatch.setattr(monitor, "_STARTED_AT", now - timedelta(hours=4))
    digest_scheduler._LAST_SUCCESSFUL_TICK_AT = now - timedelta(hours=4)
    digest_scheduler._TICKS_SINCE_LAST_SUCCESS = 3
    response = client.get("/api/health/monitor")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "error"
    serialized = response.text.lower()
    assert "staleadmin@pilot.org" not in serialized
    assert "traceback" not in serialized
    assert "secret" not in serialized


def test_active_admin_recipients_excludes_unverified_inactive_and_non_admin(db):
    _user(db, "valid", admin=True)
    _user(db, "unverified", admin=True, verified=False)
    _user(db, "inactive", admin=True, active=False)
    _user(db, "ordinary", admin=False)
    placeholder = _user(db, "placeholder", admin=True)
    placeholder.email = "legacy-admin@demo.example"
    assert monitor.active_admin_recipients(db) == ["valid@pilot.org"]


def test_explicit_alert_email_override_is_supported(db, monkeypatch):
    monkeypatch.setattr(settings, "ops_alert_email", " Owner@LiquidDemocracy.us ")
    assert monitor.active_admin_recipients(db) == ["owner@liquiddemocracy.us"]


@pytest.mark.asyncio
async def test_monitor_once_deduplicates_then_sends_recovery(db, monkeypatch):
    _user(db, "dedupeadmin", admin=True)
    incident = _snapshot("error", [{
        "component": "database",
        "severity": "error",
        "guidance": "Check Postgres.",
    }])
    recovered = _snapshot("ok")
    snapshots = [incident, incident, recovered]
    sent: list[str] = []

    monkeypatch.setattr(monitor, "build_snapshot", lambda *_args, **_kwargs: snapshots.pop(0))

    async def fake_send(_db, subject, _body):
        sent.append(subject)
        return True

    monkeypatch.setattr(monitor, "_send_to_admins", fake_send)
    now = datetime.now(timezone.utc)
    await monitor.monitor_once(db, now=now)
    await monitor.monitor_once(db, now=now + timedelta(minutes=5))
    await monitor.monitor_once(db, now=now + timedelta(minutes=10))
    assert sent == [
        "[Liquid Democracy] Production monitoring alert",
        "[Liquid Democracy] Production recovered",
    ]
    state = db.get(models.PlatformSetting, monitor.STATE_KEY).value
    assert state["active_fingerprint"] is None
    assert state["last_delivery_succeeded"] is True


@pytest.mark.asyncio
async def test_common_email_boundary_records_transport_outcomes(monkeypatch):
    import email_service

    monkeypatch.setattr(settings, "resend_api_key", "test-key")

    async def failed(*_args, **_kwargs):
        return False

    monkeypatch.setattr(email_service, "_send_via_resend", failed)
    for _ in range(3):
        assert await email_service.send_email("ops@example.test", "subject", "body") is False
    assert monitor._email_component()["status"] == "error"

    async def succeeded(*_args, **_kwargs):
        return True

    monkeypatch.setattr(email_service, "_send_via_resend", succeeded)
    assert await email_service.send_email("ops@example.test", "subject", "body") is True
    assert monitor._email_component()["status"] == "ok"


def test_monitoring_test_alert_is_admin_only_and_audited(client, db, monkeypatch):
    admin = _user(db, "testalertadmin", admin=True)
    ordinary = _user(db, "testalertmember", admin=False)

    async def delivered(_db):
        return True, 1

    monkeypatch.setattr(monitor, "send_test_alert", delivered)
    denied = client.post("/api/admin/monitoring/test-alert", headers=_auth(ordinary))
    assert denied.status_code == 403
    response = client.post("/api/admin/monitoring/test-alert", headers=_auth(admin))
    assert response.status_code == 200, response.text
    assert response.json() == {"delivered": True, "recipient_count": 1}
    audit = db.query(models.AuditLog).filter(
        models.AuditLog.action == "ops.monitoring_test_alert",
    ).one()
    assert audit.actor_id == admin.id
    assert audit.details == {"recipient_count": 1, "delivered": True}


def test_external_monitor_workflow_contract():
    workflow = (
        Path(__file__).resolve().parents[2]
        / ".github" / "workflows" / "production-monitor.yml"
    ).read_text(encoding="utf-8")
    assert 'cron: "7,37 * * * *"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "issues: write" in workflow
    assert "contents: read" in workflow
    assert "1 2 3" in workflow
    assert "production-monitor" in workflow
    assert "api/health/monitor" in workflow
    assert "state: 'closed'" in workflow
    assert "Mark an unhealthy probe failed" in workflow
