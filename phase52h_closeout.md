# Phase 52h — Combined Closeout (Stage 1 + Stage 2)

**Status:** Both stages SHIPPED + DEPLOYED 2026-06-06.
**Spec:** `phase52h_dedup_flag_upgrade_spec.md`.
**Sequencing rule honored:** Stage 1 deployed + verified on prod BEFORE Stage 2 branched. Two separate `--no-ff` merges to master, not one collapsed merge.

## Stages

| | Stage 1 (flag-feature upgrade) | Stage 2 (remove doc-block) |
|---|---|---|
| Branch | `phase-52h/flag-upgrade` | `phase-52h/remove-doc-block` |
| Merge commit | `ed66b74` | `25fd997` |
| Migration | `d5e6f7a8b9c0` (down `c4d5e6f7a8b9`) | `e6f7a8b9c0d1` (down `d5e6f7a8b9c0`) |
| Bundle | `index-DFnc-Tn7.js` | `index-Bc-c4xAD.js` |
| Verified on prod | `Running upgrade c4d5e6f7a8b9 -> d5e6f7a8b9c0`; `demoted_user_id` column visible via PG query | `Running upgrade d5e6f7a8b9c0 -> e6f7a8b9c0d1`; `ix_users_doc_number_hash_unique` DROPPED (only `ix_users_doc_number_hash` lookup index remains); alembic head = `e6f7a8b9c0d1` |

Alembic head after both stages: `e6f7a8b9c0d1`. Single head throughout. No multi-head events.

## Pre-flight grounding result

The spec required confirming whether `evaluate_duplicate_flags_for_org` was actually wired into the three join paths before building. Read `routes/organizations.py` in full (3656 lines):

- **`create_join_request`** (line 1898): `evaluate_duplicate_flags_for_org` called; high-confidence-pending routing logic at lines 1903-1909.
- **`request_join`** (line 2163): same wiring, lines 2168-2174.
- **`accept_invitation`** (line 2492): `evaluate_duplicate_flags_for_org` called; invitations explicitly bypass routing (admin endorsement is the override).

**No found-gap.** The 52e Stage 2 closeout was accurate. Stage 1 layered on top of the existing wiring rather than connecting it. The pre-flight check is documented here per the spec's instruction to surface it even when the result is null.

## Stage 1 — H1-H4 (flag-feature upgrade)

### H1 — verify-time detection trigger
- `verification_flags.evaluate_duplicate_flags_for_user_orgs` wraps the existing per-org eval and iterates the user's active `OrgMembership` rows. Closes the join-then-verify gap.
- Wired into `routes/verification._apply_decision` AFTER the user's hashes commit. Exception-swallowed so flag eval can never block the verification write itself.
- **Z-locked asymmetry vs join-time:** verify-time match on an ALREADY-ACTIVE member ONLY records the flag (so `is_org_verified` flips False per H3); does NOT flip membership back to `pending_approval`. Suspending a sitting member is more disruptive than the join-time case. The webhook caller honors this by not touching `membership.status`. Cross-org stays ignored — only the user's own orgs are walked.

### H2 — per-tier configurable action, both default to `pending_approval`
- New settings key `verification_low_confidence_flag_action`. Both tiers accept `pending_approval` (default) or `review_only`, independently flippable.
- New dispatch helper `flag_action_for_confidence(org, confidence)`. Join-path routing reads this; the per-tier branch logic at the call site is removed.
- Z-locked pivot: within a real org, false positives on the low-confidence flag are rare enough that routing to admin review beats letting a possible duplicate through. The default flips from the pre-52h hardcoded review-only to `pending_approval`. (`Mode 3` parity preserved — an org with no verification + no verified members produces no hashes → no flags → no behavior change, byte-for-byte unchanged.)
- OrgSettings.jsx renders the second dropdown alongside the existing high-confidence one.

### H3 — both tiers invalidate `is_org_verified`
- `has_open_high_confidence_flag` renamed to `has_open_flag` (any confidence). The predicate now returns False on EITHER tier.
- New companion predicate `is_demoted_in_resolved_same` for H4's durable demotion.
- `is_org_verified` is now: floor satisfied AND no open flag of either tier AND not the demoted side of any resolved_same flag.

### H4 — `resolved_same` auto-demotes the newer account
- New `org_duplicate_flags.demoted_user_id` column (FK users.id, SET NULL on delete, nullable, indexed). Migration `d5e6f7a8b9c0`.
- `resolve_flag` for `resolved_same`: looks up both users' `created_at`, sets `demoted_user_id` = newer-of-pair. Audit includes the demoted side.
- **Cardinality-floor invariant preserved by construction:** demotion flips `is_org_verified` to False but the role_id row is untouched. A demoted steward keeps their steward role; the admin handles manually. Mirror of the 52e Stage 2 cardinality-floor test with a `resolve_same` trigger.
- Fully removing/kicking the duplicate account stays a SEPARATE manual admin action — `resolved_same` only demotes verified-status-in-this-org.
- `resolved_distinct` unchanged (suppresses re-flag; no demotion).

