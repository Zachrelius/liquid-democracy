# Phase 108 — Suppress outbound email to fictional demo recipients

Status: DEPLOYED / VERIFIED. Written and executed September 15, 2026. Closeout: `docs/phase108_closeout.md`.

## Goal and dispatch

Prevent Liquid Democracy from consuming email quota for fictional `demo.example` recipients. Z authorized writing and executing this spec, including deployment and verification. Read and execute this document in full; no additional approval gate is required.

Production logs on September 14 show 85 provider-accepted submissions to 85 fictional recipients: 32 daily digests and 53 weekly digests. They occurred immediately before the Resend 80%-quota warning. September 8–15 at investigation time totals 309 submissions, all to `demo.example`. Demo seeding gives these accounts verified addresses and notification presets; the shared sender lacks a guard. Monday adds weekly digests. Resetting preferences is not durable.

## Branch, team, and sequence

Use `phase-108/demo-email-suppression` from `origin/master` at `5d9c921` or a newer compatible master. Preserve the dirty original planning checkout; use an isolated worktree. Merge with `--no-ff` into an isolated integration checkout and push the merge to origin/master without rewriting history.

Small-pass structure: lead authors the spec, integrates, deploys, and closes out; one backend teammate implements/tests; one QA/review teammate independently reviews the boundary and verification evidence. No frontend work.

1. Commit this complete spec before implementation.
2. Implement the common transport guard and meaningful regression tests.
3. Independently review, run focused checks and the backend suite, then merge/push.
4. Verify the exact Railway backend deployment, public health, and live suppression.
5. Record evidence and limitations in PROGRESS.md and a closeout.

## Locked decisions and scope

- Add suppression at the start of `email_service.send_email`, covering every existing caller: digests, queued/event mail, invitations, authentication mail, and alerts. Audit for direct transport bypasses.
- Match the recipient mailbox's exact domain `demo.example`, case-insensitively, accommodating surrounding whitespace, display-name mailbox syntax, and an optional terminal DNS dot. Do not match strings merely containing the domain; real addresses and lookalike domains must retain existing behavior. Subdomains and unrelated reserved domains are outside this narrowly authorized fix.
- Perform the check before Resend, SMTP, console body output, and email-result monitoring instrumentation. Log one explicit suppression message without body, subject, or credentials.
- Preserve the boolean contract: intentional suppression returns True (handled without retry), but is neither provider success nor failure and must not reset a real delivery-failure monitoring streak. Document this distinction.
- Do not alter demo users, verification markers, preferences, reset content, in-app notifications, org eligibility, provider settings, secrets, quotas, frontend behavior, or schema. Real people who join demo organizations still receive their configured emails.
- No new dependencies or migration. No paid capacity or infrastructure change.

## Verification matrix

| Check | Required | Notes |
| --- | --- | --- |
| Demo suppression across Resend, SMTP, console | Yes | Assert zero provider/network calls and no console body or delivery metrics; case/whitespace/display-name/terminal-dot coverage. |
| Real-recipient compatibility | Yes | Mock provider boundary; cover successful and failed sends, SMTP fallback, console, and lookalike domains. No real emails during tests. |
| Digest integration | Yes | Real model/notification storage shape; seeded-style verified demo user is processed without external send, while a real address reaches the mocked provider. |
| Monitoring regression | Yes | Suppression cannot clear a real failure streak; real successes/failures retain instrumentation. |
| Focused existing mail/digest/auth/invitation tests | Yes | Include Phase 97 monitoring tests. |
| Full backend suite | Yes | Account for environment skips; Linux CI may provide authoritative full matrix. |
| Compile, diff, independent review | Yes | Inspect all changed files and any direct provider bypasses. |
| Frontend/browser | No | No UI or frontend change; source review suffices for absence of UI changes. |
| PostgreSQL migration smoke | No | No migration. |
| Production deployment and health | Yes | Successful backend deployment row for exact pushed SHA; liveness, readiness, monitor; record unchanged frontend bundle hash. |
| Safe live guard proof | Yes | Run a checked-in verification script in deployed backend against a synthetic `demo.example` address with both transports patched to fail if reached. Assert handled result, no metrics, and suppression log. No DB writes or provider calls; never trigger demo reset/digest tick for QA. |

## Operational notes and closeout

The live proof must have transport tripwires, so an absent/broken guard cannot send an email. Deploy logs or the safe probe establish live code behavior; do not claim a future scheduled digest has already been observed. Natural scheduler-log observations are supplemental. Record tests/count delta, implementation and merge SHAs, deploy ID/status, health, guard-proof output, files, unchanged bundle, and any blocked checks. No automatic background continuation is implied by closeout.
