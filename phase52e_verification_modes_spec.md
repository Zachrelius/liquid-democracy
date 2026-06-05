# Phase 52e — Verification Modes + Org-Scoped Flags + Real-Data Grounding

**Status:** Spec + dispatch. Written 2026-06-04. **Do NOT dispatch until 52d has shipped AND both Z-actions are done: (1) the real `VERIFICATION_HASH_PEPPER` sealed variable is set in Railway, (2) Z has re-verified to ground the real OCR keys.** This phase is written against the real captured payload from the Z re-verify.

Reading order: this doc; `id_verification_arc_backlog.md` §"Locked values decisions" (the three modes + derived verified-member + unified capability config — the full model); `phase52d_hash_dedup_infra_spec.md` + its closeout; the shipped `backend/verification.py` enforcement helpers.

**Dispatch readiness (2026-06-05):** both original Z-actions are DONE (sealed pepper set; Z re-verified) and the REAL OCR key paths are folded into E1. The 52d grounding re-verify + Z's portal inspection surfaced: (1) the extractor probed wrong paths (singular vs the real plural `id_verifications[0]`) → E1 is the rewrite; (2) **the session purge is CONFIRMED non-functional — Z can see all sessions retaining full PII in the Didit portal, including one the DELETE 404'd on** → E1b is now a confirmed bug-fix (not an investigation) with the portal as acceptance test; (3) existing retained sessions need one-time cleanup → E1c. E1b/E1c carry Z-actions (ask the Didit rep the exact endpoint; manually purge existing sessions) that do NOT block dispatch — the team builds in parallel — but the privacy copy (E5) must not claim "we purge / no biometrics retained" until E1b proves (portal-observable) that sessions actually delete. **Until E1b lands, Didit is retaining full PII for every verification; this is the current real state.**

---

## Precondition Z-actions (the phase boundary — both done before dispatch)
1. **`VERIFICATION_HASH_PEPPER` set as a Railway sealed variable** + backed up. Without it, 52d's hashing fails closed (no real hashes), so 52e's real-data grounding can't run.
2. **Z re-verified** on the 52d build → a real payload exists; the 52d key-path manifest reveals the real OCR keys; Z's own re-verify must be idempotent (same doc-number hash, same user → NOT blocked, per 52d D5).

## What this builds (summary — full model in the backlog)
- **E1:** ground the hashing against the real OCR keys (from the Z re-verify manifest).
- **E2:** the **three verification modes** as org config, riding EXISTING approval infrastructure.
- **E3:** the **derived `is_org_verified` predicate** + the **unified capability config** (require verified-member for: public delegate / gated proposals / holding role X).
- **E4:** **org-scoped name-based flags** → routed into the org's existing approval gates (`pending_approval` / the `public_accepting` lifecycle), adjudicated by the org admin.
- **E5:** user-facing copy (neutral hard-block message, up-front one-identity copy, re-verify gating, honest-scope org copy).

---

## Dispatch framing

### Goal
Turn the 52d hashing floor into the org-facing feature: the three modes, a derived per-org verified-member status, a unified "what verification unlocks" config, and the org-scoped duplicate flags that route into existing approval queues for admin adjudication. After this: an org can require verification to join (Mode 1) or to act (Mode 2 — delegate/proposals/roles), suspected duplicates land in the admin's existing approve/deny queue, and the member-list shows a derived "Verified" badge.

### Branch + merge
`phase-52e/verification-modes`. `--no-ff` to master.

### Migration head
Confirm `alembic heads` single head (52d will have advanced it). Hex-prefix. Multi-head → STOP. This phase likely adds org `settings` keys (no migration — JSON) + possibly an `OrgDuplicateFlag` table (migration). Confirm.

### Greater-Phase check
This is a meaty phase (real-data grounding + three modes + derived predicate + unified config + flag eval at participation-time + admin adjudication surface + copy). It MAY trip the Greater-Phase threshold. Flag at build: if it exceeds >5 clusters + >50 tests + a migration, stage it riskiest-first (recommend: E4 flag-eval + the OrgMembership `pending_approval` routing FIRST and isolated — it touches the join/participation path — then the config surface + copy). Lead decides at sizing.

