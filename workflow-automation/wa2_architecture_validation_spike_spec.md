# WA2 — Architecture Validation Spike

**Status:** Spec, dispatched [pending]. Written 2026-05-30. Workflow-automation track (read `workflow-automation/workflow_automation_overview.md` first).

Combined dispatch framing + spec body. An **investigation spike** — mirrors Phase 42 in shape and intent. After the 2026-05-30 prior-art research corrected the architecture (shell out to `claude -p` rather than embed the Agent SDK; Playwright MCP rather than Claude-in-Chrome for autonomous QA; build-thin-and-borrow), this pass empirically confirms the *new* load-bearing pieces before WA3+ build on them. Produces a findings doc with a go/no-go per piece. No website app code, no migration, no deploy.

**Cost note up front:** every LLM call here is `claude -p` on the Max subscription with `ANTHROPIC_API_KEY` unset — the same path Phase 42 ran on, which showed as telemetry-only (~$0.54) and **not actually billed**. So this spike consumes modest Max *quota*, not new metered API dollars. No new spend authorization needed; if any step would require a metered API key, STOP and surface to Z rather than proceeding.

---

## Dispatch framing

### Goal

Confirm the four corrected load-bearing assumptions, in priority order:

1. **(PRIMARY) Planner-continuity at planning scale.** Phase 42 proved `claude -p --resume` recalls small facts over 12 fresh-process rounds. The planner needs more: hold *large* working context (specs, closeouts, multi-step reasoning) across many resume cycles without quality drift, and rotate cleanly to a fresh session (bootstrapped from a WA1-style state digest) when it approaches context limits. This is the real test of goal 1 and the place Anthropic's "long sessions degrade" caution would bite if it's going to.
2. **(PRIMARY) Playwright-MCP-from-`claude -p` headless QA.** Confirm a dispatched `claude -p` agent can load `microsoft/playwright-mcp` from `.mcp.json`, drive a headless browser against the live site (`https://www.liquiddemocracy.us/`), and report a structured pass/fail on a real scenario. This replaces the Claude-in-Chrome plan for autonomous QA (goal 4).
3. **(SECONDARY) Dashboard hook-observability pattern.** Validate the `disler/claude-code-hooks-multi-agent-observability` approach: can Claude Code hooks emit a tool-call/reasoning event stream that a tiny local WebSocket+UI renders live? Enough to confirm it's the right seam for the WA3 at-desk dashboard.
4. **(SECONDARY) Slack bridge + auth durability.** Stand up a minimal `cc-connect`-style inbound+outbound Slack path; confirm a message can reach a `claude -p` run and a reply post back, and probe whether the auth survives idle time (the WA6 concern).

