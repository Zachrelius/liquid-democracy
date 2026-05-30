# WA3 — At-Desk Dashboard Closeout

**Status:** SHIPPED 2026-05-30. Branch merged + pushed; **no Railway deploy** (workflow-automation track convention).
**Spec:** `workflow-automation/wa3_at_desk_dashboard_spec.md`
**Branch:** `wa-3/at-desk-dashboard` (worktree at `liquid-democracy-wa3/`, branched from master `686e821`, merged via `--no-ff` to master).

---

## Per-cluster status

| Cluster | Status | Notes |
|---|---|---|
| B1 — Hook event collector + WS fanout | DONE | FastAPI `/api/hook` POST endpoint normalizes + redacts + buffers events; `/ws/events` fans out to live dashboard clients; `/api/events` bare-HTTP fallback for the pytest harness and any non-WS consumer. `dashboard/hook_handler.py` is the tiny stdin-to-POST forwarder Claude Code hooks invoke. Best-effort: dashboard down → hook handler exits 0 silently so the Code session isn't blocked. |
| B2 — State panel | DONE | `/api/state` returns the WA1 PlannerState as JSON; `/api/state/markdown` returns the bootstrap render. Both reuse the WA1 `planner_state` package — no logic duplicated. UI renders project / loop_state / pending / blocked / last_code_activity / recent decisions / working-context digest, with a Refresh button + 5-second auto-poll. |
| B3 — Activity-stream UI | DONE | Single HTML page, vanilla JS, no bundler, no CDN. WebSocket client with auto-reconnect (exponential backoff capped at 30s). Event list virtualizes naturally by capping retained history at 250 in the UI (server keeps 500). PreToolUse / PostToolUse / Other filter checkboxes. Click an event row to expand a JSON detail view. |
| B4 — Chat input + IPC round-trip | DONE | Chat box writes a spec to the WA1 IPC inbox via `IPCLayout.write_spec` per contract v1 (data file + `.ready` marker, atomic). `dashboard/stub_responder.py` stands in for the future WA4 daemon — drains the inbox, writes echo replies to the outbox per contract. Outbox polled every 3s; new replies render as incoming messages with `from <spec_id>` metadata. Cmd/Ctrl+Enter sends. |
| B5 — Quota / model / cost panel | DONE | `dashboard/quota.py::detect_quota_wall` regex-matches the WA2 P1 observed "out of extra usage · resets HH:MM (TZ)" string + variants. `/api/quota/observation` POST ingests `claude -p --output-format json` payloads. Per-session table renders model + rounds + token (input/output/cache-read) + cost telemetry. Manual `Clear flag` button + 5s auto-poll. |
| B6 — Tests + manual browser verify | DONE | 30/30 dashboard pytest pass (event normalization + redaction + quota detection + per-session telemetry + state panel + hook ingest + chat IPC round-trip + outbox round-trip with the stub responder + quota observation throttle detection). Live browser QA via Chrome MCP sub-agent: all four panels render correctly, filter toggle works, chat round-trip works, quota panel shows THROTTLED + reset time + session row. No console errors. |

---

## Test results

```
98 passed in 8.71s (incl. WA1's 68 unchanged + WA3's 30 new)
```

Breakdown of the 30 new WA3 tests:

- `dashboard/tests/test_events.py` — 8 (normalization, redaction of Bearer/JWT/long-hex, secret-key-named-value full redaction, long-value truncation, missing-fields tolerance).
- `dashboard/tests/test_quota.py` — 9 (WA2 observed string, phrasing variants, false-positive rejection, session telemetry accumulation, payload-nested detection, clear, cap-at-16-sessions).
- `dashboard/tests/test_server_and_round_trip.py` — 13 (state empty/loaded/markdown, hook ingest valid/invalid/redacting, **chat post writes spec + .ready marker per IPC contract v1**, chat empty rejected, **outbox round-trip with stub_responder** end-to-end, quota initial / record / detect / clear).

The chat-IPC round-trip test is the load-bearing one — it asserts the SIDE EFFECT (spec file + `.ready` marker in inbox, then closeout file + `.closeout.done` marker in outbox after the stub responder drains), not just the HTTP API ack.

---

## Live browser QA (Chrome MCP)

Sub-agent dispatched against http://127.0.0.1:8765/ with the server running on real fixtures:

