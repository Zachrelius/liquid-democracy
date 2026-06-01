# Phase 47 — Org Titles / Offices — Closeout

**Spec:** `phase47_org_titles_spec.md`
**Branch:** `phase-47/org-titles` → merged `--no-ff` to master (pending push)
**Deployed:** Railway prod, bundle `index-CpX8ElRx.js` (pending push)
**Date:** 2026-06-01

---

## Overall

**SHIPPED + PROD-VERIFIED + HOTFIXED.** Phase 47 adds the **title/office** concept as a first-class, per-org primitive — decoupled from but optionally bound to platform roles, with public display and direct assignment. Built-in reconciliation (Steward/Admin as system titles per D6) is conservative: the role + `governance.py` floor + recovery + governance modes are **byte-for-byte unchanged**. Foundation for Phase 48 (elections fill a title).

---

## Per-cluster status

| Cluster | Status | Notes |
|---|---|---|
| B1 — Data model + migration | DONE | New `org_titles` table (name, optional `bound_role` enum, `cardinality_mode` single/multi, optional `max_holders`, `fill_method` assigned/elected/both, `is_system`, `display_order`). New `org_title_assignments` table (title_id, user_id, granted_by, granted_at; UniqueConstraint(title_id, user_id)). Reversible migration `f3c7e9b48201` with idempotency guards. **PG-portable**: switched the backfill SQL from `is_system = 1` (SQLite implicit) to parameterized `:sys = True` so the same SQL works on Postgres (strict boolean type). |
| B2 — Title CRUD + permission gate | DONE | `GET/POST/PATCH/DELETE /api/orgs/{slug}/titles`. New `title.manage` permission key registered in `permission_registry.py` (default-granted to steward + admin since DEFAULT_GRANTS uses `set(ALL_PERMISSION_KEYS)` for those tiers; moderator/member are excluded). System titles are uneditable + undeletable; custom titles with active holders cannot be deleted (must revoke first). Audit `title.created/updated/deleted`. |
| B3 — Assignment / revocation | DONE | `POST/DELETE /api/orgs/{slug}/titles/{id}/assignments[/{user_id}]`. **System titles cannot be assigned directly** — the is_system check happens BEFORE any role mutation so a rejected attempt leaves zero side effects. Single-holder cardinality enforced; multi-holder cap enforced. Bound-role assignment flows through the existing 45a/45b role-assignment machinery via a helper `_apply_bound_role_for_assign`: steward binding does an atomic swap with existing steward (mirrors `transfer-stewardship`), rejected in `admin_council` mode (no steward seat) per D7. Floor check on revoke (`_check_revoke_floor`) blocks removing the only steward-binding title from the org's only steward (the same block as `remove_member` for the active steward). Audit `title.assigned/title.revoked`. |
| B4 — held_titles surface | DONE | `OrgMemberOut.held_titles: list[str]` added; `list_members` populates via `org_titles.held_titles_for_member` which combines system titles derived from `membership.role.system_key` + custom titles from `org_title_assignments` (ordered by `display_order`, then `name`). **Extended the 46a serializer-coverage test** to assert `held_titles` is present on the `OrgMemberOut` schema (per the standing convention added in 46a) — closes the model-vs-response gap pattern at a new surface. |
| B5 — System title reconciliation | DONE | `org_titles.seed_system_titles_for_org()` seeds two system titles per org: "Steward" (binds steward, single-holder) + "Admin" (binds admin, multi-holder). Called from `create_organization` for new orgs; migration backfills the same set for existing orgs (idempotent on re-run). Per D6 these are a **label layer over the existing roles** — their "holders" are derived at response-build time from `membership.role`, NOT stored in `org_title_assignments`. Storing system-title assignments separately would create a role-vs-title sync problem; this conservative path avoids it. The `governance.py` floor reads roles, not titles, and is **not modified** in this pass. |
| B6 — Tests | DONE | `test_phase_47_org_titles.py` (19 tests): system title seed + protection × 4; CRUD + permission gate × 3; assignment mechanics × 6 (label-only doesn't change role; admin-binding promotes to admin; steward-binding atomically swaps; council-mode rejects steward-binding; single + multi-cap cardinality); revoke floor preservation × 2; held_titles surface × 2; built-in reconciliation regression × 2 (active steward still un-removable; mode switch still works). `test_phase_47_migration_cycle.py` (3 tests): upgrade adds tables; cycle; backfill seeds existing orgs. **22/22 PASS** locally. Targeted regression sweep across Phase 12 + 44 + 45a + 45b + 46 + 46a + 47 + admin + permissions + roles + notifications: **284 PASS / 1 FAIL** (the 1 is the unchanged known-baseline `test_parent_org_admin_sees_full_25_on_sub_org_via_implicit_power`). |
| F1 — Titles management UI | DONE | New `components/OrgTitlesPanel.jsx`: lists titles (system + custom) with bound role + cardinality + holder count; create-custom-title form (name + bound role + cardinality + max_holders); delete (custom titles with zero holders); inline "Assign…" picker per custom title. Gated on `useHasPermission('title.manage')` so non-managers don't see it. Mounted in `OrgSettings.jsx` above Multi-Admin Approval. Per-title holder list with inline revoke deferred to v2 (the API supports it; the UI affordance is a followup). |
| F2 — Display titles after member names | DONE | `Members.jsx` renders `member.held_titles` as a comma-joined italic tag after each member's display_name. Identity-visibility upstream (D8): the FE only renders what the backend surfaces, so a redacted node automatically shows no title — the title attribute would simply not be in the response. |

---

## Verification matrix

| Check | Required | Result |
|---|---|---|
| Backend pytest (full) | Yes | Targeted regression sweep: **284 PASS / 1 FAIL** (the 1 is the unchanged known-baseline sub-org implicit-power test). Phase 47: 22/22 PASS isolated. Phase 45a + 45b + 46 + 46a all still PASS. The bump from 27→28 in the permission registry (+ `title.manage`) propagated to the relevant count assertions. |
| Built-in reconciliation regression | Yes | **PASS** — `TestBuiltinReconciliationRegression` × 2 + the 22/22 Phase 45a + 32/32 Phase 45b + 20/20 Phase 46a all pass. Active steward still unremovable; mode switch still demotes steward to admin atomically; floor reads roles (not titles); recovery paths unchanged. The role model + governance.py are byte-for-byte unchanged. |
| Title↔role binding | Yes | **PASS** — `TestTitleAssignmentMechanics` × 6: label-only doesn't change role; admin-binding promotes member→admin; steward-binding does the atomic swap (existing steward → admin, target → steward); council-mode steward-binding rejected with clear error; single + multi-cap cardinality enforced. |
| Floor preserved through title ops | Yes | **PASS** — `TestRevokeFloorPreserved` × 2: revoking the only steward-binding title is blocked exactly as removing the only steward; revoking a label-only title succeeds without floor interference. |
| Cardinality | Yes | **PASS** — single-holder + multi-cap both tested with explicit side-effect assertions. |
| Assignment permission gate (D5) | Yes | **PASS** — `test_member_without_title_manage_cannot_create` returns 403. |
| Public display + identity-visibility (D8) | Yes | **PASS** — `TestHeldTitlesSurfacing` × 2 confirms system Steward shows for steward; system Admin for admins; member with custom Honorary Chair has both Steward and Honorary Chair in held_titles. Identity-visibility wins per D8: the FE only renders what the backend surfaces. |
| Serializer-coverage extended (B4) | Yes | **PASS** — `TestOrgMemberOutSurfaceContract` × 2 asserts `held_titles` is on `OrgMemberOut.model_fields` + the helper returns the Steward system title for a steward member. |
| Migration reversible + cycle test | Yes | **PASS** — `test_phase_47_upgrade_downgrade_upgrade_cycle` + `test_phase_47_backfills_system_titles_for_existing_orgs`. |
| PG smoke `--mode both --prior-revision e8b4d6f31a92` | Yes | **PASS (all modes)** after the boolean-type fix in the backfill SQL. Both fresh-DB and upgrade-from-prior succeed. |
| Frontend build + bundle hash | Yes | **PASS** — new bundle `index-CpX8ElRx.js`, CSS `index-tbFjDNYp.css`. PWA precache 23 entries / 2083.80 KiB. |
| Browser verification (Chrome MCP, prod) | Yes | **Initial QA: T2 PASS + T3 PASS + T1/T4 FAIL (root-cause: existing orgs lacked the `title.manage` row_permissions rows)**. Hotfix #1 (`a9ea553`, backfill migration `f4d8a9c52312`) backfilled the grant for steward + admin roles on every existing org. **Post-hotfix verification PASS**: Steward of `/demo` now has 30 user_permissions including `title.manage` (was 29); `POST /api/orgs/demo/titles/<steward_id>/assignments` returns the expected 400 "System titles are derived from the member's role and cannot be assigned directly" (T4 — the system-title block fires correctly when the caller has the gate permission). Held_titles surface (T2) was always working; backend titles endpoint (T3) always working. |
| Bundle hash changed + backend non-502 post-deploy | Yes | **PASS** — bundle `index-DBkO-try.js` → `index-CpX8ElRx.js`. Backend `/api/health` 200. Hotfix #1 redeploy succeeded; new migration `f4d8a9c52312` applied (added `title.manage` row to existing steward + admin role_permissions). |
| Worker / start.sh | Not touched | **Confirmed worker untouched** — Phase 47 has no scheduled behavior; that's Phase 49 territory. No worker-touching check required. |

---

## Files added/modified

**New backend (4):**
- `backend/org_titles.py` — title service module (seed, validate, grant/revoke, held_titles_for_member).
- `backend/routes/org_titles.py` — title CRUD + assignment endpoints.
- `backend/migrations/versions/f3c7e9b48201_phase_47_org_titles.py` — reversible migration + idempotent backfill.
- `backend/tests/test_phase_47_org_titles.py` (19 tests) + `backend/tests/test_phase_47_migration_cycle.py` (3 tests).

**Modified backend (6):**
- `backend/models.py` — `OrgTitle` + `OrgTitleAssignment` models.
- `backend/schemas.py` — `OrgMemberOut.held_titles: list[str]`.
- `backend/main.py` — register `org_titles` router.
- `backend/permission_registry.py` — `title.manage` permission key (default-granted to admin/steward).
- `backend/routes/organizations.py` — `create_organization` seeds system titles; `list_members` populates `held_titles`.
- `backend/tests/test_phase_46a_orgout_serializer_coverage.py` — extended with `TestOrgMemberOutSurfaceContract`.
- `backend/tests/test_permission_registry.py` + `backend/tests/test_phase_12_5_user_permissions_field.py` — count bumps (27→28 / 29→30) for `title.manage` addition.

**New frontend (1):**
- `frontend/src/components/OrgTitlesPanel.jsx`.

**Modified frontend (2):**
- `frontend/src/pages/admin/OrgSettings.jsx` — mount OrgTitlesPanel above Multi-Admin Approval.
- `frontend/src/pages/admin/Members.jsx` — render `held_titles` after display_name.

---

## Default-behavior regression guarantee

Orgs that never define a custom title behave **byte-for-byte as pre-47**:

- New + backfilled orgs have two system titles (Steward, Admin) but those are pure label layer over existing roles. `held_titles` on a member roster surfaces a "Steward" string for the steward, but no role / permission / floor behavior changes.
- All `title.manage` actions are permission-gated via the new key (default: admin/steward); members see no new UI.
- The `governance.py` cardinality floor reads roles, not titles, and is unchanged.
- All Phase 45a + 45b + 46 + 46a tests continue to pass without modification.

---

## Deferred / out of scope

- **Elections filling titles** — Phase 48. The election close-hook becomes "assign a title (and its bound role)" — this pass stores `fill_method = elected/both` in config but does not build the election path.
- **Scheduled / term-based title turnover** — Phase 49.
- **Title hierarchies** — flat labels only; no "reports to" structures.
- **Per-title custom permission sets** — a title binds one of the existing roles or none; no bespoke permission bundles.
- **Migrating the permission model into titles** — explicitly forbidden per D2/D6.
- **Vote-graph / delegate-listing / proposal-author title display** — D8 calls for display across more surfaces; this pass ships the Members page surface (most direct). The other surfaces are easy followups that read the same `held_titles` field once added to those schemas.
- **Per-title holders list + inline revoke UI** — v2 followup for `OrgTitlesPanel.jsx`. The API endpoints support revoke today.

---

## Tech debt / followups surfaced

- **`/assignments` GET endpoint** — would let the FE display per-title holders + revoke without re-fetching the full member roster. Small, useful, deferred.
- **Title display across more surfaces (D8)** — vote-graph node labels, delegate listings, proposal authorship, comments. These would each need a small schema + builder update. Recommended followup pass when Phase 48 is shipped (since elections will be the most common case where titles want broad display).
- **Phase 48 integration hook**: the election close-hook should call `_apply_bound_role_for_assign` (or factor it out of `routes/org_titles.py` into `org_titles.py`) + `grant_title()`. Keep the path single + reusable.

---

## Hotfix #1 narrative

Prod QA found that on the live deploy, the Phase 47 F1 panel didn't render and B2/B3 endpoints returned 403 — even for the Steward. Root cause: PERMISSION_REGISTRY + DEFAULT_GRANTS includes `title.manage` (DEFAULT_GRANTS uses `set(ALL_PERMISSION_KEYS)` for steward + admin tiers), but `seed_default_roles_for_org` runs only at org-create time. For orgs created BEFORE Phase 47 — every org on prod — the `role_permissions` rows were seeded with the pre-47 grant set; they have no row for the new key, and `has_permission` returns False. F2 (held_titles display on the members roster) wasn't gated, so that always worked.

This is structurally the same gap as Phase 45a hotfix #1 + Phase 46 hotfix #1, but at the *permission-grant* layer rather than the *response-schema* layer. The 46a `OrgOut` serializer-coverage test wouldn't have caught it (the test asserts the field is on the response; the field IS on the response — `user_permissions` exists, it just doesn't include `title.manage` because no DB row grants it). The structural lesson: adding a new permission key requires a backfill migration for existing orgs, not just registry registration.

Hotfix #1 (`a9ea553`, migration `f4d8a9c52312`): backfills the `role_permissions` row for every steward + admin role across all orgs. Idempotent on re-run. Reversible downgrade drops the backfilled rows. Verified locally with both fresh-DB and an explicit backfill simulation. PG smoke PASS both modes. 22/22 Phase 47 tests still PASS. Prod post-hotfix: Steward of `/demo` now has `title.manage` in `user_permissions`; system-title assignment correctly returns 400.

**Followup tech debt**: a generic "permission registry CI test" would catch this pattern at PR time — for each key in PERMISSION_REGISTRY that's in DEFAULT_GRANTS for steward + admin, assert that every existing role with system_key in (steward, admin) has a corresponding role_permissions row. This would be a fixture-level assertion run during the regression sweep, not a runtime check. Recommended for the next pass that touches the permission system.

---

## Branch + commit state

- Branch: `phase-47/org-titles` (left alive locally).
- Commit on branch: `90db542 Phase 47: Org titles / offices (decoupled from platform roles)`.
- Merge commit on master: `f9fd8d0 Merge phase-47/org-titles: Phase 47 (Org Titles / Offices)`.
- Hotfix #1 commit on master: `a9ea553 Phase 47 hotfix #1: backfill title.manage grants for existing orgs`.
- Pushed to origin/master at `a9ea553`.
