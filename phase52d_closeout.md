# Phase 52d — Closeout

**Status:** SHIPPED + DEPLOYED 2026-06-04/05
**Branch:** `phase-52d/hash-dedup-infra` (merged --no-ff)
**Master:** `9f37253` (merge of feature commit + tests)
**Migration:** `f1a2b3c4d5e6` (down_revision `e0a1b2c3d4f5`, hex-prefix). Applied on prod, alembic head confirmed.
**No FE bundle change** — backend-only.
**Spec:** `phase52d_hash_dedup_infra_spec.md`

## What shipped (per the D1–D6 sequence)

- **D1 — `key_path_manifest`.** Keys-only walker in
  `verification_provider.py`; extends the 52c redactor with a manifest
  function that emits `{dotted_key_path: type_label}` and nothing
  else. PII-safe by construction — there is no path through it that
  surfaces a value-string.
- **D2 — `backend/verification_hashing.py`.** Pure module computing
  three HMAC-SHA256 hashes under a single platform pepper read from
  `VERIFICATION_HASH_PEPPER`. Normalization is moderate (lowercase +
  NFKD + strip combining marks + strip punctuation + collapse
  whitespace; DOB → ISO `YYYY-MM-DD`; address →
  `"street|city|state|zip"` canonical). Pepper fail-closed: absent
  pepper → `RuntimeError`, no unsalted fallback. Same input + same
  pepper → same hash (load-bearing for dedup matching).
- **D3 — migration `f1a2b3c4d5e6`.** Adds four nullable columns to
  `users` (`doc_number_hash`, `name_dob_address_hash`,
  `name_dob_hash`, `uniqueness_strength`) and four indexes
  (`ix_users_doc_number_hash`, `ix_users_doc_number_hash_unique`
  partial-on-PG, `ix_users_name_dob_address_hash`,
  `ix_users_name_dob_hash`). The pre-existing
  `verification_nullifier` column is left in place + flagged
  deprecated in `models.py`; dropping a partial-unique-indexed column
  on PG is riskier than leaving it. A later cleanup pass can drop
  both the column and `ix_users_verification_nullifier_unique`.
- **D4 — extraction + purge wired into the webhook receiver.**
  `_extract_ocr_fields` pulls document number, first/last name, DOB,
  address from the Didit decision payload (with fallback key
  candidates for the variants Custom KYC may emit; tightened against
  the captured manifest in 52e). `verification_provider.delete_session`
  calls Didit's DELETE endpoint after extraction; failure does NOT
  roll back the verification (fail-toward-keeping-the-verification).
  The purge helper short-circuits on `PROV_DEMO_STUB` so demo
  personas never attempt a real purge.
- **D5 — document-number hard block.** Predicate is
  `hash matches AND different user_id`. Different-user collision →
  reject second write, audit `verification.duplicate_document`,
  bookkeeping row → `collision_rejected`. **Same-user re-verify =
  idempotent, NOT blocked.** That last property is the critical
  correctness guarantee; covered by its own test.
- **D6 — `map_decision_to_state` precedence fix + dead-code removal.**
  Ordinal pick now (`address_on_id` subsumes `identity_unique`);
  uniqueness SOURCE swapped from Didit's 1:N to our-side doc-number
  hash dedup. Dead functions `_decision_passed_1n_dedup` +
  `_extract_nullifier` deleted; mapper no longer emits
  `verification_nullifier`.

## Verification matrix

