# WA3 — At-Desk Dashboard

**Status:** Spec, dispatched [pending]. Written 2026-05-30. Workflow-automation track (read `workflow-automation/workflow_automation_overview.md` first).

Combined dispatch framing + spec body. This builds the **at-desk interface** Z asked for: a local web dashboard to *watch the work/thought process* and (eventually) talk to the planner — the rich desk-side counterpart to the lean Slack phone channel (WA6). It's de-risked by WA2's P3 result (the disler hook seam streams full tool input/output/duration) and builds on WA1's state format. It needs no daemon and no June-15 quota change: the hook stream works on *any* Claude Code session, so this gives Z a live view of the **current website Code team's work right away**, and becomes the window onto the WA4 daemon later. Runs local-only; light on quota.

---

## Dispatch framing

### Goal

A self-contained local web dashboard (browser at `localhost:<port>`) with four panels:

1. **Live activity / thought stream** — Claude Code hook events (PreToolUse/PostToolUse and friends) rendered as they happen: tool name, inputs, outputs, durations, and any agent/subagent tree. (WA2 P3 proved the event shape carries all of this.)
2. **State panel** — the current planner/loop state read from WA1's state files: current phase, pending, blocked, recent decisions, last Code activity. Read-only render of the WA1 bootstrap/state.
3. **Chat input box** — a text box that writes Z's message to the WA1 IPC inbox and displays any reply that lands in the outbox. The consumer (the WA4 daemon) doesn't exist yet, so this is built + tested against a stub responder and left forward-compatible with the WA1 IPC contract.
4. **Quota / model / cost panel** — surface throttle state (detect WA2's pattern-matchable "out of extra usage · resets HH:MM" string) and, per session, the model in use and token/cost telemetry from the `claude -p` JSON. This is first-class, not an afterthought — it's how Z sees burn rate and throttling live (directly serves the June-15 quota concern and the model-flexibility hedge).

This pass builds the dashboard + its hook collector. It does NOT build the daemon, the planner loop, the Slack channel, or any `claude -p` dispatch.

### Branch + merge

Branch: `wa-3/at-desk-dashboard`. `--no-ff` merge to master. No Railway deploy (this track never deploys to website infra).

### Verification matrix

| Check | Required | Notes |
|---|---|---|
| **Live hook stream renders** | ✅ | Configure Claude Code hooks → run a real Code session → confirm events render live in the dashboard with tool input/output/duration. |
| **State panel renders WA1 state** | ✅ | Point at a WA1 state dir (use a fixture or a real one) → confirm phase/pending/blocked/decisions render correctly. |
| **Chat input round-trips via IPC** | ✅ | Input box writes to the WA1 inbox per the contract; a stub responder writes to the outbox; dashboard displays the reply. Asserts the *side effect* (file written to the right place per IPC contract v1), not just a UI event. |
| **Quota-wall detection** | ✅ | Feed a captured "out of extra usage" result → dashboard shows a clear throttled/reset indicator. |
| **Model + token/cost surfaced** | ✅ | Per-session model name + token/cost telemetry from `claude -p --output-format json` rendered in the quota panel. |
| Manual browser verification | ✅ | Dev (and/or Z) opens `localhost:<port>`, confirms all four panels. Capture screenshots for the closeout. |
| Website backend pytest | ⚠️ Only if shared | Not expected to apply (separate worktree, no website imports). State the reasoning, as WA1 did. |
| PG smoke / Railway / bundle | ❌ N/A | No website code, no migration, no deploy. State explicitly. |
| File-count | ✅ | All under `workflow-automation/`. |

### Suggested team structure

Lead + one full-stack dev (this has a real, if small, web UI). **Continuing dev team.** ~3–5 hours. Note for the team: this is a *local developer tool*, not the website — it lives under `workflow-automation/`, never touches `backend/`/`frontend/`, and has no deploy. A worktree (as WA1 used) keeps it cleanly parallel to website work.

### Sequence

1. Hook event collector — a local WebSocket server that ingests Claude Code hook events (B1).
2. State panel — read + render WA1 state (B2).
3. Activity-stream UI — render the live event feed (B3).
4. Chat input plumbing — write to IPC inbox, display outbox replies, stub responder (B4).
5. Quota / model / cost panel — throttle detection + per-session model/token render (B5).
6. Manual browser verification + screenshots (B6).
7. Merge.

### Load-bearing decisions

- **Adapt the disler `claude-code-hooks-multi-agent-observability` seam; don't reinvent the stream.** WA2 P3 validated it. Borrow the hooks→WS→UI structure; trim to what we need.
- **Single self-contained app.** Small Python server (FastAPI/Flask + WebSocket) + one HTML page (vanilla JS or minimal; CDN allowed per the artifact rules). No heavy frontend build, no bundler — keep it a tool, not a product.
- **Read-only on planner state; write-only to the IPC inbox.** The dashboard renders WA1 state but never mutates it; the chat box writes to the inbox per IPC contract v1 and nothing else. No other side effects.
- **Forward-compatible, daemon-optional.** Everything works watching current Code sessions today. When the WA4 daemon exists, it becomes the stream source + the inbox consumer with no dashboard rewrite.
- **Quota/cost visibility is a feature, not telemetry trivia.** It's how Z manages the June-15 quota risk and sees when the model-flexibility hedge should kick in.
- **Local-only, no secrets in the UI.** Binds to localhost; never renders tokens/keys; if events contain sensitive args, redact in the collector.

### Operational watch-outs

- **Hook configuration is per-Code-session / per-settings.** Document exactly how to enable the hooks (settings file + event types) so Z can point the dashboard at any Code session. Note whether it's project- or user-scoped.
- **Port + bind.** Pick a fixed localhost port (document it); bind to 127.0.0.1 only.
- **Stub responder for the chat box.** The real consumer is WA4; build + test against a stub that echoes/acks so the round-trip is verifiable now.
- **Event volume.** A busy Code session emits many hook events; the UI should handle a steady stream without locking up (cap retained history / virtualize the list if needed).
- **Don't couple to a specific daemon shape.** WA4's design may still shift; bind only to the WA1 state format + IPC contract v1, which are fixed.

### Closeout reports back

- What each panel renders; screenshots of the live dashboard against a real Code session.
- Hook-enablement steps (settings + event types) + the localhost port.
- Chat-box round-trip result (inbox write + stub outbox reply displayed).
- Quota-wall indicator + model/token render confirmation.
- Files (all under `workflow-automation/`); branch + commits; "no migration / Railway / bundle — N/A."

---

## Status block

WA2 de-risked this pass: P3 confirmed Claude Code hooks emit a clean PreToolUse/PostToolUse stream with full tool input, output, and duration — the disler seam is viable. Combined with WA1's fixed state format and IPC contract v1, the dashboard has stable inputs to build against with no daemon present. It delivers value immediately (a live window onto the current website Code team's work) and becomes the at-desk window onto the WA4 daemon later. The quota/model/cost panel is deliberately first-class because of the live June-15 uncertainty: Z needs to see burn and throttling, and to see when a cheaper model has been slotted into a role (the model-flexibility hedge).

