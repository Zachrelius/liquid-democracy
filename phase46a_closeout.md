# Phase 46a — Cosign Refinements + Serializer-Coverage Guard — Closeout

**Spec:** `phase46a_cosign_refinements_spec.md`
**Branch:** `phase-46a/cosign-refinements` → merged `--no-ff` to master
**Deployed:** Railway prod, bundle `index-DBkO-try.js`
**Date:** 2026-06-01

---

## Overall

**SHIPPED.** Phase 46a refines the Phase 46 cosign mechanism in three ways:
1. **Cosignatures are delegation-weighted** (Item 1) — a cosign carries the weight the signer would carry voting on the proposal, not a flat 1.
2. **Threshold is a window-end gate, not an immediate trigger** (Item 2) — the proposal stays in `deliberation` for the full window; the worker decides advance-or-expire at `cosign_expires_at` against the live weight.
3. **Serializer-coverage test** (Item 3) — closes the recurring `OrgOut` model-vs-response gap that needed Phase 45a hotfix #1 and Phase 46 hotfix #1. Also added a CLAUDE.md convention so the gap is a code-review/CI-time catch, not a prod-QA-time hotfix.

No migration — reuses existing storage (the threshold column's *semantic* changed from headcount to weight; its type didn't).

---

## Per-cluster status

| Cluster | Status | Notes |
|---|---|---|
| Item 1 — Delegation-weighted cosignatures | DONE | New `cosign.cosign_weight(db, proposal)` + `resolve_cosign_weight_for_signers(db, proposal, signer_ids)`. Reuses the platform's tally/delegation engine — builds the standard `ProposalContext` via `DelegationService._build_context`, then overrides `direct_ballots` / `direct_votes` with synthetic ballots for ONLY the signers so the resolver dispatches as if those signers had voted. Counts users whose `resolve_vote_pure` lands on a signer's `cast_by_id`. **No parallel delegation implementation** — the engine's pure resolver does the work; this module just shapes the context. Multiple signers don't double-count overlapping delegators (set membership on `cast_by_id`). Author's implicit signature now carries the author's resolved weight per D3 (the implicit row insertion is unchanged from Phase 46; weight just resolves higher because the author has inbound delegators). `threshold_met` switched from `signature_count >= threshold` to `cosign_weight >= threshold`. Live re-evaluation per D1.4 (no per-signature snapshot — context is rebuilt against the current graph each call). |
| Item 2 — Window-end gate, not immediate | DONE | `cosign_proposal` POST route no longer calls `_advance_cosign_to_voting` mid-window. The worker (`sustained_majority_worker.resolve_due_cosign_proposals`) performs ONE unified check at `cosign_expires_at`: `weight ≥ threshold` → advance via the existing `_advance_cosign_to_voting` helper (downstream identical to manual advance); else → `expired_unsigned`. Live, not latched (D2.3) — a proposal that crossed mid-window and dropped back under (via withdrawal or delegation change) fails at window-end. `_advance_cosign_to_voting` signature loosened: `background_tasks: Optional[BackgroundTasks]` + `actor_id: Optional[str]` so the worker can call it without a FastAPI request scope. Audit events updated: `proposal.cosign_threshold_met` now fires at window-end advancement (not first crossing); `proposal.cosign_window_closed_unmet` replaces `proposal.cosign_expired`. The Phase 46 `expire_due_cosign_proposals` is kept as a backward-compat shim over `resolve_due_cosign_proposals` so old call sites keep working. |
| Item 3 — Serializer-coverage test + CLAUDE.md convention | DONE | New `tests/test_phase_46a_orgout_serializer_coverage.py` with an explicit `_MUST_SURFACE_FIELDS` allow-list — adding a new FE-facing `Organization` field is now a three-line change (add to `OrgOut`, populate in `_org_to_out`, append to the allow-list). Two additional tests assert (a) the steward's `user_permissions` includes the OWNER_ONLY_KEYS via the Phase 45a hotfix enrichment loop, and (b) the default values of mode fields are correct. **Verified the test would catch the regression** by temporarily commenting out `governance_mode` from `OrgOut` and running the test: 2 of 4 coverage tests failed loud with a clear remediation message. Restored the field. `CLAUDE.md`'s Testing strategy section now carries the standing convention: any new `Organization` field the FE reads ships with `OrgOut` + the coverage assertion in the same pass. |
| Phase 46 test updates | DONE | Three Phase 46 tests asserted 46's now-removed behavior contract: `test_threshold_met_advances_to_voting` (was asserting immediate advance), `test_expiry_emits_audit_events` (was asserting the renamed `proposal.cosign_expired` event), `test_expiry_skips_proposal_at_or_above_threshold` (was asserting the worker SKIPS at-threshold proposals — 46a says it advances them). Rewrote in place to match 46a's contract: signing alone does NOT advance; the worker advances at window-end; audit event name is `proposal.cosign_window_closed_unmet`. Renamed where appropriate (`test_threshold_met_advances_to_voting` → `test_threshold_met_does_NOT_immediately_advance`; `test_expiry_skips_proposal_at_or_above_threshold` → `test_window_end_at_threshold_advances_to_voting`). |
| FE weight UI | DONE | `ProposalDetail.jsx` Gathering Signatures panel renders BOTH the signer count AND the live weight: *"Signed by 4 members · 8.5 of 12 weight needed at window-end"* with a one-line explainer about how weight resolves through delegation. Removed the "advance immediately at threshold" framing — copy now reflects the window-end gate. `ProposalManagement.jsx` create-form advisory updated to say *"need {N} weight of cosign support (you count for yourself plus everyone who delegates a relevant topic to you)"* with the window-end framing. |

