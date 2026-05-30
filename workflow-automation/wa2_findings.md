# WA2 — Architecture Validation Spike — Findings

**Date:** 2026-05-30. Spec: `wa2_architecture_validation_spike_spec.md`. Branch `wa-2/arch-validation-spike` off master `b22d088`.

This doc is the contract back. Headline + per-probe verdicts + go/no-go + architecture adjustments for WA3+. Three harness scripts + their raw artifacts live under `workflow-automation/spike/`.

---

## Headline

**GO on the corrected architecture.** Shell out to `claude -p` (Max OAuth) + Playwright MCP for autonomous QA + hooks for the dashboard observability seam — all empirically validated. **One spec-anticipated finding bites: planner-continuity-at-planning-scale is QUOTA-constrained on Max pre-June-15.** Four planning-scale rounds at ~44k cache_read each exhausted the day's "extra usage" allowance. Within the four rounds that ran, coherence + cross-round recall were clean (no drift). **Architecture is correct; production cadence is quota-gated.** Detail below.

## Per-probe verdicts

| Probe | Verdict | Notes |
|---|---|---|
| P1 — Planner-continuity at planning scale | **PARTIAL PASS** | 4/10 resume rounds completed before the Max "out of extra usage" wall. Within those 4 rounds: tracker preserved, prior-round content cited correctly, no coherence drift. Rotation demo could not be exercised (quota wall hit mid-run). |
| P2 — Playwright MCP via `claude -p` | **PASS** | Dispatched `claude -p` loaded `@playwright/mcp@latest` from project-local `.mcp.json`, drove headless browser against `https://www.liquiddemocracy.us/`, returned a structured JSON pass/fail with all three checks `found: true`. 21.7s end-to-end. |
| Auth/ToS read-the-docs | **CORRECTS OVERVIEW** | The overview's "no Agent SDK with OAuth" framing is OUT OF DATE. Per current Anthropic docs, `claude -p` IS the Agent SDK in CLI form, and both subscription + API-key paths are supported. June 15 2026 just restructures quota (dedicated Agent-SDK credit pool separate from interactive). Architecture remains valid; the framing needs updating in `workflow_automation_overview.md`. |
| P3 — Dashboard hook stream | **PASS** | `PreToolUse` + `PostToolUse` hooks emitted clean event JSON (with `tool_input` + `tool_response`) to a local handler. The disler seam is viable for WA3. |
| P4 — Slack bridge | **DEFERRED** | No Slack workspace + connector available in this session. Protocol documented below; defer to WA6 where the workspace setup is in-scope. |

## P1 — Planner-continuity at planning scale (PRIMARY)

### Setup

`workflow-automation/spike/p1_planner_continuity_harness.py`. Seed context: the four track docs (`workflow_automation_overview.md`, `wa1_state_and_ipc_foundation_spec.md`, `wa2_architecture_validation_spike_spec.md`, `workflow-automation/README.md`) — ~42.8 KB total. Single `claude -p` session, `--resume <session_id>` for each subsequent round. Prompts piped via stdin (necessary on Windows — positional-arg cap is ~32 KB; the seed exceeds it).

### Results

10 rounds attempted. 4 completed before the quota wall:

| Round | Name | Elapsed (s) | cache_read tokens | Verdict |
|---|---|---|---|---|
| R1 | seed | 10.62 | 43,639 | seed established TRACKER correctly |
| R2 | recall + goal-risk identification | 8.89 | 43,639 | PASS — named goals 1, 2, 3 as the most-at-risk under Max-OAuth-incompatible change |
| R3 | apply Phase-42 invariant to code paths | 16.55 | 44,053 | PASS — mapped `ANTHROPIC_API_KEY` invariant to 5 distinct code/pass surfaces incl. WA1 D6 |
| R4 | cross-pass dependency mapping | 13.46 | 44,619 | PASS — listed WA4's dependencies + correctly noted "WA3/WA5/WA6/WA7 are downstream of WA4 per the roadmap, not upstream" |
| R5 | synthesis (would have referenced R2-R4) | 2.06 | 0 | **QUOTA WALL** — `result_text = "You're out of extra usage · resets 12:30pm (America/Port-au-Prince)"` |
| R6-R10 + rotation | n/a | ~2s each | 0 | Same quota error repeating |

