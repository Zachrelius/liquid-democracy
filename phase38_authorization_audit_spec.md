# Phase 38 — Authorization Audit

**Status:** Spec, dispatched [pending]. Written 2026-05-27, updated 2026-05-27 post-Phase-37 close with both dependency placeholders resolved (B6 dropped, B7 added).

This document combines dispatch framing (top) with the full spec body (below). It is intended to be picked up by a **Claude code instance that has not seen this codebase before** — the team-choice decision was to put fresh eyes on this pass since it's specifically an audit of visibility boundaries the continuing dev team has been acclimated to. The session-start read list below is the ramp.

---

## Session-start read list

Read these in order before touching code. Do not skip — every section here references specific conventions and prior decisions that will be tested at dispatch time.

1. **`CLAUDE.md`** at the repo root. The whole file. Particularly: "Operating mode" (this project runs with permissions skipped; the safety net is convention), "Branch and merge convention" (one branch per phase, `--no-ff` to master, never force-push), "Production deploy convention" (Railway auto-deploys; verify backend deploy success after push), "Testing strategy" ("assert side effects, not just API contracts"; "browser verification via Claude in Chrome MCP for load-bearing user-facing changes"), and "Closeout report shape" — the contract the planning agent reads.
2. **`external_review_2026-05-27.md`** §2.1, §2.2, §2.3, §2.7, and §3.6 — the five findings this pass closes. The §6 "uncertain — human eye" section is also worth a skim; some of those items intersect with what you're touching.
3. **`PROGRESS.md`** — at minimum the most recent ~10 phase entries (Phase 30 onwards). Particularly the Phase 4c multi-tenancy retrofit framing, Phase 8.5 sub-organizations + Decisions 6/7, Phase 10.1 cross-scope vote leak fix, Phase 12 role permissions (system_key vs. legacy column), Phase 15 sub-org transferability config, Phase 18 delegation org-scoping retrofit, Phase 30.3 visibility model consolidation. These passes are the historical reasons the gates you're tightening look the way they do.
4. **`phase37_security_hotfix_spec.md`** and **`phase37_closeout.md`** (the latter exists at dispatch time) — what just shipped, what audit-log-grep result Phase 37 produced, whether the legacy demo-login path is in active use.
5. **Schema overview:** skim `backend/models.py` for `Organization`, `OrgMembership`, `Role`, `SubOrgMembership`, `Proposal`, `DelegateProfile`. Don't read end-to-end; just internalize relationships.

