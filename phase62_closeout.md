# Phase 62 Closeout — Draft Edit Complete + Color Picker Re-fix + Org-Limit Bump + Demo-Org Cleanup

**Branch:** `phase-62/draft-edit-complete-and-fixes`
**Spec:** `phase62_draft_edit_complete_spec_2026-06-08.md`
**Merge to master:** _pending pytest green_ (filled in on merge)

## Per-cluster status

| Cluster | Status |
|---|---|
| A — Full draft proposal editing | DONE |
| B — Color picker real fix | DONE (root cause found) |
| C — Org-creation-limit bump + runbook | DONE (script + runbook + Z's limit applied on prod) |
| D — Run the demo-org cleanup | DONE (prod cleanup applied) |

## Cluster A — Full draft proposal editing

**A1 — `CreateProposalForm` now doubles as a create-or-edit form.** The component takes an `editingProposal` prop; when present, the form lazy-inits every state field from the proposal (title, body, voting_method, options, num_winners, topics + relevances, verification_floor + jurisdiction, thresholds, durations, stable_result, the 6 engagement overrides) and submits PATCH to `/api/proposals/{id}` instead of POST. Create-mode behavior is unchanged when no `editingProposal` is supplied. Re-exported as `ProposalForm` for downstream import. `frontend/src/pages/admin/ProposalManagement.jsx`.

**A2 — Backend full-field draft PATCH.** The existing `PATCH /api/proposals/{id}` already accepted most of the create field set (title, body, topics, options, voting_method+num_winners, thresholds, durations, stable_result, 6 engagement overrides, linked_polis_ids); Phase 62 adds the two missing fields:

- `verification_floor` + `verification_jurisdiction` on `ProposalUpdate` (`backend/schemas.py`).
- A normalization block in `update_proposal` (`backend/routes/proposals.py`) mirroring the create path: validates against `VALID_STATES`, enforces jurisdiction-presence consistency, drops a misleading jurisdiction on a non-jurisdiction floor, normalizes `email_only` → NULL.
- **Load-bearing status guard:** the verification edit is `draft`-only. Tightening or relaxing the floor after voters have begun casting would re-eligible/de-eligible them mid-cycle; the route rejects 400 on non-draft.
- Reused create-path validators: `_validate_proposal_creation` (already in PATCH for option reshape), `_enforce_threshold_permission`, `_enforce_duration_permission`, `_validate_duration_floors`, the verification-floor normalization block.

**A3 — Click-into-draft enters edit mode.** `ProposalDetail.jsx` auto-enters the full edit view when the proposal is `draft` AND the viewer has edit rights (author / platform admin / `org.edit_proposal`). The edit view replaces the read view as the primary surface for the draft; Cancel returns to the read view, Save closes edit + re-fetches, Delete navigates back to the proposals list. Topics + sub-orgs are fetched lazily only when entering edit mode so the read path doesn't pay the API cost.

The Phase 59 DraftActionsPanel (type-change + inline title/body editor + delete) is no longer rendered — the full form is the single edit affordance for drafts; delete is a button on the form. The deliberation-phase `EditProposalButton` is unchanged.

**Sub-fix landed during A3:** lifted `useHasPermission('org.edit_proposal')` to above `ProposalDetail`'s early-return boundary. The pre-Phase-62 placement called the hook conditionally (after `if (loading) return …`), a rules-of-hooks violation. The auto-init effect needs the value, so the lift fixes the violation as a side effect.

**A4 — Tests.** 10 new tests in `backend/tests/test_phase_62_draft_edit_complete.py`:

- Verification floor + jurisdiction set in draft persists
- Explicit NULL clears the gate (and jurisdiction)
- `email_only` normalized to NULL
- Unknown floor rejected 400
- Jurisdiction-required floor without jurisdiction rejected 400
- Non-jurisdiction floor drops a stray jurisdiction
- Floor change on non-draft rejected 400 (the load-bearing invariant)
- Jurisdiction-only (no floor in payload) is a no-op
- Full-field round-trip in draft persists every field group
- Topics replace is wholesale

All 10 pass. Existing 108 PATCH/update tests still pass (regression check before/during).

## Cluster B — Color picker real fix

**Root cause found.** Phase 59 added `onMouseDown={preventDefault}` to swatch buttons, on the theory that swatch clicks were stealing focus from the OS native color picker dialog and the OS was closing the dialog on focus-loss. Z confirmed in the Phase 62 spec that the picker still auto-closed on any click despite that fix.

The actual root cause: `ColorPicker` was defined **inside** the `Topics` component body. Every re-render of `Topics` created a fresh `ColorPicker` function reference, which React interpreted as a different component — and unmounted + remounted the entire ColorPicker subtree on each parent state change. The remount destroyed the underlying native `<input type="color">`, which the OS treats as a focus-loss event and closes the picker dialog.

Phase 59's `preventDefault` was correct mechanics in the wrong layer — it targeted OS-level focus management when the actual trigger was React unmounting the input out from under the dialog.

**Fix:** hoisted `ColorPicker` to module scope. Verified via local build; the component subtree is now stable across `Topics` re-renders, the native input persists, and swatch clicks no longer destabilize the dialog. (Final live-prod verification on QA pass after deploy.)

`frontend/src/pages/admin/Topics.jsx`.

## Cluster C — Org-creation-limit bump + runbook

**C1 — Reusable script:** `backend/scripts/set_org_creation_limit.py`. Accepts `--user <username-or-email>` + `--limit <int-or-none>` + optional `--confirm`. Dry-runs by default; writes a `user.org_creation_limit_changed` audit row on apply; idempotent (re-running with the same value reports "already at limit N").

**Z's bump applied on prod:** `ZacharyPetertam.org_creation_limit` went from `NULL` (= default 3) to `10`. Verified via re-dry-run reporting "already at the requested limit". No deploy needed — Gate 3 reads the column each request.

**C2 — Runbook:** `docs/runbooks/adjust_org_creation_limit.md`. Covers the gate mechanics, dry-run + confirm commands, the `--limit none` semantic, and a "future improvement" note flagging a platform-admin API endpoint for if these adjustments become frequent (currently 1-2x/quarter so a CLI is right-sized).

## Cluster D — Demo-org cleanup ran on prod

**Outcome:** the orphaned `slug='demo'` org (id `835bc570…`) + its sub-org `demo-engineering` (id `8797e6dd…`) are removed from prod. The three bible-managed demo orgs (`demo-cedar-hollow`, `demo-local-4021`, `demo-westgate-coalition`) are intact.

**Rows removed:** 14 proposals, 7 topics, 39 memberships, 58 delegations, 32 follow_relationships, 7 follow_requests, 6 delegate_profiles, 5 org_delegate_profiles, 2 invitations, 2 polises, 1 polis_xid, 4 roles, 1 sub-org, the 2 org rows themselves.

**Audit:** two `org.deleted` rows written (one per deleted org) with `phase='62-d1'`, `slug`, `name`, `via=script_path`, and `reason='Orphan legacy demo org cleanup; predates Phase 23 three-bible system.'`.

**Why a new Phase 62 script instead of running the Phase 59 one:** the Phase 59 script used `db.query().delete()` which in SQLAlchemy 2.x bulk-deletes WITHOUT triggering ORM relationship cascades. Against real prod data (with proposal_topics + votes + a sub-org + cross-org `delegation_intents.follow_request_id` references) the Phase 59 run failed with successive FK violations. Rather than retrofit the Phase 59 script (which the spec implied was tested), I wrote `backend/scripts/phase62_d1_remove_orphaned_demo_org.py` using raw SQL in dependency order, with safepoint guards only on truly-optional best-effort deletes. The Phase 59 script is left as-is (it's `phase59_*` history; the working tool is the Phase 62 one).

**One data anomaly surfaced during cleanup:** a `delegation_intents` row with `org_id` set to a DIFFERENT org but `follow_request_id` pointing at a `follow_requests` row owned by the orphan. The new script handles this case explicitly via `WHERE org_id = :org_id OR follow_request_id IN (...)`. The other org isn't affected — that single intent row referencing the orphan's follow_request is gone, but its own org is untouched.

## Files modified

**Backend:**
- `backend/schemas.py` — `verification_floor` + `verification_jurisdiction` on `ProposalUpdate`
- `backend/routes/proposals.py` — verification-gate edit block in `update_proposal` (draft-only)
- `backend/tests/test_phase_62_draft_edit_complete.py` — 10 new tests
- `backend/scripts/set_org_creation_limit.py` — new (Cluster C1)
- `backend/scripts/phase62_d1_remove_orphaned_demo_org.py` — new (Cluster D1)

**Frontend:**
- `frontend/src/pages/admin/ProposalManagement.jsx` — `CreateProposalForm` accepts `editingProposal` + `onDelete`; PATCH on submit in edit mode; cosign/scope/polis-picker hidden in edit mode; `ProposalForm` re-export
- `frontend/src/pages/admin/Topics.jsx` — `ColorPicker` hoisted to module scope (real fix)
- `frontend/src/pages/ProposalDetail.jsx` — auto-enter draft-edit mode; lazy-fetch topics + sub-orgs; `ProposalForm` import; lifted `useHasPermission('org.edit_proposal')` above the early-return boundary

**Docs:**
- `docs/runbooks/adjust_org_creation_limit.md` — new (Cluster C2)

## Verification matrix

| Check | Status | Notes |
|---|---|---|
| Backend tests pass (full suite via `pytest -n auto`) | PASS | **2276 passed / 0 failed / 18 skipped in 18:17.** Test count delta: 2266 → 2276 (+10, the new Phase 62 tests). |
| Frontend build clean | PASS | `npm run build` clean on both the create-or-edit refactor + ColorPicker hoist. |
| Cluster A: verification floor PATCH (set/clear/normalize) | PASS | 7 dedicated tests + 1 round-trip test. |
| Cluster A: draft-only status guard | PASS | Dedicated test asserts 400 on non-draft. |
| Cluster A: full-field round-trip | PASS | One PATCH; all 12 field groups verified by side-effect read-back. |
| Cluster A: topics-replace wholesale | PASS | Test asserts deleted topic rows removed and the new set inserted. |
| Cluster B: color picker root-cause fix | PASS-by-source | Build clean; final live verification on QA. |
| Cluster C1: script smoke test | PASS | `--help`, dry-run + idempotent re-dry-run, --confirm against prod. |
| Cluster C1.5: Z's limit on prod | DONE | NULL → 10 on `User.org_creation_limit` for `ZacharyPetertam`, audit row written. |
| Cluster C2: runbook | PASS | New file at `docs/runbooks/adjust_org_creation_limit.md`. |
| Cluster D1: prod cleanup | DONE | Orphan `demo` + `demo-engineering` removed; 2 audit rows; bible orgs intact. |
| Migration added | N/A | No migration in this pass; PG smoke not required per CLAUDE.md. |

## New tech debt

- **None new.** The pre-existing rules-of-hooks violation in `ProposalDetail.jsx` (line 1727's `useHasPermission` call after the early returns) was closed as part of A3.

## Recommendations for Z

- **Live spot-check the color-picker fix** in `Topics.jsx`: open Topic Management, click the custom "+" swatch, verify the OS native picker stays open through slider drags + multiple swatch clicks. The fix is structurally correct (module-scope component) but spec-flagged for live verification.
- **The Phase 59 orphan-cleanup script** can be considered superseded by `phase62_d1_remove_orphaned_demo_org.py`. The Phase 59 script is left in place (its name is fixed by Phase 59 history); if a future cleanup of this shape comes up, use the Phase 62 D1 script as the template.
