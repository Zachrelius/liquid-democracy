# Phase 48.1 — Digest Scheduler Async-Native Fix — Closeout

**Spec:** `phase48_1_digest_async_fix_spec.md`
**Branch:** `phase-48.1/digest-async-fix` → merged `--no-ff` to master
**Date:** 2026-06-01

---

## Overall

**SHIPPED.** Removes the digest-loop self-deadlock at the root by making the send path async-native end-to-end. The digest tick now `await`s `send_email` directly instead of bouncing through `_run_async`, which deadlocked the event-loop thread when called from within uvicorn's running loop (the prod-hang scenario from Phase 46a). `_run_async` is unchanged; only the digest path stops using it. Real-time `send_event_email` via FastAPI `BackgroundTasks` is untouched (it correctly uses `_run_async`'s `asyncio.run` branch off the main loop).

**B5 (scheduler re-enable):** DONE + observed healthy. `DISABLE_DIGEST_SCHEDULER` removed from Railway backend env at 2026-06-01 19:56 ET; redeploy `ff8f06f0` SUCCESS; first live tick observed at `2026-06-01T23:57:11Z` (UTC) — `/api/health/scheduler` shows `digest_scheduler.last_successful_tick_at` = `2026-06-01T23:57:11.804139+00:00`, `ticks_since_last_success` = 0; `/api/health` returns 200 (backend NOT 502). The async-native chain works live; the prod hang from Phase 46a is closed at the root.

---

## Per-cluster status

| Cluster | Status | Notes |
|---|---|---|
| B1 — `email_service` async-native send | DONE | New `async def send_org_email_async(...)` is the real implementation; awaits `send_email` at the end. The sync `send_org_email(...)` becomes a thin wrapper around the shared `_prepare_org_email(...)` helper that does templating + recipient resolution; the wrapper calls `_run_async(send_email(...))` for genuinely-sync callers (the real-time `send_event_email` path via `BackgroundTasks`). `send_email`'s signature + transport behavior unchanged. `_run_async` unchanged. |
| B2 — Digest tick chain async | DONE | `render_and_send_digest`, `flush_quiet_hours_queue`, `run_one_tick` are now `async def`. Send call sites replaced: `await send_email(...)` for the digest body; `await send_org_email_async(...)` for the quiet-hours flush. `digest_loop` now `await run_one_tick(db)` inside its `instrument_tick` block. Atomic-claim-before-send ordering preserved; per-user/per-cadence try/except blocks preserved; Phase 40 B4 health-state updates preserved; demo reset, halfway-deadline check, pending-actions expiry, tail cleanup all preserved. Call-convention change, not a logic rewrite. |
| B3 — DB stays sync | DONE | No async SQLAlchemy. Sync `Session` operations inside the async functions are correct — the deadlock was the email coroutine, not DB work. |
| B4 — Tests | DONE | Three existing send-exercising tests (`test_render_marks_delivered_after_send`, `test_flush_quiet_hours_queue_sends_and_clears_flag`, `test_flush_quiet_hours_queue_skips_non_queued_rows`) converted to `pytest.mark.asyncio` + `AsyncMock`. `aggregate_for_user` tests unchanged (still sync). **New regression test `test_run_one_tick_inside_event_loop_does_not_deadlock`** specifically exercises the prod-hang scenario: a tick with a qualifying digest, run inside an event loop, with `send_email` mocked async, bounded by `asyncio.wait_for(timeout=10)`. A regression would manifest as a timeout. Asserts both (a) no-deadlock, (b) the await path is exercised (`mock_send.await_count >= 1`), and (c) the delivered flag flips on the notification row. |
| B5 — Re-enable scheduler on Railway | DONE | `DISABLE_DIGEST_SCHEDULER` removed from Railway backend env via `railway variable delete --service backend DISABLE_DIGEST_SCHEDULER` at 19:56 ET. Variable change did NOT auto-trigger a redeploy on this Railway project (observation worth keeping — variable changes via CLI here are inert until a redeploy or push), so I triggered one with `railway redeploy --service backend`. Redeploy `ff8f06f0` SUCCESS at 19:56:51 ET. Backend booted with the env var absent; `digest_loop` left the disabled branch + the first tick completed in ~10s. `/api/health/scheduler` immediately after deploy: `digest_scheduler.last_successful_tick_at = 2026-06-01T23:57:11.804139+00:00`, `ticks_since_last_success = 0`. `/api/health` = 200. **First live tick under the async-native chain succeeded cleanly + the backend stayed healthy — the prod-hang scenario is closed.** Next tick is hourly (TICK_SECONDS = 3600); a second-tick observation would happen at ~20:57 ET if Z wants to spot-check, but the load-bearing signal (first tick + non-502 backend) is captured. |

---

## Verification matrix

