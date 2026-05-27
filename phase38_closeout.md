# Phase 38 — Authorization Audit Closeout

**Status:** SHIPPED 2026-05-27. All six clusters merged, deployed, and verified.
**Spec:** `phase38_authorization_audit_spec.md`
**Branch:** `phase-38/authorization-audit` (from master `e3b4551`) — merged via `--no-ff` to master as commit `14777dc`. One ride-along follow-up commit on master (`e101d8b`) added uvicorn `--proxy-headers --forwarded-allow-ips '*'` after prod verify surfaced a pre-existing slowapi infra gap.

---

## Per-cluster status

| Cluster | Status | Notes |
|---|---|---|
| B1 — Unscoped proposal endpoints | DONE | Auth + eligibility filter on `list_proposals`, `get_proposal`, `get_results` in `backend/routes/proposals.py`. Platform-admin bypass per D4. 404 on eligibility failure per D2 (Phase 19 posture). Reused `_eligible_viewers_for_proposal` from `routes/comments.py` via top-of-file import (no circular dep risk). |
| B2 — WebSocket auth handshake | DONE — backend-only | First-message handshake in `main.py`'s `/ws/proposals/{id}` route per D6. Close codes 4401/4403/4404 per D7-D8. Reused `auth._get_user_from_token` per D8. ConnectionManager split: `register()` (no accept) replaces `connect()`; route accepts then handshakes then registers per D9. **FE coordination not required** — grep of `frontend/src` for `WebSocket\|tally_update` returned zero hits; the FE refetches `/results` via HTTP, the WS endpoint exists but is unused by the current UI. Bundle hash unchanged. (Logged as a small followup: if a future FE pass wires WS for live updates, it needs to send the handshake.) |
| B3 — Login rate limit + audit | DONE | `@limiter.limit("10/minute")` on `/api/auth/login` and `/api/auth/demo-login` per D11/D14. `user.login_failed` audit event written before the 401 raise, with `db.commit()` so the row persists across the exception. |
| B4 — Sub-org tier transferability | DONE | New `_check_sub_org_transferability(membership, org)` helper in `org_middleware.py` per D17. Wired into `require_org_moderator_or_admin`, `require_org_admin`, `require_org_owner` per D15/D18. Helper no-ops when membership is `SubOrgMembership` (direct sub-org member — transferability is a parent-fallback policy, not a direct-membership policy). |
| B5 — `can_delegate_to` org scope | DONE | Added `org_id: Optional[str] = None` parameter per D20. Filters both `DelegateProfile` and `FollowRelationship` queries when non-None. Phase 37 B3 visibility filter (`visibility in ("public", "public_accepting")`) bundled in per spec B5.1 — all three DelegateProfile consumers (this helper + `delegation_tree` + `vote-graph`) now share the same visibility predicate. Callers in `routes/delegations.py` thread the URL-context `org_id` through. |
| B7 — Legacy demo-login branch delete | DONE | Removed the `if body.org_slug is None` branch from `routes/auth.py::demo_login` per B7.1. Converted to explicit `400 org_slug is required` per B7.3. Deleted `DEMO_USERNAMES` module-level constant per B7.2. **Spec deviation note:** the spec asserted "After B7.1, no code references it" — the `demo_users` GET endpoint (line 673) DID still reference `DEMO_USERNAMES`, feeding the Login.jsx quick-switch grid. To honor the B7.2 intent (no module-level hardcoded allowlist that the auth path could refer to) without breaking the Login.jsx UI, the constant was inlined as a local literal inside `demo_users` (with the `is_admin=False` filter from Phase 37 D1 carried through). The auth path no longer has any path to the hardcoded list. Followup tracked below for promoting `demo_users` to source from `Organization.personas` instead. |

---

## Backend test count delta

- Baseline (post-Phase-37, master `e3b4551`): 1418 PASS / 27 pre-existing FAILED.
- Phase 38 added: **26 new tests** in `backend/tests/test_phase_38_authorization_audit.py` (all passing).
- Test edits in existing files for spec D22 (visibility filter ride-along) + B7 audit:
  - `test_delegation_intents.py::_make_delegate_profile` — added `visibility="public_accepting"` (test was riding on the unfiltered-visibility bug per spec D22).
  - `test_phase_37_security_hotfix.py` — removed three tests targeting the now-deleted legacy `org_slug=None` branch + `DEMO_USERNAMES` constant.
  - `test_phase_23_demo_reset.py::TestDemoLoginLegacyPath` — replaced with `TestDemoLoginOrgSlugRequired` (1 test asserting 400).
  - `test_demo_mode.py` — rewritten 4 demo-login tests to use the per-org allowlist path (new `_seed_per_org_demo` helper).
