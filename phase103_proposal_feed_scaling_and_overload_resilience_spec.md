# Phase 103 — Proposal Feed Scaling and Overload Resilience

**Status:** IMPLEMENTATION COMPLETE / LOCAL GATES PASSED / DEPLOY PENDING

**Written:** 2026-08-30, after the Massachusetts Legislature production stress-test incident

**Branch:** `phase-103/proposal-feed-scaling` from the latest clean `master` after Phase 102b

**Priority:** Incident follow-up. Complete this pass before importing, scheduling, or activating another large proposal cohort.

## Goal

Make the ordinary proposal-browsing and login paths remain responsive when an organization has hundreds of active proposals and multiple people use the site at once.

The Phase 103 outcome is deliberately narrower than “solve scaling forever.” It removes the production incident's multiplicative request pattern, bounds proposal-list work, returns understandable errors during overload, and proves the fix against a production-shaped local PostgreSQL fixture. Tally caching, admin-wide pagination, scheduler extraction, and horizontal replicas remain later work.

## Confirmed production incident and root cause

On 2026-08-30, the `ma-legislature` organization had 226 proposals, including 225 in voting. Loading its member proposal page performed:

- one unbounded proposal-list request;
- one `GET /api/proposals/{id}/results` request for every voting/closed proposal; and
- one `GET /api/proposals/{id}/my-vote` request for every voting/closed proposal.

For the 225 active proposals, that was approximately **451 browser requests from one page load**, with the 450 child requests launched concurrently by `Promise.allSettled` in `frontend/src/pages/Proposals.jsx`.

The backend is intentionally a single Uvicorn worker with a SQLAlchemy pool of `pool_size=2` plus `max_overflow=3`. Railway logs captured repeated:

```text
sqlalchemy.exc.TimeoutError: QueuePool limit of size 2 overflow 3 reached,
connection timed out, timeout 30.00
```

Live PostgreSQL inspection during the incident showed all five application connections occupied as `idle in transaction`, no waiting database locks, `max_connections=500`, and healthy storage. The frontend shell itself remained fast. This makes application-side request/connection amplification—not Railway capacity or a PostgreSQL lock—the confirmed primary cause.

The production monitor independently recorded the same pattern:

- `2026-08-30T14:42:45Z`: repeated 500s on `/api/proposals/:id/results`;
- `2026-08-30T14:57:45Z`: recovered after the burst drained;
- `2026-08-30T15:02:45Z`: repeated 500s on `/api/proposals/:id/my-vote`;
- at `2026-08-30T15:07:54Z`, liveness and readiness were both back to 200 in about 0.15 seconds, while the monitor still retained **200 5xx responses in its rolling 15-minute window**.

The user-visible secondary symptoms are also part of this incident:

- login sometimes tried to parse an HTML gateway error and displayed `Unexpected token '<' ... is not valid JSON`;
- public organization discovery displayed `Couldn't load organizations: Server error 504`;
- unrelated requests became slow or failed while proposal child requests occupied the backend.

The Railway CLI session in the planning checkout is expired, so the supplied request IDs were not individually re-queried. This is not a blocker: the monitor samples, endpoint pattern, live pool state, and captured QueuePool trace converge on the same cause. The implementation lead should correlate one supplied request ID during preflight if their Railway session is already authenticated; do not block the pass or ask Z to reauthenticate solely to duplicate this evidence.

## Read order

1. This file, fully.
2. `AGENTS.md`.
3. The latest `PROGRESS.md`, especially Phases 35, 35.1, 97, 101, 102, 102a, and 102b.
4. `docs/scalability_audit_2026-05.md` and `docs/scalability_audit_phase35_1_runbook.md` for the earlier pool sizing and load-test context. The old claim that five connections were “more than sufficient” is now disproven at the new proposal scale.
5. `TECHNICAL_SUMMARY.md` for orientation only; source and newer phase docs win where it is stale.
6. `future_improvements_roadmap.md` for follow-up placement, not authorization to expand this pass.

## Workspace, branch, and delivery discipline

The planning checkout is dirty and local `master` is three commits behind `origin/master` at spec-authoring time. Those existing staged, unstaged, and untracked files belong to Z.