Plus a non-code **auth/ToS confirmation** (read Anthropic's current headless + Agent-SDK + subscription docs): verify "no Agent SDK with OAuth; `claude -p` CLI on Max is sanctioned; June 15 adds a dedicated credit pool." Record the citations.

Deliverable: `workflow-automation/wa2_findings.md` with a go/no-go per piece and any architecture adjustments.

### Branch + merge

Branch: `wa-2/arch-validation-spike`. `--no-ff` merge to master. No Railway deploy. Like Phase 42, the merge lands findings + any throwaway harness scripts (under `workflow-automation/`), not a feature.

### Verification matrix

| Check | Required | Notes |
|---|---|---|
| Website backend pytest | ✅ | Confirm unperturbed (1476/27 baseline); no website code touched. |
| **P1 — planner-continuity at scale** | ✅ | A `--resume` planner session carries large context across ≥10 rounds with substantive (not toy) planning prompts; recall/coherence graded; rotation-from-digest demonstrated. |
| **P2 — Playwright MCP via `claude -p`** | ✅ | A dispatched `claude -p` loads Playwright MCP, drives a headless browser against prod, returns structured pass/fail on a real scenario (e.g., load `/`, assert known element/text). |
| P3 — dashboard hook stream | ⚠️ Best-effort | Prove hooks emit a renderable event stream to a local WS+UI. If time-boxed out, document the seam + defer to WA3. |
| P4 — Slack bridge + auth durability | ⚠️ Best-effort | Minimal inbound+outbound round-trip; note auth-expiry behavior. If Slack workspace isn't set up yet, document the protocol + defer to WA6. |
| Auth/ToS confirmation | ✅ | Read-the-docs; cite sources; confirm or correct the `claude -p`-on-Max + June-15 picture. |
| **Findings doc with go/no-go** | ✅ | `workflow-automation/wa2_findings.md`. |
| No metered API spend | ✅ | All LLM calls via `claude -p` on Max, `ANTHROPIC_API_KEY` unset. If anything needs a metered key, STOP + surface. |
| PG smoke / Railway / bundle | ❌ N/A | State explicitly. |

### Suggested team structure

Lead + one dev (or single full-stack agent). ~3–5 hours given the four probes. **Continuing dev team** (Phase 42 patterns + repo context). P3/P4 are best-effort; P1/P2 are the gates.

### Sequence

1. **P1** planner-continuity at scale (most important; reshapes the daemon if it fails).
2. **P2** Playwright-MCP-from-`claude -p` (goal-4 mechanism).
3. Auth/ToS confirmation (read-the-docs; quick).
4. **P3** dashboard hook stream (best-effort).
5. **P4** Slack bridge (best-effort; may defer if no workspace yet).
6. Write `wa2_findings.md`; merge.

### Load-bearing decisions

- **Spike, not build.** Throwaway harnesses + a findings doc. No daemon, no real dashboard, no production Slack integration. WA3+ build off the findings.
- **All LLM work via `claude -p` on Max.** No embedded Agent SDK. No metered API key. (Confirms the corrected architecture in practice.)
- **P1 must use planning-scale context, not toy facts.** Feed real specs/closeouts from the repo; ask for real planning judgments; grade coherence + recall across rounds. Toy-fact recall (Phase 42) is already known to pass and would prove nothing new.
- **P2 targets prod read-only.** QA scenarios only read the live site; no writes, no auth-gated mutations. (Real autonomous QA scope comes in WA5.)
- **If P1 shows meaningful degradation,** that's the signal to lean harder on rotation/file-handoff (Anthropic's recommended pattern) and treat the planner's in-session memory as shorter-lived — record the degradation point as the rotation trigger.

### Operational watch-outs

