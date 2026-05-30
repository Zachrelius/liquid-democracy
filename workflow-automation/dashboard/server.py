"""Dashboard FastAPI + WebSocket server (WA3 B1-B5 wiring).

Binds 127.0.0.1 only. Reuses the WA1 ``planner_state`` package for
state reads + IPC contract writes. The WS endpoint fans out hook
events to connected dashboard clients in real time.

Endpoints:

  GET   /                          → static dashboard HTML
  GET   /static/*                  → static assets (css/js)
  GET   /api/state                 → WA1 state snapshot (JSON)
  GET   /api/state/markdown        → WA1 bootstrap render (Markdown)
  POST  /api/hook                  → ingest a hook event (called by hook_handler.py)
  WS    /ws/events                 → fan out hook events to dashboards
  POST  /api/chat                  → write a chat message to the WA1 IPC inbox
  GET   /api/outbox                → poll the IPC outbox for replies
  GET   /api/quota                 → quota / model / cost snapshot
  POST  /api/quota/observation     → ingest a `claude -p` result for quota tracking
  POST  /api/quota/clear           → manually clear the throttled flag

The server has zero command-line work and zero auth. Localhost-only;
WA3 D6: no secrets rendered (events.py redacts before fanout).
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from collections import deque
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

# Local imports — planner_state is a sibling package under workflow-automation/
_WA_DIR = Path(__file__).resolve().parents[1]
if str(_WA_DIR) not in sys.path:
    sys.path.insert(0, str(_WA_DIR))

from planner_state import (  # noqa: E402
    IPCLayout,
    StateStore,
    render_bootstrap,
)
from planner_state.checkpoint import StateCorruptionError  # noqa: E402
from planner_state.schema import SchemaVersionMismatch  # noqa: E402

from dashboard.events import normalize_event  # noqa: E402
from dashboard.quota import (  # noqa: E402
    QuotaState,
    clear_throttle,
    update_from_claude_result,
)


# ---------------------------------------------------------------------------
# App + state
# ---------------------------------------------------------------------------

EVENT_BUFFER_CAP = 500  # cap retained history; older drops out


class DashboardState:
    """In-process holder for runtime state (event buffer, WS clients,
    quota). State dir + IPC root come from the CLI / env at startup."""

    def __init__(self, state_dir: Path, ipc_root: Path) -> None:
        self.state_dir = state_dir
        self.ipc_root = ipc_root
        self.store = StateStore(state_dir)
        self.ipc = IPCLayout(ipc_root)
        self.ipc.ensure()
        self.events: deque[dict[str, Any]] = deque(maxlen=EVENT_BUFFER_CAP)
        self._next_event_id: int = 1
        self.ws_clients: set[WebSocket] = set()
        self.quota = QuotaState()

    def next_event_id(self) -> int:
        i = self._next_event_id
        self._next_event_id += 1
        return i


_state: DashboardState | None = None


def get_state() -> DashboardState:
    global _state
    if _state is None:
        raise RuntimeError(
            "DashboardState not initialized. Call init_app(state_dir, ipc_root) "
            "before serving requests."
        )
    return _state


def init_app(state_dir: Path | str, ipc_root: Path | str) -> FastAPI:
    """Wire up the FastAPI app with concrete dirs. Idempotent within
    a process so tests can re-init between cases."""
    global _state
    _state = DashboardState(Path(state_dir), Path(ipc_root))
    return _build_app()


# ---------------------------------------------------------------------------
# App builder
# ---------------------------------------------------------------------------

def _build_app() -> FastAPI:
    app = FastAPI(title="WA3 At-Desk Dashboard")

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", response_class=FileResponse)
    async def index() -> FileResponse:
        return FileResponse(str(static_dir / "index.html"))

    # ------------------------------------------------------------------
    # State panel (B2)
    # ------------------------------------------------------------------

    @app.get("/api/state")
    async def get_state_json() -> JSONResponse:
        s = get_state()
        try:
            ps = s.store.load()
        except FileNotFoundError:
            return JSONResponse({"_state": "empty", "_state_dir": str(s.state_dir)})
        except (StateCorruptionError, SchemaVersionMismatch) as e:
            return JSONResponse(
                {"_state": "error", "_error": str(e), "_state_dir": str(s.state_dir)},
                status_code=500,
            )
        return JSONResponse(ps.to_dict())

    @app.get("/api/state/markdown", response_class=PlainTextResponse)
    async def get_state_markdown() -> str:
        s = get_state()
        try:
            ps = s.store.load()
        except FileNotFoundError:
            return f"# No state yet\n\nNo `planner_state.json` at `{s.state_dir}`."
        except (StateCorruptionError, SchemaVersionMismatch) as e:
            return f"# State error\n\n```\n{e}\n```"
        return render_bootstrap(ps, state_dir=s.state_dir)

    # ------------------------------------------------------------------
    # Hook ingest + WS fanout (B1 + B3)
    # ------------------------------------------------------------------

    @app.post("/api/hook")
    async def ingest_hook(request: Request) -> JSONResponse:
        s = get_state()
        body_bytes = await request.body()
        try:
            raw = json.loads(body_bytes) if body_bytes else {}
        except json.JSONDecodeError:
            return JSONResponse({"ok": False, "error": "invalid JSON"}, status_code=400)
        event_id = s.next_event_id()
        normalized = normalize_event(raw, event_id, len(body_bytes))
        s.events.append(normalized)
        # Fan out to WS clients. Best-effort; dead sockets get pruned.
        dead: list[WebSocket] = []
        for ws in s.ws_clients:
            try:
                await ws.send_text(json.dumps({"type": "event", "event": normalized}))
            except Exception:
                dead.append(ws)
        for ws in dead:
            s.ws_clients.discard(ws)
        return JSONResponse({"ok": True, "id": event_id})

    @app.websocket("/ws/events")
    async def ws_events(websocket: WebSocket) -> None:
        s = get_state()
        await websocket.accept()
        s.ws_clients.add(websocket)
        try:
            # Send a backfill of recent events (up to EVENT_BUFFER_CAP).
            await websocket.send_text(json.dumps({
                "type": "backfill",
                "events": list(s.events),
            }))
            # Keep the socket alive; we only push, never read. A client
            # disconnect raises WebSocketDisconnect on the next send;
            # but we also tolerate the client sending pings.
            while True:
                # 60s timeout — long enough that a noisy receive_text
                # loop doesn't burn CPU, short enough that we notice
                # disconnects within a minute.
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=60.0)
                except asyncio.TimeoutError:
                    # No client → server messages expected; refresh the wait.
                    continue
        except WebSocketDisconnect:
            pass
        finally:
            s.ws_clients.discard(websocket)

    @app.get("/api/events")
    async def get_events(limit: int = 100) -> JSONResponse:
        """Bare-HTTP fallback for clients that can't speak WebSocket
        (eg the pytest harness). Returns the most recent N events.
        """
        s = get_state()
        limit = max(1, min(EVENT_BUFFER_CAP, limit))
        events = list(s.events)[-limit:]
        return JSONResponse({"events": events})

    # ------------------------------------------------------------------
    # Chat input + IPC round-trip (B4)
    # ------------------------------------------------------------------

    @app.post("/api/chat")
    async def post_chat(request: Request) -> JSONResponse:
        """Write a chat message to the IPC inbox per WA1 contract v1.
        The spec_id we use is timestamp-based so successive messages
        don't collide. The consumer (WA4 daemon or the stub responder)
        polls inbox for .ready markers and writes a closeout to outbox.
        """
        s = get_state()
        try:
            body = await request.json()
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="invalid JSON body")
        text = (body or {}).get("text", "")
        if not isinstance(text, str) or not text.strip():
            raise HTTPException(status_code=400, detail="`text` required")
        spec_id = f"chat_{int(time.time() * 1000)}"
        spec_body = (
            "# Dashboard chat message\n\n"
            f"From: at-desk dashboard\n"
            f"Sent: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\n\n"
            "---\n\n"
            f"{text}\n"
        )
        s.ipc.write_spec(spec_id, spec_body)
        return JSONResponse({"ok": True, "spec_id": spec_id})

    @app.get("/api/outbox")
    async def get_outbox() -> JSONResponse:
        """Return the list of completed closeouts (the wrapper / stub
        responder's replies). Read-only — the dashboard never consumes
        markers (the spec convention: only the daemon consumes); the
        UI polls this and decides what to render.
        """
        s = get_state()
        replies = []
        for spec_id in s.ipc.list_completed_closeouts():
            try:
                body = s.ipc.read_closeout(spec_id)
            except OSError:
                body = "<read error>"
            replies.append({"spec_id": spec_id, "body": body})
        return JSONResponse({"replies": replies})

    # ------------------------------------------------------------------
    # Quota / model / cost panel (B5)
    # ------------------------------------------------------------------

    @app.get("/api/quota")
    async def get_quota() -> JSONResponse:
        s = get_state()
        return JSONResponse(s.quota.snapshot())

    @app.post("/api/quota/observation")
    async def post_quota_observation(request: Request) -> JSONResponse:
        """Ingest a `claude -p --output-format json` result. WA4 (or
        the test harness) POSTs the parsed result; we update quota +
        per-session telemetry.
        """
        s = get_state()
        try:
            result = await request.json()
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="invalid JSON body")
        if not isinstance(result, dict):
            raise HTTPException(status_code=400, detail="result must be an object")
        diff = update_from_claude_result(s.quota, result)
        return JSONResponse({"ok": True, "diff": diff})

    @app.post("/api/quota/clear")
    async def post_quota_clear() -> JSONResponse:
        s = get_state()
        clear_throttle(s.quota)
        return JSONResponse({"ok": True})

    return app