1. Do not stash, reset, clean, overwrite, or otherwise normalize the planning checkout.
2. Create a clean linked worktree from the latest Phase 102b `master`/`origin/master` state.
3. Create `phase-103/proposal-feed-scaling` in that clean worktree.
4. Implement and verify there.
5. Merge to `master` with `--no-ff`, push, wait for both Railway services, and verify production per `AGENTS.md`.
6. Do not synthetic-load production. The production gate is one ordinary browser session plus bounded HTTP smoke.

## Verification matrix

| Check | Required | Notes |
|---|---:|---|
| Incident preflight recorded | Yes | Current health/monitor state, deploy identity, one request-ID correlation if Railway auth already works, and no production mutation. |
| Member proposal feed contract tests | Yes | Access axes, compact shape, cursor stability, filters, sub-org privacy, no cross-org rows, viewer vote summaries. |
| Public proposal feed contract tests | Yes | Public-activity gate, top-level-only scope, no viewer-specific data, cursor/filter parity. |
| Global compatibility feed tests | Yes | Platform-admin/global fallback remains bounded and visibility-correct. |
| Server-side `unvoted` tests | Yes | Direct, delegated, pending-delegate, chain, mixed method, topic precedence, and weighted/unweighted cases. |
| Query-count regression tests | Yes | Eager list projection and batch viewer resolution stay inside the locked budgets below. |
| Frontend request-budget tests | Yes | Initial member page makes no per-proposal `/results` or `/my-vote` calls and at most five total API calls. |
| Frontend pagination/filter tests | Yes | Load more, end state, reset-on-filter, stale response cancellation, errors, read-only behavior. |
| Non-JSON auth/API error tests | Yes | HTML 502/503/504 bodies never reach `res.json()` blindly and never display parser internals. |
| Pool timeout handler tests | Yes | Sanitized JSON 503, `Retry-After`, request ID, rollback/close, no SQL/credential leakage. |
| Health and pool-monitor tests | Yes | Liveness is DB-independent; readiness fails fast; coarse pool saturation component is public-safe. |
| 250-proposal PostgreSQL fixture | Yes | Mixed direct/delegated/unvoted ballot state; deterministic and disposable. |
| 20-concurrent-client load gate | Yes | Zero unexpected 5xx, bounded latency, responsive liveness, no sustained idle transactions. |
| Full backend suite | Yes | Report authoritative counts and delta from Phase 102b's 3,114 passed / 20 skipped baseline. |
| Full frontend tests + production build | Yes | Existing large-chunk warning may remain; no new changed-file lint finding. |
| Migration cycle | If migration added | Upgrade → downgrade → upgrade on SQLite. |
| PostgreSQL migration smoke | If migration added | Prior revision is `e7f8a9b0c1d2`; use `backend/scripts/pg_smoke.py --mode both --prior-revision e7f8a9b0c1d2`. |
| Production deploy verification | Yes | Exact backend deployment, bundle hash, health/readiness/monitor, member/public feed smoke, browser matrix. |

## Suggested team structure

- **Lead:** coordinates, owns incident evidence, contract review, query/load gates, deploy, and closeout. Does not implement directly in the default four-role setup.
- **Backend dev:** B/C/E/F/G clusters, backend tests, PostgreSQL fixture and query/load measurements.
- **Frontend dev:** D cluster, API parser consolidation, request-budget tests, production build, source/browser verification during development.
- **QA teammate:** production browser scenarios after both deploys are live. Per `AGENTS.md`, use the Chrome MCP; if it is still unavailable, report the exact bridge blocker and do not claim rendered QA.

## Sequence

1. Record the read-only incident preflight and baseline request/query measurements.
2. Lock the feed schemas and visibility rules before frontend work begins.
3. Implement the compact cursor-paginated member/public/global feeds.
4. Implement page-batched viewer vote resolution and server-side `unvoted`.
5. Switch proposal browsing and public landing preview to the feed; remove list fan-out.
6. Consolidate JSON-safe client parsing and cancellation/timeout behavior.
7. Add fail-fast pool handling, DB-independent liveness, and pool monitoring.
8. Run focused and full suites, query budgets, PostgreSQL fixture, and concurrent load gate.
9. Merge/push/deploy, then run bounded production HTTP and browser QA.
10. Update `PROGRESS.md`, the scalability audit, and the closeout with measured before/after results.

## Locked decisions

### 1. Remove the list fan-out; do not merely throttle it

