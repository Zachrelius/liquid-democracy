"""Independent Phase 98 monitoring and process-boundary regressions.

The backup pipeline has detailed unit coverage in its own test module.  This
file protects the cross-cutting operational contracts inherited from Phase 97:
the public monitor must distrust persisted JSON, and container/process wiring
must keep backup failure isolated from the web service.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess

import digest_scheduler
import models
import offsite_backup as backup
import ops_monitoring as monitor
import pytest
from scripts import restore_offsite_backup as restore_tool
from settings import settings


REPO_ROOT = Path(__file__).resolve().parents[2]
START_SH = REPO_ROOT / "backend" / "start.sh"
DOCKERFILE = REPO_ROOT / "backend" / "Dockerfile"
PUBLIC_FAILURE_CATEGORIES = {
    "archive_failure",
    "concurrent_run",
    "database_metadata_failure",
    "encryption_failure",
    "insufficient_space",
    "interrupted",
    "invalid_configuration",
    "invalid_recipient",
    "lock_unavailable",
    "object_store_unavailable",
    "subprocess_failure",
    "toolchain_incompatible",
    "toolchain_unavailable",
    "unexpected_failure",
    "unknown_failure",
    "unsafe_upload_tree",
    "upload_failure",
    "upload_tree_changed",
    "uploads_unavailable",
    "verification_failure",
    "wrong_instance",
}


def _put_backup_state(db, value: dict) -> None:
    db.add(models.PlatformSetting(key="offsite_backup_state_v1", value=value))
    db.flush()


def test_offsite_monitor_status_matrix(db, monkeypatch):
    now = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(settings, "offsite_backup_stale_after_seconds", 36 * 60 * 60)

    monkeypatch.setattr(settings, "offsite_backup_enabled", False)
    assert monitor._offsite_backup_component(db, now)["status"] == "disabled"

    monkeypatch.setattr(settings, "offsite_backup_enabled", True)
    monkeypatch.setattr(monitor, "_STARTED_AT", now - timedelta(minutes=5))
    assert monitor._offsite_backup_component(db, now)["status"] == "warning"

    monkeypatch.setattr(monitor, "_STARTED_AT", now - timedelta(hours=2))
    assert monitor._offsite_backup_component(db, now)["status"] == "error"

    _put_backup_state(db, {
        "last_success_at": (now - timedelta(hours=2)).isoformat(),
        "consecutive_failures": 0,
        "last_encrypted_size": 100,
        "last_retention_classes": ["daily"],
        "last_duration_seconds": 10.5,
    })
    assert monitor._offsite_backup_component(db, now)["status"] == "ok"

    row = db.get(models.PlatformSetting, "offsite_backup_state_v1")
    row.value = {
        **row.value,
        "last_failure_at": (now - timedelta(minutes=1)).isoformat(),
        "consecutive_failures": 1,
        "failure_category": "upload_failure",
    }
    db.flush()
    assert monitor._offsite_backup_component(db, now)["status"] == "error"

    row.value = {
        "last_success_at": (now - timedelta(hours=37)).isoformat(),
        "consecutive_failures": 0,
    }
    db.flush()
    assert monitor._offsite_backup_component(db, now)["status"] == "error"


def test_disabled_offsite_backup_is_not_an_incident(db, monkeypatch):
    now = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    monitor.reset_runtime_state_for_tests()
    monkeypatch.setattr(settings, "offsite_backup_enabled", False)
    monkeypatch.setattr(settings, "ops_alert_email", "ops@example.test")
    monkeypatch.setattr(monitor, "_STARTED_AT", now)
    monkeypatch.setattr(
        digest_scheduler,
        "get_scheduler_state",
        lambda: {"last_successful_tick_at": now, "ticks_since_last_success": 0},
    )
    db.add(models.PlatformSetting(
        key="sm_worker_heartbeat",
        value={"last_successful_tick_at": now.isoformat(), "ticks_since_last_success": 0},
    ))
    db.flush()

    snapshot = monitor.build_snapshot(
        db, now=now, upload_dir=Path("local-test-uploads"),
    )
    assert snapshot["components"]["offsite_backup"]["status"] == "disabled"
    assert not any(
        issue["component"] == "offsite_backup" for issue in snapshot["issues"]
    )
    assert snapshot["status"] == "ok"


def test_offsite_monitor_distrusts_persisted_json_and_never_leaks(db, monkeypatch):
    """Unexpected DB JSON must not become a public payload or a monitor 500."""
    now = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(settings, "offsite_backup_enabled", True)
    monkeypatch.setattr(monitor, "_STARTED_AT", now - timedelta(hours=2))
    secrets = (
        "private-r2-bucket",
        "production/daily/private-object.tar.age",
        "AKIA_TEST_ONLY_SECRET",
        "https://account-id.r2.cloudflarestorage.com",
    )
    _put_backup_state(db, {
        "last_success_at": (now - timedelta(hours=1)).isoformat(),
        "last_failure_at": (now - timedelta(minutes=1)).isoformat(),
        "consecutive_failures": 1,
        "failure_category": secrets[0],
        "last_retention_classes": ["daily", secrets[1]],
        "last_encrypted_size": secrets[2],
        "last_duration_seconds": secrets[3],
        "bucket": secrets[0],
        "object_key": secrets[1],
        "access_key_id": secrets[2],
        "endpoint": secrets[3],
    })

    component = monitor._offsite_backup_component(db, now)
    serialized = json.dumps(component, sort_keys=True)
    assert component["status"] == "error"
    assert all(secret not in serialized for secret in secrets)
    assert component.get("failure_category") in PUBLIC_FAILURE_CATEGORIES | {None}
    assert set(component.get("last_retention_classes") or []) <= {
        "daily", "weekly", "monthly",
    }
    assert component.get("last_encrypted_size") is None or isinstance(
        component["last_encrypted_size"], int,
    )
    assert component.get("last_duration_seconds") is None or isinstance(
        component["last_duration_seconds"], (int, float),
    )

    # A malformed counter is also untrusted input.  It must degrade to a
    # coarse public state instead of making /api/health/monitor itself fail.
    row = db.get(models.PlatformSetting, "offsite_backup_state_v1")
    row.value = {"consecutive_failures": "not-an-integer"}
    db.flush()
    malformed = monitor._offsite_backup_component(db, now)
    assert malformed["status"] in {"warning", "error"}
    assert isinstance(malformed["consecutive_failures"], int)


def test_container_pins_pg18_clients_and_official_age_1_3_1_archive():
    source = DOCKERFILE.read_text(encoding="utf-8")
    assert "postgresql-client-18" in source
    assert "pg_dump --version" in source
    assert "pg_restore --version" in source
    assert "ARG AGE_VERSION=1.3.1" in source
    # Official linux-amd64 archive digest displayed on the upstream v1.3.1
    # release.  A version pin without a digest would still permit replacement
    # of the downloaded executable at the network boundary.
    assert (
        "ARG AGE_LINUX_AMD64_SHA256="
        "bdc69c09cbdd6cf8b1f333d372a1f58247b3a33146406333e30c0f26e8f51377"
    ) in source
    assert "age-v${AGE_VERSION}-linux-amd64.tar.gz" in source
    assert "sha256sum -c -" in source
    assert 'age --version | grep -Eq "v?${AGE_VERSION}"' in source


def test_startup_supervises_backup_as_noncritical_and_forwards_shutdown():
    source = START_SH.read_text(encoding="utf-8")
    assert 'case "${OFFSITE_BACKUP_ENABLED:-false}"' in source
    assert "python -m offsite_backup_worker &" in source
    assert "BACKUP_WORKER_PID=$!" in source
    assert 'kill -TERM "${BACKUP_WORKER_PID}"' in source
    assert 'wait "${BACKUP_WORKER_PID}"' in source

    backup_exit = source.split(
        'if [ -n "${BACKUP_WORKER_PID:-}" ] && ! kill -0 "${BACKUP_WORKER_PID}"',
        1,
    )[1].split("\n    fi", 1)[0]
    assert "_cleanup" not in backup_exit
    assert "application remains available" in backup_exit
    assert 'BACKUP_WORKER_PID=""' in backup_exit

    # Uvicorn and the decision worker remain load-bearing.  Their death must
    # still take the sibling processes down so Railway can replace the service.
    uvicorn_exit = source.split(
        'if ! kill -0 "${UVICORN_PID}"', 1,
    )[1].split("\n    fi", 1)[0]
    decision_exit = source.split(
        'if [ -n "${SM_WORKER_PID:-}" ] && ! kill -0 "${SM_WORKER_PID}"',
        1,
    )[1].split("\n    fi", 1)[0]
    assert "_cleanup 1" in uvicorn_exit
    assert "_cleanup 1" in decision_exit


@pytest.mark.parametrize("target", [
    # DNS names are case-insensitive; casing cannot bypass the production-host
    # rejection while the disposable database-name marker still passes.
    "postgresql://operator:pw@PROD.INTERNAL/phase98_restore_test",
    # Libpq/SQLAlchemy query routing can override the authority host.  The
    # restore target and the target inspected for emptiness must be identical.
    (
        "postgresql://operator:pw@isolated.invalid/phase98_restore_test"
        "?host=prod.internal"
    ),
])
def test_restore_target_rejects_production_host_aliases(target, monkeypatch):
    production = "postgresql://prod:pw@prod.internal/liquid"
    monkeypatch.setenv("OFFSITE_PRODUCTION_DATABASE_HOST", "prod.internal")
    monkeypatch.setenv("OFFSITE_PRODUCTION_DATABASE_NAME", "liquid")
    confirmation = restore_tool.required_confirmation(target)
    with pytest.raises(backup.BackupError) as exc_info:
        restore_tool.validate_target(target, confirmation, production)
    assert getattr(exc_info.value, "category", None) == "unsafe_restore_target"


def test_advisory_lock_releases_and_rejects_overlap():
    class Result:
        def __init__(self, value):
            self.value = value

        def scalar_one(self):
            return self.value

    class FakeDB:
        def __init__(self, acquired):
            self.acquired = acquired
            self.statements = []

        def execute(self, statement, _parameters):
            rendered = str(statement)
            self.statements.append(rendered)
            return Result(self.acquired if "try_advisory" in rendered else True)

    db = FakeDB(True)
    with backup.advisory_lock(db):
        assert any("pg_try_advisory_lock" in item for item in db.statements)
    assert any("pg_advisory_unlock" in item for item in db.statements)

    with pytest.raises(backup.BackupError) as exc_info:
        with backup.advisory_lock(FakeDB(False)):
            raise AssertionError("contended lock must not enter the protected block")
    assert exc_info.value.category == "concurrent_run"


def test_shutdown_interrupts_active_child_and_subprocess_errors_are_sanitized(monkeypatch):
    class ActiveChild:
        terminated = False

        def terminate(self):
            self.terminated = True

    child = ActiveChild()
    backup.reset_interruption_for_tests()
    with backup._CHILD_LOCK:
        backup._ACTIVE_CHILDREN.add(child)
    try:
        backup.request_shutdown(15, None)
        assert child.terminated is True
        with pytest.raises(backup.BackupInterrupted):
            backup._safe_child(["pg_dump", "--version"])
    finally:
        with backup._CHILD_LOCK:
            backup._ACTIVE_CHILDREN.discard(child)
        backup.reset_interruption_for_tests()

    class FailedProcess:
        returncode = 2

        def communicate(self):
            return b"", b"DATABASE_URL=postgresql://user:super-secret@prod/db"

    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: FailedProcess())
    with pytest.raises(backup.BackupError) as exc_info:
        backup._safe_child(["pg_dump", "--version"])
    assert exc_info.value.category == "subprocess_failure"
    assert "super-secret" not in str(exc_info.value)


def test_preflight_checks_object_store_without_network_write(tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    candidate = backup.BackupConfig(
        enabled=False,
        time_utc="11:00",
        s3_endpoint="https://account.r2.cloudflarestorage.com",
        s3_region="auto",
        bucket="private-backups",
        prefix="production",
        access_key_id="synthetic-access-key",
        secret_access_key="synthetic-secret-value",
        age_recipient="age1" + "q" * 58,
        stale_after_seconds=129600,
        instance_selector="",
        database_url="postgresql://synthetic:password@db.internal/liquid",
        uploads_root=uploads,
        temporary_root=None,
    )

    @contextmanager
    def fake_lock(_db):
        yield

    monkeypatch.setattr(backup, "advisory_lock", fake_lock)
    monkeypatch.setattr(backup, "tool_versions", lambda: {
        "pg_dump": "pg_dump (PostgreSQL) 18.1",
        "pg_restore": "pg_restore (PostgreSQL) 18.1",
        "age": "v1.3.1",
    })
    monkeypatch.setattr(backup, "database_metadata", lambda _db: {
        "server_version": "18.1",
        "database_name": "liquid",
        "alembic_current": "head123",
        "alembic_head": "head123",
        "representative_row_counts": {},
        "database_size_bytes": 1,
    })
    monkeypatch.setattr(backup, "_recipient_preflight", lambda *_args: None)

    class HeadOnlyClient:
        head_calls = 0

        def head_bucket(self, **_kwargs):
            self.head_calls += 1

        def put_object(self, **_kwargs):
            raise AssertionError("preflight must never write an object")

    client = HeadOnlyClient()
    result = backup.preflight(candidate, db=object(), client=client)
    assert result["ok"] is True
    assert client.head_calls == 1


def test_successful_age_exit_without_ciphertext_is_encryption_failure(tmp_path, monkeypatch):
    bundle = tmp_path / "backup.tar"
    bundle.write_bytes(b"synthetic bundle")
    ciphertext = tmp_path / "backup.tar.age"
    monkeypatch.setattr(
        backup,
        "_safe_child",
        lambda args, **_kwargs: subprocess.CompletedProcess(args, 0, b"", b""),
    )
    with pytest.raises(backup.BackupError) as exc_info:
        backup.encrypt_bundle(bundle, ciphertext, "age1" + "q" * 58)
    assert exc_info.value.category == "encryption_failure"


def test_restore_credentials_are_never_sent_to_plain_http(monkeypatch):
    monkeypatch.setenv("OFFSITE_RESTORE_S3_ENDPOINT", "http://account.r2.invalid")
    monkeypatch.setenv("OFFSITE_RESTORE_S3_REGION", "auto")
    monkeypatch.setenv("OFFSITE_RESTORE_BUCKET", "private-backups")
    monkeypatch.setenv("OFFSITE_RESTORE_ACCESS_KEY_ID", "synthetic-access")
    monkeypatch.setenv("OFFSITE_RESTORE_SECRET_ACCESS_KEY", "synthetic-secret")
    with pytest.raises(backup.BackupError) as exc_info:
        restore_tool.restore_config_from_environment()
    assert exc_info.value.category == "invalid_configuration"
