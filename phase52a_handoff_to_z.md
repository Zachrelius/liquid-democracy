# Phase 52a — Handoff to Z

**Status:** Pre-secret build SHIPPED. Master `0a60747` (merge), bundle
`index-BhW0dUfb.js`, migration `e0a1b2c3d4f5` applied on prod.

**Webhook receiver is live + fail-closed.** Confirmed: POST to the URL
without a valid signature returns 401. Will continue to return 401 for
every payload until you set `DIDIT_WEBHOOK_SECRET` in Railway env.

This doc captures what you need to do next before the live sandbox
round-trip can run.

---

## 1) The webhook URL to give to Didit

```
https://www.liquiddemocracy.us/api/webhooks/didit
```

Method: POST. No path params. Receiver verifies `X-Signature`
(HMAC-SHA256 of the raw body) and `X-Timestamp` (Unix seconds, ≤300s
freshness). Idempotent on `(session_id, webhook_type)`.

In the Didit console: **Developers → Webhooks → +** (or whatever the
current console labels the destination-create button as). Paste the
URL above. Didit will generate a signing secret on creation.

---

## 2) Env vars to set in Railway

The Railway CLI was timing out at handoff time for the variable-set
mutation, so I'm passing these to you to set via the dashboard. You
can either set all three in one save and then redeploy, or set each
and let Railway redeploy in between — either works.

| Variable | Value | Source |
|---|---|---|
| `DIDIT_API_KEY` | `HITnnCYceNguO9VueGDOYKvx54lCej2wt_6x3fEJc08` | The workspace key you sent in the dispatch |
| `DIDIT_WORKFLOW_ID` | `44826819-aa15-4473-b208-d60f8b504bd3` | The Custom KYC workflow id you sent in the dispatch |
| `DIDIT_WEBHOOK_SECRET` | (Didit gives this when you create the destination above) | Generated per-destination on creation |

**Railway dashboard path:** `keen-learning` → `backend` service →
Variables → New Variable. Save triggers a deploy. After Railway
finishes the redeploy, the webhook will accept signed Didit payloads.

To confirm the env vars took effect after deploy, you can run from
the repo root with the project token:

```
RAILWAY_TOKEN=$(grep '^RAILWAY_TOKEN=' .env | cut -d= -f2) \
  railway variables --service backend 2>&1 | grep -E "DIDIT_"
```

(Three lines should come back. The CLI's read path works even when
the mutation path is stuck.)

---

## 3) One values fork I need your call on before the live round-trip

**Nullifier-collision handling** when two different accounts produce
the same opaque identity handle from Didit's 1:N face search.

Current build implements the spec's recommended path: **reject the
second**. Specifically:

- The second account's verification record is **not** written.
- The second account keeps whatever verification state it had before
  (usually `email_only`).
- An audit row `verification.nullifier_collision` is written
  (actor = second user, details include `collided_with_user_id` =
  first user's id).
- Webhook returns 200 (Didit's webhook is acknowledged; we declined
  to apply the result).
- No automatic surface to the second user that "your identity is
  already verified on another account."

Real-world: this is "one human, two accounts." Could be innocent
(family device, account-recovery dance, ghost account someone made
years ago and forgot). Could be ban-evasion / sockpuppet construction
on a civic platform.

**Three branches, pick one:**

**(A) Keep current behavior — silent reject + audit.** Lowest
friction; lets support handle it as a one-off when users notice.
Risk: the second user has no visibility into why verification
"failed" — they'll think Didit broke. Audit is internal.

**(B) Reject + visible message to the second user.** Same backend
behavior, but the FE adds a status surface (Settings page or the
structured-403 popup) that reads something like "This identity has
already been verified on another account. If that's a mistake,
contact support." This needs a way for the FE to read the rejected
state — currently the rejection only audits, doesn't surface. Small
FE follow-up.

**(C) Reject + admin notification.** Same as (B) but also emits a
platform-admin notification so a real human reviews the collision.
For a civic platform of this kind, that's defensible — a duplicate-
identity event is a real signal. Heavier; needs a notification path
+ a small admin review surface.

My take: **(B) is the right balance** for a civic platform pre-launch.
It's honest with the user without escalating every collision to ops.
(A) is the "ship and see" option. (C) is correct long-term but a
heavier build for this phase. None of these change the security
boundary; all three reject the second-account write.

Build is currently on (A). I'll convert to (B) or (C) before the
closeout if you pick one. If you want to ship (A) and revisit, that's
also fine — say the word.

---

## 4) Capability fork — confirmed CAPABLE branch

You sent the correction: 1:N face search **is** on the free KYC tier.
The build is on the capable branch (identity_unique + nullifier
populated). One open question for the live round-trip:

**Where does the 1:N face search run?**

- **(i)** Automatically inside the Custom KYC workflow — the
  `face_search` block lands on the webhook decision payload alongside
  `id_verification`. My mapper already reads this shape.
- **(ii)** Separate `POST /v3/face-search/` endpoint we have to call
  after the session completes — we'd add a second-step call.

The mapper handles (i) out of the box. If the sandbox round-trip shows
(ii), I'll add the second-step call before closeout. You can tell me
which path by looking at the workflow's advanced config (is there a
"duplicate detection" toggle on the workflow?) or I can just observe
the sandbox payload — your call.

---

## 5) Live round-trip plan

When the secret + env vars are set + the deploy has picked them up,
the round-trip is:

1. Log in to prod as a real user (your account works; the demo
   personas are blocked by C-DEMO from doing this).
2. Settings → Identity verification → **Start verification**.
3. The disclosure copy appears. Click "Continue to identity provider."
4. Complete Didit's sandbox flow (test ID + test selfie — sandbox
   doesn't count against the 500/mo quota per your note).
5. Webhook fires. Settings → reload. Status should read "Identity
   verified" (and possibly "address on ID" + "CA"-or-similar if the
   parsed address is a US state).
6. Verify the audit log shows a `verification.completed` event.

I'll run this and document the result in the Phase 52a closeout.

---

## 6) What's deferred to Stage 52b (free-pool metering)

Spec: 52a does not enforce / count / bill the free pool. The
counter + metering land in 52b. Today's behavior: prod has
unlimited verification capacity until 52b ships.

---

## What I need from you to unblock

- The webhook URL above added as a Didit destination (and the
  generated secret).
- The three env vars set in Railway.
- The collision branch decision (A / B / C from §3 above).
- Optional but helpful: which workflow-config path runs the 1:N
  face search (auto in workflow vs. standalone endpoint).

Reply with any combination and I'll finish. The round-trip + closeout
are the only items left.
