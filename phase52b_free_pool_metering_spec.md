# Phase 52b — Free-Pool Metering + Empty-Pool Wall

**Status:** Spec + dispatch. Written 2026-06-05.

Reading order: this doc; `id_verification_arc_backlog.md` (arc context + the locked metering decisions); the shipped `backend/verification_provider.py` webhook handler (where the counter increments) + `backend/org_config.py` (the settings-helper pattern this follows).

**This phase is INDEPENDENT of the hash/dedup work (52d/52e) and of Didit's capture service.** It can build + ship in parallel while the 52e grounding re-verify is blocked on Didit. It touches the verification *count*, not the verification *content* — no OCR fields, no hashes, no dedup. Dispatching it now keeps the arc moving while Didit sorts out their capture outage.

---

## Why dispatch this now (context for the team — also in the dispatch prompt)

The 52e grounding re-verify (Z + the hash extractor) is **blocked on a Didit-side outage**: Didit's live document/selfie capture flow is currently non-functional (no capture guidance, never takes the photo — confirmed across two people/two devices; manual photo upload works but the selfie/liveness step hard-requires the broken live capture). Z has reported it to the Didit account manager (Mara) and is waiting on a fix. The 52e Stage 1 500-on-abandoned-session bug was already fixed and deployed; the only thing blocking the 52e green-light is Didit's capture recovering so Z can complete a real verification.

