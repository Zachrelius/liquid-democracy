# Phase 51 — Verification State Model + Org Gate Config (Foundation) — Closeout

**Spec:** `phase51_verification_state_model_spec.md`
**Branch:** `phase-51/verification-state-model` → merged `--no-ff` to master
**Date:** 2026-06-03

---

## Overall

**SHIPPED.** Foundation pass of the ID-verification arc. Stands up the platform-level verification record + the org-level gate configuration + the pure subsumption logic. **No enforcement is wired** — that's Phase 52. The state model, serializer exposure, and gate config all land and are testable against a guarded admin backdoor before any external Persona integration adds its own risk surface. Riskiest-piece-isolated-first per the workflow playbook.

The additive-layer invariant held: deleting the new feature in your head leaves every existing query, tally, join, and role path byte-for-byte intact.

---

## Confirmed alembic head + chain state

- `alembic heads` showed **exactly one head**: `b9c2e0f43215` (Phase 49a — proposal_creation_remap). No multi-head state.
- Phase 51 stacked onto that single head. New revision: `c8d3e1f56432` (hex prefix per the Phase 48 Stage 2 incident lesson).

---

## Per-cluster status

| Cluster | Status | Notes |
|---|---|---|
| C1 — Migration | DONE | `c8d3e1f56432` adds six columns to `users` (`verification_state`, `verification_jurisdiction`, `verification_attestation_id`, `verification_nullifier`, `verification_provenance`, `verification_updated_at`) + indexes on `verification_state` and `verification_nullifier`. NO `UniqueConstraint` on `verification_nullifier` (deferred to Phase 52 — see Forward constraints below). Reversible via `batch_alter_table` for SQLite parity. `server_default` carries the column-add defaults so existing user rows are byte-for-byte unaffected (the no-backfill guarantee). |
| C2 — `backend/verification.py` | DONE | Pure-function module, no DB access. `ORDER` constant (the five-state ordered list); `VALID_STATES` frozenset; `rank(state) -> int` (unknown returns -1, fails closed); `subsumes(current_state, current_jurisdiction, required_floor, required_jurisdiction) -> bool` per the locked rules — ordinal floor + exact-string jurisdiction match at `address_on_id`/`residency_verified` + jurisdiction-ignored-below-`address_on_id` + `email_only`-satisfied-by-everyone + fail-closed on unknowns; `get_org_verification_floor(org, scope, *, role_key=None) -> (floor, jurisdiction)` with defaults-if-absent semantics matching `org_config.py`; `jurisdiction_required_for(state)` shared by the backdoor + Phase 52 setters for input validation. |
| C3 — Model + serializer + backdoor | DONE | Six `User` columns added matching the migration. `UserOut` surfaces `verification_state` / `jurisdiction` / `provenance` / `updated_at` only — `attestation_id` and `nullifier` intentionally NOT exposed. Phase 46a serializer-coverage test extended with `TestUserOutSurfaceContract` block + `_USER_OUT_MUST_SURFACE_FIELDS` (must surface) and `_USER_OUT_INTERNAL_VERIFICATION_FIELDS` (must NOT leak — defense in depth against accidental nullifier serialization). Backdoor endpoint `POST /api/admin/users/{user_id}/verification-state` (platform-admin-only via `get_current_admin`) validates state ∈ `ORDER`, validates jurisdiction-presence consistency (required iff `state >= address_on_id`; lower-tier inputs with a jurisdiction silently dropped), stamps `provenance='backdoor'` + `updated_at=now`, audit-logs as `user.verification_state_set` with old + new values. The endpoint persists as the platform-admin / ops override path beyond Phase 52. |
| C4 — Demo seed stub + parity | DONE | `demo_content/seed_pipeline._ensure_user` calls a new `_stamp_demo_verification` helper that writes `verification_state='identity_unique'`, `verification_provenance='demo_stub'`, `verification_jurisdiction='DEMO'` (sentinel that is intentionally NOT a real US state code so it can never be mistaken for a real verification). Idempotent across resets. Never overwrites a real `persona` record (defensive against a future where a demo username accrues a real one). The `demo_stub` provenance is load-bearing for demo safety — Phase 52 enforcement + Phase 53 billing MUST honor it. Existing-vs-new-org parity test (`TestExistingOrgParity::test_pre_and_post_pass_orgs_resolve_to_same_defaults`) asserts an org with a pre-Phase-51-shape settings dict and an org with an empty settings dict both resolve every verification setting to `("email_only", None)`. |
| FE — Read-only verification status | DONE (in-scope) | Plain-language "Identity verification" section on `Settings.jsx` showing state + jurisdiction + source. No "verify now" action (nothing to verify against until Phase 52). Backend state codes never appear in rendered copy — only plain-language labels — consistent with the Phase 49a C2 "no internal-name leakage" rule. New bundle hash: `index-BXYiuSeI.js`. |

---

## Verification matrix