## Stage 2 — remove platform-wide doc-number hard block

### What was removed
- `routes/verification._apply_decision`: collision lookup, `collision_rejected` branch, `verification.duplicate_document` audit on the pre-check path, `doc_number_unique=` mapper arg, `doc_number_hash` write, `uniqueness_strength` write.
- `routes/verification.didit_webhook`: the `IntegrityError` catch + wrapper try block; `from sqlalchemy.exc import IntegrityError` import (unused).
- The `doc_hash_written` field from the `verification.completed` audit details.
- `verification_hashing.compute_hashes`: doc-number-hash computation. Key remains in the output dict (always None) for back-compat callers reading it explicitly.
- `verification_provider.map_decision_to_state`: `doc_number_unique` kwarg + the `IDENTITY_UNIQUE` rung's auto-assignment + the `IDENTITY_UNIQUE` import. Z-locked Option A: post-removal, verification proves identity + residency only; uniqueness within an org is handled by the org-scoped flag system, biometric stays the deferred stronger tier. The state ladder produced is now `IDENTITY` or `ADDRESS_ON_ID`.
- Migration `e6f7a8b9c0d1`: drops `ix_users_doc_number_hash_unique` (partial-unique index that enforced the platform-wide block).

### What was retained (intentional)
- `users.doc_number_hash` COLUMN — dropping columns on PG is the riskier op. Marked deprecated in the model comment. Batches with the deprecated `verification_nullifier` column for a future cleanup pass.
- `ix_users_doc_number_hash` (the non-unique lookup index) — harmless on a no-longer-written column. Future cleanup drops both column and lookup index together.
- `UNIQUENESS_DOCUMENT_HASH` / `UNIQUENESS_BIOMETRIC` constants — useful as documentation if the deferred biometric tier ever needs to compare against the legacy value; unused by current code.

### One small consistency fix in Stage 2
`verification_provider._decision_passed_id` previously only read the legacy singular `decision.id_verification.status` and the overall `decision.status`. The rest of the mapper reads the plural `decision.id_verifications[0]` (real Didit shape per the captured manifest). Extended the passed-check to read the plural path too, matching. Unrelated to the doc-block removal but caught by the Stage 2 test suite — folded in.

