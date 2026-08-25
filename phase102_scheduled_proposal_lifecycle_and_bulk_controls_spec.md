# Phase 102 — Scheduled Proposal Lifecycle and Bulk Controls

**Status:** DRAFT FOR Z REVIEW / IMPLEMENTATION NOT STARTED. Written August 24, 2026 after production diagnosis confirmed that ordinary proposals have stored deliberation durations but no worker path that advances them when those durations expire. Z approved moving the current overdue Reform Table backlog into voting and requested broader bulk scheduling controls.

## Goal

Make proposal dates operational promises rather than advisory values, and make large proposal sets practical to administer safely.

This pass has seven user-visible and operational outcomes:

1. an ordinary proposal automatically moves from deliberation to voting when its scheduled deliberation end arrives;
2. proposal pages clearly show when voting is scheduled to begin and end;
3. authorized administrators can move selected deliberation proposals into voting now;
4. authorized administrators can set a shared voting-start date or voting-end date across selected proposals;
5. the 75 currently overdue ordinary proposals in `reform-table` move into voting through a controlled one-time production reconciliation;
6. production monitoring detects proposals that remain in deliberation after an automatic transition should have occurred; and
7. budget-allocation and budget-project proposals honor their `voting_end` automatically instead of remaining open until someone closes them manually.

The root cause is missing functionality, not a stopped worker. Phase 24 added automatic `voting -> passed/failed` close behavior, and Phase 46a added a specialized cosign-window decision, but no general worker ever implemented `deliberation -> voting` from `deliberation_start + deliberation_days`.

## Branch and delivery

- Branch: `phase-102/scheduled-proposal-lifecycle`
- Merge: no-fast-forward to `master`.
- One-line dispatch after approval: `Read and execute phase102_scheduled_proposal_lifecycle_and_bulk_controls_spec.md.`
- Expected recurring-cost delta: $0.
- Migration prior revision: `d6e7f8a9b0c1` (Phase 101).
- Railway deployment includes a temporary, cost-free lifecycle feature gate described in Cluster W4. The gate must be set to disabled before the code reaches production, then enabled only after the production inventory and reconciliation complete.
- Push `master`, verify both Railway services, perform the controlled production reconciliation, enable automation, and run production QA per `AGENTS.md`.

## Verified starting state

Read-only production inspection on August 24, 2026 found:

- The Reform Table has 77 public proposals: 75 `deliberation`, 1 `voting`, and 1 `withdrawn`.
- All 75 deliberation proposals have a stored `deliberation_start` and `deliberation_days = 14.0`.
- Their derived deadlines range from June 29 through July 3, 2026; all are overdue.
- None of the 75 is cosign-gated.
- All 77 store `voting_days = 500.0`; Phase 102 must preserve that value. A proposal entering voting during the production reconciliation will therefore receive `voting_end = actual_voting_start + 500 days` unless it has an explicit valid `voting_end_date`.
- The decision worker and its heartbeat are healthy. Its general voting query handles voting-phase evaluation/close; its deliberation query only captures optional pre-voting snapshots. The only timed deliberation transition is the separate cosign-gated path.
- Budget proposal methods are excluded from the current worker's voting query because they do not support Stable Result Required or its snapshot shape. There is no separate timed-close query for them. Manual close supports budget tallies, but automatic `voting_end` close currently does not. Phase 102 must close this adjacent gap so the new `Set voting end` control is truthful for every supported method.
- `ProposalOut` already exposes `deliberation_start`, `deliberation_days`, `voting_start`, `voting_end`, and `voting_end_date`, but not a durable `deliberation_end`.
- Proposal Detail derives the end internally for edit-lockout calculation, yet displays `Voting has not yet been scheduled` while `voting_start` is null.
- The ordinary proposal PATCH route allows duration edits only before the deliberation edit-lockout. There is no schedule-only control that remains available to authorized administrators after content editing locks.

The implementation team must refresh the production inventory immediately before reconciliation. The counts above are the expected baseline, not permission to hardcode IDs or assume nothing changed after August 24.

## What “overdue” means

Phase 102 does **not** add an `overdue` proposal status and does not hold the Reform Table proposals in a new state.

`Overdue` is a derived operational/UI condition only:

```text
status == deliberation
AND deliberation_end is not null
AND deliberation_end < now
```

Normally that condition should exist only during the worker's next five-minute interval. If it persists beyond the monitoring grace period, the proposal page shows that the transition is delayed and the production monitor reports an actionable issue. Since Z approved advancing the current Reform Table backlog, those rows will move directly from `deliberation` to `voting`; they will not remain marked overdue.

