"""Phase 9 — pol.is API wrapper.

Encapsulates all HTTP calls to the hosted pol.is API so future swaps (self-
hosted instances, alternative deliberation tools) are minimally invasive.
Same isolation principle as ``pyrankvote`` in ``delegation_engine.py``: the
rest of the codebase depends only on this module's surface, not on
pol.is-specific details.

Findings from `phase9_polis_api_findings.md`:
  - Auth is JWT-based (not API key). The Bearer token is provided via the
    ``POLIS_AUTH_TOKEN`` env var (see settings.py).
  - Without a token configured every function raises ``PolisAPIError``
    cleanly. This is the expected dev / fresh-prod-deploy state.
  - All admin endpoints (POST /api/v3/conversations, POST /api/v3/comments,
    POST /api/v3/conversation/close, GET /api/v3/dataExport) require
    ``hybridAuth`` (Bearer JWT). ``GET /api/v3/conversationStats`` is
    optional-auth so we read it without a token.
  - ``conversation_id`` returned by pol.is is a 6-10 char opaque slug.
  - ``data-xid`` accepts 1-999 char opaque strings.

Failure handling: every HTTP call maps non-2xx to ``PolisAPIError(message,
status_code)``. Routes calling these functions are responsible for rolling
back any partial platform-side state (per spec: NO orphaned platform
records on pol.is API failure).
"""
from __future__ import annotations

import logging
import secrets
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

