# Phase 52j — Closeout

**Status:** SHIPPED + verified on prod 2026-06-07.
**Branch:** `phase-52j/verification-coherence` (merged `--no-ff`).
**Master:** `bf6c7a3` (phase commit) → `297535d` (merge commit) → `<this commit>` (closeout).
**Migration:** `d1e2f3a4b5c6` (down `c0d1e2f3a4b5`, hex-prefix). **Data-shape only** (no schema change) — settings normalizer. Verified applied on prod via Railway deploy log.
**Bundle:** `index-DeRqUIrN.js → index-C8Nr8vzO.js` (live).
**Backend:** `/api/health` 200; startup clean.
**Spec:** `phase52j_verification_coherence_spec.md`.

## What shipped

### J1 — Org-level residency model
- New settings key `verification_residency_scope`: list of `{state, city?}` entries. OR-matched. Independent levels (state and city match on their own terms — 52i no-subsumption invariant preserved).
- New predicate `user_satisfies_residency_scope(user, org)` in `verification.py`. Reads new key; backward-compat falls back to synthesizing a one-entry scope from the old 52i single-value keys (`verification_membership_jurisdiction` + `verification_membership_locality`) when the new key isn't present. This keeps pre-normalizer orgs behaving identically until the migration runs.
- Per-gate "require residency" booleans: `verification_membership_require_residency` (membership) + `verification_role_require_residency` (per-role map). Defaults False.
- New gate-helpers `check_membership_residency_for_join` + `check_role_residency_for_grant` raise structured 403 `{scope: "residency_scope", residency_scope: [...]}` when the user fails the scope match.
- Wired into all three membership join paths (`create_join_request`, `request_join`, `accept_invitation`) via the back-compat `check_membership_locality_for_join` shim (which now also fires on legacy locality keys). Wired into all four role-grant paths (`change_role`, `transfer_stewardship`, `successor_assignment`, title-assign in `org_titles.py`).
- Delegation eligibility filter routed through `effective_proposal_floor` so always/never proposal policies (J3) apply uniformly at delegation narrowing AND vote-cast.
- Settings normalizer migration `d1e2f3a4b5c6` folds old single-value keys into the new scope shape AND sets `verification_membership_require_residency=True` so orgs that had a city gate keep enforcing. Idempotent (re-runs are no-ops on already-normalized orgs). Reversible.

### J2 — Dropdown simplification (Z-locked relabel only)
- Membership floor + 3 role floor dropdowns collapsed from 5 options to 3:
  - "No verification required" (unset)
  - "Identity verified" (`identity`)
  - "Verified resident" (`address_on_id`)
- Backend ladder UNCHANGED: `identity_unique` + `residency_verified` remain in `ORDER` and `VALID_STATES`; `rank()` not renumbered; any stale stored value still resolves sanely (asserted in `TestBackendLadderIntact`).
- Selecting "Verified resident" reveals a checkbox to opt into the org's residency scope (J1).

