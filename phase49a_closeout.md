# Phase 49a — Governance Integrity + Admin-Settings Clarity — Closeout

**Spec:** `phase49a_governance_integrity_clarity_spec.md`
**Branch:** `phase-49a/governance-integrity-clarity` → merged `--no-ff` to master
**Date:** 2026-06-02

---

## Overall

**SHIPPED.** Four clusters on the governance / admin-settings surface, all landed in one deploy as the spec recommended (bisection-friendly build order: A → B → C → D, all shippable as a unit since none failed mid-build).

- **A (security headline)** closes the disable-then-act escape hatch: an admin can no longer unilaterally weaken multi-admin approval while it's enabled.
- **B (design simplification)** drops the legacy 3-way `proposal_creation_mode` column for a permission + cosign-toggle model. Migration preserves each old mode's effective behavior.
- **C1 + C2 (clarity / hard rule)** plain-outcome governance copy + a frontend phase-number-leak sweep that found exactly one user-facing leak (the one Z spotted).
- **D (display only)** secondary-unit hints next to hour-based duration inputs; no storage or timestamp arithmetic change.

---

## Per-cluster status

| Cluster | Status | Notes |
|---|---|---|
| A — Approval-disarm lockdown | DONE | `org.approval_config_change` registered in the Phase 44 action registry (admin-or-steward-only, approver-set `_admins_of`, default threshold 2). `is_weakening_change(current, proposed)` in `pending_actions/settings.py` defines weakening precisely: enabled→false OR threshold decrease OR known-action removal whose default is lower. Strengthening (threshold increase, wrapped-action addition) + first-enable (false→true) + window-only changes apply directly. PATCH `/api/orgs/{slug}` intercepts the `multi_admin_approval` block, computes weakness, and routes through `submit_pending_action` when approval is currently enabled. Engine's `_execute_now` initiator re-check now respects `admin_or_steward_only` so ratified actions of this class don't fail revalidation. |
| B — Proposal-creation remap | DONE | Migration `b9c2e0f43215` (hex prefix). Drops `Organization.proposal_creation_mode`. Backfills `settings.allow_cosign_petition` per org: `open` → false (no member-grant change); `cosign_required` → true + revoke `proposal.create` from member role; `admin_only` → false + revoke member's `proposal.create`. `cosign.gate_proposal_creation` rewritten to a clean decision tree (hold `proposal.create` → direct; else if toggle on → cosign-gated; else 403). 403 message no longer leaks the `admin_only` mode name. `routes/organizations.create_org_proposal` lets the gate own the decision (removed the redundant upstream permission check that conflicted with the legacy mode dispatch). OrgUpdate / OrgOut / `_org_to_out` swapped from `proposal_creation_mode` to `allow_cosign_petition`. Phase 46a serializer-coverage allow-list updated. Phase 46 + 46a test fixtures updated for the new model. Phase 46 migration-cycle test scoped to Phase 46's own revision so the downstream drop doesn't break the assertion. |
| C1 — Plain-language governance copy | DONE | Governance-mode section: "Top leadership" header; "A single top leader (Steward)" / "A team of admins, no single top leader"; outcome-shaped switch buttons; outcome-shaped descriptions. Elected-revert toggle: "Let the admin team elect a single top leader" with outcome-shaped helptext. Zero mode-name mechanics leakage in the rewritten copy. |
| C2 — Phase-number leak sweep | DONE | **One leak found + fixed** — the exact instance Z spotted at OrgSettings.jsx:1995 ("Off keeps Phase 47's strict separation between the two modes"). The frontend-wide grep across `*.jsx` / `*.js` for `'Phase '`, lowercase `'phase '`, and `P4x`-style references in user-visible strings (excluded code comments via `/* */` filter) returned zero other matches. JSX comments and internal dev strings are explicitly exempt per spec. |
| D — Duration display consistency | DONE | Secondary-unit hints rendered next to hour-based inputs when the value resolves to >23 hours: cosign gathering window → "(N days)"; multi-admin expiry window → "(N days)" + default helptext now reads "72 hours (3 days)". NO storage change. NO timestamp arithmetic change. Implementer's discretion exercised on the lightest UX choice (secondary-unit hint), per spec D1's "OR settle the display on one primary unit per context with the other shown as a secondary hint." |

---

## Verification matrix

