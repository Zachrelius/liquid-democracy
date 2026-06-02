# Phase 49 — Scheduled / Fixed-Term Elections — Closeout

**Spec:** `phase49_scheduled_term_elections_spec.md`
**Branch:** `phase-49/scheduled-term-elections` → merged `--no-ff` to master
**Date:** 2026-06-01

---

## Overall

**SHIPPED.** Completes the elected-leadership arc (45a → 45b → 46 → 46a → 47 → 47a → 48 → 48a → 48b → 48.1 → 49). Phase 49 adds the **traditional-democracy option** — fixed-term scheduled re-election — as a third trigger source (`scheduled`) alongside Phase 48's `admin_direct` + `member_cosign`. Off-cycle "elected-until-challenged" remains the default; orgs/titles opt in to scheduled re-election explicitly.

**Locked model: A — hold-over-if-uncontested.** A fixed term FORCES an election to open on schedule; it does NOT vacate the seat. Zero-candidate scheduled election → incumbent holds over (D6 reuse from Phase 48). The seat is never empty. Crucially, `finalize_election`'s resolution semantics need NO change — Phase 49 only adds the trigger (clock) + the bookkeeping (next-due timestamp). No new winner-installation logic.

---

## Per-cluster status

| Cluster | Status | Notes |
|---|---|---|
| B1 — Schema migration | DONE | `org_titles.term_length_days` (Integer NULL), `org_titles.election_lead_time_days` (Integer NOT NULL default 7), `org_titles.next_election_due_at` (DateTime NULL), `proposals.election_trigger` (String(16) NULL). Revision `a7c1d8e94521` (hex-prefix per the Phase 48 Stage 2 incident hardening). Reversible via `batch_alter_table` (dialect parity SQLite + Postgres). Cycle test: 2/2 PASS. PG smoke: PASS both modes (fresh + upgrade-from-prior). |
| B2 — `scheduled` trigger source | DONE | Added to `elections.VALID_TRIGGER_SOURCES`. The HTTP route (`routes/elections.py::open_election`) still rejects `trigger='scheduled'` from external clients — it's an internal-only trigger, dispatched from `digest_scheduler.run_one_tick` via `elections.open_due_term_elections`. |
| B3 — Due-term tick integration | DONE | New `elections.open_due_term_elections(db, now)`. Eligibility = title has `term_length_days` set AND `next_election_due_at` set AND `next_election_due_at - lead_time <= now` AND org has elections enabled AND `scheduled` in `trigger_sources` AND `title_is_electable` AND no open election proposal already targets the title (D5 idempotency). Per-title try/except so one bad title doesn't break the batch (mirrors the halfway-deadline check's isolation). Called from `digest_scheduler.run_one_tick` wrapped in its own try/except. Counts roll into the tick report dict (`scheduled_elections_opened`, `scheduled_elections_idempotent_skips`, `scheduled_elections_errors`) for observability. |
| B4 — Next-due advancement on resolution | DONE | `finalize_election` calls `_advance_schedule_for_title(db, title)` when `proposal.election_trigger == 'scheduled'`. Advance is unconditional on outcome — hold-over, uncontested win, contested win all advance by exactly `term_length_days`. Off-cycle (`admin_direct` / `member_cosign`) elections explicitly do NOT touch the schedule per B4 decision. Advance fires BEFORE the candidate-branch return so even the zero-candidate hold-over path advances the clock (otherwise the next tick would re-open immediately). |
| B5 — Tests | DONE | `test_phase_49_scheduled_term_elections.py` (12 tests covering the full verification matrix) + `test_phase_49_migration_cycle.py` (2 tests). **14/14 PASS.** Row-level assertions: actual `next_election_due_at` advancement, actual incumbent retention on hold-over (via `_user_role` lookup), actual proposal creation w/ `trigger='scheduled'`, actual existing-title parity (post-migration scan asserts no titles have term fields). |
| F1 — Term config UI | DONE | `OrgTitlesPanel.jsx` adds "Term…" button on electable titles (fill_method in 'elected' / 'both'). Clicking prompts for `term_length_days` (blank or 0 clears) and `election_lead_time_days` (default 7). PATCHes the title; server recomputes `next_election_due_at` from now on change. |
| F2 — Schedule surface | DONE | When a term is set, the title card displays "Term: N days · Next election: <date>" under the title metadata in purple-700 (consistent with the existing "elected" affordance color). `OrgSettings.jsx` adds 'Scheduled / fixed-term' as a third toggle in the trigger-sources checklist. |

---

## Verification matrix

