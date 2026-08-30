# Phase 104 — Admin and Secondary Proposal Pagination

**Status:** LOCAL IMPLEMENTATION VERIFIED / DEPLOYMENT PENDING

**Written:** 2026-08-30, after Phase 103 production verification and Z's manual browser smoke

**Branch:** `phase-104/admin-secondary-proposal-pagination` from `origin/master` at or after Phase 103 closeout `d874245`

**Priority:** Planned scalability completion. This is not a Phase 103 incident hotfix.

## Local implementation result — 2026-08-30

All A–G implementation and local verification clusters are complete on
`phase-104/admin-secondary-proposal-pagination`. Backend commit `db1e1ff`
adds the compact management feed, shared structural eligibility, exact
sub-organization deletion impact, exact Polis reverse links, bounded and
deprecated legacy arrays, regression coverage, and the deterministic
PostgreSQL proof tool. Frontend commit `78a02be` migrates every known internal
consumer to bounded, cancellable pagination while preserving cross-page
selection and partial-retry semantics.

Local verification is green: backend 3,140 passed / 20 environment skips /
0 failed (+9 passed from Phase 103); frontend 69/69; focused backend 9/9;
affected backend compatibility 174/174; changed-file ESLint, production
frontend build, Python compilation, secret scan, and diff checks all pass.
Measured route SQL counts are 7 default management, 8 all-filter management,
6 deletion impact, and 8 Polis links. No migration was added, so migration
cycle and PostgreSQL migration smoke are not required.

The required monitor-enabled PostgreSQL 16 rerun completed 238/238 measured
requests at HTTP 200 with zero pool-timeout 503s or unexpected 5xx.
Management p50/p95/p99 was 106.93/299.72/325.17 ms; health p95 was 85.38 ms;
maximum management payload was 18,391 bytes; and the pool returned from 5/5
peak to its 1/5 baseline within five seconds. Management/sub-organization/
Polis traversals were exactly 250/50/63 rows with zero duplicate, missing, or
unexpected IDs. EXPLAIN evidence at 2,500 proposals justified no index or
normalized-link migration. The first run's measured application requests also
all passed, but its separate monitor sampler returned 503 because monitoring
was disabled in that proof process and its synthetic administrator used an
invalid alert address; the required corrected rerun returned monitor 200
before, during, and after load.

Merge, CI, Railway deployment, and production HTTP/rendered-browser QA remain
pending and are not claimed by this local result.

## Goal

Remove the remaining internal frontend dependence on unbounded full-proposal arrays, make large-organization administration usable without loading every proposal, and place a hard bound plus deprecation signal on the legacy full-list endpoints.

Phase 103 fixed the production-critical member/public proposal path: the 225-active-proposal page fell from as many as 453 page-component requests to exactly three, and the production-shaped concurrency proof completed without pool timeouts, waiting locks, or stale transactions. Phase 104 completes the known admin and secondary surfaces that Phase 103 deliberately left unchanged.

This pass does not restore aggregate result bars, add a tally cache, introduce replicas, or change scheduler ownership.

## Phase 103 baseline and new production observation

Phase 104 starts from the deployed Phase 103 baseline:

- `origin/master` closeout commit `d874245`;
- no-ff Phase 103 merge `ecfed31`;
- backend deployment `bc8a19f7-2eab-4ef9-b5eb-d2fdcd97eed6`;
- frontend deployment `cbf3c86a-92c4-42e0-8e9e-2d1ab2332002`;
- production bundle `index-BvlqA3hN.js`;
- backend 3,131 passed / 20 skipped / 0 failed;
- frontend 62/62 passed;
- 250-proposal load rerun: 158/158 HTTP 200, feed p95 1,168.47 ms, health p95 225.32 ms;
- pool 1/5 baseline, 5/5 peak, 1/5 after five seconds, with zero timeouts.

After deploy, Z manually browsed the site and confirmed that multiple proposal configurations loaded substantially better. The first sign-in attempt briefly asked Z to try again; the second succeeded and subsequent browsing worked normally. Treat that as a transient-overload observation and evidence that Phase 103's friendly fallback works—not as a reproduced auth defect. Phase 104 preflight should check current monitor/pool-timeout/5xx state. Do not alter auth or reopen Phase 103 unless logs or a repeatable test identify a distinct fault.

Rendered Phase 103 Chrome QA remains blocked by the Codex Chrome client's trusted-code-path failure. Z's manual check is useful supplemental evidence but does not retroactively convert that gate to automated rendered QA.

## Confirmed remaining raw proposal consumers