After the read pass, you should be able to answer without grepping: what does `OrgMembership.role.system_key` look like in practice (it's `"steward" | "admin" | "moderator" | "member" | "viewer"` post-Phase-12); when is `proposal.sub_org_id` non-null vs. null; what is Decision 6 versus Decision 7 in the Phase 8.5 visibility model.

## Phase 37 dependency outcomes (both resolved)

- **Audit-log grep result: BENIGN. B6 cluster NOT in scope.** Phase 37 grep returned 25 events between 2026-04-25 and 2026-05-04, all from Railway-internal `100.64.0.x` IPs (RFC 6598 / CGN egress); zero external IPs; zero suspect downstream admin actions (`make_admin` / `delete_user` / `seed` / `time_simulation` / `org.delete`) in audit history. Z confirmed the events as their own Phase 6.5 → 23.2 dev/test activity. No exploitation. Phase 38 does NOT add a post-exploitation verification cluster.
- **Legacy demo-login FE grep result: dead code. B7 cluster IN scope.** Phase 37 closeout confirms (and re-verified by grep at spec update time): the only frontend caller of `/api/auth/demo-login` is `frontend/src/pages/Demo.jsx:61`, which always passes `org_slug`. The legacy `if body.org_slug is None` branch in `backend/routes/auth.py` (lines 788-817 post-Phase-37) has no live caller. Phase 38 includes **B7 — delete the legacy branch + `DEMO_USERNAMES` constant**, closing the Phase 37 D2 deferral.

---

## Dispatch framing

### Goal

Close five visibility/authorization gaps surfaced by the 2026-05-27 external review, plus dead-code cleanup of the legacy demo-login branch that Phase 37 D2 deferred to this pass. All six items are cross-org or cross-scope leaks where the current code path silently allows access that the platform's visibility model intends to block — except B7, which is a one-step cleanup of a now-confirmed-dead code path. None are migrations; all are code-level gates added to existing endpoints + existing helpers, or in B7's case, deletion of a known-unused branch. The pass is best understood as **applying the existing eligibility helpers (`_eligible_viewers_for_proposal`, `role_transfers_to_sub_orgs`, etc.) at every site where they should already be gating but aren't**.

The six items:

- **B1** (review §2.1): the unscoped `/api/proposals/*` legacy routes (`list_proposals`, `get_proposal`, `get_results`) have no `current_user` dependency and no eligibility filter. Unauthenticated callers can list every proposal across every org, fetch any proposal by ID, and read live tallies for in-progress votes in private sub-orgs. Three routes, all in `backend/routes/proposals.py`.
- **B2** (review §2.2): the `/ws/proposals/{proposal_id}` WebSocket has no auth at connect-time and no membership check. Anyone can subscribe to live `tally_update` broadcasts on any proposal. One route, in `backend/main.py`.
- **B3** (review §2.3): the `/api/auth/login` route has no rate limit, no failed-attempt audit event, and no soft lockout. A credential-stuffing attack would run unrestricted with no observability. This pass adds the rate limit + failed-attempt audit. The soft-lockout-with-column-add piece is deferred to Phase 39 (where `User.is_active` and `User.failed_login_count` land together).
- **B4** (review §2.7): the coarse `require_org_admin` / `require_org_moderator_or_admin` dependencies don't consult `role_transfers_to_sub_orgs` when the URL is sub-org-scoped and the user is a parent-org admin. The fine-grained `has_permission_on_sub_org` correctly does. Result: a parent-org admin whose transferability is disabled (Phase 15 feature) silently retains admin access on the sub-org via any route that gates via the coarse dependency. The fix tightens the coarse path to consult transferability.
- **B5** (review §3.6): `permissions.can_delegate_to` queries `DelegateProfile` without an `org_id` filter. A user can chain a delegation to a delegate who is public in org A while the delegation itself targets org B, provided the route's separate cycle check doesn't fire. The fix adds an `org_id` parameter and filters DelegateProfile by it.
- **B7** (Phase 37 D2 carry-forward): delete the legacy `if body.org_slug is None` branch in `/api/auth/demo-login` and the `DEMO_USERNAMES` constant. Phase 37 closeout + grep confirm the only FE caller (`Demo.jsx:61`) always passes `org_slug`, so the legacy branch is dead code. Closing it eliminates a whole class of "what other usernames in the list could be exploited" risk and reduces the auth surface area.

### Branch + merge

Branch: `phase-38/authorization-audit`. Merge with `--no-ff` to master per CLAUDE.md.

### Verification matrix

| Check | Required | Notes |
|---|---|---|
| Backend pytest (full, excl. 3 demo-reset suites) | ✅ | Target ~+18-25 tests across six clusters (B1-B5 + B7). Post-Phase-37 baseline is 1418 PASS / 27 pre-existing FAILED (same 27 from Phase 36 closeout — sample-verified on clean master). Target ~1436-1443 PASS, 27 pre-existing FAILED unchanged. |
| Backend pytest: targeted suites | ✅ | `pytest -k "auth or proposal_list or proposal_detail or proposal_results or websocket or org_middleware or sub_org or delegation"`. The five clusters touch enough overlapping surfaces that a focused re-run before the full sweep is high-signal. |
| Demo-reset suite | ✅ | Run separately. Confirm B1 + B5 don't break demo persona flows. |
| Phase 18 multi-tenancy regression suite | ✅ | `pytest backend/tests/test_phase_18_delegation_org_scoping.py` — B5's `can_delegate_to` change is the natural regression risk here. |
| Phase 15 sub-org permissions suite | ✅ | `pytest backend/tests/test_phase15_sub_org_permissions.py` — B4's transferability tightening is the natural regression risk here. |
| Phase 30.3 visibility consolidation suite | ✅ | `pytest backend/tests/test_phase_30_3_visibility_consolidation.py` — B1's eligibility-filter integration is the natural regression risk. |
| PG smoke | ❌ Not required | No migration. State explicitly in closeout. |
| Frontend build | ⚠ Conditional | Bundle hash should NOT change unless the WebSocket auth strategy chosen in B2 requires a frontend token-passing change (see B2 D2 below). If frontend touched, expect new bundle hash; otherwise pass is backend-only. |
| Backend deploy success verification | ✅ | Per CLAUDE.md backend-deploy hygiene. 13th consecutive clean auto-deploy expected. |
| Demo reset post-deploy | ✅ | Via `python scripts/trigger_demo_reset.py`. Confirm success + reasonable row counts. |
| API verify: B1 unscoped routes | ✅ | curl-test the three routes both authenticated and unauthenticated against prod after deploy. Expected: unauthenticated returns 401; authenticated as non-member returns empty list / 404; authenticated as member returns expected data. |
| API verify: B2 WebSocket | ✅ | Connect to the prod WS endpoint without auth → expect close-code per B2 design. Connect with valid auth on a proposal the user can view → expect tally_update messages flow normally. |
| API verify: B3 login rate limit | ✅ | Hit `/api/auth/login` with 11+ bad credentials from one IP in <1 minute → expect 429 on the 11th. Audit-log a `user.login_failed` event with the failing username on each bad attempt. |
| Browser verification (QA via Chrome MCP) | ✅ | At least three flows: normal user login + browse proposals (B1 end-to-end), live vote-tally update visible after vote-cast (B2 end-to-end), sub-org admin access for a parent-org admin under both transferability=on and transferability=off (B4 end-to-end). |
| File-count check | ✅ | `git diff master <branch> --stat`. |

### Suggested team structure

Per CLAUDE.md default team structure (Phase 19 onwards): **Lead + backend dev + frontend dev (conditional) + QA**.

- **Lead** in delegate mode. Coordinates B1-B5 sequencing, runs the API verify quartet, writes the closeout. If B6 (Phase 37 grep-driven) is in scope, lead owns sub-specing it.
- **Backend dev.** Owns B1 (unscoped proposal endpoints — the headline change), B2 (WebSocket auth), B3 (login rate limit + audit), B4 (sub-org tier transferability), B5 (`can_delegate_to` org scope), and all backend tests. Touches `backend/routes/proposals.py`, `backend/main.py`, `backend/routes/auth.py`, `backend/org_middleware.py`, `backend/permissions.py`, `backend/routes/delegations.py` (caller of B5).
- **Frontend dev (conditional).** Engaged only if B2's chosen design requires a frontend token-passing change (see B2 D2). If B2 ships with the query-param token shape, frontend dev wires up the WS connection URL to include the access token. If B2 ships with the first-message-handshake shape, frontend dev sends the handshake on socket open. Either way, the FE change is ~30 lines in one or two components — small.
- **QA teammate.** Browser-verifies the three load-bearing flows above via Claude in Chrome MCP after prod deploy + demo reset. Captures verification notes for the closeout.

If load warrants splitting, B1 and B2 are big enough each to merit their own backend dev (B1 is the highest-stakes — it's the headline gap), and B3-B5 can fold to a third backend dev. But the work is mechanical enough that one dev holding all five backend clusters is workable for a focused multi-day pass.

### Sequence

1. **B7** first (legacy demo-login branch deletion). Cleanest item — pure code deletion + test updates. Touching `routes/auth.py` first means subsequent B3 changes to the same file don't sit on top of dead code.
2. **B3** (login rate limit + audit). Small cluster, lowest-risk regression net. Same file as B7.
3. **B5** (`can_delegate_to` signature change). Self-contained, touches one helper + one or two callers. Good warm-up before the eligibility-filter work.
4. **B4** (sub-org tier transferability). Touches `org_middleware.py` — every route that gates via `require_org_*` consumes this, so the test sweep needs to be paranoid. Bigger blast radius than B5.
5. **B1** (unscoped proposal endpoints). The headline cluster. Three routes, requires using `_eligible_viewers_for_proposal`, requires deciding the list-endpoint filter strategy (per-proposal eligibility check vs. eligibility-aware query — see B1 D3).
6. **B2** (WebSocket auth). Last because it has the only frontend coordination question. Sequence after B1 so the WS handler can reuse the eligibility check pattern B1 establishes.
6. **T1** tests across all five clusters. Land as you go OR consolidate at end — implementer's call. Prefer interleaved (test alongside each cluster) for cognitive load reasons.
7. Targeted regression suites (Phase 15, 18, 30.3) + full pytest sweep.
8. Frontend build (if B2 chose query-param shape) + commit + merge + push.
9. Backend deploy verification + demo reset.
10. API verify quartet + QA browser verification.
11. Closeout report.

### Load-bearing decisions surfaced (full list in §"Locked decisions" below)

- **B1 unscoped proposal endpoints require auth.** No anonymous access. The Phase 14 public-org landing page uses `/api/orgs/{slug}/public` and `/api/orgs/{slug}/proposals` (the org-scoped routes), NOT the unscoped ones. Pre-flight grep confirms this (`OrgPublicLanding.jsx` line 64).
- **B1 list endpoint filters by user eligibility, not by org membership only.** Per-proposal eligibility uses `routes/comments._eligible_viewers_for_proposal` as the source of truth. This honors Phase 8.5 Decision 6 (parent admin sees sub-org) and Decision 7 (sub-org public visible to parent members) correctly. Implementer chooses the query strategy (eligibility-aware ORM query vs. per-proposal-membership-check in Python); both produce the same set.
- **B1 detail + results endpoints 404 (not 403) on eligibility failure.** Don't reveal proposal existence to non-members. Matches the Phase 19 / Phase 22 trajectory endpoint posture for the same reason.
- **B2 auth strategy: first-message handshake.** When a WS connects, accept the socket, then wait for a first message `{"auth": "<access_token>"}` with a 5-second timeout. If valid AND the user is in `_eligible_viewers_for_proposal`, the socket stays open. Otherwise, close with code 4401 (custom application close-code). This avoids URL-token leakage in browser history / proxy logs and matches the existing FastAPI WS idiom better than query-param tokens. (Alternative — query param — is documented in §B2 as a fallback if the handshake approach proves clunky to wire up.)
- **B3 login rate limit: `@limiter.limit("10/minute")`.** Same shape as the existing `/forgot-password` `3/hour`. Per-IP. The `slowapi` Limiter is already initialized at `routes/auth.py:63`.
- **B3 failed-attempt audit event: `user.login_failed`.** Details include `username` from the form data (NOT the User.id, since the user may not exist). IP captured per the existing audit pattern. No new audit-event-type registration needed — `audit_utils.log_audit_event` accepts arbitrary action strings.
- **B3 does NOT add soft lockout in this pass.** The reviewer suggested optional `User.failed_login_count` + `locked_until` columns. Those land in Phase 39 alongside `User.is_active` (the refresh-token state-check column) so all User-table identity column additions ship in one migration. Phase 38 is migration-free.
- **B4 transferability check at the coarse-tier dependency layer.** When `require_org_membership` returns a parent OrgMembership for a sub-org URL (the Phase 34.1 E4 fallback), the subsequent coarse-tier check in `require_org_moderator_or_admin` / `require_org_admin` consults `role_permissions.role_transfers_to_sub_orgs(parent_org, parent_mem.role.system_key)` before granting access. If transfer is disabled, the tier check returns 403 even though membership resolved.
- **B5 adds `org_id: Optional[str]` parameter to `can_delegate_to`.** Default None for backward compat with any test fixture caller; callers in `routes/delegations.py` pass the proposal's org_id (or the explicit org_id from the URL context). DelegateProfile lookup filters by `org_id` when non-None.
- **No migration; no schema change.** All five clusters are code-level.

### Operational watch-outs

- **B1 list endpoint performance.** Eligibility-check-per-proposal in Python is O(N × cost-of-eligibility-check). At pilot scale (3 demo orgs × ~15 proposals × ~30 members = manageable). At 10x scale, an eligibility-aware ORM query is preferable. Don't over-engineer in this pass — ship the simple per-proposal check, log a tech-debt item if perf shows up as a regression. The reviewer's §3.10 note about scheduler health surfaces is the natural place to add eligibility-check timing instrumentation later.
- **B1 affects the demo proposal list page.** Persona logins navigate to `/demo-cedar-hollow/proposals` (org-scoped) AND `/proposals` (legacy unscoped, called by `frontend/src/pages/Proposals.jsx:305`). The Proposals.jsx page is gated by `ProtectedRoute`, so all callers are authenticated — but the endpoint's response will now be filtered to user-eligible proposals only. For demo personas this should be a no-op (they're members of their demo org). Confirm via QA agent on at least one persona end-to-end.
- **B2 WebSocket protocol change.** Any existing frontend code that connects to `/ws/proposals/{id}` and expects messages to flow immediately needs the first-message-handshake change. Pre-flight grep `frontend/src` for `WebSocket\(.*ws/proposals` to identify the call sites. Likely one or two locations in `ProposalDetail.jsx`. If the FE doesn't pass an auth token on socket open, the socket will close after the 5-second timeout — visible as "live updates not working." Coordinate the FE + BE change in the same PR.
- **B3 rate limit per-IP not per-user.** A shared NAT or office gateway hitting the limiter from many users will trigger the throttle for everyone behind that IP. The `@limiter.limit("10/minute")` is appropriate for v1 / pilot; if real users hit it, the next refinement is a per-IP + per-username compound key. Don't pre-optimize.
- **B3 failed-attempt audit volume.** A credential-stuffing attack can generate thousands of `user.login_failed` rows per minute pre-throttle. The rate limit caps it at 10/min/IP, so worst-case volume is 600 rows/hour/attacking-IP. Acceptable at pilot scale; flag if it becomes a noise problem.
- **B4 affects every coarse-tier-gated sub-org URL.** The blast radius is wider than B5: every route that gates on `require_org_admin` or `require_org_moderator_or_admin` will silently change behavior for parent-org admins navigating to sub-org URLs under transferability-disabled orgs. Existing demo orgs leave transferability at default (per Phase 34); confirm no demo persona flow breaks via QA agent. Real-production orgs with explicit transferability=off settings are the case this fixes — if any pilot orgs exist with that setting, the lead pings Z to confirm the change matches their expected policy.
- **B5 changes a function signature.** Add the parameter as optional with `None` default to preserve existing test-fixture callers; the `routes/delegations.py` caller passes the org_id explicitly. If any test fails because it relied on the unfiltered cross-org match, that test is asserting incorrect behavior — fix the test, don't degrade the production semantic.
- **`_eligible_viewers_for_proposal` is in `routes/comments.py`.** That's an odd home for a helper now consumed by B1's proposal endpoints. Consider promoting it to `permissions.py` or a new `eligibility.py` module — but only if the move is mechanical (rename + import update). If the move would require restructuring imports across many files, defer to a separate cleanup pass and accept the import-from-routes oddity for this ship.
- **`role_transfers_to_sub_orgs` is in `role_permissions.py`** (per line 287 in that file per the grep). Import path is `from role_permissions import role_transfers_to_sub_orgs` — `org_middleware.py` will need this import.
- **WebSocket close codes.** FastAPI exposes `websocket.close(code=4401, reason="...")`. Custom codes in the 4000-4999 range are application-defined per the WebSocket protocol. Use 4401 (modeled on HTTP 401) for auth-required; 4403 for auth-OK-but-not-eligible; 4404 for nonexistent proposal ID. The frontend can read close codes and surface appropriate UX.
- **No new audit event types to register.** All `log_audit_event` calls in this pass use existing infrastructure. `user.login_failed` is a new action string but doesn't require schema-level registration. If the codebase has an `EVENT_REGISTRY` somewhere (Phase 31 mentions one in `notification_events.py`), check whether `user.login_failed` should be added there — likely no, since notification events are user-facing and login_failed is admin-only forensics.

### Closeout reports back

- Backend test count delta (post-Phase-37 baseline → ?).
- Frontend bundle delta (only if B2 required FE changes).
- Targeted suite results (Phase 15, 18, 30.3 + auth/proposal/websocket/org_middleware/delegation).
- Demo-reset suite results.
- File-count.
- Backend deploy verification.
- API verify quartet results (B1 / B2 / B3 / B4 — happy path + denial path per cluster).
- Browser verification results (B1 normal login, B2 live tally, B4 sub-org transferability under both settings).
- Branch state + commit list.
- Production deploy status (Railway URL, new bundle hash if FE touched, prod sanity).
- Any new tech debt found.
- **Confirmation that all 5 clusters (+ B6 / B7 if in scope) hold against their locked decisions; surface any deviations.**
- Pass-summary in PROGRESS.md style.

---

## Status block

The 2026-05-27 external review surfaced eight critical findings. Phase 37 closed four of them as one-line hotfixes (the demo-login admin priv-esc, the secret_key startup assert, the DelegateProfile visibility filter, and the `/api/admin/seed` auth gate). Phase 38 closes the remaining four critical findings — all of which are larger because they involve gating at routes the platform has been treating as "internal" but which are reachable across the public surface.

The unifying shape of all five clusters: each is a place where an existing eligibility helper or permission check should be consulted, but isn't. None require new permission model design; all require applying the existing model consistently. The work is heavy on read-the-surrounding-code-and-do-it-the-platform's-way and light on novel design.

The visibility model the platform implements (Phase 4c multi-tenancy + Phase 8.5 sub-orgs + Decisions 6/7 + Phase 18 follow/delegation org-scoping + Phase 30.3 per-topic visibility ladder) is intricate. The way the team has historically validated this model is via per-cluster regression suites — `test_phase_4c_multitenancy.py`, `test_phase_8_5_sub_orgs.py`, `test_phase_15_sub_org_permissions.py`, `test_phase_18_delegation_org_scoping.py`, `test_phase_30_3_visibility_consolidation.py`. Phase 38's verification matrix runs all of these because the changes intersect each one. A regression in any of these suites is the most likely signal that the implementation deviated from the locked decisions.

## Locked decisions

### B1 — Unscoped proposal endpoints (review §2.1)

- **D1 — All three routes require `current_user`.** `list_proposals` (line 618), `get_proposal` (line 840), `get_results` (line 1969) all gain `current_user: models.User = Depends(auth_utils.get_current_user)`. No anonymous read access on this surface. Public-org landing data flows through `/api/orgs/{slug}/public` (Phase 14), not through these routes.
- **D2 — Eligibility check via `_eligible_viewers_for_proposal`.** Defined in `backend/routes/comments.py:90`. Returns `set[str]` of eligible user IDs for a given proposal — honors Phase 8.5 Decision 3 (org-wide visible to all members), Decision 6 (parent admin implicit power on sub-orgs), Decision 7 (sub-org default visibility to parent members). For `get_proposal` and `get_results`: call the helper, check `current_user.id in viewers`, 404 if not (don't 403 — Phase 19 posture is to not reveal existence to non-eligible viewers).
- **D3 — List endpoint filter strategy: per-proposal eligibility (v1 shape).** The list endpoint iterates the candidate proposals (post-existing-filters: status, org_id, topic_id) and includes only those where the current user is in `_eligible_viewers_for_proposal(proposal)`. This is O(N × cost-of-eligibility-check) but pilot scale is small (~30 proposals per org × 3 demo orgs = ~90 proposals max). If profiling shows this as a bottleneck at scale, the natural optimization is an eligibility-aware ORM query — log as tech debt in the closeout, don't ship in this pass.
- **D4 — Platform admin bypass.** Per the existing pattern (`auth.py:67` docstring on `is_admin`), platform admins bypass eligibility checks and see everything. Apply consistently across B1's three routes — `if current_user.is_admin: return as-is` before invoking the eligibility filter.
- **D5 — Cache headers unchanged.** Phase 22's trajectory endpoint sets cache headers based on proposal status (immutable for closed, short max-age for voting). The proposals endpoints don't currently set cache headers; this pass does NOT add them. Out of scope.

### B2 — WebSocket auth (review §2.2)

- **D6 — First-message handshake auth.** When the WS connects, accept the socket, then wait for a first message expected to be JSON `{"auth": "<access_token>"}`. The handler has a 5-second timeout — if no message arrives or the message is malformed, close with code 4401. If the token doesn't decode to a valid User, close with code 4401. If the User is not in `_eligible_viewers_for_proposal(proposal)`, close with code 4403. If the `proposal_id` doesn't resolve to an existing Proposal row, close with code 4404 (this is the only case where the close happens before reading the first message — fail fast on bad IDs).
- **D7 — Proposal existence check happens at connect time, before the handshake wait.** Closing 4404 on connect for a bogus proposal_id avoids leaking "this proposal exists" via the timing of the handshake-then-close-4403 sequence.
- **D8 — Reuse the auth-utils JWT decode helpers.** `auth_utils.get_user_id_from_token` or whatever the existing decode primitive is; do not reimplement JWT validation in the WS handler.
- **D9 — Existing `ConnectionManager` API is unchanged.** `backend/websocket.py` keeps its current shape (`connect`, `disconnect`, `broadcast_tally`); the auth gating happens in the route handler before `ws_manager.connect(...)` runs. Broadcasts continue to fan out to all connected sockets; the gate is at connect time, not broadcast time.
- **D10 — Frontend coordination required.** The FE's WS-connection code in `ProposalDetail.jsx` (pre-flight grep to confirm exact location) must be updated to send the auth handshake message immediately after the socket opens. Token source: the existing `auth.access_token` in `AuthContext.jsx`.

### B3 — Login rate limit + failed-attempt audit (review §2.3)

- **D11 — Rate limit `10/minute` per IP via slowapi.** `@limiter.limit("10/minute")` decorator on `login` (`routes/auth.py:364`). Same pattern as `forgot-password` `3/hour` at `routes/auth.py:584`. The `limiter` instance is already initialized at line 63; no setup work.
- **D12 — Failed-attempt audit on the password-mismatch branch.** Add `log_audit_event(db, action="user.login_failed", target_type="user", target_id=user.id if user else None, actor_id=None, details={"username": form_data.username}, ip_address=request.client.host if request.client else None)` immediately before the `raise HTTPException(401)` at line 373. Two sub-cases: user-doesn't-exist (`target_id=None`) and user-exists-but-bad-password (`target_id=user.id`). Both log; both raise 401.
- **D13 — No soft lockout in this pass.** `User.failed_login_count` and `User.locked_until` columns are deferred to Phase 39, where they ship alongside `User.is_active` (the refresh-token state-check column) in one migration. Phase 38 is migration-free by design.
- **D14 — Rate limit applies to the legacy demo-login too.** Add the same `@limiter.limit("10/minute")` decorator to `/api/auth/demo-login` (`routes/auth.py:713ish`). The demo-login path is auth-equivalent (issues tokens) and should be rate-limited on the same principle.

### B4 — Sub-org tier check transferability (review §2.7)

- **D15 — Transferability check fires when membership resolved via the Phase 34.1 E4 fallback.** Specifically: in `require_org_moderator_or_admin` and `require_org_admin` (org_middleware.py:111 and :129), after `require_org_membership` returns a membership row, check whether the returned membership is for the parent of a sub-org URL (i.e., `org.parent_org_id is not None AND membership.org_id == org.parent_org_id`). If yes, consult `role_transfers_to_sub_orgs(org.parent_org_id_org, membership.role.system_key)`. If transfer is disabled, raise 403 instead of granting access.
- **D16 — `require_org_membership` itself is unchanged.** The Phase 34.1 E4 fallback returning a parent membership for sub-org-URL navigation stays — read access to public sub-org surfaces by parent-org members is the intended Phase 8.5 Decision 7 behavior. The tightening happens at the next gate up (moderator+/admin tier), not at the membership-existence gate.
- **D17 — Implementation shape: `_check_sub_org_transferability(membership, org)` helper.** Extract the "is this a parent-membership fallback into a sub-org?" + "does the role transfer?" check into a single helper called from both `require_org_moderator_or_admin` and `require_org_admin`. Avoid duplicating the logic in two places.
- **D18 — `require_org_owner` (the Steward gate at line 145) gets the same treatment.** Phase 15 transferability includes the Steward tier. Same helper, same call.
- **D19 — Audit-log on transferability denials.** When a parent-org admin gets denied at the sub-org tier check because of transferability, the existing 403 response is the user-facing signal. No new audit event needed — these denials are policy-driven, not security-incident-grade. Distinct from a permission failure on a sub-org member who simply lacks the role.

### B5 — `can_delegate_to` org scope (review §3.6)

- **D20 — Add `org_id: Optional[str]` parameter to `can_delegate_to`.** Signature becomes `can_delegate_to(db, delegator_id, delegate_id, topic_id, org_id=None)`. The DelegateProfile queries at lines 37 and 45 add `models.DelegateProfile.org_id == org_id` to their filter chains when `org_id` is non-None.
- **D21 — Caller in `routes/delegations.py` passes the org_id from URL context.** The route already has the org context (the URL prefix is org-scoped). Thread `org_id` through to the helper call. Grep for `can_delegate_to(` callers to identify all sites.
- **D22 — Test fixture callers may omit `org_id` (kwarg default None) — but those tests are asserting behavior that's currently incorrect.** When the test asserts cross-org delegation succeeds because of an unfiltered DelegateProfile match, that test is testing the bug, not the feature. Update the test to pass the explicit org_id and confirm the assertion still holds. If the test was the only thing keeping the unfiltered match alive, deleting it is the right move.
- **D23 — `permissions.delegation_denied_message` is unchanged.** The user-facing error message doesn't need to mention org scope — the caller's UX is already "this isn't a valid delegation target," which is true at any granularity.

## What this pass IS

- B1: auth + eligibility filters on three unscoped proposal endpoints in `routes/proposals.py`.
- B2: WebSocket connect-time auth via a first-message handshake in `main.py`'s `/ws/proposals/{id}` route.
- B3: `@limiter.limit("10/minute")` on `/api/auth/login` and `/api/auth/demo-login` + a `user.login_failed` audit event on the password-mismatch branch.
- B4: transferability check in `org_middleware.py`'s coarse tier dependencies.
- B5: `org_id` parameter on `permissions.can_delegate_to` + caller updates.
- B7: delete the legacy `org_slug=None` branch in `/api/auth/demo-login` + `DEMO_USERNAMES` constant + the now-obsolete Phase 37 test that exercised the legacy non-admin path (`test_b1_demo_login_non_admin_personas_still_work`).
- New tests in `backend/tests/test_phase_38_authorization_audit.py` covering all six clusters.
- One frontend touch (in `ProposalDetail.jsx` or wherever the WS connection lives) to send the auth handshake.

## What this pass is NOT

- **Not a User-table column add.** `User.is_active`, `User.failed_login_count`, `User.locked_until` are all deferred to Phase 39. Phase 38 is migration-free.
- **Not a refresh-token state-check fix** (review §3.3). Phase 39.
- **Not a `forgot-password` timing fix** (review §3.4). Phase 39.
- **Not the demo-reset DB-level lock** (review §3.2). Phase 40.
- **Not Pillow decompression-bomb defense** (review §3.8). Phase 40.
- **Not a scheduler health endpoint** (review §3.10). Phase 40.
- **Not the in-memory graph_store rearchitecture or WORKERS=1 assert** (review §3.1). Phase 40.
- **Not a refactor of `_eligible_viewers_for_proposal` out of `routes/comments.py`.** Promoting it to `permissions.py` is good housekeeping but not in this pass — track as tech debt.
- **Not a public-org proposal read surface.** If any pilot org reports needing anonymous browsing of proposals, that's a follow-up `public-proposal-read` design pass, not a quiet relaxation of B1's auth requirement.
- **Not a cross-org delegation visibility audit beyond `can_delegate_to`.** The review's §6 uncertain item about `_build_context` and cross-sub-org delegation chains is explicitly out of scope; flag as a followup eligible for the next external review pass.

## Cluster B — Backend

### B1 — Unscoped proposal endpoints

**Files:** `backend/routes/proposals.py`.

**B1.1 — `list_proposals` (line 618):**

```python
@router.get("", response_model=list[schemas.ProposalOut])
def list_proposals(
    status_filter: Optional[str] = Query(None, alias="status"),
    topic_id: Optional[str] = Query(None),
    org_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),  # NEW
):
    q = db.query(models.Proposal)
    if org_id:
        q = q.filter(models.Proposal.org_id == org_id)
    if status_filter:
        q = q.filter(models.Proposal.status == status_filter)
    if topic_id:
        q = q.join(models.ProposalTopic).filter(models.ProposalTopic.topic_id == topic_id)
    proposals = q.order_by(*_proposal_list_ordering()).all()

    # Phase 38 B1 D3 — eligibility filter. Platform admin bypasses (D4).
    if not current_user.is_admin:
        from routes.comments import _eligible_viewers_for_proposal
        proposals = [
            p for p in proposals
            if current_user.id in _eligible_viewers_for_proposal(db, p)
        ]

    return [_build_proposal_out(p, db) for p in proposals]
```

**B1.2 — `get_proposal` (line 840):**

```python
@router.get("/{proposal_id}", response_model=schemas.ProposalOut)
def get_proposal(
    proposal_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),  # NEW
):
    proposal = _proposal_or_404(proposal_id, db)
    # Phase 38 B1 D2/D4 — eligibility check.
    if not current_user.is_admin:
        from routes.comments import _eligible_viewers_for_proposal
        if current_user.id not in _eligible_viewers_for_proposal(db, proposal):
            raise HTTPException(status_code=404, detail="Proposal not found")
    return _build_proposal_out(proposal, db)
```

**B1.3 — `get_results` (line 1969):** same shape as B1.2 — add `current_user` dep + eligibility check + 404 on fail.

**Eligibility helper import:** the cleanest shape is a one-shot import at top-of-function rather than a top-of-file import, because `routes/comments.py` may import from `routes/proposals.py` and the team has hit circular-import issues before (per various phase notes). Confirm by checking the import direction; if no cycle, top-of-file import is cleaner.

### B2 — WebSocket auth

**Files:** `backend/main.py` (line 269), possibly `backend/websocket.py`.

**Reference shape:**

```python
import asyncio
import json
from fastapi import WebSocketDisconnect, WebSocketException

@app.websocket("/ws/proposals/{proposal_id}")
async def proposal_websocket(websocket: WebSocket, proposal_id: str):
    from database import SessionLocal
    db = SessionLocal()
    try:
        # D7 — proposal existence check before accepting the socket.
        proposal = db.query(models.Proposal).filter(
            models.Proposal.id == proposal_id,
        ).first()
        if proposal is None:
            await websocket.close(code=4404, reason="proposal not found")
            return

        await websocket.accept()

        # D6 — first-message handshake with 5-second timeout.
        try:
            handshake_raw = await asyncio.wait_for(
                websocket.receive_text(), timeout=5.0,
            )
        except asyncio.TimeoutError:
            await websocket.close(code=4401, reason="auth timeout")
            return

        try:
            handshake = json.loads(handshake_raw)
            token = handshake.get("auth")
        except (json.JSONDecodeError, AttributeError):
            await websocket.close(code=4401, reason="malformed handshake")
            return

        if not token:
            await websocket.close(code=4401, reason="missing token")
            return

        # D8 — reuse existing JWT decode.
        try:
            user_id = auth_utils.get_user_id_from_token(token)
        except Exception:
            await websocket.close(code=4401, reason="invalid token")
            return

        user = db.query(models.User).filter(models.User.id == user_id).first()
        if user is None:
            await websocket.close(code=4401, reason="user not found")
            return

        # D6 — eligibility check.
        if not user.is_admin:
            from routes.comments import _eligible_viewers_for_proposal
            if user.id not in _eligible_viewers_for_proposal(db, proposal):
                await websocket.close(code=4403, reason="not eligible")
                return

        # Auth passed — register with the manager and start the recv loop.
        await ws_manager.connect(proposal_id, websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            ws_manager.disconnect(proposal_id, websocket)
    finally:
        db.close()
```

The exact JWT decode helper name (`get_user_id_from_token` vs. some other identifier) needs to be confirmed against `backend/auth_utils.py` — adjust to match the existing convention.

**`ConnectionManager.connect` change:** the existing `connect` method calls `await websocket.accept()` itself (`backend/websocket.py:30`). Since the route handler now accepts before the handshake, the manager's `connect` should skip the accept call OR a new `register` method on the manager replaces it. Minimal change: rename the existing `connect` to `register` (no accept call) and update the route to call `await websocket.accept()` itself before the handshake. Audit existing `connect` callers and update the names.

**Frontend coordination:** pre-flight grep `frontend/src` for `WebSocket\(.*ws/proposals` to find the connection site. Wire the handshake send:

```javascript
const ws = new WebSocket(`wss://api.liquiddemocracy.us/ws/proposals/${proposalId}`);
ws.onopen = () => {
  ws.send(JSON.stringify({ auth: auth.access_token }));
};
ws.onclose = (event) => {
  // Surface auth failure UX based on close code if needed.
};
```

### B3 — Login rate limit + failed-attempt audit

**Files:** `backend/routes/auth.py`.

**B3.1 — Rate limit decorator on `login` (line 364):**

```python
@router.post("/login", response_model=schemas.TokenResponse)
@limiter.limit("10/minute")  # NEW
def login(
    request: Request,
    ...
):
```

The `Request` parameter is already present (used for `client.host`). slowapi pulls the request from the parameter — no additional wiring needed.

**B3.2 — Same decorator on `demo_login` (line ~713):** `@limiter.limit("10/minute")`. Same shape.

**B3.3 — Failed-attempt audit on the 401 branch (line 372):**

```python
user = db.query(models.User).filter(models.User.username == form_data.username).first()
if not user or not auth_utils.verify_password(form_data.password, user.password_hash):
    # Phase 38 B3 D12 — failed-attempt audit. Captures both "no such user"
    # and "user exists but bad password" cases. target_id distinguishes them.
    log_audit_event(
        db,
        action="user.login_failed",
        target_type="user",
        target_id=user.id if user else None,
        actor_id=None,
        details={"username": form_data.username},
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid username or password",
    )
```

Note the `db.commit()` — the existing 401 path doesn't commit, but with the audit add, the audit row needs to persist before the raise. Confirm against existing audit-write patterns elsewhere; alternative is to push the commit into the audit utility if it does its own session management.

### B4 — Sub-org tier check transferability

**Files:** `backend/org_middleware.py`.

**B4.1 — Helper `_check_sub_org_transferability` (D17):**

```python
def _check_sub_org_transferability(
    membership: OrgMembership,
    org: Organization,
    db: Session,
) -> None:
    """Raise 403 if `membership` is a parent-org-membership-via-Phase-34.1-E4-fallback
    on a sub-org URL and the parent's role doesn't transfer to sub-orgs.

    No-op when:
      - `org` is not a sub-org (no `parent_org_id`).
      - `membership.org_id == org.id` (membership is on the sub-org itself).
      - Transferability is enabled for the role (the default).
    """
    if org.parent_org_id is None:
        return
    if membership.org_id == org.id:
        return  # direct sub-org membership, not the parent fallback
    if membership.org_id != org.parent_org_id:
        return  # defensive; shouldn't happen
    parent_org = db.get(Organization, org.parent_org_id)
    if parent_org is None:
        return  # defensive
    from role_permissions import role_transfers_to_sub_orgs
    role_system_key = membership_role_system_key(membership)
    if role_system_key is None:
        return
    if not role_transfers_to_sub_orgs(parent_org, role_system_key):
        raise HTTPException(
            status_code=403,
            detail="Your role does not transfer to sub-organizations.",
        )
```

**B4.2 — Wire the helper into `require_org_moderator_or_admin`, `require_org_admin`, `require_org_owner`:**

```python
async def require_org_moderator_or_admin(
    org: Organization = Depends(get_org_context),
    membership: OrgMembership = Depends(require_org_membership),
    db: Session = Depends(get_db),
):
    if membership_role_system_key(membership) not in _MODERATOR_TIER_SYSTEM_KEYS:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to perform this action in this organization.",
        )
    _check_sub_org_transferability(membership, org, db)  # Phase 38 B4
    return membership
```

Same shape for `require_org_admin` and `require_org_owner`. Each gets `org` and `db` deps added.

### B5 — `can_delegate_to` org scope

**Files:** `backend/permissions.py`, `backend/routes/delegations.py` (and any other callers — grep for `can_delegate_to(` to find them).

**B5.1 — Signature + filters:**

```python
def can_delegate_to(
    db: Session,
    delegator_id: str,
    delegate_id: str,
    topic_id: Optional[str],
    org_id: Optional[str] = None,  # NEW — Phase 38 B5 D20
) -> bool:
    if topic_id is not None:
        q = db.query(models.DelegateProfile).filter(
            models.DelegateProfile.user_id == delegate_id,
            models.DelegateProfile.topic_id == topic_id,
            models.DelegateProfile.visibility.in_(("public", "public_accepting")),  # ride-along Phase 37 B3 pattern
        )
        if org_id is not None:
            q = q.filter(models.DelegateProfile.org_id == org_id)
        if q.first():
            return True
    else:
        q = db.query(models.DelegateProfile).filter(
            models.DelegateProfile.user_id == delegate_id,
            models.DelegateProfile.visibility.in_(("public", "public_accepting")),
        )
        if org_id is not None:
            q = q.filter(models.DelegateProfile.org_id == org_id)
        if q.first():
            return True

    # Follow-based path is org-scoped on the FollowRelationship side post-Phase-18.
    rel_q = db.query(models.FollowRelationship).filter(
        models.FollowRelationship.follower_id == delegator_id,
        models.FollowRelationship.followed_id == delegate_id,
        models.FollowRelationship.permission_level == "delegation_allowed",
    )
    if org_id is not None:
        rel_q = rel_q.filter(models.FollowRelationship.org_id == org_id)
    return rel_q.first() is not None
```

Note the visibility filter add is a Phase 37 B3 carry-through — Phase 37 added it to `delegation_tree` and `vote-graph` but `can_delegate_to` is a third site with the same shape. Bundling here keeps the visibility predicate consistent across all three consumers.

**B5.2 — Caller updates in `routes/delegations.py`:** at every `can_delegate_to(...)` call site, thread the org_id through. Grep for all sites; pre-Phase-18 callers may not have org context handy, in which case lift it from the URL path or the delegation's target topic.

### B7 — Delete legacy demo-login branch

**Files:** `backend/routes/auth.py`.

Phase 37 D2 preserved the legacy `if body.org_slug is None` branch pending FE confirmation. Phase 37 closeout + grep confirm `Demo.jsx:61` is the only FE caller and always passes `org_slug`. The legacy branch is dead code.

**B7.1 — Delete the legacy branch.** Remove the entire `# ---- Legacy path: hardcoded DEMO_USERNAMES + DEMO_ORG_SLUG ----` block from `routes/auth.py` (post-Phase-37, lines roughly 788-817; line numbers may have drifted after the Phase 37 commit — locate by the comment marker, not the line number). The block ends just before the next route definition. Everything from that comment through the final `return {"access_token": ..., "refresh_token": ...}` of the legacy path is removed.

**B7.2 — Delete the `DEMO_USERNAMES` constant.** Post-Phase-37 it is `["alice", "dr_chen", "carol", "dave", "frank", "voter02"]`. After B7.1, no code references it. Remove the constant declaration at line 65 + its surrounding comment block (the Phase 8.5 voter02 commentary block).

**B7.3 — Restructure the route body.** With the legacy branch gone, the `if body.org_slug is not None:` guard at the top of the per-org B7 path becomes a load-bearing requirement, not a branch. Convert it to an explicit validation: if `body.org_slug is None`, raise `HTTPException(status_code=400, detail="org_slug is required")`. This makes the contract explicit and surfaces stale frontend callers loudly rather than silently.

**B7.4 — Remove the now-obsolete Phase 37 test.** `test_phase_37_security_hotfix.py::test_b1_demo_login_non_admin_personas_still_work` (asserting the legacy alice-without-org_slug path returns 200) becomes obsolete with B7. Either delete the test or update it to assert the new 400 "org_slug is required" response. Prefer deletion — the per-org demo-login tests in `test_phase_23_demo_metadata.py` (or wherever the B7 path's coverage lives) already cover the live path.

**B7.5 — Audit other tests that may hit the legacy path.** Pre-flight grep `backend/tests` for `demo-login` calls without `org_slug` in the body. Any hits get updated to pass `org_slug` (preferred) or removed (if they were testing the legacy path specifically).

**Note:** B7 must land BEFORE B3 in the file edit order. B3 adds the `@limiter.limit` decorator to the demo-login route; doing that before B7 means the limiter decorator wraps a route that's about to be restructured, which is a wasted edit. Per the Sequence section, B7 is item 1 and B3 is item 2.

## Cluster T — Tests

**New file:** `backend/tests/test_phase_38_authorization_audit.py`. Required test coverage (15-20 tests):

**B1 tests (5-6):**
- `test_b1_list_proposals_requires_auth` — unauthenticated GET returns 401.
- `test_b1_list_proposals_filters_to_user_eligible` — authenticated as user-in-org-A, GET returns only org-A proposals; not org-B proposals.
- `test_b1_list_proposals_admin_bypasses_filter` — authenticated as platform admin, GET returns everything.
- `test_b1_get_proposal_404_for_non_eligible_user` — non-member of the proposal's org gets 404 (not 403).
- `test_b1_get_results_404_for_non_eligible_user` — same shape for results endpoint.
- `test_b1_sub_org_private_proposal_hidden_from_non_parent_admin_parent_member` — Decision 7 + private flag: parent-org member who isn't a sub-org member can't see a private-sub-org proposal via the unscoped endpoint.

**B2 tests (3-4):**
- `test_b2_websocket_closes_on_missing_handshake` — connect, don't send anything, expect close code 4401 after 5s.
- `test_b2_websocket_closes_on_invalid_token` — connect, send `{"auth":"garbage"}`, expect close 4401.
- `test_b2_websocket_closes_on_non_eligible_user` — connect with valid token of a non-member, expect close 4403.
- `test_b2_websocket_closes_on_nonexistent_proposal` — connect to `/ws/proposals/does-not-exist`, expect close 4404 before any handshake.

**B3 tests (3-4):**
- `test_b3_login_rate_limit_triggers_after_10_in_a_minute` — 11 bad logins from one IP, 11th returns 429.
- `test_b3_login_failed_audits_with_bad_password` — POST with valid username + wrong password; assert `user.login_failed` audit row exists with the username + IP.
- `test_b3_login_failed_audits_with_unknown_username` — POST with non-existent username; assert audit row exists with `target_id=None`.
- `test_b3_demo_login_rate_limit_triggers` — same shape as #1 for `/api/auth/demo-login`.

**B4 tests (3-4):**
- `test_b4_parent_admin_with_transferability_enabled_passes_sub_org_admin_gate` — default org settings; parent admin reaches a sub-org admin-gated route.
- `test_b4_parent_admin_with_transferability_disabled_fails_sub_org_admin_gate` — org with explicit `sub_org_role_transferability.admin=False`; parent admin gets 403 on the same route.
- `test_b4_sub_org_member_with_admin_role_unaffected_by_transferability` — direct sub-org admin gets through regardless of transferability setting (the gate only affects parent-fallback case).
- `test_b4_steward_transferability_check` — same shape as #1/#2 for `require_org_owner`.

**B5 tests (3):**
- `test_b5_can_delegate_to_with_explicit_org_id_filters_cross_org_profile` — delegate has DelegateProfile in org A; can_delegate_to(..., org_id="org_b") returns False even though the global profile exists.
- `test_b5_can_delegate_to_with_none_org_id_preserves_legacy_behavior` — without org_id, the function behaves as pre-Phase-38 (regression net).
- `test_b5_can_delegate_to_filters_follow_relationship_by_org_id` — when org_id is provided, follow-based path is also org-scoped.

**B7 tests (2-3):**
- `test_b7_demo_login_requires_org_slug` — POST `/api/auth/demo-login` with `{"username": "alice"}` (no `org_slug`) returns 400 with the explicit error message.
- `test_b7_demo_login_with_org_slug_still_works` — POST with both `username` and `org_slug` against a valid demo org + persona returns 200 + tokens. Regression net.
- `test_b7_demo_usernames_constant_removed` — import-time assertion: `DEMO_USERNAMES` is not defined in `routes/auth.py`'s namespace. Cheap regression net against a future contributor adding the constant back without realizing it's load-bearing.

## Operational sequencing

Standard CLAUDE.md flow. Notable points:

- **No `SECRET_KEY` rotation this pass.** That was a Phase 37 belt-and-suspenders move; not needed for ordinary code changes.
- **Demo reset post-deploy is required** because B1 changes the proposal list shape for every demo persona. Confirm at least one persona's `/proposals` page renders correctly post-deploy.
- **No audit-log grep.** The Phase 37 grep was forensic-evidence-driven; nothing in this pass needs a similar after-the-fact lookup.
- **Frontend deploy timing:** if B2 chose query-param tokens (the fallback option), the FE change is small enough to ship in the same merge. If B2 chose the first-message handshake (D6 default), still the same merge — the FE change is ~10 lines.

## Followups (out of scope)

Documented for Phase 39+ planning:

- **Phase 39 — Identity hardening:** `User.is_active` column add + refresh-token state-check (review §3.3), `forgot-password` background email (review §3.4), optional `User.failed_login_count` + soft lockout. One migration; PG smoke required.
- **Phase 40 — Ops + multi-instance prep:** demo-reset DB-level lock (review §3.2), Pillow decompression-bomb defense (review §3.8), scheduler health endpoint (review §3.10), `WORKERS=1` startup assert (review §3.1), §4 minor items batched.
- **Promote `_eligible_viewers_for_proposal` out of `routes/comments.py`** into `permissions.py` or a dedicated `eligibility.py` module. Mechanical refactor; do as part of a future general cleanup pass.
- **List-endpoint eligibility-aware ORM query.** Replace B1 D3's per-proposal Python check with a query that filters at the DB layer. Profile-driven; defer until perf data warrants.
- **WebSocket cross-worker broadcast.** Today's `ConnectionManager` is per-process. Multi-worker scaling needs a Redis pub/sub or similar fan-out. Not load-bearing at v1; flag for the eventual `WORKERS>1` decision.
- **Cross-sub-org delegation chain audit.** Review §6 uncertain item about `_build_context` cross-scope leak. Worth a dedicated read-pass once Phase 38 lands — probably folds into a future external review request.
