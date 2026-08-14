"""Verify or restore a Phase 98 offsite backup into disposable resources only.

This operator CLI is intentionally disconnected from FastAPI and startup.  It
requires separate restore credentials, an offline age identity file, and an
exact typed confirmation naming a clearly disposable PostgreSQL target.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tarfile
import tempfile
from typing import Any, Optional
from urllib.parse import urlparse

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from offsite_backup import (  # noqa: E402
    ARTIFACT_FORMAT_VERSION,
    BackupError,
    _postgres_env,
    _safe_child,
    _s3_client,
    sha256_file,
    tool_versions,
)
from settings import settings  # noqa: E402


_DISPOSABLE_MARKERS = ("disposable", "rehearsal", "restore", "scratch", "temp", "test")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def required_confirmation(target_url: str) -> str:
    target = make_url(target_url)
    return f"RESTORE DISPOSABLE DATABASE {target.database} ON {target.host}"


def validate_target(target_url: str, confirmation: str, production_url: str) -> None:
    try:
        target = make_url(target_url)
    except Exception as exc:
        raise BackupError("unsafe_restore_target", "target database URL is invalid") from exc
    if not target.drivername.startswith("postgresql") or not target.host or not target.database:
        raise BackupError("unsafe_restore_target", "target must be an explicit PostgreSQL host and database")
    routing_keys = {
        "host", "hostaddr", "port", "dbname", "database", "service",
        "servicefile", "passfile",
    }
    if routing_keys.intersection(str(key).lower() for key in target.query):
        raise BackupError("unsafe_restore_target", "libpq routing overrides are forbidden")
    if confirmation != required_confirmation(target_url):
        raise BackupError("unsafe_restore_target", "typed confirmation does not name the disposable target")
    database_lower = str(target.database).lower()
    if not any(marker in database_lower for marker in _DISPOSABLE_MARKERS):
        raise BackupError("unsafe_restore_target", "target database name is not clearly disposable")
    if any(marker in database_lower for marker in ("production", "prod")):
        raise BackupError("unsafe_restore_target", "production-like target names are forbidden")
    try:
        production = make_url(production_url)
    except Exception:
        production = None
    configured_host = os.environ.get("OFFSITE_PRODUCTION_DATABASE_HOST", "").strip().lower()
    configured_name = os.environ.get("OFFSITE_PRODUCTION_DATABASE_NAME", "").strip().lower()
    if not configured_host or not configured_name:
        raise BackupError(
            "invalid_configuration",
            "explicit production database host and name safety inputs are required",
        )
    target_host = str(target.host).lower()
    target_name = str(target.database).lower()
    if target_host == configured_host or target_name == configured_name:
        raise BackupError("unsafe_restore_target", "configured production host or name is forbidden")
    if production is not None and production.drivername.startswith("postgresql"):
        if target.render_as_string(hide_password=False) == production.render_as_string(hide_password=False):
            raise BackupError("unsafe_restore_target", "current DATABASE_URL is forbidden")
        if target_host == str(production.host).lower() or target_name == str(production.database).lower():
            raise BackupError("unsafe_restore_target", "production database host or name is forbidden")


def restore_config_from_environment():
    """Build a client config from restore-only credentials (never app writes)."""
    from dataclasses import replace
    from offsite_backup import BackupConfig

    base = BackupConfig.from_settings()
    values = {
        "s3_endpoint": os.environ.get("OFFSITE_RESTORE_S3_ENDPOINT", "").strip(),
        "s3_region": os.environ.get("OFFSITE_RESTORE_S3_REGION", "auto").strip(),
        "bucket": os.environ.get("OFFSITE_RESTORE_BUCKET", "").strip(),
        "access_key_id": os.environ.get("OFFSITE_RESTORE_ACCESS_KEY_ID", "").strip(),
        "secret_access_key": os.environ.get("OFFSITE_RESTORE_SECRET_ACCESS_KEY", "").strip(),
    }
    if not all(values.values()):
        raise BackupError("invalid_configuration", "restore-only object-store credentials are required")
    if any(
        marker in values[field].lower()
        for field in ("access_key_id", "secret_access_key")
        for marker in ("change-me", "placeholder", "replace-me", "example-secret")
    ):
        raise BackupError("invalid_configuration", "placeholder restore credentials are forbidden")
    endpoint = urlparse(values["s3_endpoint"])
    if endpoint.scheme != "https" or not endpoint.hostname:
        raise BackupError("invalid_configuration", "restore S3 endpoint must be HTTPS")
    if not re.fullmatch(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", values["bucket"]):
        raise BackupError("invalid_configuration", "restore bucket name is invalid")
    # No config.validate call: restores do not possess or need the production
    # age recipient, and their S3 token should be read-only.
    return replace(base, enabled=False, **values)


def _download_ciphertext(client: Any, bucket: str, key: str, destination: Path) -> str:
    try:
        head = client.head_object(Bucket=bucket, Key=key)
        metadata = head.get("Metadata") or {}
        expected = str(metadata.get("ciphertext-sha256", ""))
        if not _SHA256_RE.fullmatch(expected):
            raise BackupError("verification_failure", "ciphertext checksum metadata is missing")
        response = client.get_object(Bucket=bucket, Key=key)
        with destination.open("wb") as output:
            shutil.copyfileobj(response["Body"], output, length=1024 * 1024)
        if destination.stat().st_size != int(head.get("ContentLength", -1)):
            raise BackupError("verification_failure", "downloaded ciphertext size mismatch")
        if sha256_file(destination) != expected:
            raise BackupError("verification_failure", "downloaded ciphertext checksum mismatch")
        return expected
    except BackupError:
        raise
    except Exception as exc:
        raise BackupError("download_failure", "ciphertext download failed") from exc


def _extract_bundle(bundle: Path, destination: Path) -> dict[str, Any]:
    allowed = {"manifest.json", "database.dump", "uploads.tar.gz"}
    with tarfile.open(bundle, "r:") as archive:
        members = archive.getmembers()
        if {member.name for member in members} != allowed or len(members) != 3:
            raise BackupError("verification_failure", "unexpected encrypted bundle members")
        for member in members:
            if not member.isfile() or member.issym() or member.islnk():
                raise BackupError("verification_failure", "unsafe encrypted bundle member")
            source = archive.extractfile(member)
            if source is None:
                raise BackupError("verification_failure", "bundle member is unreadable")
            with (destination / member.name).open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
    try:
        manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    except Exception as exc:
        raise BackupError("verification_failure", "manifest is invalid") from exc
    if manifest.get("artifact_format_version") != ARTIFACT_FORMAT_VERSION:
        raise BackupError("verification_failure", "unsupported artifact format")
    if manifest.get("environment") != "production":
        raise BackupError("verification_failure", "unexpected artifact environment")
    alembic = manifest.get("alembic")
    if (
        not isinstance(alembic, dict)
        or not alembic.get("current_revision")
        or alembic.get("current_revision") != alembic.get("head_revision")
    ):
        raise BackupError("verification_failure", "backup database was not at Alembic head")
    manifest_members = manifest.get("members")
    if not isinstance(manifest_members, dict):
        raise BackupError("verification_failure", "manifest member map is invalid")
    for name in ("database.dump", "uploads.tar.gz"):
        detail = manifest_members.get(name)
        if not isinstance(detail, dict) or not _SHA256_RE.fullmatch(str(detail.get("sha256", ""))):
            raise BackupError("verification_failure", "manifest checksum is invalid")
        path = destination / name
        if path.stat().st_size != int(detail.get("bytes", -1)) or sha256_file(path) != detail["sha256"]:
            raise BackupError("verification_failure", "artifact member did not verify")
    return manifest


def _assert_empty_database(target_url: str) -> None:
    engine = create_engine(target_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            names = connection.execute(text(
                "SELECT table_schema || '.' || table_name "
                "FROM information_schema.tables "
                "WHERE table_type = 'BASE TABLE' "
                "AND table_schema NOT IN ('pg_catalog', 'information_schema')"
            )).scalars().all()
        if names:
            raise BackupError("unsafe_restore_target", "target database is not empty")
    finally:
        engine.dispose()


def _restore_database(target_url: str, dump: Path) -> None:
    target = make_url(target_url)
    versions = tool_versions()
    if "18" not in versions["pg_restore"]:
        raise BackupError("toolchain_incompatible", "PostgreSQL 18 pg_restore is required")
    engine = create_engine(target_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            server_version = str(connection.execute(text("SHOW server_version")).scalar_one())
        match = re.search(r"(\d+)", server_version)
        if not match or int(match.group(1)) != 18:
            raise BackupError("toolchain_incompatible", "restore target must run PostgreSQL 18")
    finally:
        engine.dispose()
    _safe_child([
        "pg_restore", "--exit-on-error", "--no-owner", "--no-privileges",
        "--dbname", str(target.database), str(dump),
    ], env=_postgres_env(target_url))


def _validate_restored_database(target_url: str, manifest: dict[str, Any]) -> None:
    engine = create_engine(target_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            revisions = connection.execute(text("SELECT version_num FROM alembic_version ORDER BY version_num")).scalars().all()
            current = ",".join(str(item) for item in revisions)
            expected_revision = str(manifest.get("alembic", {}).get("current_revision", ""))
            if current != expected_revision:
                raise BackupError("verification_failure", "restored Alembic revision mismatch")
            expected_counts = manifest.get("representative_table_row_counts", {})
            if not isinstance(expected_counts, dict):
                raise BackupError("verification_failure", "manifest structural counts are invalid")
            available = set(inspect(connection).get_table_names())
            for table_name, expected in expected_counts.items():
                if table_name not in available or table_name not in {
                    "users", "organizations", "org_memberships", "proposals", "votes",
                    "delegations", "uploaded_files",
                }:
                    raise BackupError("verification_failure", "manifest structural table is invalid")
                actual = int(connection.execute(text(f'SELECT count(*) FROM "{table_name}"')).scalar_one())
                if actual != int(expected):
                    raise BackupError("verification_failure", "restored structural count mismatch")
    finally:
        engine.dispose()


def _validate_empty_upload_destination(destination: Path) -> None:
    if not destination.is_dir() or any(destination.iterdir()):
        raise BackupError("unsafe_restore_target", "uploads destination must be empty")


def _extract_uploads(archive_path: Path, destination: Path) -> tuple[int, int]:
    _validate_empty_upload_destination(destination)
    resolved_destination = destination.resolve()
    file_count = 0
    aggregate_bytes = 0
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            if "\\" in member.name:
                raise BackupError("verification_failure", "backslashes are forbidden in uploads archive members")
            parts = PurePosixPath(member.name).parts
            if not parts or parts[0] != "uploads" or ".." in parts or member.issym() or member.islnk():
                raise BackupError("verification_failure", "unsafe uploads archive member")
            target = resolved_destination.joinpath(*parts[1:]).resolve(strict=False)
            if resolved_destination != target and resolved_destination not in target.parents:
                raise BackupError("verification_failure", "uploads archive escapes target")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise BackupError("verification_failure", "upload member is unreadable")
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
                descriptor = os.open(target, flags, stat.S_IMODE(member.mode) or 0o600)
                with os.fdopen(descriptor, "wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                file_count += 1
                aggregate_bytes += int(member.size)
            else:
                raise BackupError("verification_failure", "special uploads member is forbidden")
    return file_count, aggregate_bytes


def restore(
    *, object_key: str, identity: Path, target_url: str, confirmation: str,
    uploads_destination: Path, verify_only: bool = False, keep_temporary: bool = False,
    client: Any = None,
) -> dict[str, Any]:
    validate_target(target_url, confirmation, settings.database_url)
    if not identity.is_file():
        raise BackupError("identity_unavailable", "age identity file is unavailable")
    if not object_key or object_key.startswith("/") or ".." in PurePosixPath(object_key).parts:
        raise BackupError("invalid_configuration", "object key is invalid")
    config = restore_config_from_environment()
    temporary = Path(tempfile.mkdtemp(prefix="offsite-restore-"))
    os.chmod(temporary, 0o700)
    try:
        ciphertext = temporary / "backup.tar.age"
        bundle = temporary / "backup.tar"
        checksum = _download_ciphertext(client or _s3_client(config), config.bucket, object_key, ciphertext)
        _safe_child(["age", "--decrypt", "-i", str(identity), "-o", str(bundle), str(ciphertext)])
        manifest = _extract_bundle(bundle, temporary)
        if not verify_only:
            # All filesystem safety gates happen before pg_restore mutates the
            # disposable database.
            _validate_empty_upload_destination(uploads_destination)
            _assert_empty_database(target_url)
            _restore_database(target_url, temporary / "database.dump")
            _validate_restored_database(target_url, manifest)
            extracted_count, extracted_bytes = _extract_uploads(
                temporary / "uploads.tar.gz", uploads_destination,
            )
            if extracted_count != int(manifest.get("uploads_file_count", -1)):
                raise BackupError("verification_failure", "restored upload file count mismatch")
            if extracted_bytes != int(manifest.get("uploads_aggregate_bytes", -1)):
                raise BackupError("verification_failure", "restored upload byte count mismatch")
        return {
            "status": "verified" if verify_only else "restored",
            "ciphertext_sha256": checksum,
            "artifact_format_version": manifest["artifact_format_version"],
            "uploads_file_count": manifest.get("uploads_file_count"),
            "temporary_directory": str(temporary) if keep_temporary else None,
        }
    except BackupError:
        raise
    except Exception as exc:
        raise BackupError("unexpected_failure", "unexpected restore failure") from exc
    finally:
        if not keep_temporary:
            try:
                shutil.rmtree(temporary)
            except OSError as exc:
                raise BackupError(
                    "cleanup_failure",
                    "temporary decrypted restore material could not be removed",
                ) from exc


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Verify/restore an encrypted offsite backup")
    parser.add_argument("--object-key", required=True)
    parser.add_argument("--identity", required=True, type=Path)
    parser.add_argument("--target-database-url", default=os.environ.get("OFFSITE_RESTORE_TARGET_DATABASE_URL", ""))
    parser.add_argument("--confirm", required=True)
    parser.add_argument("--uploads-destination", required=True, type=Path)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--keep-temporary", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = restore(
            object_key=args.object_key,
            identity=args.identity,
            target_url=args.target_database_url,
            confirmation=args.confirm,
            uploads_destination=args.uploads_destination,
            verify_only=args.verify_only,
            keep_temporary=args.keep_temporary,
        )
    except BackupError as exc:
        print(f"restore failed: category={exc.category}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
