"""Phase 97 — low-cost production monitoring and actionable alerts.

The public snapshot deliberately contains only coarse operational state. Raw
exceptions, query strings, user IDs, email addresses, and application content
never enter this module's public payload or alert bodies.
"""
from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timedelta, timezone
import hashlib
import html
import json
import logging
import os
from pathlib import Path
import re
import shutil
import threading
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

import models
from database import SessionLocal
from settings import settings


log = logging.getLogger(__name__)

REQUEST_WINDOW_SECONDS = 15 * 60
REQUEST_FAILURE_THRESHOLD = 3
EMAIL_FAILURE_THRESHOLD = 3
INTERNAL_ALERT_REMINDER_SECONDS = 12 * 60 * 60
FAILED_DELIVERY_RETRY_SECONDS = 60 * 60
STATE_KEY = "ops_monitor_alert_state"
PROPOSAL_LIFECYCLE_GRACE_SECONDS = 11 * 60

_STARTED_AT = datetime.now(timezone.utc)
_REQUEST_FAILURES: deque[dict[str, Any]] = deque(maxlen=200)
_POOL_TIMEOUTS: deque[datetime] = deque(maxlen=200)
_EMAIL_STATE: dict[str, Any] = {
    "consecutive_failures": 0,
    "last_failure_at": None,
    "last_success_at": None,
}
_STATE_LOCK = threading.Lock()