| Check | Required | Result |
|---|---|---|
| Backend pytest (Phase 49 + every adjacent + migration cycles) | Yes | **226/226 PASS in 112s** across Phase 49 (12 + 2 migration cycle = 14), Phase 48 Stage 1+2+3 + B0 parity + Stage 1 migration cycle (36), Phase 47 + 47 migration cycle (24), Phase 46 + 46 migration cycle + 46a + 46a serializer-coverage (50), Phase 45a + 45b + 45b migration cycle (19), Phase 44 + 44 migration cycle (28), digest aggregation, Phase 13.3 digest routing, Phase 40 ops + hygiene. **No Stage 49 regressions across any nearby surface.** |
| No-term regression | Yes | **PASS** — `TestNoTermRegression::test_tick_does_not_open_election_for_no_term_title` runs the tick with `now` 10 years in the future and asserts `opened == 0` + no election proposal exists for the title. Existing electable titles default to no-term — no auto-scheduling without explicit opt-in. |
| Existing-title parity (Phase 48 B0 discipline) | Yes | **PASS** — `TestExistingTitleParity::test_existing_electable_titles_default_to_no_term_post_migration` asserts every title in a freshly-seeded org has `term_length_days = None` and `next_election_due_at = None`. The far-future tick still opens nothing. The migration's NULL defaults + the explicit opt-in gate together close the silent-regression class. |
| Due-term opens election | Yes | **PASS** — `TestDueTermOpensElection::test_tick_opens_election_at_lead_time_with_scheduled_trigger` asserts `opened == 1` + the new proposal carries `is_election=True` and `election_trigger='scheduled'`. The negative case (`test_tick_skips_titles_before_lead_time`) asserts tick at 25 days before due does NOT open (lead-time 7 means due-eligibility starts at 23 days before). |
| Idempotency (D5) | Yes | **PASS** — `TestIdempotency::test_second_tick_during_open_election_does_not_duplicate` runs two ticks while an election is open; second tick returns `opened == 0` + `skipped_idempotent == 1`. Only one election proposal exists for the title. |
| Hold-over (model A core) | Yes | **PASS** — `TestHoldOver::test_zero_candidate_scheduled_election_preserves_incumbent`: tick opens scheduled election with single incumbent, nobody nominates, `finalize_election` resolves to `no_election`, the incumbent's role row STILL reads `steward`, `count_active_governors >= 1`. Row-level assertion, not status code. |
| Next-due advancement (D6) | Yes | **PASS** — `TestNextDueAdvancement::test_scheduled_resolution_advances_next_due_exactly_once` asserts `next_election_due_at == original_due + 30 days` after a scheduled-trigger hold-over resolution. |
| Off-cycle does NOT move clock (B4) | Yes | **PASS** — `TestNextDueAdvancement::test_off_cycle_admin_election_does_not_move_schedule` runs a full admin_direct election end-to-end (open + nominate + advance to voting + close → install) and asserts `title.next_election_due_at` is unchanged from `original_due`. |
| `scheduled`-not-enabled gate (D2) | Yes | **PASS** — `TestSchedulerGate::test_term_set_but_scheduled_not_in_trigger_sources_opens_nothing`: title has a due term, org's `trigger_sources = ['admin_direct']`, tick returns `opened == 0` + `skipped_not_eligible == 1`. |
| System-title term + floor | Yes | **PASS (via reuse)** — the test suite exercises the steward system title (`_set_steward_title_electable`) for hold-over + next-due advancement. The 45a/45b floor logic + Phase 47 atomic-swap machinery are reused unchanged from `finalize_election` → `_apply_bound_role_for_assign`. No new code path; the floor preservation tests in Phase 48 Stage 1+2 cover the resolution side. |
| Title API surface (create + patch) | Yes | **PASS** — `TestTitleApiSetsTermClock::test_create_title_with_term_sets_next_due` POSTs a title with `term_length_days=365` and asserts `next_election_due_at` is set in the response. `test_patch_term_to_zero_clears_clock` PATCHes `term_length_days=0` and asserts both `term_length_days` and `next_election_due_at` become null. |
| Migration reversible + cycle test | Yes | **2/2 PASS** — `test_phase_49_migration_cycle.py` exercises upgrade-adds-schema + the full downgrade-then-upgrade cycle on SQLite. |
| PG smoke `--mode both --prior-revision h6b9c2d04523` | Yes | **PASS (all modes)** — fresh-DB bootstrap + upgrade-from-prior both succeed against postgres:16-alpine. |
| `bash start.sh` prod-mimic env | Yes | **PASS** — local prod-mimic harness imports main + creates an in-memory DB + runs `await run_one_tick(db)`. The tick completes cleanly with `scheduled_elections_opened` in the returned counts dict (and zero opens, as expected on a fresh empty DB). No wedge under the 48.1-async-native tick. |
| Digest scheduler still healthy | Yes | **PASS** — `/api/health/scheduler` post-deploy: `digest_scheduler.last_successful_tick_at = 2026-06-02T02:00:00.437759+00:00` (~36s after backend boot), `ticks_since_last_success = 0`. The Phase 49 term-check step rode the tick without wedging. The 48.1 async-native guarantee + the new try/except wrapper around `open_due_term_elections` both held. |
| Frontend build + bundle hash | Yes | **PASS** — bundle `index-B_70Vjza.js` live on prod (verified via `curl https://www.liquiddemocracy.us/`). |
| Browser verification (Chrome MCP, prod) | Yes | **PASS** — QA sub-agent walked the prod UI (post-deploy, post-SW cache bust to confirm `index-B_70Vjza.js` was actually live in DOM, not the stale Phase 48 `index-B-Q_wWQc.js`). Results: (a) **Trigger-source toggle** — with `Enable elections` on, three checkboxes render including the new `Scheduled / fixed-term` with hint text "Titles with a configured term auto-open an election when the term is due. Set a term on the title to opt that specific seat in." (b) **"Term…" button** — PASS-by-source: no titles on the verified demo org currently have `fill_method=elected|both` (system titles default to `assigned`-only), but the bundle source at offset ~1120100 confirms the render logic gates the button on `(fill_method==='elected' \|\| fill_method==='both')` and styles it `border-purple-300 text-purple-700`. (c) **Term display row** — PASS-by-source: no title has a term set yet, but the bundle confirms the purple row renders `Term: {term_length_days} days · Next election: {next_election_due_at}` when both are truthy. (d) **No console errors** across navigation + checkbox interactions. End-to-end "set a term → confirm next-election date surfaces → tick opens election" not exercised live to avoid mutating prod demo state; covered by the 14 Phase 49 integration tests + 2 migration cycle tests. |