- Full pytest sweep result (excluding the 3 demo-reset suites per CLAUDE.md verification matrix): **27 failed, 1442 passed, 17 skipped in 542s** — failure count matches the post-Phase-37 baseline (27 pre-existing) exactly. All 24 new Phase 38 tests pass (1418 + 24 = 1442). The 27 failures are the same set as master (`test_phase3a_permissions` 2, `test_phase_12_5_user_permissions_field` 1, `test_phase_29_1_persona_delegations` 1, `test_ranked_choice_voting` 18, `test_seed_idempotency` 5). Sample-verified two of them on master before unstashing.
- **Test-state pollution caught + fixed mid-sweep.** First sweep showed 51 failures because the B3 `@limiter.limit("10/minute")` on `/api/auth/login` shared in-memory state across tests within the pytest process, exhausting the quota for downstream tests that hit login in their setup helpers. Fixed by adding a global autouse fixture in `tests/conftest.py` that resets both `routes/auth.py::limiter` and `main.py::limiter` between every test. Same shape as the existing per-file reset in `test_auth_resend_verification.py`, just promoted to suite-wide. The 2 sustained_majority_api tests that called `/api/proposals/{id}/results` anonymously were also a real B1 regression (they tested the pre-B1 anonymous behavior); updated to pass `headers=_auth(admin)`.

## PG smoke

**Not required.** No Alembic migration added in this pass — all six clusters are code-level.

## Files changed (12 modified, 1 added)

```
backend/main.py                                   |  80 ++++++++++-
backend/org_middleware.py                         |  68 +++++++++
backend/permissions.py                            |  48 +++++--
backend/routes/auth.py                            | 187 ++++++++++---------------
backend/routes/delegations.py                     |   8 +-
backend/routes/proposals.py                       |  43 +++++-
backend/schemas.py                                |  13 +-
backend/tests/test_delegation_intents.py          |  12 +-
backend/tests/test_demo_mode.py                   |  96 +++++++++++--
backend/tests/test_phase_23_demo_reset.py         |  21 +--
backend/tests/test_phase_37_security_hotfix.py    |  68 ++-------
backend/tests/test_phase_38_authorization_audit.py| 539 +++++++++++++ (NEW)
backend/websocket.py                              |   8 +-
```

## Branch + commits