Legacy active deliberation rows whose schedule has deliberately not yet been initialized have `deliberation_end = null` and are called **unscheduled**, not overdue. That distinction prevents the new worker from silently changing unrelated historical organization data during rollout.

## Verification matrix

| Check | Required | Notes |
|---|---:|---|
| Migration cycle | Yes | Add nullable indexed `Proposal.deliberation_end`; reversible upgrade -> downgrade -> upgrade from `d6e7f8a9b0c1` |
| Schema round-trip | Yes | Transition, API serializer, public/member lists, individual detail, import/seed paths, and zero-day creation |
| Lifecycle service | Yes | Manual single advance, bulk advance, cosign advance, scheduled worker advance, voting deadline calculation, election option locking, audit, and notification behavior use one deliberation-to-voting implementation |
| Worker timing and concurrency | Yes | Not early; due at boundary; bounded batches; idempotent retries; row/status recheck; duplicate/multi-instance safety; one audit and one notification set |
| Special proposal types | Yes | Ordinary binary/approval/RCV/budget/election/issuance behavior; cosign proposals remain on their specialized gate |
| Budget timed close | Yes | Allocation/project proposals remain excluded from SRR snapshots but close through a separate due-deadline path with quorum-only outcome semantics |
| Schedule mutation endpoints | Yes | Permission, org scope, per-status eligibility, date validation, atomic per-item results, audit details, and shortening-active-vote reason |
| Bulk management UI | Yes | Operation-first selection, select-visible-eligible, confirmation, schedule forms, mixed-state prevention, partial results, keyboard/mobile behavior |
| Schedule display | Yes | Future, overdue/delayed, unscheduled legacy, voting, closed, and timezone rendering on public and member surfaces |
| Existing lifecycle regressions | Yes | Phase 24 close, Phase 25 duration consumption, Phase 46a cosign gate, Phase 49 elections, Phase 70 author advance, Phase 75a absolute end, Phase 90e issuance, and Phase 100 bulk deliberation |
| Monitoring | Yes | Overdue grace count degrades/fails monitor appropriately without leaking titles or organization data publicly |
| Backend full suite | Yes | Expected baseline is Phase 101's 3,065 passed / 20 skipped |
| Frontend full suite | Yes | `npm test`, changed-file lint, and production build |
| PostgreSQL smoke | Yes | `pg_smoke.py --mode both --prior-revision d6e7f8a9b0c1` |
| Production reconciliation | Yes | Fresh dry run, scoped `reform-table` apply, 75 expected transitions or exact explained delta, no mutation of the existing voting/withdrawn rows, verification of all timestamps/audits |
| Production delivery | Yes | Feature gate on only after reconciliation, backend/readiness/monitor healthy, new bundle live, one disposable timed-transition proof |

## Suggested team structure

- **Lead:** lifecycle design integration, migration review, feature-gated rollout, production inventory/reconciliation, full gates, deployment, and closeout.
- **Backend developer:** lifecycle service, model/migration, worker, typed bulk/schedule endpoints, monitoring, reconciliation script, and backend tests.
- **Frontend developer:** schedule display, operation-first bulk controls, date modals, result summaries, responsive/accessibility behavior, and frontend tests.
- **QA teammate:** independent timed-transition, permissions, bulk action, schedule display, public/member, desktop/mobile, and post-deploy verification. The Reform Table reconciliation itself remains the lead's controlled production operation, not a QA experiment.

## Locked decisions

