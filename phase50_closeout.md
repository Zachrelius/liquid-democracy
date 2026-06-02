# Phase 50 — Leave Organization — Closeout

**Spec:** `phase50_leave_org_spec.md`
**Branch:** `phase-50/leave-org` → merged `--no-ff` to master
**Date:** 2026-06-02

---

## Overall

**SHIPPED.** Self-service leave-org closes the most user-visible remaining gap (there was no path for an active member to exit an org). Pure reuse pass — builds on Phase 45a/45b governance floor + Phase 47 title-revoke + the audit infrastructure. No new transfer mechanics, no new governance logic, no migration.

The pass also surfaces a reusable `org_leave.leave_org(db, org, user, ...)` callable that a future account-deletion path can loop across the user's orgs (forward-dep noted in the spec).

---

## Per-cluster status

| Cluster | Status | Notes |
|---|---|---|
| B1 — Core leave function + HTTP endpoint | DONE | `backend/org_leave.py` exposes `leave_org(db, org, user, ...) -> dict` and a structured `TransferRequired` exception. Single arbiter: `governance.count_active_governors(exclude_user_id=user.id)` — the same primitive `remove_member` uses; no divergent floor logic. POST `/api/orgs/{org_slug}/leave` wraps the function; 409 with `{"error": "transfer_required", "mode": "single_steward" \| "admin_council", "detail": "..."}` for the sole-governor case so the FE can render the inline transfer-first step. |
| B2 — Title cleanup on leave | DONE | Custom (`is_system=False`) `OrgTitleAssignment` rows for the leaver are deleted BEFORE the membership delete. Each deletion emits a `title.revoked` audit event with `trigger='member_left'` per spec. System titles (Steward / Admin) are role-derived and clear when the membership/role goes — the floor check above guarantees this is floor-safe (the leaver can't be the sole governor by the time we reach the title-revoke loop). |
| B3 — Delegation cleanup + investigation finding | DONE | **Investigation finding**: the tally engine already tolerates a departed delegate. `delegation_engine.eligible_voter_ids_for_proposal` filters delegates by active `OrgMembership`, and the eligibility set is propagated into `_build_context` (Phase 10.1) so a departed delegate's ballot doesn't leak through chain resolution. **Implementation decision**: clean only the leaver's outgoing `Delegation` + `DelegationIntent` rows scoped to the org; leave incoming delegations alone (they resolve naturally to no-vote at tally time). The `TestDelegationCleanupOnLeave::test_incoming_delegations_NOT_deleted_but_engine_tolerates` test asserts the row IS still there post-leave, documenting the behavior. |
| B4 — Transfer-first via existing endpoints | DONE | The leave endpoint stays a clean floor-gated membership delete; the "walk-through" is FE orchestration: when 409 surfaces, the Leave UI swaps to an inline picker that calls the existing `POST /transfer-stewardship` endpoint (no new transfer mechanics), then re-enables Leave. The user clicks Leave AGAIN deliberately to complete (the spec's D2 "two steps, not atomic" anchor). |
| B5 — Tests | DONE | `test_phase_50_leave_org.py` (10 tests, 10/10 PASS) covering: ordinary member leaves immediately; sole-steward blocked with `transfer_required`; transfer-then-leave succeeds (D2); last admin in council mode blocked; custom title revoked + audit emitted; outgoing delegations deleted; incoming delegations NOT deleted (engine tolerance documented); `org.left` audit with actor=leaver; reusable per-org callable (`leave_org` invoked directly without HTTP); leave-not-approval-gated even when `multi_admin_approval` is enabled (assert no pending action created). |
| F1 — Leave button + informed confirm | DONE | "Leave organization" section in `OrgSettings.jsx`, visible to any active member (not admin-only). The confirm dialog names what's lost: membership, held titles, org-scoped delegations made + the incoming-delegations-resolve-naturally note. No Phase 44 gate (D5). |
| F2 — Inline transfer-first flow | DONE | When the leave POST returns 409 `transfer_required`, the UI state machine flips to `transfer_required` mode: an inline member picker calls the existing `/transfer-stewardship` endpoint, then transitions back to `confirm` mode so the user clicks Leave again to complete (D2). Copy on the transfer dialog notes the successor is interim, subject to the org's normal election / handoff processes (D4). |

---

## Verification matrix

| Check | Required | Result |
|---|---|---|
| Backend pytest (Phase 50 + every adjacent) | Yes | **213/213 PASS in 176s** across Phase 50 (10), Phase 49b (10), Phase 49a (20), Phase 49 (14), Phase 48 stages (36), Phase 47 (16), Phase 46 + 46a (20), Phase 45a/45b (19), Phase 44 (28). |
| Floor reuse (D1) | Yes | **PASS** — `leave_org` calls `count_active_governors(db, org, exclude_user_id=user.id)`. Sole-steward + last-admin tests assert the gate behaves identically to `remove_member` (block + structured payload, no membership delete). Non-governor + non-last-governor tests proceed. |
| Transfer-first then leave (D2) | Yes | **PASS** — `TestSoleStewardBlockedThenTransferThenLeave::test_transfer_then_leave_succeeds` exercises the two distinct operations: first call to `/transfer-stewardship` (200), then call to `/leave` (200, formerly 409). The two steps are not fused. |
| Title cleanup (D3) | Yes | **PASS** — `TestTitleCleanupOnLeave::test_custom_title_revoked_on_leave` asserts the `OrgTitleAssignment` row is GONE post-leave + a `title.revoked` audit entry with `trigger='member_left'` exists. The floor check guards bound-role-title-on-sole-governor (those paths are gated at D1 before the title-revoke runs). |
| Delegation cleanup (B3) | Yes | **PASS** — outgoing delegations deleted (asserted); incoming delegations NOT deleted (asserted, with the engine-tolerance documentation in the test docstring). The eligibility filter handles the case naturally at tally time. |
| Informed confirm, not approval-gated (D5) | Yes | **PASS** — `TestLeaveIsNotApprovalGated::test_leave_with_approval_enabled_still_executes_directly` enables `multi_admin_approval` on the org, calls `/leave`, asserts 200 + the member is gone + ZERO pending actions exist for the org. Leave is unilateral by construction. |
| `org.left` audit | Yes | **PASS** — `TestAuditOrgLeftEmitted` asserts the `org.left` audit entry exists with `actor_id=leaver`. |
| Reusable-per-org leave logic | Yes | **PASS** — `TestReusableLeaveLogic::test_leave_org_callable_directly` invokes `leave_org` as a function (not via HTTP) and asserts the same end-state. The future account-deletion path can loop this. |
| No migration | Yes | **No Alembic revision.** Reuses `OrgMembership`, `OrgTitleAssignment`, `Delegation`, `DelegationIntent`, `AuditLog`. |
| `bash start.sh` prod-like env | N/A | Pass doesn't touch the worker / digest tick. Boot-mimic confirmed digest_loop + run_one_tick complete cleanly with no new tick steps. |
| Frontend build + bundle hash | Yes | **PASS** — new bundle `index-Wn-jh8Vj.js`. |
| Browser verification (Chrome MCP, prod) | Yes | **TBD** — recommend dispatching the QA sub-agent post-deploy to walk: (1) ordinary member leaves cleanly + redirects to /orgs; (2) sole-steward hits the 409 → inline transfer picker → transfer → re-click Leave → completes; (3) member holding a custom title leaves → title gone from their name on the next page they visit; (4) confirm dialog wording names what's lost. |

---

## Branch + commit state

- Branch: `phase-50/leave-org`
- Commit on branch: `319f097`
- Merge commit on master: `f378d6f` (no-ff)
- Pushed to origin/master: confirmed
- Railway deploy: TBD (currently BUILDING `ddbf19ae`)
- Bundle hash: `index-Wn-jh8Vj.js` (verified post-build)

---

## Forward dependency — account deletion (not in scope, noted)

Account deletion = "leave every org the user belongs to, each subject to this same floor check + transfer-first gate." `org_leave.leave_org` is structured as a reusable per-org function precisely so the future account-deletion path can loop it. A sole-steward-of-3-orgs cannot delete their account without handing off all three first — the spec's "vanish vector" check. **Backlog item**: account-deletion endpoint that loops `leave_org` across the user's active orgs + handles the user-row delete after every membership is gone.

---

## Tech debt / followups

- **Login / sub-org leave**: the Leave button currently lives in OrgSettings.jsx which is admin-flavored. A future polish could surface it on the org switcher / a member-facing surface so non-admins find it more easily. Not blocking — the spec's verification matrix only asks for it being available.
- **Sub-org leave**: `org_leave.leave_org` operates on a parent org. A user who is also a member of a sub-org under that parent should have their `SubOrgMembership` row cleaned up too. **Backlog item** — verify the existing wipe / membership-delete paths handle this correctly; if not, extend `leave_org` to clean sub-org memberships as well.
- **Toast vs. dialog UX**: the FE leave flow uses toasts for feedback; a future polish could use a dedicated confirmation modal (matching the existing `confirm()` pattern used by transfer-stewardship). Not blocking.
