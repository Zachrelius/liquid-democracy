# Phase 100 — Bill Readability and Bulk Deliberation

**Status:** APPROVED FOR IMPLEMENTATION by Z on August 22, 2026. Phase 100 may be implemented in the same Code-team run as Phase 99, but it remains a separate branch/merge unit and must preserve Phase 99's preview and public-copy boundaries.

## Goal

Make imported legislative proposals readable enough to engage with and practical to administer at Massachusetts-bill scale.

The pass has three user-visible outcomes:

1. safe Markdown links in proposal bodies render as real clickable links;
2. an imported proposal's summary and sources stay immediately visible while its full legal text is collapsed by default behind an accessible disclosure; and
3. an authorized organization steward can select many draft proposals in Proposal Management and advance them to deliberation with one reviewed action.

This is called a frontend pass because the principal benefit is workflow and presentation, but the bulk lifecycle action requires a small backend endpoint and a shared transition helper. The browser must not issue one request per proposal or reimplement lifecycle rules client-side.

## Branch and delivery

- Branch: `phase-100/bill-readability-bulk-deliberation`
- Merge: no-fast-forward to `master`.
- One-line dispatch: `Read and execute phase100_bill_readability_and_bulk_deliberation_spec.md.`
- If Phase 99 is still in flight, implement and commit Phase 100 separately. Rebase or merge the current Phase 99 result before final Phase 100 verification; do not copy, revert, or silently overwrite either pass's work.
- Push `master`, wait for Railway, confirm frontend and backend deployments match the merge, then run production QA.
- Expected recurring-cost delta: $0.

## Phase 99 coexistence contract

Phase 99 owns `/pilot`, `Pilot.jsx`, Privacy, Terms, Security & Trust, About, `PublicLayout`, reserved-slug behavior, and the approved pilot-copy documents. Phase 100 must not edit:

- `phase99_pilot_conversion_and_public_trust_spec.md`;
- `docs/pilot_outreach_materials_draft_2026-08.md`;
- `docs/pilot_public_copy_review_2026-08.md`;
- Phase 99's public-page copy or `/pilot` discoverability/metadata decisions; or
- `backend/reserved_slugs.py` unless resolving a genuine merge conflict without changing Phase 99 semantics.

Phase 100's intended product-code ownership is `frontend/src/utils/renderMarkdown.js`, a small proposal-body presentation component/helper, `frontend/src/pages/ProposalDetail.jsx`, `frontend/src/pages/admin/ProposalManagement.jsx`, the org-scoped proposal route/schema/service seams, and Phase-100-focused tests. Shared routing or documentation conflicts must be resolved additively, with both specs' tests rerun.

## Verification matrix

| Check | Required | Notes |
|---|---:|---|
| Safe-link renderer tests | Yes | Valid `http://` and `https://` Markdown links render; hostile, malformed, relative, and unsupported schemes never become active anchors; labels remain escaped |
| Proposal-body disclosure tests | Yes | Exact `## Full legal text` section defaults closed; preceding summary/sources remain visible; toggle is keyboard-operable and exposes correct accessible state; bodies without the marker retain existing rendering |
| Bulk endpoint tests | Yes | Permission, organization scope, draft-only behavior, deduplication, batch limit, partial results, idempotent retries, audit side effects, timestamps, and rollback containment |
| Existing lifecycle regression tests | Yes | Both existing single-advance routes continue to behave identically after helper extraction |
| Proposal-management tests | Yes | Draft-only checkboxes, select-visible-drafts behavior, confirmation, bounded chunking, busy state, aggregate result copy, selection cleanup, and no accidental deliberation→voting action |
| Frontend unit/source-contract suite | Yes | `cd frontend && npm test` |
| Frontend lint | Yes | `cd frontend && npm run lint`; no new errors and no unexplained warnings |
| Frontend production build | Yes | `cd frontend && npm run build` |
| Focused backend suite | Yes | New Phase 100 tests plus proposal lifecycle, notification-emission, permission, and author-advance regressions |
| Full backend suite | Yes | No unexplained regressions |
| Migration cycle / PG smoke | No | No schema migration in this pass |
| Browser QA | Yes | Production member proposal detail and authorized/unauthorized Proposal Management on desktop and approximately 380px mobile |
| Scale smoke | Yes | At least 501 draft fixtures selected so the one user action exercises multiple bounded API chunks; no per-proposal browser request pattern |
| Production delivery | Yes | New frontend bundle live, backend deployment matches merge, backend smoke succeeds, monitor remains healthy |