Rather than idle, this phase (52b — the arc's last *core* metering stage) runs as a parallel workstream. It has no dependency on the hash work or on Didit capture, so it proceeds regardless. When Didit's capture is back, the 52e re-verify completes and Stage 2 proceeds; the two workstreams converge cleanly.

---

## Goal

Track verification consumption against the shared monthly free pool (Didit's 500/month/workspace), so usage is visible and the data exists to pick a per-org sub-allocation later if the commons gets raced — without enforcing per-org allocation yet (Z decision: first-come-first-served shared pool for v1). When the shared pool is exhausted, block new verification *before* the user is sent to Didit, with a clear reason. **No billing** — overage is blocked, not billed (billing is Phase 53, entity-gated).

## Locked decisions (from the arc backlog)

- **Shared pool, FCFS for v1.** One workspace-level monthly counter (resets on the 1st, matching Didit's reset). No per-org allocation enforced yet.
- **Per-org consumption recorded from day one, NOT enforced.** The "preserve the information from day one" pattern — record per-org consumption so a sub-allocation number can be chosen later from real data, but don't act on it.
- **Empty-pool wall hits BEFORE the user is sent to Didit, never after.** Two check points: (a) at gate-display (so an unavailable gate reads honestly, not a dead button) and (b) at session-creation (the authoritative hard stop — the pool could empty between display and click). Both read one capacity check.
- **One wall in v1: the shared pool is globally empty.** No per-org "your org hasn't paid" wall — that has no backing mechanism until Phase 53 billing. Do NOT build it here.
- **demo_stub and backdoor provenance NEVER increment the counter** (Phase 51 forward-constraint #2). A real Didit verification increments; demo/test/ops-override do not.
- **A blocked verification creates no Didit session** (no spend, fail-safe toward not consuming).

## Branch + merge
`phase-52b/free-pool-metering`. `--no-ff` to master per CLAUDE.md.

## Migration head
Adds a metering table (and possibly a per-org consumption table). Confirm `alembic heads` single head at branch time (52d advanced it to `f1a2b3c4d5e6`; 52e Stage 1 added no migration; 52e Stage 2 *will* add `OrgDuplicateFlag` — **coordinate head ordering if 52e Stage 2 and 52b are in flight simultaneously**; whichever branches second confirms the actual head and stacks on it, never assumes). Hex-prefix revision. Multi-head → STOP.

## Clusters

### B1 — the shared monthly counter
A workspace-level monthly consumption counter. Recommend a `VerificationConsumption` table keyed by `(year_month, org_id)` so per-org consumption is recorded from day one (the FCFS shared total is the SUM across org_ids for the current `year_month`; per-org rows give the future-sub-allocation data without enforcing it now).
- Increment on a **real** verification completion (provenance `didit`) in the webhook handler — same place the verification record is written. NEVER increment for `demo_stub` or `backdoor` provenance (assert this — it's the Phase 51 forward-constraint).
- The monthly boundary resets implicitly via the `year_month` key (a new month = new rows; no cron reset needed). Document the reset semantics + that it mirrors Didit's calendar-month reset.
- The free-pool size (500) is a platform config constant, not hardcoded at call sites — `VERIFICATION_FREE_POOL_MONTHLY = 500` in one place, so it's tunable if Didit's free tier changes.

### B2 — the capacity check (one predicate, two call sites)
A single `verification_pool_has_capacity() -> bool` (and a companion that returns the remaining count + reset date for messaging). Reads the current `year_month` shared total vs `VERIFICATION_FREE_POOL_MONTHLY`.
- **Call site 1 — gate display:** where a verification gate is shown to a user (the "verify to join / verify to act" prompts from Phase 52), if the pool is exhausted, the gate reads "verification temporarily unavailable this month" instead of a live "Start verification" button. Honest messaging — don't show a button that can't deliver.
- **Call site 2 — session creation (authoritative hard stop):** in `POST /api/verification/session`, check capacity BEFORE calling Didit. If exhausted, return a structured block (NOT a Didit session — no spend) the FE renders as the unavailable message. This is the real gate; the pool can empty between display and click, so this is the authoritative one.

### B3 — the empty-pool message (clear reason + reset date)
Structured response → FE copy: "Identity verification is temporarily unavailable this month. Check back after [1st of next month]." Names the real reason (monthly free pool exhausted) + the reset date. Backend codes never leak into copy (Phase 49a rule). When Phase 53 billing lands, this message becomes "...unless your organization enables paid verification" — but NOT in this phase; v1 is a clean "unavailable this month."

### B4 — admin consumption visibility
A platform-admin read of current-month consumption: shared total (vs the 500 cap) + per-org breakdown. This is what informs the future sub-allocation decision — Z watches whether one org is racing the commons. Reuse the existing platform-admin gate (`is_admin`). Read-only.

## Verification matrix

| Check | Required | Notes |
|---|---|---|
| Counter increments on real verification (side-effect) | ✅ | A `didit`-provenance completion increments the `(year_month, org_id)` row. Assert the row value, not a status code. |
| demo_stub / backdoor NEVER increment | ✅ | The Phase 51 forward-constraint. Assert a demo_stub and a backdoor verification leave the counter unchanged. |
| Capacity predicate | ✅ | `has_capacity` true below 500, false at/above. Companion returns correct remaining + reset date. |
| Gate-display check | ✅ | Exhausted pool → gate shows unavailable message, not a live button. |
| Session-creation hard stop (side-effect) | ✅ | Exhausted pool → `POST /api/verification/session` blocks BEFORE any Didit call; **no Didit session created** (no spend). Assert no provider call happened. |
| Monthly reset semantics | ✅ | A new `year_month` starts fresh; prior month's consumption doesn't count against the new month. Test across a month boundary (inject the year_month). |
| Per-org recorded, not enforced | ✅ | Per-org rows accumulate; NO per-org cap is enforced (FCFS shared pool). A single org can consume the whole pool (that's the v1 behavior; the data just gets recorded). |
| Admin visibility | ✅ | Platform-admin sees shared total + per-org breakdown; non-admin can't. |
| Migration cycle + PG smoke both modes | ✅ | The consumption table. Confirm single head first; coordinate with 52e Stage 2's migration if both in flight. |
| Additive-layer parity | ✅ | Orgs/verification with the pool NOT exhausted behave exactly as today — the wall only appears at exhaustion. No verification path changes below the cap. |
| `bash start.sh` prod-mimic | ⚠️ Conditional | If the reset is wired to a worker/scheduled tick (it shouldn't be — the `year_month` key makes reset implicit), N/A. If a sweep/worker is added, REQUIRED (the Phase 48.1 digest-async context applies). Recommend implicit-reset, no worker. |
| Adjacent regression | ✅ | The ~494 set green. |

## Sequence
B1 (counter + table + migration) → B2 (capacity predicate + the two call sites) → B3 (message) → B4 (admin visibility). Deploy.

## Team
Continuing dev team. Lead: migration + head-coordination with 52e Stage 2 if concurrent, closeout. Backend: B1–B2, B4. FE: B2's gate-display + B3's message. QA: the counter side-effects (esp. demo_stub-never-increments), the no-Didit-session-on-block assertion, the month-boundary reset.

## Invariants
- **demo_stub / backdoor never increment the counter.**
- **A blocked verification creates no Didit session** (no spend).
- **The wall hits before the Didit handoff, never after.**
- **Per-org recorded, not enforced** (FCFS v1).
- **No billing** — blocked, not billed (Phase 53 is entity-gated).
- **Additive-layer:** below the cap, nothing changes.

## Closeout must report
Counter side-effect evidence (real increments; demo_stub/backdoor don't); the no-Didit-session-on-block assertion; month-boundary reset behavior; per-org-recorded-not-enforced confirmation; admin visibility; migration cycle + PG smoke on a confirmed single head (+ note any head coordination with 52e Stage 2); additive-layer parity; adjacent green. New tech debt for the backlog.

## Z-action items
- **None to run this phase.** It's pure platform infrastructure — no Didit credentials, no console, no re-verify. Builds + ships independently of the Didit capture outage blocking 52e.
- **Informational:** the free-pool size constant is 500 (Didit's current free tier). If Mara's reply reveals a different number or terms, it's a one-constant update.