Source review of deployed `origin/master` found these internal calls to `GET /api/orgs/{slug}/proposals`:

1. `frontend/src/pages/admin/ProposalManagement.jsx` — downloads every full `ProposalOut`, then drives the table, expansion rows, and bulk selection in memory.
2. `frontend/src/pages/admin/SubOrgProposals.jsx` — downloads every parent proposal, then filters by `sub_org_id` in the browser.
3. `frontend/src/pages/admin/SubOrgSettings.jsx` — downloads every parent proposal only to count rows that block sub-org deletion.
4. `frontend/src/pages/Polis.jsx` — downloads every visible proposal only to find proposals whose `linked_polis_ids` contain the current Polis.
5. `frontend/src/pages/admin/PolisDetail.jsx` — repeats the same reverse-link scan.

The import-template URL in Proposal Management contains `/proposals` but is not a list and is not part of this migration.

Phase 103 also left the raw authenticated global, member-org, and anonymous public proposal-array endpoints unbounded for compatibility. After the five internal consumers above move, those endpoints must become bounded, explicitly deprecated compatibility surfaces.

## Read order

1. This file, fully.
2. `AGENTS.md`.
3. Latest `PROGRESS.md`, especially Phases 100, 102, and 103.
4. `phase103_proposal_feed_scaling_and_overload_resilience_spec.md`, including its execution results.
5. `backend/proposal_feed.py`, `backend/routes/proposals.py`, `backend/routes/organizations.py`, and `backend/routes/sub_organizations.py`.
6. The five frontend consumers listed above plus `frontend/src/utils/bulkDeliberation.js`.
7. `docs/scalability_audit_2026-05.md`, including the August 2026 Phase 103 addendum.
8. `TECHNICAL_SUMMARY.md` for orientation only; current source and newer phase docs win.

## Workspace, branch, and delivery discipline

The original planning checkout is dirty and is behind `origin/master`. Its staged, unstaged, and untracked files belong to Z.

1. Do not stash, reset, clean, overwrite, or normalize the planning checkout.
2. Create a clean linked worktree from current `origin/master` containing Phase 103 closeout `d874245` or a later Z-approved master.
3. Create `phase-104/admin-secondary-proposal-pagination` in that clean worktree.
4. Implement and verify there.
5. Merge to `master` with `--no-ff`, push, verify both Railway deployments, then run production QA per `AGENTS.md`.
6. Do not load-test production and do not mutate Massachusetts production proposals for QA.

## Verification matrix

| Check | Required | Notes |
|---|---:|---|
| Read-only production preflight | Yes | Deploy identity, homepage/health/readiness/monitor timing, rolling pool timeouts and 5xx. No auth change from one non-reproduced retry. |
| Management-feed contract tests | Yes | Compact shape, filters, cursor, access, private sub-org visibility, eligibility metadata. |
| Management filter/cursor correctness | Yes | Status, scope, title search, eligible operation, stable traversal, malformed cursor. |
| Bulk eligibility parity tests | Yes | Feed metadata/filter agrees with the canonical bulk endpoint preconditions; actions still revalidate. |
| Proposal Management frontend tests | Yes | Bounded initial load, Load more, filters, selection across loaded pages, partial/retry behavior. |
| Sub-org proposal pagination tests | Yes | Server-side sub-org scope, correct empty/load-more behavior, create refresh. |
| Sub-org deletion-impact tests | Yes | Exact counts, authorization, shared predicate with DELETE, race-safe 409, honest copy. |
| Polis proposal-link tests | Yes | Exact JSON membership, visibility before pagination, no false substring matches, two-page traversal. |
| Legacy endpoint bound/deprecation tests | Yes | All three raw array endpoints return at most 50 rows, stable offsets, and deprecation/pagination headers. |
| Internal raw-list call audit | Yes | Zero frontend calls to the three legacy full proposal-list endpoints; import-template/detail/create routes excluded. |
| Query-count budgets | Yes | Management, counts, and Polis links remain within the locked budgets below. |
| 250/2,500-proposal PostgreSQL proof | Yes | Reuse Phase 103 shape; admin traversal, reverse-link plan, legacy cap, 20-client mixed load. |
| Full backend suite | Yes | Report exact delta from Phase 103's 3,131 passed / 20 skipped baseline. |
| Full frontend tests + build | Yes | Report exact test count, changed-file lint, build artifacts, existing bundle warning. |
| Migration cycle | If migration added | Upgrade → downgrade → upgrade on SQLite. |
| PostgreSQL migration smoke | If migration added | Prior revision remains `e7f8a9b0c1d2`; Phase 103 added no migration. |
| Production deployment and HTTP smoke | Yes | Exact deploy IDs, bundle hash, bounded routes, legacy cap headers, monitor. |
| Rendered browser QA | Yes | Chrome MCP per `AGENTS.md`; if trusted-path blocker persists, report blocked and do not claim. |