`Proposals.jsx` must make **zero** per-card `/results` calls and **zero** per-card `/my-vote` calls. A browser concurrency limiter around the existing 450 calls is not an acceptable final implementation. It reduces the blast radius but preserves work proportional to every proposal in the organization.

### 2. Add a dedicated compact proposal-feed contract

Do not change the response shape of the existing list endpoints in place; multiple admin and Polis surfaces currently expect a raw `ProposalOut[]`. Add dedicated endpoints:

- authenticated org/member: `GET /api/orgs/{org_slug}/proposal-feed`;
- anonymous public activity: `GET /api/orgs/{org_slug}/public/proposal-feed`;
- authenticated global/platform-admin fallback: `GET /api/proposal-feed`.

The full proposal-management pagination retrofit is not part of this pass. Existing raw list endpoints remain compatibility surfaces, but `Proposals.jsx` and `OrgPublicLanding.jsx` must stop using them.

### 3. Feed response is an envelope, not a raw array

Use a typed response equivalent to:

```json
{
  "items": [
    {
      "proposal": {
        "id": "...",
        "title": "...",
        "author": {"id": "...", "display_name": "..."},
        "status": "voting",
        "voting_method": "binary",
        "count_mode": null,
        "stable_result_required": false,
        "sub_org_id": null,
        "topics": [],
        "created_at": "...",
        "voting_start": "...",
        "voting_end": "...",
        "is_election": false,
        "option_count": 2
      },
      "viewer_vote": {
        "has_effective_vote": true,
        "is_direct": false,
        "binary_value": "yes",
        "selection_count": null,
        "cast_by_display_name": "Example Delegate"
      }
    }
  ],
  "next_cursor": "opaque-or-null",
  "has_more": true
}
```

The exact Pydantic class names are an implementation choice. The semantic contract is locked:

- list items contain only fields needed by the list card;
- proposal body, revisions, linked Polis objects, full eligibility state, full user objects, delegate-chain identifiers, ballots, and result time series are absent;
- `viewer_vote` is present only on authenticated member/global feeds;
- public feed items return `viewer_vote: null` or omit it consistently per the typed schema;
- viewer data contains only the caller's safe display summary—never another voter's identity or raw ballot object.

### 4. Aggregate result computation leaves the list page in this pass

Phase 103 intentionally removes live aggregate bars and winner computation from proposal-list cards. Voting cards retain status, deadline, and the caller's vote summary; closed cards retain the Passed/Failed/Unresolved status badge. The proposal detail page remains the authoritative place for live/full results.

Do not call the existing tally engine once per feed item inside one large server request. That would hide the HTTP fan-out while retaining the expensive recomputation and long-held transaction. A later tally-cache pass can restore compact list aggregates from precomputed/versioned data.

### 5. Cursor pagination is mandatory

- Default page size: 25.
- Minimum: 1.
- Maximum: 100.
- Fetch `limit + 1`; do not issue a separate full `COUNT(*)` solely for pagination.
- Cursor is opaque to clients, versioned, URL-safe, and rejected with a typed 422 when malformed.
- Preserve the Phase 31 ordering: voting first (closing soonest), deliberation next (newest first), terminal states next (most recently changed), draft last.
- Add proposal ID as the final deterministic tie-breaker.
- Cursor predicates and ordering must agree for null timestamps and ties; no duplicate or skipped row across adjacent pages.
- A filter/org change resets items and cursor. “Load more” appends only when the request belongs to the current filter generation.

### 6. Visibility must be enforced before pagination

The member feed must preserve parent/sub-org/private visibility exactly. Do not load all rows, remove private sub-org rows in Python, and then paginate; that creates short/empty pages and can expose counts or cursor behavior. Express visibility in the query or an equivalent pre-pagination eligible-ID subquery.

The public feed remains available only for discoverable organizations with `activity_visibility='public'`, contains parent-org proposals only, and returns the same 404 posture as the existing public activity endpoints otherwise.

The global feed keeps the Phase 38 eligible-viewer rule and platform-admin bypass. It is not a shortcut around org access gates.

### 7. Feed filters are server-authoritative

Support `status`, `topic_id`, `cursor`, and `limit` on member/global feeds. Public feeds support every non-viewer filter.

