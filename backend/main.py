import json
import logging
import sys
import time
import uuid

from fastapi import Depends, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address  # noqa: F401  (kept for tests that may import)
from rate_limit_utils import bypass_or_remote_address
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware

from database import create_tables, get_db, SessionLocal
from sqlalchemy.orm import Session
from delegation_engine import graph_store
from settings import settings
from websocket import manager as ws_manager
from routes import auth, topics, proposals, delegations, votes, admin, users, delegates, follows, organizations, sub_organizations, polises, invitations, avatars, comments, permissions, role_permissions_routes, org_logos, notifications, delegate_profiles, demo_reset, pending_actions, org_titles as org_titles_routes, elections as elections_routes, messages as messages_routes


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def configure_logging() -> None:
    """Configure application-wide logging.

    Production (debug=False): JSON format to stdout, INFO level.
    Development (debug=True): standard console format, DEBUG level.
    """
    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)

    if settings.debug:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
            datefmt="%H:%M:%S",
        ))
        root_logger.setLevel(logging.DEBUG)
    else:
        # JSON structured logging for production
        class JSONFormatter(logging.Formatter):
            def format(self, record):
                log_obj = {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
                    "level": record.levelname,
                    "message": record.getMessage(),
                    "logger": record.name,
                }
                return json.dumps(log_obj)

        handler.setFormatter(JSONFormatter())
        root_logger.setLevel(logging.INFO)

    root_logger.addHandler(handler)


configure_logging()