## Suggested team structure

- **Lead:** coordination, contract review, query/load evidence, legacy endpoint audit, deploy, and closeout. No direct implementation in the default four-role structure.
- **Backend dev:** B/D/E/F/G clusters, API tests, query plans, PostgreSQL load proof, optional migration if evidence requires it.
- **Frontend dev:** C/D/E/F frontend work, request budgets, pagination/filter/selection tests, responsive/accessibility verification during development.
- **QA teammate:** production member/admin/sub-org/Polis scenarios after deploy via the required Chrome MCP.

## Sequence

1. Record production preflight and local before-baseline payload/request counts.
2. Extract/reuse Phase 103 cursor, ordering, and visibility primitives without changing the deployed member/public feed contract.
3. Build the proposal-management feed and canonical bulk-eligibility helpers.
4. Migrate Proposal Management and prove cross-page selection/retry semantics.
5. Migrate SubOrgProposals and add exact sub-org deletion-impact counts.
6. Add the bounded Polis reverse-link endpoint and migrate both Polis pages.
7. Audit internal callers, then cap/deprecate the three legacy raw array endpoints.
8. Run focused/full tests, SQL budgets, EXPLAIN, and mixed PostgreSQL load.
9. Merge/push/deploy and complete bounded production HTTP plus rendered QA.
10. Record Phase 104 in `PROGRESS.md` and the scalability audit.

## Locked decisions

### 1. Purpose-built projections, not one new oversized response

The five callers have three different needs:

- management/sub-org rows;
- deletion-impact counts;
- Polis reverse-link summaries.

Do not make a new “everything an admin might ever need” `ProposalOut`. Full body, options, author objects, linked Polis expansions, engagement settings, tally state, revisions, and viewer ballot state do not belong in list responses unless a listed caller demonstrably renders them.

### 2. Add a compact management feed

Add:

`GET /api/orgs/{org_slug}/proposal-management-feed`

Parameters:

- `cursor`: optional opaque keyset cursor;
- `limit`: default 50, minimum 1, maximum 100;
- `status`: default `all`; accepts every stored proposal status plus `all`;
- `sub_org_id`: optional exact child organization ID;
- `parent_only`: optional boolean, default false;
- `q`: optional title search, trimmed, maximum 100 characters;
- `eligible_for`: optional one of `draft_to_deliberation`, `deliberation_to_voting`, `schedule_start`, or `set_end`.

`sub_org_id` and `parent_only=true` are mutually exclusive and return typed 422 together. Validate that a supplied sub-org is a child of the requested parent; use a visibility-preserving 404/422 posture that does not expose another organization's IDs.

The response is a typed envelope:

```json
{
  "items": [
    {
      "id": "...",
      "title": "...",
      "status": "deliberation",
      "voting_method": "approval",
      "num_winners": 2,
      "created_at": "...",
      "sub_org_id": null,
      "deliberation_end": "...",
      "voting_end_date": null,
      "voting_end": null,
      "is_cosign_gated": false,
      "eligible_operations": ["deliberation_to_voting", "schedule_start", "set_end"]
    }
  ],
  "next_cursor": "opaque-or-null",
  "has_more": true
}
```

Exact schema class names are an implementation choice. The fields and semantics above are locked unless source review proves one additional currently rendered field is required.

### 3. Management `all` includes every status

Unlike the member feed, Proposal Management's default `status=all` includes withdrawn, unresolved, expired-unsigned, and draft rows. This preserves the current admin array's behavior. A status filter is exact; do not map `all` through Phase 103's member-feed rule that hides withdrawn proposals.

### 4. Preserve current ordering and stable keyset behavior

Reuse the Phase 31/103 ordering: voting by nearest deadline, deliberation newest first, terminal states most recently updated, and draft last/newest first. Add proposal ID as the final deterministic tie-breaker.

Use the tested Phase 103 cursor implementation or extract shared cursor/order primitives into a neutral module. Do not copy/paste a second subtly different implementation. Existing Phase 103 cursors and response behavior must remain valid.

Fetch `limit + 1`; do not run a full count for normal pagination. Cursor/filter predicates must agree, including null/tied timestamps.

### 5. Visibility is enforced before filters and page boundaries

The management feed requires active parent membership and preserves the existing proposal visibility axes:

- parent admins/stewards may see all parent/sub-org proposal rows;
- ordinary parent members may see parent-wide rows and non-private sub-org rows;
- private sub-org rows require sub-org membership;
- a sub-org-scoped caller cannot use this endpoint to enumerate sibling-private content;
- no cross-org rows under any filter/cursor combination.

The endpoint is a read projection, not an authorization grant for actions. Existing permission checks on advance/schedule/edit/withdraw remain authoritative.

### 6. Title search is bounded and literal

`q` is a case-insensitive title substring search. Escape SQL wildcard characters so user input remains literal. An empty/whitespace query behaves as absent. Do not search proposal bodies; legal-text bodies make that unnecessarily expensive. Add exact tests for `%`, `_`, Unicode, and overlength input.

### 7. Bulk eligibility has one canonical rule layer

Extract small backend predicates for the four management operations and use them for both feed metadata/filtering and bulk endpoint precondition dispatch where feasible:

- `draft_to_deliberation`: status draft;
- `deliberation_to_voting`: status deliberation and not cosign-gated;
- `schedule_start`: status deliberation and not cosign-gated;
- `set_end`: status deliberation or voting, with no blanket cosign exclusion; request-specific date validation remains per row.

These are list-time structural eligibility rules only. Request-specific timestamps, reasons, permissions, current time, and stale state remain validated by the mutation endpoints. Bulk endpoints must still load/revalidate each ID; never trust `eligible_operations` sent back by a client.

Phase 102's locked operation table allows `Set voting end` for both deliberating and voting proposals without excluding cosign-gated rows. The current frontend helper applies a broader cosign exclusion to that operation even though the backend accepts it. Phase 104 corrects the helper/feed metadata to the Phase 102 contract; it does not change cosign advancement, which remains exclusively controlled by the specialized gate.

Remove or reduce duplicated frontend eligibility logic so it cannot drift. A defensive UI fallback is acceptable, but the server response is authoritative for which checkboxes appear.

### 8. Proposal Management uses append pagination and explicit filters

Replace the raw array call with the management feed. Add accessible controls for:

- status;
- parent/sub-org scope;
- title search;
- current bulk operation's eligible-only view.

Use append-style `Load more proposals`, consistent with Phase 103. Each Load more adds exactly one request. Filter changes cancel stale work, reset the cursor/items, and must not let old responses overwrite the new filter generation.

Do not add numbered pages or a database-wide total count.

### 9. Selection is independent of the current response page

Store selected proposal IDs plus the compact row metadata needed for confirmation in a map keyed by organization. This preserves titles/deadlines for selected rows after more pages load and preserves unsubmitted selections after a partial/network failure.

Locked behavior:

- selection may span multiple loaded pages;
- the header checkbox means **Select all loaded eligible proposals**, never all database matches;
- label and accessible name must say “loaded,” not imply database-wide selection;
- Load more preserves selection;
- changing organization clears selection;
- changing status/scope/search/eligible filter while selection is nonempty asks for confirmation, then clears on confirmation or leaves both selection and filter unchanged on cancel;
- changing bulk operation keeps the existing confirm-and-clear behavior;
- completed/terminal per-item results leave selection exactly as current Phase 100/102 behavior intends;
- requests not submitted because of a network/outer failure remain selected and retryable;
- no database-wide select-all is added.

### 10. Mutations refresh bounded state

Single advance/withdraw, create/import completion, and successful bulk operations refresh the first management page under the current filters. They must not fall back to the legacy full list. Mutation endpoints and audit/notification side effects remain unchanged.

Do not silently lose failed/unsubmitted selections during refresh; reconcile through the selection map and returned per-item results.

### 11. Sub-org proposals reuse the management feed with server scope

`SubOrgProposals.jsx` calls the management feed with its exact `sub_org_id`, default limit 25. It must not download the parent array and filter in JavaScript.

Preserve:

- title/status/created rows;
- detail links;
- create form and parent/sub-org topic rules;
- permissions and inherited settings;
- empty/loading/error states.

Add Load more. A successful create resets/reloads the first scoped page. The endpoint must enforce that the sub-org belongs to the parent and is visible to the caller.

### 12. Add an exact sub-org deletion-impact endpoint

Add:

`GET /api/orgs/{org_slug}/sub-orgs/{sub_slug}/deletion-impact`

Return a typed object:

```json
{
  "topic_count": 2,
  "proposal_count": 14,
  "can_delete": false
}
```

Authorization uses the same effective `sub_org.delete` permission boundary as the delete control/route. The frontend requests it only when that control can be shown.