| Check | Required | Result |
|---|---|---|
| Backend pytest (Phase 51 + adjacent + migration cycles) | Yes | **267/267 PASS in 240s** across Phase 51 (16 — verification model 12 + migration cycle 2 + jurisdiction-required helper 2) + Phase 50 (10) + Phase 49b (10) + Phase 49a (20) + Phase 49 (14) + Phase 48 stages (36) + Phase 47 (16) + Phase 46 + 46a + 46a-coverage (24) + Phase 45a/45b (19) + Phase 44 (28) + digest. The +16 delta is the new Phase 51 tests (the existing 251 baseline was unchanged). |
| Subsumption unit tests (pure, no DB) | Yes | **PASS** — `TestSubsumptionPureMatrix` exhaustively tests every (current_state × required_floor) pair plus jurisdiction match / mismatch / no-requirement / lower-state-with-jurisdiction-against-floor-requiring-jurisdiction / unknown-state-fails-closed / unknown-floor-fails-closed. The matrix is small and finite — enumerated, not spot-checked. |
| Existing-vs-new-org parity test | Yes | **PASS** — `TestExistingOrgParity::test_pre_and_post_pass_orgs_resolve_to_same_defaults` asserts a pre-Phase-51-shape org (no verification keys) and a post-pass org (empty settings) both resolve `membership`, `role:admin`, and `role:steward` scopes to `("email_only", None)`. The no-backfill / no-existing-org-disruption guarantee. |
| Serializer surface test | Yes | **PASS** — `TestUserOutSurfaceContract::test_all_must_surface_fields_present_on_user_out` asserts each of the four exposed verification fields round-trips through `UserOut`. `test_internal_verification_fields_never_leak` asserts `verification_attestation_id` and `verification_nullifier` are NEVER serialized (defense in depth). `test_verification_state_default_is_email_only` asserts the default-value contract for Phase 52's enforcement layer. |
| Migration cycle test | Yes | **2/2 PASS** — `test_phase_51_upgrade_adds_verification_columns` + `test_phase_51_upgrade_downgrade_upgrade_cycle`. Upgrade adds all six columns; downgrade drops all six cleanly; round-trip clean on SQLite. |
| PG smoke `--mode both --prior-revision b9c2e0f43215` | Yes | **PASS (all modes)** — fresh-DB bootstrap + upgrade-from-prior both succeed against postgres:16-alpine. |
| Demo seed compatibility | Yes | **PASS** — `TestDemoSeedStub` covers three scenarios: new persona stamped with `identity_unique` + `demo_stub` + `DEMO`; re-running the seed is idempotent and doesn't move `updated_at`; a real `persona` record on a demo username is NOT downgraded by a subsequent seed run. Demo reset post-deploy: TBD (will confirm after deploy lands). |
| Frontend build | Yes | **PASS** — new bundle `index-BXYiuSeI.js` live on prod (no PWA cache issues observed; verified after deploy). |
| `bash start.sh` prod-mimic | Not required | The pass does not touch `start.sh`, the worker, Dockerfile, railway.toml, or alembic ordering. Local boot-mimic confirmed `digest_loop` + `run_one_tick` still complete cleanly with the new columns present + the Phase 51 tick step (none) absent. |
| Backend deploy success verification | Yes | **PASS** — Railway deploy `3e88f768` SUCCESS; `/api/health` 200; digest scheduler ticked at `2026-06-03T12:50:59Z`. Direct DB inspection confirms `alembic_version=c8d3e1f56432` and all six verification columns are present on `users`. |
| Demo reset post-deploy | Yes | **DEFERRED** — daily reset hasn't run since deploy yet (next firing at midnight Pacific). The seed-pipeline change is exercised by the focused `TestDemoSeedStub` tests (3/3 PASS) which run the actual `_ensure_user` path. Manual trigger via `python scripts/trigger_demo_reset.py` available if Z wants to land the showcase immediately; otherwise the scheduled reset picks it up tonight. |

---

## Branch + commit state

- Branch: `phase-51/verification-state-model`
- Commit on branch: `d61c2be`-equivalent
- Merge commit on master: `d61c2be` (no-ff)
- Pushed to origin/master: confirmed
- Railway deploy: `3e88f768` SUCCESS at 2026-06-03 08:49:48 ET
- Bundle hash on prod: `index-BXYiuSeI.js` (verified live)
- Prod alembic_version: `c8d3e1f56432` (verified)
- All six verification columns present on prod `users` table (verified via direct DB query)
- `/api/health`: 200; digest scheduler ticked at `2026-06-03T12:50:59Z`, `ticks_since_last_success=0`

---

## Forward constraints for Phase 52 (must be honored)

These are the two non-obvious rules Phase 52 must respect:

1. **Nullifier DB UniqueConstraint deferred.** The real uniqueness semantics — what happens when a returning user re-verifies, how a nullifier collision is surfaced to the user/org — are Phase 52 territory. A DB constraint added now would have to be reasoned about against flows that don't exist yet. **Phase 52 must add the `UniqueConstraint` in the same migration that lands the Persona flow that produces real nullifiers**, alongside the corresponding collision-handling logic.

2. **`demo_stub` provenance is "not a real verification."** Any enforcement codepath (the verified-voter filter in `eligible_voter_ids_for_proposal`, the delegation-weight rule, the join / role-grant gates) AND any billing codepath (free-pool counter, per-verification charge) **MUST treat `verification_provenance='demo_stub'` as if the user is unverified** for purposes of counting against quotas, charging, or attributing to a real human. The `demo_stub` marker exists precisely so demo orgs can demonstrate verification-gated flows without running real IDV; honoring this constraint is what keeps that demo-safety property load-bearing.

Both constraints are flagged here for Phase 52's spec writer + implementers.

---

## Tech debt / followups

- **Sub-org verification inheritance** — not modeled here. Phase 52 (or later) decides whether a sub-org's verification gates inherit from the parent's settings or are configurable per-sub-org. The current `get_org_verification_floor` reads `org.settings` only with no parent-chain walk; matches the existing `org_config.py` threshold-helper posture. Tracked for whoever ships sub-org verification.
- **Multi-language jurisdiction codes** — the current implementation expects exact-string equality. A future "state satisfies county" or "US state code → ISO 3166-2 mapping" expansion is a phase-2 concern per the spec; not scoped here.
- **Backdoor endpoint discovery** — the backdoor is at `POST /api/admin/users/{user_id}/verification-state` (platform-admin-only). It's not documented anywhere user-visible by design. Document its existence in any future ops runbook so it's findable in an emergency.