import models
from audit_utils import log_audit_event
from settings import settings

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class PolisAPIError(Exception):
    """Raised when a pol.is API call fails or auth isn't configured.

    Attributes
    ----------
    message : str
        Human-readable error.
    status_code : Optional[int]
        HTTP status if the failure was an HTTP response; None when the
        failure happened before a request was sent (e.g., missing auth
        token, network error).
    """

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Default request timeout. Polis admin operations are quick (single-DB
# writes); 10s is generous and well below the FastAPI default.
_DEFAULT_TIMEOUT_SECONDS = 10


def _require_token() -> str:
    """Return the configured Bearer token or raise PolisAPIError.

    Auth-less calls (participation stats) bypass this; admin calls go
    through it.
    """
    token = (settings.polis_auth_token or "").strip()
    if not token:
        raise PolisAPIError(
            "POLIS_AUTH_TOKEN not configured. The pol.is API uses JWT-based "
            "auth (see phase9_polis_api_findings.md); set POLIS_AUTH_TOKEN "
            "to a valid pol.is admin Bearer JWT to enable programmatic "
            "Polis creation. In v1, the platform supports a manual-creation "
            "fallback flow (admin creates the conversation on pol.is, then "
            "pastes the conversation_id into the platform) which works "
            "without this env var being set."
        )
    return token


def _api_url(path: str) -> str:
    base = settings.polis_api_base_url.rstrip("/")
    return f"{base}{path}"


def _admin_headers() -> dict:
    return {
        "Authorization": f"Bearer {_require_token()}",
        "Content-Type": "application/json",
    }


def _handle_response(resp: httpx.Response, action: str) -> dict:
    """Map an `httpx.Response` to a parsed JSON dict or raise.

    Polis returns ``{"error": "polis_err_*"}`` on 4xx with the response
    body as JSON. We surface a generic message to callers and log the
    raw error code.
    """
    if 200 <= resp.status_code < 300:
        try:
            return resp.json() if resp.text else {}
        except ValueError:
            return {}

    body_summary = ""
    try:
        body = resp.json()
        body_summary = body.get("error") or str(body)[:200]
    except ValueError:
        body_summary = (resp.text or "")[:200]

    log.warning(
        "pol.is API %s failed status=%d body=%s",
        action, resp.status_code, body_summary,
    )
    raise PolisAPIError(
        f"pol.is API {action} failed (status={resp.status_code}): {body_summary}",
        status_code=resp.status_code,
    )


# ---------------------------------------------------------------------------
# Public API — conversation lifecycle
# ---------------------------------------------------------------------------

def create_conversation(
    title: str, prompt: str, seed_statements: Optional[list[str]] = None,
) -> dict:
    """Create a pol.is conversation and (best-effort) seed it.

    Returns
    -------
    dict
        ``{"conversation_id": str, "embed_url": str, "manage_url": str,
        "seed_statement_results": [{"text": str, "ok": bool, "error": ...}]}``

        ``seed_statement_results`` is empty when ``seed_statements`` is
        empty; otherwise lists per-statement outcomes so callers can
        surface partial-failure cleanly. The conversation itself is
        created either way.

    Raises
    ------
    PolisAPIError
        If the conversation-creation HTTP call fails or auth isn't
        configured. Caller is responsible for rolling back any platform-
        side rows on this exception.
    """
    payload = {
        # `topic` is the pol.is name for the conversation title.
        "topic": title,
        "description": prompt,
        # Sensible Polis defaults aligned with platform UX:
        "is_active": True,
        "is_anon": False,
        # `is_data_open` opens the data export to the public; we leave
        # it false and gate export through the platform's admin route.
        "is_data_open": False,
        "owner_sees_participation_stats": True,
    }

    try:
        resp = httpx.post(
            _api_url("/api/v3/conversations"),
            json=payload,
            headers=_admin_headers(),
            timeout=_DEFAULT_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise PolisAPIError(
            f"pol.is API create_conversation network error: {exc}",
            status_code=None,
        ) from exc

    body = _handle_response(resp, "create_conversation")
    conversation_id = body.get("conversation_id") or body.get("zinvite") or ""
    if not conversation_id:
        raise PolisAPIError(
            "pol.is API create_conversation returned no conversation_id "
            f"(body keys: {sorted(body.keys())})"
        )

    embed_url = f"{settings.polis_api_base_url.rstrip('/')}/{conversation_id}"
    manage_url = (
        f"{settings.polis_api_base_url.rstrip('/')}/m/{conversation_id}"
    )

    seed_results: list[dict] = []
    if seed_statements:
        for txt in seed_statements:
            try:
                add_seed_statement(conversation_id, txt)
                seed_results.append({"text": txt, "ok": True})
            except PolisAPIError as exc:
                # Don't fail the whole creation on a single bad seed —
                # the conversation is created and the admin can retry
                # individual seeds via the pol.is admin UI. Caller can
                # surface this as a warning.
                seed_results.append(
                    {"text": txt, "ok": False, "error": str(exc)}
                )
                log.warning(
                    "Polis seed-statement insertion failed conv=%s err=%s",
                    conversation_id, exc,
                )

    return {
        "conversation_id": conversation_id,
        "embed_url": embed_url,
        "manage_url": manage_url,
        "seed_statement_results": seed_results,
    }


def add_seed_statement(conversation_id: str, statement: str) -> None:
    """Insert a single seed statement into a Polis conversation.

    Calls ``POST /api/v3/comments`` with ``is_seed=true``. Per
    findings.md, this is fully programmatic — the pol.is admin UI just
    calls this same endpoint.

    Raises ``PolisAPIError`` on failure (HTTP non-2xx or auth missing).
    """
    payload = {
        "conversation_id": conversation_id,
        "txt": statement,
        "is_seed": True,
    }
    try:
        resp = httpx.post(
            _api_url("/api/v3/comments"),
            json=payload,
            headers=_admin_headers(),
            timeout=_DEFAULT_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise PolisAPIError(
            f"pol.is API add_seed_statement network error: {exc}"
        ) from exc
    _handle_response(resp, "add_seed_statement")


def add_seed_statements(
    conversation_id: str, statements: list[str],
) -> list[dict]:
    """Bulk wrapper for `add_seed_statement` with per-statement outcome.

    Returns ``[{"text": str, "ok": bool, "error": str?}, ...]``.
    Useful when the caller already has a created conversation and is
    appending more seeds (e.g., an admin updating the seed list later).
    """
    out: list[dict] = []
    for txt in statements:
        try:
            add_seed_statement(conversation_id, txt)
            out.append({"text": txt, "ok": True})
        except PolisAPIError as exc:
            out.append({"text": txt, "ok": False, "error": str(exc)})
    return out


def get_participation_stats(conversation_id: str) -> dict:
    """Fetch live participation stats for a Polis conversation.

    Uses ``GET /api/v3/conversationStats`` which is auth-optional, so
    this works in dev without ``POLIS_AUTH_TOKEN`` configured.

    Returns
    -------
    dict
        Either ``{"participant_count": int, "statement_count": int,
        "vote_count": int, "live_stats_unavailable": False}`` on success,
        or ``{"participant_count": 0, "statement_count": 0, "vote_count": 0,
        "live_stats_unavailable": True, "error": str}`` if the API is
        unreachable. The fail-soft shape lets callers render a "stats
        currently unavailable" badge without blowing up the route.
    """
    try:
        resp = httpx.get(
            _api_url("/api/v3/conversationStats"),
            params={"conversation_id": conversation_id},
            timeout=_DEFAULT_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        log.info(
            "pol.is participation stats unavailable conv=%s err=%s",
            conversation_id, exc,
        )
        return {
            "participant_count": 0,
            "statement_count": 0,
            "vote_count": 0,
            "live_stats_unavailable": True,
            "error": str(exc),
        }

    if resp.status_code >= 400:
        return {
            "participant_count": 0,
            "statement_count": 0,
            "vote_count": 0,
            "live_stats_unavailable": True,
            "error": f"HTTP {resp.status_code}",
        }

    try:
        body = resp.json()
    except ValueError:
        return {
            "participant_count": 0,
            "statement_count": 0,
            "vote_count": 0,
            "live_stats_unavailable": True,
            "error": "invalid JSON response",
        }

    # The /api/v3/conversationStats payload has nested arrays of counts
    # over time; the totals we want are the last entry of each. Defensive
    # access — pol.is may rev the shape and we don't want stats failures
    # to take down the Polis-detail page.
    def _last_count(key: str) -> int:
        seq = body.get(key)
        if isinstance(seq, list) and seq:
            try:
                return int(seq[-1])
            except (TypeError, ValueError):
                return 0
        return 0

    return {
        "participant_count": _last_count("voters") or _last_count("voters-cumulative"),
        "statement_count": _last_count("commenters") or _last_count("comments"),
        "vote_count": _last_count("votes") or _last_count("votes-cumulative"),
        "live_stats_unavailable": False,
    }


def archive_conversation(conversation_id: str) -> None:
    """Close a Polis conversation (no further participation).

    Calls ``POST /api/v3/conversation/close``. Polis preserves all data
    — only further participation is blocked. Reversible via reopen
    (not exposed in v1).

    Raises ``PolisAPIError`` on failure or missing auth.
    """
    payload = {"conversation_id": conversation_id}
    try:
        resp = httpx.post(
            _api_url("/api/v3/conversation/close"),
            json=payload,
            headers=_admin_headers(),
            timeout=_DEFAULT_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise PolisAPIError(
            f"pol.is API archive_conversation network error: {exc}"
        ) from exc
    _handle_response(resp, "archive_conversation")


def fetch_export(conversation_id: str, fmt: str = "csv") -> bytes:
    """Fetch a Polis data export as raw bytes.

    Calls ``GET /api/v3/dataExport`` with the format string. Returns the
    raw response body — caller is responsible for content-type handling.

    Raises ``PolisAPIError`` on failure.
    """
    try:
        resp = httpx.get(
            _api_url("/api/v3/dataExport"),
            params={"conversation_id": conversation_id, "format": fmt},
            headers={"Authorization": f"Bearer {_require_token()}"},
            timeout=_DEFAULT_TIMEOUT_SECONDS * 3,  # exports may be larger
        )
    except httpx.HTTPError as exc:
        raise PolisAPIError(
            f"pol.is API fetch_export network error: {exc}"
        ) from exc
    if 200 <= resp.status_code < 300:
        return resp.content
    raise PolisAPIError(
        f"pol.is API fetch_export failed (status={resp.status_code})",
        status_code=resp.status_code,
    )


# ---------------------------------------------------------------------------
# xid generation — pure DB, no HTTP
# ---------------------------------------------------------------------------

def get_or_create_polis_xid(
    db: Session,
    user_id: str,
    org_id: str,
    *,
    actor_id: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> str:
    """Return the user's `polis_xid` for this org, creating it if missing.

    Phase 9 Decision 4 — pseudonymous identity bridging. The xid is an
    opaque random string that pol.is sees instead of the user's
    platform identity; the platform can join `polis_xid -> user_id`
    internally for moderation.

    Per-org isolated: same user gets a different xid in each org.
    Idempotent: subsequent calls return the existing xid.

    Audit emission: `polis.xid_generated` fires ONLY on first generation,
    not on every call. Mirrors the audit-on-state-change pattern from
    Phase 3a/3b helpers.

    Parameters
    ----------
    db : Session
    user_id : str
    org_id : str
    actor_id : Optional[str]
        Audit actor (typically same as user_id since the user opens the
        Polis embed themselves). Pass through from the route.
    ip_address : Optional[str]
        Audit IP, for future abuse detection.

    Returns
    -------
    str
        The opaque xid string.
    """
    existing = db.query(models.PolisXid).filter(
        models.PolisXid.user_id == user_id,
        models.PolisXid.org_id == org_id,
    ).first()
    if existing is not None:
        return existing.polis_xid

    # Generate an opaque random string. token_urlsafe(16) -> 22 chars,
    # well within pol.is's 1-999 char xid length bound, and URL-safe so
    # it can be passed via query strings without encoding.
    new_xid = secrets.token_urlsafe(16)

    row = models.PolisXid(
        user_id=user_id, org_id=org_id, polis_xid=new_xid,
    )
    db.add(row)
    db.flush()

    log_audit_event(
        db,
        action="polis.xid_generated",
        target_type="polis_xid",
        target_id=row.id,
        actor_id=actor_id or user_id,
        # Aggregate-only payload per Phase 7.5 redaction principles —
        # we record THAT a bridging xid was generated, not the xid
        # value itself (the xid is the moderation-key the platform
        # uses to deanonymize and shouldn't be re-exposed in audit
        # log readers).
        details={
            "user_id": user_id,
            "org_id": org_id,
        },
        ip_address=ip_address,
    )

    return new_xid