Extract one shared backend helper for the exact topic/proposal count predicates. Both this endpoint and `DELETE /api/orgs/{org_slug}/sub-orgs/{sub_slug}` must call it. Add a race test where impact initially reports zero, a scoped row is inserted, and DELETE returns the current 409.

### 13. Keep sub-org deletion conservative and make the copy honest

Current source counts every scoped proposal but its docstring says “non-archived,” while the frontend suggests that archiving is sufficient. Do not change deletion/data-retention semantics in this pass: **any** scoped proposal or topic continues to block deletion.

Correct the route documentation and UI copy. Do not tell users that archiving permits deletion. Suggested copy: `This sub-organization cannot be deleted while scoped topics or proposals remain.` Proposal reassignment/deletion is a separate product workflow, not part of Phase 104.

### 14. Add a bounded Polis reverse-proposal-link feed

Add a member-authenticated endpoint alongside canonical Polis routes:

`GET /api/orgs/{org_slug}/polises/{polis_id}/proposal-links`

Parameters: cursor and limit, default 25, maximum 100.

Response:

```json
{
  "items": [
    {"id": "...", "title": "...", "status": "voting", "created_at": "..."}
  ],
  "next_cursor": "opaque-or-null",
  "has_more": false
}
```

Validate that the Polis belongs to the requested organization and is visible to the caller using the existing Polis access rules. Apply proposal member/private-sub-org visibility before pagination. Sort by proposal `created_at DESC, id ASC` with a versioned opaque cursor.

Filter exact JSON array membership in the database before `limit`; do not load all proposals and scan them in Python. PostgreSQL may use an exact JSON/JSONB expression and SQLite tests may use JSON1 or another exact dialect-safe implementation. Tests must distinguish the target UUID from prefix/suffix/lookalike strings and multi-element arrays.

### 15. Migrate both Polis pages without changing their main lifecycle

`Polis.jsx` and `admin/PolisDetail.jsx` use the proposal-link feed. Preserve their current Polis detail, member/creator lookup, XID, archive/edit/export, sub-org, and read-only behavior.

The reverse-link panel:

- loads independently so a link-panel failure does not hide the Polis itself;
- shows compact linked proposal rows;
- adds one request per Load more;
- cancels stale work on org/Polis change;
- does not claim a total before all pages load.

While `has_more=true`, label the panel without an exact total or use an honest loaded count such as `Referenced from 25+ proposals`. After the final page, an exact loaded count is safe.

### 16. Bound and deprecate legacy full-array endpoints

After every internal frontend consumer is migrated, update:

- `GET /api/proposals`;
- `GET /api/orgs/{org_slug}/proposals`;
- `GET /api/orgs/{org_slug}/public/proposals`.

Keep their response body as `ProposalOut[]` for compatibility, but add:

- `limit`, default 25, minimum 1, maximum 50;
- `offset`, default 0, minimum 0;
- fetch `limit + 1`, return at most `limit`;
- stable existing ordering plus proposal ID tie-breaker;
- visibility/filtering before offset/limit;
- `Deprecation: true`;
- `X-Has-More: true|false`;
- `X-Next-Offset` when more rows exist;
- an RFC-compatible `Link` next relation if straightforward without leaking anything not already in the authorized URL;
- OpenAPI `deprecated=True`.

Do not add `COUNT(*)`. Do not return 206. Do not silently materialize all eligible rows and slice in Python. Existing status/topic/org filters remain supported.

### 17. The internal frontend must have zero legacy list calls

Add a source-contract test or equivalent audit that fails if production frontend code calls any of the three endpoints above as proposal lists. Explicitly exclude:

- `/proposal-feed` and `/proposal-management-feed`;
- proposal detail routes with an ID;
- create/update/bulk mutation routes;
- `/proposals/import-template`.

The goal is to make the legacy bound defensive compatibility, not an internal dependency that can quietly grow again.

### 18. Query and request budgets are load-bearing

Against the Phase 104 PostgreSQL fixture:

- management first page, limit 50: at most 10 SQL statements;
- management page with every filter: at most 12;
- sub-org deletion impact: at most 6;
- Polis proposal-link first page: at most 8;
- no query count grows linearly with returned rows through relationship serialization.

Frontend request budgets after existing org/sub-org context:

- Proposal Management initial render: at most three calls (management feed, topics, sub-org metadata);
- each Proposal Management Load more: exactly one;
- SubOrgProposals initial render: at most three (scoped management feed, topics, parent org settings);
- SubOrgSettings deletion section: one deletion-impact request plus its existing parent-settings request;
- either Polis detail page: one proposal-link request, with no raw proposal-list request;
- each reverse-link Load more: exactly one.