Accepted UI status values are `all`, `deliberation`, `voting`, `unvoted`, `passed`, `failed`, and `archived`; `archived` maps to stored `withdrawn`. `all` keeps the current behavior of hiding withdrawn proposals. Unknown values return typed 422.

`unvoted` means a voting proposal for which no effective ballot is currently attributed to the caller—direct or delegated—matching the existing Phase 76e semantics. Public callers cannot request `unvoted`.

### 8. `unvoted` must not resolve hundreds of proposals through hundreds of route/service calls

Build a batch-capable viewer-state service. It may preload candidate proposal IDs/topics, relevant votes, delegations, and users, then reuse the canonical delegation rules in memory. It must preserve:

- direct vote precedence;
- topic-specific versus org-wide delegation;
- chain behavior and cycle handling;
- pending delegate with no ballot as unvoted;
- approval, ranked-choice, budget-allocation, and budget-project ballot presence semantics;
- verification/eligibility visibility without broadening who can see a proposal;
- weighted voting's ballot-presence semantics (weight affects tally, not whether a ballot exists).

Do not fork a simplified second delegation algorithm whose result can drift from `delegation_engine.resolve_vote`. Extract/reuse canonical pure logic or prove parity with a table-driven regression suite.

### 9. Query budgets are load-bearing tests

For a 25-item page with eager-loaded author/topic/card data:

- ordinary/public feed serialization: at most 12 SQL statements;
- authenticated page plus viewer summaries: at most 30 SQL statements;
- `status=unvoted` across the 250-proposal fixture: at most 40 SQL statements before returning the first page.

The budgets include permission/organization lookup performed inside the request after authentication fixtures are established, but may exclude the test harness's token creation. If source architecture makes one limit impossible without distorting correctness, the lead may adjust it only with a measured baseline, written rationale, and proof that query count does not grow linearly with returned proposal count. “Tests pass” without query-count evidence is not sufficient.

### 10. Frontend request budgets are also load-bearing

For the member proposal page's first render, count calls after the existing organization context is available:

- proposal feed: one;
- topics: at most one;
- sub-org metadata: at most one;
- incidental config call, if already intrinsic to the page shell: at most two;
- total: at most five;
- `/api/proposals/{id}/results`: zero;
- `/api/proposals/{id}/my-vote`: zero.

Each “Load more” action adds exactly one feed request. The anonymous full proposal page adds no member-only calls. The public organization landing preview requests only five proposal items and renders no hidden remainder.

### 11. Preserve useful card behavior while simplifying results

The list card must still show title, status/method, topic badges, author/date, sub-org badge, voting deadline, stable-result marker, count-mode badge, and the caller's vote state where applicable.

Use concise personal states such as “Your vote: YES via Name,” “Your vote: 2 options approved,” “Your vote is recorded,” and “Your vote: Not cast.” Do not claim a live aggregate or winner on the list. Keep accessible loading, empty, error, and pagination states.

### 12. Cancel stale feed work

Use `AbortController` or an equivalent supported mechanism so org/filter changes and component unmount cancel the previous feed request. A canceled request must not display an error, replace newer items, or leave loading state stuck. Add a bounded client timeout for GET/feed/login requests; do not auto-retry mutating methods.

### 13. One content-type-safe response parser serves every API path

Consolidate the normal request, token refresh, form-data, download error, and login error parsing around one safe primitive:

- inspect `Content-Type` before JSON parsing;
- tolerate empty bodies;
- preserve structured Pydantic/SlowAPI detail precedence;
- map HTML/text 502, 503, and 504 responses to a calm temporary-unavailability message;
- never show `Unexpected token`, raw HTML, proxy markup, SQLAlchemy text, or a JavaScript parser exception to the user;
- retain the numeric status for UI logic and tests;
- keep 401/session-expired handling and refresh de-duplication correct.

Suggested user-facing fallback: `The service is temporarily busy. Please try again in a moment.` Network-unreachable copy remains distinct.

### 14. Database pool exhaustion fails quickly and as JSON

Add an environment-configurable SQLAlchemy `pool_timeout` with a safe production default of **5 seconds** (`DB_POOL_TIMEOUT_SECONDS=5`). Add a narrow application exception handler for SQLAlchemy pool timeout that:

- returns HTTP 503;
- returns a sanitized JSON body with stable code `database_busy` and the normal request ID;
- sets `Retry-After: 2` and `Cache-Control: no-store`;
- logs the request ID, sanitized route pattern, and coarse pool occupancy once;
- does not include connection URLs, SQL text, parameters, organization slugs, or user data;
- still lets request dependency cleanup rollback/close the session.

Do not turn arbitrary application exceptions into 503. Do not increase the pool as the primary fix.

### 15. Keep the current pool size until measurements justify a change

The code defaults remain `pool_size=2` plus `max_overflow=3` for this pass. Phase 103 first removes amplified work and tests the result. A production pool-size env change is allowed only if the optimized 20-client load gate still fails specifically on checkout contention and the closeout records before/after memory, latency, and occupancy. Per `AGENTS.md`, changing Railway environment variables is an infrastructure change; surface it to Z before applying it.

### 16. Liveness must not depend on the threadpool or database

Convert `/api/health` to an `async def` route with no sync dependency and no DB access. Under saturated database work it must continue to answer quickly from the event loop.

`/api/health/ready` remains a real database readiness check and may return 503, but it must fail within the configured pool timeout rather than hanging for 30 seconds. Do not leave it queued behind the same saturated AnyIO sync-thread limiter: use an async route with a bounded dedicated execution path and an overall timeout, or an equivalently isolated design. Keep its body public-safe and do not block the event loop with synchronous SQLAlchemy work.

Do not make Railway's liveness endpoint perform a DB query.

### 17. Add coarse pool visibility to monitoring

Expose a public-safe `database_pool` component in the Phase 97 monitor snapshot using SQLAlchemy QueuePool counters—not SQL or connection identities. Include configured size/overflow capacity, checked-out count, current overflow, utilization, and pool timeout. Define tested status thresholds:

- ok below 60% utilization;
- warning at 60–79%;
- error at 80% or any pool timeout in the rolling incident window.

If exact counters are unavailable for a test/SQLite pool, report `unsupported`/`null` rather than failing the monitor. Preserve monitor alert de-duplication and recovery email behavior. Sanitize the new feed routes in 5xx samples.

### 18. No long-lived transaction is acceptable after a feed response

The PostgreSQL load test must inspect `pg_stat_activity` during and after load. Acceptance:

- no application connection remains `idle in transaction` for more than five seconds after its request completes;
- checked-out connections return to baseline within five seconds after traffic stops;
- no waiting locks;
- no connection leak across repeated filter/page cycles.

Do not set a database-wide timeout or mutate production PostgreSQL configuration in this pass. If a per-session `idle_in_transaction_session_timeout` is proposed, it needs focused PostgreSQL tests and must be called out as a scope-up in closeout; it is not required by this spec.

### 19. Add an index only from evidence

Run `EXPLAIN (ANALYZE, BUFFERS)` against the disposable PostgreSQL 250-proposal fixture and a generated 2,500-proposal query-plan fixture for default, voting, topic, and cursor-next-page queries.

If the existing `org_id`/`sub_org_id` indexes plus small bounded sort are adequate, add no migration. If an index materially removes an observed scan/sort bottleneck, add the smallest evidence-backed composite/partial index and include:

- reversible Alembic migration after `e7f8a9b0c1d2`;
- SQLite migration cycle;
- PostgreSQL smoke in both modes;
- before/after plans in the closeout.

Do not add several speculative indexes; write amplification matters for high-volume import.

### 20. No production load test and no user-data dump

All concurrency testing runs against disposable local PostgreSQL or an already-authorized isolated environment. Do not create a paid Railway test project or service without Z's explicit cost/infrastructure approval. Do not print production proposal titles, user identities, ballots, or tokens into fixtures/logs. Aggregate counts and sanitized route patterns are sufficient.

## Scope clusters

### A — Incident preflight and reproducible baseline

Before edits:

1. Record exact source/deploy SHA and service status.
2. Check homepage, `/api/health`, `/api/health/ready`, and `/api/health/monitor` with timing.
3. If Railway auth already works, search one supplied request ID and record only the exception class/pool message and deployment identity.
4. Capture the 225-item before baseline in a small test harness or source-backed calculation (one list plus 225 results plus 225 my-vote calls), then add the final frontend regression assertion that the Phase 103 implementation stays inside its five-call budget.
5. Add backend query-count instrumentation local to tests; do not enable verbose SQL logging in production.

