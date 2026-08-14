"""Phase 98 unit coverage for encrypted offsite backup and restore safety."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile

import pytest

import models
import offsite_backup as backup
from scripts import restore_offsite_backup as restore_tool
from settings import Settings


RECIPIENT = "age1" + "q" * 58


def config(tmp_path: Path, **changes) -> backup.BackupConfig:
    uploads = tmp_path / "uploads"
    uploads.mkdir(exist_ok=True)
    ephemeral = tmp_path / "ephemeral"
    ephemeral.mkdir(exist_ok=True)
    base = backup.BackupConfig(
        enabled=True,
        time_utc="11:00",
        s3_endpoint="https://account.r2.cloudflarestorage.com",
        s3_region="auto",
        bucket="private-backups",
        prefix="production",
        access_key_id="synthetic-access-key",
        secret_access_key="synthetic-secret-value",
        age_recipient=RECIPIENT,
        stale_after_seconds=129600,
        instance_selector="",
        database_url="postgresql://synthetic:password@db.internal/liquid",
        uploads_root=uploads,
        temporary_root=ephemeral,
    )
    return replace(base, **changes)


def test_configuration_is_disabled_safe_by_default():
    settings = Settings(_env_file=None)
    assert settings.offsite_backup_enabled is False
    assert settings.offsite_backup_time_utc == "11:00"
    assert settings.offsite_backup_stale_after_seconds == 129600
    disabled = backup.BackupConfig(
        enabled=False, time_utc="11:00", s3_endpoint="", s3_region="auto",
        bucket="", prefix="production", access_key_id="", secret_access_key="",
        age_recipient="", stale_after_seconds=129600, instance_selector="",
        database_url="sqlite:///local.db", uploads_root=Path("/data/uploads"),
    )
    disabled.validate(require_enabled=False)
    with pytest.raises(backup.BackupError, match="disabled"):
        disabled.validate(require_enabled=True)


@pytest.mark.parametrize("field,value,category", [
    ("time_utc", "25:00", "invalid_configuration"),
    ("s3_endpoint", "http://public.invalid", "invalid_configuration"),
    ("bucket", "", "invalid_configuration"),
    ("secret_access_key", "change-me", "invalid_configuration"),
    ("age_recipient", "private-identity-material", "invalid_recipient"),
    ("database_url", "sqlite:///local.db", "invalid_configuration"),
])
def test_enabled_configuration_fails_closed(tmp_path, field, value, category):
    candidate = config(tmp_path, **{field: value})
    with pytest.raises(backup.BackupError) as exc_info:
        candidate.validate()
    assert exc_info.value.category == category


def test_temporary_storage_cannot_overlap_upload_volume(tmp_path):
    candidate = config(tmp_path)
    candidate = replace(candidate, temporary_root=candidate.uploads_root / "temp")
    with pytest.raises(backup.BackupError) as exc_info:
        candidate.validate()
    assert exc_info.value.category == "invalid_configuration"


def test_time_and_retention_classification_are_utc_calendar_based():
    assert backup.parse_backup_time("00:00") == (0, 0)
    sunday_first = datetime(2026, 11, 1, 11, tzinfo=timezone.utc)
    monday = sunday_first + timedelta(days=1)
    assert backup.retention_classes(sunday_first) == ["daily", "weekly", "monthly"]
    assert backup.retention_classes(monday) == ["daily"]


def test_upload_archive_contains_only_rooted_regular_files(tmp_path):
    candidate = config(tmp_path)
    (candidate.uploads_root / "avatars").mkdir()
    (candidate.uploads_root / "avatars" / "one.png").write_bytes(b"synthetic-image")
    destination = tmp_path / "uploads.tar.gz"
    count, total = backup.archive_uploads(candidate.uploads_root, destination)
    assert (count, total) == (1, len(b"synthetic-image"))
    with tarfile.open(destination, "r:gz") as archive:
        assert set(archive.getnames()) == {"uploads", "uploads/avatars", "uploads/avatars/one.png"}


def test_upload_archive_rejects_symlinks(tmp_path):
    candidate = config(tmp_path)
    outside = tmp_path / "outside-secret"
    outside.write_text("never archive", encoding="utf-8")
    link = candidate.uploads_root / "link"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(backup.BackupError) as exc_info:
        backup.archive_uploads(candidate.uploads_root, tmp_path / "unsafe.tar.gz")
    assert exc_info.value.category == "unsafe_upload_tree"


def test_client_major_must_not_be_older_than_live_server():
    good = {"pg_dump": "pg_dump (PostgreSQL) 18.2", "pg_restore": "pg_restore (PostgreSQL) 18.2"}
    backup.validate_client_server_compatibility(good, "18.1")
    with pytest.raises(backup.BackupError) as exc_info:
        backup.validate_client_server_compatibility(good, "19.0")
    assert exc_info.value.category == "toolchain_incompatible"


def test_toolchain_requires_pg18_and_pinned_age(monkeypatch):
    outputs = {
        "pg_dump": b"pg_dump (PostgreSQL) 18.2\n",
        "pg_restore": b"pg_restore (PostgreSQL) 18.2\n",
        "age": b"v1.3.1\n",
    }
    monkeypatch.setattr(
        backup, "_safe_child",
        lambda args, **_kwargs: __import__("subprocess").CompletedProcess(args, 0, outputs[args[0]], b""),
    )
    assert "18.2" in backup.tool_versions()["pg_dump"]
    outputs["age"] = b"v1.2.1\n"
    with pytest.raises(backup.BackupError) as exc_info:
        backup.tool_versions()
    assert exc_info.value.category == "toolchain_incompatible"


class MemoryS3:
    def __init__(self, *, uncertain_first: bool = False):
        self.objects = {}
        self.calls = []
        self.uncertain_first = uncertain_first

    def head_bucket(self, **_kwargs):
        return {}

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise RuntimeError("not found")
        item = self.objects[Key]
        return {"ContentLength": len(item["body"]), "Metadata": item["metadata"]}

    def put_object(self, **kwargs):
        assert kwargs["IfNoneMatch"] == "*"
        assert "ACL" not in kwargs
        body = kwargs["Body"].read()
        self.calls.append(kwargs["Key"])
        self.objects[kwargs["Key"]] = {"body": body, "metadata": kwargs["Metadata"]}
        if self.uncertain_first:
            self.uncertain_first = False
            raise TimeoutError("response lost after server commit")
        return {}


def test_object_keys_are_unique_prefixed_and_immutable_upload_is_verified(tmp_path):
    candidate = config(tmp_path)
    ciphertext = tmp_path / "ciphertext.age"
    ciphertext.write_bytes(b"age-encrypted-synthetic-data")
    checksum = backup.sha256_file(ciphertext)
    now = datetime(2026, 8, 14, 11, tzinfo=timezone.utc)
    key = backup.object_key(candidate.prefix, "daily", now, checksum)
    assert key == f"production/daily/2026/08/liquid-democracy-20260814T110000Z-{checksum[:12]}.tar.age"
    client = MemoryS3(uncertain_first=True)
    backup.upload_ciphertext(client, candidate, ciphertext, key, started=now, checksum=checksum)
    assert client.calls == [key]
    assert client.objects[key]["metadata"] == {
        "artifact-format-version": "1",
        "created-at-utc": "2026-08-14T11:00:00Z",
        "encrypted-bytes": str(ciphertext.stat().st_size),
        "ciphertext-sha256": checksum,
    }


def test_advisory_lock_rejects_overlap_and_releases():
    class Scalar:
        def __init__(self, value):
            self.value = value

        def scalar_one(self):
            return self.value

    class FakeSession:
        def __init__(self, acquire):
            self.acquire = acquire
            self.calls = []

        def execute(self, statement, parameters):
            rendered = str(statement)
            self.calls.append((rendered, parameters))
            return Scalar(self.acquire if "try_advisory" in rendered else True)

    blocked = FakeSession(False)
    with pytest.raises(backup.BackupError) as exc_info:
        with backup.advisory_lock(blocked):
            pass
    assert exc_info.value.category == "concurrent_run"
    acquired = FakeSession(True)
    with backup.advisory_lock(acquired):
        assert len(acquired.calls) == 1
    assert "pg_advisory_unlock" in acquired.calls[-1][0]
    assert acquired.calls[0][1] == acquired.calls[-1][1] == {"key": backup.ADVISORY_LOCK_KEY}


def test_preflight_is_read_only_and_accepts_disabled_flag(tmp_path, monkeypatch):
    candidate = config(tmp_path, enabled=False)
    client = MemoryS3()
    monkeypatch.setattr(backup, "tool_versions", lambda: {
        "pg_dump": "pg_dump (PostgreSQL) 18.1",
        "pg_restore": "pg_restore (PostgreSQL) 18.1",
        "age": "v1.3.1",
    })
    monkeypatch.setattr(backup, "database_metadata", lambda _db: {
        "server_version": "18.1", "database_size_bytes": 1,
    })
    monkeypatch.setattr(backup, "_recipient_preflight", lambda *_args: None)
    monkeypatch.setattr(backup, "_check_space", lambda *_args: None)

    @contextmanager
    def fake_lock(_db):
        yield

    monkeypatch.setattr(backup, "advisory_lock", fake_lock)
    monkeypatch.setattr(
        backup, "create_database_dump",
        lambda *_args: pytest.fail("preflight must not invoke pg_dump"),
    )
    result = backup.preflight(candidate, db=object(), client=client)
    assert result["ok"] is True
    assert client.calls == []
    assert client.objects == {}


def test_subprocess_failure_is_sanitized_and_sigterm_terminates_children():
    with pytest.raises(backup.BackupError) as exc_info:
        backup._safe_child([sys.executable, "-c", "raise SystemExit(7)"])
    assert exc_info.value.category == "subprocess_failure"
    assert "SystemExit" not in str(exc_info.value)

    class Child:
        def __init__(self):
            self.terminated = False

        def terminate(self):
            self.terminated = True

    child = Child()
    backup._ACTIVE_CHILDREN.add(child)  # signal-handler boundary, no process spawn needed
    try:
        backup.request_shutdown(15, None)
        assert child.terminated is True
        assert backup.shutdown_requested() is True
    finally:
        backup._ACTIVE_CHILDREN.discard(child)
        backup.reset_interruption_for_tests()


def test_invalid_recipient_aborts_before_any_network_write(tmp_path):
    candidate = config(tmp_path, age_recipient="invalid")
    client = MemoryS3()
    with pytest.raises(backup.BackupError) as exc_info:
        backup.run_backup(candidate, client=client)
    assert exc_info.value.category == "invalid_recipient"
    assert client.calls == []


def test_complete_pipeline_uploads_only_ciphertext_and_persists_coarse_state(
    db, tmp_path, monkeypatch,
):
    candidate = config(tmp_path)
    (candidate.uploads_root / "avatars").mkdir()
    (candidate.uploads_root / "avatars" / "synthetic.png").write_bytes(b"file")
    monkeypatch.setattr(backup, "SessionLocal", lambda: db)

    @contextmanager
    def fake_lock(_db):
        yield

    monkeypatch.setattr(backup, "advisory_lock", fake_lock)
    monkeypatch.setattr(backup, "database_metadata", lambda _db: {
        "server_version": "18.1", "database_name": "liquid",
        "alembic_current": "head123", "alembic_head": "head123",
        "representative_row_counts": {"users": 3}, "database_size_bytes": 1024,
    })
    monkeypatch.setattr(backup, "tool_versions", lambda: {
        "pg_dump": "pg_dump (PostgreSQL) 18.1",
        "pg_restore": "pg_restore (PostgreSQL) 18.1",
        "age": "v1.3.1",
    })
    monkeypatch.setattr(backup, "create_database_dump", lambda _cfg, path: path.write_bytes(b"custom-dump"))

    def fake_encrypt(bundle, ciphertext, _recipient):
        ciphertext.write_bytes(b"age-ciphertext:" + backup.sha256_file(bundle).encode("ascii"))

    monkeypatch.setattr(backup, "encrypt_bundle", fake_encrypt)

    class InspectingS3(MemoryS3):
        def put_object(self, **kwargs):
            siblings = {path.name for path in Path(kwargs["Body"].name).parent.iterdir()}
            assert siblings == {"backup.tar.age"}
            return super().put_object(**kwargs)

    client = InspectingS3()
    result = backup.run_backup(candidate, client=client, now=datetime.now(timezone.utc))
    assert result["status"] == "ok"
    assert set(result["retention_classes"]).issubset({"daily", "weekly", "monthly"})
    assert len(client.objects) == len(result["retention_classes"])
    assert all(item["body"].startswith(b"age-ciphertext:") for item in client.objects.values())
    state = db.get(models.PlatformSetting, backup.STATE_KEY).value
    assert state["consecutive_failures"] == 0
    assert state["last_success_at"]
    serialized = json.dumps(state)
    assert candidate.secret_access_key not in serialized
    assert candidate.database_url not in serialized
    assert candidate.s3_endpoint not in serialized


def test_interrupted_dump_cleans_temporary_files_records_state_and_never_uploads(
    db, tmp_path, monkeypatch,
):
    candidate = config(tmp_path)
    monkeypatch.setattr(backup, "SessionLocal", lambda: db)

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
        "server_version": "18.1", "database_name": "liquid",
        "alembic_current": "head123", "alembic_head": "head123",
        "representative_row_counts": {}, "database_size_bytes": 1,
    })

    def interrupted(_config, destination):
        destination.write_bytes(b"partial plaintext")
        raise backup.BackupInterrupted()

    monkeypatch.setattr(backup, "create_database_dump", interrupted)
    client = MemoryS3()
    with pytest.raises(backup.BackupInterrupted):
        backup.run_backup(candidate, client=client)
    assert client.calls == []
    assert list(candidate.temporary_root.iterdir()) == []
    state = db.get(models.PlatformSetting, backup.STATE_KEY).value
    assert state["failure_category"] == "interrupted"
    assert state["last_interruption_at"]
    assert state["consecutive_failures"] == 1


def test_restore_target_requires_disposable_name_and_exact_confirmation(monkeypatch):
    monkeypatch.setenv("OFFSITE_PRODUCTION_DATABASE_HOST", "prod.internal")
    monkeypatch.setenv("OFFSITE_PRODUCTION_DATABASE_NAME", "liquid")
    target = "postgresql://operator:pw@isolated.local/phase98_restore_test"
    confirmation = restore_tool.required_confirmation(target)
    restore_tool.validate_target(target, confirmation, "postgresql://prod:pw@prod.internal/liquid")
    with pytest.raises(backup.BackupError):
        restore_tool.validate_target(target, "yes", "postgresql://prod:pw@prod.internal/liquid")
    with pytest.raises(backup.BackupError):
        restore_tool.validate_target(
            "postgresql://operator:pw@prod.internal/phase98_restore_test",
            "RESTORE DISPOSABLE DATABASE phase98_restore_test ON prod.internal",
            "postgresql://prod:pw@prod.internal/liquid",
        )


def test_restore_credentials_require_https_and_reject_placeholders(monkeypatch):
    values = {
        "OFFSITE_RESTORE_S3_ENDPOINT": "http://account.invalid",
        "OFFSITE_RESTORE_S3_REGION": "auto",
        "OFFSITE_RESTORE_BUCKET": "private-backups",
        "OFFSITE_RESTORE_ACCESS_KEY_ID": "synthetic-access",
        "OFFSITE_RESTORE_SECRET_ACCESS_KEY": "synthetic-secret",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(backup.BackupError) as exc_info:
        restore_tool.restore_config_from_environment()
    assert exc_info.value.category == "invalid_configuration"
    monkeypatch.setenv("OFFSITE_RESTORE_S3_ENDPOINT", "https://account.invalid")
    monkeypatch.setenv("OFFSITE_RESTORE_SECRET_ACCESS_KEY", "change-me")
    with pytest.raises(backup.BackupError) as exc_info:
        restore_tool.restore_config_from_environment()
    assert exc_info.value.category == "invalid_configuration"
    with pytest.raises(backup.BackupError):
        restore_tool.validate_target(
            "postgresql://operator:pw@isolated.local/liquid",
            "RESTORE DISPOSABLE DATABASE liquid ON isolated.local",
            "postgresql://prod:pw@prod.internal/liquid",
        )


def _write_member(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    archive.addfile(info, io.BytesIO(payload))


def test_bundle_verification_checks_member_checksums(tmp_path):
    dump = b"synthetic-custom-dump"
    uploads = b"synthetic-upload-archive"
    manifest = {
        "artifact_format_version": backup.ARTIFACT_FORMAT_VERSION,
        "environment": "production",
        "alembic": {"current_revision": "head123", "head_revision": "head123"},
        "members": {
            "database.dump": {"bytes": len(dump), "sha256": __import__("hashlib").sha256(dump).hexdigest()},
            "uploads.tar.gz": {"bytes": len(uploads), "sha256": __import__("hashlib").sha256(uploads).hexdigest()},
        },
    }
    bundle = tmp_path / "bundle.tar"
    with tarfile.open(bundle, "w") as archive:
        _write_member(archive, "manifest.json", json.dumps(manifest).encode())
        _write_member(archive, "database.dump", dump)
        _write_member(archive, "uploads.tar.gz", uploads)
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    assert restore_tool._extract_bundle(bundle, extracted)["artifact_format_version"] == 1
    (extracted / "database.dump").write_bytes(b"tampered")
    # A fresh extraction catches tampering encoded into the bundle itself.
    tampered_bundle = tmp_path / "tampered.tar"
    with tarfile.open(tampered_bundle, "w") as archive:
        _write_member(archive, "manifest.json", json.dumps(manifest).encode())
        _write_member(archive, "database.dump", b"tampered")
        _write_member(archive, "uploads.tar.gz", uploads)
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    with pytest.raises(backup.BackupError) as exc_info:
        restore_tool._extract_bundle(tampered_bundle, fresh)
    assert exc_info.value.category == "verification_failure"


def test_bundle_rejects_database_not_at_alembic_head(tmp_path):
    dump = b"dump"
    uploads = b"uploads"
    digest = __import__("hashlib").sha256
    manifest = {
        "artifact_format_version": 1,
        "environment": "production",
        "alembic": {"current_revision": "prior", "head_revision": "head"},
        "members": {
            "database.dump": {"bytes": len(dump), "sha256": digest(dump).hexdigest()},
            "uploads.tar.gz": {"bytes": len(uploads), "sha256": digest(uploads).hexdigest()},
        },
    }
    bundle = tmp_path / "behind.tar"
    with tarfile.open(bundle, "w") as archive:
        _write_member(archive, "manifest.json", json.dumps(manifest).encode())
        _write_member(archive, "database.dump", dump)
        _write_member(archive, "uploads.tar.gz", uploads)
    destination = tmp_path / "behind"
    destination.mkdir()
    with pytest.raises(backup.BackupError) as exc_info:
        restore_tool._extract_bundle(bundle, destination)
    assert exc_info.value.category == "verification_failure"


def test_upload_restore_rejects_backslash_traversal_and_reports_counts(tmp_path):
    destination = tmp_path / "restored-uploads"
    destination.mkdir()
    safe_archive = tmp_path / "safe-uploads.tar.gz"
    with tarfile.open(safe_archive, "w:gz") as archive:
        directory = tarfile.TarInfo("uploads/")
        directory.type = tarfile.DIRTYPE
        archive.addfile(directory)
        _write_member(archive, "uploads/avatars/one.png", b"four")
    assert restore_tool._extract_uploads(safe_archive, destination) == (1, 4)

    unsafe_destination = tmp_path / "unsafe-uploads"
    unsafe_destination.mkdir()
    unsafe_archive = tmp_path / "unsafe-uploads.tar.gz"
    with tarfile.open(unsafe_archive, "w:gz") as archive:
        _write_member(archive, "uploads/..\\escape.txt", b"escape")
    with pytest.raises(backup.BackupError) as exc_info:
        restore_tool._extract_uploads(unsafe_archive, unsafe_destination)
    assert exc_info.value.category == "verification_failure"
    assert not (tmp_path / "escape.txt").exists()


@pytest.mark.skipif(shutil.which("age") is None or shutil.which("age-keygen") is None, reason="age binary not installed locally")
def test_age_round_trip_uses_disposable_identity_and_wrong_identity_fails(tmp_path):
    identity = tmp_path / "identity.txt"
    generated = backup._safe_child(["age-keygen", "-o", str(identity)])
    recipient_line = generated.stderr.decode("utf-8", "replace") + generated.stdout.decode("utf-8", "replace")
    match = re_search = __import__("re").search(r"age1[023456789acdefghjklmnpqrstuvwxyz]{50,80}", recipient_line)
    assert match is not None, re_search
    plaintext = tmp_path / "plain.tar"
    plaintext.write_bytes(b"synthetic secret")
    ciphertext = tmp_path / "plain.tar.age"
    backup.encrypt_bundle(plaintext, ciphertext, match.group(0))
    plaintext.unlink()
    restored = tmp_path / "restored.tar"
    backup._safe_child(["age", "--decrypt", "-i", str(identity), "-o", str(restored), str(ciphertext)])
    assert restored.read_bytes() == b"synthetic secret"
    wrong_identity = tmp_path / "wrong.txt"
    backup._safe_child(["age-keygen", "-o", str(wrong_identity)])
    with pytest.raises(backup.BackupError):
        backup._safe_child(["age", "--decrypt", "-i", str(wrong_identity), "-o", str(tmp_path / "wrong.out"), str(ciphertext)])
