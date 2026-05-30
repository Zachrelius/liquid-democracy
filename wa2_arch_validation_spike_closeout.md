# WA2 — Architecture Validation Spike Closeout

**Status:** SHIPPED 2026-05-30. Branch merged + pushed; **no Railway deploy** (workflow-automation track convention).
**Spec:** `workflow-automation/wa2_architecture_validation_spike_spec.md`
**Branch:** `wa-2/arch-validation-spike` (worktree at `liquid-democracy-wa2/`, branched from master `b22d088`, merged via `--no-ff` to master).

---

## Headline

**GO on the corrected architecture.** Three probes ran cleanly (P2 Playwright MCP, P3 hook stream, auth/ToS read-the-docs). One probe (P1 planner-continuity at planning scale) hit a Max-subscription quota wall after 4 of 10 rounds — itself a spec-anticipated finding. Within the 4 rounds that ran, the `--resume` planner session held planning-scale context cleanly with no coherence drift. The architecture is correct; production cadence is quota-gated until June 15 2026 when subscription `claude -p` gets a dedicated credit pool.

Full findings + go/no-go matrix in `workflow-automation/wa2_findings.md`.

---

## Per-probe status

| Probe | Verdict | Highlights |
|---|---|---|
| P1 — Planner-continuity at planning scale | **PARTIAL PASS / spec-anticipated quota finding** | 4/10 rounds completed before "out of extra usage" wall. Within those 4 rounds: tracker preserved, prior-round content cited correctly, no coherence drift. Cache_read tokens grew linearly (43,639 → 44,619 across R1-R4). Rotation demo not exercised. Implication: WA4's rotation trigger should be **quota-driven, not coherence-driven**. |
| P2 — Playwright MCP via `claude -p` | **PASS** | `@playwright/mcp@latest` loaded from project-local `.mcp.json`; headless browser drove `https://www.liquiddemocracy.us/`; structured JSON pass/fail returned on first attempt (21.7s end-to-end, all 3 checks `found:true`). No `npx playwright install` needed — MCP self-provisioned the browser. |
| Auth/ToS read-the-docs | **CORRECTS OVERVIEW** | Overview's "no Agent SDK with OAuth" framing is OUT OF DATE per current Anthropic docs. `claude -p` IS the Agent SDK in CLI form; subscription is supported. June 15 2026 restructures quota (dedicated credit pool, not a ban). Architecture is unchanged; documentation correction flagged. |
| P3 — Dashboard hook stream | **PASS** | `PreToolUse` + `PostToolUse` events flowed cleanly to a local handler with full `tool_input` + `tool_response` + `duration_ms`. Disler seam viable for WA3. |
| P4 — Slack bridge | **DEFERRED** | No Slack workspace + connector configured this session. Protocol well-documented; defer the round-trip test to WA6 (which already requires workspace setup). |

---

## Cluster B — Build deliverables (throwaway harnesses)

All under `workflow-automation/spike/`:

- `p1_planner_continuity_harness.py` — Phase 42 lineage. Seeds session with real workflow-automation docs (~42.8 KB), runs ≥10 fresh-process `--resume` rounds with substantive planning prompts, grades coherence + tracker continuity, demonstrates rotation.
- `p2_playwright_mcp_harness.py` — writes `.mcp.json`, dispatches `claude -p` with a read-only QA scenario against prod, validates structured JSON output.
- `p3_dashboard_hook_stream_harness.py` — writes `.claude/settings.local.json` hook config + tiny stdin handler, dispatches `claude -p` with a small Read-tool task, captures the resulting hook event stream.

Raw artifacts under `workflow-automation/spike/artifacts/` (5 files: P1 summary + rounds + rotation digest, P2 result, P3 result + raw event log).

---

## Key technical findings (load-bearing for WA3+)

1. **Windows command-line length cap is real.** Planning-scale seed prompts (~40 KB) exceed Windows' ~32 KB positional-arg limit (`WinError 206: filename or extension too long`). **The wrapper MUST pipe prompts via stdin to `claude -p`**, not as a positional after `--`. Documented in `p1_planner_continuity_harness.py::_run_claude`. WA4 dispatch will hit this immediately if it doesn't carry the pattern forward.
2. **Token growth on `--resume` is modest.** R2-R4 added 414-566 tokens of cache_read on top of the cached seed (43.6 KB). Within the 4 rounds that ran, no drift. The continuity mechanism works.
3. **Max "out of extra usage" wall hits at ~4 planning-scale rounds.** The `claude -p` response on quota exhaustion is a non-zero exit + a `result_text` like `"You're out of extra usage · resets HH:MMpm (timezone)"`. The wrapper can pattern-match this to know to back off + when to retry. WA4 implementation note.
4. **`--bare` is a future-default watch-item.** Current headless docs say `--bare` will become the `-p` default in a future release. Bare mode disables OAuth/keychain reads and requires `ANTHROPIC_API_KEY`. **Our wrapper MUST explicitly NOT pass `--bare` to keep Max OAuth working.** Pin in the daemon's startup check + the overview.
5. **`.mcp.json` auto-loads in `-p` mode (no `--bare`).** Phase 42 finding re-confirmed: project-local MCP servers are discovered automatically. WA5 binds to this directly.

---

## Auth + cost statement