1. **Scheduled transition is the default contract.** Once an ordinary proposal enters deliberation with a non-null `deliberation_end`, the decision worker advances it automatically at or shortly after that timestamp. Administrators no longer need to press a button for normal passage of time.
2. **Use a durable indexed deadline.** Add nullable `Proposal.deliberation_end: DateTime`. Do not make the worker scan thousands of rows and calculate every deadline in Python every five minutes. `deliberation_end` is the authoritative scheduled voting-start time after deliberation begins; `deliberation_days` remains the configured duration and is kept synchronized when an administrator reschedules an active deliberation.
3. **Snapshot the schedule when deliberation starts.** `draft -> deliberation` sets `deliberation_start = now` and `deliberation_end = now + effective_deliberation_days`. Later changes to an organization's default duration do not retroactively move existing proposals.
4. **Zero-day behavior stays immediate.** A zero-day proposal still enters voting at creation. It records `deliberation_start = deliberation_end = voting_start = now`, then computes `voting_end` through the same voting-deadline rules as today.
5. **No new status.** `overdue` and `unscheduled` are derived labels, never enum values. Status transitions remain `draft -> deliberation -> voting -> terminal` plus existing specialized states.
6. **Cosign proposals remain specialized.** A cosign-gated deliberation advances or expires only through `cosign_expires_at` and the Phase 46a live-threshold decision. The general scheduled-transition query must explicitly exclude `is_cosign_gated = true`; `deliberation_end` must not bypass or compete with that gate.
7. **One deliberation-to-voting implementation.** Extract a route-independent lifecycle service used by both existing single-advance routes, the cosign helper, the new bulk route, the scheduled worker, and the reconciliation script. It owns status/timestamps, voting-end resolution, election candidate-option locking, audit details, and notification dispatch orchestration. The worker must not import a FastAPI route to mutate a proposal.
8. **Actual voting time controls the duration fallback.** When a proposal begins voting, `voting_start` is the actual transition timestamp. If `voting_end_date` is null, `voting_end = voting_start + voting_days`; automatic delay does not silently shorten the configured voting window.
9. **Explicit voting end remains absolute.** A valid `voting_end_date` continues to win over `voting_days`. If it has become stale or would violate the 0.05-day minimum at transition time, that proposal does not enter an invalid voting state: the item fails safely, remains visibly delayed, logs the error, and appears in monitoring for administrator correction.
10. **Future automatic transitions use normal notifications.** A successful scheduled transition emits the existing single `proposal.entered_voting*` notification choice per eligible opted-in recipient, just like a manual transition. Notification failure remains contained and never rolls back the lifecycle mutation.
11. **Historical Reform Table reconciliation suppresses notification fan-out.** The one-time operational repair advances the qualifying backlog without creating 75 voting-opened notifications per recipient. Each audit event records `trigger = phase102_reform_table_reconciliation` and `notifications_suppressed = true`. This exception applies only to that explicitly scoped historical repair; ordinary manual, bulk, cosign, and future automatic transitions retain normal notification behavior.
12. **The Reform Table authorization is bounded and explicit.** On apply, select only current `reform-table` rows that are ordinary, still in `deliberation`, have a valid start/duration, and whose derived deadline is due. Do not touch its existing `voting` or `withdrawn` proposal, and do not alter proposal text, options, topics, thresholds, durations, or the stored 500-day voting duration.
13. **Do not silently repair other organizations' overdue history.** The rollout inventory reports other active overdue ordinary proposals and historical overdue budget votes by organization/count. Overdue deliberation rows outside Reform Table keep `deliberation_end = null` until an authorized administrator schedules/advances them or Z separately approves a broader reconciliation. Existing future-due deliberation rows may be initialized to their derived future deadline because doing so preserves rather than accelerates their already-configured schedule. An already-overdue budget vote blocks activation of the new gate pending Z's disposition; Phase 102 may not silently close or reschedule it.
14. **Operation-first bulk UX.** The administrator chooses a bulk operation first; only rows eligible for that operation become selectable. This replaces the riskier idea of selecting mixed statuses and deciding afterward what a button might do.
15. **Bulk operations in scope.** The action selector offers:
    - `Move drafts to deliberation` (existing Phase 100 behavior);
    - `Move deliberation proposals to voting now`;
    - `Schedule voting to begin` for deliberation proposals; and
    - `Set voting end` for deliberation or currently voting proposals.
16. **Selection is visible-set and bounded.** Header selection means all currently rendered eligible rows, not every matching database row. Requests remain bounded to 500 unique IDs and use purpose-built bulk endpoints rather than one browser request per proposal.
17. **Scheduling authority requires both relevant powers.** Moving phases requires `proposal.advance_phase`. Setting a voting-start or voting-end date requires both `proposal.advance_phase` and `proposal.set_durations`, because it changes both lifecycle timing and duration policy. Existing author/moderator exceptions on single-item advance do not grant mass scheduling authority.
18. **Date validation is server-authoritative.** A scheduled voting start must be in the future; use `Move ... to voting now` for immediate action. A voting end must be in the future and must preserve at least 0.05 days (72 minutes) between the applicable voting start and end. Every item is validated against its own timestamps; one incompatible row does not poison valid siblings.
19. **Active-vote shortening requires a reason.** Extending an active voting deadline needs confirmation but no mandatory prose. Moving an active `voting_end` earlier requires a nonblank reason stored in the audit event. Immediate closure continues through the existing `Close Voting` action, not by supplying a past timestamp.
20. **Schedule changes are auditable.** Each changed proposal emits one `proposal.schedule_changed` event containing operation, old/new `deliberation_end`, old/new `deliberation_days`, old/new `voting_end_date`, old/new actual `voting_end`, actor, and reason when supplied. Avoid a second redundant bulk event per proposal.
21. **Partial, idempotent bulk results.** Duplicate IDs are processed once in stable first-occurrence order. Known results are named and retry-safe. Per-item savepoints contain unexpected failures. A retry never advances an already-voting proposal to a terminal status and never duplicates a successful schedule audit.
22. **Monitoring checks outcome, not merely heartbeat.** The public-safe monitor reports counts and guidance, never proposal titles, IDs, org names, or schedule timestamps. A healthy worker heartbeat plus persistent overdue proposals must not remain green.
23. **Five-minute timing expectation.** The existing decision worker interval remains 300 seconds. The UI says “scheduled” rather than promising an exact-to-the-second transition. Monitoring allows two intervals plus a small buffer before treating a due proposal as stuck.
24. **Budget deadlines must be real too.** Keep budget methods out of Stable Result Required evaluation and its incompatible snapshot path, but add a separate bounded due-budget close operation using the same quorum-only outcome semantics as manual close. Setting a budget proposal's voting end must therefore cause an automatic close within the normal worker interval.