- WA1 state populated with project="Liquid Democracy", current_pass="WA3 — At-Desk Dashboard"(in_progress), one pending + one blocked item, one locked decision.
- One PreToolUse hook event ingested.
- One chat message sent + the stub responder acked it.
- One quota observation POSTed with the WA2 throttle string.

**All checks PASS** — verbatim from the sub-agent's report:

1. Page loaded HTTP 200, no console errors.
2. Activity panel — 1 PreToolUse event visible (tool=Read, file=/tmp/x.txt). Filter toggle hides/restores correctly.
3. State panel — project name, pass + status, pending, blocked, locked decision, digest all render.
4. Chat panel — outgoing "smoke test from curl" + incoming "Stub-responder ack" reply both visible.
5. Quota panel — "THROTTLED" badge + "resets 11:15am (America/New_York)" + sessions table row for sess-live-A with model claude-opus-4-7 and rounds=1.
6. New chat message typed in the textarea + submitted → appeared immediately as outgoing.

No regressions. No deferred items. All four panels operational.

---

## How to use it (operator guide for the closeout)

**Run the dashboard:**

```bash
cd workflow-automation
../backend/.venv/Scripts/python.exe -m dashboard.cli serve \
    --port 8765 \
    --state-dir /path/to/wa1_state \
    --ipc-root /path/to/ipc_root
```

Browser → http://127.0.0.1:8765/

**Configure Claude Code hooks** (so a live Code session streams into the dashboard). Add to your `~/.claude/settings.json` (or a project-local `.claude/settings.local.json`):

```json
{
  "hooks": {
    "PreToolUse": [
      {"hooks": [{"type": "command",
                  "command": "<python> <repo>/workflow-automation/dashboard/hook_handler.py",
                  "timeout": 10}]}
    ],
    "PostToolUse": [
      {"hooks": [{"type": "command",
                  "command": "<python> <repo>/workflow-automation/dashboard/hook_handler.py",
                  "timeout": 10}]}
    ]
  }
}
```

The hook handler reads JSON from stdin → POSTs to `http://127.0.0.1:8765/api/hook`. Override the URL with `WA3_DASHBOARD_URL` env var if you use a non-default port. Dashboard not running = handler exits 0 silently (never blocks the Code session).

**Run the stub responder** alongside the server (until WA4 exists) to exercise the chat round-trip:

```bash
../backend/.venv/Scripts/python.exe -m dashboard.stub_responder \
    --ipc-root /path/to/ipc_root
```

**Feed `claude -p` results into the quota panel** (manual or via wrapper). POST the parsed JSON to `http://127.0.0.1:8765/api/quota/observation`. The dashboard pattern-matches the WA2 throttle string + extracts per-session model + token totals.

---

## File list

