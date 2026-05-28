# WebSocket Status — `/ws/proposals/{id}`

**Status (2026-05-28):** Backend plumbing complete; **frontend does not consume**. The endpoint is dead-end from the user-facing surface.

## Backend shape (Phase 38 B2 hardened)

- `WS /ws/proposals/{proposal_id}` accepts a token via subprotocol or `?token=` query, validates via `auth.get_current_user_from_ws_token`, returns close codes:
  - 4401 — missing or invalid token
  - 4403 — token valid but caller not eligible to view this proposal (uses the same `_eligible_viewers_for_proposal` predicate as the HTTP list / get endpoints)
  - 4404 — proposal not found
- After successful handshake the connection passively waits for `WebSocketDisconnect` — no inbound message loop, no per-client server-push state.
- `backend/main.py::ConnectionManager` maintains a `{proposal_id: set[WebSocket]}` map (in-memory, single-worker per Phase 40 B3 startup assert).
- `routes/votes.py::cast_vote` (and the org-scoped equivalent) calls `ws_manager.broadcast_tally(proposal_id, ...)` after each successful vote, pushing a `{type: "tally_updated", ...}` JSON envelope to all currently-connected clients on that proposal.

## Frontend status

- `grep -r 'WebSocket\|/ws/' frontend/src` returns **zero hits** (verified 2026-05-28).
- Live tally updates on the proposal results page happen via HTTP refetch — either the user navigates away and back, or specific UI interactions trigger a `/api/proposals/{id}/results` re-poll. There is no FE component opening a WS connection to receive `tally_updated` push messages.
- The Phase 22 Support Trajectory Chart endpoint (`/api/proposals/{id}/trajectory`) uses the same HTTP-refetch pattern (with a 30-second Cache-Control window for voting proposals); WebSocket-driven live chart updates are not wired.

## Why the plumbing exists

The endpoint was added pre-pilot under the assumption that live tally updates were a near-term FE feature. Phase 38 B2 retroactively closed the unauth-anyone-can-listen gap that existed in the original plumbing (was: accept-then-read; now: validate-then-accept). The hardening was load-bearing for security regardless of whether the FE ever wires it.

## Decision needed: wire / delete / leave

Three options:

1. **Wire it.** Add a `useWebSocketTally(proposalId)` hook in FE, subscribe on results-page mount, drive a live-update banner or auto-refresh state. ~3-4 hours of frontend work + design pass for what "live update" UX should look like (does the chart re-render? does a "+1 vote" toast appear? does the page just silently update?). Real product decision — out of scope for hygiene passes.

2. **Delete the plumbing.** Remove `WS /ws/proposals/{id}` from `main.py`, delete `ws_manager` from `backend/main.py`, delete `broadcast_tally` calls from `routes/votes.py` (and the org-scoped equivalent). ~30 minutes of cleanup + small test updates. Reasonable hygiene choice if no FE wiring is on the near roadmap.

3. **Leave as-is, documented (current default).** This file documents the gap. Future contributors can find this doc before re-investigating "why doesn't live tally work?" Cost: backend carries dead-but-secure code; broadcast_tally cycles do small no-op work after each vote (no listeners → empty set iteration).

**Phase 41 disposition: option (3) — leave-and-document.** Reason: FE wiring is a real product feature (interaction design + live-update UX call) that deserves its own pass with Z input. Delete-the-plumbing has a small structural value (-50 lines) but defers a decision that benefits from product framing rather than hygiene framing.

When a future pass adds live-tally-update UX, this file is the trigger to either (a) wire the existing endpoint or (b) confirm the dead-end-plumbing teardown if the new UX uses a different mechanism (e.g., Server-Sent Events instead of WebSocket).