## What this pass is

- The missing ordinary deliberation-to-voting scheduler.
- A durable proposal schedule visible to members and public read-only viewers where proposal visibility permits.
- A safe extension of Phase 100's bulk administration pattern.
- A controlled, explicitly authorized correction of the current Reform Table backlog.
- An operational monitor for stuck scheduled transitions.
- A compatibility repair ensuring the existing automatic voting-close promise covers both budget methods.

## What this pass is not

- No new `overdue` database status.
- No automatic advancement of cosign-gated proposals outside their existing live-threshold gate.
- No automatic movement from draft into deliberation.
- No redesign of Phase 24's non-budget terminal close; the budget-method compatibility path is a narrow extension using the same deadline/audit/notification contract.
- No bulk withdraw, archive, delete, edit-content, change-voting-method, change-threshold, or change-topic operation.
- No database-wide “select every matching proposal,” pagination, or virtualization project.
- No change to organization default duration values.
- No change to the Reform Table's 500-day voting duration.
- No notification-preference redesign or permanent suppression of voting-opened notifications.
- No second worker process or new paid service.

## Implementation sequence

1. Set `PROPOSAL_SCHEDULE_AUTOMATION_ENABLED=false` in Railway production **before** pushing the migration/code. Record this cost-free infrastructure change in the closeout.
2. Add the migration/model/schema and lifecycle service; update every transition call site and pass focused regressions.
3. Add the worker path, monitoring, typed bulk/schedule endpoints, and reconciliation script.
4. Build the schedule display and operation-first bulk controls.
5. Run migration cycle, PostgreSQL smoke, focused/full backend gates, frontend gates, and local timed/concurrency scale tests.
6. Merge with `--no-ff`, deploy with automation still disabled, and verify schema/head, bundle, readiness, monitor, and route presence.
7. Run a fresh non-writing production inventory. Initialize future-due legacy schedules as specified; leave unrelated overdue organization history unscheduled and report it.
8. Run the Reform Table reconciliation dry-run, compare against the expected 75-row baseline, then apply. Verify each resulting status/timestamp/audit and confirm the pre-existing voting/withdrawn rows were untouched.
9. Set `PROPOSAL_SCHEDULE_AUTOMATION_ENABLED=true`, allow the deploy/restart to settle, and verify the worker heartbeat plus zero stuck scheduled transitions.
10. Run a disposable timed-transition production proof and final browser QA. Do not create throwaway proposals in Reform Table.

## Cluster M — Model, migration, and schedule semantics

### M1 — `Proposal.deliberation_end`

Add:

```python
deliberation_end: Mapped[Optional[datetime]] = mapped_column(
    DateTime, nullable=True, index=True,
)
```

Use the repository's naive-UTC storage convention. Add the field to `schemas.ProposalOut` and every explicit proposal response builder. Confirm both member and public proposal endpoints surface it without exposing anything beyond the schedule already derivable from public proposal fields.