No restart, data edit, archive, lifecycle transition, or environment change belongs in preflight.

### B — Compact keyset-paginated feeds

Add schemas, shared query/service code, and the three endpoints from Decisions 2–7. Requirements:

- one shared ordering/cursor implementation;
- eager load only list-card relationships;
- SQL-enforced org/sub-org/public visibility before `limit`;
- `limit + 1` pagination;
- no body/full-detail serializer use;
- no aggregate tally engine call;
- typed validation and OpenAPI coverage;
- backward-compatible existing detail and raw list endpoints.

The implementation should live in a focused service/module if keeping it inside `routes/proposals.py` or `routes/organizations.py` would duplicate logic.

### C — Batch viewer vote state and `unvoted`

Create the page/batch resolver described in Decisions 7–9. Tests must use real ORM storage shapes, including `Vote.ballot`, and cover:

- binary direct yes/no/abstain;
- approval list;
- ranked-choice ranking;
- budget allocation mapping;
- budget project ranking;
- delegated effective vote;
- delegate found but not voted;
- two-hop chain and cycle;
- topic-specific precedence over org-wide delegation;
- withdrawn/ineligible proposal exclusion;
- no cross-org resolution;
- public response contains no viewer state.

### D — Bounded frontend proposal browsing

Refactor `Proposals.jsx` to consume feed envelopes, render compact cards, and append pages. Add a clearly labeled, keyboard-accessible `Load more proposals` control with in-progress and terminal states. Filters remain persisted per org and reset pagination correctly.

Refactor `OrgPublicLanding.jsx` to request `limit=5` from the public feed. The full public proposals page uses the same feed with `limit=25` and no member-only calls.

Delete the per-proposal `Promise.allSettled` blocks and obsolete tally state/helpers/imports from the list page. Do not disturb detail-page results/vote behavior.

### E — Client and server overload handling

Implement Decisions 12–16. Add tests at both layers:

- HTML 504 login response;
- HTML 502 refresh response;
- empty 503 API response;
- JSON Pydantic error remains authoritative;
- abort is silent;
- timeout produces friendly retry copy;
- simulated QueuePool timeout produces the exact JSON 503 and headers;
- unrelated exception remains 500 and follows the existing sanitized handling.

### F — Pool observability and monitor integration

Implement Decision 17 without making monitor construction brittle. Include rolling pool-timeout observation in memory alongside the existing bounded 5xx recorder, or use another bounded process-local structure. Do not persist request details or add a new paid service.

Update monitor email/rendering tests so an error identifies `database_pool` and gives actionable guidance: inspect fan-out/slow requests and pool checkout duration before raising pool size.

### G — Query plans and optional index

Run Decision 19 after the endpoint shape is final. This is the only discovery-dependent code cluster. Report “no migration; smoke not required” if the plans are already adequate.

### L — Production-shaped load proof

Add or adapt a deterministic load tool and fixture. The required dataset is:

- one public parent organization;
- 250 voting proposals plus representative deliberation/closed/withdrawn rows;
- mixed binary, approval, ranked-choice, budget-allocation, and budget-project methods;
- at least 100 members;
- direct votes, topic/org-wide delegations, two-hop chains, pending delegates, and true unvoted rows;
- enough tied timestamps to exercise cursor ID tie-breaking.

Run against disposable PostgreSQL, not SQLite. Required scenarios:

1. One member initial page and all filter changes.
2. Sequential traversal of every page with no duplicate/missing IDs.
3. Twenty concurrent clients requesting the first member feed page.
4. Twenty concurrent clients split across member feed, public feed, `unvoted`, health, and readiness.
5. Five repeated page/filter cycles per client to catch leaks.

Acceptance on the production-like local run:

- zero unexpected 5xx;
- zero pool-timeout 503s;
- feed p95 at or below 2.0 seconds and p99 at or below 5.0 seconds;
- `/api/health` p95 at or below 250 ms during load;
- first member page payload below 350 KB uncompressed;
- request and SQL budgets from Decisions 9–10 pass;
- post-load pool/transaction conditions from Decision 18 pass.

Record machine/runtime details and raw aggregate output. If local hardware noise misses a latency target while request/query/occupancy curves are sound, do not silently waive it: rerun once, diagnose, and either fix or report the measured blocker.

### T — Regression, documentation, and closeout

Run the full suites and update:

- `PROGRESS.md` with Phase 103 outcome and exact measured delta;
- `docs/scalability_audit_2026-05.md` with an August 2026 incident addendum that supersedes its unmeasured “five connections are sufficient” assumption;
- API/frontend comments that still describe `unvoted` as client-side;
- the follow-up roadmap only for concrete deferred work found during this pass.

Do not revise historical closeouts to make the incident look previously predicted.

## Browser verification scenarios

After both production deploys are confirmed:

1. Sign in as an authorized `ma-legislature` member and open the proposal page. It renders the first page without a long freeze, raw parser error, or 5xx toast.
2. Verify the browser network panel shows zero list-page `/results` and `/my-vote` requests and no more than five API requests after org context is available.
3. Exercise All, Voting, To vote, a topic filter, and Load more. Confirm filter persistence after opening one proposal and returning.
4. Open a proposal detail and confirm full results and vote controls still load there.
5. Visit a public-activity organization's public landing while logged out. It shows at most five proposal previews and the full read-only proposal page paginates.
6. At approximately 380px width, verify cards, filters, and Load more do not overflow and focus order is sensible.
7. Keyboard-only: change filters, activate Load more, open a card, and return.
8. Exercise the non-JSON fallback with a mocked/local HTML 504 response; do not manufacture a production outage.

If a disposable production member account/data is needed, create only the minimum exact-tagged rows and delete them after exact-target verification. Prefer existing authorized accounts and read-only navigation. Do not cast or delete a real Massachusetts ballot for QA.

## Operational watch-outs

- **The current monitor can remain red briefly after recovery.** It retains a rolling 15-minute 5xx count; distinguish live endpoint responsiveness from retained incident state.
- **One server request can still be pathological.** The feed must not loop through the full tally engine merely because the browser no longer fans out.
- **Post-pagination filtering is a correctness/security bug.** Private sub-org visibility and `unvoted` must be resolved before page boundaries.
- **Keyset ordering is easy to get subtly wrong.** Null secondary timestamps and identical timestamps require explicit tests plus the ID tie-breaker.
- **Delegation semantics are load-bearing.** A fast but simplified `has_voted` check that ignores delegated ballots breaks the To vote filter.
- **Avoid masking regressions by enlarging the pool.** Pool tuning may buy headroom but cannot replace bounded work.
- **The login parse error may originate at nginx/Railway.** The client must handle non-JSON even when the FastAPI handler never ran.
- **Do not couple liveness to a sync thread.** A `def` route with no DB still enters Starlette's threadpool and can stall behind blocking sync work.
- **The old raw list endpoints remain a later scalability surface.** They serve several admin tools and must not be casually changed during this incident pass.
- **Chrome QA has recently been blocked.** Follow the current skill/AGENTS path and report the bridge state honestly.

## Explicitly out of scope

- Redis or another paid cache/service.
- Persisted/versioned tally cache or restoring aggregate result bars to list cards.
- Full proposal-management, SubOrgSettings, Polis picker, and admin raw-list pagination.
- Bulk database-wide select-all.
- Multiple Uvicorn workers or Railway backend replicas.
- Moving digest/lifecycle/demo-reset scheduling out of the web process.
- Distributed scheduler locks for multi-instance deployment.
- Production PostgreSQL global timeout changes.
- Synthetic load against production.
- Importing, advancing, archiving, withdrawing, or deleting Massachusetts proposals.
- A paid Railway test project/service without a separate explicit approval.

## Expected follow-ups, not authorized by this spec

1. **Phase 104 candidate — Admin and secondary proposal-list pagination.** Migrate Proposal Management, SubOrgProposals, SubOrgSettings, Polis pickers, and remaining raw-array consumers; then place a hard maximum on legacy list endpoints.
2. **Phase 105 candidate — Versioned tally summaries.** Maintain/invalidate compact list-safe result snapshots on vote, delegation, eligibility, and close events; restore aggregate bars without live recomputation.
3. **Replica-readiness pass.** Extract schedulers or add distributed ownership before increasing `WORKERS` or Railway replicas.
4. **Authorized isolated Railway load run.** Optional only if local PostgreSQL proof leaves platform/network uncertainty worth the cost.

These are **NOT STARTED** and must not be silently absorbed into Phase 103.

## Local execution result — 2026-08-30

