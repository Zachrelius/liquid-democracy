# Phase 52h — Org-Scoped Flag Upgrade + Remove Platform-Wide Doc-Number Block

**Status:** Spec + dispatch. Written 2026-06-06.

Reading order: this doc; `id_verification_arc_backlog.md` (the locked dedup model + the confidence-determines-scope principle); the shipped `backend/verification_flags.py` (detection + `is_org_verified` + adjudication — the module this upgrades); `backend/routes/verification.py` (`_apply_decision` — where the doc-block lives + where verify-time detection gets added); `backend/routes/organizations.py` (the three join paths where detection is already wired); `phase52e_stage2_closeout.md` (what shipped).

## Why this phase exists

Two linked changes, sequenced deliberately:

1. **Upgrade the org-scoped duplicate-flag feature** (the `name_dob_address_hash` / `name_dob_hash` → `OrgDuplicateFlag` → existing-approval-queue mechanism) to match Z's intended behavior. This is the dedup mechanism the platform will rely on going forward.
2. **THEN remove the platform-wide document-number hard block** (`doc_number_hash`). It contradicts the locked principle that cross-org duplicate accounts for the same person are fine (harm is org-scoped), and it stores a reversible government-ID fingerprint platform-wide forever for no value the name-based org-scoped flags don't already provide. A person with two legitimately-different verified identities would need two different documents anyway, so the doc-number adds nothing over name-based detection.

**Sequencing is load-bearing: upgrade the flag feature FIRST (Stage 1), prove it works, THEN remove the doc-block (Stage 2).** Don't remove the existing dedup mechanism before its replacement is upgraded and verified. The two stages ship as separate `--no-ff` deploys.

## Pre-flight grounding (the team does this BEFORE building — do not assume)

The 52e Stage 2 closeout states detection is "Wired into all three join paths: `create_join_request`, `request_join`, `accept_invitation`." A prior planning read of the head of `routes/organizations.py` did NOT show `verification_flags` imported (it's expected lower in the file). **Before building, confirm the actual wiring by reading `routes/organizations.py` IN FULL** (`search_files` matches filenames only, not contents — grep won't work through the MCP; read the file). Specifically confirm:
- `verification_flags.evaluate_duplicate_flags_for_org` IS imported and called in `create_join_request`, `request_join`, `accept_invitation`.
- The high-confidence → `pending_approval` routing actually fires at those call sites (not just that the flag is created).
If the wiring is NOT actually present (orphaned function), Stage 1 ALSO includes connecting it to the join paths — flag this in the closeout as a found-gap rather than silently fixing, since it changes what "already shipped" meant.

---

# STAGE 1 — Upgrade the org-scoped flag feature

Branch `phase-52h/flag-upgrade`. `--no-ff`. No migration expected (the `OrgDuplicateFlag` table already exists; this changes logic + settings reads + adds a verify-time trigger + one new resolved-side marker — confirm whether the "which side is demoted" needs a column, see H4). Confirm `alembic heads` single head (`c4d5e6f7a8b9` after 52e Stage 2) regardless.

## H1 — Add the verify-time detection trigger (the big new capability)

Today detection runs ONLY at join / promote. Add a second trigger: **when a user completes verification, evaluate them against the members of EACH org they are already a member of.**