| Check | Required | Result |
|---|---|---|
| D1 key-path manifest safety test | ✅ | 3 cases — zero PII value-strings in manifest output |
| `compute_hashes` purity + normalization + pepper fail-closed | ✅ | 12 cases — same input → same hash; missing fields → None; pepper-missing → RuntimeError; no unsalted fallback; pepper value changes the hash |
| Precedence-bug regression (`map_decision_to_state`) | ✅ | 5 cases — address subsumes unique; ordinal pick honored |
| Document-number hard block (side-effect + same-user idempotency) | ✅ | 3 cases — different-user blocked + audit row written; same-user re-verify proceeds + state escalates; first-verification writes hash + IDENTITY_UNIQUE |
| Session purge + fail-safe | ✅ | 3 cases — purge called on approved; purge False does NOT erase verification; purge raise does NOT break receiver |
| demo_stub sealed from Didit path | ✅ | 1 case — `_purge_session_best_effort` short-circuits on `PROV_DEMO_STUB`; no provider call |
| Serializer guard | ✅ | 1 case — three new hashes + deprecated nullifier + attestation id all absent from `UserOut` |
| Dead-code removed | ✅ | 3 cases — `_decision_passed_1n_dedup` + `_extract_nullifier` gone; mapper output no longer carries `verification_nullifier` key; obsolete `TestNullifierCollision` deleted from 52a |
| Adjacent regression | ✅ | 467/467 PASS in 3:52 (433 baseline + 34 new) |
| Migration cycle (SQLite) | ✅ | 3 cases — upgrade adds; downgrade-upgrade cycle; multi-NULL tolerance through ORM |
| PG smoke fresh + upgrade-from-e0a1b2c3d4f5 | ✅ | PASS both modes |
| `bash start.sh` prod-mimic | N/A | No start.sh / worker / Dockerfile change |
| Deploy + migration on prod | ✅ | `Running upgrade e0a1b2c3d4f5 -> f1a2b3c4d5e6, phase 52d — hash-dedup fields on users` + Startup complete |
| Prod schema confirmed | ✅ | Direct PG query: 4 new columns present + `verification_nullifier` deprecated-but-kept; 4 new indexes present (`ix_users_doc_number_hash`, `ix_users_doc_number_hash_unique`, `ix_users_name_dob_address_hash`, `ix_users_name_dob_hash`); alembic head = `f1a2b3c4d5e6` |
| Phase 52c capture line still PII-safe post-52d | ✅ | Signed canary fire on prod redacted all 3 PII vectors (`FAILCLOSED_FIRST_NAME`, `FAILCLOSED_LAST`, `FAILCLOSED-DOC-NUM-123456789`) — receiver short-circuited at `unknown_session` (since the canary's session id isn't in the DB) but the capture line still emitted with redaction intact |

## Test count delta

- Phase 52c baseline: 433
- Phase 52d additions: +34 → 467
  - +31 in `test_phase_52d_hash_dedup.py`
  - +3 in `test_phase_52d_migration_cycle.py`
  - Net 0 from 52a/52c migrations (a few 52a tests removed/updated for the dead-code removal; pepper autouse fixture added to 52a + 52c — same total cases)

## Files added / modified

**Backend (9)**
- A `backend/verification_hashing.py` — pure hashing module (D2)
- A `backend/migrations/versions/f1a2b3c4d5e6_phase_52d_hash_dedup_fields.py` (D3)
- A `backend/tests/test_phase_52d_hash_dedup.py` (31 cases)
- A `backend/tests/test_phase_52d_migration_cycle.py` (3 cases)
- M `backend/models.py` — 4 new columns; deprecated-flag comment on `verification_nullifier`
- M `backend/routes/verification.py` — `_extract_ocr_fields`, rewritten `_apply_decision` (D4+D5+D6 wired), `_purge_session_best_effort`, race-collision audit renamed to `verification.duplicate_document`
- M `backend/verification_provider.py` — `key_path_manifest` (D1), `delete_session` (D4), rewritten `map_decision_to_state` with `doc_number_unique=` kwarg (D6), dead `_decision_passed_1n_dedup` + `_extract_nullifier` removed
- M `backend/tests/test_phase_52a_didit_integration.py` — updated mapper-shape tests, removed `TestNullifierCollision`, added pepper fixture
- M `backend/tests/test_phase_52c_payload_capture.py` — added pepper fixture so `_apply_decision` can run

**Spec (1)**
- A `phase52d_hash_dedup_infra_spec.md`

## Deploy verification

