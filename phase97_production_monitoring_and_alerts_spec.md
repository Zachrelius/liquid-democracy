# Phase 97 — Low-Cost Production Monitoring and Actionable Alerts

**Status:** Complete — deployed and production-verified (2026-07-18)

## Goal

Detect pilot-relevant production failures without adding a recurring paid service. Combine an external, same-origin production probe with application-level aggregation so total outage, database loss, background-worker staleness, repeated server errors, upload-capacity pressure, and repeated email-delivery failures produce durable, deduplicated alerts and explicit recovery evidence.

## Branch + delivery

- Branch: `phase-97/production-monitoring`
- Merge: no-fast-forward to `master`, push, wait for Railway, and verify the deployed monitor without creating a fake production incident.
- No new paid vendor, subscription, database table, or schema migration.
- Existing Railway, GitHub Actions, platform-admin accounts, and Resend transport are the only delivery dependencies.
- Production probes are read-only. No destructive data operation and no intentional production 500/error burst.

## Verification matrix

| Check | Required | Notes |
|---|---:|---|
| Monitor unit tests | Yes | Thresholds, staleness, redaction, deduplication, recovery, recipient rules |
| Endpoint tests | Yes | Healthy 200, unhealthy 503, DB failure, public response contains no secrets/private data |
| Request instrumentation tests | Yes | Repeated 5xx counted; health probes and expected 4xx excluded |
| Email instrumentation tests | Yes | Consecutive failures counted and success clears the streak |
| Scheduler integration tests | Yes | Digest/decision-worker staleness and disabled-worker behavior |
| External workflow contract | Yes | Scheduled + manual trigger, retries, deduplicated issue, recovery close, least privilege |
| Existing affected backend suites | Yes | Health, scheduler, email, middleware, settings, startup |
| Full backend suite | Yes | No unexplained regression |
| Frontend build | No | No frontend source change planned |
| Migration / PG smoke | No | Reuses `PlatformSetting`; no schema change |
| Production deploy row | Yes | Railway deployment matching the merge |
| Production monitor smoke | Yes | Homepage, readiness, scheduler, and combined monitor all healthy |
| Alert delivery proof | Yes | Safe platform-admin test alert or transport mock; no fabricated outage |

## Locked decisions

1. **Two independent layers.** A GitHub Actions probe detects total application/database/scheduler failure from outside Railway. An in-process monitor aggregates failures that an uptime-only check cannot understand.
2. **No alert storm.** One alert opens per incident fingerprint; unchanged incidents are suppressed, a materially changed component set may update the incident, and recovery closes it. Internal email alerts use a long reminder interval rather than per-check sends.
3. **Operational recipients only.** Direct monitoring email goes only to active, verified platform-admin accounts. It does not use organization notification preferences and never emails ordinary members.
4. **Fail closed without leaking.** `GET /api/health/monitor` is public like the existing health probes, returns only component names, coarse state, counts, timestamps, and capacity percentages, and never returns exception messages, email addresses, user IDs, database URLs, secrets, ballot/content data, or raw query text.
5. **Thresholds favor signal over noise.** Repeated HTTP failures mean at least 3 non-health 5xx responses inside 15 minutes. Email delivery becomes unhealthy after 3 consecutive transport failures. Digest is stale after 2.5 hours; the decision worker after the greater of 20 minutes or three configured intervals. Upload storage warns at 85% and becomes critical at 95%. PostgreSQL size warns at 80% of the configured 5 GB reference and becomes critical at 90%.
6. **Health checks do not self-poison.** `/api/health*` responses and expected 4xx outcomes never enter the repeated-500 counter.
7. **Email-provider failure has an independent route.** If Resend/SMTP is the failing component, internal alert delivery may also fail; the public monitor returns 503 so the GitHub workflow still opens a durable incident and fails visibly.
8. **Startup grace.** A fresh deployment gets enough time for the first digest and decision-worker heartbeat before null/stale timestamps are treated as incidents.
9. **No automatic remediation.** Monitoring never restarts services, changes Railway settings, flips platform kill switches, or mutates organization/user data.

## Workstreams

### A — Monitoring state and safe snapshot

- Add a small monitoring module with bounded rolling state for request failures and email transport outcomes.
- Query database connectivity/size, scheduler heartbeats, and upload-volume capacity when building a snapshot.
- Return a stable `healthy/degraded` contract plus component-specific operator guidance.
- Persist only incident-delivery state in the existing `PlatformSetting` table so deploys do not reset deduplication.

### B — Application integration and alert delivery