_UUID_RE = re.compile(
    r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_HEX_TOKEN_RE = re.compile(r"(?i)^[0-9a-f]{24,}$")
_DYNAMIC_PARENT_SEGMENTS = {
    "comments", "delegates", "elections", "invitations", "members",
    "messages", "organizations", "orgs", "polises", "proposals",
    "reports", "roles", "sub-orgs", "topics", "users",
}
_PLACEHOLDER_EMAIL_SUFFIXES = (
    "@demo.example", "@test.example", "@example.com", ".invalid", ".local",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def sanitize_path(path: str) -> str:
    """Remove identifiers/tokens while preserving the route's useful shape."""
    clean = (path or "/").split("?", 1)[0]
    parts: list[str] = []
    previous: Optional[str] = None
    for part in clean.split("/"):
        if not part:
            continue
        if previous in _DYNAMIC_PARENT_SEGMENTS:
            parts.append(":id")
        elif len(part) > 48:
            parts.append(":token")
        elif part.isdigit() or _UUID_RE.fullmatch(part) or _HEX_TOKEN_RE.fullmatch(part):
            parts.append(":id")
        else:
            parts.append(part[:64])
        previous = part
    return "/" + "/".join(parts)


def reset_runtime_state_for_tests() -> None:
    """Test-only helper; production never calls this."""
    with _STATE_LOCK:
        _REQUEST_FAILURES.clear()
        _POOL_TIMEOUTS.clear()
        _EMAIL_STATE.update({
            "consecutive_failures": 0,
            "last_failure_at": None,
            "last_success_at": None,
        })


def record_http_failure(
    *, method: str, path: str, request_id: str, status_code: int,
    now: Optional[datetime] = None,
) -> None:
    if status_code < 500 or (path or "").startswith("/api/health"):
        return
    observed_at = now or _utcnow()
    with _STATE_LOCK:
        _REQUEST_FAILURES.append({
            "observed_at": observed_at,
            "method": (method or "UNKNOWN")[:12].upper(),
            "path": sanitize_path(path),
            "request_id": (request_id or "")[:64],
            "status_code": int(status_code),
        })


def record_pool_timeout(*, now: Optional[datetime] = None) -> None:
    """Record occurrence only; never retain route/user/SQL details."""
    with _STATE_LOCK:
        _POOL_TIMEOUTS.append(now or _utcnow())


def _database_pool_component(now: datetime) -> dict[str, Any]:
    from database import pool_snapshot
    counters = pool_snapshot()
    cutoff = now.timestamp() - REQUEST_WINDOW_SECONDS
    with _STATE_LOCK:
        while _POOL_TIMEOUTS and _POOL_TIMEOUTS[0].timestamp() < cutoff:
            _POOL_TIMEOUTS.popleft()
        timeout_count = len(_POOL_TIMEOUTS)
    if not counters["supported"]:
        return {
            "status": "unsupported",
            **counters,
            "timeout_count_15m": timeout_count,
            "guidance": "Pool counters are unavailable for this database pool implementation.",
        }
    utilization = float(counters["utilization_percent"] or 0)
    status = "error" if timeout_count or utilization >= 80 else "warning" if utilization >= 60 else "ok"
    return {
        "status": status,
        **counters,
        "timeout_count_15m": timeout_count,
        "guidance": (
            "Inspect request fan-out, slow requests, and pool checkout duration before raising pool size."
            if status in {"warning", "error"} else "No action required."
        ),
    }


def record_email_result(success: bool, *, now: Optional[datetime] = None) -> None:
    observed_at = now or _utcnow()
    with _STATE_LOCK:
        if success:
            _EMAIL_STATE["consecutive_failures"] = 0
            _EMAIL_STATE["last_success_at"] = observed_at
        else:
            _EMAIL_STATE["consecutive_failures"] += 1
            _EMAIL_STATE["last_failure_at"] = observed_at


def _request_component(now: datetime) -> dict[str, Any]:
    cutoff = now.timestamp() - REQUEST_WINDOW_SECONDS
    with _STATE_LOCK:
        while _REQUEST_FAILURES and _REQUEST_FAILURES[0]["observed_at"].timestamp() < cutoff:
            _REQUEST_FAILURES.popleft()
        recent = list(_REQUEST_FAILURES)
    count = len(recent)
    return {
        "status": "error" if count >= REQUEST_FAILURE_THRESHOLD else "ok",
        "count_15m": count,
        "threshold": REQUEST_FAILURE_THRESHOLD,
        "samples": [
            {
                "method": row["method"],
                "path": row["path"],
                "request_id": row["request_id"],
                "status_code": row["status_code"],
            }
            for row in recent[-3:]
        ],
        "guidance": "Search Railway backend logs for the listed request IDs.",
    }


def _email_component() -> dict[str, Any]:
    with _STATE_LOCK:
        state = dict(_EMAIL_STATE)
    failures = int(state["consecutive_failures"])
    return {
        "status": "error" if failures >= EMAIL_FAILURE_THRESHOLD else "ok",
        "consecutive_failures": failures,
        "threshold": EMAIL_FAILURE_THRESHOLD,
        "last_failure_at": (
            state["last_failure_at"].isoformat() if state["last_failure_at"] else None
        ),
        "last_success_at": (
            state["last_success_at"].isoformat() if state["last_success_at"] else None
        ),
        "guidance": "Check Resend delivery logs, quota, domain status, and Railway email configuration.",
    }


def _worker_component(
    *, name: str, last_success: Any, ticks_since_success: int,
    now: datetime, stale_after_seconds: int, failure_threshold: int,
    disabled: bool = False,
) -> dict[str, Any]:
    if disabled:
        return {
            "status": "disabled",
            "last_successful_tick_at": None,
            "ticks_since_last_success": 0,
            "stale_after_seconds": stale_after_seconds,
            "guidance": f"{name} is intentionally disabled by configuration.",
        }
    last = _as_utc(last_success)
    age = int((now - last).total_seconds()) if last else None
    startup_age = int((now - _STARTED_AT).total_seconds())
    beyond_grace = startup_age >= settings.ops_monitor_startup_grace_seconds
    failed = int(ticks_since_success or 0) >= failure_threshold
    stale = age is not None and age > stale_after_seconds
    missing = last is None and beyond_grace
    status = "error" if (failed or stale or missing) else "ok"
    return {
        "status": status,
        "last_successful_tick_at": last.isoformat() if last else None,
        "age_seconds": age,
        "ticks_since_last_success": int(ticks_since_success or 0),
        "stale_after_seconds": stale_after_seconds,
        "guidance": f"Check Railway backend logs and the {name} process heartbeat.",
    }


def _offsite_backup_component(db: Session, now: datetime) -> dict[str, Any]:
    """Render versioned backup state without destination/object identifiers."""
    stale_after = settings.offsite_backup_stale_after_seconds
    if not settings.offsite_backup_enabled:
        return {
            "status": "disabled",
            "last_success_at": None,
            "age_seconds": None,
            "stale_after_seconds": stale_after,
            "guidance": "Encrypted offsite backups are intentionally disabled by configuration.",
        }
    try:
        row = db.get(models.PlatformSetting, "offsite_backup_state_v1")
        state = dict(row.value) if row is not None and isinstance(row.value, dict) else {}
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        state = {}
    def safe_int(value: Any) -> int:
        try:
            return max(0, min(int(value), 9_223_372_036_854_775_807))
        except (TypeError, ValueError, OverflowError):
            return 0

    def safe_float(value: Any) -> Optional[float]:
        try:
            result = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return round(result, 3) if 0 <= result <= 7 * 24 * 60 * 60 else None

    safe_categories = {
        "archive_failure", "concurrent_run", "database_metadata_failure",
        "disabled", "encryption_failure", "insufficient_space",
        "interrupted", "invalid_configuration", "invalid_recipient",
        "lock_unavailable", "object_store_unavailable", "subprocess_failure",
        "toolchain_incompatible", "toolchain_unavailable", "unexpected_failure",
        "unsafe_upload_tree", "upload_failure", "upload_tree_changed",
        "uploads_unavailable", "verification_failure", "wrong_instance",
    }
    consecutive_failures = safe_int(state.get("consecutive_failures"))
    category_value = state.get("failure_category")
    safe_category = category_value if category_value in safe_categories else (
        "unexpected_failure" if category_value else None
    )
    raw_classes = state.get("last_retention_classes")
    safe_classes = (
        [item for item in raw_classes if item in {"daily", "weekly", "monthly"}]
        if isinstance(raw_classes, list) else None
    )
    encrypted_size = safe_int(state.get("last_encrypted_size")) or None
    last_success = _as_utc(state.get("last_success_at"))
    last_failure = _as_utc(state.get("last_failure_at"))
    if last_success is not None and last_success > now + timedelta(minutes=5):
        last_success = None
    if last_failure is not None and last_failure > now + timedelta(minutes=5):
        last_failure = None
    age = int((now - last_success).total_seconds()) if last_success else None
    startup_age = int((now - _STARTED_AT).total_seconds())
    within_grace = startup_age < settings.ops_monitor_startup_grace_seconds
    has_failure = consecutive_failures > 0
    failure_after_success = last_failure is not None and (
        last_success is None or last_failure > last_success
    )
    stale = age is not None and age > stale_after
    missing = last_success is None
    if has_failure or failure_after_success or stale or (missing and not within_grace):
        status = "error"
    elif missing:
        status = "warning"
    else:
        status = "ok"
    return {
        "status": status,
        "last_success_at": last_success.isoformat() if last_success else None,
        "last_failure_at": last_failure.isoformat() if last_failure else None,
        "age_seconds": age,
        "stale_after_seconds": stale_after,
        "consecutive_failures": consecutive_failures,
        "last_encrypted_size": encrypted_size if last_success else None,
        "last_retention_classes": safe_classes if last_success else None,
        "last_duration_seconds": safe_float(state.get("last_duration_seconds")) if last_success else None,
        "failure_category": safe_category if status == "error" else None,
        "guidance": (
            "Run the offsite backup preflight and inspect sanitized backend worker logs."
            if status in {"warning", "error"}
            else "No action required."
        ),
    }


def _proposal_lifecycle_component(db: Session, now: datetime) -> dict[str, Any]:
    """Public-safe overdue state for the Phase 102 scheduler."""
    enabled = bool(settings.proposal_schedule_automation_enabled)
    if not enabled:
        return {
            "status": "warning",
            "automation_enabled": False,
            "overdue_count": 0,
            "oldest_overdue_age_seconds": None,
            "grace_seconds": PROPOSAL_LIFECYCLE_GRACE_SECONDS,
            "guidance": "Scheduled proposal automation is rollout-disabled; complete reconciliation before enabling it.",
        }
    now_naive = now.astimezone(timezone.utc).replace(tzinfo=None)
    threshold = now_naive - timedelta(seconds=PROPOSAL_LIFECYCLE_GRACE_SECONDS)
    try:
        ordinary = db.query(models.Proposal).filter(
            models.Proposal.status == "deliberation",
            models.Proposal.is_cosign_gated.is_(False),
            models.Proposal.deliberation_end.is_not(None),
            models.Proposal.deliberation_end <= threshold,
        ).all()
        voting = db.query(models.Proposal).filter(
            models.Proposal.status == "voting",
            models.Proposal.voting_end.is_not(None),
            models.Proposal.voting_end <= threshold,
        ).all()
        deadlines = [p.deliberation_end for p in ordinary] + [p.voting_end for p in voting]
        unscheduled = db.query(models.Proposal).filter(
            models.Proposal.status == "deliberation",
            models.Proposal.is_cosign_gated.is_(False),
            models.Proposal.deliberation_end.is_(None),
        ).count()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return {
            "status": "error",
            "automation_enabled": True,
            "overdue_count": None,
            "oldest_overdue_age_seconds": None,
            "grace_seconds": PROPOSAL_LIFECYCLE_GRACE_SECONDS,
            "guidance": "Check Railway backend logs and proposal lifecycle database access.",
        }
    oldest_age = (
        max(0, int((now_naive - min(deadlines)).total_seconds()))
        if deadlines else None
    )
    return {
        "status": "error" if deadlines else "ok",
        "automation_enabled": True,
        "overdue_count": len(deadlines),
        "ordinary_deliberation_overdue_count": len(ordinary),
        "voting_overdue_count": len(voting),
        "unscheduled_active_deliberation_count": int(unscheduled),
        "oldest_overdue_age_seconds": oldest_age,
        "grace_seconds": PROPOSAL_LIFECYCLE_GRACE_SECONDS,
        "guidance": (
            "Check decision-worker logs, invalid proposal schedules, and the lifecycle feature-gate state."
            if deadlines else "No action required."
        ),
    }


def _capacity_component(
    *, used_bytes: Optional[int], capacity_bytes: Optional[int], guidance: str,
    warning_percent: float = 85, error_percent: float = 95,
) -> dict[str, Any]:
    if used_bytes is None or not capacity_bytes:
        return {
            "status": "not_applicable",
            "used_bytes": used_bytes,
            "capacity_bytes": capacity_bytes,
            "percent_used": None,
            "guidance": guidance,
        }
    percent = round(100 * used_bytes / capacity_bytes, 2)
    status = (
        "error" if percent >= error_percent
        else "warning" if percent >= warning_percent
        else "ok"
    )
    return {
        "status": status,
        "used_bytes": int(used_bytes),
        "capacity_bytes": int(capacity_bytes),
        "percent_used": percent,
        "guidance": guidance,
    }


def active_admin_recipients(db: Session) -> list[str]:
    explicit = settings.ops_alert_email.strip().lower()
    if explicit:
        return [explicit]
    rows = db.query(models.User.email).filter(
        models.User.is_admin.is_(True),
        models.User.is_active.is_(True),
        models.User.email_verified.is_(True),
        models.User.email.is_not(None),
    ).all()
    return sorted({
        normalized
        for (email,) in rows
        if email and (normalized := str(email).strip().lower())
        and not normalized.endswith(_PLACEHOLDER_EMAIL_SUFFIXES)
    })


def build_snapshot(
    db: Session, *, now: Optional[datetime] = None,
    upload_dir: Optional[Path] = None,
    force_storage_check: bool = False,
) -> dict[str, Any]:
    """Build the coarse, public-safe monitoring snapshot."""
    now = now or _utcnow()
    components: dict[str, dict[str, Any]] = {}

    database_ok = True
    try:
        db.execute(text("SELECT 1"))
        components["database"] = {
            "status": "ok",
            "guidance": "No action required.",
        }
    except Exception:
        database_ok = False
        try:
            db.rollback()
        except Exception:
            pass
        components["database"] = {
            "status": "error",
            "guidance": "Check the Railway Postgres service and backend database logs.",
        }

    db_used: Optional[int] = None
    if database_ok and db.bind is not None and db.bind.dialect.name == "postgresql":
        try:
            db_used = int(db.execute(text("SELECT pg_database_size(current_database())")).scalar_one())
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
    components["database_capacity"] = _capacity_component(
        used_bytes=db_used,
        capacity_bytes=settings.ops_database_capacity_bytes if db_used is not None else None,
        guidance="Review database growth and resize the Railway Postgres volume before 90%.",
        warning_percent=80,
        error_percent=90,
    )

    components["http_5xx"] = _request_component(now)
    components["database_pool"] = _database_pool_component(now)
    components["email_delivery"] = _email_component()

    try:
        from digest_scheduler import get_scheduler_state
        digest_state = get_scheduler_state()
    except Exception:
        digest_state = {"last_successful_tick_at": None, "ticks_since_last_success": 2}
    components["digest_scheduler"] = _worker_component(
        name="digest scheduler",
        last_success=digest_state.get("last_successful_tick_at"),
        ticks_since_success=int(digest_state.get("ticks_since_last_success", 0)),
        now=now,
        stale_after_seconds=settings.ops_digest_stale_seconds,
        failure_threshold=2,
        disabled=(os.environ.get("DISABLE_DIGEST_SCHEDULER", "").strip().lower() in {"1", "true", "yes"}),
    )

    sm_state: dict[str, Any] = {}
    if database_ok:
        try:
            row = db.get(models.PlatformSetting, "sm_worker_heartbeat")
            if row is not None and isinstance(row.value, dict):
                sm_state = row.value
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
    sm_stale_seconds = max(
        settings.ops_decision_worker_min_stale_seconds,
        3 * settings.sustained_majority_check_interval_seconds,
    )
    components["decision_worker"] = _worker_component(
        name="decision worker",
        last_success=sm_state.get("last_successful_tick_at"),
        ticks_since_success=int(sm_state.get("ticks_since_last_success", 0)),
        now=now,
        stale_after_seconds=sm_stale_seconds,
        failure_threshold=3,
        disabled=settings.sustained_majority_worker_disable,
    )

    components["proposal_lifecycle"] = _proposal_lifecycle_component(db, now)

    components["offsite_backup"] = _offsite_backup_component(db, now)

    upload_dir = Path(upload_dir or os.environ.get("UPLOAD_DIR") or "/data/uploads")
    should_check_storage = force_storage_check or str(upload_dir).replace("\\", "/").startswith("/data/")
    upload_used: Optional[int] = None
    upload_capacity: Optional[int] = None
    if should_check_storage:
        try:
            usage = shutil.disk_usage(upload_dir)
            upload_used = int(usage.used)
            upload_capacity = int(usage.total)
        except Exception:
            components["upload_capacity"] = {
                "status": "error",
                "used_bytes": None,
                "capacity_bytes": None,
                "percent_used": None,
                "guidance": "Check that the Railway uploads volume is mounted at /data/uploads.",
            }
    if "upload_capacity" not in components:
        components["upload_capacity"] = _capacity_component(
            used_bytes=upload_used,
            capacity_bytes=upload_capacity,
            guidance="Review upload growth and resize or archive before 95%.",
        )

    try:
        recipient_count = len(active_admin_recipients(db)) if database_ok else 0
    except Exception:
        recipient_count = 0
        try:
            db.rollback()
        except Exception:
            pass
    components["alert_delivery"] = {
        "status": "ok" if recipient_count else "error",
        "active_verified_admin_recipients": recipient_count,
        "guidance": "Keep at least one active, verified platform-admin email available for operational alerts.",
    }

    issues = [
        {
            "component": name,
            "severity": component["status"],
            "guidance": component.get("guidance"),
        }
        for name, component in components.items()
        if component.get("status") in {"warning", "error"}
    ]
    status = "error" if any(i["severity"] == "error" for i in issues) else "warning" if issues else "ok"
    return {
        "status": status,
        "checked_at": now.isoformat(),
        "components": components,
        "issues": issues,
    }


def _fingerprint(snapshot: dict[str, Any]) -> str:
    material = sorted(
        (item["component"], item["severity"])
        for item in snapshot.get("issues", [])
    )
    return hashlib.sha256(json.dumps(material).encode("utf-8")).hexdigest()[:20]


def _parse_state_time(value: Any) -> Optional[datetime]:
    return _as_utc(value)


def _render_alert_html(snapshot: dict[str, Any], *, recovery: bool) -> str:
    when = html.escape(str(snapshot.get("checked_at") or _utcnow().isoformat()))
    monitor_url = html.escape(settings.base_url.rstrip("/") + "/api/health/monitor")
    if recovery:
        return (
            "<h2>Liquid Democracy production recovered</h2>"
            f"<p>All monitored components were healthy at <strong>{when}</strong>.</p>"
            f'<p><a href="{monitor_url}">View the live monitor</a>.</p>'
        )
    rows: list[str] = []
    for issue in snapshot.get("issues", []):
        component = html.escape(str(issue.get("component", "unknown")))
        severity = html.escape(str(issue.get("severity", "unknown")))
        guidance = html.escape(str(issue.get("guidance", "Check production logs.")))
        rows.append(f"<li><strong>{component}</strong> ({severity}): {guidance}</li>")
    samples = snapshot.get("components", {}).get("http_5xx", {}).get("samples", [])
    sample_html = ""
    if samples:
        sample_html = "<h3>Recent sanitized request samples</h3><ul>" + "".join(
            "<li>"
            + html.escape(
                f"{s.get('method')} {s.get('path')} — "
                f"{s.get('status_code')} — request {s.get('request_id')}"
            )
            + "</li>"
            for s in samples
        ) + "</ul>"
    return (
        "<h2>Liquid Democracy production alert</h2>"
        f"<p>Monitoring detected an incident at <strong>{when}</strong>.</p>"
        f"<ul>{''.join(rows)}</ul>{sample_html}"
        "<p>First response: open Railway backend logs, confirm database/service status, "
        "and use the request IDs above when present. Monitoring does not make automatic changes.</p>"
        f'<p><a href="{monitor_url}">View the live monitor</a>.</p>'
    )


async def _send_to_admins(db: Session, subject: str, body: str) -> bool:
    recipients = active_admin_recipients(db)
    if not recipients:
        log.error("ops monitoring: no active verified platform-admin alert recipients")
        return False
    from email_service import send_email
    results = [await send_email(recipient, subject, body) for recipient in recipients]
    return all(results)


async def send_test_alert(db: Session) -> tuple[bool, int]:
    recipients = active_admin_recipients(db)
    if not recipients:
        return False, 0
    body = (
        "<h2>Liquid Democracy monitoring test</h2>"
        "<p>This is a safe delivery test. No production incident was created.</p>"
        f'<p><a href="{html.escape(settings.base_url.rstrip("/") + "/api/health/monitor")}">'
        "View the live monitor</a>.</p>"
    )
    from email_service import send_email
    results = [
        await send_email(recipient, "[Liquid Democracy] Monitoring test", body)
        for recipient in recipients
    ]
    return all(results), len(recipients)


async def monitor_once(db: Session, *, now: Optional[datetime] = None) -> dict[str, Any]:
    now = now or _utcnow()
    snapshot = build_snapshot(db, now=now)
    row = db.get(models.PlatformSetting, STATE_KEY)
    state = dict(row.value) if row is not None and isinstance(row.value, dict) else {}
    active_fingerprint = state.get("active_fingerprint")
    issues = snapshot.get("issues", [])

    if not issues:
        if active_fingerprint:
            delivered = await _send_to_admins(
                db,
                "[Liquid Democracy] Production recovered",
                _render_alert_html(snapshot, recovery=True),
            )
            if delivered:
                state = {
                    "active_fingerprint": None,
                    "recovered_at": now.isoformat(),
                    "last_delivery_succeeded": True,
                }
        else:
            return snapshot
    else:
        fingerprint = _fingerprint(snapshot)
        last_attempt = _parse_state_time(state.get("last_attempt_at"))
        last_sent = _parse_state_time(state.get("last_sent_at"))
        previous_delivery_succeeded = bool(state.get("last_delivery_succeeded"))
        changed = fingerprint != active_fingerprint
        retry_due = (
            not previous_delivery_succeeded
            and (last_attempt is None or (now - last_attempt).total_seconds() >= FAILED_DELIVERY_RETRY_SECONDS)
        )
        reminder_due = (
            previous_delivery_succeeded
            and last_sent is not None
            and (now - last_sent).total_seconds() >= INTERNAL_ALERT_REMINDER_SECONDS
        )
        if changed or retry_due or reminder_due:
            delivered = await _send_to_admins(
                db,
                "[Liquid Democracy] Production monitoring alert",
                _render_alert_html(snapshot, recovery=False),
            )
            state = {
                "active_fingerprint": fingerprint,
                "opened_at": state.get("opened_at") if not changed else now.isoformat(),
                "last_attempt_at": now.isoformat(),
                "last_sent_at": now.isoformat() if delivered else state.get("last_sent_at"),
                "last_delivery_succeeded": delivered,
                "components": [item["component"] for item in issues],
            }
        else:
            return snapshot

    if row is None:
        row = models.PlatformSetting(key=STATE_KEY, value=state)
        db.add(row)
    else:
        row.value = state
    db.commit()
    return snapshot


def is_disabled() -> bool:
    return not settings.ops_monitor_enabled


async def monitor_loop() -> None:
    log.info(
        "ops monitoring loop starting; interval=%ss enabled=%s",
        settings.ops_monitor_interval_seconds,
        settings.ops_monitor_enabled,
    )
    await asyncio.sleep(settings.ops_monitor_initial_delay_seconds)
    while True:
        if not is_disabled():
            db = SessionLocal()
            try:
                await monitor_once(db)
            except Exception:
                log.exception("ops monitoring tick failed; application remains available")
                try:
                    db.rollback()
                except Exception:
                    pass
            finally:
                db.close()
        try:
            await asyncio.sleep(settings.ops_monitor_interval_seconds)
        except asyncio.CancelledError:
            log.info("ops monitoring loop cancelled; exiting")
            return