All A/B/C/D/E/F/G/L/T implementation and local verification workstreams are
complete. The member proposal page now makes three API calls after org context
(feed, topics, and sub-org metadata) instead of 451 proposal-data calls / 453
page-component calls for the 225-active-proposal incident shape. It makes zero
list-page `/results` and `/my-vote` requests; every Load more action makes one
feed request. Aggregate bars/winner computation were removed from list cards
and remain authoritative on proposal detail.

Measured route SQL counts are member 18, public 5, global 13, and 25 for the
first `unvoted` page across 250 voting proposals. The required PostgreSQL 16
rerun completed 158/158 requests at HTTP 200 with feed p50/p95/p99 of
492.84/1,168.47/1,189.03 ms, health p95 225.32 ms, maximum payload 20,746
bytes, complete 266/266 traversal, peak pool occupancy 5/5 returning to 1/5,
zero pool timeouts, zero stale idle transactions, and zero waiting locks. The
first run's health p95 was 378.15 ms; the required rerun passed rather than
waiving the miss.

The 2,500-row EXPLAIN fixture measured default/voting/topic/cursor queries at
2.905/2.748/5.492/2.764 ms with existing indexes and bounded in-memory top-N
sorts. No index or migration was justified; PostgreSQL migration smoke is not
required. No Railway environment variable or pool-size change was made.

Local verification is green: backend 3,131 passed / 20 environment skips / 0
failed across 3,151 cases (+17 passes/cases from the Phase 102b baseline),
frontend 62/62, changed-file lint, production build, Python compile, focused
compatibility, and diff checks. Production merge/deploy/HTTP/browser evidence
is intentionally pending and will be recorded after rollout; no production
load test will be run.

## Expected file set

Exact names may vary, but the closeout should explain deviations.

- `phase103_proposal_feed_scaling_and_overload_resilience_spec.md`
- `backend/schemas.py`
- `backend/database.py`
- `backend/main.py`
- `backend/ops_monitoring.py`
- `backend/routes/proposals.py`
- `backend/routes/organizations.py`
- a focused feed/batch service module if extracted
- Phase 103 backend contract/query/load/monitor tests
- an optional Alembic migration only if G-cluster evidence requires it
- `frontend/src/api.js`
- `frontend/src/pages/Proposals.jsx`
- `frontend/src/pages/OrgPublicLanding.jsx`
- focused frontend request/pagination/error tests
- a deterministic Phase 103 fixture/load script
- `docs/scalability_audit_2026-05.md`
- `PROGRESS.md`

## Closeout report shape

In addition to the standard `AGENTS.md` closeout, report:

- A/B/C/D/E/F/G/L/T workstream status as DONE / blocked / scoped-up.
- Root cause in one paragraph and why Railway itself was not the primary fault.
- Before/after browser request count for the 225-voting-proposal case (approximately 451 → actual measured Phase 103 count).
- Feed SQL counts at limit 25 and for first-page `unvoted` over 250 proposals.
- Payload size and p50/p95/p99 latency from the PostgreSQL load proof.
- Peak pool occupancy, pool timeouts, post-load checkout baseline, idle-in-transaction observation, and waiting-lock count.
- Exact card UX removed/preserved, including the decision to move aggregate results to detail.
- HTML 502/503/504 parser behavior and exact user-facing message.
- Whether an index/migration was added; if so, before/after plans, cycle, and PG smoke.
- Backend test-count delta from Phase 102b, frontend test/build results, changed-file lint, Python compile, and diff check.
- Files added/modified.
- Commit SHAs, no-ff merge SHA, GitHub Actions run, Railway backend/frontend deployment IDs, and production bundle hash.
- Production health/readiness/monitor state before and after rollout, noting any retained 15-minute incident window.
- Browser QA result for every scenario, or the exact Chrome bridge blocker.
- Any Railway environment change, its measured justification, and Z approval; otherwise state none.
- New debt and the precise recommended next phase. Do not call a follow-up started unless it actually is.

## Go

Read the entire spec, create the clean worktree/branch, and execute Phase 103 through verified production deployment. No additional approval is needed for the code, tests, normal merge/push/deploy, or read-only production checks described here. Pause only for a genuinely irreversible action, destructive production-data change, paid/new infrastructure, Railway environment-variable change, or a material scope decision not resolved by this spec.
