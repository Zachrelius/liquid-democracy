# Resend quota investigation — September 15, 2026

## Finding

Liquid Democracy's production backend is submitting real emails to fictional demo accounts. This explains the September 14 quota warning.

The warning email arrived at 2026-09-14 09:36:56 UTC (05:36:56 Eastern), reporting 80% of the 100-email daily quota. Railway backend logs show 85 successful Resend submissions between 09:36:37 and 09:36:54 UTC, immediately before the warning. All 85 recipients were distinct addresses at `demo.example`:

| Subject | Count |
| --- | ---: |
| Your Liquid Democracy daily digest | 32 |
| Your Liquid Democracy weekly digest | 53 |
| Total | 85 |

Examples: `hoa_helen@demo.example` (weekly), `hoa_frank@demo.example` (daily), `coalition_jay@demo.example` (daily), `cal_walt@demo.example` (weekly).

## Recurrence

Read-only Railway query: backend deployment logs, filter `Resend`, September 8 00:00 UTC through September 15 at investigation time, limit 5,000. Returned 618 log entries: 309 successful HTTP entries and 309 corresponding email-service send entries. Count each send once.

September 8–13: 32 submissions per day. September 14: 85. September 15 at investigation time: 32. All 309 recorded submissions were to `demo.example`; none were to real recipient addresses. No error-level entries were returned by this query. These are provider-accepted submissions, not confirmed inbox deliveries. The query establishes this app's activity; it does not audit other applications using the Resend account.

## Cause in the checked-out source

- `backend/demo_content/seed_pipeline.py`: demo accounts receive `{username}@demo.example` addresses and `email_verified=True`. Notification presets are restored during demo seeding/reset.
- `backend/digest_scheduler.py`: the worker iterates all users, sends daily digests during the user's 9 a.m. hour, and adds weekly digests on Mondays. The send check requires an address and verified email, but does not exclude fictional demo accounts.
- `backend/email_service.py`: the common sender submits to Resend without a demo-recipient exclusion.

September 14 was Monday, explaining the extra 53 weekly emails. Changing only demo notification preferences is not a durable solution because resets restore them.

## Recommended remediation — NOT STARTED

Add a common outbound-email guard for fictional demo recipients, covering digests and other email paths. Preserve real users' email and the demo's in-app notification experience. Test that demo recipients never reach the provider and real recipients still do. Ship and verify production suppression using logs without sending test emails to external recipients.

No application code, production configuration, production data, or Resend settings were changed during this investigation. No email was sent by the investigator.
