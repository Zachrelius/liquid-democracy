# Phase 52a — Closeout

**Status:** SHIPPED + LIVE round-trip CONFIRMED 2026-06-03
**Branches merged --no-ff to master:**
- `phase-52a/didit-integration` → merge `0a60747` (feature `64f4aa9` includes the handoff doc)
- Final copy fix (label overclaim) folded in below; commit forthcoming this turn
**Migration:** `e0a1b2c3d4f5` (down_revision `d9e4f2a78543`, hex-prefix) applied on prod
**Bundle:** `index-BhW0dUfb.js` (pre-secret build) → `index-CMG-321T.js` (copy fix)
**Spec:** `phase52a_didit_integration_spec.md`

## Scope shipped

Stage 52a only (per dispatch). Stage 52b (free-pool metering) deferred
to a separate verified deploy.

## Per-cluster status

| Cluster | Status |
|---|---|
| C-PROVIDER (`backend/verification_provider.py`) — session, webhook verify, pure mapper | DONE |
| C-MIGRATION (`e0a1b2c3d4f5` — `verification_sessions` + nullifier partial-unique index) | DONE |
| C-NULLIFIER (collision check + audit) | DONE (Branch A — see Z-fork below) |
| C-WEBHOOK (`POST /api/webhooks/didit`) | DONE + live-verified |
| C-SESSION (`POST /api/verification/session`) | DONE + live-verified |
| C-DEMO (demo_stub writable only on demo-only accounts + join-direction guard) | DONE |
| C-JURIS (US-state-code controlled vocabulary in `normalize_jurisdiction`) | DONE |
| C-FE (consent disclosure + Start Verification button on Settings + label copy) | DONE |

## Live round-trip — OBSERVED (Z's account on prod)

Sequence verified against Railway backend logs + direct Postgres query:

1. `POST /api/verification/session` for user `dab7a23a-…` at 18:47:57 →
   our backend called `POST https://verification.didit.me/v3/session/` →
   201 Created → returned `{session_url, session_id, consent_disclosure}`
2. User completed Didit's hosted flow.
3. Three signed `status.updated` webhooks arrived at `/api/webhooks/didit`
   at 18:47:58 (23.7ms), 18:49:47 (21ms), 18:50:30 (30.4ms) — all 200.
4. Final state on Z's row:
   - `verification_state` = `identity`
   - `verification_provenance` = `didit` ✓
   - `verification_attestation_id` = NOT NULL ✓
   - `verification_nullifier` = **NULL**
   - `verification_jurisdiction` = NULL
   - `verification_updated_at` = 2026-06-03 18:50:24
