# Phase 108 — Demo email suppression closeout

## Scope and root cause

Demo accounts have verified `demo.example` addresses and seeded notification preferences. The production digest scheduler treated them as deliverable recipients, producing 32 daily emails and an extra 53 weekly emails on Monday, September 14. All 309 successful submissions found in the September 8–15 investigation logs went to fictional demo addresses.

The shared sender now suppresses the exact parsed `demo.example` domain before Resend, SMTP, console body output, or delivery-result monitoring. Case, whitespace, display-name syntax, and one terminal DNS dot are handled. Other addresses retain existing behavior, including real people participating in demo organizations. Suppression returns handled=True without resetting a real delivery-failure streak. Existing digest claims prevent retries. No data cleanup, preference changes, schema changes, dependencies, infrastructure configuration, or frontend changes were required.

## Workstreams

- Spec and implementation: DONE. Spec `phase108_demo_email_suppression_spec.md`; code commit `6a683a9`.
- Independent review: DONE, no outstanding findings; `docs/phase108_review.md`.
- Focused regression checks: DONE, 48 new cases and 72 existing compatibility checks passed (120 total).
- Full local backend: DONE, 3,236 passed / 20 skipped / zero failures in 28m47s. Collection included the initial 40 new cases; the final expanded 48-case file passed separately, covering all eight later additions. Relative to Phase 107's 3,196 local passes, this verifies 3,244 distinct passing cases (+48). Linux CI is checking the final 48-case version and is supplemental to these completed local checks.
- Release and production verification: DONE, `224e55329607223a5c44bd2a067953e2c71902d2`, pushed to origin/master and verified live.

## Verification available before release

The new tests assert no provider calls, console body output, or delivery metrics for demo mail under all three provider configurations. They cover exact matching and lookalikes, unchanged real-recipient successful/failed outcomes, monitoring-failure preservation, and real-model daily/weekly digest processing for fictional and real recipients in a demo organization.

Local safe probe and independent rerun pass: handled=True, transports=0, delivery metrics=0, console body=0, exact suppression log. The probe replaces both transports with tripwires and makes no database writes or actual email submissions.

Python compile, whitespace checks, and the repository's scoped Didit-assignment check pass. No migration; PostgreSQL migration smoke is not required. Browser verification is not required by this pass's matrix because no UI behavior changed.

## Files and branch

- `phase108_demo_email_suppression_spec.md`
- `backend/email_service.py`
- `backend/digest_scheduler.py` (boolean-contract documentation)
- `backend/tests/test_phase_108_demo_email_suppression.py`
- `backend/scripts/verify_demo_email_guard.py`
- `docs/resend_quota_investigation_2026-09-15.md`
- `docs/phase108_review.md`
- `docs/phase108_closeout.md`
- `PROGRESS.md` (release evidence)

Branch: `phase-108/demo-email-suppression`. Spec commit `155001a`; implementation commit `6a683a9`; no-ff release merge `224e553`. PR #2 is merged. Original dirty planning checkout is preserved. PR CI run `35034729597` provides Linux/Python 3.11 coverage matching production; frontend and credential checks passed, with its backend job still running at the time of live verification. The PR head and release merge have identical trees. Ordinary master/closeout CI runs may continue independently; their results are not claimed here.

## Production verification

Railway backend deployment `00fa12d4-4fba-4fd2-b2f3-fd38f8784243` is **SUCCESS** for exact release SHA `224e55329607223a5c44bd2a067953e2c71902d2`.

The checked-in probe executed inside the actual deployed Python 3.11.16 backend through Railway SSH:

```text
PASS: demo recipient handled; transports=0; delivery metrics=0; console body=0; suppression log verified
```

The production homepage, `/api/health`, `/api/health/ready`, and `/api/health/monitor` all returned HTTP 200. Health states were `ok`; monitoring reported zero issues. URL: https://www.liquiddemocracy.us. Frontend remains on `index-DKjP7ryU.js`, as expected for this backend-only change.

No actual email was submitted during verification, no demo reset was triggered, and no production data or configuration was changed. A future naturally scheduled digest cycle was not observed or scheduled for background follow-up. The live probe plus shared-boundary source audit establishes suppression in deployed code now. No new technical debt was identified beyond the existing slow full-reset test batch.

## Operational limits

Scope intentionally covers the exact domain `demo.example`; no broader address-policy redesign was undertaken. The probe proves deployed guard execution when run on production, not future scheduler activity. Natural post-deploy digest observations must be identified separately. No outbound email or demo reset is used for verification.