---

## Verification matrix

| Check | Required | Result |
|---|---|---|
| Backend pytest (full) | Yes | Targeted regression sweep: **346 PASS / 1 FAIL** (the 1 is the unchanged known-baseline `test_parent_org_admin_sees_full_25_on_sub_org_via_implicit_power`). Phase 46a new + updated tests: 11 cosign refinement + 6 serializer coverage + 3 updated Phase 46 = 20 PASS. The delegation engine suite (`test_delegation_engine.py`) included in the sweep also passes — confirming the cosign-weight resolver doesn't perturb the tally engine's behavior. |
| Cosign-disabled / open-mode regression | Yes | **PASS** — Phase 46 `TestOpenModeRegression` × 3 plus the cosign-not-gated branch in `_build_proposal_out` (where `_cosign_weight` returns 0 without hitting the resolver). |
| Weighted-threshold behavior (Item 1) | Yes | **PASS** — `TestCosignWeight` × 5: direct signer = 1; delegate carries N inbound delegators = 1+N; topic-scoped delegation only counts on matching-topic proposals; multiple signers don't double-count overlap; live recomputation picks up post-signing graph changes (both adds and removes). |
| Window-end gate (Item 2) | Yes | **PASS** — `TestWindowEndGate` × 6: signing alone does NOT advance mid-window; window-end advances at-or-above threshold; window-end expires when unmet; **drop-back-under-then-window-close → expires** (not latched, per D2.3); `proposal.cosign_threshold_met` audit fires at window-end advancement; `proposal.cosign_window_closed_unmet` audit fires on unmet expiry. |
| **`bash start.sh` prod-like env** | **Yes** | **PASS** — prod-mimic sequence (create_tables → alembic stamp head → `python -m sustained_majority_worker --once`) runs end-to-end with no errors. "Worker exited cleanly." The new `resolve_due_cosign_proposals` path is wrapped in try/except in the tick so any unexpected exception is logged without crashing the worker (start.sh's `set -e` would otherwise take the container with it). |
| Serializer-coverage test (Item 3) | Yes | **PASS** — `TestOrgOutSurfaceContract` × 4. Belt-and-suspenders: temporarily commenting out `governance_mode` from `OrgOut` made 2 of the 4 coverage tests fail with the expected remediation message ("`_org_to_out` is missing FE-facing field(s): ['governance_mode']. Add the field to schemas.OrgOut + populate it in routes.organizations._org_to_out (and update _MUST_SURFACE_FIELDS in this test file in the same pass)"). Restored. The same test would have caught Phase 45a hotfix #1 + Phase 46 hotfix #1 at CI time. |
| Migration | Confirm | **None.** Threshold semantics changed (headcount → weight) but the storage type (Integer) is unchanged. The existing column carries the new meaning without a migration. Explicit confirmation: no `alembic upgrade` needed for this pass. |
| Frontend build + bundle hash | Yes | **PASS** — new bundle `index-DBkO-try.js`, CSS unchanged. PWA precache 23 entries / 2077.60 KiB. |
| Browser verification (Chrome MCP, prod) | Yes | TBD post-deploy. Watch the PWA cache (re-flagged from 46 closeout). |
| Bundle hash changed + backend non-502 post-deploy | Yes | TBD post-deploy. |

---

## Files added/modified

**New backend (2 tests):**
- `backend/tests/test_phase_46a_cosign_refinements.py` (11 tests: 5 weight resolution + 6 window-end gate).
- `backend/tests/test_phase_46a_orgout_serializer_coverage.py` (6 tests: 4 coverage contract + 2 belt-and-suspenders).

**Modified backend (4):**
- `backend/cosign.py` — new `signer_ids_for`, `cosign_weight`, `resolve_cosign_weight_for_signers` (reuses delegation engine, doesn't reimplement). `threshold_met` switched to weight.
- `backend/routes/proposals.py` — `cosign_proposal` POST no longer advances mid-window; `_advance_cosign_to_voting` signature loosened (Optional background_tasks + actor_id) so the worker can call it; `_build_proposal_out` surfaces `cosign_weight` via `_cosign_weight` helper.
- `backend/schemas.py` — `ProposalOut.cosign_weight: int = 0`.
- `backend/sustained_majority_worker.py` — new `resolve_due_cosign_proposals` (unified window-end gate); `expire_due_cosign_proposals` becomes a backward-compat shim. Tick logging shows advanced + expired counts.

**Modified frontend (2):**
- `frontend/src/pages/ProposalDetail.jsx` — Gathering Signatures panel shows count + weight + window-end framing.
- `frontend/src/pages/admin/ProposalManagement.jsx` — create-form advisory uses weight + window-end framing.

**Modified docs (1):**
- `CLAUDE.md` — Testing strategy section gained the "new Organization field → OrgOut + coverage test in the same pass" convention with the three-step recipe.

**Modified Phase 46 tests (1):**
- `backend/tests/test_phase_46_cosign_gated_proposals.py` — three tests rewritten to match Phase 46a's contract (no immediate advance; window-end gate; renamed audit event).

---

## Default-mode (`open`) regression guarantee

Orgs in `open` mode never see a cosign-gated proposal (`is_cosign_gated` is always False on those proposals), so `_cosign_weight` returns 0 early and the worker's window-end gate never picks them up (filter requires `is_cosign_gated == True`). All Phase 46 / 45a / 45b tests pass without modification. `ProposalOut.cosign_weight = 0` for non-cosign-gated proposals; the FE only renders the panel when `is_cosign_gated && status === 'deliberation'`, so non-cosign proposals are visually unchanged.

---

## Deferred / out of scope

- Per-proposal or per-category cosign overrides — still a later refinement.
- Anything election-specific — Phase 47.
- Weighted *voting* — the tally engine is unchanged; only cosign weight uses the engine's resolution.

---

## Tech debt / followups surfaced

- **Phase 47 election-trigger consumption**: 47 Stage 3 (per the arc passdown) consumes cosign as an election trigger. The corrected weighted/window-end version is what 47 sees — the spec called this out as the only ordering constraint and it's now satisfied.
- **`expire_due_cosign_proposals` backward-compat shim**: kept for Phase 46-era tests + any external integrations that called it by name. New code should prefer `resolve_due_cosign_proposals` which returns both counts. The shim can be removed after Phase 47 lands if no callers remain.
- **`_advance_cosign_to_voting` optional background_tasks**: the helper now accepts `None` for the worker call path; `_emit_proposal_status_notifications` was already tolerant of this (it wraps each emit in try/except). If a future refactor extracts the helper out of routes/proposals.py, keep the optional-background_tasks contract — it's load-bearing for the worker path.
- **Live weight is recomputed per call**: each `cosign_weight` call rebuilds the ProposalContext (one DB pass per call). Acceptable for cosign-gated proposals (gathering windows are hours-to-days, signature events are infrequent). If cosign gathering scales to many concurrent proposals, consider caching the resolved weight per proposal+graph-version. Not a problem today.

---

## Branch + commit state

- Branch: `phase-46a/cosign-refinements` (left alive locally).
- Commit on branch: TBD on commit.
- Merge commit on master: TBD.
- Pushed to origin/master: TBD.