5. `verification_sessions` row: `status = 'approved'`, `webhook_type_last = 'status.updated'`
6. Settings UI rendered "Identity verified" (per Z's confirmation) — fixed to be more honest below.

## 1:N face-search path — ANSWERED by the live payload

**The current Custom KYC workflow does NOT run 1:N face search inline.**
Evidence: the `id_verification` block was Approved (state escalated to
`identity`), but no `face_search` block with an `identity_handle` /
`nullifier` was present, so the nullifier column stayed NULL despite the
mapper being on the capable branch.

What this means: the nullifier UniqueConstraint shipped is currently
**dormant on real data** — Z's row has the only real Didit verification
in prod and its nullifier is NULL. The collision logic is exercised in
unit tests but has not seen a real payload yet.

Two paths to actually populate nullifiers (pick one; either is a small
follow-up, NOT blocking 52a):

- **(i)** Reconfigure the Didit workflow to include 1:N duplicate
  detection inline. The mapper already reads the `face_search` /
  `identity_dedup` block when present. Zero code change.
- **(ii)** Add a backend follow-up call to `POST /v3/face-search/`
  after we see a `decision.id_verification.status == "Approved"`
  webhook. We'd need to introspect Didit's response shape, populate
  the nullifier, then re-emit a `verification.completed` audit row
  with the dedup result.

Recommendation: try (i) first — it's a console toggle if Didit exposes
it for this workflow type, and keeps the webhook as the single source
of truth. If the workflow doesn't support it, fall back to (ii).
Either way, until 1:N is wired, every Didit-verified user lands on
`identity` (not `identity_unique`), which is correct fail-safe behavior.

## Z-fork landed: nullifier-collision policy

**Per Z's dispatch:** Branch (A) — silent reject + audit — shipped.
Branches (B) and (C) were offered in the handoff but Z's response
authorized the closeout without changing the branch. Current behavior:
collision rejects the second account's write, leaves prior state
untouched, writes a `verification.nullifier_collision` audit row,
returns 200 to Didit. The second user gets no visible signal.

This is captured as a known UX gap for a future pass (see Backlog
Items below — the re-verification UX touch-point is the natural
place to also surface collision rejection).

## Copy-overclaim fix folded in

Z called out that the bare "Identity verified" badge implies the
display name matches the ID, which we don't check. `VERIFICATION_STATE_LABELS`
in `frontend/src/verificationLabels.js` now reads:

- `identity` → "Identity verified — a government ID was confirmed for this account"
- `identity_unique` → "… and this ID has not been used on another account"
- `address_on_id` → "… with an address on it"
- `residency_verified` → "Identity verified — residency confirmed against a government ID for this account"

`VERIFICATION_STATE_SHORT_LABELS` untouched (those go in chips/badges
where brevity matters; long-form labels go on Settings + the
admin OrgSettings dropdown).

New bundle: `index-CMG-321T.js`.

## Verification matrix

| Check | Required | Result |
|---|---|---|
| Phase 52a unit tests (mapper + webhook security + collision + demo-stub + serializer) | Yes | 33/33 PASS |
| Phase 52a migration cycle | Yes | 2/2 PASS |
| Adjacent regression sweep (Phase 45-52 + delegation/voting/role) | Yes | 420/420 PASS in 3:36 |
| PG smoke (fresh + upgrade-from-d9e4f2a78543) | Yes | PASS both modes |
| **Live Didit sandbox round-trip** | Yes | **OBSERVED** — user record updated with `provenance='didit'`, attestation id, audit row |
| Webhook security in prod (fail-closed before secret set) | Yes | Confirmed: every POST returned 401 until DIDIT_WEBHOOK_SECRET was set |
| Webhook security in prod (post-secret) | Yes | Test Webhook from Didit console returned 200 (per Z); three real `status.updated` payloads all 200 |
| Serializer guard (nullifier + attestation_id NOT on UserOut) | Yes | PASS (test_phase_52a_didit_integration::TestSerializerGuard) |
| Deploy + demo reset post-deploy | Yes | Demo seed ran on deploy ("existing users: 252" + bible reapply); demo-stub state intact |
| `bash start.sh` prod-mimic | N/A | Deploy did not touch start.sh; migration applied via existing alembic upgrade path. No worker/startup hook touched. |
| FE build clean | Yes | `index-BhW0dUfb.js` then `index-CMG-321T.js` after copy fix |
| FE: `demo_stub` never touched by Didit path | Yes | C-DEMO blocks both directions (the guards are in place; demo personas can't initiate Didit because they're blocked from real-org actions, and the backdoor isn't the Didit path) |

## Test count delta

- Phase 52 Stage 1 adjacent baseline: 385
- Phase 52a additions: +35 (33 integration cases + 2 migration cycle)
- New adjacent regression: 420/420 PASS in 3:36

## Files added / modified

**Backend (10)**
- A `backend/verification_provider.py` — Didit client + HMAC verify + pure mapper + jurisdiction normalizer
- A `backend/routes/verification.py` — session endpoint + webhook receiver
- A `backend/migrations/versions/e0a1b2c3d4f5_phase_52a_didit_session_and_nullifier_unique.py`
- A `backend/tests/test_phase_52a_didit_integration.py` (33 cases)
- A `backend/tests/test_phase_52a_migration_cycle.py` (2 cases)
- M `backend/main.py` — mounts the verification router
- M `backend/models.py` — `VerificationSession` model row
- M `backend/routes/admin.py` — backdoor comment clarifying C-DEMO scope
- M `backend/routes/organizations.py` — `ensure_can_join_real_org` wired into the three join paths
- M `backend/verification.py` — `ensure_demo_stub_writable` + `ensure_can_join_real_org` helpers (+ inline `_user_has_real_org_membership`)

**Frontend (2)**
- M `frontend/src/verificationLabels.js` — CTA copy updated + state-label overclaim fix
- M `frontend/src/pages/Settings.jsx` — new `VerificationSection` component with disclosure flow

**Spec + handoff (3)**
- A `phase52a_didit_integration_spec.md`
- A `phase52a_handoff_to_z.md`
- A `phase52a_closeout.md` (this doc)

## Deploy verification

- Pre-secret deploy: master `0a60747` pushed; bundle flipped in 101s
  to `index-BhW0dUfb.js`. Backend log: `Running upgrade d9e4f2a78543 ->
  e0a1b2c3d4f5, phase 52a — Didit verification sessions + nullifier
  uniqueness`. Startup complete; `/api/health` 200.
- Pre-secret prod smoke: webhook URL returned 401 to both unsigned and
  bogus-signed payloads — correct fail-closed posture.
- Post-secret round-trip: see "Live round-trip" above.
- Copy-fix deploy: forthcoming this turn. New bundle `index-CMG-321T.js`.

## Backlog (NOT 52a — captured per Z)

1. **Re-verification UX.** Once verified, "Start verification" should
   become "Update verification" + a confirmation: "You're already
   verified; re-verifying replaces your current verification and uses
   one check from the shared pool. Continue?" Re-verify is a real
   need (address change, age-out, original was wrong), so don't disable
   it — just gate it behind a confirmation so accidental re-runs don't
   waste a Didit check. The collision-rejection UX (Branch B/C from the
   handoff) is the natural co-located surface; Settings would also
   show the "this identity is already verified on another account"
   message if the current re-verify session was rejected on collision.
   Small follow-up pass.
2. **Display-name-match org option.** A future phase candidate: an org
   admin can require that verified members' display names match the
   name on their ID. Needs values + data-model decision (store legal
   name? use Didit's name-match boolean as a checked-but-not-stored
   gate? force display name to ID name on verify?). Real PII tradeoff
   at design time — store-the-name escalates the privacy posture
   meaningfully. Deliberately deferred past 52b.

## For Z review (load-bearing design choices)

1. **1:N face search did NOT run inline on this Custom KYC workflow.**
   Z's verified row has NULL nullifier. The nullifier UniqueConstraint
   shipped + works at the index level (proven by PG smoke + unit tests)
   but has not exercised a real-data collision. To actually start
   producing nullifiers, follow path (i) or (ii) above. Recommend
   (i) — workflow config — if Didit exposes the toggle.

2. **Collision policy stayed on Branch (A).** Acceptable for ship,
   but folded into Backlog #1 as the natural co-located fix when the
   re-verification UX gets touched.

3. **The webhook receiver accepts both `decision`-carrying and
   `status.updated` payloads gracefully.** Logs show three `status.updated`
   webhooks for Z's session; the receiver wrote the user record on the
   one that carried a `decision` block and ack'd the others. Idempotency
   key is `(session_id, webhook_type)` — replays of the same type are
   no-op 200s, and a later webhook with a different type can still
   apply if it carries fresh decision data.

4. **Sandbox vs. live cost.** Per Z's correction: sandbox runs don't
   count against the 500/mo quota. Z's round-trip used the sandbox flow.
   Going to "real" verifications will start consuming the pool — that's
   Stage 52b's metering job to track.

## Branch state

- `phase-52a/didit-integration` merged via `0a60747` (--no-ff). Branch
  exists locally; safe to delete at next cleanup.
- master at `0a60747` + handoff `64f4aa9` + (this turn) copy fix + closeout.

## What 52b inherits

- Working session + webhook + audit + collision + demo_stub plumbing.
- A NULL nullifier on the only real Didit row in prod — so the
  free-pool metering Stage 52b ships against still needs the 1:N path
  decision (i or ii from above) to land alongside or before billing
  starts.
- The Custom KYC workflow id is configured in Railway env; 52b can
  read usage from Business Console → Settings → Usage.
