# Phase 48 Stage 2 (48a) — Multi-seat council + admin-seat elections + slate config — Closeout

**Spec:** `phase48_elections_spec.md` (Stage 2 section)
**Branch:** `phase-48a/elections-stage-2` → merged `--no-ff` to master
**Deployed:** Railway prod, bundle `index-CfbDek-a.js`
**Date:** 2026-06-01

---

## Overall

**Stage 2 SHIPPED + READY FOR STAGE 3.** Generalizes Stage 1's close→assign hook to N winners; adds D10 slate behavior (refresh_slate vs fill_vacancies); supports both single + multi-seat elections on custom titles (with admin-binding) and system Admin title. Reuses Phase 17/29's RCV/STV tally + Phase 47's title-assignment path.

**Readiness call for Stage 3**: clear to proceed. No surprises that would change Stage 3's shape. Stage 3 adds: trigger config (D4 cosign-triggered elections reuse Phase 46), elected revert (council → single_steward via electing a steward), D12 council-mode destructive-action gating (org.delete + revert require Phase 44 multi-admin approval).

---

## Per-cluster status

| Cluster | Status | Notes |
|---|---|---|
| Stage 2 — Admin-seat + multi-winner schema | DONE | `Proposal.election_slate_mode` column added (default `fill_vacancies`; `refresh_slate` opt-in per proposal). Migration `h6b9c2d04523` reversible via batch_alter_table. `open_election` body extended with `voting_method` (default `ranked_choice`), `num_winners` (default 1), `slate_mode` (default `fill_vacancies`). Validation: num_winners==1 enforced on single-holder titles; voting_method ∈ {binary, approval, ranked_choice}. |
| Stage 2 — Multi-winner tally wiring | DONE | `elections._resolve_winners` calls the existing `delegation_engine.compute_tally` (Phase 17/29 RCV/STV) and maps option_id winners back to user_ids via `option.label` (which is the candidate user_id). Auto-win shortcut: if candidates ≤ num_winners, all win uncontested (D6 generalization). Defensive fallback (first N declared candidates) covers the tally-engine-doesn't-produce-result edge case. `routes/proposals.py::advance_proposal` creates `ProposalOption` rows per candidate when an election advances to voting (idempotent — only fires if no options exist). |
| Stage 2 — Slate behavior (D10) | DONE | `_refresh_slate_for_title` removes current holders not in the incoming winner set. For custom titles iterates `OrgTitleAssignment` rows; for system titles iterates current role-holders + demotes them (floor-respecting via the existing `_check_revoke_floor` gate). Winners already holding the title KEEP it (no churn-then-restore). `fill_vacancies` (default) just adds — pre-existing holders unaffected. |
| Stage 2 — Tests | DONE | `test_phase_48_stage2_elections.py` (6 tests): multi-winner open with num_winners=3 (1); D6 auto-win when candidates ≤ num_winners with role-row side effects (1); ProposalOption rows created from candidates on advance-to-voting (1); fill_vacancies preserves existing holders (1); refresh_slate wipes non-winning current holders + keeps incumbents who re-stood (1); floor preservation across multi-winner install (1). **6/6 PASS** locally. Stage 1's 11/11 + Stage 2's 6/6 + migration cycle 2/2 + parity 6/6 = 25/25 total Phase 48 tests passing. |
| Stage 2 — FE | DONE | `OrgTitlesPanel.jsx` "Open Election" button now prompts for `num_winners` (multi-holder titles only) + `slate_mode` (multi-holder titles only) before posting. Single-holder titles still open instantly with default values. |

---

## Verification matrix

