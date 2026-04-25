"""
WebSocket manager for live vote-tally broadcasts.

Clients connect to  /ws/proposals/{proposal_id}  and receive JSON messages
whenever a vote is cast or retracted while the proposal is in voting phase.

Message format:
  { "type": "tally_update", "proposal_id": "...", "yes": 5, "no": 3, ... }
"""

import json
import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from fastapi import WebSocket

if TYPE_CHECKING:
    from delegation_engine import ProposalTally

log = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        # proposal_id -> list of active WebSocket connections
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)

    async def connect(self, proposal_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[proposal_id].append(websocket)
        log.debug("WS connected: proposal=%s total=%d", proposal_id, len(self._connections[proposal_id]))

    def disconnect(self, proposal_id: str, websocket: WebSocket) -> None:
        conns = self._connections.get(proposal_id, [])
        if websocket in conns:
            conns.remove(websocket)
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

        dead: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self.disconnect(proposal_id, ws)


manager = ConnectionManager()
