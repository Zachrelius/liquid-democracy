# Phase 92 — Pilot Readiness and Operational Recovery

**Status:** Planning and live sizing complete; infrastructure changes awaiting Z approval (2026-07-13)

## Goal

Turn the post-audit recommendations into a durable pre-pilot plan, then execute the highest-priority operational-recovery work first. The platform is feature-rich enough for a small concierge pilot; this plan prioritizes recoverability, first-use clarity, moderation, accessibility, and operational confidence over additional governance features.

## Branch + delivery

- Branch: `phase-92/operational-recovery`
- Merge: no-ff to `master` only after the selected recovery configuration is implemented and verified.
- Z must approve any Railway backup schedule, volume resize, external backup destination, monitoring vendor, or recurring cost before it is enabled.
- No destructive production-data operation. A restore rehearsal must preserve the source database and have an explicit rollback path.

## Readiness sequence

### P0 — Before relying on a pilot's data

1. **Operational recovery and monitoring**
   - Configure database and upload-volume backups.
   - Prove a restore path without risking the production source.
   - Add external uptime checks and actionable alerts for backend health, repeated 500s, scheduler failures, database capacity, and email-delivery failures.
   - Define simple recovery targets and an incident contact path.

2. **First-ten-minutes and empty-organization audit**
   - Rehearse steward create-org → invite → member registration/email verification → first proposal → vote/delegate → close/result.
   - Test a genuinely empty organization and zero-history member, not only the populated demo.
   - Exercise Chrome, Firefox, Safari, and approximately 380px mobile width.
   - Verify friendly handling of expired invitations, repeat joins/votes, no delegates, no notifications, and zero-node visualizations.

3. **Remaining moderation surface and administrator protection**
   - Add attributed, reversible hide/redact controls for display names, delegate bios, vote rationales, organization names/descriptions, proposal titles/bodies, and abusive message content.
   - Preserve reasons, actor identity, audit events, and author notice.
   - Add passkey or TOTP protection for platform-admin accounts.

4. **Accessibility pass**
   - Run axe/Lighthouse over critical public, member, ballot, visualization, and admin surfaces.
   - Manually verify keyboard-only use, visible/unobscured focus, modal focus trapping, form errors, non-drag ballot alternatives, chart data-table alternatives, contrast, and mobile target sizes.
   - Use WCAG 2.2 AA as the working target without making a compliance claim until the complete surface is assessed.

### P1 — Before broad public outreach

5. **Targeted adversarial security verification**
   - Use OWASP ASVS 5.0 Level 2 as a recorded checklist.
   - Focus on cross-org isolation/IDOR, permission escalation, invitation and verification tokens, WebSocket authorization, upload handling, admin/moderation actions, rate-limit bypass, and session invalidation.

6. **Deferred load test**
   - Run the existing 1x and 5x synthetic workload.
   - Add a vote-open/close burst, scheduler activity, and backend redeploy during browsing.
   - Record latency, errors, database pool pressure, memory, and recovery.

7. **Privacy and pilot operating agreement**
   - Document operator access, ballot/privacy modes, retention/deletion requests, identity-verification vendor involvement, backup posture, incident response, acceptable use, support expectations, and pilot exit/data handling.
   - Keep identity verification optional unless the pilot needs it; make no vendor-deletion promise until deletion is observed end to end.
   - Obtain appropriate legal review before regulated, employment, housing, union, governmental, or legally binding use.

### P2 — Product learning and go-to-market

8. **Privacy-conscious funnel telemetry and feedback**
   - Measure landing → registration → verification → invitation/join → first proposal → first vote → first delegation.
   - Never record ballot contents or sensitive proposal/member content in product analytics.
   - Add an in-product feedback/report-a-problem path that includes page and app version but excludes private content.

9. **Pilot onboarding package**
   - Steward setup call, recommended starter configuration, one-page member guide, sample first proposal, moderation/incident contact, and weekly first-month check-ins.
   - Measure invitation completion, participation, delegation comprehension, steward workload, support interventions, and whether the organization voluntarily runs a second decision.

10. **Narrow initial customer profile**
    - Prefer a known-membership organization of roughly 20–200 people with recurring but correctable decisions and a committed steward.
    - Avoid government, contentious elections, contract ratification, or legally irreversible decisions for the first external pilot.

## Phase 92A — Live backup inventory and cost analysis

Observed from Railway production on 2026-07-13:

| Service | Volume | Mount | Used | Capacity | Utilization | Existing schedules/backups |
|---|---|---|---:|---:|---:|---:|
| Postgres | `postgres-volume` | `/var/lib/postgresql/data` | 435.978 MB | 500 MB | 87.20% | 0 / 0 |
| backend | `user-uploads` | `/data/uploads` | 150.143 MB | 5,000 MB | 3.00% | 0 / 0 |
| **Total** | | | **586.121 MB (~0.572 GB)** | | | **none** |

