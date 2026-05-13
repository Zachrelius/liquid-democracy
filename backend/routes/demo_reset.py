"""Phase 23.2 B0 — token-gated demo reset trigger.

Exposes ``POST /api/demo/trigger-reset`` so the Code team can trigger a
demo-org reset autonomously without going through the admin-auth path on
``/api/admin/demo/reset`` (which requires a platform-admin user).

Token comes from the ``DEMO_RESET_TRIGGER_TOKEN`` env var (set in Railway
production env + local ``.env``). The endpoint:

- 503 if the env var is unset (this environment isn't configured for the
  trigger).
- 401 if the ``Authorization: Bearer <token>`` header is missing/malformed
  or the token doesn't match.
- 200 with the ``DemoResetResult`` JSON shape on success — byte-identical
  to what ``POST /api/admin/demo/reset`` returns, since both paths call
  ``run_demo_reset_if_due(db, force=True)`` directly.

The ``is_demo=True`` safety boundary inside ``run_demo_reset_if_due`` is
NOT bypassed; the trigger only resets demo orgs.

See ``phase23_2_demo_metadata_dispatch_2026-05-13.md`` §B0 for the full
rationale + CLI helper (``scripts/trigger_demo_reset.py``).
"""
from __future__ import annotations

import hmac
import os
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/api/demo", tags=["demo-reset"])


@router.post("/trigger-reset")
def trigger_demo_reset_via_token(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> dict:
    """Token-gated demo reset trigger.

    Mirrors the response shape of ``POST /api/admin/demo/reset`` so the
    CLI helper and the admin endpoint return identical JSON.
    """
    expected_token = os.environ.get("DEMO_RESET_TRIGGER_TOKEN")
    if not expected_token:
        raise HTTPException(
            status_code=503,
            detail="demo reset trigger not configured on this environment",
        )

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="missing or malformed authorization header",
        )

    provided = authorization[len("Bearer "):]
    if not hmac.compare_digest(provided, expected_token):
        # Generic message — never echo the provided token value.
        raise HTTPException(status_code=401, detail="invalid token")

    # Reuse the same code path the scheduled reset uses. Token auth has no
    # human user, so actor_id stays None.
    from demo_reset_job import run_demo_reset_if_due

    result = run_demo_reset_if_due(db, force=True)
    return {
        "success": result.success,
        "started_at": result.started_at.isoformat(),
        "completed_at": result.completed_at.isoformat(),
        "orgs_reset": result.orgs_reset,
        "rows_wiped": result.rows_wiped,
        "rows_seeded": result.rows_seeded,
        "error": result.error,
        "skipped": result.skipped,
        "reason": result.reason,
    }
