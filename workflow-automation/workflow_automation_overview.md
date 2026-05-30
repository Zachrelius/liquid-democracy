# Workflow Automation — Overview & Architecture

**Status:** Planning doc. Written 2026-05-30. Owner: the workflow planning agent (separate from the liquiddemocracy.us feature-planning agent).

This is the anchor doc for the **workflow-automation track**: building a persistent autonomous planner/orchestrator that coordinates the Claude Code dev team so Z stops being the manual courier and can steer the work (at desk richly, from phone briefly). It supersedes the Cowork-scheduled-task design (`workflow_automation_handoff.md`, scrapped — stateless-per-tick violates the persistent-planner requirement) and refines the `agent_sdk_daemon_proposal.md` (the "embed the Agent SDK" framing is corrected below).

---

## This track is separate from website development

To avoid confusion with the website's `phaseXX_*` sequence:

- **Location:** everything for this track lives under `workflow-automation/` (docs + code).
- **Numbering:** a distinct sequence — `WA1`, `WA2`, … Spec files: `workflow-automation/waN_<short-name>_spec.md`. No dots in filenames (same rule as the website convention).
- **Branches:** `wa-N/short-name` (e.g., `wa-1/state-foundation`), not `phase-X-Y/...`.
- **Git:** same repo, same discipline — commit to branch, `--no-ff` merge to master, never force-push.
- **Verification is different:** this track does NOT touch website app code (`backend/`, `frontend/`), adds no Alembic migrations, and triggers no Railway deploy / PG smoke / frontend bundle. Its verification is the track's own tests + the validation each spec defines. A WA pass that somehow needs to touch website code is out of scope and should be flagged.
- **Tooling/runtime:** Python (consistent with the repo's scripts), runs on Z's Windows machine.
- **Repo split (decided 2026-05-30):** stay co-located in this repo through the validation passes (WA1/WA2) — lowest friction, the validation reuses this repo's context, Phase 42 artifacts already live here. **Split into a dedicated repo before the live daemon (WA4):** at that point the orchestrator is a separate project, its code shouldn't sit in the tree the Code agents edit, and it may orchestrate beyond Liquid Democracy. The IPC files (specs in, closeouts out) still land in *this* repo where Code works — that's the contract; the orchestrator code lives separately. Keep `workflow-automation/` self-contained meanwhile so extraction is a clean lift. (Splitting earlier is fine if preferred; cost is minor cross-repo setup for the validation passes.)

## The six goals (Z, 2026-05-29)

1. **Persistent** across tasks and messages — one planner with accumulated context, not respawned per task.
2. **Dispatch coding agents and hear back** from them.
3. **Max account, not API credits.**
4. **Planner and/or coding agent can dispatch QA agents** that drive a browser (Claude in Chrome "or similar").
5. **Easy passdown** to a fresh version when context fills.
6. **Phone communication** with Z (nice-to-have) — plus, per follow-up, a richer **at-desk interface** to watch the work/thought process.

## Two decisive research corrections (2026-05-30)

Prior-art research (web, May 2026) changed two load-bearing assumptions. Both improve the plan; both deserve Z's eyes.

**Correction 1 — Don't embed the Agent SDK; shell out to `claude -p`. (Goal 3) — CONFIRMED 2026-05-30 via live-docs research + OpenClaw precedent.**
Anthropic's compliance docs confirm **OAuth tokens from Free/Pro/Max accounts cannot be used with the Claude Agent SDK** ([support.claude.com Agent SDK + plan](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan), [code.claude.com legal-and-compliance](https://code.claude.com/docs/en/legal-and-compliance)) — the SDK requires a metered Console API key. So an "Agent SDK daemon authed via Max" is a ToS problem. **But the `claude -p` CLI headless IS sanctioned on a Max subscription** ([code.claude.com/headless](https://code.claude.com/docs/en/headless)) — exactly what Phase 42 ran on. So the orchestrator does all LLM work by **shelling out to `claude -p` subprocesses**, never embedding the SDK. Consequences:
  - **NOT blocked until June 15.** `claude -p` under Max works now (draws from interactive quota). **June 15 2026** moves programmatic `claude -p` / Agent-SDK usage to a *dedicated monthly credit pool* — Pro $20, Max 5x $100, Max 20x $200, per-user, non-rolling. So it ISOLATES orchestrator usage from interactive chat quota with a monthly ceiling (almost certainly plenty for our cadence) — not a build gate. (Env trap, per Phase 42: `ANTHROPIC_API_KEY` must be UNSET or it reverts to metered billing.)
  - **Corroborated by OpenClaw** (popular OSS personal-assistant daemon): it uses the same `claude -p`/CLI-subscription-reuse path, and its docs cite Anthropic staff confirming that usage is allowed. Real-world precedent, not just our doc reading.
  - **Caveat — policy churn:** Feb 2026 ban on subscription-OAuth-in-third-party-tools → May 2026 reversal for CLI reuse → June 15 credit restructure. Keep under watch; our `claude -p` design is on the safe side regardless. WA2 re-verifies from live docs at build time.

**Correction 2 — Autonomous QA uses Playwright MCP, not Claude-in-Chrome. (Goal 4)**
No open-source project drives the Claude-in-Chrome *extension* from a headless orchestrator — it's a desktop UX, awkward to automate unattended (Phase 42 also found Chrome MCP is absent in `claude -p`). The ecosystem has standardized on **Microsoft's `playwright-mcp`**, which runs headless and is the de-facto agent-QA browser layer. So: a dispatched `claude -p` QA agent uses **Playwright MCP** for autonomous verification. Claude-in-Chrome stays the tool for *interactive*, human/Code-driven QA (the existing website CLAUDE.md convention is unchanged). This is a slight reinterpretation of goal 4's wording ("or similar") and I want Z aware of it — flagged as an open confirmation, not assumed-settled.

## Architecture (corrected)

A thin **custom orchestrator daemon** plus borrowed components. Pieces:

- **Orchestrator daemon** — a long-lived Python process on Z's machine. It is *plumbing*, not an LLM: it holds loop/orchestration state in memory, checkpoints to disk, watches inboxes (dashboard input, Slack, Code closeouts), and dispatches work. Survives restarts by reloading from the WA1 state layer.
- **Planner brain** — a long-lived `claude -p --resume <planner_session>` session the daemon resumes for each planning reasoning step. Phase 42 proved `--resume` preserves full context across fresh-process invocations with zero drift (12/12 recall). *This is how goal 1 (persistent planner) is actually delivered* — the planner session accumulates the whole work-loop context and is replayed via `--resume`, which is real continuity, not lossy file-summary reconstruction. Max-legal.
- **Code agents** — dispatched `claude -p`, fresh per pass, `--resume` for within-pass back-and-forth (the Phase 42 pattern; `docs/workflow_spike_resume_findings.md`).
- **QA agents** — dispatched `claude -p` running Playwright MCP, headless, against the live site.
- **At-desk dashboard** — a local web UI (localhost) showing the live thought/tool-call stream + state + a chat input. Built by adapting the **hook-event → WebSocket → UI** pattern from `disler/claude-code-hooks-multi-agent-observability`.
- **Phone channel** — Slack (or Telegram/Discord) for brief input-needed questions and landmark updates ("phase landed"). Built by adapting **`cc-connect`**.
- **Durable state / checkpoint / passdown** — ours (WA1). Study LangGraph's checkpoint patterns. Serves goal 5 *and* makes the daemon and the planner session safe to rotate.

### Liveness vs. continuity (the synthesis, now grounded)

The daemon buys **liveness** — a process running between Z's messages that reacts to events (closeout landed, Slack message) with nobody poking it. That's the thing a turn-based Cowork agent can't do, and it's what makes goals 2 and 6 real. **Continuity** comes from the planner's `--resume` session (full-context replay, Phase-42-proven) — not from raw in-RAM persistence. When that session approaches context limits (Phase 42's defensive triggers: latency > 30s or cache-read tokens > 150k), the daemon **rotates** it: start a fresh planner session, bootstrap it from the WA1 checkpoint. So goals 1 and 5 are the same investment from two sides — the checkpoint layer that makes passdown effortless is what makes the long-lived planner safe and defuses Anthropic's "long sessions degrade" caution.