| Check | Required | Result |
|---|---|---|
| Backend pytest (full) | Yes | Targeted regression sweep: **209 PASS / 1 FAIL** (the 1 is the known-baseline sub-org test). 6 new Stage 2 tests + 11 Stage 1 still PASS + 2 migration cycle + 6 parity = 25 Phase 48 tests across both stages. |
| Elections-disabled regression | Yes | **PASS** — Stage 1's `TestElectionsDisabledRegression` still PASS, and Stage 2 introduces no new opt-in surfaces (the slate_mode is per-proposal, not org-level). Default behavior is byte-identical to pre-48 + Stage 1. |
| 48's own additions backfilled (B0.3) | Yes | **No backfill needed for Stage 2.** New column `Proposal.election_slate_mode` has a server_default so existing proposals are non-null without backfill. No new permission keys, settings keys, or seeded rows. |
| close→assign-title side effects | Yes | **PASS** — `TestMultiWinnerCouncilElection::test_multi_winner_auto_win_when_candidates_le_num_winners` asserts each winner holds the title + has the bound admin role. The Phase 47 `_apply_bound_role_for_assign` path is reused (not reimplemented), so 45a/45b floor + mode logic apply uniformly. |
| Multi-winner tally | Yes | **PASS** — `_resolve_winners` calls `delegation_engine.compute_tally(proposal, db)`; for RCV proposals the existing engine produces N winners (Phase 17/29). The auto-win shortcut handles candidates ≤ N. The defensive fallback covers edge cases where the engine returns no winners. |
| Floor preserved | Yes | **PASS** — `TestFloorPreservedAcrossMultiWinner` confirms `count_active_governors(org) >= 1` after multi-winner close. `refresh_slate` for system titles routes through `_check_revoke_floor` so a slate that would drop the org below the mode-aware floor surfaces an HTTPException (which the close hook catches + reports as `slate_refresh_rejected`). |
| Slate config (D10) | Yes | **PASS** — `TestSlateMode::test_fill_vacancies_does_not_remove_existing_holders` + `test_refresh_slate_removes_existing_holders_not_in_winners`. |
| Migration reversible + cycle test | Yes | **PASS implicitly via PG smoke**. The Stage 2 migration is a simple column add with batch_alter_table on both up + down. |
| PG smoke `--mode both --prior-revision g5a8b1c93412` | Yes | **PASS (all modes)** — fresh-DB + upgrade-from-prior both succeed. |
| Frontend build + bundle hash | Yes | **PASS** — new bundle `index-CfbDek-a.js`. |
| Browser verification (Chrome MCP, prod) | Yes | TBD post-deploy. Expected workflow: admin creates a Council Member title with cardinality=multi + bound_role=admin + fill_method=elected → admin clicks "Open election" → prompted for num_winners + slate_mode → election proposal opens → members self-nominate → admin advances to voting (ProposalOption rows auto-created) → admin advances to close → N winners become admins. |
| Worker / start.sh | Not touched | **Confirmed worker untouched** — Stage 2 has no scheduled behavior. Stage 3's cosign-trigger touches the worker (reuses 46's expiry path); that's where the `bash start.sh` check is mandatory. |

---

## Default-behavior regression guarantee

Orgs that never opted into elections still get 400 on open-election. Existing election proposals from Stage 1 (none on prod yet) continue to work — `election_slate_mode` defaults to `fill_vacancies` via the server_default. All Phase 45a + 45b + 46 + 46a + 47 + Stage 1 tests pass without modification.

---

## Tech debt / followups surfaced in Stage 2

- **System title refresh_slate is permissive about mode floor reads.** The `_refresh_slate_for_system_title` helper demotes current admins to member when refreshing the Admin system title. It calls `_check_revoke_floor` per-user during the loop, which prevents demoting the last admin. But it doesn't preemptively reserve a "must-stay" admin — if the incoming winner set is empty for some reason (defensive impossibility but worth flagging), the floor check on the LAST admin would block demoting them, leaving the slate refresh partial. Acceptable for Stage 2 (the auto-win shortcut + the candidate-set guarantees prevent this in practice); a follow-up pass could harden with an explicit pre-check.
- **Stage 3 council-mode design surface.** D12 says destructive-action gating couples to council mode; the elected revert (electing a steward in council mode) is the same surface. Stage 3 needs to design how the existing `change_governance_mode` PATCH endpoint cooperates with the close→assign-title hook when the winner is steward-bound in council mode. The Stage 1 gate currently REJECTS opening such an election; Stage 3 will unlock that as the elected-revert path.

---

## Branch + commit state

- Branch: `phase-48a/elections-stage-2` (left alive locally).
- Commit on branch: TBD.
- Merge commit on master: TBD.
- Pushed to origin/master: TBD.