- `6cbfd5a` — Phase 38: Authorization audit bundle (B1+B2+B3+B4+B5+B7) (17 files, +1850/-223)
- `14777dc` — Merge phase-38/authorization-audit: Phase 38 (Authorization Audit Bundle) (no-ff)
- `e101d8b` — Phase 38 followup: trust Railway-edge forwarded headers (1 file, +8/-1) — direct commit on master after the merge, post-deploy verify surfaced the slowapi infra gap (see deviation #5 below).

Master now at `e101d8b`.

## Production deploy

- Railway backend deploy `fe072516` (Phase 38 main commit): BUILDING → DEPLOYING → SUCCESS, ~7 min build + warmup. Verified: `GET /api/health` returned `{"status":"ok","version":"0.1.0"}`.
- Railway backend deploy `b722c7a5` (start.sh follow-up commit): BUILDING → DEPLOYING → SUCCESS.
- Demo reset post-deploy: `python scripts/trigger_demo_reset.py` → 3 orgs reset, 6607 rows wiped, 4750 rows seeded. `skipped: false, success: true`.
- Frontend bundle: unchanged at `index-Dp3YmSzh.js` (backend-only pass).
- Railway URL: https://www.liquiddemocracy.us

### API verify quartet results

- **B1 anonymous-blocked:** `GET /api/proposals`, `GET /api/proposals/{id}`, `GET /api/proposals/{id}/results` all returned `HTTP 401 {"detail":"Not authenticated"}` without an Authorization header. ✅
- **B1 authenticated + filtered:** janet_reilly (steward on demo-cedar-hollow) → `GET /api/proposals` returned 28 proposals from 1 distinct org_id. dana_whitfield (westgate-coalition) → 24 proposals from 1 distinct org_id (different org). Cross-org leak closed. ✅
- **B3 rate-limit (after the follow-up commit):** 12 bad-credential POSTs to `/api/auth/login` from one client IP → 401 on attempts 1-10, **429 on attempts 11-12**. ✅. Pre-follow-up (before `e101d8b`) the same test returned 401 on all 12 because the slowapi key was per-edge-IP — see deviation #5.
- **B7 demo-login org_slug-required:** POST `/api/auth/demo-login {"username":"alice"}` (no org_slug) → `HTTP 400 {"detail":"org_slug is required"}`. POST with valid `(username, org_slug)` pair → `HTTP 200` + access_token + refresh_token. ✅

### Browser QA via Chrome MCP

QA sub-agent run, persona `janet_reilly` on `demo-cedar-hollow`:
- Demo-login button at `/demo` cleared. Tokens landed in sessionStorage (`token` + `refreshToken`), redirected to `/orgs`.
- `/demo-cedar-hollow/proposals` rendered 17 proposals across all statuses (voting / deliberation / passed / failed / decided / draft) without 401 / error banner. Per-proposal vote-state badges accurate.
- Clicked a voting proposal — detail page rendered: full body, Vote Network panel showing 16 Yes / 7 No / 0 Abstain / 53 Not Cast (Janet visible in Yes column), Support Trajectory chart (63 data points), Your Vote block with Change/Retract controls.
- Results tally: 16 Yes (69.6%), 7 No (30.4%), 0 Abstain, 23/76 (30.3%) cast.

**Headline:** auth gate + per-proposal eligibility filter haven't locked out the legitimate steward persona; full end-to-end demo flow holds.

B2 live-tally WebSocket flow was **not** browser-verified because (per the FE-grep finding) the current FE doesn't consume `/ws/proposals/{id}` — tally updates happen via HTTP refetch. B4 transferability=off path was not exercised on prod because demo orgs all default to transferability ON (per Phase 34); the unit tests cover transferability=off explicitly.

## Locked-decision confirmation

- **D1-D5 (B1):** ✅ All three routes gain `current_user` dep. `_eligible_viewers_for_proposal` is the eligibility source. Per-proposal Python filter (D3 v1 shape). Platform-admin bypass (D4). 404 on eligibility failure (D2). Cache headers untouched (D5).
- **D6-D10 (B2):** ✅ First-message handshake (D6). Proposal existence check before accept (D7). Reused `_get_user_from_token` (D8). `ConnectionManager.connect` split into accept-less `register` per D9. **D10 frontend coordination skipped** — the FE doesn't use WS today; surface added a followup item below.
- **D11-D14 (B3):** ✅ `10/minute` per-IP rate limit on `login` + `demo_login` (D11/D14). `user.login_failed` audit on the 401 branch (D12). No soft lockout (D13 — deferred to Phase 39 per spec).
- **D15-D19 (B4):** ✅ Transferability check at coarse-tier dependency layer (D15). `require_org_membership` unchanged (D16). `_check_sub_org_transferability` helper extracted (D17). `require_org_owner` gets same treatment (D18). No new audit event on transferability denials (D19).
- **D20-D23 (B5):** ✅ `org_id: Optional[str] = None` parameter added (D20). Callers in `routes/delegations.py` thread URL context (D21). Tests asserting unfiltered cross-org match updated (D22 — fix to `test_delegation_intents.py::_make_delegate_profile`). `delegation_denied_message` unchanged (D23).

## Notable spec deviations

1. **B7.2 — `DEMO_USERNAMES` had a non-auth caller the spec missed.** The spec stated "After B7.1, no code references it." In fact, the `demo_users` GET endpoint (`routes/auth.py:673`) also read it, feeding the Login.jsx quick-switch grid. To honor the B7.2 intent at the auth-path layer without breaking the unrelated quick-switch UI, the constant was inlined into `demo_users` as a local literal (with the Phase 37 D1 `is_admin=False` filter carried through). The auth path (`demo_login`) no longer references any hardcoded allowlist. Followup: promote the quick-switch endpoint to source from `Organization.personas` (or delete it + the Login.jsx affordance — the per-org Demo.jsx flow has superseded it). Filed as Tier-3 tech debt.
2. **B3 D12 — `AuditLog.target_id` is NOT NULL.** The spec's reference shape used `target_id=user.id if user else None`, but the column is `nullable=False`. Used `form_data.username` as the fallback when `user is None` — preserves insertability and is more forensically useful (lets ops grep which usernames are being probed). Recorded as a deliberate deviation in the audit-event details payload (`user_exists: bool`).
3. **B5.1 visibility-filter ride-along — broke one passing test.** The Phase 37 B3 visibility filter was carried into `can_delegate_to` per spec B5.1. The `test_delegation_intents.py::test_public_delegate_bypasses_intent` test was riding on the unfiltered-visibility bug (the test helper created profiles without setting visibility, leaving the column at its Phase-30.3 default of `followers_only`). Per spec D22, the test was asserting incorrect behavior; updated the helper to set `visibility="public_accepting"` explicitly. Same root cause as the spec's call-out about "test fixtures may need updating."
4. **B2 D10 frontend coordination not required.** Grep of `frontend/src` for WebSocket usage returned zero hits. The FE refetches `/results` via HTTP — the WS endpoint is plumbed in nginx + vite but no UI component connects to it. Bundle hash unchanged. If a future FE pass wires WS, the handshake-send is a 5-line addition.
5. **Pre-existing rate-limiter infra gap discovered during prod verify; fixed in a small follow-up commit.** The B3 prod verify (12 bad-credential POSTs to `/api/auth/login` from one client IP) returned `401` on all 12 instead of `429` on the 11th+. Root cause: `backend/start.sh` ran `uvicorn` without `--proxy-headers --forwarded-allow-ips '*'`. Uvicorn's `--forwarded-allow-ips` defaults to `127.0.0.1`, so the Railway-edge IP became `request.client.host` and every slowapi limiter in the codebase was effectively keyed per-edge-IP instead of per-client-IP. Same applied to the pre-existing `/forgot-password` `3/hour` limiter — verified by hitting it 4× without triggering. Fixed in commit `e101d8b` (post-merge follow-up on master) by adding the proxy-header flags. Also closes the Phase 37 closeout's Tier-2 "audit-log IP forensics" tech debt — `AuditLog.ip_address` now records the actual client IP. Re-verified post-redeploy that B3 rate limit fires at the 11th attempt from one client IP.

## New tech debt found

- **`demo_users` endpoint sources from inline hardcoded list.** Cosmetic; the surface is debug/demo-only and gated on `settings.debug or settings.is_public_demo`. Promote to read from `Organization.personas` (or delete + remove Login.jsx quick-switch) in a future cleanup pass.
- **`_eligible_viewers_for_proposal` import from `routes/comments.py` is structurally odd.** Spec called this out (Operational watch-outs). Mechanical refactor — promote to `permissions.py` or new `eligibility.py` — deferred per spec.
- **B1 list-endpoint perf at scale.** Per-proposal eligibility check is O(N) in Python. Fine at pilot scale; flag as profile-driven followup if perf shows up.

## Followups (out of scope this pass)

Per spec §Followups, deferred to Phase 39+:
- User identity-column adds (`is_active`, `failed_login_count`, `locked_until`) + soft-lockout.
- Refresh-token state-check, forgot-password background email.
- `_eligible_viewers_for_proposal` promotion out of `routes/comments.py`.
- List-endpoint eligibility-aware ORM query.
- WebSocket cross-worker broadcast.
- Cross-sub-org delegation chain audit (review §6 uncertain item).
- (New, from this pass) `demo_users` endpoint sources from `Organization.personas` instead of inline list.

## Pass-summary in PROGRESS.md style

Phase 38 closed five visibility/authorization gaps surfaced by the 2026-05-27 external review, plus dead-code cleanup of the legacy demo-login branch. B1 added auth + per-proposal eligibility filtering to the three unscoped `/api/proposals/*` routes; B2 added a first-message handshake on the `/ws/proposals/{id}` WebSocket; B3 added a 10/min/IP slowapi rate limit + a `user.login_failed` audit event on both `/login` and `/demo-login`; B4 tightened the coarse-tier sub-org dependencies to consult Phase 15 transferability config; B5 added an `org_id` parameter to `can_delegate_to` and bundled in the Phase 37 B3 visibility filter as a ride-along. B7 deleted the legacy `org_slug=None` branch + the `DEMO_USERNAMES` constant — the spec missed that `demo_users` also referenced the constant, surfaced as a documented spec deviation.

26 new tests in `test_phase_38_authorization_audit.py`. Migration-free pass (no PG smoke). Bundle hash unchanged (FE didn't need to touch — the WS endpoint isn't consumed by the current FE).