## Locked decisions

- **D1 — Adapt the disler hook-observability seam** (WA2 P3-validated); don't reinvent.
- **D2 — Single self-contained local app** (Python WS server + one HTML page; localhost-only).
- **D3 — Read-only on WA1 state; write-only to the IPC inbox** per contract v1; no other mutations.
- **D4 — Daemon-optional + forward-compatible:** works on current Code sessions now; the WA4 daemon slots in as stream source + inbox consumer later.
- **D5 — Quota/model/cost is a first-class panel.**
- **D6 — No secrets in the UI; redact sensitive event args in the collector.**

## What this pass IS

A local web dashboard (hook-event collector + four-panel UI) under `workflow-automation/`, watching live Claude Code activity, rendering WA1 planner state, round-tripping a chat message through the IPC inbox/outbox (stub consumer), and surfacing quota/throttle + per-session model/token state.

## What this pass is NOT

- Not the orchestrator daemon / planner loop (WA4) — the chat box's real consumer.
- Not the Slack phone channel (WA6).
- Not the QA agent (WA5).
- Not any `claude -p` dispatch, and not a touch of website app code, migrations, or deploy.

## Cluster B — Build

- **B1 — Hook event collector.** Local WebSocket server ingesting Claude Code hook events; normalize to a small event schema; redact sensitive args. Document hook enablement.
- **B2 — State panel.** Read WA1 state dir; render phase/pending/blocked/decisions/last-activity (reuse WA1's bootstrap renderer where possible).
- **B3 — Activity-stream UI.** Live feed of events (tool, inputs, outputs, duration, agent/subagent grouping); handle steady volume.
- **B4 — Chat input.** Write message to the WA1 IPC inbox per contract v1; poll/display outbox replies; stub responder for the round-trip test.
- **B5 — Quota / model / cost panel.** Detect the WA2 quota-wall string + reset time → throttled indicator; render per-session model + token/cost from `claude -p` JSON.
- **B6 — Verification.** Live hook render against a real Code session; state-fixture render; IPC round-trip; quota indicator; manual browser pass + screenshots.

## Operational notes

- Match repo Python conventions; keep the whole thing under `workflow-automation/` (e.g., `workflow-automation/dashboard/`).
- CDN imports allowed for the single HTML page (Chart.js/Grid.js are fine if useful); no bundler.
- The dashboard is the first WA artifact Z interacts with directly — prioritize legibility of the activity stream and the state/quota panels over feature breadth.

## Followups

- WA4 daemon binds to this dashboard as its stream source + chat-input consumer (replacing the stub responder); confirm the IPC contract matched.
- Quota/model panel feeds the cost-management decision once June-15's real pool size is known.
- If Z wants the dashboard to also drive actions (pause/resume the loop, approve a dispatch), that's a WA4-era enhancement once there's a daemon to act on them.
