# Phase 52i — Closeout

**Status:** SHIPPED + DEPLOYED 2026-06-06. The final phase of the ID-verification arc's field-capture set.
**Branch:** `phase-52i/locality-residency` (merged `--no-ff`).
**Master:** `2726de6` (phase commit) → `1bf0d4a` (merge commit) → `<this commit>` (closeout).
**Migration:** `a8b9c0d1e2f3` (down `f7a8b9c0d1e2`, hex-prefix). Applied on prod.
**Bundle:** `index-n8l9QaMJ.js → index-C7TTC6pJ.js` (live).
**Spec:** `phase52i_locality_residency_spec.md`.

## What shipped

### Migration `a8b9c0d1e2f3`
Adds:
- `users.verification_locality_hash` (String 128, nullable, no index) — the HMAC-SHA256 hash of `(normalized_city, normalized_state)`, computed at verify time and stored in place of any readable city.

All nullable / additive. Reversible (batch_alter_table). Prod deploy log confirms: `Running upgrade f7a8b9c0d1e2 -> a8b9c0d1e2f3, phase 52i — city/locality residency gating (hashed)`. Bundle hash flipped to `index-C7TTC6pJ.js`. Backend `/api/health` returns 200.

### `verification_hashing.compute_locality_hash(city, state)`
- Reuses the existing `_h` + `VERIFICATION_HASH_PEPPER` machinery — no second hasher, no second secret, same fail-closed behavior (absent pepper → `RuntimeError`).
- City normalized via `normalize_text` (lowercase / NFKD / strip-marks / strip-punct / collapse-ws — identical to the dedup hashes).
- State normalized via `verification_provider.normalize_jurisdiction` (so "Massachusetts"/"MA" canonicalize identically — consistent with how `verification_jurisdiction` is already derived).
- Version-prefixed `"locality_v1"` — schema-versioned for future migrations off this format.
- **State is in the hash.** Load-bearing for correctness: "Springfield, MA" and "Springfield, IL" produce DIFFERENT hashes. Without it, a city gate would match residents of the wrong Springfield. Asserted explicitly in `TestComputeLocalityHash::test_state_in_hash_disambiguates_springfields`.
- Returns `None` on missing or unnormalizable inputs (fail-safe — a user with no parseable city has no hash, so they fail any city gate; the safe direction).