## Suggested team structure

- **Lead:** integration with the concurrent Phase 99 pass, lifecycle-helper review, gates, deployment, and closeout.
- **Backend developer:** shared draft-to-deliberation service, bulk endpoint/schema, and side-effect tests.
- **Frontend developer:** safe links, legal-text disclosure, bulk-selection workflow, responsive/accessibility work, and frontend tests.
- **QA teammate:** independent production checks for link safety, collapsed legal text, permissions, and small/large bulk actions.

## Locked decisions

1. **Imported-section contract.** The collapse boundary is an exact Markdown heading line, `## Full legal text`, allowing surrounding whitespace but not fuzzy prose matching. The bill pipeline already emits this marker. Text before it—including `## Plain-language summary` and `## Official sources`—renders normally. The full-text heading and everything after it live inside the disclosure.
2. **Default state.** Full legal text is collapsed on initial render. The control reads `Show full legal text` / `Hide full legal text`, has `aria-expanded` and `aria-controls`, and preserves a logical heading order. This is a presentation change only; the complete body remains in the proposal and DOM only when expanded.
3. **Backwards compatibility.** A proposal body without the exact marker renders in full exactly as before. Phase 100 does not heuristically collapse long ordinary proposals, comments, delegate profiles, topic guidance, or rationales.
4. **Links.** Extend the existing escape-first renderer to support inline Markdown links `[label](URL)`. Only absolute `http://` and `https://` destinations may become anchors. Rendered anchors open in a new tab with `target="_blank"` and `rel="noopener noreferrer"`, have a visible focus style through the surrounding prose styles, and preserve their escaped label. Do not enable raw HTML, images, autolinking, relative URLs, `javascript:`, `data:`, or other schemes.
5. **Shared renderer impact is intentional.** Safe Markdown link syntax becomes available anywhere the shared `renderMarkdown` utility is already used. The full-legal-text collapse is proposal-body-specific and must not be built into that shared renderer.
6. **Selection rather than indiscriminate all.** Proposal Management gains a checkbox on every eligible draft row and a header checkbox labeled for assistive technology. The header selects all currently visible eligible drafts. Phase 100 does not add a dangerous database-wide `Advance all` action detached from what the steward can see and review.
7. **Draft-only operation.** The new bulk action can perform only `draft → deliberation`. Deliberation, voting, unresolved, passed, failed, archived, or otherwise ineligible proposals are neither selectable nor advanceable through this endpoint. It can never apply the generic “next status” transition.
8. **One user action, bounded requests.** `Advance selected to deliberation` is one confirmed user action. The frontend submits proposal IDs to a purpose-built org-scoped bulk endpoint in chunks of at most 500 and aggregates the results. Thus 1,000 selections make two bulk calls, not 1,000 lifecycle calls. Disable selection and action controls while the operation is running.
9. **Review before mutation.** Confirmation states the organization, exact selected count, that only current drafts will move, and that deliberation timing starts immediately. It shows up to five titles plus an `and N more` count. The confirm button is not styled as destructive, but cancellation remains the default safe path.
10. **Partial and retry-safe results.** Each submitted ID returns `advanced`, `already_in_deliberation`, `ineligible_status`, or `not_found`. Duplicate IDs are processed once. A retry must not move an already-advanced proposal into voting. The endpoint returns aggregate counts plus per-ID results; eligible records commit independently so one stale or invalid ID does not discard unrelated successes.
11. **Permissions and scope.** The endpoint is organization-scoped and requires `proposal.advance_phase`; author-only and moderator-own-proposal exceptions from the general single-advance route do not grant mass-action power. Cross-org and nonexistent IDs both return per-item `not_found`, avoiding information disclosure.
12. **Single lifecycle implementation.** Extract a shared draft-to-deliberation transition helper/service and call it from the existing single-advance paths and the bulk path. It owns `deliberation_start`, `status`, `updated_at` behavior if currently automatic, and the existing `proposal.status_changed` audit event. Do not copy a third version of the transition code.
13. **No notification storm invention.** Preserve whatever notification behavior the existing single `draft → deliberation` transition currently has. If it emits none, bulk advance emits none. If it emits notifications, the shared helper must retain the same semantics and use the existing failure-containment pattern; Phase 100 does not introduce a new bulk-specific member notification.
14. **Post-action UX.** Refresh proposals after all chunks settle, clear successful and no-longer-eligible selections, retain failed eligible selections for retry where meaningful, and show a concise aggregate toast such as `487 advanced; 8 were already in deliberation; 5 could not be advanced.` Do not emit hundreds of toasts.
15. **No migration.** This is renderer, component, route/service, and schema work only.