- Pre-deploy: master `9f37253` pushed; backend redeployed.
- Backend log: `Running upgrade e0a1b2c3d4f5 -> f1a2b3c4d5e6, phase 52d — hash-dedup fields on users` + Startup complete + Uvicorn running.
- Direct PG schema query on prod confirms 4 new columns + 4 new indexes; alembic head = `f1a2b3c4d5e6`.
- Pepper currently UNSET on Railway by design — `VERIFICATION_HASH_PEPPER` is the Z-action sealed variable. Until set, any verification webhook with a known session id will record `config_error` on the bookkeeping row and leave the user's verification record untouched (proven by the unit test `TestComputeHashes::test_pepper_fail_closed_raises` + the `_apply_decision` pepper-missing branch).
- Phase 52c capture log line still emits + redacts correctly (verified via signed canary fire on prod).

## Deprecated-column flag

`users.verification_nullifier` is no longer written by any code path
in Phase 52d. The column + its partial-unique index
(`ix_users_verification_nullifier_unique`) are left in place because
dropping a partial-unique-indexed column on PG is riskier than
leaving it. A future cleanup pass can drop both. The
`verification_attestation_id` column is still written (it carries
Didit's session id for audit + record-keeping).

## Phase boundary handoff to 52e

**52d complete; 52e gated on TWO Z-actions:**

1. **Z sets the real `VERIFICATION_HASH_PEPPER` as a Railway SEALED
   variable.** Sealed = write-only, can't be read back in the
   dashboard. The team never sees the real pepper. Z backs it up in
   a password manager (sealed = unrecoverable from Railway). Single
   platform-wide value, never changed (changing orphans all hashes).
   Walked through step-by-step in chat per the spec.

2. **Z re-verifies their own ID on the deployed build** (do NOT
   delete Z's existing verification first — it's the enrollment the
   re-verify must match against). This produces:
   - A real captured payload skeleton (the Phase 52c capture log
     line) showing the exact OCR key paths Didit emits, so 52e can
     tighten `_extract_ocr_fields` against ground truth instead of
     the documented-shape fallbacks.
   - The first three real hashes in prod (`doc_number_hash`,
     `name_dob_address_hash`, `name_dob_hash`) so 52e's hard-block +
     name-flag lookups have at least one real row to exercise
     against.
   - A real same-user re-verify side-effect test against Z's own
     record (the spec's load-bearing correctness property — must not
     self-block).

When both Z-actions are done, 52e picks up: the name-based org-
scoped flags, the three modes (verification-to-join, verification-
to-act, no-verification), the derived `is_org_verified` predicate,
and the unified capability config.

## For Z review

1. **Pepper-fail-closed is load-bearing.** A deploy without
   `VERIFICATION_HASH_PEPPER` set produces no real hash, no state
   write, no purge. Today's prod is exactly that state — the
   migration applied + the receiver is alive + every approved
   webhook records `config_error` on its bookkeeping row until the
   pepper is set. That is the intended phase boundary, not a bug.
2. **`verification_nullifier` deprecated, not dropped.** Confirmed
   left in place because the partial-unique index on it can't be
   safely dropped in the same migration that adds
   `doc_number_hash`'s replacement partial-unique index without
   risking either a race window where neither is enforced or a
   migration ordering hazard. Future cleanup pass.
3. **52c capture line continues to redact correctly post-52d.**
   Canary fire on prod produced the redacted skeleton, all three
   canary PII strings absent. The redactor + manifest disciplines
   continue to hold.
4. **Same-user re-verify idempotency.** This is the critical
   correctness property — if it broke, every legitimate re-verify
   would self-block. Test
   `TestDocumentNumberHardBlock::test_same_user_reverify_idempotent_not_blocked`
   covers it with both directions (the seeded same-user case writes
   no duplicate-document audit; the seeded different-user case does).

## Branch state

- `phase-52d/hash-dedup-infra` merged via `9f37253` (--no-ff); safe
  to delete at next cleanup.
- master at `9f37253`, pushed to origin, Railway deployed.

**52d complete; 52e gated on (1) Z sets the real
`VERIFICATION_HASH_PEPPER` sealed variable in Railway and (2) Z
re-verifies on the deployed build.**