All LLM work via `claude -p` on Max with `ANTHROPIC_API_KEY` unset. The P1 quota wall is the only real spend signal — Max's daily "extra usage" allowance was exhausted by 4 planning-scale rounds. `total_cost_usd` fields in payload JSON are informational (what the API would charge), not metered billing per Phase 42 + WA1.

**No metered API spend.** **No website code touched.** **No migration. No Railway deploy. No frontend bundle.** All N/A per workflow-automation track convention.

---

## Files added (all under `workflow-automation/`)

```
workflow-automation/wa2_findings.md                                  (NEW — the contract back)
workflow-automation/spike/p1_planner_continuity_harness.py           (NEW)
workflow-automation/spike/p2_playwright_mcp_harness.py               (NEW)
workflow-automation/spike/p3_dashboard_hook_stream_harness.py        (NEW)
workflow-automation/spike/artifacts/p1_summary.json                  (NEW — round-by-round)
workflow-automation/spike/artifacts/p1_rounds.json                   (NEW — full round transcripts)
workflow-automation/spike/artifacts/p1_rotation_digest.md            (NEW — digest the rotation round was handed)
workflow-automation/spike/artifacts/p2_result.json                   (NEW — Playwright QA result)
workflow-automation/spike/artifacts/p3_result.json                   (NEW — hook stream summary)
workflow-automation/spike/artifacts/p3_hook_events.jsonl             (NEW — raw hook events)
wa2_arch_validation_spike_closeout.md                                (NEW — this file)
```

---

## Branch + commit + worktree

- **Worktree:** `liquid-democracy-wa2/` (sibling of `liquid-democracy/` + `liquid-democracy-wa1/`). Created via `git worktree add` to isolate from any in-flight parallel work.
- **Branch:** `wa-2/arch-validation-spike` from `b22d088`. Single commit + merge.
- **Merge:** `--no-ff` to master via temp master worktree (WA1 lineage).

---

## Locked-decision confirmation (spec D1-D6)

- ✅ **D1 — Spike only.** Throwaway harnesses + findings doc. No daemon, no real dashboard, no production Slack.
- ✅ **D2 — `claude -p` on Max, no SDK embed, no metered key.** Every subprocess invocation strips `ANTHROPIC_API_KEY`. The Auth/ToS check confirms — and refines — the architecture.
- ✅ **D3 — P1 uses real planning-scale context.** Seed is 42.8 KB of actual workflow-automation track docs; prompts demand judgments referencing prior-round content.
- ✅ **D4 — P2 is prod read-only.** Landing page only, no auth-gated surfaces, no writes.
- ✅ **D5 — P3/P4 best-effort, skippable.** P3 ran + passed in ~15 minutes; P4 deferred explicitly (no workspace).
- ✅ **D6 — Degradation point in P1 is the rotation trigger.** No coherence-driven degradation observed; the QUOTA wall is the real trigger. WA4 rotation logic should key on cumulative cache_read + quota-error detection.

---

## Notable spec deviations

**One.** Spec asked for ≥10 rounds in P1; quota wall hit at round 5. Per spec's own anticipation ("A rate-limit hit is itself a finding"), this is recorded as the finding rather than blocking. We have 4 high-quality rounds + the quota-error JSON; that's enough to make the architectural verdict.

The spec also mentioned re-checking that the auth/ToS picture in `workflow_automation_overview.md` "Correction 1" matches current docs. It doesn't — flagged in findings as a small documentation update for a follow-up commit (not load-bearing for build).

---

## New tech debt

- **`workflow_automation_overview.md` "Correction 1" framing is out of date** vs. current Anthropic docs (Agent SDK + OAuth + subscription). Suggested rewrite is in `wa2_findings.md`. Tier-3 — documentation accuracy, not load-bearing.
- **WA4 must carry forward** the stdin-piping invariant (Windows command-line length cap) AND the quota-aware rotation trigger AND the `--bare` watch-item. All recorded in findings.

---

## Followups (out of scope, per spec §Followups)

- **WA3 — At-desk dashboard.** Build path unblocked by P3.
- **WA4 — Orchestrator daemon + planner core.** Build with quota-aware rotation + pre-flight quota probe. P1's findings shape the rotation logic.
- **WA5 — Autonomous QA agent.** Drop-in on Playwright MCP per P2 setup.
- **WA6 — Phone channel.** Carries the deferred P4 round-trip probe as its first sub-task.
- **Tiny doc commit** updating `workflow_automation_overview.md` "Correction 1" (or fold into WA3's spec context refresh).

---

## Pass-summary (PROGRESS.md-style)

WA2 architecture-validation spike — SHIPPED 2026-05-30 via the `wa-2/arch-validation-spike` worktree. **GO on the corrected architecture.** P2 (Playwright MCP from `claude -p`) and P3 (dashboard hook stream) PASS. P1 (planner-continuity at planning scale) PARTIAL — 4 high-quality `--resume` rounds completed before the Max-subscription "out of extra usage" wall hit at round 5; no coherence drift within the 4 rounds. The rotation trigger for WA4 is QUOTA-driven, not coherence-driven. Auth/ToS read-the-docs corrects the overview's framing: `claude -p` IS the Agent SDK in CLI form; subscription is supported; June 15 2026 restructures quota with a dedicated credit pool. P4 (Slack) deferred to WA6. Three throwaway harnesses + raw artifacts checked in under `workflow-automation/spike/`. No website code touched, no migration, no Railway deploy.