### 19. Reuse Phase 103 overload and cancellation behavior

All new GETs use the shared content-type-safe API client, bounded timeout, friendly 502/503/504 copy, and abort semantics. Do not add special retry loops or a second response parser. Mutations are never automatically retried.

The one observed initial login retry is a monitoring watch item. Phase 104 does not change login/auth code unless preflight produces a reproducible non-Phase-103 defect. Any such discovery is a scoped-up diagnostic reported to the lead before implementation.

### 20. Add an index or normalized link table only from evidence

Run `EXPLAIN (ANALYZE, BUFFERS)` on management default/filters/next-page and Polis reverse-link queries against 2,500 proposals.

Default expectation: existing proposal indexes plus bounded sorts remain adequate, and the Polis JSON scan is acceptable at this scale. If reverse-link membership is measurably pathological, the lead may choose the smallest evidence-backed fix:

- an exact PostgreSQL expression/GIN index compatible with the stored JSON; or
- a normalized proposal–Polis association table with a backfill and single canonical write path.

The normalized-table option is a material scope-up: it must preserve `linked_polis_ids` API compatibility, cover create/update/backfill/downgrade, and pass migration/PG smoke. Do not introduce dual sources of truth casually. Report the measurement and decision in closeout.

No speculative proposal indexes.

### 21. No production load or data mutation

Use disposable local PostgreSQL. Production checks are bounded reads plus normal navigation. Do not bulk-advance, reschedule, withdraw, archive, edit, link, or create Massachusetts proposals for QA. Do not create a paid Railway test service without separate Z approval.

## Scope clusters

### A — Preflight and baseline

1. Record `origin/master`, deployments, bundle, and current production health/readiness/monitor timing.
2. Record current 15-minute pool-timeout and sanitized 5xx components, specifically checking whether Z's one login retry produced a continuing pattern.
3. Measure raw Proposal Management response count and payload against a local 250-proposal fixture.
4. Record the five internal raw-list callers and current request counts as the before baseline.

No restart, environment change, or production mutation in preflight.

### B — Shared pagination and management backend

Implement Decisions 2–7. Prefer extracting Phase 103's neutral cursor/order helpers rather than importing private underscored functions across route domains. Preserve Phase 103 member/public/global feed tests unchanged.

Tests cover:

- every status including draft/withdrawn/unresolved/expired_unsigned;
- parent-only/exact-sub/all scopes;
- private and non-private sub-org access;
- literal title search;
- every eligible operation and its Phase 102 cosign rule;
- permission/action separation;
- cursor ties, nulls, malformed/stale cursors;
- no cross-org rows;
- query budgets.

### C — Proposal Management frontend

Implement Decisions 8–10. Preserve create/import, single advance/withdraw, legacy escalation resolution, four bulk operations, confirmation copy, deterministic 500-ID chunks, partial results, and retry safety.

Add focused tests for:

- initial and appended pages;
- filter/search cancellation and response races;
- select all loaded eligible;
- selection across two loaded pages;
- filter-change confirmation accept/cancel;
- bulk partial result plus outer network failure;
- mutation refresh without legacy endpoint call;
- responsive/keyboard labels.

### D — Sub-org bounded data

Implement Decisions 11–13 in `SubOrgProposals`, `SubOrgSettings`, and the sub-organization backend route/service.

The deletion-impact endpoint and DELETE route must share exact count code. Preserve deletion's authorization, audit, 204 behavior, and conservative data-integrity gate.

### E — Polis reverse links

Implement Decisions 14–15 in canonical Polis backend routes and both frontend pages. Do not touch the separate linked-Polis picker/list unless necessary for compilation; pagination of the Polis collection itself is not authorized by this proposal-list pass.

### F — Legacy endpoint bounding and audit

Implement Decisions 16–17 only after B–E callers are migrated. Update compatibility tests that intentionally read arrays to specify/inspect pagination where their fixture exceeds the default. Do not mechanically rewrite proposal detail/create tests that happen to include `/proposals` in the path.

### G — PostgreSQL plans and load proof

Reuse or adapt the deterministic Phase 103 fixture/tool rather than inventing a weaker dataset. Required dataset:

- 250 active/mixed-status proposals for request/load tests;
- 2,500 proposals for EXPLAIN;
- parent-wide, public sub-org, and private sub-org rows;
- tied/null ordering timestamps;
- cosign and ordinary proposals across every bulk eligibility class;
- at least two Polises with zero, one, 25, and more-than-25 exact proposal links;
- lookalike link IDs that would catch substring matching.

