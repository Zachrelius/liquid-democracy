# Phase 107 — Live Connection Security and Resource Safety

## Goal and authorization

Z authorized specification and implementation of high-priority review findings on September 4, 2026. Prevent live tally subscriptions from retaining database connections and prevent subscriptions from receiving updates after their credentials or proposal access cease to be valid. Verify the separately documented Didit credential exposure without disclosing or using the suspected credential.

Branch: `phase-107/connection-session-security`, based on refreshed `origin/master` at `1a8aead`. Work in an isolated linked worktree; preserve the dirty planning checkout. Integrate using a no-ff merge from current origin/master and push only after required checks pass. Do not overwrite concurrent upstream changes.

## Team and sequence

Lead coordinates specification, review, validation and closeout. Backend developer implements connection fixes and regression tests. Independent reviewer verifies security boundaries and QA evidence. Read-only credential investigator establishes what is known and a remediation plan. No new product features or paid infrastructure.

1. Read this entire spec and the latest PROGRESS.md. Reproduce risks in disposable test fixtures.
2. Implement bounded connection/session handling and tests.
3. Run focused compatibility, full backend suite, frontend tests/build if changed, and independent review.
4. Verify CI and deployment identity, readiness and bounded production socket smoke; browser QA per AGENTS.md where available. Clearly disclose unavailable gates.
5. Record credential evidence and safe follow-up plan; do not imply an unverified key is active or revoked.

## Verification matrix

| Check | Required | Notes |
|---|---:|---|
| Existing WebSocket handshake contracts | Yes | Missing proposal, malformed/missing/expired token, outsider, valid member, platform admin |
| Connection lifetime regression | Yes | Actual QueuePool fixture with more simultaneously open sockets than pool capacity; zero retained connection while waiting, ordinary database request succeeds |
| Authorization after connection | Yes | Membership revoked, account deactivated, private scope access removed, proposal deleted, token expires; no later tally payload delivered |
| Cleanup and transport failures | Yes | Disconnect/cancellation/malformed frames and slow/broken clients release manager registrations; bounded sends |
| Fail-closed database error | Yes | Authorization failure/error prevents broadcast and does not leak exception details |
| Healthy tally compatibility | Yes | Eligible subscriber receives unchanged method-aware payload |
| Focused existing suites | Yes | Phase 38 WebSocket/auth and affected voting/visibility coverage |
| Full backend suite | Yes | Baseline latest closeout 3,172 passed / 20 skips; report actual result |
| Frontend tests/build | If changed | Source inventory currently finds no frontend WebSocket consumer; do not invent a new one |
| SQLite/PG migration smoke | If migration added | No migration expected; PG connection proof desirable independently |
| Secret scan | Yes | No credentials in changed files or outputs |
| Production verification | Yes | Exact backend deployment commit, health/readiness/monitor and bounded nonmutating socket check; no production load |

## Status and locked decisions

Status: IMPLEMENTATION IN PROGRESS.

- Preserve the existing `/ws/proposals/{proposal_id}` route and initial JSON auth message. Do not put tokens in URLs or logs.
- Database sessions are short-lived and closed before socket waits or network sends. Never retain a checked-out connection for the socket lifetime. Keep dependency injection testable; update existing fixture overrides explicitly if the session boundary changes.
- Revalidate authorization immediately before each outgoing tally using fresh database state, with periodic idle checks (at most 30 seconds) and token expiry enforcement. A revoked subscriber receives no subsequent update after the next validation observes the committed change.
- Preserve current proposal visibility and platform-admin rules; no new visibility grants. Use the canonical authorization rules, and avoid loading every member merely to authorize one socket where practical.
- Fail closed on failed authorization or database checks; use safe close codes/reasons. Bound handshake size/time and outgoing send time. Remove manager entries in unconditional cleanup and prune empty proposal buckets.
- Authentication and synchronous database work must not block the async event loop. Protect broadcasts from one slow client; avoid unbounded task creation.
- No access-token schema/session-version migration in this pass. The medium-priority HTTP password-reset revocation window remains a separately specified follow-up; do not silently expand into authentication migration.
- No replicas, Redis, worker-count increase, pool-size increase, paid services, identity-provider session creation, production data cleanup, secret rotation, or git history rewriting in this pass. Credential rotation requires a concrete reviewed plan if still needed under the repository's secrets/infrastructure convention.

## Credential workstream

Read documentation/history safely and identify whether there is evidence of revocation. Never print secret values or invoke the suspected leaked key. Recommend revocation/rotation before any history removal, identify deployment dependencies and verification/rollback steps, and propose preventative scanning. Any unresolved provider-side status is explicitly unknown, not evidence of safety.

The confirmed plaintext assignment in the current historical handoff will be replaced with a secure-configuration reference in an ordinary commit. Add a targeted, tested Didit-sensitive-assignment CI guard that scans tracked documentation as well as code, emits only path/line, and documents its limited scope. This prevents recurrence of the specific known miss; it is not a claim of comprehensive secret detection. Historical removal and provider-side rotation remain distinct actions.

## Closeout

Report fixes and regression evidence, per-workstream completion/blockers, full-suite counts, migration status, commit/deployment identity, production checks, unavailable browser gates, unchanged user workspace, and exact remaining credential action. Follow-ups not implemented must be labeled NOT STARTED.
