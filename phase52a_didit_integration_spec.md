# Phase 52a — Didit Integration (Stage 2 of the Phase 52 Greater Phase)

**Status:** Spec + dispatch. Written 2026-06-03, post-Stage-1-ship. Second stage of the verification-enforcement Greater Phase.

Reading order: this doc; the Phase 52 Stage 1 closeout (`phase52_stage1_closeout.md`); `id_verification_research.md` §12 (the Didit pivot + integration shape); the shipped `backend/verification.py`.

**This is Stage 2 of 3.** Stage 1 (enforcement + delegation fork against stubbed state) SHIPPED — migration `d9e4f2a78543`, merge `a89f9b1`, 27/27 + 385/385 + PG smoke green. Stage 52b (free-pool metering) follows this. Dispatch authorizes **52a only**; 52b is a separate verified deploy.

---

## What Stage 1 shipped that 52a builds on

Confirmed against the live `verification.py`:

- **Provenance:** `PROV_DIDIT = "didit"` is defined and in `VALID_PROVENANCES`. `PROV_PERSONA` is kept defined-but-unused; prod confirmed **252/252 users on `provenance='none'`**, zero `persona` rows — no rename needed. Real verifications from this stage stamp `PROV_DIDIT`.
- **The gate predicate + enforcement helpers** (`user_satisfies_floor`, `check_membership_floor_for_join`, `check_role_grant_floor`, `check_vote_floor_for_proposal`, `verification_required_payload`) are live and wired into join/role/vote paths. **52a does NOT touch enforcement** — it only adds the real path to *set* verification state, which the Stage-1 gates already read. Clean separation.
- **Delegation fork** (`delegation_carries_unverified_weight`, default False) is live in `eligible_voter_ids_for_proposal`. Untouched by 52a.
- **`Proposal.verification_floor` + `verification_jurisdiction`** columns shipped (migration `d9e4f2a78543`). `email_only`/`""` normalized to NULL.
- **Backdoor** (`POST /api/admin/users/{user_id}/verification-state`, `PROV_BACKDOOR`) remains the ops-override path. 52a adds the *real* provider path alongside it; the backdoor stays.

**Two forward constraints from Stage 1's closeout that are 52a's job:**
1. **Nullifier `UniqueConstraint` + collision handling** — column shipped in Phase 51 with index only; the uniqueness invariant lands here with the real verifier that produces nullifiers.
2. **`demo_stub` write tightening** — the backdoor currently accepts `demo_stub` onto any user. 52a constrains it (see C-DEMO below). This is now a hard requirement, not a nice-to-have, because 52b's counter and Phase 53's billing both key off `demo_stub` meaning "never real."

---

## Goal

Users verify through Didit's hosted flow; the signed webhook updates their verification record via the hybrid pattern (platform stores attestation id + nullifier + state + coarse jurisdiction — NEVER the document image, selfie, or raw PII). Land the deferred nullifier uniqueness + collision handling. Tighten `demo_stub` so it can only ever sit on demo-only accounts. After this stage: real verification state exists in prod, the Stage-1 gates enforce against it, and the FE "verify now" CTA routes to a real flow. **No free-pool counter and no billing yet** — overage handling is 52b/53; this stage just makes real verification possible. (If the 500/month free pool is a concern during 52a testing: sandbox/test verifications on Didit's free tier are production-grade and count against the pool, so keep test volume modest — but with 252 users and a 500 pool there's ample headroom for this stage's smoke tests.)

## Provider configuration (env, not in this spec)

Secrets go in the **dispatch prompt**, never here (specs sync to public GitHub). The dispatch prompt carries: `DIDIT_API_KEY`, `DIDIT_WEBHOOK_SECRET`, and either a pre-created `DIDIT_WORKFLOW_ID` (recommended — create the ID_VERIFICATION workflow once in the Didit console, pass the id) or authorization to create it programmatically on first use. Railway env vars; the Railway project token is in the dispatch prompt too. **Z-action confirmed:** Z has a Didit account as of 2026-06-03.

Integration shape (from §12, confirmed against Didit docs):
- API root `https://verification.didit.me/v3/`.
- `POST /v3/session/` with `workflow_id` + `vendor_data = user.id` → `session_url`.
- Signed webhook on status change carries a `decision` object (extracted fields incl. parsed address) when `Approved`/`Declined`.
- **Security (load-bearing spec requirements):** API key server-side ONLY, never browser; webhook HMAC-SHA256 verify + `X-Timestamp` freshness ≤300s + idempotent dedupe on `session_id + webhook_type` + return 200 fast; consent/disclosure shown before the session opens.

