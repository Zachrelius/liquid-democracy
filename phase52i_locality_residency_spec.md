# Phase 52i — City/Locality Residency Gating (Hashed, Two Independent Levels)

**Status:** Spec + dispatch. Written 2026-06-06. The final phase of the ID-verification arc's planned field-capture set.

Reading order: this doc; `id_verification_arc_backlog.md` (the "City-level residency / multi-level jurisdiction" locked decision — hashed, two independent levels, exact-match); the shipped `backend/verification_hashing.py` (the hash machinery this REUSES — `normalize_text`, `normalize_address`, `_h`, the pepper); `backend/verification_provider.py` (`normalize_jurisdiction` + `_extract_jurisdiction` — the state-level precedent this mirrors at city level); `backend/routes/verification.py` `_apply_decision` (where the locality hash gets computed + stored); `backend/verification.py` (`get_org_verification_floor` + `subsumes` — the gate pattern, though locality is a SEPARATE dimension, see below).

## Goal

Let an org gate membership / participation on **city-level residency**, in addition to the existing state-level (`verification_jurisdiction`) gate. The two levels are **independent** — an org gates on state OR city OR both, with NO hierarchy (a state gate is not auto-satisfied by a city within it, and vice versa; each is an exact match on its own level). City is stored **HASHED, never readable** — reusing the same pepper + hash machinery as the dedup hashes, so no readable city PII is ever persisted.

## Locked values decisions (from the backlog — settled, do not re-litigate)

- **Hashed city, not readable.** `hash(pepper + normalized_city + normalized_state)` stored on the user as `verification_locality_hash`. The org's configured gate-city is hashed the same way; gating = exact-hash-equality. No readable city stored anywhere.
- **Two independent levels, no hierarchy/subsumption.** State (`verification_jurisdiction`, already exists, readable) + city (`verification_locality_hash`, new, hashed). An org may require either or both. Exact-match on each level independently — NO "state gate satisfied by any city in it" logic. (Z chose this over a subsumption hierarchy.)
- **Why hashed is the right call here (the city case, distinct from the legal-name case):** the org CONFIGURES the gate value (a specific city, e.g. "Somerville"), so both sides of the comparison are known — the system hashes the member's city and the org's gate-city and compares. That's exactly what a hash supports. (Contrast 52f legal-name-match, where the system must compare an ARBITRARY user-entered display name against the legal name, which a hash can't do — hence readable there, hashed here.)
- **Accepted costs (locked):** admins CAN'T see/display members' cities (gating returns a boolean "matches the gate," never the city); NO fuzzy or hierarchical matching (exact equality only — a small explicit town list can be OR-matched by hashing each, but no counties/ranges); and the pepper's protection is BOUNDED for city specifically because city is low-entropy (~hundreds per state) — if BOTH the DB and the pepper leak, hashed-city is brute-forceable. Acceptable because the goal is "not stored casually readable," not secrecy.
- **No purge-fix dependency.** Hashed city adds no readable PII, so it's independent of the Didit session-purge fix. Sequence freely.

## Design — data model

