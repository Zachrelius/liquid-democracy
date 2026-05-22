"""Phase 35 A1+A2 — scalability audit instrumentation.

Lightweight per-request + per-tick measurement that captures the data needed
to compute Railway cost decomposition. Gated by env var
``SCALABILITY_AUDIT_INSTRUMENTATION_ENABLED`` so we can deploy the code path
without paying its overhead on prod. Output is JSON one-per-line to stdout
under logger name ``scalability_audit`` (Railway log retention captures
this).

A1 — RequestQueryInstrumentationMiddleware. Per-request:
  - endpoint path + HTTP method
  - response time (ms)
  - DB query count for the request
  - DB query total duration (ms)
  - process RSS at request end (cheap process-level read; no per-request
    memory delta because tracemalloc would add ~10% overhead which is too
    much for permanent-on consideration)

A2 — instrument_tick context manager. For background-job ticks
(sustained_majority_worker, digest_scheduler, demo_reset_job):
  - tick name
  - start + end timestamps
  - duration (ms)
  - peak RSS during tick
  - work units dict (caller-supplied: snapshots_captured, rows_seeded, etc.)
  - errors (if any)

The A1 middleware uses SQLAlchemy event listeners on the engine to count
queries. Listeners are registered once at import time; per-request state
is held in a contextvar so the count is correctly scoped even under
concurrent FastAPI requests.
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import os
import time
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from sqlalchemy import event

log = logging.getLogger("scalability_audit")


# Env gate — middleware is a no-op when False.
_ENABLED_RAW = os.environ.get("SCALABILITY_AUDIT_INSTRUMENTATION_ENABLED", "")
INSTRUMENTATION_ENABLED: bool = _ENABLED_RAW.lower() in ("true", "1", "yes")


# Per-request counters via contextvars (correctly scoped across async tasks).
_query_count: contextvars.ContextVar[int] = contextvars.ContextVar(
    "scalability_query_count", default=0,
)
_query_duration_ms: contextvars.ContextVar[float] = contextvars.ContextVar(
    "scalability_query_duration_ms", default=0.0,
)


def _process_rss_mb() -> Optional[float]:
    """Process RSS in MB. Returns None if psutil isn't available (we don't
    require it as a hard dep; instrumentation degrades gracefully)."""
    try:
        import psutil  # type: ignore
        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except Exception:
        return None


def register_sqlalchemy_event_listeners(engine) -> None:
    """Wire SA before_cursor_execute + after_cursor_execute to count queries.
    Per-request scoping is via contextvars; the listeners only mutate the
    contextvars, so they're safe even when the middleware isn't enabled
    (the values are computed but unused — cheap)."""
    if not INSTRUMENTATION_ENABLED:
        return  # Skip listener registration entirely; zero overhead.

    @event.listens_for(engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):
        context._scalability_query_start = time.perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):
        start = getattr(context, "_scalability_query_start", None)
        if start is not None:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            _query_count.set(_query_count.get() + 1)
            _query_duration_ms.set(_query_duration_ms.get() + elapsed_ms)


class RequestQueryInstrumentationMiddleware(BaseHTTPMiddleware):
    """Phase 35 A1 — emit one JSON line per request with timing + query
    counters. No-op when env gate is off."""

    async def dispatch(self, request: Request, call_next):
        if not INSTRUMENTATION_ENABLED:
            return await call_next(request)

        # Reset per-request counters (contextvars).
        _query_count.set(0)
        _query_duration_ms.set(0.0)

        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000.0

        log.info(json.dumps({
            "audit": "request",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "elapsed_ms": round(elapsed_ms, 1),
            "query_count": _query_count.get(),
            "query_total_ms": round(_query_duration_ms.get(), 1),
            "rss_mb": _process_rss_mb(),
        }))
        return response


@contextlib.contextmanager
def instrument_tick(tick_name: str, **work_units):
    """Phase 35 A2 — context manager for background-job ticks.

    Usage:
        with instrument_tick("digest_scheduler") as ctx:
            counts = run_one_tick(db)
            ctx["work_units"] = counts
    """
    ctx: dict = {"work_units": dict(work_units), "error": None}
    if not INSTRUMENTATION_ENABLED:
        # No-op fast path.
        yield ctx
        return

    start = time.perf_counter()
    start_rss = _process_rss_mb()
    peak_rss = start_rss
    try:
        yield ctx
    except Exception as exc:
        ctx["error"] = repr(exc)
        raise
    finally:
        end_rss = _process_rss_mb()
        if start_rss is not None and end_rss is not None:
            peak_rss = max(start_rss, end_rss)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        log.info(json.dumps({
            "audit": "tick",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "tick_name": tick_name,
            "elapsed_ms": round(elapsed_ms, 1),
            "start_rss_mb": round(start_rss, 1) if start_rss is not None else None,
            "end_rss_mb": round(end_rss, 1) if end_rss is not None else None,
            "peak_rss_mb": round(peak_rss, 1) if peak_rss is not None else None,
            "work_units": ctx.get("work_units"),
            "error": ctx.get("error"),
        }))