## What this pass is

- A safe readability layer for the deterministic legislative-body format already generated by the Massachusetts pipeline.
- A scalable steward workflow for moving reviewed imported drafts into deliberation.
- A consolidation of the draft-to-deliberation transition so single and bulk paths cannot silently drift.

## What this pass is not

- No AI summarization or AI provider integration. The separate content pipeline supplies any plain-language summary.
- No editing, regeneration, or backfill of existing proposal bodies.
- No replacement of the deliberately small Markdown renderer with a full Markdown library unless implementation proves the safe link grammar cannot be added clearly and tests demonstrate the replacement preserves every current behavior. A library substitution is a scoped-up decision that must be called out in closeout.
- No rich HTML, image, attachment-preview, PDF viewer, table-of-contents, sticky navigation, or side-by-side statutory diff.
- No automatic advancement immediately after CSV/JSON import.
- No bulk advancement beyond deliberation, bulk withdrawal, bulk archive, or bulk deletion.
- No new search, pagination, virtualized list, or server-side “select every matching proposal” capability. If the current unpaginated management list becomes a measured bottleneck at thousands of rows, record it as follow-up rather than expanding this pass.
- No change to the one-day minimum deliberation setting or organization duration defaults.
- No change to Phase 99 public copy, pilot promotion, or inquiry intake.

## Implementation sequence

1. Land Cluster B's shared helper, endpoint schema, and focused tests.
2. Land Cluster F1 safe-link rendering and proposal-body disclosure with focused tests.
3. Land Cluster F2 selection and bulk action against the endpoint.
4. Run focused and full gates against the integrated Phase 99 + Phase 100 tree.
5. Merge Phase 100 separately with `--no-ff`, deploy, and run Cluster Q production verification.

## Cluster B — Draft-to-deliberation bulk backend

### B1 — Centralize the transition

Extract the smallest shared operation needed for `draft → deliberation`; do not attempt a risky refactor of voting close, elections, issuance, tie resolution, or all generic status transitions.

The helper accepts the database session, proposal, actor, and request IP/audit context. It must:

- verify the proposal is currently `draft`;
- set one captured UTC timestamp as `deliberation_start`;
- set `status = "deliberation"`;
- create the existing `proposal.status_changed` audit event with `old_status=draft` and `new_status=deliberation`; and
- leave commit ownership to its caller so both existing routes and the bulk endpoint can choose the correct transaction boundary.

Replace only the draft branch of both existing advance routes with this helper. Their permission gates, response shapes, and behavior on every other status remain unchanged.

### B2 — Bulk request and response

Add an org-scoped route following the repository's existing naming style, recommended:

`POST /api/orgs/{org_slug}/proposals/bulk-advance-to-deliberation`

Request:

```json
{"proposal_ids": ["uuid", "uuid"]}
```

Validation:

- one to 500 IDs per request;
- valid UUID strings;
- stable first-occurrence order with duplicates removed before processing; and
- caller must have `proposal.advance_phase` in this organization, including platform-admin behavior only if the existing org middleware deliberately grants it.

Response:

```json
{
  "requested": 3,
  "processed": 3,
  "advanced": 1,
  "already_in_deliberation": 1,
  "ineligible_status": 0,
  "not_found": 1,
  "results": [
    {"proposal_id": "...", "result": "advanced", "status": "deliberation"},
    {"proposal_id": "...", "result": "already_in_deliberation", "status": "deliberation"},
    {"proposal_id": "...", "result": "not_found", "status": null}
  ]
}
```

Use Pydantic response models rather than an untyped dictionary. For each proposal, use a savepoint/nested transaction or an equivalently tested containment pattern: an unexpected per-item failure is rolled back for that item, reported without leaking internals, and does not roll back already successful items. Known stale-state outcomes use the named result values and are not HTTP errors. Request/schema/auth failures remain ordinary 4xx responses.

