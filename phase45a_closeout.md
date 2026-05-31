# Phase 45a — Steward Recovery + Voluntary Handoff — Closeout

**Spec:** `phase45a_steward_recovery_handoff_spec.md`
**Branch:** `phase-45a/steward-recovery-handoff` → merged `--no-ff` to master (pending push)
**Deployed:** Railway prod, bundle `index-BARSNmNc.js` (pending push)
**Date:** 2026-05-31

---

## Per-cluster status

| Cluster | Status | Notes |
|---|---|---|
| B1 — Relax steward-removal guard for inactive stewards | DONE | The `system_key == "steward"` guard in `routes/organizations.py::remove_member` + `pending_actions/registry.py::_validate_member_remove` + `execute_member_remove` now keys off `User.is_active`. Active stewards remain unconditionally protected; inactive stewards become removable as a recovery action. Audit event `steward.removed_while_inactive` emitted on every recovery path (direct + Phase 44 ratified). |
| B2 — Successor requirement on inactive-steward removal | DONE | Removal of the sole steward requires `successor_user_id` in the request body / pending-action payload. The successor must be an active member of the org, must not equal the target, and must have an active User account. Atomic transaction: the successor's `OrgMembership.role_id` is promoted to the Steward role in the same DB unit-of-work as the prior steward's row deletion, so the org never observes a zero-steward state on the default path. Defensive: if another active steward already exists (not possible on the default path today, but the guard is unconditional), the successor requirement is waived per D3. |
| B3 — Implement `org.transfer_stewardship` | DONE | New endpoint `POST /api/orgs/{slug}/transfer-stewardship` (body `{target_user_id}`), gated on `require_org_owner` which is itself the consumer of the existing `org.transfer_stewardship` OWNER_ONLY_KEY (declared since Phase 12 with no consuming route until now). Atomic swap per D1: outgoing steward → admin, target → steward. Rejects: non-active member targets, inactive targets, self. Audit `org.stewardship_transferred`. |
| B4 — Phase 44 integration | DONE | `member.remove` payload-validator + executor extended to carry `successor_user_id`; the field round-trips through `PendingAdminAction.payload` and is re-validated at execute time via the engine's D7 revalidation hook. No registry-shape changes — extension was additive. Preview builder also extended to surface "and promote X to Steward" in the ratify UI. |
| B5 — Tests | DONE | `test_phase_45a_steward_recovery_handoff.py` (19 tests) covering: active-steward regression × 3 (cannot be removed / role-changed / suspended), inactive-steward removal blocked without successor, removable with successor + atomic promotion, can promote a Member as successor, audit event emitted, non-active successor rejected, self-as-successor rejected, transfer happy path (atomic swap), transfer audit emitted, admin-cannot-initiate, non-member / inactive / self target rejected, Phase 44 ratification path defers + carries successor through to ratified execution, Phase 44 path still blocks active-steward removal at submit, invariant after transfer, invariant after recovery removal. **19/19 PASS** locally. |
| F1 — Un-hardcode delete-org gating | DONE | `OrgSettings.jsx:199` `currentOrg?.user_role === 'steward'` swapped for `useHasPermission('org.delete')`. Functionally identical today (OWNER_ONLY_KEYS still resolves the permission only for Stewards); the change tracks Phase 12.5/12.6 convention and stays correct under any future relaxation of `org.delete`. Recon GAP-5 closed. |
| F2 — Transfer-stewardship UI | DONE | New "Stewardship" section in `OrgSettings.jsx` (above Danger Zone), gated on `useHasPermission('org.transfer_stewardship')`. Member picker reads `/api/orgs/{slug}/members`, filters to active non-steward members. Confirmation dialog (destructive) before submit. On success: toast + `refreshOrgs()` so the caller's `user_role` flips to admin immediately. |

---

## Verification matrix

