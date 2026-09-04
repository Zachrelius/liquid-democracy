"""
WebSocket manager for live vote-tally broadcasts.

Clients connect to  /ws/proposals/{proposal_id}  and receive JSON messages
whenever a vote is cast or retracted while the proposal is in voting phase.

Message format:
  { "type": "tally_update", "proposal_id": "...", "yes": 5, "no": 3, ... }
"""

import asyncio
import time
import json
import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from fastapi import WebSocket, WebSocketDisconnect, HTTPException
from starlette.concurrency import run_in_threadpool

if TYPE_CHECKING:
    from delegation_engine import ProposalTally

log = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        # proposal_id -> list of active WebSocket connections
        self._validators = {}
        self._locks = {}
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)

    def register(self, proposal_id: str, websocket: WebSocket, validator) -> None:
        """Phase 38 B2 — register an already-accepted socket. The route
        handler accepts + auth-handshakes before calling this; the
        manager no longer accepts the socket itself so the gate runs
        before any tally_update messages can flow.
        """
        self._validators[websocket] = validator
        self._locks[websocket] = asyncio.Lock()
        self._connections[proposal_id].append(websocket)
        log.debug("WS connected: proposal=%s total=%d", proposal_id, len(self._connections[proposal_id]))

    def disconnect(self, proposal_id: str, websocket: WebSocket) -> None:
        conns = self._connections.get(proposal_id, [])
        if websocket in conns:
            conns.remove(websocket)
        if not conns:
            self._connections.pop(proposal_id, None)
        self._validators.pop(websocket, None)
        self._locks.pop(websocket, None)
        log.debug("WS disconnected: proposal=%s total=%d", proposal_id, len(conns))

    async def broadcast_tally(self, proposal_id: str, tally: "ProposalTally") -> None:
        conns = list(self._connections.get(proposal_id, []))
        if not conns:
            return

        # Method-aware payload — binary surfaces yes/no/abstain pcts; approval
        # and ranked_choice surface ballots-cast counts so the frontend can
        # render any voting method.
        msg: dict = {
            "type": "tally_update",
            "proposal_id": proposal_id,
            "not_cast": tally.not_cast,
            "total_eligible": tally.total_eligible,
        }
        if hasattr(tally, "yes") and hasattr(tally, "no"):
            msg.update(
                yes=tally.yes,
                no=tally.no,
                abstain=tally.abstain,
                yes_pct=round(tally.yes_pct, 4),
                no_pct=round(tally.no_pct, 4),
                abstain_pct=round(tally.abstain_pct, 4),
            )
        if hasattr(tally, "total_ballots_cast"):
            msg["total_ballots_cast"] = tally.total_ballots_cast
        if hasattr(tally, "winners"):
            msg["winners"] = list(getattr(tally, "winners", []) or [])
        if hasattr(tally, "tied"):
            msg["tied"] = bool(getattr(tally, "tied", False))

        payload = json.dumps(msg)

        # Fixed-size batches bound fan-out tasks; each client has a send deadline.
        for offset in range(0, len(conns), BROADCAST_CONCURRENCY):
            await asyncio.gather(*(
                self._send(proposal_id, ws, payload)
                for ws in conns[offset:offset + BROADCAST_CONCURRENCY]
            ))

    async def validate(self, proposal_id, ws):
        lock = self._locks.get(ws)
        if lock is None:
            return False
        async with lock:
            return await self._validate_unlocked(proposal_id, ws)

    async def _validate_unlocked(self, proposal_id, ws):
        validator = self._validators.get(ws)
        try:
            code, expires = await validator() if validator else (4401, 0)
            if not code and expires <= time.time():
                code = 4401
        except Exception:
            code = 1011
        if code:
            self.disconnect(proposal_id, ws)
            await safe_close(ws, code)
            return False
        return True

    async def _send(self, proposal_id, ws, payload):
        lock = self._locks.get(ws)
        if lock is None:
            return
        async with lock:
            if ws not in self._validators:
                return
            if not await self._validate_unlocked(proposal_id, ws):
                return
            if ws not in self._validators:
                return
            try:
                await asyncio.wait_for(ws.send_text(payload), SEND_TIMEOUT)
            except Exception:
                self.disconnect(proposal_id, ws)
                await safe_close(ws, 1011)


manager = ConnectionManager()


HANDSHAKE_TIMEOUT = 5.0
HANDSHAKE_MAX_BYTES = 8192
IDLE_CHECK_SECONDS = 30.0
SEND_TIMEOUT = 2.0
BROADCAST_CONCURRENCY = 8


def get_websocket_session_factory():
    """Inject the factory, never a session spanning the socket lifetime."""
    from database import SessionLocal
    return SessionLocal


def check_access(session_factory, proposal_id, token=None):
    """All ORM work stays in one worker thread and one closed transaction."""
    import auth
    import models
    from eligibility import eligible_viewers_for_proposal
    from jose import jwt, JWTError
    from settings import settings

    try:
        with session_factory() as db:
            proposal = db.get(models.Proposal, proposal_id)
            if proposal is None:
                return 4404, 0
            if token is None:
                return 0, 0
            try:
                payload = jwt.decode(token, settings.secret_key, algorithms=[auth.ALGORITHM])
                expires = float(payload["exp"])
                if not expires > time.time():
                    return 4401, 0
                user = auth._get_user_from_token(token, db)
            except (JWTError, HTTPException, KeyError, TypeError, ValueError, OverflowError):
                return 4401, 0
            if not user.is_admin and user.id not in eligible_viewers_for_proposal(
                db, proposal, user_id=user.id,
            ):
                return 4403, 0
            return (0, expires) if expires > time.time() else (4401, 0)
    except Exception:
        # Never expose database errors or credentials through close reasons/logs.
        return 1011, 0


async def safe_close(ws, code):
    try:
        await asyncio.wait_for(ws.close(code=code), SEND_TIMEOUT)
    except Exception:
        pass


async def serve_proposal_socket(ws, proposal_id, session_factory, manager):
    try:
        code, _ = await run_in_threadpool(check_access, session_factory, proposal_id)
        if code:
            await safe_close(ws, code)
            return
        await ws.accept()
        try:
            raw = await asyncio.wait_for(ws.receive_text(), HANDSHAKE_TIMEOUT)
            if len(raw.encode("utf-8")) > HANDSHAKE_MAX_BYTES:
                raise ValueError("oversized")
            handshake = json.loads(raw)
            token = handshake.get("auth") if isinstance(handshake, dict) else None
            if not isinstance(token, str) or not token:
                raise ValueError("missing")
        except (asyncio.TimeoutError, ValueError, TypeError, KeyError):
            await safe_close(ws, 4401)
            return

        async def validator():
            return await run_in_threadpool(check_access, session_factory, proposal_id, token)

        code, expires = await validator()
        if code:
            await safe_close(ws, code)
            return
        manager.register(proposal_id, ws, validator)
        while True:
            timeout = max(0.001, min(IDLE_CHECK_SECONDS, expires - time.time()))
            try:
                frame = await asyncio.wait_for(ws.receive(), timeout)
                if frame["type"] == "websocket.disconnect":
                    return
                # No client messages are part of the subscribed protocol.
                if frame["type"] == "websocket.receive":
                    await safe_close(ws, 4400)
                    return
            except asyncio.TimeoutError:
                pass
            if not await manager.validate(proposal_id, ws):
                return
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(proposal_id, ws)