### B3 — Backend tests

Create `backend/tests/test_phase_100_bulk_deliberation.py` and extend existing lifecycle coverage where helper extraction changes a route.

Required assertions:

- an authorized steward advances 1, many, and 500 drafts;
- empty and 501-ID payloads reject before mutation;
- duplicate IDs mutate and audit once;
- member, author-without-key, and moderator-without-key cannot bulk advance;
- cross-org and nonexistent IDs are indistinguishable `not_found` results;
- drafts get `deliberation_start` and exactly one correct audit row;
- already-deliberation is idempotently skipped and never reaches voting;
- voting/terminal states return `ineligible_status` and do not change;
- mixed batches return stable per-ID and aggregate results;
- an injected per-item failure cannot undo successful siblings;
- both pre-existing single routes still advance drafts with the same timestamp/audit behavior; and
- no bulk-specific notification is added, while any existing shared emission behavior remains intact.

## Cluster F1 — Readable legislative bodies

### F1.1 — Safe Markdown links

Extend `frontend/src/utils/renderMarkdown.js` without weakening the escape-first boundary. Parse and validate a link destination before emitting an anchor. Because regex replacement order can accidentally let emphasis/code substitutions corrupt a link or permit an encoded unsafe scheme, put URL validation in a named helper and test the composed renderer, not only the helper.

Required cases include:

- `[Bill page](https://malegislature.gov/Bills/194/S3029)`;
- `[Official PDF](https://malegislature.gov/Bills/194/S3029.pdf)`;
- `http://` support;
- labels containing escapable characters;
- `javascript:`, `data:`, relative paths, protocol-relative URLs, malformed brackets/parentheses, and quote/attribute-breakout attempts; and
- current headings, emphasis, inline code, lists, and paragraph rendering unchanged.

Update the renderer comment, which currently promises “no link auto-detection,” to distinguish supported explicit Markdown links from still-unsupported autolinking.

### F1.2 — Proposal-only legal-text disclosure

Add a focused component/helper, recommended `frontend/src/components/ProposalBody.jsx`, that:

1. splits only on the first line matching the exact `## Full legal text` heading;
2. renders the preamble through the shared renderer immediately;
3. renders an accessible disclosure button even when the legal-text section contains only the pipeline's overflow/missing-text notice;
4. renders the heading and remainder through the same shared renderer when expanded; and
5. falls back to the current full-body rendering when no marker exists.

Replace ProposalDetail's direct body `dangerouslySetInnerHTML` call with this component. Preserve its current typography/prose classes and ensure sections/paragraphs have visibly distinct spacing. Do not use native `<details>` if existing button styles and test infrastructure make explicit `aria-expanded` state clearer; either implementation is acceptable only if keyboard and screen-reader behavior is correct.

## Cluster F2 — Bulk selection in Proposal Management

1. Add selection state keyed by proposal ID.
2. Render checkboxes only for `status === "draft"` and only when `canAdvancePhase` is true. Other rows keep their alignment and status/actions.
3. The header checkbox selects/deselects all currently visible draft rows and correctly represents checked/unchecked/indeterminate state. With no client filters today, “visible” means the currently rendered proposal list; do not claim database-wide selection.
4. Add a sticky or clearly visible action bar above the table when at least one draft is selected: selection count, `Clear selection`, and `Advance selected to deliberation`.
5. Open the review dialog from Locked Decision 9. On confirmation, freeze the ID snapshot, sort/chunk deterministically at 500, send bulk calls sequentially or with very low bounded concurrency, and aggregate results.
6. Keep the existing expanded-row actions. The existing single-item `Advance to Deliberation` remains useful and is not replaced by the bulk route.
7. Clicking a checkbox must not expand/collapse its row; stop event propagation. Give each checkbox a title-specific accessible label.
8. A refresh or organization switch must not carry selections into another organization. Reconcile selection when the loaded proposal set changes.
9. If one chunk fails at the request level, stop subsequent chunks, refresh current state, retain still-eligible unprocessed selections, and show one actionable error/partial-completion message.
10. At approximately 380px width, the action bar and row controls wrap without horizontal scrolling or tiny click targets.

## Cluster T — Tests and source review