Add to `User` (additive, nullable):
- `verification_locality_hash` (String(128), nullable, indexed only if a lookup needs it — for GATING it's compared to a computed value, not looked-up-by, so an index is likely NOT needed; confirm. Unlike the dedup hashes, this is never searched across users — it's compared to the org's gate-city hash for the one user being gated. So no index unless a future feature searches by it.)

NOT added: any readable city column. The `parsed_address.city` value is read transiently in `_apply_decision`, hashed, and discarded with the rest of the address (exactly as it already is for the `name_dob_address_hash` input — city already flows through there and is discarded; this phase additionally computes a standalone locality hash from it).

## Design — the hashing

Reuse `verification_hashing.py` — do NOT write a second hasher.
- Add a `compute_locality_hash(city, state) -> Optional[str]` to `verification_hashing.py`, mirroring the existing `_h` + `normalize_text` pattern:
  - Normalize city via the existing `normalize_text` (lowercase/NFKD/strip-marks/strip-punct/collapse-ws — same as the name hashes).
  - Normalize state to the 2-letter code via `verification_provider.normalize_jurisdiction` (so "Massachusetts"/"MA" both canonicalize — consistency with how `verification_jurisdiction` is already derived).
  - Return `_h(["locality_v1", normalized_city, normalized_state])` — the version prefix + the unit-separator join, exactly like the existing hashes. Include the STATE in the hash so "Springfield, MA" ≠ "Springfield, IL" (city names collide across states; hashing city-with-state disambiguates).
  - Return None if city or state is absent/unnormalizable (fail-safe — a user with no parseable city simply has no locality hash and fails any city gate, the safe direction).
- **Pepper:** same `VERIFICATION_HASH_PEPPER`, same fail-closed behavior (absent pepper → the existing `_require_pepper` raises). No new secret.

## Design — compute-and-discard

In `routes/verification.py` `_apply_decision`, alongside the existing hash extraction + (post-52f/52g) the legal-name + age-band capture:
- Read `parsed_address.city` + `parsed_address.region` (state) from the decision — the SAME fields the address hash + jurisdiction already use (confirmed real paths from the 52e grounding: `decision.id_verifications[0].parsed_address.{city, region}`).
- Compute `verification_locality_hash = compute_locality_hash(city, region)`; store it on the user.
- The readable city is NOT persisted (it's already discarded today; this phase just also derives the hash before discard).
- demo_stub / backdoor: no real payload → no locality hash; demo path sealed.

## Design — the gate

City is a SEPARATE dimension from the state-level jurisdiction (which lives inside `subsumes` rule 2 as a string-equality check on `verification_jurisdiction`). Two clean implementation options — recommend the parallel-helper approach for clarity:

- New settings key on `Organization.settings`:
  - `verification_membership_locality` (string, nullable) — the gate-city (readable, as the ADMIN enters it; it's the org's own config value, not member PII). When set, a joining/gated member must have a `verification_locality_hash` equal to `compute_locality_hash(verification_membership_locality, verification_membership_jurisdiction)`.
  - **Important:** the gate-city must be hashed WITH a state to match the member-side hash (which includes state). The org's existing `verification_membership_jurisdiction` (state) is the natural state to pair it with. So a city gate REQUIRES a state to be set too (you can't gate "Springfield" without saying which state — that's the city-name-collision problem). Enforce at config time: setting a membership locality requires a membership jurisdiction. Surface this in the OrgSettings UI (the city field is enabled only once a state is chosen).
- A predicate `user_meets_locality(user, org) -> bool`:
  - If no `verification_membership_locality` set → True (no city gate).
  - Else compute the gate-city hash (city + the org's jurisdiction) and compare to `user.verification_locality_hash`. Equal → True.
  - A user with no `verification_locality_hash` → False against any set city gate (the safe direction).
  - Centralized; never reimplemented at call sites (same discipline as `user_satisfies_floor`).
- **Composition:** the membership gate now checks state floor (existing `check_membership_floor_for_join`) AND city (`user_meets_locality`) when both are set. Either failing → blocked. Extend the structured-403 so the FE can distinguish "must be a resident of {city}" from "must verify ID" / "must be in {state}". (Per-proposal city gating is possible but NOT in this phase unless trivial — membership-level is the locked scope; flag if the team wants to add the proposal column in the same pass, but default to membership-only.)
- **Cardinality-floor invariant (same as every gate):** a city requirement on a role/membership gates the GRANT; a config change (org adds/changes a city gate) must NOT auto-strip a seated role / remove a member below the governor floor. Same construction as the verification-floor checks — block the mutation, never demote the incumbent. Test it.

## Verification matrix

| Check | Required | Notes |
|---|---|---|
| Locality hash computed + stored, city discarded | ✅ | A real verification (with a parseable city) produces `verification_locality_hash`; assert NO readable city column exists / is written (grep the write path). |
| Hash includes state (cross-state disambiguation) | ✅ | "Springfield, MA" and "Springfield, IL" produce DIFFERENT hashes. Unit-test with the two. |
| `compute_locality_hash` reuses the pepper + normalization | ✅ | Same pepper, same `normalize_text` + `normalize_jurisdiction`; absent pepper raises (fail-closed); absent city/state → None. |
| `user_meets_locality` predicate | ✅ | Member city-hash == gate city-hash → True; mismatch → False; no member hash → False; no gate set → True. |
| City gate requires a state (config validation) | ✅ | Setting `verification_membership_locality` without `verification_membership_jurisdiction` is rejected at config time. |
| Two independent levels, no subsumption | ✅ | A member matching the city but NOT the state gate fails the state gate (and vice versa); neither auto-satisfies the other. Assert both directions. |
| Composition with state floor | ✅ | An org gating on BOTH state and city checks both; either failing blocks join. |
| Membership gate side-effect | ✅ | Non-matching-city user blocked from join with the locality-scoped structured 403; matching passes. Assert membership row state. |
| Cardinality-floor on city-gated role/membership | ✅ | Adding a city gate doesn't auto-strip a seated incumbent below the governor floor. Mirror the verification-floor role test. |
| demo_stub sealed | ✅ | No real payload → no locality hash; demo path unaffected. |
| Additive-layer parity | ✅ | Org with no city gate → byte-for-byte today. |
| Serializer | ✅ | `verification_locality_hash` NEVER serialized to any client (it's a hash, same as the dedup hashes — extend the existing serializer-exclusion guard). The gate exposes only a boolean if any UI needs it. |
| Migration (locality hash column + setting) cycle + PG smoke both modes | ✅ | Additive nullable column. Confirm `alembic heads` single head at branch time (52f/52g will have advanced it past `e6f7a8b9c0d1`; stack on the real head, don't assume). |
| Adjacent regression | ✅ | Full suite green. |

## Sequence
Confirm head (52f/52g may be ahead) → migration (locality hash column) → `compute_locality_hash` in `verification_hashing.py` → compute-and-discard in `_apply_decision` → `user_meets_locality` predicate + config validation (city requires state) → membership gate composition + structured-403 extension → FE (org settings: city field gated behind a state choice; the locality-scoped 403 copy) → serializer exclusion. Deploy.

## Z-action items
- **None to run.** No Didit console work, no re-verify required to ship. Same "existing verified users light up on next re-verify" property as 52f/52g/locality — a user's `verification_locality_hash` populates on their next verification (the city was discarded on prior verifications, so no backfill is possible — same as the age band). For the ~1-real-user pre-launch state, fine; note it.
- **The "verify once, light up everything" bundling note (carried from 52f/52g):** 52f (legal name), 52g (age band), and 52i (locality hash) ALL populate only on a user's next verification. If minimizing re-verification matters, these three benefit from shipping close together so ONE re-verify populates legal name + age band + locality hash at once. They're independent enough to ship separately (and 52f/52g are already in flight), but if 52i lands soon after, a single Z re-verify covers all three. Flag for Z's sequencing call — no hard dependency.

## Notes for the team
- **Reuse, don't reinvent:** `compute_locality_hash` belongs IN `verification_hashing.py` next to the existing hashes, using `_h` + `normalize_text` + (imported) `normalize_jurisdiction`. Do NOT write a parallel hashing path or a second normalizer.
- **The state-in-the-hash decision is load-bearing** — without it, "Springfield" collides across ~30 states and a city gate would match residents of the wrong Springfield. Always hash city WITH its state.
- **No index needed (probably):** unlike the dedup hashes (searched across users to find matches), the locality hash is only ever compared to the org's computed gate-hash for the single user being gated — no cross-user lookup. Skip the index unless a future feature searches by locality. Confirm + note.
- **This is the last planned phase of the field-capture arc.** After 52f/52g/52i, the verified user carries: state jurisdiction (readable), city locality (hashed), legal name (readable, 52f), age band (derived, 52g), plus the two name-based dedup hashes. That's the full long-term field set — a user who verifies once lights up every gate the platform supports. The remaining arc items are operational (purge fix, admin UI) or entity-gated (billing).