- **Where:** in `routes/verification.py` `_apply_decision`, AFTER the user's hashes are written + committed (the verification record must exist first), call a new helper that iterates the user's active `OrgMembership` rows and runs `verification_flags.evaluate_duplicate_flags_for_org(db, candidate_user=target_user, org=<each org>, ...)` for each.
- **Why this matters:** it closes the join-then-verify gap (someone joins an org, THEN verifies — today nothing re-checks them against that org). It also organically backfills existing members: as people verify / re-verify, they get evaluated against their current orgs, so the population gets checked over time without a separate backfill sweep.
- **Cross-org stays ignored:** only the user's OWN orgs are evaluated — never a global walk. Consistent with the locked org-scoped-harm principle.
- **Same module, same function:** reuse `evaluate_duplicate_flags_for_org` unchanged for the comparison logic; H1 is purely a new CALL SITE (the verify path) plus the per-org iteration wrapper. Do NOT duplicate the comparison logic.
- **Action on a verify-time match against an ALREADY-ACTIVE member (Z decision):** create the flag + let `is_org_verified` go False (gating their verified-only actions), but **do NOT flip the active membership back to `pending_approval`.** Verify-time detection must not suspend a sitting member — less disruptive than join-time, where pending is the natural pre-active state. So: join-time match → may route to `pending_approval` (per H2 settings); verify-time match on an active member → flag + predicate-invalidation only, membership stays `active`. Document this asymmetry explicitly in the code + closeout.
- **Performance note:** a user in N orgs triggers N evaluations on verify. At current volumes trivial; note it, don't optimize prematurely.

## H2 — Both confidence tiers get the configurable action, both default to pending_approval

Today: high-confidence default-action is configurable (`pending_approval` default); low-confidence is ALWAYS review-only (hardcoded). Change:

- **Low-confidence becomes configurable too**, with the SAME action setting semantics as high-confidence, and **defaults to `pending_approval`** (Z reasoning: within a real org, false positives on even the low-confidence flag are rare enough that the safer default — route to admin review — beats letting a possible duplicate through).
- **Two settings keys** (keep them separate so an org can tune each tier independently):
  - `verification_high_confidence_flag_action` — exists; default stays `pending_approval`.
  - `verification_low_confidence_flag_action` — NEW; default `pending_approval` (this is the behavior change — was effectively a hardcoded `review_only`).
- Both accept `pending_approval` or `review_only`.
- **Additive-layer parity:** an org that has never touched verification settings — does it now suddenly route low-confidence matches to pending where before it didn't? **YES, that's the intended behavior change**, but it ONLY affects orgs that have verification enabled at all (a flag only gets raised if members carry hashes, which only happens once verification is in use). An org with no verification configured and no verified members produces no hashes → no flags → no behavior change. Confirm + test: a truly verification-unconfigured org is byte-for-byte unchanged (the Mode 3 parity test must still pass).
- Update `high_confidence_flag_action` / add `low_confidence_flag_action` reads in `verification_flags.py` (mirror the existing helper). Update the join-path routing so the action is read per-tier (today low-confidence skips the routing entirely; now it reads its own setting).
- **FE:** `OrgSettings.jsx` "Identity verification gates" section — the existing high-confidence action dropdown gets a sibling low-confidence action dropdown. Both default-display `pending_approval`.

## H3 — `is_org_verified` invalidates on open flags of BOTH tiers

Today: only an open high-confidence flag flips `is_org_verified` to False (`has_open_high_confidence_flag`). Change:

- `is_org_verified` returns False if the user is the subject of an open flag of EITHER tier in this org.
- Rename / generalize `has_open_high_confidence_flag` → `has_open_flag` (any confidence), or add the low-confidence case. Keep one predicate the rest of the code reads.
- **Consistency with H2:** since low-confidence now defaults to routing-to-pending and is treated as a real signal, it should also invalidate verified status — same reasoning. (The old special-casing existed because low-confidence was review-only; that rationale is gone.)
- Update `TestIsOrgVerifiedPredicate` cases: low-confidence open flag now invalidates (was: did not).

## H4 — `resolved_same` auto-demotes the duplicate (not records-only)

Today: `resolved_same` records the verdict but changes nothing — `is_org_verified` only keys on OPEN flags, so resolving (which sets status away from `open`) actually RE-VERIFIES the user (the open flag stops invalidating). That's backwards. Change so `resolved_same` durably demotes ONE account:

- **Which account (Z decision):** auto-demote the **NEWER** account (later `User.created_at`) of the pair. The admin can manually adjust afterward if the newer account is actually the real person. (Rationale: the newer account is the more-likely duplicate; auto-picking avoids an extra admin step in the common case.)
- **Mechanism (stay derived — no stored `verified` boolean, avoid drift):** `is_org_verified` becomes:
  - False if there's an open flag of either tier involving the user (H3), OR
  - False if the user is the **demoted side** of any `resolved_same` flag in this org.