### `_apply_decision` compute-and-discard
- Reads `parsed_address.{city, region}` from the decision payload (same fields the address dedup hash + the jurisdiction already use; confirmed from Phase 52e grounding).
- Hashes them via `compute_locality_hash`, stores ONLY the hash on `user.verification_locality_hash`. The readable city is never persisted — it's already discarded today; this phase just additionally derives the hash before discard.
- Wrapped in try/except so a hash-computation failure never blocks the broader verification write (the verification still completes; the user just won't pass any city gate until they re-verify with a parseable address).
- `demo_stub` / `backdoor` provenance paths have no real payload → no locality hash. Demo path sealed.

### Gate predicate + helper
- `SETTING_MEMBERSHIP_LOCALITY = "verification_membership_locality"` — the org's gate-city value (admin-entered, readable on the org config; it's the org's own value, not member PII).
- `_gate_city_for_org(org)` — returns `(gate_city, gate_state)`. **Fails safe** if the org has a city configured but no jurisdiction (state) — returns `(None, None)`, which the predicate treats as "no gate." Defensive misconfig handling: the FE primarily enforces city-requires-state, but a server-side safety net prevents an admin who bypasses the UI from accidentally locking everyone out with an unhashable gate config.
- `user_meets_locality(user, org)` — True when no gate, or when the member's hash equals the org's gate-city hash (computed lazily via `compute_locality_hash`).
- `check_membership_locality_for_join(user, org)` — raises 403 with structured detail `{error: "verification_required", scope: "locality", locality_city, locality_state}`. Wired into all three join paths (`create_join_request`, `request_join`, `accept_invitation`) alongside the existing floor + min-age checks.

### Two independent levels — NO subsumption
This is the architectural decision the spec's locked-decisions section enforces and the test matrix proves. The state-level gate (`verification_jurisdiction`, readable, exact-match on the 2-letter code) and the city-level gate (`verification_locality_hash`, hashed, exact-match on the hash) are **completely independent dimensions**. An org may set either, both, or neither. A city match does NOT auto-satisfy a state gate (you could match the city hash but have a `verification_jurisdiction` that doesn't equal the gate state — rare in practice but possible). A state match does NOT auto-satisfy a city gate (you're in the right state but the wrong city). Both directions are explicitly asserted in `TestIndependentLevels`.

The rationale (locked by Z over a subsumption hierarchy): subsumption would require a city-to-state lookup table the platform doesn't own and can't reliably maintain; exact-match-per-level is correct-by-construction and matches the existing `verification_jurisdiction` pattern.

### FE
- `OrgSettings.jsx`: city input rendered after the jurisdiction input. Gated behind BOTH a residency floor (`address_on_id` or `residency_verified`) AND a jurisdiction (state) choice — the field is disabled until both prerequisites are satisfied. Help text explains the cross-state disambiguation rule. Empty string clears the gate.
- `verificationLabels.js`: `ctaCopyForVerificationRequired` now handles `detail.scope === 'locality'` and returns "This organization requires members to be verified residents of {city}{, state}." The city + state values come from the structured-403 payload (the gate values are readable on the org side, so showing them in the CTA leaks no member PII).

## Verification matrix

| Check | Required | Result |
|---|---|---|
| Locality hash computed + stored, city discarded | ✅ | `TestApplyDecisionCapturesLocalityHash::test_real_payload_populates_hash`. No readable city column written or added. |
| Hash includes state (cross-state disambiguation) | ✅ | `TestComputeLocalityHash::test_state_in_hash_disambiguates_springfields` — "Springfield, MA" ≠ "Springfield, IL". |
| `compute_locality_hash` reuses pepper + normalization | ✅ | Same `VERIFICATION_HASH_PEPPER`; absent pepper raises `RuntimeError`; absent city/state → `None`. |
| `user_meets_locality` predicate | ✅ | `TestUserMeetsLocality` — match → True; mismatch → False; no member hash → False; no gate → True. |
| City gate fails safe when state missing | ✅ | `TestUserMeetsLocality::test_city_without_state_misconfig_acts_as_no_gate` — defensive server-side handling. |
| Two independent levels, no subsumption | ✅ | `TestIndependentLevels` — city match doesn't auto-satisfy state gate; state match doesn't auto-satisfy city gate. |
| Membership gate side-effect | ✅ | `TestMembershipGateSideEffect` — matching passes; non-matching blocked with locality-scoped structured 403; Mode-3 / additive-layer parity asserted (no gate → byte-for-byte today). |
| Cardinality-floor on city-gated membership | ✅ | `TestCardinalityFloorInvariantLocality::test_adding_city_gate_doesnt_strip_seated_steward` — adding a city gate doesn't auto-strip a seated incumbent. |
| Serializer guard | ✅ | `TestSerializerGuard::test_locality_hash_never_on_userout` — `verification_locality_hash` NEVER serialized to any client. |
| demo_stub sealed | ✅ | demo provenance path produces no locality hash. |
| Migration cycle | ✅ | `test_phase_52i_migration_cycle.py` — 2 cases (upgrade adds column; downgrade-upgrade cycle clean). |
| PG smoke both modes | ✅ | `python backend/scripts/pg_smoke.py --mode both --prior-revision f7a8b9c0d1e2` — passed first try. |
| Adjacent regression | ✅ | Full suite green: **572 → 596 (+24)**. |
| Browser QA | PASS-by-source | OrgSettings panel addition is routine surface (a single conditional input wired through an existing settings save path). FE source review confirms the city input renders when state + residency floor both set; empty string clears. |
| Prod deploy | ✅ | Migration line in Railway deploy logs; backend `/api/health` 200; bundle `index-C7TTC6pJ.js` live. |

## Files added/modified

**Added**
- `backend/migrations/versions/a8b9c0d1e2f3_phase_52i_locality_residency.py` (+63)
- `backend/tests/test_phase_52i_locality_residency.py` (+482, 22 cases)
- `backend/tests/test_phase_52i_migration_cycle.py` (+86, 2 cases)
- `phase52i_locality_residency_spec.md` (+89)

**Modified**
- `backend/models.py` (+11) — `verification_locality_hash` column on `User`.
- `backend/verification_hashing.py` (+41) — `compute_locality_hash` + the `"locality_v1"` constant.
- `backend/verification.py` (+101) — `SETTING_MEMBERSHIP_LOCALITY`, `_gate_city_for_org`, `user_meets_locality`, `check_membership_locality_for_join`.
- `backend/routes/verification.py` (+20) — compute-and-discard wiring inside `_apply_decision`.
- `backend/routes/organizations.py` (+6) — locality check wired into the three join paths.
- `frontend/src/pages/admin/OrgSettings.jsx` (+25) — city input in the "Identity verification options" section.
- `frontend/src/verificationLabels.js` (+8) — `scope='locality'` branch in `ctaCopyForVerificationRequired`.

Total: **11 files, +932 lines**.

## Branch + commits
- Branch: `phase-52i/locality-residency` (merged `--no-ff` into master; deleted post-merge).
- Phase commit: `2726de6` — "Phase 52i: city/locality residency gating (hashed, two independent levels)".
- Merge commit: `1bf0d4a` — "Merge phase-52i/locality-residency: Phase 52i — city/locality residency gating (hashed)".
- Pushed: `2f2edb1..1bf0d4a master -> master`.

## Prod deploy verification

- **Railway backend deploy log:**
  ```
  Alembic-stamped DB detected — applying pending migrations…
  INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
  INFO  [alembic.runtime.migration] Will assume transactional DDL.
  INFO  [alembic.runtime.migration] Running upgrade f7a8b9c0d1e2 -> a8b9c0d1e2f3, phase 52i — city/locality residency gating (hashed)
  ```
- **Backend health:** `GET https://www.liquiddemocracy.us/api/health` → `200`.
- **Bundle hash:** `index-C7TTC6pJ.js` live (flipped from `index-n8l9QaMJ.js`).
- **Backend startup clean:** Application startup complete; digest scheduler launched; first tick OK; no errors.

## Design notes worth carrying forward

**"Verify once, light up everything" property.** Phase 52i extends this property — the same DB row write that captures the dedup hashes (52d/52h Stage 2), the legal name (52f), and the age band (52g) now also captures the locality hash. A user who verifies once gets all five field-capture artifacts simultaneously: hashes for dedup, readable legal name for display-name-match, age band for min-age gates, and the locality hash for city-residency gates. No new round-trip to the provider, no incremental verification step.

**Hashed-vs-readable: the principled cut.** The arc has two storage modes for verification artifacts:
- **Readable** when the system must compare against an arbitrary user-provided value the system doesn't know in advance (52f legal-name vs an arbitrary display name).
- **Hashed** when the system compares two values it knows the canonical forms of on both sides (52d/52h Stage 2 dedup, 52i locality — the org enters the gate value, the system hashes the member value).
This is now the clean convention for any future verification field. If a 7-state-arc adds e.g. educational-level gating, the same fork applies: hashable if the org enters the threshold; readable if the system needs to compare against arbitrary text.

**Two independent levels — why no hierarchy.** A subsumption "state gate is satisfied by any city in it" rule would require a platform-maintained city-to-state mapping, which (a) the platform doesn't own and can't keep current, (b) would entangle the gate semantics with reference data we don't want to ship in `start.sh`, and (c) is unnecessary because exact-match-per-level is what admins actually want — an org gating on "Massachusetts" doesn't gate-implicit on every city in Massachusetts; it gates on the canonical state code. The two-independent-levels design matches admin mental model with NO reference-data dependency.

**Bounded pepper protection for city.** Documented in the spec's locked-decisions list and worth restating: city is a low-entropy field (a few hundred to ~thousand candidates per state). If BOTH the production DB AND the platform pepper leak, a `verification_locality_hash` is brute-forceable in seconds (you simply hash every (city, state) pair under the leaked pepper and lookup). That is acceptable for this artifact: the design goal is "not stored casually readable," not "secret under all attacker models." Anyone who has compromised both the DB AND a sealed Railway environment variable has bigger problems than reversing a city.

**No PG smoke followup risk.** The migration adds a single nullable column with no index, no UniqueConstraint, no backfill. Reversible via `batch_alter_table`. Confirmed safe both up and down via PG smoke + the cycle test.

## ID-verification arc — field-capture set complete

With Phase 52i shipped, the planned ID-verification arc's field-capture set is **complete**:

| Phase | Artifact | Storage | Purpose |
|---|---|---|---|
| 52a | Provider integration + Didit purge | n/a (provider-side) | Capture pipeline |
| 52b | Verification state lifecycle | column | Lifecycle source-of-truth |
| 52c | Floor enforcement | code | Gate composition |
| 52d | name_dob_hash, name_dob_address_hash | hashed | Org-scoped dedup |
| 52e Stage 2 | Org-scoped high-confidence flag system | column | Dedup tier |
| 52f | Legal name | readable | Display-name-match |
| 52g | Age band | column | Min-age gates |
| 52h Stage 1 | Org-scoped flag-feature upgrade | code | Pre-removal of doc-block |
| 52h Stage 2 | Doc-number hard block removed | code | One-account-per-person retired |
| **52i** | **Locality hash** | **hashed** | **City-residency gates** |

Five gating dimensions are now live: **identity floor**, **jurisdiction (state)**, **locality (city)**, **age**, **display-name-match**. Each independent. Each composable. Each carries the cardinality-floor invariant (config changes block grants but never auto-strip incumbents). Each respects the additive-layer parity rule (unconfigured orgs unchanged byte-for-byte).

## No new tech debt

No deprecated columns introduced; no backfills required (the column is nullable + populated on next verify). The Phase 52h Stage 2 already-deprecated `users.doc_number_hash` + `users.verification_nullifier` columns remain queued for a future cleanup pass; this phase does not touch them.

## Followups (none blocking)

- Per-proposal locality gating (today the gate is membership-only, per the locked scope). Would require a `Proposal.locality_required` column + a parallel `check_vote_locality_for_proposal` helper. Defer until an org asks for it.
- A small explicit town-list for an org (OR-match against multiple city hashes) is mentioned in the spec as a possible extension. Same pattern as today's per-org single-city, just iterates a list. Defer until requested.