| Check | Required | Result |
|---|---|---|
| Backend pytest (digest + adjacent + Phase 48 sweep) | Yes | **150/150 PASS** in 57s across `test_digest_aggregation.py` (14, incl. the new regression), `test_phase13_3_digest_routing.py`, `test_phase_40_ops_and_hygiene.py`, `test_notifications_endpoints.py`, `test_phase_46_cosign_gated_proposals.py`, `test_phase_46a_cosign_refinements.py`, `test_phase_44_multi_admin_approval.py`, `test_phase_48_stage1_elections.py`, `test_phase_48_stage2_elections.py`, `test_phase_48_stage3_elections.py`. |
| No-deadlock regression test (B4) | Yes | **PASS** — `test_run_one_tick_inside_event_loop_does_not_deadlock` exercises the prod-hang scenario inside an asyncio loop and completes within 10s with `mock_send.await_count >= 1` + `counts["daily"] == 1` + the delivered flag flipped. A regression would surface as `asyncio.wait_for` timing out. |
| Digest behavior preserved | Yes | **PASS** — atomic-claim-before-send call ordering unchanged; multi-worker double-send protection unchanged (`with_for_update(skip_locked=True)` + the "first-tick-wins, second-tick-skips" semantics); quiet-hours flush still sends + clears the flag; empty digests still don't send; per-user try/except still isolates failures. Verified by the pre-existing tests + the new regression. |
| Real-time email path untouched | Yes | **PASS** — `send_event_email` still calls `send_org_email` (the sync wrapper) which uses `_run_async`. `_run_async`'s logic is byte-identical to pre-Phase-48.1. No change to behavior when invoked from `BackgroundTasks`'s threadpool. The notifications endpoints regression suite (57 tests inside the adjacent sweep) confirms the real-time path is intact. |
| No migration | Yes | **No Alembic revision added.** Behavior change is purely at the application call-convention layer. `alembic upgrade head` against prod is unchanged. |
| `bash start.sh` prod-mimic env | Yes | **PASS** — local boot-mimic exercises the full chain: imports `main`, starts `digest_loop` under `DISABLE_DIGEST_SCHEDULER=true`, hits the disabled-branch sleep, cancels cleanly; then unsets the env var and runs `await run_one_tick(db)` against an empty in-memory DB — completes cleanly returning `{daily: 0, weekly: 0, quiet: 0, cleaned: 0, halfway_*: 0, pending_actions_expired: 0, demo_reset: 'completed orgs=3 wiped=0 seeded=4750'}`. The async chain works end-to-end with no wedge. |
| Frontend | N/A | **No frontend change.** |
| Scheduler re-enabled in prod (B5) | Yes | **PASS** — env var removed at 19:56 ET, redeploy `ff8f06f0` SUCCESS, first live tick at `2026-06-01T23:57:11Z` (~10s after backend boot), `ticks_since_last_success = 0`, backend stayed at 200. See Per-cluster B5 row above. |
| Bundle hash / backend non-502 post-deploy | Yes | **PASS** — Bundle unchanged from Phase 48 Stage 3 (`index-B-Q_wWQc.js`, no FE change). Backend `/api/health` = 200 across both deploys (the deploy of the fix + the deploy after removing the env var). `/api/health/scheduler` confirms a fresh successful digest tick. |

---

## Branch + commit state

- Branch: `phase-48.1/digest-async-fix`
- Commit on branch: `14dc72a` (the async-native fix + regression test)
- Merge commit on master: `ed6909d` (no-ff merge)
- Pushed to origin/master: confirmed
- Railway deploy of fix: `f55c2b00` SUCCESS at 19:54 ET
- Railway redeploy after B5 env-var removal: `ff8f06f0` SUCCESS at 19:56 ET
- Bundle hash: unchanged (no FE change), `index-B-Q_wWQc.js`
- First live digest tick after re-enable: `2026-06-01T23:57:11Z`

---

## Notes for Z

- **The deadlock is closed at the root.** The digest tick now `await`s the email transport directly. There is no longer any path through `_run_async` from the digest call chain.
- **`_run_async` is unchanged** and is still used by the sync real-time send path (`send_event_email` via FastAPI `BackgroundTasks`), which runs sync tasks off the main loop in a threadpool. That branch is correct + safe there.
- **The fix is invisible until B5.** After the deploy lands healthy, the closeout is updated with the B5 result: env var removed at `<time>`, first live tick observed at `<time>`, `/api/health/scheduler` showed `last_successful_tick_at` = `<timestamp>`, `ticks_since_last_success` = 0, backend stayed non-502.
- **Inert-window emails are forfeit.** No retroactive send. Per spec: digests are a convenience feed; the in-app notification rows were never affected (they were always written), so the user experience loss is bounded to the email reminder layer.