- Add focused Node tests for the renderer and any pure proposal-body split helper. The current frontend harness is `node --test`; do not introduce a new test framework solely for this pass.
- Add stable source-contract tests for Proposal Management semantics that the current no-DOM harness cannot exercise, then rely on browser QA for real interaction. Do not claim a source assertion is a browser test.
- Run `git diff --check`, frontend tests/lint/build, the focused backend sets, and the full backend suite.
- Source-review every existing `renderMarkdown` call site because explicit link support is shared. Confirm no call site wraps output in an anchor or otherwise creates invalid nested links.
- No migration means no migration cycle or PostgreSQL smoke is required; state that explicitly in closeout.

## Cluster Q — Production verification

After merge, push, and deploy:

1. Confirm the frontend bundle changed, the backend deployment corresponds to the Phase 100 merge, a known backend smoke endpoint succeeds, and the production monitor is healthy.
2. Open a Massachusetts proposal containing `## Plain-language summary`, Markdown source links, and `## Full legal text`.
3. Confirm summary and source links are visible without expansion; links navigate to the correct General Court HTTPS destination in a new tab and expose `noopener noreferrer`.
4. Confirm the legal text defaults closed, expands/collapses by mouse and keyboard, has correct announced state, preserves section paragraph spacing, and works around 380px width.
5. Confirm an ordinary body with no marker remains fully visible. Spot-check a comment or delegate-profile Markdown surface for renderer regressions.
6. As an authorized steward, select two safe test drafts, cancel once, then confirm once. Verify both enter deliberation, start timestamps exist, and a refresh does not advance them again.
7. Verify a deliberation proposal cannot be selected for the bulk action and is not moved to voting by a stale/retried request.
8. Verify a user without `proposal.advance_phase` sees no bulk controls and receives 403 from a direct endpoint call.
9. Run the 501-fixture scale smoke in a local/staging database, not by creating hundreds of disposable production proposals. Confirm two bounded calls and one aggregate user result.
10. Regression-check Phase 99's `/pilot`, preview isolation, and public trust pages if Phase 99 shipped in the same deploy.

## Operational watch-outs

- The current code has two largely duplicated single-advance implementations. Phase 100 intentionally extracts only the simple draft branch; broad lifecycle unification would create unnecessary election/tie/issuance risk.
- `renderMarkdown` is shared and feeds `dangerouslySetInnerHTML`. Escape first, validate schemes, and test attribute-breakout payloads. Never interpolate an unvalidated destination.
- Do not wrap the whole body in a single `<p>` once it contains headings, lists, or nested paragraphs. Keep valid-enough block structure and visible vertical rhythm.
- Bulk processing must not call `db.commit()` inside the shared transition helper. Caller-owned transaction boundaries are necessary for single-route compatibility and per-item containment.
- The management endpoint currently returns an unpaginated list. Phase 100 makes its action scale reasonably but does not claim the list itself is ready for an unbounded corpus. Measure before adding pagination/virtualization.
- Imported proposals may already exist in production with plain source syntax. Explicit Markdown links become active without a data backfill; the collapse requires the exact marker already present in the revised pipeline bodies.

## Followups deliberately left unstarted

- AI-generated plain-language bill summaries and their editorial/audit workflow.
- A server-side filtered “select all matching drafts” operation for corpora too large to render in one management list.
- Proposal-list pagination or virtualization if measured Massachusetts scale makes the current list slow.
- Full Markdown-library adoption if future content needs tables, footnotes, or richer legislative structure.
- Automatic synchronization when an official bill receives a new draft or substitute.

## Closeout contract

Report:

- per-cluster DONE / blocked / deferred;
- exact Phase 99 integration/merge order and confirmation that its preview/public-copy boundaries survived;
- backend test count delta and focused lifecycle/side-effect results;
- frontend test/lint/build results and bundle-size delta;
- no migration / PG smoke not required;
- renderer security cases and source-review result across all shared call sites;
- 501-fixture chunking result;
- production desktop/mobile/keyboard QA for link, disclosure, selection, confirmation, permission, retry, and stale-status behavior;
- files changed and commit SHAs;
- no-ff merge/push, Railway deployment rows, frontend bundle hash, backend smoke, and production-monitor result;
- any measured list-performance issue or newly found tech debt; and
- confirmation that AI summarization, pagination/virtualization, database-wide select-all, and all advancement beyond draft→deliberation remain **NOT STARTED**.
