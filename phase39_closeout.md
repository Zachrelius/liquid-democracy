# Phase 39 — Identity Hardening Closeout

**Status:** [pending deploy + browser QA] — drafted 2026-05-27
**Spec:** `phase39_identity_hardening_spec.md`
**Branch:** `phase-39/identity-hardening` (from master `e101d8b` — branch was created from `6d90ded`, which is `e101d8b` + the Phase 38 closeout fill-in commit; no functional difference).

---

## Per-cluster status

| Cluster | Status | Notes |
|---|---|---|
| B3 — ORM nullable=False sync (4 Phase 18b tables) | DONE | Updated `Delegation.org_id`, `FollowRequest.org_id`, `FollowRelationship.org_id`, `DelegationIntent.org_id` from `Mapped[Optional[str]] nullable=True` to `Mapped[str] nullable=False`. Pure declaration sync — no migration. Local fresh `create_all` check confirmed all four columns come up `nullable=False`. Closes the fresh-DB-vs-upgraded-DB schema-drift gap. |
| B2 — forgot-password BackgroundTasks move | DONE | One-line move at `routes/auth.py:594-643`: `await send_password_reset_email(...)` → `background_tasks.add_task(send_password_reset_email, ...)`. `db.commit()` already happened before the response per the existing register pattern. |
| B1 — User.is_active + state guards | DONE | Added `is_active` to `User` model (Boolean, NOT NULL, server_default `true`). `_get_user_from_token` in `backend/auth.py` now filters on `User.is_active == True` (replaces `db.get` with an explicit filtered query — `db.get` bypasses filters by design). `refresh_token` route now re-fetches `User` with the same filter before issuing a fresh access token (pre-Phase-39 the refresh path didn't re-check user state at all, letting an inactive user keep refreshing). |
| B4 — Soft-lockout columns + login wiring | DONE | Added `failed_login_count: int NOT NULL default 0` and `locked_until: DateTime nullable` to `User`. `routes/auth.py` carries the new `LOCKOUT_THRESHOLD = 10` + `LOCKOUT_WINDOW_SECONDS = 900` constants. Login route now: (a) checks `locked_until > now` before password-check, returning 401 with `detail={"reason": "account_locked", "locked_until": ...}` + incrementing the counter; (b) on bad-password increments + sets `locked_until` at threshold (only when user exists, D16); (c) on successful auth resets `failed_login_count=0, locked_until=None`. `reset_password` endpoint also clears lockout state on success (D17). |
| Migration | DONE | New revision `4b0bf8f1761f_phase_39_identity_hardening.py` adds all 3 User columns in one shot. **Idempotency guards** added per CLAUDE.md migration convention — pre-inspect `users` columns, no-op if already present. PG smoke's upgrade-mode caught this on the first run (`create_all` builds the columns from the current models before `stamp prior` + `upgrade head` runs the migration's `ALTER TABLE ADD COLUMN`, producing a DuplicateColumn collision). Down-migration drops in reverse order with the same guards. |

---

## Backend test count delta

- Baseline (post-Phase-38, master `e101d8b`): 1442 PASS / 27 pre-existing FAILED.
- Phase 39 added: **17 new tests** in `backend/tests/test_phase_39_identity_hardening.py` (all passing locally).
  - B1: 4 tests (inactive token 401, refresh rejects inactive, active sanity, default-true)
  - B2: 2 tests (known-email enqueues `send_password_reset_email` via `BackgroundTasks`; unknown-email returns 200 without enqueueing)
  - B3: 4 parametrized tests (one per Phase 18b table — `delegations`, `follow_requests`, `follow_relationships`, `delegation_intents`)
  - B4: 6 tests (lockout-triggers, lockout-persists, no-lockout-for-nonexistent, success-resets, increments-during-lockout, password-reset-clears)
  - Migration: 1 cycle test
- Full sweep result: [PENDING — sweep in flight]

## PG smoke

**`python backend/scripts/pg_smoke.py --mode both --prior-revision b6d8e2f1a350` — PASS (both modes).** First run failed in `upgrade` mode with `DuplicateColumn: "is_active"` because pg_smoke's upgrade path is `create_all → stamp prior → upgrade head` (an over-shaped schema stamped at prior, then the migration tries to `ADD COLUMN` columns that already exist). Fixed by adding idempotency guards to the migration's `upgrade()` + `downgrade()` (pre-inspect `users` column list, no-op if present). Second run cleared both modes.

Docker Desktop wasn't running at first attempt — started it manually (one-time setup cost; not in spec scope). Future migration-bearing passes can assume Docker is up.

## B2 test approach deviation

