# Phase 52d — Hash Dedup Infrastructure + Document-Number Hard Block

**Status:** Spec + dispatch. Written 2026-06-04. Supersedes all earlier 52d drafts (the Didit-1:N nullifier approach is obsolete).

Reading order: this doc; `id_verification_arc_backlog.md` §"Locked values decisions" (the document-hash dedup model + three modes — READ THIS, the full design lives there); the shipped `backend/verification.py` (the enforcement helpers this builds alongside) + `backend/verification_provider.py` (the mapper + redactor + the dead 1:N code this removes).

**Why this phase ends where it does (the pepper boundary).** Per the phase-boundary rule, a required Z-action is a phase boundary. This phase needs the `VERIFICATION_HASH_PEPPER` set in Railway (a Z-action — Z sets a sealed variable + backs it up) before real hashing can run in prod, AND it needs the Z re-verify to ground the real OCR field keys. Both are Z-actions. So this phase builds everything that can be built + verified WITHOUT the real pepper or a real payload (against a dummy pepper + synthetic payloads), deploys, and STOPS at: "infrastructure shipped, dummy-pepper-tested, awaiting Z to (1) set the real sealed pepper and (2) re-verify." Phase 52e picks up after both Z-actions.

---

## What this builds (summary — full model in the backlog)

Dedup is **our-side hashing of Didit's OCR/MRZ fields**, NOT Didit's 1:N. This phase builds:
- Safe field-key discovery (so 52e can target the real OCR keys).
- The hashing module: three salted hashes (document-number, name+DOB+address, name+DOB) under a single platform pepper.
- The **document-number platform-wide hard block** (repurposes the shipped collision infra from the deprecated nullifier).
- Session purge after extraction (process-and-purge — no biometric/PII retained).
- The `map_decision_to_state` precedence-bug fix + removal of the dead Didit-1:N code.

The **name-based org-scoped flags, the three modes, the derived `is_org_verified` predicate, and the unified capability config are Phase 52e** — they need the real OCR keys (from the Z re-verify) and are the bigger surface. This phase is the infrastructure floor they sit on.

---

## Dispatch framing

### Goal
Ship the hashing infrastructure + the document-number hard block, fully built and tested against a **dummy pepper** and **synthetic payloads**, deployed. End at the pepper/re-verify boundary. No real verification produces a real hash until Z sets the sealed pepper (next, between phases) — that's correct and intended; the code reads the pepper from env and refuses to hash (fail closed) if it's absent.

### Branch + merge
`phase-52d/hash-dedup-infra`. `--no-ff` to master per CLAUDE.md.

### Migration head — CONFIRM
Run `alembic heads` at branch time. Candidates from the file listing: 52a's `e0a1b2c3d4f5` and 52's `d9e4f2a78543` (52c was log-only, no migration). Do NOT assume which is the true single head — confirm; multi-head → STOP and flag. Hex-prefix revision id.

### Verification matrix
| Check | Required | Notes |
|---|---|---|
| D1 key-path manifest safety test | ✅ | Manifest = keys + types only, ZERO value-strings. Gating safety test (extends the 52c redactor discipline). |
| `compute_hashes` unit tests (pure) | ✅ | Every field-presence combo; same input → same hash; normalization cases; missing field → None. Tested with a DUMMY pepper fixture. |
| Pepper fail-closed | ✅ | Absent `VERIFICATION_HASH_PEPPER` → hashing RAISES (never falls back to unsalted). Test asserts the raise. |
| Document-number hard-block (side-effect) | ✅ | Different user, same doc-hash → second write rejected + audit row. SAME user, same doc-hash → idempotent, NOT blocked (the critical correctness property). Assert row state, not status code. |
| Precedence-bug regression | ✅ | `map_decision_to_state`: address + unique → highest rung (`address_on_id` subsumes `identity_unique`); unique-without-address → `identity_unique`. |
| Session purge + fail-safe | ✅ | `DELETE` called after extraction; a FAILED purge does NOT lose the verification (retry/log, never drop the identity record). demo_stub never purged (no real session). |
| Partial-unique migration cycle + PG smoke both modes | ✅ | On `doc_number_hash` (repurposing the nullifier partial-unique pattern); multi-NULL tolerance PG + SQLite (Phase 18 note). Confirm single head first. |
| demo_stub sealed | ✅ | No real hashes, no session, no purge on demo_stub rows. Assert. |
| Dead-code removed | ✅ | `_decision_passed_1n_dedup` + `_extract_nullifier` + their probes + tests gone; suite green without them. |
| Adjacent regression | ✅ | The ~433 set green; enforcement/tally untouched (this phase changes state *production*, not the gates that read it). |
| Serializer | ✅ | The three hashes NEVER serialized to any client (cross-user correlation handles). Extend the `_MUST_SURFACE_FIELDS` exclusion. |
| `bash start.sh` prod-mimic | ⚠️ Conditional | If the purge-retry uses a worker/scheduled sweep, REQUIRED. If inline/background-task only, N/A — state which in the closeout. |