- **Recording the demoted side:** the `OrgDuplicateFlag` row needs to record WHICH user_id was demoted (since `user_a_id`/`user_b_id` are lexically ordered, not semantically "kept/demoted"). Add a nullable `demoted_user_id` column to `OrgDuplicateFlag` (FK users, SET NULL on delete), set at `resolve_same` time to the newer account's id. **This is a migration** — a small additive nullable column. (If the team finds a cleaner derivation that avoids the column, fine, but the column is the clean explicit approach; don't infer "newer" at every predicate read.)
- `resolve_flag` for `resolved_same`: compute newer-of-pair, set `demoted_user_id`, set status `resolved_same`. Audit includes which side was demoted.
- **Fully removing/kicking the duplicate account stays a SEPARATE manual admin action** (Z) — `resolved_same` only demotes verified-status-in-this-org; it does not deny membership, strip roles, or delete the account. The admin uses existing membership/deny controls for that.
- **Cardinality-floor invariant still holds:** demotion flips `is_org_verified` to False but must NEVER auto-strip a seated role below the governor floor (same invariant as 52e Stage 2 — a verification-status change never auto-removes a role; it flags for manual handling). If the demoted account holds a floor-critical role, demotion does NOT remove it — preserve + test this exactly as 52e did.
- `resolved_distinct` is unchanged (suppresses re-flagging the pair; no demotion).

## Stage 1 verification matrix

| Check | Required | Notes |
|---|---|---|
| Verify-time detection fires (side-effect) | ✅ | A user completing verification gets evaluated against each of their active orgs; a real same-org name match creates a flag. Assert flag rows. |
| Verify-time match on active member does NOT flip to pending | ✅ | Active member stays `active`; `is_org_verified` goes False; membership status unchanged. Assert all three. |
| Both tiers configurable + default pending_approval | ✅ | Low-confidence with default setting → routes to pending at join. High unchanged. Both settings independently flippable to review_only. |
| Both tiers invalidate is_org_verified | ✅ | Open low-confidence flag now flips the predicate False (regression vs old behavior — update the test). |
| resolved_same demotes the NEWER account | ✅ | After resolve_same, the newer account's `is_org_verified` is False (durably, not just while open); the older account's is unaffected by the demotion. Side-effect assert on the predicate + the `demoted_user_id` column. |
| resolved_same does NOT auto-strip roles below floor | ✅ | Demoted account holding steward → role survives; predicate False; membership active. Mirror the 52e cardinality-floor test. |
| resolved_distinct unchanged | ✅ | Suppresses re-flag; no demotion. |
| Migration (demoted_user_id column) cycle + PG smoke both modes | ✅ | Additive nullable column. Confirm single head. |
| Mode 3 / verification-unconfigured parity | ✅ | An org with no verification + no verified members → no hashes → no flags → byte-for-byte unchanged despite the low-confidence default flip. |
| Adjacent regression | ✅ | Full suite green (547 baseline + new). |
| Pre-flight wiring confirmation | ✅ | Closeout states whether join-path detection was actually wired (and if it had to be connected). |

## Stage 1 sequence
Pre-flight grounding → H4 migration (demoted_user_id) → H2 (per-tier settings) → H3 (both-tier invalidation) → H4 logic (resolve_same demotion) → H1 (verify-time trigger) → FE (two dropdowns). Deploy. Verify on prod (a Z re-verify naturally exercises H1 — see Z-action).

---

# STAGE 2 — Remove the platform-wide document-number hard block

**Only after Stage 1 is deployed + verified.** Branch `phase-52h/remove-doc-block`. `--no-ff`. Includes a migration (drop the partial-unique index).

## What to remove

The doc-number hard block is the platform-wide "one document = one account" enforcement. Remove it entirely:

- **`routes/verification.py` `_apply_decision`:** remove the collision lookup (`collided_with_user`), the `collision_rejected` branch, and the `verification.duplicate_document` audit on the pre-check path. Remove the `IntegrityError` catch in `didit_webhook` that handles the doc-hash unique-index race (the index is going away).
- **The `doc_number_unique` signal into the mapper:** today `map_decision_to_state` takes `doc_number_unique` to decide the `identity_unique` rung. With the doc-block gone, decide the replacement for the uniqueness rung — see "Uniqueness rung" below. Do NOT leave `map_decision_to_state` reading a now-meaningless `doc_number_unique`.
- **Stop computing + storing `doc_number_hash`:** remove it from `verification_hashing.compute_hashes` (or stop persisting it in `_apply_decision`). Removing it from `compute_hashes` is cleaner (don't compute a hash we never store). Keep the two name-based hashes (they drive the org-scoped flags — unchanged).
- **Migration:** drop the partial-unique index on `doc_number_hash`. **Decide whether to drop the COLUMN too.** Recommend: drop the index now (it enforces the platform-wide block we're removing); leave the COLUMN drop to the same cleanup pass that drops the deprecated `verification_nullifier` column (dropping columns on PG is the riskier op; batch them). Mark `doc_number_hash` deprecated in the model comment. Confirm + state which in the closeout.
- **`verification_hashing.py` docstring:** update — the module docstring currently describes `doc_number_hash` as "Platform-wide HARD BLOCK." Remove that; the module now produces only the two name-based org-scoped-flag hashes.
- **`uniqueness_strength`:** today set to `document_hash` when `doc_number_hash` is written. Decide what (if anything) sets it now — see below.

## Uniqueness rung — the real design question for Stage 2

Removing the doc-block removes the thing that drove the `identity_unique` verification state rung. Two options, needs a decision at build (flag to Z if non-obvious):

- **Option A — drop the `identity_unique` rung's auto-assignment; uniqueness becomes purely org-scoped-flag-based.** A verification reaches `identity` / `address_on_id` (residency) as before, but "platform-wide unique" is no longer a claimed state because we no longer enforce it platform-wide. Org-scoped flags handle in-org duplication. `uniqueness_strength` stops being set (or only ever set by the deferred biometric tier). This is the most consistent with "we don't dedup platform-wide anymore."
- **Option B — keep `identity_unique` meaning "verified a real gov ID" without the cross-account-uniqueness claim.** Weaker semantics; risks the state name lying (it says "unique" but nothing enforces uniqueness). NOT recommended — a state called `identity_unique` that doesn't mean unique is a footgun.

**Recommend Option A.** The honest model post-removal: verification proves identity + residency; *uniqueness within an org* is handled by org-scoped flags + admin review; *platform-wide uniqueness* is not claimed (and the biometric tier remains the deferred path for orgs that need real Sybil resistance). Confirm with Z if the team wants B.

## E5 copy implications (Stage 2 touches the honest-scope copy)

- The `DOC_HARD_BLOCK_MESSAGE` ("We couldn't complete identity verification…") is no longer reachable (there's no hard block). Remove it / repurpose. Confirm no FE path still renders it.
- `UP_FRONT_ONE_IDENTITY_COPY` ("You can verify only one account per person…") is now FALSE platform-wide — a person CAN verify on multiple accounts across non-overlapping orgs. **Rewrite it** to be honest: the constraint is per-org (an org may flag/limit duplicate members), not "one account per person platform-wide." Coordinate the exact wording with the content agent; the spec requirement is "don't claim a platform-wide one-account guarantee we no longer enforce."
- This dovetails with the still-pending privacy-copy pass (gated on the purge fix). Note for the content agent: the dedup posture shifted from "platform-wide document uniqueness" to "org-scoped duplicate review."

## Stage 2 verification matrix

| Check | Required | Notes |
|---|---|---|
| Doc-block gone (side-effect) | ✅ | Two accounts, same document, different non-overlapping orgs → BOTH verify successfully, NO `duplicate_document` audit, NO `collision_rejected`. (The exact case the old block prevented.) |
| Same document, SAME org → still flagged | ✅ | The name-based org-scoped flag still catches same-person-same-org (via name+DOB+address). Removing the doc-block does NOT remove in-org dedup. Assert a flag is still raised for a same-org duplicate. |
| `doc_number_hash` no longer written | ✅ | A new verification leaves `doc_number_hash` NULL (or the column is gone). No platform-wide uniqueness lookup runs. |
| Mapper no longer reads doc_number_unique | ✅ | `map_decision_to_state` signature/logic updated; uniqueness rung per the chosen option. |
| Index dropped, migration cycle + PG smoke | ✅ | Partial-unique index on `doc_number_hash` dropped; reversible; both modes. |
| No orphaned references | ✅ | No code path references the removed collision logic, the IntegrityError doc-hash catch, or `doc_number_hash` (except the deprecated-column comment if the column is retained). |
| Copy honesty | ✅ | `UP_FRONT_ONE_IDENTITY_COPY` rewritten (no platform-wide one-account claim); `DOC_HARD_BLOCK_MESSAGE` removed/unreachable confirmed. |
| Adjacent regression | ✅ | Full suite green. |

## Stage 2 sequence
Migration (drop index) → remove collision logic + IntegrityError catch → stop computing/storing `doc_number_hash` → update mapper + uniqueness rung (Option A) → update docstrings + copy → confirm no orphaned refs. Deploy. Verify the two-accounts-same-doc-different-orgs case on prod (Z + spouse, or two test accounts).

---

## Invariants (both stages)
- **Confidence-determines-scope, now fully org-scoped:** no platform-wide dedup action remains; all dedup is org-scoped flags → existing approval queues → admin adjudication.
- **Derived, never stored:** `is_org_verified` stays computed-on-read (open flags either tier + resolved_same demoted-side). No stored verified boolean.
- **Cardinality floor:** no verification-status change (flag, demotion) ever auto-strips a seated role below the governor floor.
- **Cross-org ignored:** detection only ever runs against the user's own orgs (join, promote, and now verify-time).
- **Additive-layer:** a verification-unconfigured org is byte-for-byte unchanged.
- **No raw PII:** the two name-based hashes remain the only dedup data; with `doc_number_hash` gone, even the reversible document fingerprint is no longer stored.

## Closeout must report (both stages)
Stage 1: pre-flight wiring confirmation (was join-detection actually wired?); verify-time trigger side-effect; the active-member-not-flipped-to-pending asymmetry; both-tier settings + defaults; both-tier predicate invalidation; resolved_same demotes-newer (+ the demoted_user_id column); resolved_same does-not-strip-roles; migration + PG smoke; parity. Stage 2: the two-accounts-same-doc-different-orgs success case; same-org-duplicate-still-flagged; doc_number_hash no longer written; index dropped; mapper/uniqueness-rung decision (A or B + why); copy-honesty rewrite; no orphaned refs.

## Z-action items
- **Stage 1 grounding:** after Stage 1 deploys, Z re-verifies once → naturally exercises H1 (verify-time detection runs against Z's orgs). If Z + spouse are both members of one test org with matching/non-matching identities, that exercises the flag + the no-false-block paths live. (Optional; unit tests cover it.)
- **Stage 2 grounding:** the clean live test is two accounts verifying the SAME document in two DIFFERENT non-overlapping orgs → both succeed (the case the old block prevented). Z can do this with two test accounts + one document, OR confirm via the unit test if inconvenient.
- **No secrets, no console work, no CLI.** Pepper unchanged (still used for the two name-based hashes). Removing the doc-block does not touch the pepper.
- **Decision already locked by Z:** demote-newer (H4); active-member-not-suspended on verify-time match (H1). The only open build-time decision is the uniqueness-rung option (recommend A) — flag to Z if the team wants B.