- **Env hygiene (Phase 42):** `ANTHROPIC_API_KEY` unset in every `claude -p` subprocess, no `--bare`. Confirm the auth path in findings.
- **`.mcp.json` trust (Phase 42):** Playwright MCP is a new project MCP server — headless `-p` auto-loads it (doesn't prompt), but treat the `.mcp.json` as trusted-by-design and version it. If a first-run interactive trust step is needed on Windows, note it.
- **cwd discipline (Phase 42):** run resume rounds from a stable cwd (session slug = cwd).
- **Playwright install:** Playwright MCP may need a browser install step (`npx playwright install`); record the setup so WA5 can reproduce.
- **P1 quota:** planning-scale prompts are bigger than Phase 42's; keep rounds reasonable (~10–15) to bound Max quota. A rate-limit hit is itself a finding.
- **P3/P4 are explicitly skippable** if time-boxed — don't let them eat the P1/P2 gates.

### Closeout reports back

- **P1 verdict:** does a `--resume` planner session hold planning-scale context across the rounds without drift? Round-by-round coherence/recall, latency, token growth, and the degradation point (or "none observed"). Rotation-from-digest demonstrated? This is the headline for goal 1.
- **P2 verdict:** Playwright MCP loaded + headless browser drove prod + structured pass/fail returned? Setup steps captured.
- **Auth/ToS:** confirmed or corrected, with citations.
- **P3 / P4:** result or documented deferral.
- **Recommendation:** go/no-go per piece + any architecture adjustments for WA3+.
- Website suite unperturbed; files (all under `workflow-automation/`); branch + SHAs; "no metered spend, no migration, no Railway — N/A."

---

## Status block

The 2026-05-30 research replaced the spike's original unknowns. Chrome-MCP-from-a-daemon is off the table (use Playwright MCP). Agent-SDK-with-Max-OAuth is off the table (ToS; shell out to `claude -p` instead) — which also means we're not blocked until June 15. What's left genuinely unproven and load-bearing:

The planner's continuity *at planning scale* is the big one. Phase 42's `--resume` result is encouraging but tested only small-fact recall; whether a resumed session sustains good planning judgment over a long, context-heavy run — or degrades as Anthropic warns — decides how hard we lean on session-persistence vs. rotation-from-state. And Playwright-MCP-from-`claude -p` is the new goal-4 mechanism we've reasoned should work (Phase 42 showed `.mcp.json` MCPs load in `-p`) but haven't run. Both are cheap to test now on Max, and both should be settled before WA3/WA4/WA5 build on them.

## Locked decisions

- **D1 — Spike only;** throwaway harnesses + findings doc.
- **D2 — `claude -p` on Max for all LLM work; no SDK; no metered key.**
- **D3 — P1 uses real planning-scale context,** not toy facts.
- **D4 — P2 is prod read-only.**
- **D5 — P3/P4 best-effort, skippable;** P1/P2 are the gates.
- **D6 — Degradation point in P1 (if any) becomes the documented rotation trigger.**

## What this pass IS

Four scoped probes (two gating, two best-effort) + a read-the-docs auth confirmation, producing `wa2_findings.md` with go/no-go and any architecture adjustments. Throwaway harness scripts under `workflow-automation/`.

## What this pass is NOT

- Not the daemon, planner loop, dashboard, QA agent, or production Slack integration.
- Not a touch of website app code, migrations, or deploy infra.
- Not a metered-API anything — if a step needs it, STOP and surface to Z.

## Cluster P — Probes

### P1 — Planner-continuity at planning scale (PRIMARY)

Build a harness (like `backend/scripts/workflow_resume_spike.py` from Phase 42, but planning-flavored). Seed a `claude -p` session with a real planning context (e.g., the workflow-automation overview + a couple of repo specs/closeouts). Over ≥10 fresh-process `--resume` rounds, pose substantive planning tasks that build on earlier rounds (e.g., "given what we decided about X two rounds ago, draft the next step", "reconcile this new closeout against the plan"). Grade each round on whether it correctly uses earlier-established context and stays coherent. Then demonstrate **rotation**: snapshot a WA1-style digest, start a *fresh* session bootstrapped from only that digest, and confirm it continues sensibly. Record latency, token growth, and any degradation point.

### P2 — Playwright MCP via `claude -p` (PRIMARY)

Add `microsoft/playwright-mcp` to a `.mcp.json`. Dispatch a `claude -p` agent with a read-only QA scenario against `https://www.liquiddemocracy.us/` (e.g., load the landing page, assert a known element/text; optionally navigate `/about`). Confirm: the MCP loads in `-p`, the headless browser actually drives, and the agent returns a structured pass/fail. Capture the setup (incl. any `npx playwright install`).

### P3 — Dashboard hook stream (best-effort)

Prototype the `disler` seam: configure Claude Code hooks to emit tool-call/event JSON; pipe to a minimal local WebSocket + a bare HTML page that renders the stream live. Goal is only to confirm it's the right mechanism for the WA3 at-desk dashboard — not to build the dashboard. Time-box; defer to WA3 with notes if needed.

### P4 — Slack bridge + auth durability (best-effort)

If a Slack workspace + connector are available, stand up a minimal `cc-connect`-style round-trip: a Slack message reaches a `claude -p` run; a reply posts back. Note whether auth survives an idle gap (the WA6 durability concern). If no workspace yet, document the protocol and defer to WA6.

### Auth/ToS confirmation (read-the-docs)

Read Anthropic's current headless docs, Agent SDK docs, and subscription/usage policy. Confirm or correct: (a) Agent SDK requires a Console API key (OAuth/Max tokens not permitted), (b) `claude -p` CLI headless is sanctioned on Max and draws subscription quota, (c) June 15 2026 adds a dedicated Agent-SDK credit pool for subscription `claude -p`. Cite sources in findings. If any of these is wrong, flag immediately — it reshapes the architecture.

## Operational notes

- Mirror Phase 42's harness style + env hygiene. Reuse `docs/workflow_spike_resume_findings.md` as the template for `wa2_findings.md`.
- Keep all artifacts under `workflow-automation/`.
- P1 and P2 are the gates; protect them from P3/P4 time spend.

## Followups

- P1's degradation point (if any) → the rotation trigger WA4 implements.
- P2's setup steps → WA5's Playwright-QA-agent baseline.
- P3 notes → WA3 dashboard spec.
- P4 notes → WA6 Slack spec.
- If the auth/ToS reading shifts, update `workflow_automation_overview.md` and the planner memory before any further build.