## At-desk interface decision

Z wants two channels, deliberately different:

- **At the desk (rich):** a **local web dashboard** served alongside the daemon. Shows the planner's and agents' live reasoning + tool-call stream (the "see the work" requirement), the current loop/phase state, what's pending/blocked, and a **chat box to converse with the planner** in real time. Adapt the disler hook-observability pattern for the stream; add a state panel + input box. Browser at `localhost:<port>`.
- **On the phone (lean):** Slack via a cc-connect-style bridge — only input-needed questions and brief landmarks (phase landed, blocked, needs-decision). Not the full stream.

Same daemon backend feeds both; the dashboard input box and Slack are just two inbox sources the daemon consumes. The dashboard is the answer to "I want to see more of the work/thought process at the computer."

## Build vs. adapt

No project to fork wholesale for our exact shape. Build the thin orchestrator + planner core ourselves (nothing does stateful long-running planning — they're per-task spawners or TUIs); borrow components.

| Need | Source | Disposition |
|---|---|---|
| Persistent planner core, `claude -p` dispatch, closeout capture, checkpoint/passdown (goals 1,2,5) | — | **Ours to build.** Study `affaan-m/claude-swarm` for `claude -p` dispatch wiring; LangGraph for checkpoint patterns. |
| At-desk dashboard / live thought stream (goal 6) | `disler/claude-code-hooks-multi-agent-observability` (hooks→WS→UI); alts: `simple10/agents-observe`, `hoangsonww/Claude-Code-Agent-Monitor` | **Adapt** the hook-event seam. |
| Phone channel (goal 6) | `chenhg5/cc-connect` (Slack/Telegram/Discord bridge, no public IP needed); alt: `mpociot/claude-code-slack-bot` | **Adapt.** |
| Messaging-gateway daemon / phone interface (goal 6) | `openclaw/openclaw` (model-agnostic personal-assistant gateway; talk via WhatsApp/Telegram/Discord/iMessage; uses `claude -p`/CLI-subscription reuse) | **Evaluate as a base for the phone/gateway layer** (or even run the orchestrator as an OpenClaw skill) vs. just borrowing patterns. Different category (general assistant, not a dev orchestrator; no cross-pass planning state), but its gateway IS goal 6, and it's our auth-model precedent. Decide during the phone-channel pass; don't couple the planner core to it. |
| Autonomous QA browser (goal 4) | `microsoft/playwright-mcp` (Apache-2.0, headless, mature) | **Adopt** as the QA agent's browser layer. |
| Dashboard + parallel dispatch reference | `BloopAI/vibe-kanban` (now community-maintained) | **Learn-from** (closest overall shape; don't fork — upstream abandoned). |
| Worktree isolation for parallel agents | Claude Squad / Conductor / Crystal | Learn-from if we ever run parallel Code agents. |
| General coding-agent frameworks | OpenHands, Goose, Aider, AutoGen/CrewAI/LangGraph | **Not a base** — model-agnostic, don't dispatch `claude -p`, would fight the Max-CLI constraint. LangGraph: checkpoint patterns only. |
| Anthropic Agent Teams (official) | proprietary | Watch; was Pro/Max-blocked as of Apr 2026. |

## Gates, risks, open unknowns

- **June 15 2026 — quota economics, not a build gate.** Build/validate now on Max quota (modest usage); heavy production usage benefits from the dedicated Agent-SDK credit pool then.
- **ToS confirmation.** Confirm the "no Agent SDK with OAuth; `claude -p` CLI on Max is fine" reading directly from Anthropic's current docs before heavy build. The `claude -p` path is safe regardless.
- **Planner-continuity-at-scale (the real goal-1 unknown).** Phase 42 proved `--resume` recall over 12 small rounds. Planning is more demanding (large specs/closeouts, long reasoning). WA2 must test a resumed planner session at *planning* scale over many rounds, and validate clean rotation. This is where Anthropic's degradation caution would show up if it's going to.
- **Playwright-MCP-from-`claude -p` (goal 4).** Likely fine (Phase 42 showed `.mcp.json` MCPs load in `-p`; Playwright MCP is just another server), but unconfirmed that a dispatched `claude -p` actually drives a headless browser against the live site. WA2 confirms.
- **Operational complexity.** Z's machine becomes load-bearing infra (daemon crashes, Windows reboots, extension/network blips). Mitigated by the checkpoint layer (restart → reload state) + robust failure handling (later WA pass).

## Roadmap

Pre-June-15 buildable now (on Max quota, no new metered spend):

- **WA1 — State & IPC foundation.** Durable planner-state schema, atomic checkpoint writer, fresh-instance bootstrap/recovery, passdown generator (goal 5), daemon↔Code-wrapper file-IPC contract. No-regret: also improves passdown for *today's* manual planner. Zero/low cost. → `wa1_state_and_ipc_foundation_spec.md`
- **WA2 — Architecture validation spike.** Confirm the corrected load-bearing pieces before building on them: planner-continuity-at-scale via `claude -p --resume` + rotation; Playwright-MCP-from-`claude -p` headless QA; the dashboard hook-observability pattern; a cc-connect-style Slack bridge; and read-the-docs confirmation of the auth/ToS picture. Runs on Max (like Phase 42), so no new metered spend. → `wa2_architecture_validation_spike_spec.md`

Then (WA2 result + WA1 foundation gate these):

- **WA3 — At-desk dashboard** (adapt disler pattern over the WA1 state format).
- **WA4 — Orchestrator daemon + planner-session core + Code dispatch** (the persistent brain; goals 1,2).
- **WA5 — Autonomous QA agent** (Playwright MCP; goal 4).
- **WA6 — Phone channel** (cc-connect-style Slack; goal 6).
- **WA7 — Full loop + failure handling + checkpoint/rotation hardening.**

WA1 and WA2 are dispatchable now. WA3+ get specced as WA2's findings land.