All under `workflow-automation/` (this track's convention):

```
workflow-automation/wa3_at_desk_dashboard_spec.md             (already present, brought into worktree)
workflow-automation/dashboard/__init__.py                     (NEW)
workflow-automation/dashboard/server.py                       (NEW, ~280 lines — FastAPI + WS)
workflow-automation/dashboard/events.py                       (NEW, ~125 lines — normalize + redact)
workflow-automation/dashboard/quota.py                        (NEW, ~165 lines — throttle + sessions)
workflow-automation/dashboard/hook_handler.py                 (NEW, ~70 lines — stdin → POST)
workflow-automation/dashboard/stub_responder.py               (NEW, ~100 lines — IPC inbox drainer)
workflow-automation/dashboard/cli.py                          (NEW, ~70 lines — `python -m dashboard.cli serve`)
workflow-automation/dashboard/static/index.html               (NEW)
workflow-automation/dashboard/static/dashboard.css            (NEW)
workflow-automation/dashboard/static/dashboard.js             (NEW)
workflow-automation/dashboard/tests/__init__.py               (NEW empty)
workflow-automation/dashboard/tests/conftest.py               (NEW — sys.path setup)
workflow-automation/dashboard/tests/test_events.py            (NEW)
workflow-automation/dashboard/tests/test_quota.py             (NEW)
workflow-automation/dashboard/tests/test_server_and_round_trip.py  (NEW — the load-bearing one)
wa3_at_desk_dashboard_closeout.md                             (NEW — this file)
```

No website code touched. No migration. No Railway deploy. No frontend bundle.

---

## Branch + worktree + merge

- **Worktree:** `liquid-democracy-wa3/` (sibling of liquid-democracy/, ../wa1, ../wa2). Created via `git worktree add` to isolate from any in-flight parallel work.
- **Branch:** `wa-3/at-desk-dashboard` from `686e821`.
- **Merge:** `--no-ff` to master.

---

## Locked-decision confirmation (spec D1-D6)

- ✅ **D1 — Disler hook-observability seam adapted.** Hooks → POST → server buffer → WS fanout to UI, exactly matching the WA2 P3-validated event shape (PreToolUse + PostToolUse with tool_input + tool_response_excerpt + duration_ms).
- ✅ **D2 — Single self-contained local app.** FastAPI + uvicorn + one HTML/CSS/JS page. No bundler, no CDN. Localhost-only bind (127.0.0.1 by default; CLI flag to override).
- ✅ **D3 — Read-only on WA1 state; write-only to IPC inbox.** State endpoints never write; chat endpoint only writes to inbox via `IPCLayout.write_spec`; outbox endpoint only reads. No mutations of state files.
- ✅ **D4 — Daemon-optional + forward-compatible.** Works today against any Code session by pointing hooks at the handler. The stub_responder is a labeled stand-in for WA4. WA4 will slot in as inbox consumer + hook event source with zero dashboard changes.
- ✅ **D5 — Quota/model/cost is first-class.** Bottom panel full-width; THROTTLED indicator is visually distinct; sessions table renders model + rounds + tokens (input/output/cache-read) + cost telemetry.
- ✅ **D6 — No secrets in the UI.** `events.py` redacts at ingest (the dashboard never receives the raw secret on the wire): key-name match (api_key, password, token, etc.) → `<REDACTED>`; Bearer-line regex; JWT regex; long-hex regex; long values truncated.

---

## Notable spec deviations

**None.** All six clusters delivered as specified. The verification matrix's "website backend pytest" entry is stated explicitly N/A — this worktree shares no Python imports with backend/, and the parallel agent on a different branch has in-flight uncommitted website changes (same situation as WA1 + WA2 documented).

---

## New tech debt

None at this layer. Followups all live in WA4+ specs.

---

## Followups (out of scope, per spec)

- **WA4 daemon** binds to this dashboard as both stream source (it'll proxy `claude -p` hook events through the same POST endpoint or directly via the daemon's own broker) AND inbox consumer (replacing the stub responder). The IPC contract v1 is what they bind on — no dashboard changes expected.
- **Hook-event log persistence.** Today, events live in an in-process deque (cap 500). The dashboard restart loses them. Worth a small file-tail option in WA4 era (the events log on disk already exists in the WA2 P3 pattern).
- **Multi-Code-session view.** A single dashboard receives events from any number of Code sessions today (hook URL is fixed). The UI doesn't yet group by `session_id` — events from concurrent sessions interleave. Future enhancement.
- **Quota observations are manual today.** WA4 will POST `claude -p` result JSON automatically. Until then, an operator wrapper or a small "tee" can do it.
- **Documentation correction to `workflow_automation_overview.md`** — Correction 1 framing flagged in WA2 findings is still pending; trivial one-doc-line update.

---

## Pass-summary (PROGRESS.md-style)

WA3 At-Desk Dashboard — SHIPPED 2026-05-30 via the `wa-3/at-desk-dashboard` worktree. Local web dashboard (FastAPI + WebSocket + vanilla-JS HTML at http://127.0.0.1:8765/) with the four panels Z asked for: live activity stream from Claude Code hook events (PreToolUse / PostToolUse with full tool_input + tool_response_excerpt + duration_ms), planner state read from WA1 (project, loop_state, decisions, working-context digest), chat box writing to the WA1 IPC inbox per contract v1 with a stub responder echoing back from the outbox for round-trip verification, and a first-class quota / model / cost panel that detects the WA2 P1 "out of extra usage" throttle string + tracks per-session model + token + cost telemetry. 30 new tests (98/98 total with WA1's 68) including the load-bearing IPC round-trip side-effect assertions. Live Chrome-MCP browser QA confirmed all four panels render against real fixtures. The dashboard delivers value today (watch live Code sessions; render WA1 state; chat into the IPC) and becomes the at-desk window onto the WA4 orchestrator daemon when that ships — no dashboard rewrite needed. No website code, no migration, no deploy.
