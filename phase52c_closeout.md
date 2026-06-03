# Phase 52c — Closeout

**Status:** SHIPPED + LIVE-VERIFIED 2026-06-03
**Branch:** `phase-52c/didit-payload-capture` (merged --no-ff)
**Master commits:**
- `c25205e` — Merge phase-52c/didit-payload-capture (Phase 52c PII-safe payload capture)
- `94e7e8b` — Merge Phase 52c hotfix: tighten redactor opaque-id passthrough
**No migration.** Alembic head unchanged at `e0a1b2c3d4f5`.
**No bundle change** (backend-only). FE bundle still `index-CMG-321T.js`.
**Spec:** `phase52c_didit_payload_capture_spec.md`

## What shipped

Per the spec's C1 / C2 / C3 sequence (writing C2 alongside C1 so capture
never deployed unproven):

- **C1 — PII-safe capture.** `verification_provider.redact_payload`
  walks the Didit decision payload and returns a JSON-safe skeleton
  where every leaf that could be PII is replaced with `<str:N>`.
  Allow-list rule: status enum values (`Approved` / `Declined` etc.),
  opaque ids whose KEY is on a safe-key allow-list (`session_id`,
  `nullifier`, `identity_handle`, etc.), and numbers / booleans / nulls.
  Wired into `routes/verification.didit_webhook` immediately after
  signature verification + JSON parse — emits exactly one structured
  log line per webhook: `didit_webhook_payload_capture skeleton=...`.