## Clusters

### C-PROVIDER — `backend/verification_provider.py` (the swappable provider module)
Single module, env-var-configured, so a future provider swap touches one file (the arc's provider-agnostic state model makes this real). Functions:
- `create_session(user_id: str) -> dict` — calls Didit `POST /v3/session/` with `vendor_data=user_id` + the configured `workflow_id`, returns `{session_url, session_id}`. API key from env, server-side.
- `verify_webhook(raw_body: bytes, signature: str, timestamp: str) -> bool` — HMAC-SHA256 over the canonical body, `X-Timestamp` freshness ≤300s, constant-time compare. Returns False on any failure (caller 401s).
- `map_decision_to_state(decision: dict) -> dict` — pure mapper from Didit's `decision` payload to our record fields: `{verification_state, verification_jurisdiction, verification_nullifier, verification_attestation_id}`. **This is the one place provider-specific response shape is interpreted** — keep it pure + unit-tested so a provider swap is "rewrite this mapper." Maps a passed ID check → `IDENTITY`; passed + 1:N face-search dedup → `IDENTITY_UNIQUE`; passed + parsed address present → `ADDRESS_ON_ID` with `verification_jurisdiction` from the address's region (normalized to the same coarse form the gate jurisdiction uses — see C-JURIS). The nullifier comes from Didit's 1:N identity handle (the dedup primitive). Never extract or store raw PII, document images, or selfies — only the derived state + the opaque nullifier + the attestation id + coarse jurisdiction.

### C-SESSION — session-initiation endpoint
Authenticated `POST /api/verification/session`: calls `verification_provider.create_session(current_user.id)`, persists a minimal session-bookkeeping row (see C-MIGRATION), returns `{session_url}`. Rate-limited (reuse the Phase 38 limiter). The consent/disclosure copy (hybrid-pattern privacy text: "We send your ID to Didit to verify your identity; we don't keep a copy of your documents") is returned/shown before the redirect. Never exposes the API key.

### C-WEBHOOK — webhook receiver
`POST /api/webhooks/didit` (unauthenticated by session, authenticated by signature):
1. `verify_webhook(...)` → 401 on failure (bad signature, stale/missing timestamp).
2. **Idempotency:** dedupe on `(session_id, webhook_type)` — a replay is a no-op 200 (the closeout's idempotency requirement). Use the session-bookkeeping table.
3. On `Approved`: `map_decision_to_state(decision)`, then write the record onto the user identified by `vendor_data` (= our `user.id`): set `verification_state`, `verification_jurisdiction`, `verification_attestation_id`, `verification_nullifier`, `verification_provenance = PROV_DIDIT`, `verification_updated_at = now`. **Nullifier collision check first (C-NULLIFIER).** Audit-logged (`verification.completed`, actor = the user, details = state + provenance, NEVER PII).
4. On `Declined`/other: update the bookkeeping row's status; do not change the user's verification_state. Audit `verification.declined`.
5. Return 200 fast; heavy work stays minimal (no external calls in the handler).

### C-NULLIFIER — uniqueness + collision handling (the deferred Phase 51 constraint)
- **Migration** adds the uniqueness invariant on `verification_nullifier`. **Cross-DB NULL caveat (Phase 18 precedent):** most users have NULL nullifier; the constraint must allow many NULLs. Use a partial/filtered unique index (`WHERE verification_nullifier IS NOT NULL`) on PG; confirm the SQLite test-path behavior matches (SQLite treats NULLs as distinct in a UNIQUE index, so a plain unique index also tolerates multiple NULLs — verify both in the migration-cycle + PG-smoke, document the divergence note like Phase 18 did).
- **Collision behavior (VALUES FORK — flagged for Z, see Z-action):** when an incoming verification's nullifier matches an existing row on a *different* user, that's "one human, two accounts." Spec's recommended handling: **reject the second** — do not overwrite, do not merge; leave the second account at its prior state, write an audit `verification.nullifier_collision` (actor = second user, target = first user id), and return a webhook 200 (we accepted the webhook; we declined to apply it) while surfacing to the second user a status of "this identity is already verified on another account, contact support." Do NOT silently merge accounts or move the verification. **Confirm this with Z before finalizing** — it's a real policy call about what duplicate-identity means on a civic platform (could be innocent — shared device — or could be ban-evasion).

### C-DEMO — `demo_stub` write tightening (Z decision locked)
**Rule (locked with Z, 2026-06-03):** `demo_stub` provenance is writable **only onto a demo-only account** — a user every one of whose org memberships is in an `is_demo=True` org. The instant an account holds any real-org membership, it can never receive `demo_stub`.
- Enforce at the backdoor setter (and any provenance writer): reject a `demo_stub` write with 422 if the target user has any non-demo `OrgMembership`. The demo-reset seed path is the only legitimate `demo_stub` writer, onto accounts it owns.
- **Join-direction guard (FORK — flag to Z if non-trivial):** if a `demo_stub` account later joins a real org, that's a state to detect. Recommended: block the join with a structured "demo accounts can't join real orgs" message (demo personas shouldn't be joining real orgs anyway), OR strip the stub on join. Surface to Z as a one-line fork if the join paths make this awkward; default to blocking the join (simplest, matches the "demo world is sealed" intuition).
- Test: a `demo_stub` write onto a user with a real-org membership → 422; onto a demo-only account → OK; the join-direction guard fires.

### C-JURIS — jurisdiction normalization
The gate compares `verification_jurisdiction` by exact string equality (`subsumes` rule 2). So the value Didit's parsed address yields MUST be normalized to the same coarse form an org admin enters when setting a jurisdiction floor. Recommend: US state two-letter codes (e.g. `"CA"`) as the canonical form for v1, since that's the realistic civic case (HOA/union/tenant orgs are state-scoped at most). `map_decision_to_state` normalizes Didit's address region to this form; the OrgSettings jurisdiction input (shipped Stage 1) should constrain/validate to the same vocabulary. **Flag at build:** if Stage 1's jurisdiction input is a free-text field, 52a should tighten it to a controlled vocabulary (state-code picker) so a typo can't silently make a jurisdiction gate unsatisfiable. Small FE follow-up; note it in the closeout if done.

### C-MIGRATION — schema
- The nullifier unique index (C-NULLIFIER).
- A minimal `VerificationSession` bookkeeping table: `(id, user_id, provider_session_id, status, webhook_type_last, created_at, updated_at)` — supports idempotent dedupe + a record of in-flight/declined sessions. Keyed for dedupe on `(provider_session_id, webhook_type_last)` or a separate processed-webhook log; pick the simpler idempotency mechanism and document it. `server_default`s where non-null; no backfill (new table).
- Confirm `alembic heads` shows a single head (Stage 1 left `d9e4f2a78543`; nothing should have stacked since, but confirm). Hex-prefix revision id. Multi-head → STOP.

### C-FE — verification flow
- The "verify now" / "start verification" CTA (Stage 1 closeout noted the placeholder copy "Verification options will become available in a future update" — replace it): the structured-403 prompts and the Settings verification section now route to `POST /api/verification/session` → open `session_url` (Didit JS SDK modal, iframe, or redirect — pick the modal for desktop, redirect for cross-device per Didit's patterns).
- Consent/disclosure shown BEFORE the session opens (hybrid-pattern privacy copy).
- On return, the status reflects (poll the user record or reflect on next load; the webhook is the source of truth, the FE just re-reads).
- Backend state codes never leak into copy (Phase 49a C2 rule; the Stage-1 `verificationLabels.js` is the shared label source — extend it, don't duplicate).

## Verification matrix

| Check | Required | Notes |
|---|---|---|
| Backend pytest (curated adjacent set) | ✅ | Record Stage-1 baseline (385). Target meaningful additions across webhook/provider/nullifier/demo clusters. Match the curated-adjacent convention (the full-repo sweep hit the buffered-output trap in Stage 1 — curated set is correct scope). |
| `map_decision_to_state` unit tests (pure) | ✅ | Every decision shape → expected state + jurisdiction + nullifier. The provider-swap seam; test it exhaustively. |
| Webhook security tests | ✅ | Bad signature → 401; stale/missing `X-Timestamp` → 401; valid → 200 + record written; replay (same session_id+type) → deduped no-op 200. |
| Nullifier collision tests (side-effect) | ✅ | Same nullifier, second user → second account unchanged + `verification.nullifier_collision` audit row written. Assert the row state, not just status. |
| `demo_stub` tightening tests | ✅ | Write onto real-org-member → 422; onto demo-only account → OK; join-direction guard fires. |
| Nullifier-constraint migration cycle + PG smoke both modes | ✅ | Partial unique index; confirm multi-NULL tolerance on BOTH PG and SQLite; document the divergence note. Confirm single head first. |
| **`bash start.sh` prod-mimic** | ⚠️ Conditional | The webhook receiver + session endpoint don't touch start.sh / the worker. IF the `VerificationSession` table or anything else wires a startup/worker hook, the prod-mimic run becomes REQUIRED. Default expectation: not needed for 52a — but state explicitly in the closeout whether a deploy-time path was touched. |
| Live Didit sandbox round-trip | ✅ | One real end-to-end: initiate session → complete Didit's flow (free-tier test verification, production-grade) → webhook received + signature-verified → record written with `PROV_DIDIT`. Observed, not inferred. This is the load-bearing "it actually works" evidence. |
| `demo_stub` never touched by the Didit path | ✅ | A demo-stub user and a real Didit verification coexist; the Didit path never writes onto / never reads-as-real the demo-stub account. |
| Serializer: nullifier still NOT exposed | ✅ | Phase 51 excluded `verification_nullifier` + `verification_attestation_id` from the user-facing serializer. Confirm the exclusion HOLDS now that real nullifiers exist — a leak here is a cross-org correlation handle. Re-assert the `_MUST_SURFACE_FIELDS` guard's exclusion side. |
| FE build + bundle hash | ✅ | C-FE touches FE. Record new hash. PWA-cache caveat (Stage 1 noted SW may mask new bundle). |
| Deploy + demo reset post-deploy | ✅ | Observed. Demo personas still log in; demo-stub state intact. |

## Sequence
1. C-PROVIDER (pure mapper + client + webhook verify) → C-MIGRATION (nullifier index + session table) → C-NULLIFIER (collision logic) → C-WEBHOOK (receiver, uses all of the above) → C-SESSION (initiation) → C-DEMO (tightening) → C-JURIS (normalization) → C-FE.
2. The pure `map_decision_to_state` + `verify_webhook` land + unit-test first (the provider seam, no DB). Then the migration. Then the stateful webhook/session paths on top. C-DEMO can land any time after C-MIGRATION; it's independent of the Didit flow.
3. Land the live sandbox round-trip LAST, after everything's wired, as the observed-not-inferred proof.

## Team
Continuing dev team (the subsystem owners from Stage 1). This is build-on-known-surface work; codebase context wins. Lead sequences + runs migration/PG-smoke + the live sandbox round-trip + closeout. Backend dev owns C-PROVIDER through C-JURIS. FE dev owns C-FE. QA: webhook security + collision + demo-tightening side-effect assertions, then the post-deploy demo + sandbox round-trip.

## Invariants (don't regress)
- **Enforcement untouched:** 52a adds the state-*setting* path; the Stage-1 gates that *read* state are not modified. An ungated org still behaves byte-for-byte as pre-arc.
- **Hybrid pattern:** never store document image / selfie / raw PII. Only state + opaque nullifier + attestation id + coarse jurisdiction.
- **Nullifier internal:** never serialized to any client (re-confirm post-real-nullifier).
- **`demo_stub` sealed:** writable only onto demo-only accounts; never the Didit path; (52b will ensure) never increments the counter.
- **API key server-side only; webhook always signature+timestamp+idempotency verified.**
- **No billing, no free-pool enforcement in 52a** — overage handling is 52b/53.

## Closeout must report
Load-bearing evidence: the live sandbox round-trip (initiate → Didit flow → signed webhook → record written, observed); webhook security test results (bad-sig 401, replay deduped, stale-timestamp rejected); nullifier collision side-effect (second account unchanged + audit row); `demo_stub` tightening side-effects; migration cycle + PG-smoke both modes with the NULL-tolerance divergence note; whether any deploy-time path was touched (+ `bash start.sh` result if so); serializer nullifier-exclusion re-confirmed; test-count delta; bundle hash; the C-JURIS controlled-vocabulary decision; new tech debt. Forward note: free-pool metering (52b) and billing (Phase 53, entity-gated) remain deferred.

## Z-action items
- **Provide in the dispatch prompt (NOT this spec):** `DIDIT_API_KEY`, `DIDIT_WEBHOOK_SECRET`, `DIDIT_WORKFLOW_ID` (recommend pre-creating the ID_VERIFICATION workflow in the Didit console), Railway project token.
- **One values fork to confirm (C-NULLIFIER):** nullifier-collision handling — the spec's recommended "reject the second account + audit + surface 'already verified elsewhere'" vs. an alternative. I'll bring this to you as a single focused fork; it's a civic-platform policy call (innocent shared-device vs. ban-evasion), and it's worth your judgment rather than my default. Does NOT block starting 52a — the rest can build while we settle it; only the collision branch needs the answer.
