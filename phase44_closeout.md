# Phase 44 — Multi-Admin Approval Workflow — Closeout

**Spec:** `phase44_multi_admin_approval_spec.md`
**Branch:** `phase-44/multi-admin-approval` → merged `--no-ff` to master (TBD)
**Deployed:** Railway prod, bundle `index-BcmuObmw.js` (TBD verified)
**Date:** 2026-05-31

---

## Per-cluster status

| Cluster | Status | Notes |
|---|---|---|
| B1 — Migration + models | DONE | New `pending_admin_actions` + `pending_action_approvals` tables; reversible `down()`; idempotency guards. `down_revision = "4b0bf8f1761f"`. Models added in `models.py` with cascade-delete relationship from action → approvals + unique constraint on (pending_action_id, approver_id). |
| B3 — Action registry + execution engine | DONE | `pending_actions/registry.py` registers the four wrapped action types with permission key + approver-set resolver + payload validator + executor + preview builder. Shared executors used by both direct path (approval off) and ratification executor (approval on). `org.delete` approver-set is steward-only (D5). Role-permissions executor re-checks baseline drift before applying. |
| B4 — Endpoints | DONE | `routes/pending_actions.py` mounts under `/api/orgs/{slug}/admin/pending-actions`. POST submit / GET list / GET single / POST approve / POST decline / GET count. Approver-gating in engine; engine-level permission checks; viewer gating via `can_view_pending_actions`. |
| B5 — Expiry worker tick | DONE | `expire_due_pending_actions` plugged into `digest_scheduler.run_one_tick`. Cheap short-circuit when no rows due; wrapped in try/except per scheduler convention. |
| B6 — Notifications + audit | DONE | 5 new event types in `notification_events.py` (`pending_action.submitted` / `.executed` / `.declined` / `.expired` / `.failed`) under new "Admin actions" category. Audit entries at every transition via `log_audit_event`. All `emit_notification` calls wrapped in try/except. |
| B7 — Tests | DONE | `test_phase_44_multi_admin_approval.py` (19 tests) + `test_phase_44_migration_cycle.py` (3 tests). Covers: feature-off regression × 4 actions, submit/approve/execute happy path, decline veto (D9), self-approval (D4), deadlock guard (D6), revalidation failure (D7), expiry worker (D8), role_permissions baseline drift detection (D11b), permission gating, count endpoint, full audit trail. **22/22 PASS** locally. |
| F1 — Opt-in setting | DONE | New "Multi-Admin Approval" section in `OrgSettings.jsx` with enable toggle + per-action thresholds + window-hours. Persists to `organization.settings.multi_admin_approval`. |
| F2 + F2b — Pending-actions surface + discovery | DONE | New `pages/admin/PendingActions.jsx` lists pending + resolved actions with full previews (including per-role permission diff for `role_permissions.edit` and drift warning). `usePendingActionsCount` hook polls the count endpoint every 60s. Count badge on Admin → Pending actions menu item (desktop + mobile). `PendingActionsBanner` component in-context-banner on Members, Topics, RolePermissions, OrgSettings pages. |
| F3 — Initiate-flow interception | DONE | Members.jsx, Topics.jsx, RolePermissionsPage.jsx, OrgSettings.jsx destructive handlers now detect `status: "submitted_for_approval"` in the response and show a distinct toast. `api.delete` extended to optionally carry a body (`{body: {confirmation: <slug>}}`) for `org.delete`'s confirmation payload. |

---

## Verification matrix

| Check | Required | Result |
|---|---|---|
| Backend pytest (full) | Yes | TBD (running). Phase 44 suite locally: **22/22 PASS** including side-effect assertions for member-actually-removed, topic-actually-soft-deleted, audit log entries, notification fan-out, and the regression check that wrapped actions behave EXACTLY as today with approval off. |
| Migration reversible + cycle test | Yes | **PASS** — `test_phase_44_migration_cycle.py` runs upgrade → downgrade → upgrade and asserts both tables present/absent at each stage, plus the unique-constraint check. |
| PG smoke (`pg_smoke.py --mode both --prior-revision 4b0bf8f1761f`) | Yes | **PASS** (both modes). Output: `PG SMOKE PASS (all modes)`. |
| Frontend build | Yes | **PASS** — new bundle `index-BcmuObmw.js`, CSS `index-BSd66wTC.css`. PWA precache 23 entries / 2064.55 KiB. |
| Browser verification (Chrome MCP, prod) | Yes | TBD post-deploy. |
| Bundle hash changed + backend non-502 post-deploy | Yes | TBD. |

---

## Files added/modified

**New backend (4):**
- `backend/migrations/versions/c1a4d8b7e2f1_phase_44_pending_admin_actions.py`
- `backend/pending_actions/__init__.py`
- `backend/pending_actions/settings.py`
- `backend/pending_actions/registry.py`
- `backend/pending_actions/engine.py`
- `backend/routes/pending_actions.py`
- `backend/tests/test_phase_44_migration_cycle.py`
- `backend/tests/test_phase_44_multi_admin_approval.py`

**Modified backend (5):**
- `backend/models.py` — added `PendingAdminAction` + `PendingActionApproval` classes.
- `backend/notification_events.py` — added "Admin actions" category + 5 event types.
- `backend/digest_scheduler.py` — added expiry tick.
- `backend/main.py` — registered router.
- `backend/routes/organizations.py` — wrapped `delete_organization`, `remove_member`, `delete_org_topic` with Phase 44 intercepts.
- `backend/routes/role_permissions_routes.py` — wrapped `patch_role_permissions` with Phase 44 intercept.

**New frontend (3):**
- `frontend/src/pages/admin/PendingActions.jsx`
- `frontend/src/hooks/usePendingActionsCount.js`
- `frontend/src/components/PendingActionsBanner.jsx`

**Modified frontend (8):**
- `frontend/src/App.jsx` — new route.
- `frontend/src/components/Nav.jsx` — Admin dropdown entry + count badge (desktop + mobile).
- `frontend/src/constants/admin_nav_permissions.js` — `pendingActions` mapping.
- `frontend/src/utils/urls.js` — `admin-pending-actions` URL kind.
- `frontend/src/api.js` — DELETE body support.
- `frontend/src/pages/admin/OrgSettings.jsx` — opt-in section + intercept handling + discovery banner.
- `frontend/src/pages/admin/Members.jsx` — intercept handling + discovery banner.
- `frontend/src/pages/admin/Topics.jsx` — intercept handling + discovery banner.
- `frontend/src/pages/admin/RolePermissionsPage.jsx` — intercept handling + discovery banner.

---

## Feature-off regression guarantee

**With `multi_admin_approval.enabled = false` (the default), the four wrapped actions behave EXACTLY as today.** Verified via the `TestFeatureOffRegression` test class — four tests, one per action type, each asserts the direct-path side effect (`db.delete(membership)`, `topic.org_id = None`, `db.delete(org)`, matrix patched in-place) with zero pending rows created. The intercept is a single `if p44_settings.is_action_wrapped(org, action_type):` branch at the top of each handler; falsy → falls through to the unchanged direct path.

---

## Deferred / out of scope

- The elected-leadership layer (per spec — needs its own design conversation).
- Ratification for non-destructive actions.
- Majority-override of declines (one decline vetoes is fixed for v1 per D9).
- "Initiator doesn't count" mode (D4 self-approval is fixed for v1).
- Time-locks on already-ratified actions.

---

## Branch + commit state

- Branch: `phase-44/multi-admin-approval`.
- Commit on branch: TBD.
- Merge commit on master: TBD.