### Team
Continuing dev team (owns the mapper + redactor from 52a/52c). Lead: confirm alembic head, run migration + PG smoke, closeout. Backend dev: D1–D6 below. QA: the two safety tests (manifest, hash purity/fail-closed) + the hard-block side-effect.

---

## Spec body — clusters

### D1 — safe field-key discovery
The 52c redactor (shipped) redacts the OCR fields we now need to hash (document_number, names, DOB, address → `<str:N>`), so we can see WHERE they sit but not the exact key paths. Add a **platform-admin-only, keys-only** manifest mode: log/return the full set of key-PATHS present in a decision payload (keys + value-types only, NEVER values). Recommend extending the existing redactor with a "manifest" flag rather than a new mechanism — a key-path manifest is keys-only by construction, inherently PII-safe, no teardown needed.
- **Safety test (gating):** feed a synthetic payload with fake PII through the manifest fn → assert output contains zero value-strings, only key-paths + type labels.
- This produces the input 52e needs (real key paths from the Z re-verify) but can be built + tested now against the 52c-captured structure + synthetic payloads. The real-payload grounding happens in 52e.

### D2 — the hashing module (`verification_hashing.py`, pure, no DB)
- `compute_hashes(fields: dict) -> dict` → `{doc_number_hash, name_dob_address_hash, name_dob_hash}` (any None if its source field absent). Pure; exhaustively unit-tested.
- **Pepper:** read `VERIFICATION_HASH_PEPPER` from env. Single platform-wide value, applied to every hash (`sha256(pepper + normalized_input)` or HMAC — team's call, document it). **NOT per-user** (per-user salt breaks matching — the same person must hash identically across verifications). **Fail closed:** absent pepper → raise, never unsalted fallback.
- **Normalization (load-bearing — tunes the false-positive/miss tradeoff):** moderate — lowercase, strip whitespace/punctuation/accents, collapse internal spaces. Do NOT aggressive-nickname-collapse or drop middle names (accept misses over false positives — a false block is disenfranchisement, a miss is just imperfect dedup). DOB → ISO `YYYY-MM-DD`. Address → the same canonical form the residency `address_on_id` path uses (reuse, don't fork). Document the exact normalization in the module docstring so 52e's real-data test + future provider swaps can reason about it.
- Inputs come from Didit's OCR/MRZ extraction (NOT user free-text), so name strings are document-stable.

### D3 — model fields + migration
On `User` (additive, `server_default` per the established pattern — same as the Phase 51 verification columns):
- `doc_number_hash` (String(128), nullable, indexed). **Repurpose the 52a nullifier partial-unique-index pattern** — the platform-wide uniqueness invariant now lives here (filtered unique WHERE NOT NULL; confirm multi-NULL tolerance PG + SQLite per the Phase 18 note).
- `name_dob_address_hash` (String(128), nullable, indexed — NOT unique; matching is a lookup, not a constraint).
- `name_dob_hash` (String(128), nullable, indexed — NOT unique).
- `uniqueness_strength` (String(16), nullable; `document_hash` now, `biometric` reserved for a deferred tier). NULL until a unique-tier verification completes.
- **The old `verification_nullifier` column** (Phase 51, now unused): do NOT drop it here (a drop migration on a partial-unique-indexed column is riskier than leaving it; 52a logic referenced it). Mark deprecated in a comment, repoint logic to `doc_number_hash`. A later cleanup pass drops it. Flag in closeout.

### D4 — wire extraction + purge into the webhook handler
- After a passed ID verification: extract the OCR fields, call `compute_hashes`, write the hashes + `uniqueness_strength='document_hash'` + the existing derived state/jurisdiction (via the corrected mapper, D6).
- **Then purge the Didit session:** add `verification_provider.delete_session(session_id)` (DELETE `/v3/sessions/{id}/` or the documented Didit deletion endpoint — confirm the exact path from Didit docs at build) in the swappable provider seam. **Fail toward keeping the verification:** if delete fails, the verification record still stands; retry/log, never lose the identity verification because cleanup failed. A background retry or a swept pending-delete list is fine; don't block the webhook 200 on it.
- **demo_stub never hits this path** — no real session, no hashes, no purge. Assert.

### D5 — document-number hard block (repurpose 52a collision logic)
- On a verification whose `doc_number_hash` matches an EXISTING DIFFERENT user: **platform-wide hard block** — reject the second account's verification write, leave it at prior state, audit `verification.duplicate_document` (repurpose the old `nullifier_collision` audit action name or rename — make it mean "doc-number hard block").
- **Same-user re-verify = idempotent, NOT a block.** The check is `match AND different user_id`. A false block on self-re-verify breaks legitimate re-verification — this is the critical correctness property; test it explicitly.
- Side-effect-asserting tests (row state + audit row), not status codes — the load-bearing test property for anything mutating verification state.

### D6 — `map_decision_to_state` precedence fix + dead-code removal
- **Precedence fix:** the shipped mapper does `if jurisdiction → ADDRESS_ON_ID / elif dedup_passed → IDENTITY_UNIQUE / else IDENTITY`, wrongly making address + uniqueness mutually exclusive. The model is ordinal (`address_on_id` rung 3 subsumes `identity_unique` rung 2). Correct so the assigned state is the highest satisfied rung. **Under the new model, "unique" comes from the hash dedup** (doc-number didn't collide → eligible for `identity_unique`), NOT a Didit dedup block — so a passed ID with a non-colliding doc-number hash + no address → `identity_unique`; with address → `address_on_id` (subsumes unique). Encode in `verification.py` rung terms, tested.
- **Remove dead code:** `_decision_passed_1n_dedup`, `_extract_nullifier`, and their probes are obsolete (not using Didit's 1:N). Delete them + their tests. Note in closeout.

### Sequence
D1 (manifest + safety test) → D2 (hashing module + tests, dummy pepper) → D3 (migration) → D6 (mapper fix + dead-code removal) → D4 (extraction + purge) → D5 (hard block). Deploy. **End here.**

## Invariants
- **Pepper fail-closed + env-only + never in repo/chat/dispatch.** Team builds against a dummy; the real sealed pepper is Z's between-phases action.
- **Hashes never serialized** to any client.
- **demo_stub sealed:** no real hashes, no session, no purge.
- **Hybrid pattern:** purge the Didit session after extraction; retain only hashes + derived fields. No raw doc-number/DOB/biometric/images.
- **Fail toward the weaker valid state:** a purge/extraction hiccup never destroys a valid `identity` verification.
- **Enforcement/tally untouched:** this phase changes state *production*, not the gates that read it. Adjacent sweep proves it.

## Closeout must report
Key-path-manifest safety result; `compute_hashes` purity + the documented normalization + pepper-fail-closed confirmation; doc-number hard-block side-effect (+ self-reverify-idempotent); session-purge fail-safe; partial-unique migration + PG smoke both modes on a confirmed single head; dead-code removal; the deprecated-`verification_nullifier`-column note; serializer exclusion; adjacent sweep green; `bash start.sh` result if a deploy-time path was touched. Plus the explicit handoff line: **52d complete; 52e gated on TWO Z-actions — (1) Z sets the real `VERIFICATION_HASH_PEPPER` sealed variable in Railway, (2) Z re-verifies to ground the real OCR keys.**

## Z-action items
- **None to run THIS phase.** It builds + tests against a dummy pepper + synthetic payloads.
- **After this ships (the phase boundary → walked through in chat):**
  1. **Set `VERIFICATION_HASH_PEPPER` as a Railway SEALED variable** + back it up in a password manager (sealed = unreadable afterward). Permanent, never-change. Walked through step-by-step in chat.
  2. **Re-verify** (Z's own ID) on the deployed build so a real payload exists for 52e to ground the real OCR key paths. (Don't delete the existing verification first.)
  These two unblock 52e.