log = logging.getLogger(__name__)
request_log = logging.getLogger("request")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log method, path, user_id, status code, and response time.

    In production: structured JSON logs.
    In debug: human-readable format.
    Adds X-Request-ID header to every response.
    """

    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # Phase 97: retain a bounded, sanitized sample for repeated-500
            # detection. Monitoring must never interfere with exception
            # propagation or turn a primary failure into a different one.
            try:
                from ops_monitoring import record_http_failure
                record_http_failure(
                    method=request.method,
                    path=request.url.path,
                    request_id=request_id,
                    status_code=500,
                )
            except Exception:
                pass
            request_log.exception(
                "Unhandled request exception method=%s path=%s request_id=%s",
                request.method,
                request.url.path,
                request_id,
            )
            raise
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)

        if response.status_code >= 500:
            try:
                from ops_monitoring import record_http_failure
                record_http_failure(
                    method=request.method,
                    path=request.url.path,
                    request_id=request_id,
                    status_code=response.status_code,
                )
            except Exception:
                pass

        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id

        # Extract authenticated user id from the JWT if present (best-effort).
        user_id: str | None = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            try:
                from jose import jwt as _jwt
                payload = _jwt.decode(
                    auth_header[7:],
                    settings.secret_key,
                    algorithms=["HS256"],
                    options={"verify_exp": False},
                )
                user_id = payload.get("sub")
            except Exception:
                pass

        if settings.debug:
            # Human-readable format for development
            user_str = f" user={user_id}" if user_id else ""
            request_log.info(
                f"{request.method} {request.url.path} → {response.status_code} "
                f"({elapsed_ms}ms){user_str} [{request_id[:8]}]"
            )
        else:
            # Structured JSON for production
            request_log.info(
                json.dumps(
                    {
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "level": "INFO",
                        "message": "request",
                        "request_id": request_id,
                        "user_id": user_id,
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": response.status_code,
                        "response_time_ms": elapsed_ms,
                    }
                )
            )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to every response."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


# ---------------------------------------------------------------------------
# Rate limiter (slowapi)
# ---------------------------------------------------------------------------

limiter = Limiter(key_func=bypass_or_remote_address)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Liquid Democracy API",
    description="Vote directly or delegate your vote on specific topics.",
    version="0.2.0",
    # Phase 63 (security): don't serve Swagger/ReDoc/openapi.json outside
    # debug. The backend's own *.up.railway.app domain bypasses the nginx
    # proxy, so pre-fix the full interactive API surface was publicly
    # browsable on prod.
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    openapi_url="/openapi.json" if settings.debug else None,
)

# Attach rate-limiter state and error handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Middleware is applied in reverse registration order (last registered = outermost).
# We want: SecurityHeaders → RequestLogging → CORS → route handler
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLoggingMiddleware)
# Phase 35 A1 — scalability audit instrumentation. No-op when env gate is
# off (default); when SCALABILITY_AUDIT_INSTRUMENTATION_ENABLED=true emits
# JSON-per-line with per-request query count + duration + RSS to stdout.
from scalability_instrumentation import (
    RequestQueryInstrumentationMiddleware,
    register_sqlalchemy_event_listeners,
)
from database import engine as _engine
register_sqlalchemy_event_listeners(_engine)
app.add_middleware(RequestQueryInstrumentationMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["X-Request-ID"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(auth.router)
app.include_router(topics.router)
app.include_router(proposals.router)
app.include_router(delegations.router)
app.include_router(votes.router)
app.include_router(admin.router)
app.include_router(users.router)
# Phase 19 B4 / Phase 96 — the org-scoped, visibility-filtered delegate
# directory is the only mounted browse surface. The legacy tenant-unscoped
# /api/delegates/public routes are deliberately retired.
app.include_router(delegates.org_delegates_router)
app.include_router(follows.router)
# Phase 14 B2 — public org landing page endpoint (no-auth GET /api/orgs/{slug}/public).
# Phase 23 B6 — public demo directory endpoint (no-auth GET /api/orgs/demo).
# Separate APIRouter so the unauthenticated path is visible at the route-table
# level and doesn't accidentally inherit auth-required dependencies if
# organizations.router grows a router-level auth dependency in the future.
# MUST be registered BEFORE organizations.router so the literal /demo path
# wins over the auth-required /{org_slug} catch-all (FastAPI matches routes
# in registration order across mounted routers).
app.include_router(organizations.public_org_router)
app.include_router(organizations.router)
app.include_router(sub_organizations.router)
app.include_router(polises.router)
app.include_router(invitations.router)
app.include_router(avatars.router)
app.include_router(comments.proposal_router)
app.include_router(comments.comment_router)
app.include_router(permissions.router)
app.include_router(role_permissions_routes.router)
# Phase 44 — multi-admin approval pending-actions surface.
# Mounted under /api/orgs/{slug}/admin/pending-actions; per-action permission
# enforcement happens inside the engine, not at the router level.
app.include_router(pending_actions.router)
app.include_router(org_titles_routes.router)
app.include_router(elections_routes.router)
# Phase 77 — org-scoped direct messaging.
app.include_router(messages_routes.router)
# Phase 86 (B-4) — member content report / flag queue.
from routes import reports as reports_routes
app.include_router(reports_routes.report_router)
app.include_router(reports_routes.org_report_router)
# Phase 12.7 B1+B2 — org branding endpoints (logo upload/delete, color PATCH).
# Mounted on /api/orgs/{slug}/logo + /branding; gated by org.edit_branding.
app.include_router(org_logos.router)
# Phase 13 B4 — notification feed + preferences endpoints. Mounted on
# /api/notifications/*; account-scoped (every authenticated user accesses
# their own notifications and preferences — no role-tier gates per spec
# Item 30 audit guidance).
app.include_router(notifications.router)
# Phase 19 (B3) — public-delegate-page lifecycle endpoints. Mounted on
# /api/orgs/{slug}/delegate-profile/* per spec — get-or-create the
# caller's OrgDelegateProfile, edit per-topic DelegateProfile rows,
# submit/approve/deny the public_accepting workflow, and the user-
# initiated revert endpoints (soft + hard, with the hard-revert
# centralized via _revoke_public_origin_delegations_on_topic).
app.include_router(delegate_profiles.router)
# Phase 19 (B6) — vote rationale CRUD. Mounted on /api/votes/{vote_id}/
# rationale (separate APIRouter from votes.router so the URL prefix
# matches the spec without colliding with the proposal-prefixed vote
# endpoints).
app.include_router(votes.rationale_router)
# Phase 23.2 B0 — token-gated demo reset trigger (POST /api/demo/trigger-reset).
# Code-team autonomy path: bearer-token-auth alternative to the admin-auth
# endpoint at /api/admin/demo/reset. See backend/routes/demo_reset.py for the
# scope boundary (single endpoint, reuses run_demo_reset_if_due force=True).
app.include_router(demo_reset.router)
# Phase 52a — verification session initiation + Didit webhook receiver.
# Session endpoint authenticated by JWT; webhook endpoint authenticated
# by HMAC-SHA256 signature + X-Timestamp freshness. Until
# DIDIT_WEBHOOK_SECRET is set in env, the webhook fails closed (401)
# on every payload — the intended "build receiver first, surface URL
# to Z, set secret, then smoke" sequence.
from routes import verification as verification_routes
app.include_router(verification_routes.router)
# Phase 52e Stage 2 E4 — org-scoped duplicate-flag adjudication.
from routes import duplicate_flags as duplicate_flags_routes
app.include_router(duplicate_flags_routes.router)


# ---------------------------------------------------------------------------
# Static files — uploaded user content (Phase 9.8 W A1; Phase 12.7 I2)
# ---------------------------------------------------------------------------
# Files written by routes/avatars.py and routes/org_logos.py to the resolved
# uploads base directory. Phase 25 B3 switched from the Phase 12.7 3-tier
# auto-detect to env-driven config: ``UPLOAD_DIR`` (or legacy
# ``UPLOADS_BASE_DIR``) overrides; default is ``/data/uploads`` (Railway
# Volume mount in prod). We import the resolved constant rather than
# recomputing so tests that monkeypatch the constant continue to work and
# the StaticFiles mount stays in sync with where files are actually
# written.
from routes.avatars import UPLOADS_BASE_DIR as _UPLOADS_BASE_DIR
_UPLOADS_BASE_DIR.mkdir(parents=True, exist_ok=True)
(_UPLOADS_BASE_DIR / "avatars").mkdir(parents=True, exist_ok=True)
(_UPLOADS_BASE_DIR / "logos").mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(_UPLOADS_BASE_DIR)), name="uploads")


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@app.websocket("/ws/proposals/{proposal_id}")
async def proposal_websocket(
    websocket: WebSocket,
    proposal_id: str,
    db=Depends(get_db),
):
    """Phase 38 B2 — auth-gated subscribe to live tally_update broadcasts.

    Flow:
      1. Resolve the proposal up-front. If it doesn't exist, close 4404
         BEFORE accepting the socket — leaks no timing signal about
         which proposal IDs are valid.
      2. Accept the socket and wait up to 5s for the first message:
         ``{"auth": "<access_token>"}``. Timeout/malformed/missing
         token closes 4401.
      3. Decode the token via ``auth_utils._get_user_from_token``.
         Decode failure closes 4401.
      4. Run the proposal-eligibility check (same
         ``_eligible_viewers_for_proposal`` set used by B1). Platform
         admins bypass. Failure closes 4403.
      5. On auth success, register with the manager and run the
         passive receive loop until WebSocketDisconnect.

    Uses ``Depends(get_db)`` so TestClient fixtures that override
    ``get_db`` (per-test in-memory SQLite) see the same session the
    route operates on — without the dep, SessionLocal() opened a
    separate session that didn't see test-fixture writes.
    """
    import asyncio
    import json as _json

    import auth as auth_utils
    import models
    from eligibility import eligible_viewers_for_proposal as _eligible_viewers_for_proposal

    proposal = db.query(models.Proposal).filter(
        models.Proposal.id == proposal_id,
    ).first()
    if proposal is None:
        await websocket.close(code=4404, reason="proposal not found")
        return

    await websocket.accept()

    try:
        handshake_raw = await asyncio.wait_for(
            websocket.receive_text(), timeout=5.0,
        )
    except asyncio.TimeoutError:
        await websocket.close(code=4401, reason="auth timeout")
        return
    except WebSocketDisconnect:
        return

    try:
        handshake = _json.loads(handshake_raw)
    except (_json.JSONDecodeError, TypeError):
        await websocket.close(code=4401, reason="malformed handshake")
        return

    token = handshake.get("auth") if isinstance(handshake, dict) else None
    if not token or not isinstance(token, str):
        await websocket.close(code=4401, reason="missing token")
        return

    try:
        user = auth_utils._get_user_from_token(token, db)
    except Exception:
        await websocket.close(code=4401, reason="invalid token")
        return

    if not user.is_admin:
        if user.id not in _eligible_viewers_for_proposal(db, proposal):
            await websocket.close(code=4403, reason="not eligible")
            return

    ws_manager.register(proposal_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(proposal_id, websocket)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup() -> None:
    # Phase 37 B2 (2026-05-27): refuse to start in non-debug mode with the
    # placeholder SECRET_KEY. The platform trusts JWTs minted with this key,
    # so a placeholder value would let anyone with read access to the public
    # repo forge tokens. Defense-in-depth against env-injection failures —
    # primary safety property is that Railway env always sets SECRET_KEY.
    if not settings.debug:
        placeholder_key = "change-me-in-production-use-a-long-random-string"
        if settings.secret_key == placeholder_key:
            raise RuntimeError(
                "SECRET_KEY is the placeholder default in non-debug mode. "
                "Set SECRET_KEY env var to a long random value before starting."
            )

        # Phase 40 B3 (2026-05-27): refuse to start with WORKERS > 1.
        # graph_store cycle detection is process-local; running multiple
        # uvicorn workers makes concurrent cycle-creating delegations both
        # pass their own local cycle check, breaking the cycle-prevention
        # invariant. Until graph_store is rearchitected (option (a) — DB
        # level CTE), single-worker is load-bearing. The env var read here
        # (WORKERS) matches start.sh's `--workers ${WORKERS:-1}`.
        import os
        workers = int(os.environ.get("WORKERS", "1"))
        if workers > 1:
            raise RuntimeError(
                f"WORKERS={workers}. Phase 40 B3: multi-worker is not safe "
                "until graph_store is rearchitected (cycle detection is "
                "process-local). Set WORKERS=1 or run with settings.debug=True."
            )

        # Phase 40 B5 D17 (2026-05-27): refuse to start with rate-limit
        # bypass on a public-demo env. The compound gate at the slowapi
        # key_func layer also enforces this, but failing fast at boot is
        # better than discovering it at request time.
        if settings.is_public_demo and settings.rate_limit_bypass:
            raise RuntimeError(
                "RATE_LIMIT_BYPASS=true is incompatible with "
                "IS_PUBLIC_DEMO=true. The bypass is dev/ops-only and must "
                "never be set in any prod environment."
            )

    log.info("Creating database tables…")
    create_tables()

    log.info("Rebuilding delegation graphs from DB…")
    db = SessionLocal()
    try:
        graph_store.rebuild_from_db(db)
    finally:
        db.close()

    # Phase 25 B3 — surface ephemeral-uploads misconfiguration. Phase 25
    # switched to env-driven config (default /data/uploads); a path NOT
    # under /data/ usually means UPLOAD_DIR was overridden for local dev
    # or the volume mount isn't reachable. Logging keeps the deploy state
    # observable.
    if not str(_UPLOADS_BASE_DIR).startswith("/data/"):
        log.warning(
            "UPLOADS storage resolved to non-volume path %s — "
            "uploaded logos/avatars will be lost on the next redeploy "
            "unless this is local dev. Verify the Railway Volume mount "
            "at /data/uploads is attached to this service and that "
            "UPLOAD_DIR is unset in prod.",
            _UPLOADS_BASE_DIR,
        )

    # Phase 13 E3 — digest scheduler. Wakes hourly, processes daily/
    # weekly digests + quiet-hours flush + 90-day cleanup. Gated on
    # DISABLE_DIGEST_SCHEDULER env var so tests don't accidentally launch
    # the loop. See backend/digest_scheduler.py for implementation choice
    # rationale + DEPLOYMENT.md for the ops note.
    #
    # Phase 13.2 W-DEPLOY-3 defensive-launch pattern: wrapping in try/
    # except so a scheduler launch failure (import error in
    # digest_scheduler, asyncio loop misconfig, etc.) cannot crash
    # startup. Endpoints stay up; in-app notifications continue to flow;
    # only the scheduled digest job goes silent. This is the graceful-
    # degradation contract spec'd in phase13_1_notifications_redeploy_spec.md.
    try:
        from digest_scheduler import digest_loop, is_disabled
        if is_disabled():
            log.info(
                "Digest scheduler disabled via DISABLE_DIGEST_SCHEDULER; "
                "skipping startup task."
            )
        else:
            import asyncio
            asyncio.create_task(digest_loop())
            log.info("Digest scheduler launched.")
    except Exception:  # noqa: BLE001 — never let scheduler issues kill startup
        log.exception(
            "Failed to start digest scheduler — falling back to in-app "
            "notifications only; digest emails + quiet-hours flush + "
            "90-day cleanup will not run until next deploy fixes this."
        )

    # Phase 97 — five-minute internal monitoring loop. It is deliberately
    # isolated from startup: failure to import/launch monitoring is logged but
    # cannot take the application down. The external GitHub probe will then
    # detect the missing/stale monitor surface.
    try:
        from ops_monitoring import is_disabled as monitor_disabled, monitor_loop
        if monitor_disabled():
            log.info("Operations monitoring disabled via OPS_MONITOR_ENABLED=false.")
        else:
            import asyncio
            app.state.ops_monitor_task = asyncio.create_task(monitor_loop())
            log.info("Operations monitoring loop launched.")
    except Exception:  # noqa: BLE001
        log.exception("Failed to start operations monitoring loop")

    log.info("Startup complete.")


# ---------------------------------------------------------------------------
# Health check endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "0.1.0"}


@app.get("/api/public-config")
def public_config():
    """Frontend-readable feature flags. No auth — read at app boot.

    Phase 9: ``polis_token_configured`` drives the manual-fallback UX
    (when the platform doesn't have a pol.is admin token configured,
    Polis-create + archive surfaces show "complete this step on pol.is"
    reminders rather than treating the API call as the source of truth).
    """
    from settings import settings
    return {
        "polis_token_configured": bool(getattr(settings, "polis_auth_token", "") or ""),
    }


@app.get("/api/health/ready")
def health_ready():
    """Readiness probe — verifies database connectivity."""
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            return {"status": "ok", "database": "connected"}
        finally:
            db.close()
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "database": "disconnected"},
        )


@app.get("/api/health/scheduler")
def health_scheduler(db: Session = Depends(get_db)):
    """Phase 40 B4 — health probe for the two background workers.

    Returns ``last_successful_tick_at`` (ISO 8601 UTC) and
    ``ticks_since_last_success`` for both the in-process ``digest_loop``
    (read from module-level state) and the out-of-process
    ``sustained_majority_worker`` (read from the
    ``sm_worker_heartbeat`` PlatformSetting row written at the end of
    each worker tick). Public, no auth — matches /api/health/ready
    posture; Railway probes shouldn't require auth.

    A worker that has never completed a tick (e.g., just-restarted
    process) reports ``last_successful_tick_at: null``. A worker that's
    been failing reports an increasing ``ticks_since_last_success``.
    """
    import models
    from digest_scheduler import get_scheduler_state as _digest_state

    sm_state = {"last_successful_tick_at": None, "ticks_since_last_success": 0}
    try:
        row = db.query(models.PlatformSetting).filter(
            models.PlatformSetting.key == "sm_worker_heartbeat",
        ).first()
        if row is not None and isinstance(row.value, dict):
            sm_state = {
                "last_successful_tick_at": row.value.get("last_successful_tick_at"),
                "ticks_since_last_success": int(
                    row.value.get("ticks_since_last_success", 0)
                ),
            }
    except Exception:  # noqa: BLE001
        log.exception("health_scheduler: failed to read SM worker heartbeat")
        # Fall through with the default empty sm_state — the endpoint
        # itself shouldn't 5xx just because the heartbeat row is unreadable.

    return {
        "digest_scheduler": _digest_state(),
        "sustained_majority_worker": sm_state,
    }


@app.get("/api/health/monitor")
def health_monitor(db: Session = Depends(get_db)):
    """Phase 97 combined public-safe production monitor.

    HTTP 503 is reserved for actionable errors so the external GitHub probe
    can fail. Capacity warnings remain HTTP 200 while still appearing in the
    payload and triggering the deduplicated internal admin alert.
    """
    from ops_monitoring import build_snapshot
    snapshot = build_snapshot(db, upload_dir=_UPLOADS_BASE_DIR)
    if snapshot["status"] == "error":
        return JSONResponse(status_code=503, content=snapshot)
    return snapshot