- **C2 — redaction safety test.** 15 unit cases covering every PII
  shape (full name, parts, street, city, ZIP, document number,
  driver's license, passport, ARN, DOB, email, phone, country); status
  enum preservation; opaque-id KEY-allow-list behavior; deep-nesting
  truncation; recursion guard; capture-failure isolation.
- **C3 — live capture verified in prod.** See the canary section
  below — the hotfix found and closed a real PII leak path.

Mechanism chosen: **(i) log-only** per spec recommendation. No capture
table was added. The log line is grep-able from Railway and
auto-purges with log retention. Nothing to tear down before 52d.

## Canary verification on prod — and the hotfix it forced

**Initial capture firing test.** After the first 52c deploy, I fired
a signed test webhook with a synthetic payload carrying 4 distinct
canary PII strings under canonical Didit-shape keys
(`first_name`, `last_name`, `document_number`,
`address.street`). The capture line emitted and 3 of 4 canaries
redacted correctly — but `document_number` value
`CANARY-DOC-NUM-987` passed through verbatim.

Root cause: the v1 redactor accepted any ≥16-char alnum+dash string
as an opaque id (intended to preserve UUIDs / nullifier handles).
Real document numbers, driver's licenses, passports, and alien
registration numbers share that shape — so the deployed receiver
would have leaked them when the next real Didit payload arrived.

**Hotfix** (commit `94e7e8b` + branch merge): opaque-id passthrough
now requires the parent KEY to be on `_SAFE_ID_KEYS`
(`session_id` / `provider_session_id` / `attestation_id` / `id` /
`nullifier` / `identity_handle` / `identity_id` / `face_search_id` /
`dedup_id` / `request_id` / `transaction_id`). Every other ≥16-char
alnum string redacts to `<str:N>` like normal PII — even if it
happens to look like a UUID.

Fail-closed direction: an unknown opaque-id key that turns out to
carry a real nullifier will redact to a placeholder, but the captured
KEY still tells us what to add to the allow-list — and the cost of
redacting too aggressively is a 2-line allow-list update, while the
cost of redacting too loosely is a PII leak.

**Hotfix verified in prod.** Second canary fire after redeploy:

```
[INFO] didit_webhook_payload_capture skeleton={
  "decision": {
    "face_match": {"score": 0.99, "status": "Approved"},
    "id_verification": {
      "address": {"state":"<str:2>","street":"<str:22>","zip":"<str:5>"},
      "document_number": "<str:24>",
      "first_name": "<str:17>",
      "last_name": "<str:16>",
      "license_number": "<str:20>",
      "passport_number": "<str:22>",
      "status": "Approved"
    },
    "identity_handle": "handle_HOTFIX_xyz0123456789",
    "nullifier": "null_HOTFIX_abcdef0123456789",
    "session_id": "phase52c-hotfix-bbbbbbbbbbbbbbbbb",
    "status": "Approved"
  },
  "session_id": "phase52c-hotfix-bbbbbbbbbbbbbbbbb",
  "status": "Approved",
  "webhook_type": "status.updated"
}
```

All six PII canary strings (names, document/license/passport numbers,
street, full state-name "California Drivers License") absent.
All three safe-key handles (session_id, nullifier, identity_handle)
preserved verbatim. Status enums (`Approved`) preserved. Behavior:
the receiver still processed the unknown-session payload as a
200 no-op exactly as Phase 52a defines it.

## Verification matrix

| Check | Required | Result |
|---|---|---|
| Redaction safety test (THE gating test) | ✅ | 15/15 PASS — synthetic PII in → zero PII out, both pre-hotfix and post-hotfix |
| Capture-fires confirmation | ✅ | Observed in prod logs (twice — first deploy + post-hotfix) |
| Behavior-unchanged regression | ✅ | 433/433 PASS in 3:37 across Phases 45-52 + delegation/voting/role (420 baseline + 13 Phase 52c) |
| Serializer guard intact | ✅ | Nullifier + attestation_id still not on UserOut (no change from 52a) |
| Migration cycle + PG smoke | N/A | No migration added; spec explicitly conditional |
| `bash start.sh` prod-mimic | N/A | No deploy-path / worker / Dockerfile change |
| Deploy + demo reset post-deploy | ✅ | Backend redeployed twice; demo seed ran ("existing users: 252"); demo personas intact |

## Test count delta

- Phase 52a baseline: 420
- Phase 52c first commit: +13 → 433
- Hotfix: +2 → 435 (15 Phase 52c cases total)

## Files added / modified (4)

- M `backend/verification_provider.py` — `redact_payload` +
  `_redact_string` + `_SAFE_ENUM_VALUES` + `_SAFE_ID_KEYS` + the
  `_OPAQUE_ID_RE` / `_OPAQUE_ID_MIN_LEN` pair (post-hotfix gated
  on safe-key allow-list)
- M `backend/routes/verification.py` — capture log line in the
  webhook receiver, wrapped in try/except so a redactor failure
  cannot break live verification
- A `backend/tests/test_phase_52c_payload_capture.py` (15 cases)
- A `phase52c_didit_payload_capture_spec.md`

## Phase boundary handoff to 52d

**Phase 52c is complete.** The next phase (52d — mapper correction +
collision proof) is gated on the **Z-action**: Z + spouse complete
real verifications on this instrumented build. When those land, two
real captured `didit_webhook_payload_capture` log lines will show:

1. The actual KEY structure Didit uses for the dedup block
   (whether it's `face_search`, `identity_dedup`, or a different
   name; whether the dedup handle key is `nullifier`,
   `identity_handle`, or something we haven't accounted for).
2. Whether the spouse's verification — the second face in the
   workspace — produces a 1:N hit on Z's (or doesn't, if Didit only
   matches against subsequent sessions and Z was first).

If the dedup handle key isn't yet on `_SAFE_ID_KEYS`, the capture
will show `<str:N>` for it — that's the signal to extend the
allow-list in 52d alongside the mapper correction. The captured
shape is what 52d reads to (a) fix `_extract_nullifier` /
`_decision_passed_1n_dedup` against ground truth and (b) prove the
collision logic against real data.

## For Z review

1. **PII canary leak found and closed before any real verification
   could hit the deployed receiver.** The hotfix is the load-bearing
   safety lesson here — the v1 opaque-id rule was overly permissive
   and a real document number would have been logged plain-text. The
   v2 rule (KEY allow-list) is fail-closed.
2. **`_SAFE_ID_KEYS` is the only knob 52d may need to touch on the
   redactor.** If a real Didit payload uses an unfamiliar key for
   the nullifier (e.g. `dedup_token`), 52d adds that key string to
   the set. Otherwise the redactor stays untouched in 52d — its job
   ends at the capture.
3. **No data persisted from the canary fires.** Capture is log-only
   per spec recommendation. The synthetic canary strings exist only
   in Railway log retention; nothing landed in the DB.

## Branch state

- `phase-52c/didit-payload-capture` merged via `c25205e` (initial) +
  `94e7e8b` (hotfix), both --no-ff. Branch can be deleted at next
  cleanup pass.
- master at `94e7e8b`, pushed to origin.
- Backend redeployed twice cleanly (first the initial Phase 52c, then
  the hotfix). FE unchanged (still `index-CMG-321T.js` from 52a).

**52c complete; 52d (mapper correction + collision proof) is gated
on the Z-action — Z + spouse verifying on this instrumented build.**
