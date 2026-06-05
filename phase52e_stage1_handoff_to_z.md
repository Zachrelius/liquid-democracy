# Phase 52e Stage 1 — Handoff to Z (mid-pass grounding re-verify)

**Status:** Stage 1 (E1 + E1b) SHIPPED + deployed 2026-06-05.
Master `7b5e249`. Backend redeployed; no migration this stage; alembic
head unchanged at `f1a2b3c4d5e6`. 27 new tests + 494/494 adjacent
regression PASS.

The Z-action below is the spec's required mid-pass grounding
re-verify. Doing it gives us the load-bearing evidence Stage 2 (E2-E5)
needs before it can sensibly build on top.

---

## What I need you to do

**Re-verify yourself on the deployed build.** Settings → Identity
verification → Start verification. Complete the Didit flow as usual.
Don't delete your existing verification first; the same-user idempotency
branch needs your existing `verification_attestation_id` row to match
against.

That's it for the Z-action. Everything below is what I'll check
after, and the bug I'm watching for on the purge side.

---

## What Stage 1 actually changed (so you know what to expect)

### E1 — extractor now reads the real Didit paths

The 52d-shipped `_extract_ocr_fields` probed
`decision.id_verification` (singular object). Your 52d capture showed
Didit actually emits `decision.id_verifications` (plural array). So
your 52d re-verify produced all-None hashes:

```
verification_state = 'identity'
doc_number_hash    = NULL    ← should be set
name_dob_hash      = NULL    ← should be set
name_dob_address_hash = NULL ← should be set
uniqueness_strength   = NULL ← should be 'document_hash'
```

E1 rewrites the extractor against the real plural-array paths:
- `decision.id_verifications[0].document_number`
- `decision.id_verifications[0].first_name` / `.last_name`
- `decision.id_verifications[0].date_of_birth`
- `decision.id_verifications[0].parsed_address.{street_1, city,
  region, postal_code}` (structured form)
- Jurisdiction read from `parsed_address.region` (the full state
  name string, e.g. `"Massachusetts"`); `normalize_jurisdiction` was
  extended to accept full names + map to 2-letter codes, so
  `"Massachusetts"` resolves to `"MA"` and the ladder escalates to
  `address_on_id` correctly.

Issuing state (the document's authority, e.g. `"MA-"`) is
deliberately NOT used for residency — only the holder's address
region is.

### E1b — purge no longer treats 404 as success

You confirmed:
- Manual portal delete works (the deletion capability exists in the account).
- Session `66a70eb2` is fully retained at Didit even though our DELETE got a 404.

So 404 is NOT "already deleted, success" — it's "the delete didn't
work, the data is still there." Stage 1 changes:
- `delete_session` now walks a candidate-path list (extendable via
  the `DIDIT_SESSION_DELETE_PATHS` env var — comma-separated — so when
  your account manager replies, we can prepend the rep-confirmed path
  with a one-env-var update, no code deploy).
- 404 from any candidate → try the next; all-fail → return False.
- The webhook receiver now records two distinct bookkeeping
  statuses: `approved_purged` (confirmed-deleted 2xx) vs.
  `approved_purge_failed` (delete didn't work). A retry sweep can
  find the failed ones later.

### What did NOT change

- The webhook signature verification, the redactor, the doc-number
  hard-block predicate, the same-user idempotency design, the
  fail-toward-keeping-the-verification invariant — all unchanged.
- No migration. Your existing row stays exactly as it is until your
  re-verify webhook arrives.

---

## What I'll check after your re-verify

I'll PG-query your `users` row + bookkeeping rows + audit log and
report back. Specifically:

| Check | What I expect to see (success criterion) |
|---|---|
| New bookkeeping row created at session-start | A `verification_sessions` row for the new Didit session id you generate, status starts `initiated`. |
| Webhook arrives + state writes | After Didit's webhook fires: `verification_state` escalates to `IDENTITY_UNIQUE` or `ADDRESS_ON_ID` (depending on whether `parsed_address.region` resolves; given your prior payload was Massachusetts, `address_on_id` with jurisdiction `MA` is expected). |
| Three hashes written | `doc_number_hash`, `name_dob_hash`, `name_dob_address_hash` all non-NULL on your row. `uniqueness_strength = 'document_hash'`. |
| Idempotency confirmed live | NO `verification.duplicate_document` audit row for your own user id. (Your prior doc-hash matches your new doc-hash, but the predicate is "match AND different user_id" — so re-verify by you should NOT block.) |
| Purge bookkeeping | The new session's row should land at either `approved_purged` (if one of the candidate paths Didit accepts) or `approved_purge_failed` (if none of them work). The latter is the more likely outcome until your account manager replies. |
| Capture log line redacts cleanly | PII still absent from the `didit_webhook_payload_capture skeleton=…` log line. |

If hashes land NULL again, Stage 1's extractor is wrong against your
actual payload shape (despite matching the 2026-06-05 capture) and
I need to debug from a fresh manifest before Stage 2 can build. If
they land non-NULL: green light to dispatch Stage 2.

---

## Optional — useful for Stage 2 but not required

1. **Manually purge the four lingering test sessions from the portal**
   (`61ea6065` from the original 52a round-trip; `237833ae` the
   pre-pepper `config_error`; `66a70eb2` the 52d round-trip; plus
   the new one from this re-verify if its purge fails). This is E1c
   in the spec — independent of the code, just hygiene now that you've
   confirmed the manual delete works. Each manually-deleted session
   is a verified data wipe.

2. **Forward your account manager's reply** whenever it lands. Even
   one line — "the deletion endpoint is `DELETE /v3/sessions/{id}/`
   (plural) with `Authorization: Bearer <api_key>`" — and Stage 2's
   E1b finalization is a one-env-var edit. Without the reply we ship
   Stage 2 with the candidate-walker still trying its list and
   probably continuing to fail; the purge stays open as a known
   issue rather than blocking Stage 2.

3. **Spouse / second-identity test** (the spec's "Optional cleaner
   test"). Not required; useful if you want a live no-false-block
   confirmation against a real second person.

---

## Stage 2 scope (what I'll build after your green light)

Per `phase52e_verification_modes_spec.md`:
- **E2:** three verification modes as org config (verification-to-
  join / verification-to-act / none), riding the existing
  approval infrastructure.
- **E3:** the derived `is_org_verified(user, org)` predicate (NEVER
  stored; computed on read) + the unified capability config (one
  org panel mapping to the existing proposal-floor + role-grant +
  the new delegate-promotion gate).
- **E4:** org-scoped name-based duplicate flags evaluated at
  participation points, routed into the existing approval queues
  (`pending_approval` / `public_accepting` denial-comment), admin
  adjudicates with no platform-admin PII access.
- **E5:** user-facing copy (neutral hard-block message, up-front
  one-identity expectation copy, re-verify gating, honest-scope
  org copy). Privacy claims about purge gated on E1b being proven
  working (your portal observation).

Stage 2 will include a migration (for the `OrgDuplicateFlag` table)
and will deploy as a separate `--no-ff` merge.

---

## Reply with

- "Done, hashes look right" → I dispatch Stage 2.
- "Done, but hashes still NULL" → I debug from the new capture
  before Stage 2.
- "Account manager replied: <endpoint>" → I update the env var
  default + retest the purge before Stage 2.
- "Manually purged the four lingering sessions" → I note it in the
  Stage 1 closeout (E1c done).
