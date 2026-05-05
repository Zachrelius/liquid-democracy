import json
import logging
import sys
import time
import uuid

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware

from database import create_tables, get_db, SessionLocal
from delegation_engine import graph_store
from settings import settings
from websocket import manager as ws_manager
from routes import auth, topics, proposals, delegations, votes, admin, users, delegates, follows, organizations, sub_organizations, polises, invitations, avatars, comments, permissions, role_permissions_routes, org_logos, notifications


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
        response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)

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

limiter = Limiter(key_func=get_remote_address)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Liquid Democracy API",
    description="Vote directly or delegate your vote on specific topics.",
    version="0.2.0",
)

# Attach rate-limiter state and error handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Middleware is applied in reverse registration order (last registered = outermost).
# We want: SecurityHeaders → RequestLogging → CORS → route handler
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLoggingMiddleware)
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
app.include_router(delegates.router)
app.include_router(follows.router)
app.include_router(organizations.router)
app.include_router(sub_organizations.router)
app.include_router(polises.router)
app.include_router(invitations.router)
app.include_router(avatars.router)
app.include_router(comments.proposal_router)
app.include_router(comments.comment_router)
app.include_router(permissions.router)
app.include_router(role_permissions_routes.router)
# Phase 12.7 B1+B2 — org branding endpoints (logo upload/delete, color PATCH).
# Mounted on /api/orgs/{slug}/logo + /branding; gated by org.edit_branding.
app.include_router(org_logos.router)
# Phase 13 B4 — notification feed + preferences endpoints. Mounted on
# /api/notifications/*; account-scoped (every authenticated user accesses
# their own notifications and preferences — no role-tier gates per spec
# Item 30 audit guidance).
app.include_router(notifications.router)


# ---------------------------------------------------------------------------
# Static files — uploaded user content (Phase 9.8 W A1; Phase 12.7 I2)
# ---------------------------------------------------------------------------
# Files written by routes/avatars.py and routes/org_logos.py to the resolved
# uploads base directory. Phase 12.7 I2 relocated the base from the in-image
# ``backend/uploads/`` (ephemeral on Railway) to ``/data/uploads/`` on a
# mounted Railway Volume — see ``routes/avatars.py::_resolve_uploads_base``
# for the 3-tier fallback. We import the resolved constant rather than
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
async def proposal_websocket(websocket: WebSocket, proposal_id: str):
    await ws_manager.connect(proposal_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(proposal_id, websocket)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
def startup() -> None:
    log.info("Creating database tables…")
    create_tables()

    log.info("Rebuilding delegation graphs from DB…")
    db = SessionLocal()
    try:
        graph_store.rebuild_from_db(db)
    finally:
        db.close()

    # Phase 12.8 audit Tier 1, Item 1 — surface ephemeral-uploads fallback.
    # The 3-tier path resolver in routes/avatars.py silently falls back to
    # backend/uploads/ when the Railway Volume isn't mounted. Without this
    # warning the deploy looks healthy but uploaded logos/avatars vanish
    # on the next redeploy. Logging makes the misconfiguration visible.
    if not str(_UPLOADS_BASE_DIR).startswith("/data/"):
        log.warning(
            "UPLOADS storage is on ephemeral container path %s — "
            "uploaded logos/avatars will be lost on the next redeploy. "
            "Provision a Railway Volume at /data and run "
            "scripts/phase12_7_migrate_uploads.py to migrate legacy files.",
            _UPLOADS_BASE_DIR,
        )

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
