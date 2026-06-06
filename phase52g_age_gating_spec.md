# Phase 52g — Age-Gating (Derived Age Band, Never Raw DOB)

**Status:** Spec + dispatch. Written 2026-06-06.

Reading order: this doc; `id_verification_arc_backlog.md` (the age-gating locked decision + the keep-list); the shipped `backend/verification.py` (the floor/gate pattern this composes with — but note age is a SEPARATE dimension, NOT a new state rung); `backend/routes/verification.py` `_extract_ocr_fields` + `_apply_decision` (where age gets derived + stored); `backend/verification_provider.py` (the real payload shape).

## Goal

Let an org gate membership / a proposal on a minimum age (e.g. 18+ / 21+), using a **derived age band stored on the user — NEVER the raw date of birth.** A verified user's age is computed once from the Didit payload, bucketed, and stored as a coarse band; the raw DOB continues to be used only as a hash input and then discarded (as today). Minors get a narrower stored band + an auto-promotion date so a user who later crosses a threshold doesn't have to re-verify.

## Locked values decisions (from the backlog — settled, do not re-litigate)

- **Store a derived age RESULT/BAND, never raw DOB.** The raw DOB is already consumed as a hash input in `_extract_ocr_fields` and discarded; this phase adds deriving an age band from it (or from Didit's `age` field) before discard. No raw DOB persists.
- **Adult bands are coarse:** store booleans/bands like "18+: yes", "21+: yes". An adult comfortably over every threshold needs only a coarse "meets all thresholds" representation.
- **Minor auto-promotion (the Z idea, locked):** for a verified user UNDER a gating threshold, store a narrower band (month-granularity) + the date they cross the next threshold, and AUTO-PROMOTE at that date — so a 16-yo who later turns 18 doesn't re-verify to satisfy an 18+ gate. This avoids BOTH raw-DOB storage AND forced re-verification.
- **Age is a SEPARATE gate dimension, NOT a new verification state rung.** Do NOT add age to the `verification.py` ORDER ladder. Age composes WITH the existing floors (a gate can require both `address_on_id` AND 18+), it doesn't sit inside the identity-strength ordering. Keep the two dimensions orthogonal.

## Design — the data model

The crux is representing age without storing DOB while still supporting auto-promotion. Recommended model (team confirms against real `age`/`date_of_birth` payload fields):

- **`verification_age_bands`** — a stored representation of which thresholds the user meets. Two reasonable encodings; team picks at build, document which:
  - **(A) A set of met-threshold integers** (e.g. `[13, 16, 18]` meaning "≥13, ≥16, ≥18 all true; <21"). Compact, extensible to any threshold an org configures.
  - **(B) A small JSON of `{threshold: bool}`** for the platform's supported thresholds. Simpler to read, less flexible.
  Recommend (A) — a sorted list of met thresholds — because orgs configure their own thresholds and a fixed bool-set would need a migration per new threshold.
- **`verification_age_promotes_at`** (nullable datetime) — for a user who does NOT yet meet some platform-relevant threshold, the date they cross the NEXT one. NULL when the user already meets every threshold the platform supports (the common adult case — no promotion needed). A daily tick (or lazy-on-read; see below) promotes them.
- **Granularity invariant:** the stored band must NOT be fine enough to reconstruct DOB. Storing "met thresholds [18]" + "promotes to 21 on 2027-03-01" reveals the user will turn 21 on that date — which IS a DOB leak for the 21st birthday. **Resolution:** store the promotion date at MONTH granularity (first of the month in which they cross), not the exact day. The backlog's "month-granularity" decision is precisely this. A gate satisfied "sometime in March 2027" is close enough for gating and doesn't expose the birth day. Document this as the load-bearing privacy property of the phase.

## Derive-and-discard — where it happens

In `routes/verification.py` `_apply_decision`, alongside the existing hash extraction:
- Read the age signal from the real payload. Didit returns BOTH `decision.id_verifications[0].age` (derived int) AND `date_of_birth`. **Prefer computing from `date_of_birth`** (more reliable than a provider-derived `age` whose as-of date is unclear), but cross-check against `age` if present and log a warning on a large mismatch (data-quality signal). Confirm both fields against a real payload at build.
- Compute met-thresholds against the platform's supported threshold set (see below) + the next-threshold promotion month.
- Store `verification_age_bands` + `verification_age_promotes_at`; **discard the DOB** (it's already only a hash input — do not add a new DOB-storing path).
- demo_stub / backdoor: no real payload → no age band (or a backdoor-settable band for demo, mirroring how provenance is handled; keep demo sealed).

## Supported thresholds

- A platform constant `SUPPORTED_AGE_THRESHOLDS` (e.g. `(13, 16, 18, 21)`) — the thresholds orgs may gate on. Keep it small + explicit; adding one later is a constant change + a backfill consideration (existing verified users' bands were computed against the old set — see the "new additions don't reach existing users" gotcha; a band recompute for existing rows on threshold-set change is the parity concern, though in practice re-verification refreshes it).
- An org gates by choosing one of the supported thresholds. The gate config lives in `settings` JSON, same pattern as the verification floors.

## The gate

- New settings keys (mirror `get_org_verification_floor`'s pattern in `verification.py`):
  - `verification_membership_min_age` (int or null) — min age to join.
  - Per-proposal: a `min_age` analog to `verification_floor` on the `Proposal` model (nullable column) — min age to vote on this proposal. (Confirm whether to add a column or fold into existing proposal verification config; a column matches `verification_floor`'s precedent.)
- A predicate `user_meets_age(user, threshold) -> bool` — reads `verification_age_bands`, returns whether `threshold` is in the met set. Centralized, never reimplemented (same discipline as `user_satisfies_floor`).
- Enforcement composes with the existing floor checks: a join/vote gated on BOTH a verification floor AND a min-age checks both; either failing → the structured 403 (extend the `verification_required_payload` scope/reason so the FE can say "must be 18+" distinctly from "must verify ID").
- **Cardinality-floor invariant (same as every gate):** an age requirement on a role gates the GRANT; a user aging-out is not a thing (age only increases), but a CONFIG change (org raises the min age) must NOT auto-strip a seated role below the governor floor. Same construction as the verification-floor role check — block the mutation, never demote the incumbent.

## Auto-promotion mechanism

When a user's `verification_age_promotes_at` month arrives, their band should gain the crossed threshold. Two options:
- **(A) Lazy-on-read:** `user_meets_age` checks `if verification_age_promotes_at <= now: treat the next threshold as met`. No scheduler. Simpler, no worker, no `start.sh` risk. **Recommend this** — it avoids the digest-worker class of deploy risk entirely (see the standing `start.sh` caution).
- **(B) A daily tick** that recomputes bands. More moving parts, touches the worker/scheduler risk surface. Avoid unless lazy-on-read proves insufficient.
- If lazy-on-read (A): the stored band is "as of verification date" + the promotion month lets the predicate advance it without a write. A periodic cleanup could persist the advance, but it's not required for correctness. **Pick A; note B as the fallback.**

## Verification matrix

| Check | Required | Notes |
|---|---|---|
| Age derived from real payload, DOB discarded | ✅ | A real verification produces `verification_age_bands`; no raw DOB persisted anywhere (assert no DOB column written; grep the write path). |
| Month-granularity promotion date (no DOB leak) | ✅ | `verification_age_promotes_at` is first-of-month, never the exact birth day. Assert the stored value is month-aligned. |
| `user_meets_age` predicate | ✅ | Met threshold → True; unmet → False; lazy-promotion: a user past their promotes_at month now meets the next threshold without a write. |
| Membership min-age gate (side-effect) | ✅ | Under-age user blocked from join with the age-scoped structured 403; over-age passes. Assert membership row state. |
| Proposal min-age gate | ✅ | Under-age blocked from voting; over passes. |
| Composes with verification floor | ✅ | A gate requiring BOTH address_on_id AND 18+ checks both independently; either failing blocks. |
| Cardinality-floor on age-gated role | ✅ | Org raising a role's min-age does NOT auto-strip a seated under-threshold holder below the governor floor. Mirror the verification-floor role test. |
| Age is NOT in the state ladder | ✅ | `verification.py` ORDER unchanged; age is orthogonal. Assert no new rung. |
| demo_stub sealed | ✅ | No real payload → no real age band; demo path unaffected. |
| Additive-layer parity | ✅ | An org with no age gate set behaves byte-for-byte as today. |
| Migration (age band columns + optional proposal min_age) cycle + PG smoke | ✅ | Additive nullable columns. Confirm single head (`e6f7a8b9c0d1` after 52h). |
| Serializer | ✅ | Age band may surface a coarse "verified 18+" badge if useful, but NEVER the promotion date or anything DOB-reconstructing to clients. Default: don't serialize the band unless a UI needs the coarse boolean. |
| Adjacent regression | ✅ | Full suite green. |

## Sequence
Migration (age band columns) → derive-and-discard in `_apply_decision` (compute from real `date_of_birth`, cross-check `age`) → `user_meets_age` predicate (lazy-promotion) → membership + proposal gates → FE (org settings min-age controls + the age-scoped 403 copy) → optional coarse badge. Deploy.

## Z-action items
- **None to run.** No Didit console work, no re-verify required to ship (a future re-verify naturally populates the band; existing verified users get a band on next re-verify, or a one-time backfill computes it — see below).
- **Decision for Z (small, can default):** existing already-verified users (Z) have no age band yet (DOB was discarded at their verification). Options: (a) they get a band on next re-verify (lazy — simplest), or (b) a one-time backfill — but the backfill CAN'T run because the DOB is already gone (we discarded it). So (a) is effectively forced: **existing verified users get an age band only on their next verification.** Flag this clearly — it means age gates won't apply to already-verified users until they re-verify. For a pre-launch platform with ~1 real verified user (Z), this is fine; note it so it's not a surprise.

## Notes for the team
- **Loose end from 52h to confirm (not this phase's job, but flag in closeout):** `IDENTITY_UNIQUE` is still defined in `verification.py` ORDER but no longer produced by the mapper (52h Stage 2 Option A). A future cleanup could remove the dead rung, but removing it renumbers `rank()` — do it deliberately, not as a drive-by. Just note its dead status.
- The "existing users only get bands on re-verify" property is the same shape as the city/locality phase (also only populates on re-verify). Worth stating in the privacy/onboarding copy eventually: "verify once, and you light up every gate your verification supports" — which is the argument for capturing the full long-term field set (age, locality, legal name) in one pass so users don't re-verify repeatedly.
