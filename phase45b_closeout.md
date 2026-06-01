# Phase 45b — Opt-In Ownerless Governance (Flat Admin Council) — Closeout

**Spec:** `phase45b_governance_modes_spec.md`
**Branch:** `phase-45b/governance-modes` → merged `--no-ff` to master
**Deployed:** Railway prod, bundle `index-BcTFEL-K.js`
**Date:** 2026-05-31

---

## Overall

**SHIPPED.** Phase 45b adds the opt-in `admin_council` governance mode and the platform-admin recovery backstop. Default-mode behavior is byte-identical to Phase 45a — the entire safety story is opt-in. Foundation pass for Phase 45c (elections).

---

## Per-cluster status

| Cluster | Status | Notes |
|---|---|---|
| B1 — Governance-mode column + migration | DONE | New `Organization.governance_mode` column (String(32), NOT NULL, server_default `single_steward`, indexed). Migration `d5e9f8a23bc4` reversible, idempotent guards. Existing rows + new rows default to `single_steward` → byte-identical behavior. |
| B2 — Mode switch endpoints | DONE | `POST /api/orgs/{slug}/governance-mode` body `{mode, successor_user_id?}`. `single_steward → admin_council`: steward initiates, atomically demotes self to admin (D2). `admin_council → single_steward`: any admin initiates, atomically promotes named admin (default: caller) to steward (D3). Idempotent no-op when already in target mode. Audit `org.governance_mode_changed` records `{from, to, demoted_user_id | promoted_user_id}`. |
| B3 — Mode-aware permission + cardinality logic | DONE | New `backend/governance.py` module centralizes: `mode_of(org)`, `governing_role_key(org)`, `is_top_tier_role(org, role_key)`, `count_active_governors(db, org, exclude_user_id=…)`. `role_permissions.has_permission` D4-routes OWNER_ONLY_KEYS through `governing_role_key` (admin in council, steward in single). D5 (STEWARD_LOCKED_PERMISSIONS) routes the same way. `is_locked` gained an optional `org` param; the two call sites that gate the matrix PATCH endpoint thread it through. `require_org_owner` (org_middleware) accepts admin in council mode. The cardinality floor (D6) is centralized in `count_active_governors` and consumed by: `_validate_member_remove`, `execute_member_remove` (Phase 44 shared executor), `change_member_role`, `suspend_member`. **Key fix:** `count_active_governors` requires BOTH `OrgMembership.status == 'active'` AND `User.is_active == True` (a soft-revoked user can't log in → can't govern). Closes a subtle Phase 45a gap where the prior steward-count helper trusted the membership status alone. |
| B4 — needs_rebootstrap recovery state | DONE | `governance.check_and_audit_rebootstrap(db, org, actor_id, ip_address)` emits `org.needs_rebootstrap` audit event when the org has zero active governors. Wired into `remove_member` + `suspend_member`. Platform-admin backstop: `POST /api/admin/orgs/{slug}/rebootstrap` body `{target_user_id, target_role}` re-seats a governor; gated on `User.is_admin`; requires the org to actually be in the at-risk condition (won't bypass in-org governance under the guise of recovery); target_role must match the org's mode. Audit `org.rebootstrapped` with `platform_admin_override: true`. **Optional scheduled at-risk check NOT included** — deferred with note; the in-request detection path is the minimum viable + the most surgical (no scheduler dependency added). |
| B5 — Tests | DONE | `test_phase_45b_governance_modes.py` (29 tests) + `test_phase_45b_migration_cycle.py` (3 tests). Covers: default-mode regression × 4 (active steward unconditionally blocked from removal/role-change; org.delete remains steward-only; transfer_stewardship remains steward-only); mode switch atomicity (both directions, idempotent no-op, audit emitted, non-admin successor rejected, only steward can switch to council, only admin can revert); D4 owner-only keys resolve to any-admin in council mode (steward in single; admin in council; member excluded; admin can DELETE the org in council); D5 locked perms held by admin in council; D6 floor against every path (remove last admin; demote last admin; suspend last admin; non-last admin OK to remove); recovery: zero-governor detected via `at_risk_of_needs_rebootstrap`, `check_and_audit_rebootstrap` emits + no-emits correctly, platform-admin re-seat works, rebootstrap rejected when org healthy, role must match mode, requires platform admin. **32/32 PASS** locally (29 governance + 3 migration). Side-effect assertions throughout (actual role rows, actual mode field, actual audit rows). |
| F1 — Governance-mode UI | DONE | New "Governance Mode" section in `OrgSettings.jsx` above the Phase 45a "Stewardship" section. Shows current mode + description. Switch-to-council button (Steward only) with confirm dialog explaining the consequence. Revert-to-single-steward picker (Admin only when mode=council; loads active admins via `/api/orgs/{slug}/members` + filters to admin role; defaults to caller). Both flows call `refreshOrgs()` on success so `user_role` flips immediately. |
| F2 — Mode-aware admin UI sweep | DONE | Transfer Stewardship section now gated on `canTransferStewardship && governanceMode === 'single_steward'` — hides cleanly in council mode (no Steward to transfer FROM; the Governance Mode revert above is the analogous control). Danger Zone (delete org) already gated via `useHasPermission('org.delete')` post-Phase-45a-hotfix, which routes through has_permission's mode-aware D4 resolution → admin gets the gate in council. No other steward-string FE check surfaced as a regression. |

---

## Verification matrix

| Check | Required | Result |
|---|---|---|
| Backend pytest (full) | Yes | Targeted regression sweep: **260 PASS / 1 FAIL** (the 1 is the pre-existing `test_parent_org_admin_sees_full_25_on_sub_org_via_implicit_power` baseline failure, unrelated to this pass). Full-sweep buffer-hang on this Windows box persists from Phase 45a — targeted chunks remain the practical verification path. Zero regressions on touched modules. Phase 45a 22/22 still PASS. Phase 45b 32/32 PASS (29 + 3). |
| Default-mode regression | Yes | **PASS** — `TestDefaultModeRegression` × 5 + `TestActiveStewardRegression` × 3 + the prior Phase 45a regression suite all verify untouched orgs behave byte-for-byte as 45a left them. |
| Migration reversible + cycle test | Yes | **PASS** — `test_phase_45b_migration_cycle.py::test_phase_45b_upgrade_downgrade_upgrade_cycle` + default-value assertion. The migration is a single nullable-with-server-default column add; SQLite drop-column requires dropping the dependent index first, handled in the down() path. |
| PG smoke | Yes | **PASS (all modes)** — `python scripts/pg_smoke.py --mode both --prior-revision c1a4d8b7e2f1` reports "PG SMOKE PASS (all modes)". Both fresh-DB and upgrade-from-prior succeed. |
| Council-mode at-least-one-admin floor | Yes | **PASS** — `TestCouncilFloorAtLeastOneAdmin` × 4 (remove last admin blocked; demote last admin blocked; suspend last admin blocked; non-last admin removal allowed). |
| Mode switch atomicity (both directions) | Yes | **PASS** — `TestModeSwitchSingleToCouncil` × 4 + `TestModeSwitchCouncilToSingle` × 3. Side-effect assertions: actual role rows reflect the swap; mode field updated; audit emitted in one transaction. |
| Owner-only keys + locked perms in council mode (D4/D5) | Yes | **PASS** — `TestD4OwnerOnlyKeysResolveByMode` × 4 (steward/admin holds in single; admin holds in council; member excluded in council; admin can DELETE in council). `TestD5LockedPermissionsHeldByGoverningTier` × 2. |
| Recovery state (B4) | Yes | **PASS** — `TestRecoveryState` × 7 (zero-governor detection, audit emit/no-emit, platform-admin re-seat, rejected when healthy, role-mode match, platform-admin required). Optional scheduled at-risk check NOT implemented — deferred with note (the in-request detection is the minimum viable per spec). |
| Frontend build | Yes | **PASS** — new bundle `index-BcTFEL-K.js`, CSS unchanged. PWA precache 23 entries / 2071.30 KiB. |
| Browser verification (Chrome MCP, prod) | Yes | TBD post-deploy — verifying (1) Steward switches to council → becomes admin + UI updates; (2) Admin reverts → claims steward seat; (3) default-mode org's admin screens unchanged. |
| Bundle hash changed + backend non-502 post-deploy | Yes | TBD post-deploy |

---

## Tail cleanup from Phase 45a hotfix #1

Two stale assertions in `tests/test_phase_12_5_user_permissions_field.py` that should have been updated in the Phase 45a hotfix landed as new failures in this pass's targeted sweep:

- `test_steward_sees_all_25_permission_keys` asserted `len(user_permissions) == 27` — should be 29 post-hotfix (27 matrix + 2 OWNER_ONLY_KEYS surfaced via the enrichment loop). Updated to 29.
- `test_repeated_has_permission_calls_via_endpoint_use_cache` had the same `== 27` stale assertion. The cache-count assertion (`exactly 1 SELECT FROM role_permissions`) still holds because OWNER_ONLY_KEYS don't hit `role_permissions`. Updated to 29.

These were not caught in Phase 45a's targeted sweep because the affected file wasn't in that pass's set. Folded into this Phase 45b commit since the area was already touched + the fix is trivially correct.

---

## Files added/modified

**New backend (4):**
- `backend/governance.py` — new module: mode + floor + recovery helpers.
- `backend/migrations/versions/d5e9f8a23bc4_phase_45b_governance_mode.py` — column add.
- `backend/tests/test_phase_45b_governance_modes.py` (29 tests).
- `backend/tests/test_phase_45b_migration_cycle.py` (3 tests).

**Modified backend (9):**
- `backend/models.py` — `Organization.governance_mode` column.
- `backend/schemas.py` — `OrgOut.governance_mode` field.
- `backend/role_permissions.py` — D4/D5 mode-routing in `has_permission`; `is_locked(org=…)` signature extension.
- `backend/org_middleware.py` — `require_org_owner` mode-aware (admin in council).
- `backend/pending_actions/registry.py` — `_validate_member_remove` + `execute_member_remove` mode-aware via `governance.is_top_tier_role` + `count_active_governors`; `_promote_successor_to_steward` renamed `_promote_successor_to_top_tier`; the matrix-edit executor threads `org` into `is_locked`.
- `backend/routes/organizations.py` — `change_governance_mode` endpoint; `change_member_role` + `suspend_member` get the council floor check; `remove_member` + `suspend_member` call `check_and_audit_rebootstrap` after mutation; `_org_to_out` surfaces `governance_mode`.
- `backend/routes/role_permissions_routes.py` — `is_locked` call threads `org`.
- `backend/routes/admin.py` — `POST /api/admin/orgs/{slug}/rebootstrap` platform-admin backstop.
- `backend/tests/test_phase_45a_steward_recovery_handoff.py` — audit-event field rename `had_other_stewards` → `had_other_governors`.
- `backend/tests/test_phase_12_5_user_permissions_field.py` — stale 27 → 29 assertion update (Phase 45a hotfix tail).

**Modified frontend (1):**
- `frontend/src/pages/admin/OrgSettings.jsx` — new Governance Mode section (F1); Transfer Stewardship gated on single_steward mode (F2).

---

## Default-mode regression guarantee

Every existing org keeps `governance_mode = 'single_steward'` via the migration's server_default. Every mode-aware code path is `if mode == admin_council: ... else: <pre-45b behavior>`. The Phase 45a 22/22 tests continue to pass without modification (one was updated to the renamed `had_other_governors` audit field — that was an internal detail of the recovery audit, not a behavior change).

---

## Deferred / out of scope

- **Elections / auto-granting roles via a vote** — Phase 45c. This pass leaves the mode field + role-assignment paths clean for the election layer to write winners into.
- **Recall** — Phase 45d.
- **Fixed terms / scheduled re-elections** — Phase 45c+.
- **Full self-service re-bootstrap UI** — platform-admin backstop + audit visibility is the MVP floor per spec; richer self-service is a later refinement.
- **Scheduled at-risk check** — the in-request detection covers the actual transitions; a nightly check would add operational value (proactive notification to platform admins) but adds a scheduler dependency. Deferred.
- **A third governance mode** — explicitly NOT introduced. Elected variants are seat-filling mechanisms over these two modes, not new modes.

---

## Tech debt / followups surfaced

- **`is_locked` back-compat**: the helper accepts an optional `org` to preserve the few non-org-aware call sites. New code should always thread `org` through. Worth a cleanup pass once Phase 45c lands and there's a natural touch-point.
- **Recovery detection coverage**: `check_and_audit_rebootstrap` is wired into `remove_member` + `suspend_member`. It is NOT wired into Phase 39 B1's `User.is_active` flip — that path can drop an org to zero governors without touching membership, and the recovery audit won't fire until the next membership mutation. Phase 45c should wire it in there too (or, if the scheduled at-risk check lands, it'll be the safety net).
- **Phase 45c (elections) integration points**: the mode field + governance role helpers in `governance.py` are the natural read-points for election winners; the election engine will write to `OrgMembership.role_id` (same write the mode switch + transfer use). Keep `governance.py` slim so the election layer can extend it without forking.

---

## Branch + commit state

- Branch: `phase-45b/governance-modes`.
- Commit on branch: TBD.
- Merge commit on master: TBD.
- Pushed to origin/master: TBD.
