"""Phase 98 encrypted PostgreSQL + uploads offsite backups.

This module contains the reusable, testable backup pipeline.  It is imported
by the dedicated worker and by the public-safe monitor, but it never starts a
backup at import time.  Detailed manifests remain inside the age-encrypted
bundle; logs and PlatformSetting state intentionally contain only coarse data.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import stat
import subprocess
import tarfile
import tempfile
import threading
import time
from typing import Any, Iterator, Optional
from urllib.parse import urlparse

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

import models
from database import SessionLocal
from settings import settings


ARTIFACT_FORMAT_VERSION = 1
STATE_KEY = "offsite_backup_state_v1"
ADVISORY_LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"liquid-democracy:offsite-backup:v1").digest()[:8], "big"
) & 0x7FFF_FFFF_FFFF_FFFF
AGE_VERSION = "1.3.1"
MINIMUM_FREE_BYTES = 256 * 1024 * 1024
WEEKLY_UTC_WEEKDAY = 6  # Sunday
MONTHLY_UTC_DAY = 1
ROW_COUNT_TABLES = (
    "users", "organizations", "org_memberships", "proposals", "votes",
    "delegations", "uploaded_files",
)

_AGE_RECIPIENT_RE = re.compile(r"^age1[023456789acdefghjklmnpqrstuvwxyz]{50,80}$")
_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_PLACEHOLDER_PARTS = ("change-me", "placeholder", "replace-me", "example-secret")
_ACTIVE_CHILDREN: set[subprocess.Popen[bytes]] = set()
_CHILD_LOCK = threading.Lock()
_INTERRUPTED = threading.Event()


class BackupError(RuntimeError):
    """Expected backup failure with a public-safe category."""

    def __init__(self, category: str, message: str = "backup operation failed"):
        super().__init__(message)
        self.category = category


class BackupInterrupted(BackupError):
    def __init__(self) -> None:
        super().__init__("interrupted", "backup interrupted by shutdown")


@dataclass(frozen=True)
class BackupConfig:
    enabled: bool
    time_utc: str
    s3_endpoint: str
    s3_region: str
    bucket: str
    prefix: str
    access_key_id: str
    secret_access_key: str
    age_recipient: str
    stale_after_seconds: int
    instance_selector: str
    database_url: str
    uploads_root: Path
    temporary_root: Optional[Path] = None

    @classmethod
    def from_settings(cls) -> "BackupConfig":
        uploads = os.environ.get("UPLOAD_DIR") or os.environ.get("UPLOADS_BASE_DIR") or "/data/uploads"
        return cls(
            enabled=settings.offsite_backup_enabled,
            time_utc=settings.offsite_backup_time_utc,
            s3_endpoint=settings.offsite_backup_s3_endpoint.strip(),
            s3_region=settings.offsite_backup_s3_region.strip(),
            bucket=settings.offsite_backup_bucket.strip(),
            prefix=settings.offsite_backup_prefix.strip(),
            access_key_id=settings.offsite_backup_access_key_id.strip(),
            secret_access_key=settings.offsite_backup_secret_access_key.strip(),
            age_recipient=settings.offsite_backup_age_recipient.strip(),
            stale_after_seconds=settings.offsite_backup_stale_after_seconds,
            instance_selector=settings.offsite_backup_worker_instance_id.strip(),
            database_url=settings.database_url,
            uploads_root=Path(uploads),
            temporary_root=None,
        )

    def validate(
        self, *, require_enabled: bool = True, validate_credentials: bool = False,
    ) -> None:
        parse_backup_time(self.time_utc)
        if self.stale_after_seconds < 3600:
            raise BackupError("invalid_configuration", "stale threshold is too short")
        if require_enabled and not self.enabled:
            raise BackupError("disabled", "offsite backup is disabled")
        if not self.enabled and not require_enabled and not validate_credentials:
            return
        required = {
            "endpoint": self.s3_endpoint,
            "region": self.s3_region,
            "bucket": self.bucket,
            "access key": self.access_key_id,
            "secret key": self.secret_access_key,
            "age recipient": self.age_recipient,
            "database URL": self.database_url,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise BackupError("invalid_configuration", "required backup configuration is missing")
        if any(part in value.lower() for value in required.values() for part in _PLACEHOLDER_PARTS):
            raise BackupError("invalid_configuration", "placeholder backup configuration is forbidden")
        parsed_endpoint = urlparse(self.s3_endpoint)
        if parsed_endpoint.scheme != "https" or not parsed_endpoint.hostname:
            raise BackupError("invalid_configuration", "S3 endpoint must be HTTPS")
        if not _BUCKET_RE.fullmatch(self.bucket):
            raise BackupError("invalid_configuration", "invalid bucket name")
        normalized_prefix = self.prefix.strip("/")
        if not normalized_prefix or ".." in PurePosixPath(normalized_prefix).parts:
            raise BackupError("invalid_configuration", "invalid object prefix")
        if not _AGE_RECIPIENT_RE.fullmatch(self.age_recipient):
            raise BackupError("invalid_recipient", "invalid age recipient")
        try:
            url = make_url(self.database_url)
        except Exception as exc:
            raise BackupError("invalid_configuration", "invalid database URL") from exc
        if not url.drivername.startswith("postgresql") or not url.database:
            raise BackupError("invalid_configuration", "backup requires PostgreSQL")
        if not self.uploads_root.is_absolute():
            raise BackupError("invalid_configuration", "uploads root must be absolute")
        if self.temporary_root is not None:
            try:
                temporary = self.temporary_root.resolve()
                uploads = self.uploads_root.resolve()
                if temporary == uploads or uploads in temporary.parents or temporary in uploads.parents:
                    raise BackupError("invalid_configuration", "temporary storage must be separate from uploads")
            except OSError as exc:
                raise BackupError("invalid_configuration", "invalid temporary storage root") from exc


def parse_backup_time(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{2}):(\d{2})", value or "")
    if not match:
        raise BackupError("invalid_configuration", "backup time must be HH:MM")
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise BackupError("invalid_configuration", "backup time is outside UTC day")
    return hour, minute


def retention_classes(now: datetime) -> list[str]:
    now = as_utc(now)
    classes = ["daily"]
    if now.weekday() == WEEKLY_UTC_WEEKDAY:
        classes.append("weekly")
    if now.day == MONTHLY_UTC_DAY:
        classes.append("monthly")
    return classes


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_child(args: list[str], *, env: Optional[dict[str, str]] = None) -> subprocess.CompletedProcess[bytes]:
    """Run a child without a shell while allowing prompt SIGTERM cleanup."""
    if _INTERRUPTED.is_set():
        raise BackupInterrupted()
    process = subprocess.Popen(
        args,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    )
    with _CHILD_LOCK:
        _ACTIVE_CHILDREN.add(process)
    try:
        stdout, stderr = process.communicate()
    finally:
        with _CHILD_LOCK:
            _ACTIVE_CHILDREN.discard(process)
    if _INTERRUPTED.is_set():
        raise BackupInterrupted()
    if process.returncode:
        raise BackupError("subprocess_failure", f"{Path(args[0]).name} failed")
    return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)


def request_shutdown(_signum: int, _frame: Any) -> None:
    _INTERRUPTED.set()
    with _CHILD_LOCK:
        children = list(_ACTIVE_CHILDREN)
    for process in children:
        try:
            process.terminate()
        except OSError:
            pass


def install_signal_handlers() -> None:
    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)


def reset_interruption_for_tests() -> None:
    _INTERRUPTED.clear()


def shutdown_requested() -> bool:
    return _INTERRUPTED.is_set()


def wait_for_shutdown(timeout_seconds: float) -> bool:
    return _INTERRUPTED.wait(timeout=max(0.0, timeout_seconds))


def _postgres_env(database_url: str) -> dict[str, str]:
    url = make_url(database_url)
    env = dict(os.environ)
    mapping = {
        "PGHOST": url.host,
        "PGPORT": str(url.port) if url.port else None,
        "PGDATABASE": url.database,
        "PGUSER": url.username,
        "PGPASSWORD": url.password,
    }
    for key, value in mapping.items():
        if value is not None:
            env[key] = str(value)
    query = dict(url.query)
    if query.get("sslmode"):
        env["PGSSLMODE"] = str(query["sslmode"])
    return env


def tool_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    commands = {
        "pg_dump": ["pg_dump", "--version"],
        "pg_restore": ["pg_restore", "--version"],
        "age": ["age", "--version"],
    }
    for name, args in commands.items():
        try:
            output = _safe_child(args).stdout.decode("utf-8", "replace").strip()
        except (OSError, BackupError) as exc:
            raise BackupError("toolchain_unavailable", f"required tool {name} is unavailable") from exc
        versions[name] = output
    pg_match = re.search(r"(\d+)(?:\.\d+)?", versions["pg_dump"])
    restore_match = re.search(r"(\d+)(?:\.\d+)?", versions["pg_restore"])
    if not pg_match or int(pg_match.group(1)) < 18 or not restore_match or int(restore_match.group(1)) < 18:
        raise BackupError("toolchain_incompatible", "PostgreSQL 18-compatible clients are required")
    if AGE_VERSION not in versions["age"]:
        raise BackupError("toolchain_incompatible", "unexpected age version")
    return versions


def _tool_major(version: str) -> int:
    match = re.search(r"(\d+)(?:\.\d+)?", version or "")
    if not match:
        raise BackupError("toolchain_incompatible", "tool major version is unavailable")
    return int(match.group(1))


def validate_client_server_compatibility(versions: dict[str, str], server_version: str) -> None:
    server_major = _tool_major(server_version)
    dump_major = _tool_major(versions.get("pg_dump", ""))
    restore_major = _tool_major(versions.get("pg_restore", ""))
    if dump_major < server_major or restore_major < server_major:
        raise BackupError(
            "toolchain_incompatible",
            "PostgreSQL clients are older than the live server",
        )


def _inspect_upload_tree(root: Path) -> tuple[int, int]:
    try:
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise BackupError("uploads_unavailable", "uploads root is unavailable") from exc
    if not resolved.is_dir():
        raise BackupError("uploads_unavailable", "uploads root is not a directory")
    count = 0
    total = 0
    for current, dirs, files in os.walk(resolved, followlinks=False):
        current_path = Path(current)
        for name in list(dirs):
            path = current_path / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise BackupError("unsafe_upload_tree", "upload symlinks are forbidden")
            if not stat.S_ISDIR(mode):
                raise BackupError("unsafe_upload_tree", "special upload entries are forbidden")
        for name in files:
            path = current_path / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
                raise BackupError("unsafe_upload_tree", "non-regular upload entries are forbidden")
            count += 1
            total += path.stat().st_size
    return count, total


def archive_uploads(root: Path, destination: Path) -> tuple[int, int]:
    count, total = _inspect_upload_tree(root)
    resolved = root.resolve(strict=True)
    try:
        with tarfile.open(destination, "w:gz", format=tarfile.PAX_FORMAT) as archive:
            _tar_add_directory(archive, resolved, "uploads")
            for current, dirs, files in os.walk(resolved, followlinks=False):
                current_path = Path(current)
                relative = current_path.relative_to(resolved)
                for name in sorted(dirs):
                    path = current_path / name
                    _tar_add_directory(
                        archive, path,
                        str(PurePosixPath("uploads", relative.as_posix(), name)),
                    )
                for name in sorted(files):
                    path = current_path / name
                    _tar_add_regular(
                        archive, path,
                        str(PurePosixPath("uploads", relative.as_posix(), name)),
                    )
    except BackupError:
        raise
    except Exception as exc:
        raise BackupError("archive_failure", "uploads archive failed") from exc
    return count, total


def _tar_info(name: str, source_stat: os.stat_result, *, is_directory: bool) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name.rstrip("/") + ("/" if is_directory else ""))
    info.mode = stat.S_IMODE(source_stat.st_mode)
    info.mtime = int(source_stat.st_mtime)
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.type = tarfile.DIRTYPE if is_directory else tarfile.REGTYPE
    info.size = 0 if is_directory else int(source_stat.st_size)
    return info


def _tar_add_directory(archive: tarfile.TarFile, path: Path, name: str) -> None:
    source_stat = path.lstat()
    if not stat.S_ISDIR(source_stat.st_mode) or stat.S_ISLNK(source_stat.st_mode):
        raise BackupError("unsafe_upload_tree", "upload directory changed during archive")
    archive.addfile(_tar_info(name, source_stat, is_directory=True))


def _tar_add_regular(archive: tarfile.TarFile, path: Path, name: str) -> None:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
        raise BackupError("unsafe_upload_tree", "upload file changed during archive")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise BackupError("unsafe_upload_tree", "upload file could not be opened safely") from exc
    with os.fdopen(descriptor, "rb") as file_handle:
        opened = os.fstat(file_handle.fileno())
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != before.st_dev
            or opened.st_ino != before.st_ino
        ):
            raise BackupError("unsafe_upload_tree", "upload file changed during archive")
        archive.addfile(_tar_info(name, opened, is_directory=False), fileobj=file_handle)


def create_database_dump(config: BackupConfig, destination: Path) -> None:
    args = [
        "pg_dump", "--format=custom", "--compress=6", "--no-password",
        "--file", str(destination),
    ]
    try:
        _safe_child(args, env=_postgres_env(config.database_url))
    except OSError as exc:
        raise BackupError("toolchain_unavailable", "pg_dump is unavailable") from exc


def _alembic_head() -> str:
    config_path = Path(__file__).with_name("alembic.ini")
    cfg = AlembicConfig(str(config_path))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    return ",".join(sorted(heads))


def database_metadata(db: Session) -> dict[str, Any]:
    try:
        server_version = str(db.execute(text("SHOW server_version")).scalar_one())
        current_rows = db.execute(text("SELECT version_num FROM alembic_version ORDER BY version_num")).scalars().all()
        database_name = str(db.execute(text("SELECT current_database()")).scalar_one())
        counts: dict[str, int] = {}
        for table_name in ROW_COUNT_TABLES:
            exists = db.execute(text("SELECT to_regclass(:name)"), {"name": table_name}).scalar_one()
            if exists:
                counts[table_name] = int(db.execute(text(f'SELECT count(*) FROM "{table_name}"')).scalar_one())
        size_bytes = int(db.execute(text("SELECT pg_database_size(current_database())")).scalar_one())
    except Exception as exc:
        raise BackupError("database_metadata_failure", "database metadata unavailable") from exc
    return {
        "server_version": server_version,
        "database_name": database_name,
        "alembic_current": ",".join(str(row) for row in current_rows),
        "alembic_head": _alembic_head(),
        "representative_row_counts": counts,
        "database_size_bytes": size_bytes,
    }


@contextmanager
def advisory_lock(db: Session) -> Iterator[None]:
    try:
        acquired = bool(db.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": ADVISORY_LOCK_KEY}
        ).scalar_one())
    except Exception as exc:
        raise BackupError("lock_unavailable", "backup advisory lock failed") from exc
    if not acquired:
        raise BackupError("concurrent_run", "another backup run owns the advisory lock")
    try:
        yield
    finally:
        try:
            db.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": ADVISORY_LOCK_KEY})
        except Exception:
            pass


def _recipient_preflight(recipient: str, directory: Path) -> None:
    empty = directory / "recipient-check.txt"
    encrypted = directory / "recipient-check.age"
    empty.write_bytes(b"")
    try:
        _safe_child(["age", "--encrypt", "-r", recipient, "-o", str(encrypted), str(empty)])
    except (OSError, BackupError) as exc:
        raise BackupError("invalid_recipient", "age recipient validation failed") from exc
    finally:
        empty.unlink(missing_ok=True)
        encrypted.unlink(missing_ok=True)


def _s3_client(config: BackupConfig):
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise BackupError("toolchain_unavailable", "S3 client library is unavailable") from exc
    return boto3.client(
        "s3",
        endpoint_url=config.s3_endpoint,
        region_name=config.s3_region,
        aws_access_key_id=config.access_key_id,
        aws_secret_access_key=config.secret_access_key,
        config=Config(
            connect_timeout=10,
            read_timeout=30,
            retries={"max_attempts": 1, "mode": "standard"},
            signature_version="s3v4",
        ),
    )


def _check_space(config: BackupConfig, database_bytes: int, uploads_bytes: int) -> None:
    root = config.temporary_root or Path(tempfile.gettempdir())
    root.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(root).free
    required = max(MINIMUM_FREE_BYTES, 2 * (database_bytes + uploads_bytes))
    if free < required:
        raise BackupError("insufficient_space", "insufficient ephemeral storage for backup")


def preflight(config: BackupConfig, *, db: Optional[Session] = None, client: Any = None) -> dict[str, Any]:
    """Read-only checks.  Does not dump the database or write to object storage."""
    config.validate(require_enabled=False, validate_credentials=True)
    if config.instance_selector:
        current = os.environ.get("INSTANCE_ID") or os.environ.get("RAILWAY_REPLICA_ID") or ""
        if current != config.instance_selector:
            raise BackupError("wrong_instance", "this replica is not selected for backups")
    versions = tool_versions()
    own_db = db is None
    db = db or SessionLocal()
    try:
        with advisory_lock(db):
            metadata = database_metadata(db)
            validate_client_server_compatibility(versions, metadata["server_version"])
            _, upload_bytes = _inspect_upload_tree(config.uploads_root)
            _check_space(config, metadata["database_size_bytes"], upload_bytes)
            temp_parent = str(config.temporary_root) if config.temporary_root else None
            with tempfile.TemporaryDirectory(prefix="offsite-preflight-", dir=temp_parent) as temporary:
                os.chmod(temporary, 0o700)
                _recipient_preflight(config.age_recipient, Path(temporary))
            s3 = client or _s3_client(config)
            s3.head_bucket(Bucket=config.bucket)
    except BackupError:
        raise
    except Exception as exc:
        raise BackupError("object_store_unavailable", "object store preflight failed") from exc
    finally:
        if own_db:
            db.close()
    return {
        "ok": True,
        "pg_dump_version": versions["pg_dump"],
        "pg_restore_version": versions["pg_restore"],
        "age_version": versions["age"],
    }


def _bundle(directory: Path, manifest: dict[str, Any]) -> Path:
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    bundle_path = directory / "backup.tar"
    with tarfile.open(bundle_path, "w", format=tarfile.PAX_FORMAT) as archive:
        for name in ("manifest.json", "database.dump", "uploads.tar.gz"):
            archive.add(directory / name, arcname=name, recursive=False)
    return bundle_path


def encrypt_bundle(bundle: Path, ciphertext: Path, recipient: str) -> None:
    try:
        _safe_child(["age", "--encrypt", "-r", recipient, "-o", str(ciphertext), str(bundle)])
    except OSError as exc:
        raise BackupError("toolchain_unavailable", "age is unavailable") from exc
    if not ciphertext.is_file() or ciphertext.stat().st_size == 0:
        raise BackupError("encryption_failure", "age produced no ciphertext")


def object_key(prefix: str, retention: str, started: datetime, ciphertext_sha256: str) -> str:
    started = as_utc(started)
    clean_prefix = prefix.strip("/")
    timestamp = started.strftime("%Y%m%dT%H%M%SZ")
    return (
        f"{clean_prefix}/{retention}/{started:%Y/%m}/"
        f"liquid-democracy-{timestamp}-{ciphertext_sha256[:12]}.tar.age"
    )


def _verified_existing(client: Any, bucket: str, key: str, size: int, checksum: str) -> bool:
    try:
        head = client.head_object(Bucket=bucket, Key=key)
    except Exception:
        return False
    metadata = head.get("Metadata") or {}
    return int(head.get("ContentLength", -1)) == size and metadata.get("ciphertext-sha256") == checksum


def upload_ciphertext(
    client: Any, config: BackupConfig, ciphertext: Path, key: str,
    *, started: datetime, checksum: str, attempts: int = 3,
) -> None:
    size = ciphertext.stat().st_size
    metadata = {
        "artifact-format-version": str(ARTIFACT_FORMAT_VERSION),
        "created-at-utc": as_utc(started).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "encrypted-bytes": str(size),
        "ciphertext-sha256": checksum,
    }
    for attempt in range(attempts):
        if _INTERRUPTED.is_set():
            raise BackupInterrupted()
        if attempt and _verified_existing(client, config.bucket, key, size, checksum):
            return
        try:
            with ciphertext.open("rb") as body:
                client.put_object(
                    Bucket=config.bucket,
                    Key=key,
                    Body=body,
                    ContentLength=size,
                    ContentType="application/octet-stream",
                    Metadata=metadata,
                    IfNoneMatch="*",
                )
            break
        except Exception as exc:
            if _verified_existing(client, config.bucket, key, size, checksum):
                return
            if attempt + 1 >= attempts:
                raise BackupError("upload_failure", "ciphertext upload failed") from exc
            time.sleep(min(2 ** attempt, 4))
    if not _verified_existing(client, config.bucket, key, size, checksum):
        raise BackupError("verification_failure", "uploaded object did not verify")


def load_state(db: Session) -> dict[str, Any]:
    row = db.get(models.PlatformSetting, STATE_KEY)
    return dict(row.value) if row is not None and isinstance(row.value, dict) else {}


def persist_state(db: Session, state: dict[str, Any]) -> None:
    safe = dict(state)
    safe["version"] = 1
    row = db.get(models.PlatformSetting, STATE_KEY)
    if row is None:
        db.add(models.PlatformSetting(key=STATE_KEY, value=safe))
    else:
        row.value = safe
    db.commit()


def _state_attempt(db: Session, now: datetime) -> dict[str, Any]:
    state = load_state(db)
    state.update({"enabled": True, "last_attempt_at": as_utc(now).isoformat()})
    persist_state(db, state)
    return state


def _state_failure(db: Session, state: dict[str, Any], now: datetime, category: str) -> None:
    state.update({
        "enabled": True,
        "last_failure_at": as_utc(now).isoformat(),
        "consecutive_failures": int(state.get("consecutive_failures", 0)) + 1,
        "failure_category": category,
    })
    if category == "interrupted":
        state["last_interruption_at"] = as_utc(now).isoformat()
    persist_state(db, state)


def mark_disabled_state(db: Session) -> None:
    state = load_state(db)
    if state.get("enabled") is not False:
        state["enabled"] = False
        persist_state(db, state)


def run_backup(config: BackupConfig, *, client: Any = None, now: Optional[datetime] = None) -> dict[str, Any]:
    """Execute one locked backup.  Only ciphertext exists when upload starts."""
    started = as_utc(now or datetime.now(timezone.utc))
    config.validate(require_enabled=True)
    if config.instance_selector:
        current = os.environ.get("INSTANCE_ID") or os.environ.get("RAILWAY_REPLICA_ID") or ""
        if current != config.instance_selector:
            raise BackupError("wrong_instance", "this replica is not selected for backups")
    db = SessionLocal()
    state = _state_attempt(db, started)
    temp_parent = str(config.temporary_root) if config.temporary_root else None
    try:
        with advisory_lock(db):
            # Verify the client contract before pg_dump can touch production.
            versions = tool_versions()
            metadata = database_metadata(db)
            validate_client_server_compatibility(versions, metadata["server_version"])
            upload_count, upload_bytes = _inspect_upload_tree(config.uploads_root)
            _check_space(config, metadata["database_size_bytes"], upload_bytes)
            classes = retention_classes(started)
            with tempfile.TemporaryDirectory(prefix="offsite-backup-", dir=temp_parent) as temporary:
                os.chmod(temporary, 0o700)
                directory = Path(temporary)
                dump = directory / "database.dump"
                uploads = directory / "uploads.tar.gz"
                ciphertext = directory / "backup.tar.age"
                create_database_dump(config, dump)
                archived_count, archived_bytes = archive_uploads(config.uploads_root, uploads)
                if (archived_count, archived_bytes) != (upload_count, upload_bytes):
                    raise BackupError("upload_tree_changed", "uploads changed during backup window")
                completed = datetime.now(timezone.utc)
                pg_client = versions["pg_dump"]
                manifest = {
                    "artifact_format_version": ARTIFACT_FORMAT_VERSION,
                    "environment": "production",
                    "application_commit_sha": (
                        os.environ.get("RAILWAY_GIT_COMMIT_SHA")
                        or os.environ.get("GIT_COMMIT_SHA") or "unknown"
                    )[:64],
                    "started_at_utc": started.isoformat(),
                    "completed_at_utc": completed.isoformat(),
                    "backup_window_seconds": round((completed - started).total_seconds(), 3),
                    "postgresql": {
                        "server_version": metadata["server_version"],
                        "client_version": pg_client,
                        "database_name": metadata["database_name"],
                    },
                    "alembic": {
                        "current_revision": metadata["alembic_current"],
                        "head_revision": metadata["alembic_head"],
                    },
                    "members": {
                        "database.dump": {"bytes": dump.stat().st_size, "sha256": sha256_file(dump)},
                        "uploads.tar.gz": {"bytes": uploads.stat().st_size, "sha256": sha256_file(uploads)},
                    },
                    "uploads_file_count": upload_count,
                    "uploads_aggregate_bytes": upload_bytes,
                    "representative_table_row_counts": metadata["representative_row_counts"],
                    "retention_classes": classes,
                    "encryption_recipient_fingerprint": hashlib.sha256(
                        config.age_recipient.encode("ascii")
                    ).hexdigest()[:20],
                }
                bundle = _bundle(directory, manifest)
                encrypt_bundle(bundle, ciphertext, config.age_recipient)
                # No plaintext survives into the network phase or any retry sleep.
                for path in (directory / "manifest.json", dump, uploads, bundle):
                    path.unlink(missing_ok=True)
                checksum = sha256_file(ciphertext)
                size = ciphertext.stat().st_size
                s3 = client or _s3_client(config)
                keys: list[str] = []
                for retention in classes:
                    key = object_key(config.prefix, retention, started, checksum)
                    upload_ciphertext(s3, config, ciphertext, key, started=started, checksum=checksum)
                    keys.append(key)
                duration = round((datetime.now(timezone.utc) - started).total_seconds(), 3)
                state.update({
                    "enabled": True,
                    "last_success_at": datetime.now(timezone.utc).isoformat(),
                    "consecutive_failures": 0,
                    "failure_category": None,
                    "last_encrypted_size": size,
                    "last_retention_classes": classes,
                    "last_object_key_hash": hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()[:20],
                    "last_object_basename": PurePosixPath(keys[0]).name,
                    "last_duration_seconds": duration,
                })
                result = {
                    "status": "ok",
                    "encrypted_bytes": size,
                    "retention_classes": classes,
                    "duration_seconds": duration,
                }
        # Persist only after the advisory-lock context has released its
        # session-bound PostgreSQL connection.  Committing inside that context
        # could return the locked connection to the pool before unlock.
        persist_state(db, state)
        return result
    except BackupError as exc:
        try:
            db.rollback()
        except Exception:
            pass
        _state_failure(db, state, datetime.now(timezone.utc), exc.category)
        raise
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        _state_failure(db, state, datetime.now(timezone.utc), "unexpected_failure")
        raise BackupError("unexpected_failure", "unexpected backup failure") from exc
    finally:
        db.close()