### Verification matrix
| Check | Required | Notes |
|---|---|---|
| Session purge confirmed working (E1b) | ✅ | Portal-observable: a real session DISAPPEARS from the Didit portal after purge. 404 is NOT success. Distinguish confirmed-deleted from delete-failed (retry/alert). The privacy copy depends on this. |
| Real-data hash grounding | ✅ | A real Z verification produces expected hashes against the CONFIRMED real OCR keys. Observed on a real row. |
| Spouse / second-identity no-false-block | ✅ | A distinct identity → different doc-hash → not blocked. (If spouse verifies; else document that only the single-identity path was exercised live.) |
| Derived `is_org_verified` unit + integration | ✅ | Computed = platform-floor-satisfied AND not-duplicate-flagged-in-this-org. Centralized predicate; never reimplemented at call sites. Badge reads it. |
| Three-mode enforcement (side-effect) | ✅ | Mode 1: verified+unflagged → `active`; flagged → `pending_approval` in the existing queue. Mode 2: verified-member gates delegate-promotion / gated proposals / role-grant per the unified config. Mode 3: unset → byte-for-byte today. Assert the resulting rows/states. |
| Unified capability config | ✅ | One org config maps to the existing gates: proposal floor (`verification_floor`), role-grant (`check_role_grant_floor`), delegate-promotion (new gate on `public_accepting`). |
| Cardinality-floor interaction | ✅ | "require verified-member to hold role X" gates the GRANT; a later verification lapse / new flag does NOT auto-revoke a seated role — it flags for review. A verification change can NEVER strand an org below `governance.count_active_governors()`. Test it. |
| Org-scoped flag (side-effect) | ✅ | Same-org name-hash match → flag routed to the existing approval gate + audit; cross-org match → NO flag (computed-but-ignored). High-confidence (`name_dob_address_hash`) vs soft (`name_dob_hash`) → org's configured default action. |
| Org-admin adjudication | ✅ | Admin resolves via the EXISTING approve/deny (membership `pending_approval`) or the `public_accepting` approve/deny + denial-comment. No platform-admin PII access; no cross-org leakage; surface shows WHICH members, not the matched PII values. |
| Additive-layer parity | ✅ | An org with no verification settings behaves byte-for-byte as pre-arc. Phase 48 B0 parity helper. |
| Copy renders, no code leakage | ✅ | All copy surfaces; bundle hash recorded; backend state codes never in copy (Phase 49a rule; extend the shared label source). |
| Adjacent regression | ✅ | The full set green. |
| Serializer | ✅ | Hashes still never serialized; the derived verified-member badge value IS exposed (it's a boolean, not a hash). |

### Team
Continuing dev team. Lead: confirm both Z-actions done + real OCR keys folded in, sizing/staging call, closeout. Backend: E1–E4. FE: the unified config panel + admin adjudication surface (rides existing queues) + E5 copy. QA: real-data observation, three-mode side-effects, the cardinality-floor interaction, flag routing.

---

## Spec body — clusters

### E1 — rewrite `_extract_ocr_fields` against the REAL payload (the load-bearing fix)
**Confirmed from the Z post-pepper re-verify manifest (2026-06-05).** 52d's extractor probed the WRONG paths — `decision.id_verification` (singular) + top-level `decision.address`/`decision.address_state` — but Didit emits a PLURAL ARRAY. Every field came back None → three None hashes → no hashes written → Z's row sits at `identity` with NULL hashes / NULL `uniqueness_strength`. Fail-closed held (no half-written state); this cluster closes the gap. **This is the single most important cluster in 52e** — until it lands, the entire hash-dedup feature produces nothing.

Rewrite `_extract_ocr_fields` to read the real paths (all under the first element of the plural array; handle empty/missing array → all None, fail-safe):
- Document number → `decision.id_verifications[0].document_number`
- First name → `decision.id_verifications[0].first_name`
- Last name → `decision.id_verifications[0].last_name`
- Full name → `decision.id_verifications[0].full_name`
- Date of birth → `decision.id_verifications[0].date_of_birth` (str, ISO-shape `YYYY-MM-DD`)
- Jurisdiction → `decision.id_verifications[0].parsed_address.region` (the full state name, str), normalized through the existing `normalize_jurisdiction` allow-list (full names → 2-letter codes; values off the allow-list → None, and the rung simply doesn't escalate — the safe direction). NOTE: `issuing_state` (3-char) is the document's ISSUING authority, NOT the holder's residence — do NOT use it for residency jurisdiction; `parsed_address.region` is the holder's address region, which is what `address_on_id` means. Use `parsed_address.region`.
- Address components for the `name_dob_address_hash` → use the structured `parsed_address` fields (`street_1`, `city`, `region`, `postal_code`, `country`) normalized via the same canonical form the residency path uses — NOT the freeform `address` string (structured is more stable across re-verifications).

**Defensive shape-handling (the lesson from this gap):** the extractor must tolerate the array being empty, the element missing a field, or `parsed_address` being null (all → None for that field, never a crash). Add a unit test fixture built from the REAL captured payload (PII-redacted) and assert each field extracts to the expected non-None. Also keep a "malformed/empty array → all None, no crash" test.

After E1: Z's NEXT re-verify (the 52e grounding re-verify) will produce three real hashes + escalate the rung to `identity_unique` (no jurisdiction match required for that rung) or `address_on_id` (if `parsed_address.region` normalizes to an allow-listed jurisdiction). That same re-verify is the LIVE idempotency test of the "same hash + same user → not a duplicate" inner branch (52d only exercised it against a synthetic seeded hash because no real hash existed yet).

### E1b — fix the session purge (CONFIRMED non-functional — privacy-load-bearing)
**Z confirmed in the Didit portal (2026-06-05): all sessions retain full PII, including session `66a70eb2` that the receiver tried to DELETE and got a 404 on.** So the 404 is NOT "already deleted, success" — it is "the DELETE did not work, the session is fully retained." The purge is **confirmed non-functional**, and Didit currently holds full PII (document images, selfie, address) for every verification. This is exactly the retention the hash-model design exists to avoid. The receiver's current handling lets the failed DELETE pass quietly (logs a WARN, keeps the verification) — correct fail-toward-keeping for the verification, but it masks that NOTHING is being purged.

This is now a bug-fix with a concrete acceptance test (the portal), NOT an investigation:
- **Fix the DELETE call** — wrong path/verb/auth is the likely cause. Confirm the exact endpoint against Didit's docs + the rep (see Z-action). Current default `DIDIT_SESSION_DELETE_PATH=/v3/session/{id}/`; candidates include `/v3/sessions/{id}/` (plural), no-trailing-slash, or a different verb/route entirely.
- **Acceptance test (portal-observable):** after a successful purge call, the session must DISAPPEAR from the Didit portal. This is the real proof — not an HTTP 200, not a 404. The closeout reports "confirmed a session vanished from the portal after purge." Z can eyeball this.
- **404 must NOT be treated as success** — it's currently a false signal (the session is still there). Distinguish "confirmed deleted" (verified gone) from "delete failed" (retry/alert). A purge that can't be confirmed-gone is a failure, surfaced, not swallowed.
- **Retry path:** a failed purge should retry (background) and, if it keeps failing, alert rather than silently leaving PII retained.

### E1c — purge the EXISTING retained sessions (Z-action, one-time cleanup)
Independent of the code fix: Z's current sessions (the Phase 52a original + the three 52d-era sessions: `61ea6065`, `237833ae` config_error, `66a70eb2`) are sitting in Didit with full PII right now and will persist until explicitly deleted. After E1b proves the delete mechanism works, **Z manually deletes the existing test sessions from the portal** (or the team purges them via the now-fixed API). Also: if the portal offers a manual per-session delete, Z deleting `66a70eb2` by hand confirms the deletion CAPABILITY exists and narrows the bug to the API path specifically (useful signal for the team).

### E2 — the three verification modes (org config over existing infrastructure)
Org config in `settings` JSON (defaults-if-absent → Mode 3 / unset → today's behavior; the additive-layer parity guarantee). The modes ride EXISTING anchors (confirmed in `models.py`):
- **Mode 1 — verification to join.** Org sets a membership floor (the shipped `SETTING_MEMBERSHIP_FLOOR` / `check_membership_floor_for_join` already enforce the floor). New in this phase: a verified-but-duplicate-FLAGGED applicant lands `OrgMembership.status='pending_approval'` (existing status) instead of `active`, surfacing in the org's existing join-approval queue. The flag is a REASON for pending, not a new queue.
- **Mode 2 — verification to act.** Anyone joins; verification gates capabilities (E3). 
- **Mode 3 — none.** Settings unset. Untouched.
- Reuse `Organization.join_policy` + `OrgMembership.status` (`active`/`pending_approval`) — do NOT build a parallel approval system.

### E3 — derived verified-member status + unified capability config
- **Derived predicate `is_org_verified(user, org, db) -> bool`** in `verification.py` (alongside `user_satisfies_floor`, same centralization discipline): True iff `user_satisfies_floor(user, org membership floor)` AND the user is not currently duplicate-flagged-as-open in this org. NO stored flag — computed on read (avoids the seed-time/existing-rows drift class). The member-list "Verified" badge reads this. Cache only if list-perf demands; derived stays source of truth.
- **Unified capability config** (`settings` JSON): "require verified-member for: [public delegate] [gated proposals] [holding role X]". Maps to:
  - gated proposals → the existing per-proposal `verification_floor` + `check_vote_floor_for_proposal` (shipped).
  - holding role X → the existing `SETTING_ROLE_FLOORS` + `check_role_grant_floor` (shipped — already documents cardinality-floor-preservation-by-construction).
  - public delegate → NEW gate: the `public_accepting` promotion checks `is_org_verified` before allowing the submit→approve transition. Rides the existing `DelegateProfile.visibility` approval lifecycle (`public_accepting_submitted_at` / `approved_at` / `denied_comment`).
- **Cardinality-floor invariant (encode + test):** requiring verified-member to hold a role gates the GRANT only. A sitting role-holder who later loses verified status (platform verification lapses, or a new duplicate flag) does NOT get auto-revoked — it FLAGS for admin review. A verification change can NEVER auto-strip a seated role below `governance.count_active_governors()`. Consistent with Stage 1's grant-check-before-write protection + the "removing power requires process" invariant.

### E4 — org-scoped name-based flags → existing approval gates
- **Evaluation:** name-based hash matches checked ONLY between members of the SAME org, at org participation points. Recommend at join (Mode 1) + at the `public_accepting` submit + a backstop at gated-vote-cast (Mode 2). Cross-org matches computed-but-ignored (no double-voting harm across non-overlapping orgs).
- **Confidence → action:** `name_dob_address_hash` match (high confidence, math-verified near-zero false positives) → the org's configured default (may default to block-pending-appeal → `pending_approval`). `name_dob_hash` match (low confidence, false-positives at scale) → route-to-review, NOT auto-block, regardless of org setting (a low-confidence auto-block would wall innocents — the birthday-paradox math). **Confirm the exact default-per-confidence config with Z at build if non-obvious; default low-confidence to review.**
- **Flag record:** an `OrgDuplicateFlag` row (org_id, the two user_ids, confidence level, status open/resolved-distinct/resolved-same, created_at). Audit-logged. Routes into the EXISTING approval gate (membership `pending_approval` or the `public_accepting` pending state) — not a new adjudication UI; the admin resolves it where they already resolve approvals.
- **Adjudication surface:** the existing approve/deny queue, annotated with the duplicate reason. Admin actions: confirm-distinct (clears the flag, suppresses re-flagging the pair) or confirm-same (records it; the actual consequence — restricting one account — is an org-policy call; **recommend v1 = record + notify, leave enforcement manual; surface to Z as a values fork if the team wants to auto-enforce**). NO platform-admin PII access; NO cross-org leakage; the surface shows WHICH two members, NOT the matched name/DOB values (the admin already knows their members).

### E5 — user-facing copy (the honest layer)
- **Document-number hard-block message** (neutral, non-leaky): "We couldn't complete verification for this account. If you think this is a mistake, contact support." NOT "already verified on another account" (leaks another account exists).
- **Up-front expectation copy** before leaving for Didit: "You can verify only one account per person. Each verified identity is tied to a single account."
- **Re-verify gating:** verified users see "Update verification" + a confirmation (replaces current verification, uses a pool check). Don't disable (re-verify is real: address change, age-out, error).
- **Honest-scope org-facing copy:** when an org enables a uniqueness/verification gate, describe the document-hash tier as preventing casual/accidental duplicates, with biometric as a stronger future option. Don't overclaim Sybil resistance.
- Backend codes never leak into copy (Phase 49a rule; extend the shared label source).

### Sequence
E1 (extractor rewrite — load-bearing) → E1b (fix the confirmed-broken purge; portal-observable acceptance; final path gated on the Didit rep reply but buildable in parallel) → E1c (one-time cleanup of existing retained sessions) → E2 (modes config) → E3 (derived predicate + unified config) → E4 (flag eval + routing into existing gates + adjudication) → E5 (copy — privacy claims gated on E1b proving purge works). If Greater-Phase-staged: E1 + E4's participation-path routing land first + isolated.

## Invariants
- **Confidence-determines-scope:** doc-number = global auto-block (52d); name-based = same-org, routed to existing admin approval, never auto-block on low confidence.
- **Derived verified-member, never stored** (no drift).
- **Verification change never auto-strips a seated role below the cardinality floor.**
- **demo_stub sealed; hashes never serialized; additive-layer parity** for unset orgs.
- **Reuse existing approval infrastructure** — no parallel adjudication system.

## Closeout must report
Real-data hash grounding (the confirmed real OCR keys, PII-redacted, documented for future provider work); **the session-purge resolution (the confirmed Didit deletion endpoint + proof a real session is actually gone Didit-side — the privacy claim depends on this)**; spouse/second-identity no-false-block (or why only single-identity was exercised live); the live same-user idempotency-branch exercise (Z's post-E1 re-verify against a now-written hash); the three-mode side-effects; the derived-predicate + unified-config behavior; the cardinality-floor interaction test; org-scoped flag routing (same-org flags into existing queues, cross-org doesn't); admin adjudication (no platform/cross-org PII access); copy renders; the confirm-same enforcement decision (recommend record+notify) + any Z values fork raised; additive-layer parity; adjacent green.

## Z-action items
- **Precondition (done):** sealed pepper set; Z re-verified; real OCR keys folded into E1.
- **Ask the Didit rep (E1b) — does not block dispatch, gates the privacy copy:** confirm the exact session-deletion endpoint (path/verb/auth header). Framed concretely now: "our DELETE to `/v3/session/{id}/` returns 404 but the session still shows in the portal — what's the correct deletion call, and do approved sessions auto-expire?" Z has a named Didit rep as of 2026-06-05.
- **One-time cleanup (E1c):** after the delete mechanism is confirmed working, Z manually deletes the existing retained test sessions from the portal (Phase 52a original + `61ea6065`, `237833ae`, `66a70eb2`). If the portal has a manual per-session delete, Z deleting `66a70eb2` by hand now also confirms the deletion capability exists + narrows the bug to the API path (useful signal for the team).
- **Mid-pass grounding re-verify:** after E1 deploys, Z re-verifies once → first real hashes + rung escalation + live same-user idempotency-branch exercise. (Walked through in chat.)
- **Optional cleaner test:** spouse verifies a distinct identity (no-false-block on a real second person) and/or attempts a second account with Z's ID (cross-account doc-number block). Not required.
