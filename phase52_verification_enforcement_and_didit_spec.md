# Phase 52 — Verification Enforcement + Delegation Fork + Didit Integration (Greater Phase)

**Status:** Spec + dispatch. Written 2026-06-03, post-Phase-51-ship. Second phase of the ID-verification arc.

Reading order at session start: this doc; then `id_verification_research.md` §7 + §10 + **§12 addendum (the Persona→Didit pivot)**; then the shipped `backend/verification.py` and the Phase 51 closeout.

**This is a GREATER PHASE — it ships as three staged deploys (52 → 52a → 52b), riskiest-isolated-piece first.** It trips every threshold in the workflow playbook: >5 clusters, a migration, novel external-integration infrastructure (Didit HTTP + signed webhooks), the governance-state-touching tally change, and >50 new tests. Per the Phase 13 precedent (single-deploy attempt that had to be reverted) and the Phase 48 elections precedent (clean 48→48a→48b staging), this MUST NOT collapse into one deploy. Each stage is independently shippable and verified before the next.

---

## What shipped in Phase 51 (the foundation this builds on)

Confirmed against the live model + `verification.py`:

- **`User` columns** (all with `server_default`, no backfill needed): `verification_state` (String(32), default `"email_only"`, indexed), `verification_jurisdiction` (String(16), nullable), `verification_attestation_id` (String(128), nullable), `verification_nullifier` (String(128), nullable, **indexed, NO unique constraint yet**), `verification_provenance` (String(16), default `"none"`), `verification_updated_at` (DateTime, nullable).
- **`backend/verification.py`** — pure, no DB. Source of truth. Public API this phase consumes by exact name:
  - State constants `EMAIL_ONLY`, `IDENTITY`, `IDENTITY_UNIQUE`, `ADDRESS_ON_ID`, `RESIDENCY_VERIFIED`; `ORDER`; `VALID_STATES`.
  - Provenance constants `PROV_NONE`, `PROV_PERSONA`, `PROV_DEMO_STUB`, `PROV_BACKDOOR`. **NOTE:** the real-provider provenance constant is named `PROV_PERSONA` (`"persona"`). Since the provider is now **Didit**, this phase adds `PROV_DIDIT = "didit"` to `verification.py` and uses it for real verifications. Leave `PROV_PERSONA` in place (unused but harmless) OR rename with a data-migration — see C1 D-note. Do NOT silently repurpose `"persona"` to mean Didit; that corrupts the audit meaning.
  - `rank(state)` (unknown → -1, fail-closed), `subsumes(current_state, current_jurisdiction, required_floor, required_jurisdiction)`, `get_org_verification_floor(org, scope, *, role_key=None)` → `(floor, jurisdiction)` defaults-if-absent, `jurisdiction_required_for(state)`.
  - Settings keys `SETTING_MEMBERSHIP_FLOOR`, `SETTING_MEMBERSHIP_JURISDICTION`, `SETTING_ROLE_FLOORS`.