| Check | Required | Result |
|---|---|---|
| Backend pytest (full) | Yes | TBD — running |
| New behavior tests (B5) | Yes | **19/19 PASS** locally; isolated sweep clean. Side-effect assertions in every test (actual role rows after swap; actual membership deletion + successor promotion; audit log entries). |
| No migration | Yes | **Confirmed** — no Alembic revision added. The guards key off existing `User.is_active` + `Role.system_key` + the existing `OrgMembership.role_id`. No schema change required. |
| Active-steward regression | Yes | PASS — three tests (`test_active_steward_cannot_be_removed_via_direct_path`, `_role_changed`, `_suspended`) explicitly assert active stewards remain unconditionally protected via every mutating endpoint. |
| At-least-one-steward invariant | Yes | PASS — explicit assertions after transfer + recovery removal, plus the embedded counts in 6 other tests. Default-path invariant holds: every mutating path exits with exactly one active steward. |
| Phase 44 path (D2/B4) | Yes | PASS — `test_inactive_steward_removal_defers_when_approval_enabled` asserts: (a) endpoint returns `submitted_for_approval`, (b) `pending.payload["successor_user_id"]` matches what the FE sent, (c) ratification by the second admin executes the actual removal AND the successor promotion, (d) invariant still holds. The active-steward block also fires at submit time, not just at execute (`test_phase44_path_blocks_active_steward_removal_at_submit`). |
| Frontend build | Yes | PASS — new bundle `index-BARSNmNc.js`, CSS `index-CaWc8b6x.css`. PWA precache 23 entries / 2067.34 KiB. |
| Browser verification (Chrome MCP, prod) | Yes | TBD post-deploy |
| PG smoke | No | Not required — no migration. |
| Bundle hash changed + backend non-502 post-deploy | Yes | TBD post-deploy |

---

## Files added/modified

**New backend (1):**
- `backend/tests/test_phase_45a_steward_recovery_handoff.py`

**Modified backend (2):**
- `backend/pending_actions/registry.py` — `_validate_member_remove` + `execute_member_remove` extended for inactive-steward + successor path; new `_count_other_active_stewards` + `_promote_successor_to_steward` helpers; `_exec_member_remove` wrapper passes `successor_user_id` + `actor_id` through; `_preview_member_remove` surfaces successor; `log_audit_event` import added.
- `backend/routes/organizations.py` — `remove_member` accepts optional `_MemberRemoveBody { successor_user_id? }`; direct path delegates to shared `execute_member_remove` so audit + invariant logic lives in one place; new `transfer_stewardship` POST endpoint + `_TransferStewardshipBody` schema.

**New frontend (0):**
- (none — F2 added a section to existing `OrgSettings.jsx` rather than creating a new component, matching how the Phase 44 Multi-Admin Approval section was added)

**Modified frontend (1):**
- `frontend/src/pages/admin/OrgSettings.jsx` — replaced `isSteward` role-string gate with `canDeleteOrg = useHasPermission('org.delete')` (F1); added `canTransferStewardship`, transfer-section state + handlers + UI block (F2).

---

## Feature-off / regression guarantee

**The relaxation is narrow and inactive-only.** Active stewards are exactly as protected after this pass as before — the removal guard now reads `if target_user.is_active: raise "Cannot remove the Steward"`, identical to the prior unconditional block when `is_active=True`. The B5 regression class (`TestActiveStewardRegression`) explicitly asserts this on three independent endpoints (remove / role-change / suspend).

The at-least-one-steward invariant is enforced on every mutating path: the transfer is structurally atomic (swap, never leaves zero), and the recovery removal requires a named successor before it can complete.

---

## Deferred / out of scope

- Opt-in ownerless mode (`org.allow_ownerless` setting, zero-stewards-as-a-valid-state, recovery state machine) — Phase 45b.
- Elected-leadership / board / recall — Pass B/C of the broader arc.
- Admin-initiated transfer of an *active* steward as a routine path — explicitly out of scope per spec.
- Leave-org and self-delete-account flows — don't exist today; future passes must add the sole-steward guard when they ship.

---

## Tech debt / followups surfaced

- The `_count_other_active_stewards` helper + `_promote_successor_to_steward` helper are placed in `pending_actions/registry.py` because they share that file's existing imports and the `execute_member_remove` shared executor. For Phase 45b, this logic will likely want to live in a more central `org_membership.py` or `steward_recovery.py` module once the cardinality floor becomes setting-driven — but moving it now would be churn for no benefit.
- The transfer endpoint is steward-only-initiated. The recon's OPT-IN-2 ("admins must be able to initiate in recovery mode") is deferred to Phase 45b along with the rest of the opt-in surface; the recovery removal path (B1/B2) is the admin-tier action that's needed today.

---

## Branch + commit state

- Branch: `phase-45a/steward-recovery-handoff`
- Commit: TBD on commit
- Merge commit on master: TBD
- Pushed to origin/master: TBD