### Copy honesty
- `DOC_HARD_BLOCK_MESSAGE` REMOVED from `verificationLabels.js`. No FE path renders it; no backend path produces a hard block.
- `UP_FRONT_ONE_IDENTITY_COPY` REWRITTEN. The platform-wide "one account per person" claim was honest pre-52h Stage 2 (the block enforced it); post-removal it would be a copy lie. New copy frames the constraint as per-org: "Each organization may have its own rules about duplicate members; if your verified identity matches another member of the same organization, that organization's admin can review and decide."
- Remaining privacy / non-retention copy is still gated on the E1b purge proof (Mara's reply pending). This stage doesn't touch that.

## Combined verification matrix

| Check | Stage | Required | Result |
|---|---|---|---|
| Verify-time detection fires + active-member-not-flipped asymmetry | 1 | ✅ | `TestH1VerifyTimeTrigger` — 3 cases including the active-member-stays-active assertion |
| Both tiers configurable; both default `pending_approval` | 1 | ✅ | `TestH2LowConfidenceDefault` — 6 cases including the explicit join-time routing under default |
| Both tiers invalidate `is_org_verified` | 1 | ✅ | `TestH3PredicateInvalidatesBothTiers` — low-conf now invalidates (regression vs pre-52h); 52e Stage 2 test renamed `test_low_confidence_flag_NOW_invalidates_phase_52h_h3` |
| `resolved_same` demotes newer + durable predicate False | 1 | ✅ | `TestH4ResolveSameDemotesNewer` — 4 cases: demoted_user_id = newer; predicate stays False post-resolve; cardinality-floor preserved; resolved_distinct unchanged |
| Mode 3 parity preserved | 1 | ✅ | `TestMode3ParityStillHolds::test_unconfigured_org_with_no_verified_members_unchanged` |
| Migration cycle Stage 1 + PG smoke | 1 | ✅ | 2 cases SQLite + PG smoke fresh + upgrade PASS |
| Two accounts same doc different orgs both verify | 2 | ✅ | `TestDocBlockRemoved::test_same_document_different_users_both_verify` — both verify; zero duplicate_document audits; no collision_rejected status |
| Same-org match still flagged | 2 | ✅ | `TestSameOrgFlagStillRaised::test_same_org_same_person_still_flagged_at_join` |
| `doc_number_hash` no longer written | 2 | ✅ | `TestDocBlockRemoved::test_doc_number_hash_no_longer_written` |
| Mapper signature no longer reads `doc_number_unique` | 2 | ✅ | `TestMapperUniquenessRungRemoved` — 4 cases including signature inspection + `IDENTITY_UNIQUE` unreachable across decision-shape matrix |
| `compute_hashes` `doc_number_hash` key always None | 2 | ✅ | `TestComputeHashesNoLongerProducesDocHash::test_compute_hashes_doc_number_hash_always_none` |
| No orphaned references (IntegrityError, duplicate_document audit) | 2 | ✅ | `TestNoOrphanedReferences` — 2 source-scan cases |
| Migration cycle Stage 2 + PG smoke | 2 | ✅ | 2 cases SQLite + PG smoke fresh + upgrade PASS |
| Stage 1 adjacent regression | 1 | ✅ | 496/496 PASS in 4:15 |
| Stage 2 adjacent regression | 2 | ✅ | 506/506 PASS in 4:26 |
| FE build clean | both | ✅ | Stage 1 `index-DFnc-Tn7.js`; Stage 2 `index-Bc-c4xAD.js` |
| `bash start.sh` prod-mimic | both | N/A | No start.sh / worker / scheduled tick change either stage |
| Prod migration applied | both | ✅ | Stage 1 + Stage 2 both observed via Railway logs + direct PG queries; alembic head = `e6f7a8b9c0d1`; `ix_users_doc_number_hash_unique` DROPPED on prod |

## Test count deltas

- Stage 1: +21 new (19 unit + 2 migration cycle) + 2 migrated 52e Stage 2 tests renamed to reflect H2/H3 behavior changes. Adjacent regression 496/496 PASS.
- Stage 2: +12 new (10 unit + 2 migration cycle). Bulk updates to 52d / 52e Stage 1 tests that asserted the now-removed doc-block behavior — TestComputeHashes (3 tests rewritten), TestMapDecisionToStatePrecedence (5 → 3 tests, kwarg removed + IDENTITY_UNIQUE assertions dropped), TestDocumentNumberHardBlock (3 tests rewritten to assert the new "both verify" / "in-org dedup still works" contract), TestPurgeWiring (2 tests updated for state=IDENTITY), TestMapperOnRealShape (2 tests updated for new mapper signature). Adjacent regression 506/506 PASS.

## Files added / modified

### Stage 1 (10)
- A `backend/migrations/versions/d5e6f7a8b9c0_phase_52h_stage1_demoted_user_id.py`
- A `backend/tests/test_phase_52h_stage1_flag_upgrade.py` (19 cases)
- A `backend/tests/test_phase_52h_stage1_migration_cycle.py` (2 cases)
- M `backend/models.py` — `OrgDuplicateFlag.demoted_user_id` field
- M `backend/routes/organizations.py` — per-tier dispatch via `flag_action_for_confidence`
- M `backend/routes/verification.py` — verify-time trigger via `evaluate_duplicate_flags_for_user_orgs`
- M `backend/verification_flags.py` — `low_confidence_flag_action` + `flag_action_for_confidence` + `has_open_flag` + `is_demoted_in_resolved_same` + `evaluate_duplicate_flags_for_user_orgs` + extended `is_org_verified` + extended `resolve_flag` for newer-demotion
- M `backend/tests/test_phase_52e_stage2_modes_and_flags.py` — 2 tests renamed to reflect 52h H2/H3 behavior changes
- M `frontend/src/pages/admin/OrgSettings.jsx` — low-confidence dropdown
- A `phase52h_dedup_flag_upgrade_spec.md`

### Stage 2 (11)
- A `backend/migrations/versions/e6f7a8b9c0d1_phase_52h_stage2_drop_doc_number_unique_index.py`
- A `backend/tests/test_phase_52h_stage2_remove_doc_block.py` (10 cases)
- A `backend/tests/test_phase_52h_stage2_migration_cycle.py` (2 cases)
- M `backend/models.py` — `users.doc_number_hash` marked deprecated (comment)
- M `backend/routes/verification.py` — collision lookup + `collision_rejected` branch + audit + try-wrapper + IntegrityError import + doc_hash_written audit field all removed
- M `backend/verification_hashing.py` — module docstring updated; `compute_hashes` no longer computes `doc_number_hash`
- M `backend/verification_provider.py` — `map_decision_to_state` signature dropped `doc_number_unique`; `IDENTITY_UNIQUE` import dropped; `_decision_passed_id` consistency fix for plural shape
- M `backend/tests/test_phase_52d_hash_dedup.py` — bulk updates (TestComputeHashes, TestMapDecisionToStatePrecedence, TestDocumentNumberHardBlock, TestPurgeWiring)
- M `backend/tests/test_phase_52d_migration_cycle.py` — pinned to `_PHASE_52D_REVISION` rather than head
- M `backend/tests/test_phase_52e_stage1_extractor_and_purge.py` — TestMapperOnRealShape + TestWebhookOnRealShape updated for new mapper signature + no doc_number_hash write
- M `frontend/src/verificationLabels.js` — DOC_HARD_BLOCK_MESSAGE removed; UP_FRONT_ONE_IDENTITY_COPY rewritten for honesty

## Deploy verification

**Stage 1 (2026-06-06 17:06 UTC):**
- Railway log: `Running upgrade c4d5e6f7a8b9 -> d5e6f7a8b9c0, phase 52h stage 1 — demoted_user_id on org_duplicate_flags`
- Bundle flipped to `index-DFnc-Tn7.js`
- Direct PG query: `demoted_user_id` column present on `org_duplicate_flags`; alembic head = `d5e6f7a8b9c0`

**Stage 2 (2026-06-06 17:34 UTC):**
- Railway log: `Running upgrade d5e6f7a8b9c0 -> e6f7a8b9c0d1, phase 52h stage 2 — drop platform-wide doc_number_hash unique index`
- Bundle flipped to `index-Bc-c4xAD.js`
- Direct PG query: `ix_users_doc_number_hash_unique` DROPPED on prod (only the non-unique lookup index `ix_users_doc_number_hash` remains, as intended); deprecated columns `doc_number_hash` and `uniqueness_strength` retained; alembic head = `e6f7a8b9c0d1`

Stage 1 verified BEFORE Stage 2 branched. Two `--no-ff` merges per the spec's sequencing rule.

## For Z review (build-time decisions)

1. **Uniqueness rung: Option A (locked).** Z's instruction was to drop `IDENTITY_UNIQUE`'s auto-assignment entirely; the post-removal model claims only identity + residency. I did not see a reason to flag Option B (keeping the rung name without enforcement) — Option B would have produced a misleading state name. Built per Option A.
2. **`resolved_same` newer-account demotion (locked).** Implemented exactly: at resolve time, look up both `User.created_at` values; the later one's id goes into `demoted_user_id`. Admin can manually override afterward via the existing endpoints.
3. **Verify-time active-member asymmetry (locked).** Recorded the flag + predicate-invalidation only; never flipped membership back to `pending_approval`. The webhook caller's H1 helper (`evaluate_duplicate_flags_for_user_orgs`) records flags but does not own membership state.

## What's NOT done in this phase (acknowledged future work)

- **Deprecated column cleanup pass.** `users.doc_number_hash`, `users.verification_nullifier`, `ix_users_doc_number_hash`, and `ix_users_verification_nullifier_unique` are all retained intentionally for safety; a small future migration drops them together once we're confident the deprecation lookups are gone from any out-of-band consumer.
- **E5 privacy / non-retention copy.** Still gated on Mara's purge-endpoint reply. When the correct Didit deletion endpoint lands and a session is observed to disappear from the portal, the honest non-retention copy ships in a small FE pass.
- **Admin UI for the open-flags adjudication surface.** Still backend-only. Z (or any org admin) can `curl` the endpoints; a small admin page is a follow-up.
- **Flag-raised notifications.** No email/notification fan-out yet when a flag is raised — admins notice via the open-flags list when they look. Small follow-up if Z wants admins paged proactively.

## Branch state

- `phase-52h/flag-upgrade` merged via `ed66b74` (Stage 1, --no-ff). Safe to delete.
- `phase-52h/remove-doc-block` merged via `25fd997` (Stage 2, --no-ff). Safe to delete.
- master at `25fd997` (Stage 2 merge) + closeout commit (forthcoming this turn), pushed to origin, Railway deployed.

## Closeout assertion

**Phase 52h complete.** The org-scoped flag system is upgraded (verify-time trigger + per-tier configurable + both-tier invalidation + resolved_same demotion), and the platform-wide doc-number hard block is retired. The verification arc's dedup posture is now honest: confidence-determines-scope all the way down, no platform-wide platform-wide claims about cross-org uniqueness, in-org dedup via the name-based flag system, biometric remains the deferred stronger tier for orgs that need real Sybil resistance.