- **Guarded backdoor**: platform-admin-only `POST /api/admin/users/{user_id}/verification-state`, provenance `backdoor`. This is the test lever for enforcement BEFORE wiring Didit — use it heavily in 52 (the enforcement stage) so gate + tally logic is verified against a controlled state before the external integration lands in 52b.
- **Two forward constraints carried from 51 (both are THIS phase's responsibility):**
  1. **Nullifier `UniqueConstraint` deferred to here** — must land alongside the Didit flow that produces real nullifiers + the collision-handling logic.
  2. **`demo_stub` provenance must be honored** by enforcement + billing as "not a real verification" — never counted against the free pool, never billed. Enforcement (this phase) treats `demo_stub` as a valid satisfying verification for *gating* (so demo orgs can demo gated flows) but the free-pool counter (52b) must never increment for it.

---

## Provider: Didit (not Persona)

Per the §12 addendum: **Didit (didit.me)**, $0 floor, 500 free verifications/month/workspace forever, pay-as-you-go overage (~$0.33 full KYC) with no monthly minimum, 1:N face-search dedup, address-on-ID in the ID response, Proof-of-Address module for the stronger residency tier. Z has an account as of 2026-06-03.

**Integration shape (confirmed from Didit docs):**
- API root `https://verification.didit.me/v3/`.
- Hosted flow: (1) `POST /v3/workflows/` with `features: [{feature: "ID_VERIFICATION"}]` (UPPERCASE strict enum), header `x-api-key`; (2) `POST /v3/session/` with `workflow_id` + `vendor_data` (set to our `User.id` — the bridge back to our row), returns `session_url`; (3) redirect/modal/iframe the user to `session_url`; (4) signed webhook fires on status change carrying a `decision` object with extracted fields (incl. parsed address) when status is `Approved`/`Declined`.
- **Security-critical (load-bearing — these are spec requirements, not suggestions):**
  - API key is **server-side only, NEVER shipped to the browser**. Session creation is a backend call.
  - Webhook handler: verify HMAC-SHA256 signature, enforce `X-Timestamp` freshness ≤ 300s, **idempotent** (dedupe on `session_id + webhook_type`), return 200 quickly. Store the webhook secret + API key as Railway env vars (`DIDIT_API_KEY`, `DIDIT_WEBHOOK_SECRET`), never in the repo / never in this spec (specs sync to public GitHub — the Railway project token + secrets go in the dispatch prompt, not here).
  - Consent/disclosure shown to the user BEFORE the session opens (Didit handles biometric consent inside its flow; the legal/disclosure layer outside is ours). The Phase 51 hybrid-pattern privacy copy ("We send your ID to Didit to verify; we don't keep a copy") leads here.
- Provider is configurable behind one env-var-pointed backend module (`verification_provider.py`) so a future swap (Stripe Identity fallback, etc.) touches one file. The arc's provider-agnostic state model means this is genuinely a one-module surface.

---

## The arc's staging

| Stage | Deploy | Riskiest-piece rationale |
|---|---|---|
| **52** | Enforcement + delegation fork, against STUBBED state (backdoor/demo only) | The governance-state-touching change (the tally read path) is the single most dangerous piece. It ships FIRST and ALONE, verified against controlled backdoor state, with NO external integration in the blast radius. If something regresses the tally, it localizes here. |
| **52a** | Didit integration (workflow/session/webhook), hybrid-pattern attestation handling, nullifier uniqueness + collision handling | External integration + the deferred nullifier constraint. Lands only after enforcement is proven. Real verifications become possible; free-pool metering recorded but overage simply blocked (no billing). |
| **52b** | Free-pool counter + per-org consumption metering (record-only) + address-on-ID residency wiring | The metering/counter surface + residency state population. Smallest-risk last. Billing is NOT here (that's Phase 53, entity-gated). |

Each stage merges `--no-ff` to master and is independently deployed + verified before the next. Dispatch authorizes **Stage 52 only**; 52a and 52b are dispatched as separate verified deploys per the playbook (never collapsed into one merge).

---

## Branch + merge

Branch per stage: `phase-52/verification-enforcement`, `phase-52a/didit-integration`, `phase-52b/free-pool-metering`. `--no-ff` to master per CLAUDE.md.

## Migration head

This arc adds migrations in **52a** (nullifier unique constraint + any Didit-session bookkeeping table) and possibly **52b** (metering counter). **Stage 52 itself may need NO migration** (it's enforcement logic + the delegation org-setting, which rides `Organization.settings` JSON — no schema change). Confirm with `alembic heads` at each stage's branch time; the Phase 51 head was `c8d3e1f56432` but later phases may have stacked since — do NOT assume. Single-head check + hex-prefix revision IDs per the playbook. Multi-head → STOP and flag.

---

# STAGE 52 — Enforcement + Delegation Fork (against stubbed state)

## Goal

Wire the verified-floor gate into the three action scopes (join, role-grant, per-vote) and implement the delegation fork (org-level option, default No) — all enforced against verification state set via the Phase 51 backdoor / demo stub. No Didit, no external calls. After this stage: an org can require a verification floor to join / hold a role / vote on a specific proposal, and unverified users (and their delegated weight) are correctly excluded per the locked rules — all provable with backdoor-set state.

## Clusters

### C1 — Provenance constant for Didit
Add `PROV_DIDIT = "didit"` to `verification.py` and include in `VALID_PROVENANCES`. **D-note (decide at build):** the Phase 51 module shipped `PROV_PERSONA`. Recommend: ADD `PROV_DIDIT`, leave `PROV_PERSONA` defined-but-unused (zero existing rows carry `"persona"` since no real verification ever ran — confirm with a `SELECT DISTINCT verification_provenance` first). Do NOT rename in a way that orphans existing data; there is no existing real-provider data, so a clean add is safe and reversible. Trivial, lands first.

### C2 — Per-proposal verification gate field
The per-action (per-vote) floor is a per-proposal setting (per §10, NOT an org setting). Add to `Proposal`:
- `verification_floor: Mapped[Optional[str]]` — String(32), nullable. NULL = inherit "no gate" (today's behavior). Non-null = the floor required to cast a (direct) vote on this proposal. Set at proposal-creation by a user with the existing proposal-create permission; validated against `VALID_STATES`.
- `verification_jurisdiction: Mapped[Optional[str]]` — String(16), nullable. Optional jurisdiction scoping for the proposal gate. Validated for presence-consistency via `jurisdiction_required_for(floor)`.

Both `server_default` NULL → existing proposals byte-for-byte unaffected (additive-layer invariant). This is the one schema add in Stage 52; if the team prefers to keep Stage 52 migration-free, these two fields can move to 52a's migration and Stage 52 enforces only membership + role gates (which ride `Organization.settings`). **Recommend including them in 52** so the full gate model is testable together; the migration is trivial (two nullable columns). Decide at build; either is defensible.

### C3 — The gate predicate + the three enforcement points
Add a single helper, `verification.user_satisfies_floor(user, floor, jurisdiction)` → bool, wrapping `subsumes(user.verification_state, user.verification_jurisdiction, floor, jurisdiction)`. One chokepoint; never reimplement `subsumes` at call sites.

Enforce at three points (per §10's three composable scopes):
1. **Membership (join):** in the join path, read `get_org_verification_floor(org, "membership")`; if the user doesn't satisfy it, block the join with a structured 403 (`{reason: "verification_required", floor, jurisdiction}`) the FE turns into a "verify to join" prompt. Applies to all join routes (open join, approval-grant, invitation-accept). **Audit the multi-path join surface** — the Phase 4c multi-tenancy debt note warns join/invitation wiring has gaps; find every path that creates an `OrgMembership` and gate them all, or gate at the single chokepoint if one exists. Ground this against the real join routes before wiring.
2. **Role-grant:** in the role-assignment path, read `get_org_verification_floor(org, "role", role_key=<target role system_key>)`; block the grant if the target user doesn't satisfy it. This includes election-driven title→role binding (Phase 48) — a user winning an election to a title that binds a gated role must satisfy the floor, or the bind is blocked/deferred. **Flag at build:** decide what happens when an election winner fails the role floor (recommend: the title is granted but the role-bind is held with a surfaced "verification required" state, rather than silently dropping the election result — but this is a values fork, surface it to Z if it's non-trivial).
3. **Per-vote:** in the vote-cast path, if the proposal carries a `verification_floor`, block a *direct* vote-cast by a user who doesn't satisfy it (structured 403). The deeper tally-side handling of delegated weight is C4.

All three assert **side effects** (no membership row created; no role assigned; no vote row written), not status codes, per the playbook's load-bearing test property for governance passes.

### C4 — The delegation fork (the core-mechanic-touching piece)
This is the most careful cluster. The locked decision (Z, this arc): **org-level option, default No** — when a proposal is verification-gated, an unverified principal's delegated weight does NOT carry to their verified delegate by default; the org can flip it to Yes.

Grounding finding (from Phase-51-era code read): the tally chokepoint is `delegation_engine.eligible_voter_ids_for_proposal` feeding `DelegationService.compute_tally` → `compute_tally_pure`. The Phase 10.1 `eligible_ids` filter already means a user excluded from the eligible set has their direct ballot dropped from `direct_ballots`, so a delegate landing on them resolves `None` and `chain_behavior` fires. **The "default No" rule is therefore implemented as narrowing the eligible-voter set by the verified-floor filter when the proposal is gated** — it reuses the exact mechanism the cross-scope-leak fix established. Do NOT build a parallel tally path.

Precise semantics:
- **Org setting** `verification_delegation_carries_weight` in `Organization.settings` (defaults-if-absent → `False` = No). Add a `verification.py` getter mirroring the existing helpers.
- **Default (No):** for a gated proposal, `eligible_voter_ids_for_proposal` returns only users who satisfy the proposal's floor. Unverified users are excluded entirely — both their direct vote (C3 blocks the cast) and their delegated weight (they're not in the eligible set, so their ballot never enters `direct_ballots`, so a delegate resolving to them gets `None`). Internally consistent: unverified = no influence on this vote by any path.
- **Yes (org opted in):** the verified-floor filter applies to who can *cast directly* (C3 still blocks an unverified direct cast) but the *tally's* delegation resolution uses the wider member set, so a verified delegate carries the unverified principal's delegated weight. Implementation: split the two notions — "direct-cast eligibility" (always floor-filtered) vs "delegation-resolution eligibility" (floor-filtered only when the setting is No). Be surgical; this is the one place where the two diverge.

**Transparency surface (ships WITH the rule, not after — same unit):**
- The delegate sees their effective weight on a gated proposal and *why* it differs from their headline delegated count ("Effective weight here: 12 of 40 — 28 of your delegators aren't verified for this vote"). 
- The unverified principal sees why their delegated weight didn't carry ("Your delegate couldn't carry your vote on this proposal because it requires identity verification — verify to participate").
- These are honest-by-construction; without them the weight evaporation reads as a bug in QA. The closeout must show the transparency strings render.

**Tests (side-effect level):** construct gated proposals with mixed verified/unverified principals + verified delegates, assert the resulting tally counts under both org settings, including the delegation-chain cases (`accept_sub` hop through an unverified intermediate). This is the load-bearing test set for the whole arc.

### C5 — FE enforcement surfaces
The "verify to join / verify to vote" prompts (reading the structured 403s), the org-admin settings UI for the three floors + the delegation-carries-weight toggle, the per-proposal floor picker at proposal creation, and the transparency strings from C4. Backend state codes never leak into copy (Phase 49a C2 rule). Bundle hash changes — record it.

## Stage 52 verification matrix

| Check | Required | Notes |
|---|---|---|
| Backend pytest (full) | ✅ | Record baseline at branch; target ~+40–60 across C2–C4. |
| Subsumption integration tests | ✅ | The gate predicate + three enforcement points, against backdoor-set state across every floor. |
| **Delegation-fork tally tests (side-effect)** | ✅ | THE load-bearing set. Mixed verified/unverified, both org settings, chain hops. Assert tally counts + effective-weight numbers, not status codes. |
| Existing-vs-new-org parity | ✅ | Phase 48 B0 helper. A gated org and an ungated (default) org; the ungated path is byte-for-byte today's behavior. The additive-layer invariant: delete the gate in your head, nothing changes. |
| Backdoor-drives-enforcement E2E | ✅ | Set state via the Phase 51 backdoor → confirm join/role/vote gates fire → flip state → confirm they pass. Proves enforcement without Didit. |
| Migration cycle + PG smoke both modes | ✅ if C2 migration included | If Stage 52 ships the two `Proposal` columns. Confirm head first. |
| `bash start.sh` prod-mimic | ❌ | Stage 52 doesn't touch start.sh / worker / Dockerfile. (52a/52b might — re-check there.) |
| Frontend build + bundle hash | ✅ | C5 touches FE. Record new hash. |
| Demo gated-flow showcase | ✅ | A demo org set to require a floor; demo personas' `demo_stub` state satisfies the gate so the flow demos end-to-end with zero real IDV. Confirm `demo_stub` is treated as satisfying for gating. |
| Deploy + demo reset post-deploy | ✅ | Observed, not inferred. |

## Stage 52 sequence
1. C1 (provenance add) → C2 (proposal columns + migration if included) → C3 (gate predicate + three enforcement points) → C4 (delegation fork + transparency) → C5 (FE). 
2. C3 before C4 (the simple direct-cast gate before the tally subtlety). C4 is the riskiest cluster within the riskiest stage — isolate it, land it with its full side-effect test set, verify before moving to FE.

---

# STAGE 52a — Didit Integration

## Goal
Replace the backdoor as the real path to verification state: users verify through Didit's hosted flow; the signed webhook updates their verification record via the hybrid pattern (platform stores attestation id + nullifier + state + coarse jurisdiction; never the document, selfie, or raw PII). Lands the deferred nullifier uniqueness + collision handling.

## Clusters
- **A1 — `verification_provider.py`**: env-var-configured Didit client. `create_workflow` (or reuse a pre-created workflow id from env), `create_session(user_id)` → `session_url`, webhook signature verification. API key server-side only. The Didit coding-agent skill/MCP (`DIDIT_API_KEY`) MAY be used to scaffold — but the integration code lands in our repo, reviewed, not black-boxed.
- **A2 — session-initiation endpoint**: authenticated `POST /api/verification/session` creates a Didit session with `vendor_data=user.id`, returns `session_url`. Rate-limited (reuse Phase 38 limiter). Consent/disclosure copy returned/shown before redirect.
- **A3 — webhook receiver** `POST /api/webhooks/didit`: HMAC-SHA256 verify, `X-Timestamp` ≤300s, idempotent dedupe on `session_id + webhook_type`, maps the `decision` to a verification state, writes the hybrid-pattern record (`verification_state`, `verification_jurisdiction` from parsed address when present, `verification_attestation_id` = Didit session/verification id, `verification_nullifier` from the 1:N face-search identity handle, `verification_provenance = PROV_DIDIT`, `verification_updated_at`). **Never store the document image / selfie / raw PII.** Audit-logged.
- **A4 — nullifier uniqueness + collision handling (the deferred 51 constraint)**: add the `UniqueConstraint` on `verification_nullifier` (migration). Define collision behavior: when an incoming verification's nullifier matches an existing *different* user, that's the "one human, two accounts" case — decide handling (recommend: reject the second with a structured "this identity is already verified on another account" + audit, do NOT silently merge). **This is a values + security fork — surface the exact handling to Z before finalizing.** The constraint must tolerate NULLs (most users have no nullifier) — partial/filtered unique index or app-layer enforcement per PG/SQLite behavior; confirm the cross-DB story in the migration like the Phase 18 NULL-distinctness notes did.
- **A5 — FE verification flow**: the "verify now" CTA → session → hosted flow → return → status reflects. Reads the Phase 51 serialized fields. Hybrid-pattern privacy copy leads.

## Stage 52a matrix highlights
- Webhook signature/timestamp/idempotency unit + integration tests (forge a bad signature → 401; replay → deduped; stale timestamp → rejected).
- Nullifier collision tests (same nullifier, second user → rejected + audited).
- **`bash start.sh` prod-mimic REQUIRED** if anything touches start.sh / a worker (the webhook receiver likely doesn't, but the metering counter in 52b might — re-check per stage).
- Migration cycle + PG smoke both modes (nullifier constraint).
- Live Didit sandbox smoke: one real sandbox verification end-to-end (Didit's free tier = production-grade test users, no separate sandbox), webhook received + record written. Observed, not inferred.
- `demo_stub` honored: a real Didit verification and a demo-stub user coexist; demo-stub never hits the Didit path.

---

# STAGE 52b — Free-Pool Metering (record-only, no billing)

## Goal
Track verification consumption against the shared 500/month free pool so that (a) usage is visible and (b) the data exists to pick a per-org sub-allocation later if the commons gets raced — without acting on it yet. Per Z's decision: **first-come-first-served on the shared pool for v1; per-org consumption recorded from day one but NOT enforced.** Overage past the free pool is **blocked** (not billed) — billing is Phase 53, entity-gated.

## Clusters
- **B1 — consumption counter**: a monthly counter (platform-level, resets on the 1st to match Didit's reset). A real Didit verification increments it; `demo_stub` and `backdoor` provenance NEVER increment it (forward-constraint #2 from Phase 51). Recommend a small `VerificationConsumption` table keyed by `(year_month, org_id)` so per-org consumption is recorded from day one (the "preserve the information from day one" pattern) even though allocation is FCFS and unenforced.
- **B2 — pool-exhaustion block**: when the shared monthly counter ≥ 500, new session-initiation requests are blocked with a structured "verification temporarily unavailable this month" response — NOT billed, NOT silently failing. Fail-safe toward not spending money. (When Phase 53 lands billing, this block becomes "blocked unless the org opted into paid overage.")
- **B3 — address-on-ID residency wiring**: populate `verification_jurisdiction` + the `address_on_id` state from the Didit ID response's parsed address (already received in 52a's webhook). This lights up the `address_on_id` floor for real. The stronger `residency_verified` (Didit Proof-of-Address module) stays deferred to a later phase per §10 — note it, don't build it.
- **B4 — admin consumption visibility**: a platform-admin read of current-month consumption (shared total + per-org breakdown). Informs the future sub-allocation decision.

## Stage 52b matrix highlights
- Counter increments on real verification, NOT on demo_stub / backdoor (assert at side-effect level — the counter row).
- Pool-exhaustion block fires at the threshold; blocked request creates no Didit session (no spend).
- Per-org consumption recorded correctly across multiple orgs.
- `bash start.sh` prod-mimic if the counter reset is wired to the worker/scheduler (likely — re-check; the Phase 48.1 digest-async-fix context applies if a scheduler tick is involved).
- Migration cycle + PG smoke (counter table).

---

## Invariants across all stages (don't regress)

- **Additive-layer:** an ungated org (no floor set, no delegation-carries setting) behaves byte-for-byte as pre-arc. Parity test proves it at every stage.
- **`demo_stub` honored:** satisfies gating (so demos work) but NEVER increments the free-pool counter and is NEVER billed. Asserted in 52 (gating) and 52b (counter).
- **Nullifier stays internal:** never serialized to any client (Phase 51 already excludes it from the serializer — confirm the exclusion holds after 52a writes real nullifiers).
- **Delegation core mechanic:** the Follow=info-access vs Delegation=vote-responsibility distinction is untouched; the fork only changes whether unverified *delegated* weight carries on *gated* votes, and only via the eligible-set narrowing — never by a parallel tally path.
- **Cardinality floor + governance invariants** (governance.py): the role-grant gate (C3 point 2) must not let a verification block break the ≥1-governor floor — e.g. a verification requirement on the steward-bound title must not be able to strand an org with no eligible steward. Flag the interaction with `governance.count_active_governors()` and test it. **This is a real cross-feature interaction — surface to Z if the resolution is non-obvious.**
- **API key never in repo / never browser-side; webhook always signature+timestamp+idempotency verified.**

## Closeout (each stage) must report
Per the playbook: the load-bearing invariant held with side-effect evidence (for 52: the delegation-fork tally numbers; for 52a: webhook security + nullifier collision; for 52b: counter never moves on demo_stub); migration cycle + PG-smoke-both-modes on a confirmed single head; `bash start.sh` result if any deploy-time path touched; observed-not-inferred prod health (for 52a: a real sandbox verification round-trip); test-count delta; bundle hash if FE touched; and any new tech debt. Plus the forward note: `residency_verified` (Proof-of-Address) and billing (Phase 53) remain deferred.

---

## Z-action items (explicit)

- **Before 52a dispatch:** provide the Didit API key + webhook secret for the dispatch prompt (NOT in this spec — specs sync to public GitHub). Confirm whether to pre-create the Didit workflow in the Didit console and pass a fixed `workflow_id`, or have the integration create it programmatically (recommend pre-create in console; simpler, one less moving part).
- **Two values forks to confirm when they arise (the spec flags them inline, no need to pre-answer):** (1) what happens when an election winner fails a gated role floor (C3 point 2); (2) nullifier-collision handling — reject-second vs other (A4). Both are surfaced at build; I'll bring them to you as one-at-a-time forks if the team hits them.
- **None of these gate Stage 52** — enforcement against backdoor state needs no Didit credentials. Stage 52 can dispatch immediately.