Required scenarios:

1. Traverse all management pages: every expected ID exactly once.
2. Traverse one sub-org: only its rows, exactly once.
3. Traverse a Polis with more than 25 links: exact linked set, no false match.
4. Verify each legacy endpoint never exceeds 50 and exposes correct next headers.
5. Twenty concurrent clients mixed across management feed, scoped sub-org feed, Polis links, deletion impact, health, and readiness.
6. Five repeated filter/load-more cycles to detect pool/session leaks.

Acceptance:

- zero unexpected 5xx and zero pool-timeout 503s;
- management-feed p95 at or below 1.0 second and p99 at or below 3.0 seconds;
- `/api/health` p95 at or below 250 ms during load;
- management first-page payload below 150 KB uncompressed;
- SQL/request budgets pass;
- pool returns to baseline within five seconds;
- zero waiting locks and zero idle-in-transaction sessions older than five seconds;
- EXPLAIN results justify either no migration or the exact chosen index/link normalization.

If the health p95 misses once, follow the Phase 103 rule: diagnose, rerun once, and report both results rather than waiving or hiding the first run.

### T — Full regression, docs, and closeout

Run:

- focused Phase 104 backend/frontend tests;
- affected Phase 100/102 bulk, sub-org, Polis, visibility, and Phase 103 feed/overload suites;
- full backend suite;
- full frontend tests;
- changed-file ESLint;
- production build;
- Python compile;
- diff check;
- migration cycle and PG smoke only if a migration is added.

Update:

- `PROGRESS.md` with Phase 104 results;
- `docs/scalability_audit_2026-05.md` with remaining raw-list closure and measurements;
- comments that still describe full parent-array filtering/counting;
- follow-up roadmap only for concrete newly discovered work.

## Browser verification scenarios

After backend and frontend deployments both match the merge:

1. Sign in and open Proposal Management for `ma-legislature`. The first bounded page loads without a raw-array request or long freeze.
2. Exercise status, scope, title search, and eligible-operation filters; clear them and Load more twice.
3. Select eligible proposals across two loaded pages, verify the loaded-only label/count, change a filter and test both Cancel and Confirm-clear paths. Do not submit a production mutation.
4. Open a sub-org proposal admin page and verify only that sub-org's rows plus Load more behavior.
5. Open sub-org settings with delete permission and verify deletion-impact counts render without downloading proposal/topic arrays. Do not delete the sub-org.
6. Open a Polis voter page and admin detail page with linked proposals. Verify the reverse-link panel and proposal navigation; do not create/archive/link anything.
7. Inspect the browser network panel: zero calls to the three legacy raw proposal lists from these pages.
8. At approximately 380px, verify filters, management rows, selection controls, Load more, and reverse links do not overflow.
9. Keyboard-only: filters/search, selection, Load more, row expansion, linked proposal navigation.
10. If feasible in local/mock QA, return an HTML 504 from one new GET and confirm the existing Phase 103 friendly message; do not manufacture a production outage.

The Chrome MCP is mandatory per `AGENTS.md`. If its trusted-code-path startup failure persists, report the exact blocker and do not substitute another browser or claim rendered QA. Z's manual Phase 103 smoke may be noted separately but does not replace this gate.

## Operational watch-outs

- **Drafts sort after active/terminal proposals.** Without `eligible_for`/status filters, a large active cohort can bury drafts needed for bulk administration.
- **Selection plus pagination is stateful.** Do not derive selected-row metadata solely from the current page.
- **“Select all” wording is dangerous.** This pass selects loaded eligible rows only; database-wide selection is explicitly absent.
- **Mutation eligibility can change after listing.** Every action endpoint must re-read and revalidate.
- **Sub-org counts and DELETE currently have copy drift.** Reuse one predicate; do not fix the UI alone.
- **JSON reverse membership must be exact.** String `LIKE`/substring matching is not acceptable for UUID arrays.
- **Legacy array pagination is offset-based only for compatibility.** New feature work must use typed keyset envelopes.
- **Full `ProposalOut` rows can be large.** A 50-row maximum is a ceiling, not a recommended internal page shape.
- **Do not regress Phase 103 feeds.** Shared cursor extraction must preserve their version-1 behavior.
- **A transient friendly login retry is not enough evidence for auth redesign.** Escalate only if preflight or tests reproduce a separate fault.
- **Pool peak 5/5 is expected under the load fixture only because it drains cleanly.** Do not raise the pool to make measurements look better.

## Explicitly out of scope