- Record completed/exceptional requests in the existing request middleware.
- Record email transport success/failure at the common `send_email` boundary.
- Add `/api/health/monitor` and a platform-admin-only monitoring status/test-alert surface if needed for safe delivery proof.
- Run a lightweight monitor loop inside the existing single-worker FastAPI process; email platform admins on incident open/change and recovery.
- Keep monitoring failure isolated: it must never take down requests, digest processing, or email delivery.

### C — External production monitor

- Add a GitHub Actions workflow on a twice-hourly off-peak cron plus manual dispatch.
- Probe the public homepage and combined monitor endpoint with bounded retries.
- On failure, create one labeled GitHub issue or leave the existing incident open; fail the workflow so GitHub's scheduled-workflow notification path also fires.
- On recovery, comment with the successful run and close the monitoring issue.
- Use only `contents: read` and `issues: write` permissions.

### D — Runbook and delivery

- Document each component, threshold, evidence source, first response, escalation, silence/deduplication behavior, and known limitations.
- Note that Railway deployment healthchecks are deploy-time gates, not continuous monitoring.
- Note that GitHub scheduled workflows may be delayed and their email notification depends on the repository owner's GitHub notification settings.
- Deploy, confirm live healthy output, manually dispatch the external workflow, and confirm no incident issue is opened for a healthy site.

## Alert content contract

Every incident alert identifies:

- environment and UTC time;
- failing component(s) and threshold crossed;
- coarse observed values;
- up to three sanitized request paths/request IDs for repeated 5xx incidents;
- immediate first check and escalation guidance;
- links to the public monitor and relevant GitHub workflow run where available.

It must not contain private organization content, ballot data, credentials, authorization headers, raw exception bodies, or full request query strings.

## Cost and limits

- GitHub Actions runs twice hourly. Healthy probes should finish in seconds; retries occur only on failure. No new subscription is introduced.
- Resend operational alerts consume the existing transactional quota. Current official free-plan limits are 100 messages/day and 3,000/month; deduplication makes monitoring volume negligible during normal operation.
- Railway's configured deployment healthcheck remains useful for rollout gating but is not continuous monitoring after a deployment becomes active.

## Closeout

Report implementation status by workstream, new alert thresholds, test count/results, no-migration status, files changed, commits/merge, Railway deployment evidence, live health payload, external workflow result, safe alert-delivery evidence, cost impact, and residual limitations. Do not mark Phase 97 complete until production monitoring is active and its healthy path is verified.

## Verification results (pre-deploy)

- Phase 97 monitoring regressions: 15 passed.
- Monitoring-adjacent health, scheduler, email, admin, notification, and security compatibility suites: 253 passed across the two focused runs (the Phase 97 file was included in the first run).
- Full backend suite: 2,998 passed, 18 skipped, 0 failed (four workers, 15m17s). Phase 96 baseline 2,983 + 15 new Phase 97 tests = 2,998.
- Python compile and `git diff --check`: passed.
- GitHub workflow YAML parses and its static contract test passed.
- No frontend source change; frontend build not required by the verification matrix.
- No migration added; PostgreSQL migration smoke is not required.

## Production closeout

- Implementation commit `d7c3a27`; no-fast-forward merge `8fe3fce` to `master`.
- Railway backend deployment `271e7926-305d-4fd6-8628-b1b2e1818de2` matched the merge and reported **Deployment successful**.
- Live smoke passed: homepage 200, readiness 200/database connected, scheduler heartbeat 200, and combined monitor 200 with overall status `ok`.
- Live component evidence at `2026-07-18T17:12:12Z`: database connectivity healthy; PostgreSQL capacity 5.67%; non-health 5xx count 0; email failure streak 0; digest and decision-worker heartbeats current; upload capacity 0.03%; one eligible operational recipient; no issues.
- GitHub Actions manual production-monitor run `29653540197` completed successfully in 8 seconds against merge `8fe3fce`. The healthy run opened no monitoring incident.
- Safe alert-delivery evidence is covered by the mocked common-email transport integration and test-alert endpoint regression tests; no fabricated production outage was generated.
- Closeout commit `4928f33`; no-fast-forward closeout merge `da2f28b`. The workflow's `actions/github-script` dependency was raised from v7 to v8 after the first production run exposed GitHub's Node 20 retirement warning. Manual run `29653634264` then verified the final workflow revision: success in 7 seconds with no annotations and no open `production-monitor` incident.
- No new subscription or recurring paid service was added. Normal healthy checks send no email and use only the repository's existing GitHub Actions and Railway/Resend resources.

## References

- GitHub Actions scheduled workflows and notifications: https://docs.github.com/en/actions/concepts/workflows-and-actions/notifications-for-workflow-runs
- GitHub Actions workflow syntax: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
- Railway deployment healthchecks: https://docs.railway.com/deployments/healthchecks
- Resend quotas: https://resend.com/docs/knowledge-base/account-quotas-and-limits