| Check | Required | Result |
|---|---|---|
| Backend pytest (Phase 49a + every adjacent + migration cycles) | Yes | **247/247 PASS in 124s** across Phase 49a (20 new — disarm lockdown 11, proposal-creation parity 7, migration cycle 2), Phase 49 (14), Phase 48 stages (36), Phase 47 (24), Phase 46 + 46a (50), Phase 45a/45b (19), Phase 44 (28), digest aggregation, Phase 13.3 + Phase 40 ops. No regressions in any adjacent phase. |
| A — disarm escape hatch closed | Yes | **PASS** — `TestWeakeningRoutesToPendingAction::test_disable_attempt_while_enabled_does_not_apply` asserts the config STAYS `enabled=True` after a PATCH attempting to disable it, and exactly one pending action is created. `test_threshold_decrease_does_not_apply_directly` covers the threshold case. `TestRatificationAppliesTheChange::test_ratification_applies_disable` asserts the disable lands ONLY after a second admin approves. **Row-level side effects (config state before/after ratification), not just status codes.** |
| A — strengthening / first-enable stays direct | Yes | **PASS** — `TestStrengtheningIsDirect::test_first_enable_applies_directly` + `test_raising_threshold_applies_directly`. |
| A — weakening predicate unit coverage | Yes | **PASS** — `TestWeakeningPredicate` covers each transition case independently. |
| B — proposal-creation parity (load-bearing) | Yes | **PASS** — `TestParityHelper::test_open_mode_parity` (member without grant → 403), `test_cosign_required_mode_parity` (member without grant + toggle on → cosign-gated 201), `test_admin_only_mode_parity` (member without grant + toggle off → 403). Each old mode's effective behavior preserved under the new model with the migration-style fixture setup. |
| B — migration reversible + cycle test | Yes | **2/2 PASS** — `test_phase_49a_migration_cycle.py` exercises upgrade-drops-column + the full downgrade-then-upgrade cycle on SQLite. |
| B — Phase 46 cycle test preserved | Yes | **PASS** — scoped to Phase 46's own revision so the downstream Phase 49a drop doesn't break the column-add assertion. |
| C2 — no phase numbers in user-facing copy | Yes | **PASS** — exactly one leak found + fixed; the post-fix grep returns zero matches in user-visible strings. |
| C1 — governance copy reads in plain terms | Yes | **PASS by source** — the rewritten copy describes outcomes ("A single top leader (Steward)", "Let the admin team elect a single top leader") without mode names or mechanic references. Browser QA will confirm rendered behavior post-deploy. |
| D — no storage / timestamp change | Yes | **PASS** — all changes are JSX render hints; no backend code, no schema, no `*_end` / `*_due_at` arithmetic touched. Verified by source diff. |
| PG smoke `--mode both --prior-revision a7c1d8e94521` | Yes | **PASS (all modes)** — fresh-DB bootstrap + upgrade-from-prior both succeed against postgres:16-alpine. The fresh-DB path uses the column-existence guard so the data backfill cleanly skips when the column was never added by `create_all`. |
| Existing-org parity (48 B0 helper) | Yes | **PASS** — B's parity tests model each old mode → new-state combination; existing orgs reach the same effective behavior post-migration. |
| `bash start.sh` prod-like env | N/A | Worker / tick not touched by this pass. The new wrapped action is request-time only; the duration display is FE-only. Confirmed via local boot-mimic: `digest_loop` + `run_one_tick` complete cleanly with the existing tick steps and the Phase 49 `scheduled_elections_opened` counter present (no Phase 49a addition to the tick). |
| Frontend build + bundle hash | Yes | **PASS** — new bundle `index-Bp9L34tG.js` live on prod. |
| Browser verification (Chrome MCP, prod) | Yes | **TBD** — recommend dispatching the QA sub-agent for: (1) admin attempts to disable approval in a multi-admin-enabled org → confirm it goes to ratification queue rather than applying directly; (2) the proposal-creation section renders the new single-toggle UI; (3) governance-mode copy reads plainly + no phase numbers anywhere; (4) duration inputs show the "(N days)" hints. |

---

## Branch + commit state

- Branch: `phase-49a/governance-integrity-clarity`
- Commit on branch: `e3ea48f`-equivalent (the full pass)
- Merge commit on master: `e3ea48f` (no-ff)
- Pushed to origin/master: confirmed
- Railway deploy: `94801911` SUCCESS at 2026-06-02 08:03:52 ET
- Bundle hash on prod: `index-Bp9L34tG.js`
- First post-deploy digest tick: `2026-06-02T12:04:27Z`, `/api/health/scheduler` reports `ticks_since_last_success=0`

---

## Tech debt / followups

- **The `admin_or_steward_only` flag is now used by two action types** (`org.governance_mode_revert` + `org.approval_config_change`). If a third appears it's time to factor into a `tier_required: Optional[str]` field on `ActionDefinition`.
- **`_is_weakening_change` window-handling**: per spec D-cluster discussion, the conservative interpretation is "window changes are NOT gated" (decreases could rush ratifiers but the threshold itself is the gate; increases simply delay). If org operators report concern about a single admin shortening the window to pressure approvers, gate window decreases too — small follow-up.
- **Phase-leak-sweep automation**: the C2 sweep was manual grep. A small CI lint that fails on user-visible `Phase N` references in `*.jsx` / `*.js` strings would close the class. Not urgent — the rule is now codified in the closeout + the one instance is fixed.
- **Pending-actions surface in PATCH response**: when the PATCH route routes a multi_admin_approval change to ratification, the response shape is still `OrgOut` with the old config visible. A future polish could augment OrgOut with a `pending_approval_config_change` field or similar so the FE can show "your change is pending ratification" without polling `/admin/pending-actions`. Not blocking.