---

## Branch + commit state

- Branch: `phase-49/scheduled-term-elections`
- Commit on branch: `7c3cad0` (the full pass)
- Merge commit on master: `4b18535` (no-ff)
- Pushed to origin/master: confirmed
- Railway deploy: `f7739bfe` SUCCESS at 2026-06-01 21:59:24 ET
- Bundle hash on prod: `index-B_70Vjza.js` (verified live)
- First successful digest tick under Phase 49: `2026-06-02T02:00:00.437759Z`

---

## Tech debt / followups

- **Term-limit-on-number-of-terms** (e.g. "max 2 consecutive terms" barring an incumbent from re-running) — explicitly out of scope; future refinement if any org asks.
- **Off-cycle elections resetting the scheduled clock** — explicitly rejected for this pass per B4 (fixed calendar cadence). If a future org wants "any election resets the clock," that's a per-title boolean opt-in; trivial to add but not built here.
- **Term-set notifications** — when a title's term changes, members holding the title (or running) aren't currently notified. Surface a `title.term_configured` notification in a future polish pass.
- **Reset clock manually** — there's no admin endpoint to force-advance `next_election_due_at` or reset it. PATCH-to-set-term-length-again is the workaround; explicit `POST /api/orgs/{slug}/titles/{id}/reset-schedule` could land as a small enhancement.
- **`/demo` "Sign in as ..." button regression (pre-existing, NOT Phase 49)** — Browser QA observed that clicking the persona "Sign in" button on the `/demo` page triggers zero network requests + zero sessionStorage writes (verified across 3 separate clicks). The `POST /api/auth/demo-login` endpoint itself is healthy (the QA agent authenticated successfully by calling it directly). `frontend/src/pages/Demo.jsx` was last modified in Phase 43 and is unchanged across Phases 44 → 49, so this is NOT a Phase 49 regression — it surfaced now because Phase 49's QA agent looked at the demo entry point. Tracked here for Z's attention as a separate small hotfix candidate; doesn't block Phase 49 (the underlying API works + direct-login is the workaround).

---

## Arc closure

Phase 49 closes the elected-leadership arc (45a → 49). Eleven passes across ~3 months: recovery (45a), ownerless-org floor + governance modes (45b), cosign-gated proposals (46), cosign refinements (46a), org titles / offices (47), permission-grant backfill hotfix (47a), binding elections — admin steward (48), council multi-winner + slate (48a), trigger config + elected revert + D12 (48b), digest scheduler async-native fix (48.1), scheduled/fixed-term elections (49). 

Operational hardening that landed alongside: the start.sh fresh-DB regex + users-existence guard, the hex-prefix-revision-ID convention (in CLAUDE.md), the parity helper for new fields reaching existing rows (Phase 48 B0), the recovery-script template (Phase 48.1's fix_stage2_column.py).

Phase 49 fully exercises the closing-the-arc invariant: it adds new trigger behavior WITHOUT changing the resolution semantics. `finalize_election` is unchanged for off-cycle paths; the new scheduled-trigger advancement is a single helper call. The locked model A means the floor invariants from 45a/45b/48 carry forward verbatim.