Cache-read growth is linear and modest: +414 to +566 tokens per round on top of the cached seed. Within R1-R4 there is no observable drift; each round cited prior-round content correctly and built on it. The model in R3 even surfaced its own correct refusal pattern ("Naming a specific locked decision to justify a yes-or-no would be fabrication").

### Verdict + implication

**Within the rounds that ran, the `--resume` planner session held planning-scale context cleanly.** The mechanism works.

**The quota wall is the architectural blocker today, not session quality.** This is exactly the "rate-limit hit is itself a finding" the spec anticipated. Implications:

- **Pre-June-15:** the wrapper shares Max's interactive-usage quota with Z's normal Claude Code work. Heavy autonomous planning at scale will conflict with interactive use within a day's allowance. Manual orchestration + WA1's checkpoint-based passdown continues to be the operating mode.
- **Post-June-15 (per the headless docs we re-read this pass):** `claude -p` on subscription draws from a dedicated monthly Agent-SDK credit pool, separate from interactive limits. THAT'S when running the autonomous planner at production cadence becomes practical without competing with interactive sessions.
- **No coherence-driven rotation trigger.** The spec asked us to surface the degradation point if any. None observed in the 4 rounds. The rotation trigger for WA4 should be **token-budget / quota-driven**, not coherence-driven — rotate when cumulative `cache_read_input_tokens` approach a threshold the wrapper picks (e.g., 150k as the Phase 42 defensive trigger or whatever the post-June-15 credit-pool math suggests).

### What this means for WA3 / WA4

- WA4 (orchestrator daemon) implementation can proceed on the planned `claude -p --resume` foundation. The mechanism is sound.
- WA4's planner-rotation logic should key on **cumulative cache_read across rounds + a "I'm running low" probe** (e.g., catch the "out of extra usage" string in the result), NOT on coherence-drift detection (which we don't have evidence justifies a separate trigger).
- A useful WA4 sub-task surfaces: a **"quota check" pre-flight** that the daemon runs before dispatching a heavy planning round (cheap one-message probe; if it errors with the quota string, sleep until the reset time the message names).

## P2 — Playwright MCP via `claude -p` (PRIMARY)

### Setup

`workflow-automation/spike/p2_playwright_mcp_harness.py`. Project-local `.mcp.json`:

```json
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["@playwright/mcp@latest"]
    }
  }
}
```

No explicit `npx playwright install` step needed — the MCP's first invocation provisioned the browser. (`node v24.13.1`, `npm 11.8.0` on the machine.) Dispatched `claude -p --dangerously-skip-permissions --output-format json` with an inline read-only scenario (no `--bare`; we want the project-local MCP loaded).

### Results

The agent returned the expected JSON shape on first attempt:

```json
{
  "scenario": "ld_landing_page_smoke",
  "url": "https://www.liquiddemocracy.us/",
  "page_loaded": true,
  "checks": [
    {"name": "title_present", "expect": "Liquid Democracy", "found": true},
    {"name": "tagline_present", "expect": "Delegate your vote", "found": true},
    {"name": "login_link_present", "expect": "Log in or Login or Sign in (any case)", "found": true}
  ],
  "overall_pass": true,
  "evidence_excerpt": "Liquid Democracy — Vote directly or delegate to people you trust ..."
}
```

End-to-end elapsed: 21.71 s. Exit code 0. Read-only (no writes, no auth-gated surfaces hit). `evidence_excerpt` is the visible page text the agent actually read — confirms the headless browser drove rather than the agent guessing from memory.

### Verdict + implication

**Playwright MCP is the right autonomous-QA browser layer.** Drop-in: `npx @playwright/mcp@latest` works out of the box, project-local `.mcp.json` is honored by `claude -p` (no `--bare`), structured JSON output is reliable. WA5 (autonomous QA agent) builds on this directly — no infrastructure surprises.

A small operational note: the MCP's first run installs the browser binaries silently (probably to `%LOCALAPPDATA%/ms-playwright/` per Playwright's default). For CI / fresh-machine WA5 runs, document `npx playwright install --with-deps` as a one-time setup. Not necessary on this machine.

## Auth/ToS confirmation

Read sources (cited):