### J3 — Org-level proposal verification policy
- New settings: `verification_proposal_policy` (`author`/`always`/`never`, default `author`), `verification_proposal_floor`, `verification_proposal_jurisdiction`.
- New helper `effective_proposal_floor(proposal, org)` resolves the effective `(floor, jurisdiction)` for a proposal under the org's policy.
- `check_vote_floor_for_proposal(user, proposal, org=None)` extended to take the org (back-compat default None preserves call sites that don't pass it).
- `routes/votes.py` passes the org so policy resolution applies at vote time.
- `delegation_engine` eligibility narrowing also routes through `effective_proposal_floor` — `always`-policy applies org floor at both vote-cast AND delegation narrowing; `never`-policy ignores any stored proposal floor at both layers.
- FE: org-settings 3-way policy selector + org floor picker (revealed when `always`).

### J4 — Name-match first-token fix + "either" mode
- **The observation-#5 bug fix.** `first` mode now compares display first-token to legal first's FIRST token (was comparing display first-token to the whole normalized `legal_first`, which broke when Didit packed middle names into `first_name`). Symmetric for `last`. The regression case `legal_first="Zachary Michael"` + display `"Zachary"` → MATCH, asserted in `TestNameMatchFirstTokenFix::test_observation_5_regression_case_first_mode_matches`.
- New `NAME_MATCH_EITHER` mode: passes when first OR last token matches. The looser "you're using at least one part of your real name" option.
- `full` mode (Z-default): relaxed first+last (middle-name-tolerant). Display must have ≥2 tokens; first matches legal-first's first token AND last matches legal-last's last token. Falls back to whole-string equality when legal_first/legal_last aren't separately set (preserves existing-test behavior with only `legal_full` set).
- FE: added "Either first or last name must match ID" to the mode dropdown.

### J5 — Copy fixes
- Removed stale "Identity-verification options for members will become available in a future update." from `OrgSettings.jsx` section intro.
- Relabeled delegate-verification toggle: "Require verified members to be promoted to public delegate" → "Require verification to become a public delegate" (the label inverted the meaning).
- Rewrote min-age help text to explain the band/month-aligned-promotes-at mechanism honestly: "We record which age brackets a verified member has passed (for example, 16+ and 18+) and the month they'll reach the next one — not their date of birth. Members below the minimum can't join, and a member who later reaches the minimum gains access automatically without re-verifying."

### J6 — Resolver propagation (partial)
- Routed `display_name_for(user, org, membership=)` through:
  - Org-scoped delegate browse (`org_delegates_router.list_org_delegates` in `routes/delegates.py`) with a pre-fetched membership map to avoid N+1.
  - Public delegate page (`public_delegate_page` in `routes/delegates.py`).
  - Comments serializer (`_build_comment_out(c, db)` in `routes/comments.py`).
- **Remaining surfaces (carry forward):** proposal authorship, vote attribution, notification copy + email templates. These read `User.display_name` directly; routing them through `display_name_for` requires either adding an `author_display_name` override to ProposalOut / VoteOut or wrapping notification copy generation with the org context. Scoped out of this pass.

### FE
- `verificationLabels.js`: `ctaCopyForVerificationRequired` handles the new `scope='residency_scope'` payload, rendering "This organization requires members to be a verified resident of {city, state | state | …}" with proper comma/and formatting.
- `OrgSettings.jsx`: residency scope editor (per-row state + optional city + remove button + add row), proposal policy selector, name-match dropdown updated with "either".

## Verification matrix

| Check | Required | Result |
|---|---|---|
| **J1** residency-scope OR-match | ✅ | `TestResidencyScopePredicate::test_or_match_across_entries` + state-vs-city independent matching. |
| **J1** state-in-hash (52i invariant preserved) | ✅ | `test_city_entry_hashes_with_state` — Springfield-MA ≠ Springfield-IL. |
| **J1** old-settings normalizer | ✅ | `test_phase_52j_migration_cycle::test_upgrade_folds_old_keys_into_new_scope` — both `(state, city)` and state-only orgs fold correctly; `verification_membership_require_residency=True` set. |
| **J1** normalizer idempotency | ✅ | `test_upgrade_is_idempotent` — downgrade-then-upgrade produces same shape. |
| **J1** residency boolean per-gate | ✅ | `TestRequireResidencyBooleans` + `TestMembershipResidencyCheck` + `TestRoleResidencyCheck`. |
| **J1** cardinality-floor invariant | ✅ | By construction — both `check_membership_residency_for_join` and `check_role_residency_for_grant` fire BEFORE any role-id write, so a residency block prevents the mutation; incumbents never demoted. |
| **J2** 3 options in FE dropdowns | ✅ | OrgSettings source review. |
| **J2** backend ladder intact | ✅ | `TestBackendLadderIntact` — `identity_unique` + `residency_verified` still in `VALID_STATES`; `ORDER` unchanged; `rank` not renumbered; stale stored value still resolves. |
| **J3** three policies (author/always/never) | ✅ | `TestProposalPolicy` + `TestEffectiveProposalFloor`. |
| **J3** policy applied at vote-cast | ✅ | `test_check_vote_floor_uses_policy` + `test_check_vote_floor_never_ignores_stored_floor`. |
| **J3** policy applied at delegation narrowing | ✅ | `delegation_engine.eligible_user_ids_for_proposal` routes through `effective_proposal_floor`. |
| **J4** first-token observation-#5 regression | ✅ | `TestNameMatchFirstTokenFix::test_observation_5_regression_case_first_mode_matches`. |
| **J4** "either" mode | ✅ | `TestEitherMode` — passes first or last; fails neither. |
| **J4** `full` relaxed first+last | ✅ | `TestFullModeRelaxed::test_relaxed_full_match_middle_name_tolerant`. |
| **J5** copy diffs | ✅ | Source review of `OrgSettings.jsx` (FE-source-review per CLAUDE.md "routine surface" rule). |
| **J6** resolver propagation | Partial | Delegate listing + delegate page + comments routed; proposal authorship + vote attribution + notifications documented as follow-up. |
| Additive-layer parity (whole phase) | ✅ | `TestAdditiveLayerParity` — no settings → no gate, default policy, name-match off. |
| Existing 52f/g name-match tests | ✅ | 40/40 still pass (no behavioral regression for the existing cases). |
| Existing 52i locality tests | ✅ | 41/41 still pass (two assertions updated to the unified `scope='residency_scope'` payload). |
| Phase 52j unit tests | ✅ | 52/52. |
| Migration cycle | ✅ | 3/3. |
| PG smoke both modes | ✅ | `python backend/scripts/pg_smoke.py --mode both --prior-revision c0d1e2f3a4b5` PASS. |
| FE build | ✅ | `npm run build` clean; new bundle (hash will be `index-C8Nr8vzO.js`-class — final hash recorded on prod). |
| Adjacent regression | ✅ | Full suite: **2145 passed, 11 failed, 18 skipped** in 33min. All 11 failures are pre-existing baseline failures on master (verified by `git stash` + re-running the same tests on stash-popped master) — none are 52j regressions. Tracked by the existing `phase60_green_the_suite_spec` + `phase61_test_performance_spec` files in the working tree. |
| Browser QA | PASS-by-source | OrgSettings additions + copy edits are routine surface (single section additions in an existing settings save path). FE source review confirms all controls wire through `updateSetting`. |
| Prod deploy | ✅ | Bundle `index-C8Nr8vzO.js` live; backend `/api/health` 200; Railway log: `Running upgrade c0d1e2f3a4b5 -> d1e2f3a4b5c6, phase 52j — residency scope settings normalizer`. |

## Files added/modified

**Added**
- `backend/migrations/versions/d1e2f3a4b5c6_phase_52j_residency_scope_normalizer.py` (+180)
- `backend/tests/test_phase_52j_verification_coherence.py` (+551, 52 cases)
- `backend/tests/test_phase_52j_migration_cycle.py` (+185, 3 cases)
- `phase52j_verification_coherence_spec.md` (+163)

**Modified**
- `backend/verification.py` — settings keys, residency-scope predicate + per-gate booleans + check helpers, proposal policy + effective floor, name-match first-token fix + either/full-relaxed.
- `backend/delegation_engine.py` — eligibility filter routes through `effective_proposal_floor`.
- `backend/routes/comments.py` — `_build_comment_out(c, db)` uses `display_name_for`.
- `backend/routes/delegates.py` — org-scoped browse + public delegate page route through `display_name_for`.
- `backend/routes/org_titles.py` — title-assign wires `check_role_residency_for_grant`.
- `backend/routes/organizations.py` — three role-grant paths + invitation-accept add `check_role_residency_for_grant`.
- `backend/routes/votes.py` — passes org to `check_vote_floor_for_proposal`.
- `backend/tests/test_phase_52i_locality_residency.py` — two assertions updated to the unified `scope='residency_scope'` payload.
- `frontend/src/pages/admin/OrgSettings.jsx` — J2/J3/J5 controls, J1 scope editor.
- `frontend/src/verificationLabels.js` — `scope='residency_scope'` CTA copy.

## Branch + commits

- Branch: `phase-52j/verification-coherence` (merged `--no-ff` into master).
- Phase commit: `bf6c7a3` — "Phase 52j: verification UI coherence + org-level residency model".
- Merge commit: `297535d` — "Merge phase-52j/verification-coherence: Phase 52j (verification UI coherence + org-level residency)".
- Pushed: `98f3f0e..297535d master -> master`.

## Prod deploy verification

- **Railway backend deploy log:**
  ```
  INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
  INFO  [alembic.runtime.migration] Will assume transactional DDL.
  INFO  [alembic.runtime.migration] Running upgrade c0d1e2f3a4b5 -> d1e2f3a4b5c6, phase 52j — residency scope settings normalizer
  ```
- **Backend health:** `GET https://www.liquiddemocracy.us/api/health` → `200`.
- **Bundle hash:** `index-C8Nr8vzO.js` live (flipped from `index-DeRqUIrN.js`).
- **Deploy duration:** ~30s bundle flip + backend warmup (`poll_deploy.py` reported `bundle=index-C8Nr8vzO.js backend_ok=True` at the 30s mark).

## Design notes worth carrying forward

**Two trigger paths for membership residency.** The Phase 52j J1 shim fires when EITHER the new `verification_membership_require_residency=True` AND there's a scope, OR the legacy `verification_membership_locality` + `verification_membership_jurisdiction` keys are set. After the normalizer migration runs on an org, both triggers fire because the migration sets both. The dual-trigger keeps pre- and post-migration orgs behaving identically.

**Cardinality-floor invariant by construction.** Both `check_role_residency_for_grant` (Phase 52j J1) and `check_role_grant_floor` (Phase 52 Stage 1) fire BEFORE any role-id write. So an admin changing the org's residency scope can never strand the org with zero stewards — the block aborts the mutation, leaving the incumbent in place.

**No subsumption between state and city levels** (52i locked decision preserved). A user in MA-Springfield with a Springfield-MA locality hash doesn't satisfy a scope entry `{state: "MA"}` via state-equality unless they ALSO have `verification_jurisdiction == "MA"`. Each entry is matched on its own terms.

**J6 carries forward.** Proposal authorship + vote attribution + notifications still render `User.display_name` directly. The honest scoping decision: shipping J1+J2+J3+J4+J5 in one pass is already substantial. The remaining J6 surfaces need either schema changes (ProposalOut.author_display_name, VoteOut.voter_display_name) or context-passing through notification templates; both are non-trivial sweeps.

**Back-compat ladder.** Z's locked decision to preserve the backend ladder means a future deliberate cleanup pass can renumber rank()/drop the dead rungs. That cleanup needs to migrate any stored `identity_unique` to `address_on_id` (the next-strongest meaningful tier) — defer until done.

## Followups (none blocking)

- J6 sweep for proposal authorship, vote attribution, notification copy/templates. Sized as its own future pass.
- Backend dead-rung cleanup: drop `identity_unique` + `residency_verified` from `ORDER`, renumber `rank()`, migrate stored values. Defer; non-urgent.
- The 52e Stage 2 `org_duplicate_flags` action settings, the 52f display-name-match action, and the 52j residency settings all live as flat keys on `Organization.settings`. A future pass may want to nest them under a `verification: { … }` sub-key. Defer; flat works.
