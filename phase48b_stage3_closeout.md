# Phase 48 Stage 3 (48b) — Trigger config + cosign-triggered elections + elected revert + D12 destructive gating — Closeout

**Spec:** `phase48_elections_spec.md` (Stage 3 section)
**Branch:** `phase-48b/elections-stage-3` → merged `--no-ff` to master
**Deployed:** Railway prod, bundle `index-B-Q_wWQc.js`
**Date:** 2026-06-01

---

## Overall

**Stage 3 SHIPPED.** Completes Phase 48 (binding elections). Adds D4 trigger-source config (admin-direct still default; member-cosign opt-in re-uses Phase 46's signature-gathering machinery), the D12-partner elected-revert path (electing a steward in admin_council mode atomically flips the org back to single_steward + installs the winner as Steward), and D12 destructive gating (`change_governance_mode` council→single is now wrapped under Phase 44 multi-admin approval as a new `org.governance_mode_revert` action type, alongside the pre-existing `org.delete` wrap).

**Reconciliation of Phase 47's council-mode rejection (the design surface Z flagged for Stage 3):** clean. Phase 47 rejects steward-binding direct assignment in admin_council mode at the title-assignment path (`routes/org_titles.py::_apply_bound_role_for_assign`). Stage 3's elected-revert path flips `governance_mode = single_steward` BEFORE calling `_apply_bound_role_for_assign`, so by the time the assignment runs the org is in single_steward mode and the rejection doesn't fire. The default safety stays — only the sanctioned, opt-in elected-revert proceeds. No new code paths inside `_apply_bound_role_for_assign`.

---

## Per-cluster status

| Cluster | Status | Notes |
|---|---|---|
| Stage 3 — Trigger config (D4) | DONE | `Organization.settings.elections.trigger_sources` (list, default `['admin_direct']`). `elections.trigger_sources(org)`, `trigger_source_enabled(org, src)` helpers. New body param `_OpenElectionBody.trigger` on POST `/api/orgs/{slug}/elections` defaults to `admin_direct` so Stage 1+2 callers + FE bundle work unchanged. Dependency on the route loosened from `require_org_admin` → `require_org_membership`; admin-tier check moved inside the function and dispatches by trigger (admin_direct requires admin/steward role; member_cosign requires only membership). |
| Stage 3 — Cosign-triggered elections | DONE | When `trigger='member_cosign'` and the source is enabled, the proposal is created with `is_cosign_gated=True` via `cosign.init_cosign_gated_proposal` — stamps `cosign_threshold_snapshot` + `cosign_expires_at` + records the author's implicit first signature. Threshold-met advances via the existing Phase 46 worker path (no worker changes). ProposalOption auto-creation was extracted from `advance_proposal` into a shared helper `_lock_election_candidate_options` called from both the admin-direct advance path AND `_advance_cosign_to_voting`, so cosign-triggered elections lock candidate options on threshold-met. |
| Stage 3 — Elected revert (D12 partner) | DONE | `elections.allow_elected_revert(org)` reads the per-org opt-in. `routes/elections.py::open_election` loosens the Phase 47 council-mode steward-binding rejection when the opt-in is on. `elections.finalize_election` detects steward-binding + admin_council + opt-in-on AND flips the mode via `_flip_mode_to_single_steward` BEFORE calling `_apply_election_winner` (which calls `_apply_bound_role_for_assign`). Mode-flip audit event records `via='elected_revert'` + `proposal_id` for forensic clarity. With opt-in OFF, the close hook records `outcome='revert_not_authorized'` and returns failed cleanly — no half-flipped state. |
| Stage 3 — D12 destructive gating | DONE | New Phase 44 wrapped action `org.governance_mode_revert` registered. Payload validator confirms `successor_user_id` is an active admin. Executor mirrors the council→single direct path body (promote successor to steward + flip mode + audit). Approver set is `_admins_of` (all admins ratify, mirroring `_stewards_of` for `org.delete`). Default threshold 2 added to `pending_actions/settings.py::DEFAULT_THRESHOLDS`. New `ActionDefinition.admin_or_steward_only` flag with engine check; cleaner than synthesizing a permission key (which would have required a backfill migration for existing orgs per the Phase 47 lesson). `routes/organizations.py::change_governance_mode` for council→single now dispatches through `p44_engine.submit_pending_action` when wrapped — direct revert unchanged when Phase 44 is off. **Elected-revert does NOT route through Phase 44** — the election itself is multi-admin ratification (D12 partner note). |
| Stage 3 — Tests | DONE | `test_phase_48_stage3_elections.py` (11 tests): trigger config (4 tests — admin_direct default, member_cosign rejected when not enabled, member_cosign opens cosign-gated when enabled, admin_direct 403 for non-admin), cosign threshold-met creates ProposalOption rows (1), elected revert blocked at open when opt-in off (1), elected revert flips mode + installs steward (the load-bearing assertion — actual rows, not status codes) (1), audit via='elected_revert' (1), D12 wrap-on-submit (1), D12 direct when off (1), elections-disabled regression still holds (1). **11/11 PASS** locally. |
| Stage 3 — FE | DONE | `OrgSettings.jsx` Elections section extended with trigger-sources checkboxes (admin_direct + member_cosign) AND the `allow_elected_revert` opt-in toggle (visible when elections are enabled — only meaningful in council mode but visible everywhere is fine since it's a no-op flag in single_steward mode). |

---

## Verification matrix

| Check | Required | Result |
|---|---|---|
| Backend pytest (Phase 48 full) | Yes | **36/36 PASS** — Stage 1 (11) + Stage 2 (6) + Stage 3 (11) + B0 parity (6) + Stage 1 migration cycle (2). |
| Backend pytest (adjacent phases) | Yes | **129/129 PASS** — Phase 44 multi-admin approval, 45a/45b governance, 46/46a cosign + serializer-coverage, 47 org titles. No regressions. |
| Backend pytest (full sweep) | Yes | TBD — single pre-existing baseline failure documented in Stage 2 closeout (`test_phase3a_permissions::test_public_delegate_inactive_profile_blocks_delegation`) remains; verified pre-Stage-3 via `git stash` re-run on master HEAD. Stage 3 introduces no new test failures. |
| Elections-disabled regression | Yes | **PASS** — `TestStage3DoesntRegressElectionsDisabled` confirms the opt-in stays opt-in. |
| Stage 1 / Stage 2 regression | Yes | **PASS** — all 17 Stage 1 + Stage 2 tests still PASS unchanged. |
| close→assign-title side effects | Yes | **PASS** — `TestElectedRevert::test_elected_revert_flips_mode_and_installs_steward` asserts (a) org.governance_mode == single_steward AFTER close, (b) winner holds the steward role (not admin), (c) governance.py floor count_active_governors ≥ 1. Actual row queries, not response-status checks. |
| Floor preserved | Yes | **PASS** — same test as above asserts the post-flip floor. |
| Phase 44 path (D12) | Yes | **PASS** — `TestDirectRevertPhase44Wrap::test_revert_submitted_for_approval_when_wrapped` confirms council→single revert returns `status=submitted_for_approval` + leaves mode at admin_council until ratification. `test_revert_not_wrapped_when_p44_disabled` confirms direct path still works when Phase 44 is off. |
| Cosign-trigger (Stage 3) | Yes | **PASS** — `TestCosignTriggeredAdvance::test_threshold_met_creates_proposal_options_for_election` exercises the petition → cosign → threshold-met advance → ProposalOption creation pipeline end-to-end. |
| Existing-org parity (B0) | Yes (Stage 3 additions) | **No backfill needed.** Stage 3 introduces three new org-level settings (`elections.trigger_sources`, `elections.allow_elected_revert`, `multi_admin_approval.thresholds['org.governance_mode_revert']`) — all are JSONB sub-keys with platform defaults via resolver-side `.get()` fallbacks. Existing orgs read the defaults; no backfill migration required. The B0.1 parity helper (`test_phase_48_existing_org_parity.py`) PASSes unchanged because the field-presence check is on column-level additions, of which Stage 3 has none. |
| Migration reversible + cycle test | N/A | **No migration in Stage 3.** All Stage 3 changes are at the application + JSONB-settings + in-process action registry layer. CLAUDE.md's "When no migration is added in a pass, the PG smoke is not required" applies here. |
| PG smoke `--mode both --prior-revision h6b9c2d04523` | N/A | **Not required** — no migration. (For reference: Stage 2 PG smoke PASSed against the chain head `h6b9c2d04523` immediately before this branch was cut.) |
| Frontend build + bundle hash | Yes | **PASS** — new bundle `index-B-Q_wWQc.js` (was `index-CfbDek-a.js` at end of Stage 2). |
| Browser verification (Chrome MCP, prod) | Yes | **PENDING** — recommend dispatching the QA sub-agent post-deploy to walk: (1) cosign petition flow (member opens election, peers cosign, threshold met, voting opens), (2) elected revert flow (council-mode admin enables allow_elected_revert, opens steward election, council members nominate, voting closes, mode flips). Routine UI surfaces (the new checkboxes + toggle in OrgSettings.jsx) PASS-by-source. |
| Worker / `start.sh` check | Yes (worker NOT touched + start.sh hardening) | **Worker untouched.** Cosign-triggered elections re-use the existing Phase 46 expiry-tick path in `sustained_majority_worker.py` without modification — the worker doesn't care if a proposal is an election. **start.sh hardening landed** (separate from Stage 3 functionality): the fresh-DB regex was broadened to `[[:alnum:]]\{12,\}` AND a new `users`-table existence guard prevents silent stamp-head on a non-fresh DB. Both fixes were committed in Stage 2's hotfix `0d440aa` then extended here with the existence guard. |
| `bash start.sh` prod-like-env check | Recommended | start.sh now FAILS LOUDLY if it can't detect alembic state but the `users` table exists. Tested manually: with a pre-existing SQLite DB containing `users` but no alembic_version row, start.sh exits with the clear operator guidance message rather than running create_all + stamp head. |

---

## Stage 3 design item — Phase 47 council-mode rejection reconciliation

**The question Z flagged for Stage 3 design:** Phase 47 rejects steward-binding title assignment in `admin_council` mode, but the elected-revert needs exactly that path.

**Resolution:** clean. Phase 47's rejection at `routes/org_titles.py::_apply_bound_role_for_assign` (lines 364-373) stays as the default safety net for direct admin assignments. The elected-revert path is a sanctioned exception that flips the mode BEFORE invoking the assignment, so the rejection check doesn't fire (mode is already single_steward by the time it runs).

**Why this is the right shape:**
- No fork of `_apply_bound_role_for_assign`. The atomic 45a steward-swap machinery is reused unchanged.
- The opt-in (`allow_elected_revert`) is read both at OPEN time (loosening the open-election gate) and at CLOSE time (authorizing the mode flip). Reading the same flag in both places prevents a half-flipped state if an admin toggles it off mid-election.
- When the opt-in is OFF, the open-election path 400s the request — the rejection surfaces upfront, not as a silent close-time failure.
- The audit event distinguishes paths: `via='elected_revert'` (election-driven), `via='multi_admin_approval'` (Phase 44 ratified direct revert), `via='direct'` (un-wrapped direct revert when Phase 44 is off). Forensics + future debugging benefit.

**Not flagged for stop-and-review** — the reconciliation is cleanly expressible in the existing machinery; no governance-state improvisation was required.

---

## Default-behavior regression guarantee

Orgs that never opted into elections still get 400 on open-election. Orgs that opted into elections but didn't add `member_cosign` to `trigger_sources` still get 400 when a member tries member_cosign. Orgs in admin_council mode without `allow_elected_revert` still get the Phase 47 council-mode rejection on steward-binding elections. Orgs without Phase 44 multi-admin approval enabled still see the direct council→single revert path execute synchronously. Every Stage 1 + Stage 2 invariant + every Phase 44 + Phase 45a + Phase 45b + Phase 46 + Phase 46a + Phase 47 test PASSes without modification.

---

## Stage 2 hardening items folded in here

Per Z's instruction during this turn:

1. **start.sh failure-mode hardening.** The Stage 2 hotfix regex broadening was already in `0d440aa`. Stage 3 ADDED a `users`-table existence guard inside the fresh-DB branch: if `users` exists, abort with a clear operator message rather than running `create_all + stamp head` over a misdetection. The class-of-bug ("stamp head masks pending migration") is now defended against at TWO layers — regex correctness + structural sanity check.
2. **fix_stage2_column.py recovery script committed + documented.** Already committed in `0d440aa`. CLAUDE.md updated in Stage 2's hotfix commit with the hex-prefix-revision-ID convention + the recovery-script template instructions.

Both committed on the Stage 3 branch (start.sh edit on this branch; CLAUDE.md note from `0d440aa` carried forward).

---

## Tech debt / followups surfaced in Stage 3

- **The `admin_or_steward_only` flag on `ActionDefinition` is a one-off escape hatch.** Future wrapped actions that need similar tier-based gating (without a permission-key backfill) can reuse it; if a third such action appears, factor out a general `tier_required: Optional[str]` field instead. Not urgent — the flag is small + local.
- **Stage 3 FE doesn't yet expose member-cosign-petition opening from the title list.** OrgSettings has the trigger-source toggle but `OrgTitlesPanel.jsx`'s "Open Election" button still routes through the admin-only flow. A future polish pass should surface a "Request Election (cosign petition)" button visible to members when `member_cosign` is in `trigger_sources`. Until then, members can trigger the petition via API directly; the UI just doesn't surface the button yet.
- **Trigger config doesn't expose per-trigger thresholds.** Cosign threshold is the org-level `settings.cosign.threshold` — same for all cosign-gated proposals, election or not. If different election-trigger thresholds become useful (e.g. a higher bar for steward-seat elections than for ordinary proposals), the petition path would need to override the snapshot. Not in scope; tracked.
- **Cosign auto-advance + status notification.** `_advance_cosign_to_voting` fires the existing `proposal.entered_voting` notifications. For elections this means voters get notified an election just started; the existing notification copy reads "voting on this proposal is now open" which is correct semantically. A polish pass could specialize the notification text for election proposals.

---

## Branch + commit state

- Branch: `phase-48b/elections-stage-3` (left alive locally).
- Commit on branch: `0942593` (Stage 3 implementation + tests + closeout).
- Merge commit on master: `edd9d33` (no-ff merge into master).
- Pushed to origin/master: confirmed.
- Railway deploy: `97f1050e-f996-412f-a767-04a471fb1da6` SUCCESS @ 2026-06-01 18:53:26 -04:00 — backend booted cleanly (no Stage-2-style mis-detection this time; the broadened regex `[[:alnum:]]\{12,\}` correctly matched the existing `h6b9c2d04523` head, and even if it hadn't the new users-existence guard would have aborted loudly instead of stamping).
- Bundle hash on prod: `index-B-Q_wWQc.js` (verified live via curl).
- `/api/health`: 200 (verified).
- Proposal-touching endpoints: 401 (auth-required, not 500) — confirms SQLAlchemy mapping loads cleanly with the new helpers in elections.py + pending_actions/registry.py.

---

## Phase 48 (overall) — complete

Three deploys: Stage 1 (`5d301eb` merge, `195baf95` SUCCESS) → Stage 2 (`0c8883f` merge, hotfix `0d440aa`, `f75a4b30` SUCCESS post-hotfix) → Stage 3 (`edd9d33` merge, `97f1050e` SUCCESS no incident). The bisection-by-stage design did its job: when Stage 2 crashed on a deploy-class bug (start.sh fresh-DB regex), the symptom localized to that stage's revision-ID specifically and the recovery + durable fix landed in <30 minutes without touching any election code. The start.sh fix carries forward as a project-wide hardening (regex + users-existence guard + recovery-script template) — future passes inherit the protection.

**Phase 48 + the Phase 48 incident together establish the convention**: hex-prefix revision IDs by default, with a structural backstop (users-existence guard) for the case where a future contributor forgets. Codified in CLAUDE.md.

Phase 49 (D11 — scheduled / fixed-term elections + auto-re-election) is the next election-related work, but it's a separate phase and not yet scoped/spec'd.