Migration `e7f8a9b0c1d2` (or the implementation team's next valid unique revision) follows `d6e7f8a9b0c1` and:

- adds the nullable column and index;
- backfills a derived value for historical proposals no longer in active deliberation when both start and duration exist;
- deliberately leaves currently active deliberation rows null for the feature-gated reconciliation rather than causing an uncontrolled first worker tick;
- drops only the index/column on downgrade; and
- passes SQLite cycle plus PostgreSQL fresh/upgrade smoke.

Do not use an organization slug inside the migration. Production-specific reconciliation belongs in the audited script.

### M2 — Transition-time population and synchronization

- `draft -> deliberation`: resolve the proposal's stored duration (normally already snapshotted at creation; org default only as legacy fallback), set start and end from one captured `now`.
- zero-day create: set start/end/voting-start to one captured timestamp.
- reschedule active deliberation: set the exact new end and update `deliberation_days = (new_end - deliberation_start) / 86400` so lockout calculations and displayed duration do not disagree.
- moving to voting: preserve `deliberation_end` as the planned historical boundary; do not overwrite it with actual `voting_start` if the worker was late.
- back-to-deliberation escalation path: inspect and deliberately define a fresh start/end rather than leaving a stale old schedule. The default is a new window starting at resolution time using the stored duration.

### M3 — Serializer and seed/import audit

Audit both proposal-create routes, issuance creation, elections, demo seed pipeline, direct model fixtures, import preview/create, response builders, and escalation paths. Most draft creation paths should leave `deliberation_end` null until entry; any path creating directly in deliberation or voting must set a coherent value or explicitly document why null is correct.

## Cluster L — Shared lifecycle service

Create a route-independent module such as `backend/proposal_lifecycle.py`. Move or wrap only the lifecycle pieces needed to prevent drift; do not refactor terminal tally/close logic into this pass.

The shared deliberation-to-voting function accepts `db`, `proposal`, actual transition time, actor/audit context, trigger, optional explicit voting end, notification mode/context, and the already-loaded organization when available. It must:

1. require/recheck `status == deliberation`;
2. reject the general path for cosign-gated proposals unless invoked by the specialized cosign gate;
3. calculate and validate `voting_end` through the existing Phase 25/75 precedence;
4. set `voting_start`, `voting_end`, and `status = voting` atomically;
5. lock election candidate options exactly once where applicable;
6. write `proposal.status_changed` with old/new status plus `trigger` and scheduled/actual timing;
7. leave transaction ownership to the caller;
8. return a typed transition/side-effect result so a shared post-commit helper can emit existing status notifications only after the durable commit, with failure containment; and
9. support the one explicitly audited `notifications_suppressed` reconciliation mode without making suppression client-selectable.

Replace both manual route implementations and `_advance_cosign_to_voting` with this service. Route permission gates and response shapes stay intact. A manual request cannot supply `trigger` or notification-suppression flags.

## Cluster W — Worker and monitoring

### W1 — Due ordinary proposal resolver

Add a named `advance_due_deliberation_proposals` operation to the existing decision worker. It runs once per tick when `PROPOSAL_SCHEDULE_AUTOMATION_ENABLED` is true and selects a bounded batch of rows satisfying:

- `status == deliberation`;
- `is_cosign_gated == false`;
- `deliberation_end IS NOT NULL`; and
- `deliberation_end <= now`.

Order by `deliberation_end`, then ID. Use a reasonable bounded batch (recommended 100) and continue across later ticks. On PostgreSQL, use row locking/`SKIP LOCKED` or an equivalently proven atomic-claim pattern. SQLite tests may use a compatible fallback. Recheck status/deadline inside the transaction so a manual action racing the worker becomes a no-op, not a double transition.

Each proposal commits independently. A stale/invalid explicit voting end or other item error logs safely, rolls back only that proposal, increments failure metrics, and allows siblings to proceed. Return/report `advanced`, `skipped`, and `failed` counts separately from snapshot counts.

Run the due transition before the tick snapshots/evaluates voting proposals, or document/test an equally safe ordering. Newly voting rows must not be terminally closed immediately unless their independently valid voting end is already due—which validation should normally prevent.

### W2 — Budget voting-end close compatibility

Do not send budget proposals through `evaluate_proposal`, SRR stability evaluation, or binary/multi-option snapshot capture. When `PROPOSAL_SCHEDULE_AUTOMATION_ENABLED` is true, run a separate bounded query for `status == voting`, method in `budget_allocation`/`budget_project`, and `voting_end <= now`.

Close each due row through the existing natural-close helper after extending that helper's outcome branch to support `AllocationTally` and `ProjectTally` exactly like both manual routes: quorum met -> `passed`, quorum unmet -> `failed`, including the valid degenerate “fund nothing” result. Preserve the original `voting_end`, emit the ordinary `proposal.closed` notification behavior, audit a clear `voting_end_reached` trigger, and contain failures per proposal. Add no budget trajectory snapshots and no SRR behavior.

### W3 — Health/monitor outcome check

Extend `ops_monitoring.build_snapshot` with a public-safe `proposal_lifecycle` component:

- `ok`: automation enabled and no proposal exceeds the grace period;
- `warning` with overall HTTP 200 while the feature gate is intentionally disabled during rollout;
- `error` with overall HTTP 503 when an ordinary scheduled deliberation or any supported voting proposal remains due more than approximately 11 minutes (two five-minute intervals plus buffer);
- include only count, oldest-overdue age bucket/seconds if safe, gate state, and guidance;
- guidance: check decision-worker logs, invalid proposal schedule, and lifecycle feature-gate state; and
- never expose IDs, titles, authors, or organization identifiers.

An intentionally null legacy schedule is not counted as overdue. Surface an aggregate `unscheduled_active_deliberation_count` as informational metadata for administrators/closeout if this can remain public-safe; it must not fail monitoring merely because unrelated legacy rows were deliberately held.

The voting-overdue check must include budget methods; it should also catch any regression in the existing Phase 24 close path.

### W4 — Feature gate

Add `PROPOSAL_SCHEDULE_AUTOMATION_ENABLED`, parsed with the project's standard truthy/falsey handling. It gates both new Phase 102 paths: ordinary deliberation auto-advance and budget-method timed close. Existing Phase 24 non-budget close and Phase 46a cosign behavior remain active so temporarily disabling the new code cannot regress already-shipped lifecycle promises. Default true for ordinary environments after Phase 102, but the production rollout must explicitly set false before deploy and true after reconciliation. When false, the worker logs one concise disabled-state message per startup/tick cadence—not per proposal—and the monitor reports disabled with actionable guidance.

Before enabling the gate, the production inventory must show zero unresolved historical budget proposals already past `voting_end`. If any exist, do not silently close or reschedule them: keep the gate false, report their organization/count to Z, and obtain a disposition because closing a vote is a governance outcome rather than a harmless metadata repair.

## Cluster B — Typed bulk lifecycle and scheduling APIs

Retain Phase 100's existing draft endpoint and its behavior. Add two org-scoped endpoints following the same validation, scoping, savepoint, and typed-result conventions.

### B1 — Bulk deliberation to voting now

Recommended route:

`POST /api/orgs/{org_slug}/proposals/bulk-advance-to-voting`

Request: 1–500 proposal UUIDs. Permission: `proposal.advance_phase`.

Named results:

- `advanced`;
- `already_in_voting` (idempotent success/no mutation);
- `ineligible_status`;
- `cosign_gate_required`;
- `invalid_schedule` with safe actionable detail; and
- `not_found` (including cross-org IDs).

Never call the generic “advance next status” route in a loop. A retry of an already-voting ID must not close it. Standard notification behavior applies.

### B2 — Bulk schedule update

Recommended route:

`PATCH /api/orgs/{org_slug}/proposals/bulk-schedule`

Request shape:

```json
{
  "proposal_ids": ["uuid"],
  "voting_starts_at": "2026-09-01T13:00:00Z",
  "voting_ends_at": "2026-09-15T13:00:00Z",
  "reason": null
}
```

At least one date is required; both may be supplied for deliberation rows. Permission requires both `proposal.advance_phase` and `proposal.set_durations`.

Eligibility and writes:

- `voting_starts_at`: only ordinary `deliberation`; set `deliberation_end` and synchronized `deliberation_days`.
- `voting_ends_at` on `deliberation`: set `voting_end_date`; validate against the new/existing scheduled start plus 72-minute floor.
- `voting_ends_at` on `voting`: update both actual `voting_end` and `voting_end_date`; validate against `voting_start`, current time, and shortening-reason rule.
- Draft, cosign-gated start schedules, terminal states, and cross-org rows return typed non-mutating results.

The endpoint returns requested/processed/updated/unchanged/ineligible/invalid/not-found aggregates plus stable per-ID results and safe detail. Identical schedule values are `unchanged` and do not create a second audit event.

### B3 — Individual controls reuse bulk semantics

The admin UI may call the bulk schedule endpoint with one ID rather than adding another nearly identical endpoint. Proposal Detail's ordinary author `Advance` button remains. Do not allow a public/client request to suppress notifications or impersonate a worker trigger.

## Cluster F — Schedule display and operation-first administration

### F1 — Proposal schedule display

On Proposal Detail, replace the misleading deliberation copy with:

- future scheduled: `Voting is scheduled to begin [localized date and time].`;
- due within worker grace: `Voting is scheduled to begin shortly.` plus the date/time;
- overdue beyond grace: `Voting was scheduled to begin [date/time] and the automatic transition is delayed.` Authorized administrators additionally see a link/button to the schedule controls;
- legacy null: `Voting has not been scheduled. An administrator can set a date or move it to voting.` for administrators, with neutral non-admin copy; and
- voting: retain `Closes ...` but include localized time, not date alone, where space permits.

Use the exact server field; do not independently recompute the authoritative deadline from current org settings. Public read-only pages may show the schedule because the proposal itself is public. Avoid exposing admin controls publicly.

Add a concise schedule summary to expanded Proposal Management rows: voting begins, voting ends (explicit or duration-derived where determinable), and delayed/unscheduled state.

### F2 — Bulk operation selector

Replace the draft-only selection assumption with an operation selector above the table. Default to no active operation or preserve `Move drafts to deliberation` as a clearly labeled initial choice—the frontend developer may choose the less surprising rendered flow during implementation, but no checkbox is selectable until its operation and eligibility are unambiguous.

Operations and eligible rows:

| Operation | Eligible statuses | Additional exclusions |
|---|---|---|
| Move drafts to deliberation | draft | existing Phase 100 rules |
| Move to voting now | deliberation | exclude cosign-gated |
| Schedule voting to begin | deliberation | exclude cosign-gated |
| Set voting end | deliberation, voting | per-row date validation |

Changing operations clears the previous selection after confirmation if any IDs were selected. The header checkbox selects/deselects all currently visible eligible rows for that operation and maintains checked/indeterminate state. Ineligible rows show no checkbox and preserve alignment.

### F3 — Review and date dialogs

Every mutation requires a confirmation showing organization, operation, count, up to five titles plus `and N more`, and the exact localized date(s) where relevant.

- Move-now warns that voting starts immediately and each proposal keeps its own configured voting duration/end rule.
- Schedule-start explains that automation normally runs within five minutes of the selected time.
- Set-end explains whether the selected set includes active voting proposals and requires a reason field if any active deadline is being shortened.
- Confirmation copy must not claim all rows will succeed; the backend validates each row.

Submit deterministic chunks of at most 500 with low bounded concurrency, aggregate all typed results into one toast/summary, refresh after completion, clear successes/no-longer-eligible rows, and retain retryable failures. Do not emit one toast per proposal.

### F4 — Accessibility and responsive behavior

Operation selector, checkbox labels, dialog fields, validation errors, and result summaries must be keyboard-operable, announced, and usable at approximately 380px without horizontal scrolling or undersized targets. Date inputs show the viewer's local timezone while requests send ISO timestamps. Display the timezone abbreviation/name in confirmation so a shared bulk schedule cannot be misread.

## Cluster R — Controlled production reconciliation

Add an idempotent script, recommended `backend/scripts/reconcile_deliberation_schedules.py`, with dry-run as the default and explicit `--apply` required. It must never accept arbitrary SQL and must never touch terminal/voting rows.

Required modes:

1. **Inventory:** report counts grouped by organization and category: future-due ordinary deliberation, overdue ordinary deliberation, cosign-gated, invalid/missing schedule inputs, already scheduled, and overdue budget voting. No mutation.
2. **Initialize future legacy schedules:** for active ordinary deliberations outside Reform Table whose derived deadline remains in the future, set `deliberation_end` to that derived deadline with an audit event; do not advance them.
3. **Reform Table authorized reconciliation:** for `org.slug == reform-table`, advance every currently qualifying overdue ordinary deliberation row through the shared service, with historical notification suppression and the Phase 102 trigger/audit detail.

The apply mode prints and records before/after counts, IDs/titles for the operator's private evidence file, new voting timestamps/end timestamps, failures, and audit counts. Do not commit titles/IDs to a public monitoring payload. If the qualifying Reform Table count differs from 75, do not blindly abort: rerun/inspect the delta, confirm every changed row still meets the locked criteria, and explain the exact count in closeout. No hardcoded proposal IDs.

After apply, verify:

- Reform Table has zero qualifying overdue ordinary deliberation rows;
- each advanced row has one status audit with the reconciliation trigger;
- no entered-voting notification rows were created by this reconciliation;
- the existing voting proposal stayed voting and retained its prior timestamps;
- the withdrawn proposal stayed withdrawn;
- all proposal content/configuration remained unchanged except lifecycle timestamps/status; and
- unrelated organization overdue rows remained unscheduled/unmodified except explicitly initialized future schedules.

## Cluster T — Automated tests

Create focused Phase 102 backend tests and update existing lifecycle/monitor suites. Required coverage includes:

- migration/model/serializer/round-trip and index presence;
- draft transition populates one start/end pair from stored duration and legacy org fallback;
- zero-day create produces coherent equal start/end/voting-start;
- org-default change after entry does not move an existing deadline;
- manual single routes, new bulk route, cosign route, and worker share identical voting-start/end and audit behavior;
- ordinary due proposal advances at equality and after deadline, never before;
- null schedule, cosign gate, wrong status, and invalid voting end do not advance;
- binary, approval, RCV, allocation, project, election, and issuance proposals enter voting correctly; election options lock once;
- worker batch bound/order, per-item failure containment, retry idempotence, and simulated concurrent/manual race;
- due budget-allocation and budget-project proposals close automatically with quorum-only pass/fail semantics, ordinary close notifications, preserved deadline, no SRR snapshot, and idempotent retry;
- notification emission once for future automatic/manual bulk transitions; reconciliation suppression only through server-internal mode;
- bulk advance permission/scope/results/duplicate/retry behavior, including proof an already-voting retry cannot close;
- bulk schedule permissions require both keys; start/end eligibility and validation; active shortening reason; unchanged no-audit; partial results;
- rescheduling updates `deliberation_days` consistently;
- Phase 24 auto-close respects a newly bulk-updated active `voting_end`;
- monitor healthy, disabled, within-grace, stuck-overdue, invalid-schedule, and public-safe payload cases;
- monitor detects overdue voting proposals for both budget and non-budget methods;
- reconciliation dry-run writes nothing; apply is slug-scoped/idempotent; existing voting/withdrawn rows untouched; no notification rows; and
- migration upgrade -> downgrade -> upgrade on SQLite plus PostgreSQL smoke.

Frontend tests/source contracts must cover:

- correct future/delayed/unscheduled/voting copy and use of `deliberation_end`;
- localized date-time and timezone confirmation;
- operation selection determines checkbox eligibility;
- operation change clears/confirms existing selection;
- select-visible and indeterminate state per operation;
- each operation calls only its intended endpoint with bounded chunks;
- schedule validation and active-shortening reason UI;
- partial completion/selection reconciliation and one aggregate result;
- public read-only schedule display with no admin controls; and
- desktop keyboard plus approximately 380px responsive contracts.

## Cluster Q — QA and production verification

Before production mutation, use a disposable local/temporary organization to verify:

1. a proposal scheduled a few minutes ahead remains deliberating before the boundary and advances within one worker interval after it;
2. one normal voting-opened notification per opted-in eligible recipient, not duplicates;
3. bulk move-now on several proposals preserves their own voting durations;
4. bulk schedule-start and set-end produce correct local/UTC timestamps and audit entries;
5. a cosign-gated proposal cannot be selected or advanced by the ordinary scheduler;
6. an already-voting retry cannot close voting;
7. an active voting deadline can be extended, while shortening requires a reason;
8. delayed/unscheduled/future copy on member and public pages;
9. operation-first checkboxes, confirmation, partial results, keyboard, and approximately 380px behavior; and
10. monitor changes from controlled overdue failure back to healthy after correction.

Production order is load-bearing: disabled gate -> deploy -> inventory -> reconcile -> verify -> enable -> disposable proof -> final monitor. Do not reverse it.

## Operational watch-outs

- The worker currently lives in `sustained_majority_worker.py`, but its health label is presented as the decision worker. Renaming the process/module is not required; use clear new log event names so lifecycle failures are searchable.
- Budget methods are intentionally excluded from SRR, not intentionally exempt from their voting deadline. Keep their new close query separate so adding deadline enforcement does not accidentally feed budget ballot shapes into SRR code.
- Notification creation can be expensive for a large eligible electorate. Process due proposals in bounded batches and keep notification failures contained. Do not hold a database row lock while performing external email delivery.
- Existing `voting_end_date` can be stale because proposals may sit in draft/deliberation. This was already a manual-advance 400; automation makes monitoring and schedule correction essential.
- A 500-day Reform Table voting window is unusual but confirmed stored configuration. Preserve it exactly; this pass is lifecycle repair, not governance-policy reinterpretation.
- Editing lockout remains applicable to proposal content. The schedule endpoint is intentionally separate and permission-gated so administrators can correct timing without reopening substantive edits.
- If production has overdue proposals in an organization other than Reform Table, list only organization/count in the closeout and leave them unscheduled unless separately authorized. Do not let enabling the worker accidentally advance them.
- Railway env changes are infrastructure changes. Record old/new gate values and deployment timing; never print secrets. The boolean is not sensitive.

## Closeout reporting

The Phase 102 closeout must include:

- per-cluster DONE/blocked/scoped-up status;
- root cause statement distinguishing missing general automation from worker health;
- migration revision, row/backfill counts, cycle, and PostgreSQL smoke;
- lifecycle tests across all proposal types, budget timed-close compatibility, concurrency/idempotence, notifications, monitoring, and bulk endpoints;
- backend test-count delta from 3,065 and frontend test/build/lint results;
- browser verification for schedule display and every bulk operation, or an explicit unclaimed blocker per `AGENTS.md`;
- production gate sequence and timestamps;
- fresh pre-apply inventory by organization/category;
- exact Reform Table dry-run/apply count and any difference from the expected 75;
- confirmation of notification suppression for only the historical reconciliation;
- confirmation that the existing Reform Table voting/withdrawn rows and all proposal content/configuration were untouched;
- post-enable worker heartbeat, overdue count, readiness, monitor, bundle, and disposable timed-transition result;
- files changed and commit list; and
- branch, no-ff merge, push, Railway deployment row if available, and production sanity status.