The database capacity is the immediate concern: 87.2% utilization leaves little room for normal growth and its current used size exceeds Railway's documented manual-backup limit of 50% of volume capacity (250 MB on the present 500 MB volume). Capacity should be increased before taking the first manual snapshot.

### Where Railway backups live

Railway native backups are incremental Copy-on-Write snapshots associated with the source volume. They remain inside the same Railway project and environment. They are convenient for service/volume recovery but are not an independent offsite copy:

- Native backups can only be restored in the same project and environment.
- Wiping a volume also deletes its backups.
- Restoring stages a replacement volume and service redeploy; the source/rollback procedure must be planned before a production drill.

For a pilot, use two layers:

1. Railway native snapshots for fast recovery of both Postgres and uploads.
2. A separate encrypted logical database export at least monthly to a different provider/account, after the destination and privacy controls are chosen. This protects against project/account/provider loss that same-project snapshots do not cover.

### Current pricing and estimate

Railway's current volume and backup storage rate is **$0.15 per GB-month**, billed by the minute. Backups are charged only for blocks exclusive to the snapshots, not as full copies of unchanged data.

Current live primary-volume storage is approximately:

`0.572 GB × $0.15 = $0.086/month`

Recommended native schedule for both volumes:

- Daily: retained 6 days
- Weekly: retained 1 month (normally 4–5 snapshots)
- Monthly: retained 3 months

There would normally be about 13–14 retained recovery points across the three schedules. A deliberately pessimistic upper bound, treating every retained snapshot as a completely independent full copy of today's data, is:

| Coverage | Full-copy upper bound/month |
|---|---:|
| Postgres only | $0.83–$0.89 |
| Uploads only | $0.29–$0.31 |
| **Both volumes** | **$1.12–$1.20** |

Actual native-backup cost should be lower because Railway uses incremental Copy-on-Write storage, but it cannot be predicted exactly before observing changed-block usage. The daily demo reset may churn a meaningful portion of Postgres even when total database size stays flat, so the estimate should not assume near-zero database deltas.

On the Hobby plan, the $5 monthly subscription includes the first $5 of total resource usage. If the project is currently below that usage allowance, backups may add **$0 to the invoice**; if it is already above the allowance, expect up to roughly **$1.20/month at today's data size**, plus growth.

### Recommended immediate configuration

Pending Z approval:

1. Increase `postgres-volume` from 500 MB to **2 GB**. This provides about 4.6× current headroom and raises the documented manual-backup ceiling to roughly 1 GB. Railway bills actual storage, although its filesystem metadata uses approximately 2–3% of configured capacity; the resize should add only about $0.01/month of storage at current data volume.
2. Enable daily + weekly + monthly schedules on **both** `postgres-volume` and `user-uploads`.
3. Create one manual snapshot of each volume after the database resize and confirm the backups appear with expected sizes.
4. Re-check snapshot-exclusive storage and invoice projection after 7 and 30 days; revise schedules only if observed churn is materially higher than the upper-bound model.
5. Design the restore rehearsal before executing it. Preferred proof: restore entirely within Railway to a temporary isolated target, validate schema/head revision and representative row/file counts, and delete the temporary target only after evidence is recorded. Production must remain untouched.
6. Select an independent encrypted offsite destination and retention policy as a separate decision; do not copy production data to a local workstation merely for sizing.

## Phase 92 verification matrix

| Check | Required | Notes |
|---|---:|---|
| Railway live volume inventory | Yes | Complete: sizes, capacities, mounts, and backup counts observed |
| Cost model | Yes | Complete using current official $0.15/GB-month pricing |
| Z approval of resize/schedules | Yes | Pending |
| Postgres volume resized | Yes | Pending; target 2 GB |
| Both backup schedules created | Yes | Pending; daily + weekly + monthly |
| Initial manual backups visible | Yes | Pending |
| Main site/backend health after infra changes | Yes | Pending |
| Restore rehearsal | Yes | Pending; source production DB must remain untouched |
| Seven-day observed backup-cost check | Yes | Follow-up evidence |
| Monitoring/alerts spec | Yes | Next Phase 92 cluster after backups |
| Migration / PG smoke | No | No application schema migration is planned for backup configuration |

## Sources used for the cost model

- Railway Backups: https://docs.railway.com/volumes/backups
- Railway Pricing Plans: https://docs.railway.com/pricing/plans
- Railway Volumes reference: https://docs.railway.com/volumes/reference
- Railway Point-in-Time Recovery: https://docs.railway.com/volumes/point-in-time-recovery
- W3C WCAG 2.2: https://www.w3.org/TR/WCAG22/
- OWASP ASVS: https://owasp.org/www-project-application-security-verification-standard/
