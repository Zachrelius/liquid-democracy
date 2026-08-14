"""Dedicated Phase 98 offsite-backup process.

Modes:
  python -m offsite_backup_worker --preflight  # read-only checks, flag may be false
  python -m offsite_backup_worker --once       # one enabled backup
  python -m offsite_backup_worker              # daily UTC scheduler
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import logging
import sys

from database import SessionLocal
from offsite_backup import (
    BackupConfig,
    BackupError,
    install_signal_handlers,
    load_state,
    mark_disabled_state,
    persist_state,
    preflight,
    run_backup,
    shutdown_requested,
    wait_for_shutdown,
    parse_backup_time,
)


log = logging.getLogger("offsite_backup_worker")
RETRY_AFTER_FAILURE_SECONDS = 15 * 60


def _record_start_failure(config: BackupConfig, category: str) -> None:
    """Best-effort coarse state for failures before run_backup opens a DB."""
    db = SessionLocal()
    try:
        state = load_state(db)
        now = datetime.now(timezone.utc).isoformat()
        state.update({
            "enabled": bool(config.enabled),
            "last_attempt_at": now,
            "last_failure_at": now,
            "consecutive_failures": int(state.get("consecutive_failures", 0)) + 1,
            "failure_category": category,
        })
        persist_state(db, state)
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


def _run_once(config: BackupConfig) -> bool:
    try:
        result = run_backup(config)
    except BackupError as exc:
        # The core records failures after it opens state; validation errors
        # happen earlier and need this best-effort fallback.
        if exc.category in {"disabled", "invalid_configuration", "invalid_recipient", "wrong_instance"}:
            _record_start_failure(config, exc.category)
        log.error("offsite backup failed; category=%s", exc.category)
        return False
    log.info(
        "offsite backup verified; encrypted_bytes=%s retention_classes=%s duration_seconds=%s",
        result["encrypted_bytes"],
        ",".join(result["retention_classes"]),
        result["duration_seconds"],
    )
    return True


def _last_success_date() -> object:
    db = SessionLocal()
    try:
        value = load_state(db).get("last_success_at")
    finally:
        db.close()
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc).date()
    except ValueError:
        return None


def scheduled_loop(config: BackupConfig) -> int:
    try:
        config.validate(require_enabled=True)
    except BackupError as exc:
        _record_start_failure(config, exc.category)
        log.error("offsite backup worker configuration rejected; category=%s", exc.category)
        return 2
    hour, minute = parse_backup_time(config.time_utc)
    log.info("offsite backup worker started; schedule_utc=%02d:%02d", hour, minute)
    while not shutdown_requested():
        now = datetime.now(timezone.utc)
        due_today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now >= due_today and _last_success_date() != now.date():
            succeeded = _run_once(config)
            if wait_for_shutdown(60 if succeeded else RETRY_AFTER_FAILURE_SECONDS):
                break
            continue
        wait_seconds = max(1.0, min(60.0, (due_today - now).total_seconds()))
        if due_today <= now:
            wait_seconds = 60.0
        wait_for_shutdown(wait_seconds)
    log.info("offsite backup worker stopped")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Encrypted offsite backup worker")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--once", action="store_true", help="run one enabled backup")
    modes.add_argument("--preflight", action="store_true", help="read-only dependency/connectivity checks")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    install_signal_handlers()
    config = BackupConfig.from_settings()
    if args.preflight:
        try:
            result = preflight(config)
        except BackupError as exc:
            log.error("offsite backup preflight failed; category=%s", exc.category)
            return 2
        log.info(
            "offsite backup preflight passed; pg_dump=%s pg_restore=%s age=%s",
            result["pg_dump_version"], result["pg_restore_version"], result["age_version"],
        )
        return 0
    if args.once:
        return 0 if _run_once(config) else 2
    if not config.enabled:
        db = SessionLocal()
        try:
            mark_disabled_state(db)
        finally:
            db.close()
        log.info("offsite backup worker is intentionally disabled")
        return 0
    return scheduled_loop(config)


if __name__ == "__main__":
    sys.exit(main())