- Restoring list-card aggregate bars or computing tallies in any list/feed.
- Persisted/versioned tally cache.
- Pagination of topics, members, Polises themselves, audit logs, or other non-proposal collections.
- Database-wide select-all or operations over an implicit search result.
- Proposal reassignment/deletion workflow for emptying a sub-org.
- Changing sub-org deletion to cascade or ignore archived proposals.
- Changing proposal bodies, ballots, schedules, statuses, links, or visibility in production QA.
- Auth/login redesign based solely on one successful-retry observation.
- Redis or another paid service.
- Uvicorn worker/connection-pool increases.
- Multiple Railway replicas or scheduler extraction.
- Production PostgreSQL timeout/config changes.
- Synthetic load against production.
- A paid Railway test service without separate approval.

## Expected follow-ups, not authorized here

1. **Phase 105 candidate — Versioned tally summaries.** Optional product restoration of aggregate list-card results from invalidated/precomputed data.
2. **Collection-pagination audit.** Topics, member rosters, and Polis collection pickers may eventually need their own bounded contracts; Phase 104 records but does not expand into them.
3. **Sub-org content relocation workflow.** Needed if admins should be able to empty/delete a sub-org that has historical proposals.
4. **Replica readiness.** Scheduler ownership/extraction before raising workers or Railway replicas.
5. **Chrome tooling repair.** External to application phases unless Z explicitly dispatches it.

All are **NOT STARTED**.

## Expected file set

Exact names may vary; closeout explains deviations.

- `phase104_admin_and_secondary_proposal_pagination_spec.md`
- `backend/proposal_feed.py` or an extracted neutral pagination helper
- `backend/schemas.py`
- `backend/routes/organizations.py`
- `backend/routes/proposals.py`
- `backend/routes/sub_organizations.py`
- canonical Polis route module
- Phase 104 management/count/Polis/legacy/load tests
- optional migration only if G-cluster evidence requires it
- `frontend/src/pages/admin/ProposalManagement.jsx`
- `frontend/src/pages/admin/SubOrgProposals.jsx`
- `frontend/src/pages/admin/SubOrgSettings.jsx`
- `frontend/src/pages/Polis.jsx`
- `frontend/src/pages/admin/PolisDetail.jsx`
- `frontend/src/utils/bulkDeliberation.js`
- focused frontend pagination/selection tests
- Phase 104 PostgreSQL load/EXPLAIN script or a documented extension of the Phase 103 tool
- `docs/scalability_audit_2026-05.md`
- `PROGRESS.md`

## Closeout report shape

In addition to the standard `AGENTS.md` closeout, report:

- A/B/C/D/E/F/G/T workstream status: DONE / blocked / scoped-up.
- Production preflight and whether Z's one login retry corresponded to any continuing sanitized 5xx/pool-timeout pattern; no private auth data.
- Before/after request count and payload for Proposal Management at 250 proposals.
- Management/sub-org/Polis traversal totals with zero missing/duplicate/unexpected IDs.
- SQL counts for management default/filters, deletion impact, and Polis links.
- p50/p95/p99, maximum payload, pool baseline/peak/recovery, pool timeouts, locks, and idle transactions from mixed load.
- Exact filter/search/selection semantics, including selected rows across pages, partial/network retry behavior, and the Phase 102 `set_end` cosign-eligibility parity correction.
- Sub-org deletion count/DELETE predicate reuse and corrected copy.
- Exact JSON membership strategy and lookalike-ID test result.
- Legacy endpoint maximum, stable paging, headers, OpenAPI deprecation, and proof of zero internal frontend callers.
- EXPLAIN plans and whether a migration/index/normalized link table was justified.
- If migration added: revision, reversible cycle, PG smoke, and backfill output.
- Backend test delta from 3,131/20; frontend test delta from 62; lint/build/compile/diff results.
- Files added/modified, commit SHAs, no-ff merge, GitHub Actions run.
- Railway backend/frontend deployment IDs, bundle hash, health/readiness/monitor, bounded production route smoke.
- Rendered QA per scenario or exact Chrome trusted-path blocker.
- Confirmation that no production mutation/load, pool/env change, or new paid service occurred.
- New debt and recommended next phase, explicitly marking unstarted work.

## Go

Read the entire spec, create the clean worktree/branch, and execute Phase 104 through verified production deployment. No additional approval is needed for the code, tests, normal merge/push/deploy, or bounded read-only production checks described here. Pause for destructive production-data action, paid/new infrastructure, Railway environment-variable changes, a normalized-link-table scope-up not justified by the locked evidence gate, or another material decision this spec does not resolve.