The spec sketched the B2 timing test as "measure response time at p50 over 10 trials each, assert <50ms." TestClient awaits FastAPI BackgroundTasks before returning from `.post()` (well-documented FastAPI behavior), so a slow-stub timing test would slow down the `.post()` itself — defeating the test's purpose. Replaced the timing assertion with a structural-correctness check: spy on `BackgroundTasks.add_task` and assert that `send_password_reset_email` is enqueued (rather than awaited inline) on the known-email branch, and is NOT enqueued on the unknown-email branch. Catches the exact regression the spec was guarding against (re-inlining the email send into the request path).

The end-to-end timing closure is verified post-deploy via the API verify trio — `curl`-based timing measurement against the real HTTP transport (no TestClient awaiting background tasks).

## Files changed

```
backend/auth.py                                         |   ~15 lines  (B1)
backend/main.py                                         |    no change
backend/migrations/versions/4b0bf8f1761f_phase_39...py  |  ~70 lines  (NEW)
backend/models.py                                       |   ~50 lines  (B1+B3+B4)
backend/routes/auth.py                                  |  ~70 lines  (B1+B2+B4)
backend/tests/test_phase_39_identity_hardening.py       | ~530 lines  (NEW)
phase39_identity_hardening_spec.md                      |   (spec, NEW at root)
phase39_closeout.md                                     |   (this file, NEW at root)
```

## Branch + commits

[PENDING — commit + merge after sweep clears]

## Production deploy

[PENDING]

## API verify trio

[PENDING]

## Browser verification

[PENDING]

## Locked-decision confirmation

- **D1-D5 (B1):** ✅ Column added Boolean NOT NULL default True. State checks in both `_get_user_from_token` AND `refresh_token`. 401 (not 403) on inactive. No new endpoint to flip — DB-side UPDATE only.
- **D6-D7 (B2):** ✅ BackgroundTasks dependency added to signature, email-send enqueued via add_task. db.commit() before the enqueue (preserves token row visibility for the background task).
- **D8-D10 (B3):** ✅ All four tables synced. No migration. Local fresh-DB inspection confirms NOT NULL.
- **D11-D18 (B4):** ✅ Columns added in same migration as is_active. Login logic per D12 (lockout-check before pw-check, increment on bad pw + during lockout window per D12, set locked_until at threshold). LOCKOUT_THRESHOLD/LOCKOUT_WINDOW_SECONDS constants per D13/D14. Successful login resets per D15. No phantom rows for nonexistent usernames per D16. Password reset clears state per D17. Lockout 401 carries `locked_until` in detail per D18.
- **Migration convention:** ✅ One revision for all three columns per spec sequencing. Reversible. Idempotency guards added (per CLAUDE.md convention) after PG smoke surfaced the create_all-then-upgrade collision.

## Notable spec deviations

1. **B2 test approach.** TestClient behavior made the spec's timing test unusable; replaced with structural-spy assertion that catches the same regression class. See B2 test approach deviation above.
2. **Idempotency guards on the migration.** Spec didn't explicitly call for them; CLAUDE.md's "Idempotent migration guards" convention covers it. The first PG smoke run surfaced the need.

## New tech debt found

- **None novel.** The Phase 38 followup list (promote `_eligible_viewers_for_proposal`, WebSocket FE wiring, etc.) remains the standing queue.

## Followups (out of scope this pass)

Per spec §Followups, Phase 40 queue is unchanged + a couple of small items spillover from this pass:

- **Phase 40** — ops + multi-instance prep (demo-reset DB-level lock, Pillow decompression-bomb, scheduler health endpoint, WORKERS=1 startup assert, §4 minor items).
- **Admin "revoke user" endpoint.** v1 mechanism is direct DB update via Railway PG console.
- **Exponential-backoff lockout** — refine if abuse surfaces; fixed 15-min window for v1.
- **Locked-account UX in the frontend** — B4 D18 includes `locked_until` in the 401 detail; a future FE pass can render it.
- **Phase 38 standing items** — `demo_users` sources from `Organization.personas`, `_eligible_viewers_for_proposal` promotion out of `routes/comments.py`, WebSocket FE wiring decision.

## Pass-summary in PROGRESS.md style

Phase 39 closed the identity-lifecycle layer of the 2026-05-27 external review. B1 added `User.is_active` with state checks in `_get_user_from_token` and `refresh_token`, giving ops a soft-revocation lever and closing the refresh-token-doesn't-re-check-user-state gap. B2 moved the `forgot-password` email send into `BackgroundTasks`, closing the timing side-channel for enumerating registered emails. B3 synced the four Phase 18b tables' `org_id` ORM declarations to NOT NULL, closing the fresh-DB-vs-upgraded-DB schema drift. B4 added `User.failed_login_count` + `User.locked_until` with login-route wiring for per-username soft-lockout (10 consecutive failures → 15-minute window). Per-IP rate limit (Phase 38 B3) + per-username lockout (Phase 39 B4) compound: an attacker must defeat both gates.

One migration (`4b0bf8f1761f`) adding three User columns. PG smoke `--mode both` PASS after idempotency guards added (caught by upgrade mode on first run). 17 new tests; full sweep pending.