- [https://code.claude.com/docs/en/headless](https://code.claude.com/docs/en/headless) — "Run Claude Code programmatically. Use the Agent SDK to run Claude Code programmatically from the CLI, Python, or TypeScript." Note explicitly states: *"Starting June 15, 2026, Agent SDK and `claude -p` usage on subscription plans will draw from a new monthly Agent SDK credit, separate from your interactive usage limits."*
- [https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan) — confirms Agent SDK credit applies to subscription plan holders (Pro, Max, Team, Enterprise) after they claim their monthly credit. Distinguishes "Claude Platform accounts using an API key" (different billing).

### Where the overview is OUT OF DATE

The `workflow-automation/workflow_automation_overview.md` "Correction 1" section currently reads:

> "Anthropic's compliance docs confirm OAuth tokens from Free/Pro/Max accounts cannot be used with the Claude Agent SDK ... So an 'Agent SDK daemon authed via Max' is a ToS problem. But the `claude -p` CLI headless IS sanctioned on a Max subscription..."

The current Anthropic docs treat `claude -p` AS the Agent SDK (the headless page literally is titled *"Use the Agent SDK to run Claude Code programmatically from the CLI..."*). Subscription plans CAN use the Agent SDK. The Feb-2026-policy → May-2026-reversal → June-15-restructure timeline mentioned in the overview is consistent with what the docs show now, but the framing "no Agent SDK with OAuth" is no longer accurate. The architecture remains correct — we shell out to `claude -p` (which IS the SDK's CLI form), which works on Max OAuth. The overview's framing should be updated.

### Update to apply

Recommend a small follow-up commit (or fold into a WA1.1 revision) updating `workflow_automation_overview.md` "Two decisive research corrections" → "Correction 1" to say:

> "Use `claude -p` CLI (the headless form of the Agent SDK) — sanctioned on Max OAuth subscription per current docs. The Python/TypeScript SDK packages are also subscription-supported per the same docs; we still prefer the CLI form for subprocess isolation + env hygiene + reuse of Phase 42 patterns. June 15 2026 moves both `claude -p` and the Agent SDK packages on subscription to a dedicated monthly credit pool, separate from interactive limits."

Not strictly load-bearing for build; the architecture is unchanged. Flagged for documentation accuracy.

### `--bare` note (Phase 42 carry-forward, re-validated)

The headless docs say `--bare` **"skips OAuth and keychain reads. Anthropic authentication must come from `ANTHROPIC_API_KEY`."** That's the metered-billing trap. Phase 42 + WA1 + this spike all explicitly DON'T pass `--bare`. The headless docs note `--bare` "will become the default for `-p` in a future release" — when that happens, **our wrapper must explicitly skip `--bare`** (i.e., not blindly upgrade to whatever the new default is). Track as a watch-item.

## P3 — Dashboard hook stream (best-effort)

### Setup

`workflow-automation/spike/p3_dashboard_hook_stream_harness.py`. Wrote a project-local `.claude/settings.local.json` declaring `PreToolUse` + `PostToolUse` hooks pointing at a tiny Python handler that appends JSON-per-line to `hook_events.jsonl`. Dispatched `claude -p` with a small "read sample.txt" task in the same cwd.

### Results

Two events captured (one PreToolUse + one PostToolUse), both for the `Read` tool. Sample (truncated):

```json
{
  "hook_event_name": "PreToolUse",
  "session_id": "be6729e9-0269-4f6a-b056-6cd1024a4cfa",
  "cwd": "...wa2_p3_cwd",
  "tool_name": "Read",
  "tool_input": {"file_path": "...sample.txt"},
  "tool_use_id": "toolu_01TLddF8NDGzbiiu9SzdZHEz"
}
```

The PostToolUse event carries the full `tool_response` (with the file's content) and a `duration_ms` field — exactly what a dashboard needs to render "tool just ran, took N ms, here's what it did." The events stream cleanly via the simplest possible seam (script appending to a file). A WebSocket+UI on top is straightforward.

### Verdict

**The disler hook-observability seam is viable for WA3.** No surprises. WA3 spec can confidently bind to:

- `~/.claude/settings.json` (or project-local) for hook configuration.
- `PreToolUse` + `PostToolUse` + `SessionStart` + `Stop` as the core event set (the dashboard's MVP signals).
- The hook handler reads JSON from stdin → forwards to a WebSocket (or writes to a file the WebSocket server tails).
- Exit code semantics: 0 = no decision, 2 = block (with stderr surfaced). Dashboards write exit-0 handlers.

## P4 — Slack bridge (best-effort, DEFERRED)

No Slack workspace + bot token configured on this machine for this session. The protocol shape from `chenhg5/cc-connect` is well-documented (outbound: webhook POST; inbound: Slack Events API or polling; auth via bot token); the implementation belongs in WA6 where the workspace setup is the first step anyway. Documented as the deferral; not a finding.

If Z wants to validate the bridge ahead of WA6, the WA6 spec can carry a short "prove the round-trip works before building the bridge" sub-task — same shape as P1/P2/P3 here.

## Architecture adjustments for WA3+

Based on the four probe results:

1. **WA4 rotation trigger is quota-driven, not coherence-driven.** Key on cumulative cache_read across rounds + result-text quota-error detection. No need for a separate "coherence drift" detector in v1; we have no evidence it's needed at the round counts a single quota window allows.

2. **WA4 needs a pre-dispatch quota probe.** Cheap one-message `claude -p` ping; if it returns the "out of extra usage" string, sleep until the reset time named in the error or surface to Slack/dashboard. Saves heavy planning rounds from failing mid-flight.

3. **WA5 (autonomous QA agent) build path is unblocked.** Playwright MCP + project-local `.mcp.json` + `claude -p` + read-only prod scenarios = pattern proven. No infrastructure dragons.

4. **WA3 (dashboard) build path is unblocked.** Use `PreToolUse`/`PostToolUse` hooks → file or WebSocket → bare HTML/JS UI. No infrastructure dragons.

5. **Auth/ToS framing in the overview needs an update** (above). Not a build blocker.

6. **`--bare`-becoming-default watch-item.** When the headless docs ship `--bare` as the `-p` default, the wrapper must explicitly continue to opt out OR start passing `ANTHROPIC_API_KEY`. Mark in `workflow_automation_overview.md` and the daemon's startup checks.

## Go / No-Go matrix

| Pass | Verdict | Reasoning |
|---|---|---|
| WA3 — At-desk dashboard | **GO** | P3 confirmed the hook seam. No new unknowns. |
| WA4 — Orchestrator daemon + planner core | **GO with quota-awareness** | P1 confirmed `--resume` mechanism + planning judgment within the rounds that ran. Quota wall is real; design rotation/pre-flight per §"Architecture adjustments" #1-#2. |
| WA5 — Autonomous QA agent | **GO** | P2 confirmed Playwright MCP + `claude -p`. Drop-in. |
| WA6 — Phone channel (Slack) | **PROCEED** (no validation done; not a blocker) | Bridge pattern well-understood; first WA6 task is workspace setup + the round-trip probe deferred from here. |
| WA7 — Hardening | unchanged | Quota-aware rotation logic + the `--bare` watch-item are inputs to WA7's hardening surface. |

## File list

All under `workflow-automation/` (this track's convention):

- `wa2_findings.md` (this doc)
- `spike/p1_planner_continuity_harness.py`
- `spike/p2_playwright_mcp_harness.py`
- `spike/p3_dashboard_hook_stream_harness.py`
- `spike/artifacts/p1_summary.json`
- `spike/artifacts/p1_rounds.json` (incl. the R5 quota-error text)
- `spike/artifacts/p1_rotation_digest.md`
- `spike/artifacts/p2_result.json`
- `spike/artifacts/p3_result.json`
- `spike/artifacts/p3_hook_events.jsonl`

## Costs + auth

All LLM calls via `claude -p` on Max with `ANTHROPIC_API_KEY` unset (Phase 42 invariant). Telemetry from the JSON payloads shows `total_cost_usd` populated but, as Phase 42 documented, that's the "what this would have cost on the API" informational number, not actual metered billing. The quota wall in P1 is the only real spend signal — Max's daily extra-usage allowance was exhausted by 4 planning-scale rounds.

**No metered API spend.** **No website code touched.** **No migration. No Railway deploy. No frontend bundle.** All N/A per track convention.

## Pass-summary

WA2 architecture-validation spike returns **GO on the corrected architecture** with one quota-driven caveat. The `claude -p` + Max-OAuth + Playwright MCP + hooks-for-observability stack is empirically validated. Planner-continuity at planning scale is mechanism-sound (no coherence drift in 4 rounds at ~44k cache_read each) but quota-constrained on Max pre-June-15-2026. WA3 (dashboard) and WA5 (QA agent) build paths are unblocked; WA4 (daemon) builds with a quota-aware rotation trigger + pre-flight probe; WA6 (Slack) deferred its round-trip test to its own pass. One small documentation correction recommended in `workflow_automation_overview.md` (Correction 1 framing is out of date vs. current Anthropic docs).
