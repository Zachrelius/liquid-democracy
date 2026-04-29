# Phase 8 — Sustained-Majority Voting Windows (opt-in)

**Type:** Feature pass with backend, frontend, and ops surfaces. New governance feature, no breaking changes.
**Dependencies:** Phase 7C.2 complete (Sankey polish landed). All current platform features (binary/approval/RCV voting, multi-tenant orgs, admin portal, audit logging, Phase 7.5 access controls).
**Goal:** Ship sustained-majority voting windows as a fully configurable, default-off opt-in feature. Org admins choose whether their org wants it; proposal authors can override per-proposal where the org allows.

---

## Context

Sustained-majority voting windows are a real governance feature: a proposal must maintain support throughout the voting window rather than just pass at a single moment. The mechanism protects against late-stage manipulation (a controversial vote cast in the final hour with no time for delegators to react), narrow majorities that flip with normal participation churn, and "snap votes" that don't reflect durable preference. The platform was originally designed to ship this as the default for binary proposals.

After roadmap review on 2026-04-28, we're shipping it as opt-in instead. Reasoning:

1. Most decisions don't need it. A neighborhood association picking a meeting time doesn't need durable-consensus protection. Forcing the regime on every proposal is the platform pretending to know more about what the org needs than the org does.
2. Orgs that want it should get the full feature, configured to match their governance norms. Threshold, floor, failure mode, and per-proposal override should all be choices, not defaults.
3. The infrastructure work is the same either way. Snapshots get evaluated against thresholds; the feature gets configurability. Default-off is a one-bit decision in the seed config.

The pass also serves an infrastructure-validation purpose: `VoteSnapshot` is the ground truth for the sustained-majority background job, and it'll get exercised at higher cadence than ever before. If the snapshot pipeline has bugs, this pass will surface them — better to find them now than after Phase 9 (Polis) layers deliberation content on top of an already-stretched pipeline.

---

## Design Decisions Locked In Before Dispatch

### Decision 1: All defaults are off

Every sustained-majority configuration key defaults to off, threshold-equivalent, or fail-safe:
- `sustained_majority_enabled_default`: `false`
- `sustained_majority_per_proposal_override`: `true` (so authors can opt a single proposal in even if org default is off)
- `sustained_majority_threshold`: `0.5` (matches existing pass-threshold default)
- `sustained_majority_floor`: `0.45`
- `sustained_majority_failure_mode`: `fail`

Existing orgs migrate cleanly: their settings JSON gets these keys added with the defaults above on first read (lazy migration via the settings accessor) or on a one-time backfill — dev team's call. No proposal currently active has sustained-majority enabled, so nothing in flight changes behavior.

### Decision 2: The configuration lives in `Organization.settings` JSON

No new database table. The `Organization.settings` JSON column already holds voting defaults; sustained-majority keys are added as siblings. Reasons: simpler migration, matches the existing pattern for org-scoped voting defaults (deliberation_days, voting_days, pass_threshold, quorum_threshold), avoids a schema change for what's effectively five config values.

This means the JSON-mutation bug from Phase 4 Cleanup (Fix 1) is in scope: any update to these settings must use the new-dict construction pattern (`org.settings = {**(org.settings or {}), **body.settings}`), not in-place mutation, or SQLAlchemy won't detect the change.

### Decision 3: `Proposal.sustained_majority_enabled` is nullable boolean override

Three states:
- `null` (default for new proposals): use org's `sustained_majority_enabled_default`
- `true`: this proposal uses sustained-majority regardless of org default
- `false`: this proposal does not use sustained-majority regardless of org default

This is a schema migration (new nullable column). The author can only set this to a non-null value if the org has `sustained_majority_per_proposal_override: true`. If the org has it false, the proposal creation form doesn't show the toggle and the API rejects non-null values with 403.

### Decision 4: New proposal status `unresolved` only when failure_mode is `escalate`

`Proposal.status` lifecycle extends:
- Existing: `draft` → `deliberation` → `voting` → `passed` / `failed` / `withdrawn`
- New: `voting` → `unresolved` (only reachable when sustained_majority is enabled and failure_mode is `escalate` and the floor was breached)

`unresolved` proposals require an org admin (or moderator with proposal-advance permission) to take an explicit action: extend the window, mark as failed, mark as passed (admin override — discouraged but available for emergencies), or move back to deliberation for amendment.

The action is itself audit-logged (`proposal.escalation_resolved` with the chosen resolution).

### Decision 5: Snapshot cadence is "every 5 minutes during active voting windows"

The existing snapshot mechanism takes a snapshot at vote events. For sustained-majority, we additionally take a snapshot every 5 minutes while a proposal is in `voting` status, regardless of whether votes are being cast. This catches floor breaches caused by delegate-vote changes, delegator revocations, or follow-relationship changes that affect the effective tally without producing a vote event.

5 minutes is a balance — fine enough to catch breaches before they're stale, coarse enough that the database doesn't fill with mostly-identical snapshots. Configurable via env var `SUSTAINED_MAJORITY_CHECK_INTERVAL_SECONDS` (default 300) for ops tuning.

The background job is implemented as a separate process spawned at startup (similar pattern to the existing email worker if there is one, or a new worker entry in `start.sh`). For a single-instance deployment this is fine; for multi-instance the job should run on exactly one instance — the dev team should add a simple lock-table or env-flag mechanism to control this.

### Decision 6: Multi-option "stable result" semantics

When sustained-majority is enabled on an approval or RCV proposal, the failure condition isn't "support drops below the floor" (that doesn't map cleanly). Instead, it's "the computed winner changes during the final N% of the voting window." Default N: 25%.

Concrete behavior:
- During the first 75% of the voting window: snapshots are taken but no failure check runs
- During the final 25%: each snapshot's computed winner is compared to the previous snapshot's. Any change triggers the failure mode.

This catches the equivalent failure mode for multi-option (a controversial late-stage shift in who wins) without the binary-style threshold mechanic that doesn't fit ranked or approval ballots.

### Decision 7: Floor-approach notifications are in-app initially

When a user's effective ballot (their direct vote, or the inheritance from their delegate) is contributing to a sustained-majority proposal that is approaching the floor (within 5 percentage points), the platform notifies them in-app with a small banner on the proposal detail page and a notification badge increment. They can review the situation and decide whether to revoke their delegation or change their vote.

Email notifications for this are deferred to Phase 10 if the notification system lands first. If Phase 10 is sequenced before this pass — possible but not currently planned — notifications are added to the existing notification preferences with a sensible default (on for users who already have notifications on).

---

## Scope

### Backend

**Schema migration:**
- Add `Proposal.sustained_majority_enabled` (nullable boolean)
- Extend `Proposal.status` enum with `unresolved`
- Migration is reversible: `unresolved` proposals downgrade to `failed` on rollback

**Settings accessors:**
- New helper `get_sustained_majority_config(org)` that returns a typed object with all five keys, applying defaults if absent. Used everywhere the config is read.
- All writes to `Organization.settings` use the new-dict pattern from Phase 4 Cleanup Fix 1.

**Tally evaluation:**
- New module `backend/sustained_majority.py`:
  - `is_above_floor(snapshot, config)` — for binary proposals, checks support level vs floor
  - `winner_stable(snapshot, previous_snapshot)` — for multi-option proposals, checks whether the computed winner changed
  - `should_trigger_failure(proposal, snapshots, config)` — combines the above; returns the failure mode that should fire, or None
- Pure functions, no DB access, fully testable

**Background job:**
- `backend/sustained_majority_worker.py` — long-running process that wakes every `SUSTAINED_MAJORITY_CHECK_INTERVAL_SECONDS`, queries proposals in `voting` status with sustained-majority enabled, and applies failure mode if triggered
- Each check is a transaction; failure-mode actions are atomic (status change + audit log entry in the same transaction)
- Multi-instance protection: if `SUSTAINED_MAJORITY_WORKER_INSTANCE_ID` env var is set, only the matching instance runs the job. Default to running on instance "primary" or first-to-start.
- Started from `start.sh` as a separate process; container restart resumes cleanly.

**API endpoints:**
- Existing org-settings endpoint extends to accept the new keys (via the existing settings update pattern)
- Existing proposal-create and proposal-update endpoints accept `sustained_majority_enabled` (rejected if org doesn't allow per-proposal override)
- New endpoint `POST /api/orgs/{slug}/proposals/{id}/resolve_escalation` for admins to resolve `unresolved` proposals. Body specifies action (`extend` / `fail` / `pass` / `back_to_deliberation`) and optional reason.
- Existing proposal-detail endpoint includes sustained-majority status in the response (current support level, distance to floor, time remaining, whether floor has been breached)

**Audit events:**
- `org.sustained_majority_config_changed` with the new and old config values
- `proposal.sustained_majority_enabled` / `proposal.sustained_majority_disabled` (per-proposal toggle)
- `proposal.window_extended` with the new end time
- `proposal.failed_sustained_majority` with the breach details
- `proposal.escalated` when failure_mode is `escalate`
- `proposal.escalation_resolved` with the admin's chosen action and reason

### Frontend

**Org admin settings (`pages/admin/OrgSettings.jsx`):**
- New "Sustained-Majority Voting" section with:
  - Toggle: "Default on for new proposals" (sets `sustained_majority_enabled_default`)
  - Toggle: "Allow proposal authors to override per-proposal" (sets `sustained_majority_per_proposal_override`)
  - Slider: "Required support level" (sets threshold)
  - Slider: "Drop-below floor" (sets floor)
  - Radio: "When floor is breached" (`fail` / `extend` / `escalate`) with brief explanation per option
  - Help text linking to the admin help page

**Proposal creation form (`pages/admin/ProposalManagement.jsx`):**
- New "Sustained-Majority Voting" toggle, visible only if org has `sustained_majority_per_proposal_override: true`
- Default value matches org default
- Help tooltip: "Requires the proposal to maintain support throughout the voting window. Useful for binding decisions; overkill for routine matters."

**Proposal detail page (`pages/ProposalDetail.jsx`):**
- When sustained-majority is active: support indicator showing current support level and distance to floor (visual: a bar with a marker for current support and a red zone for sub-floor territory)
- Historical chart of support over the window (Recharts; reuse the existing snapshot-time-series chart pattern)
- Floor-approach banner: shown to users whose effective ballot is contributing to a proposal within 5pp of the floor. Banner offers "Review your vote" and "Review your delegation" links.
- Status badge for `unresolved` proposals: distinct visual treatment (yellow/amber, "Awaiting admin review")
- For multi-option: "Stable result lock" indicator when in the final 25% of the window, with a visible note if the winner changed (rare but possible)

**Admin escalation resolution (`pages/admin/ProposalManagement.jsx`):**
- New section/badge on `unresolved` proposals showing breach details (when, how far below floor, who was contributing)
- Resolution UI: four-button choice (Extend window / Mark as failed / Mark as passed (override) / Return to deliberation), with required reason field for the override case
- Audit-log link so the admin can see the full breach history

**Proposal list page (`pages/Proposals.jsx`):**
- Small badge on proposals with sustained-majority active. Helps voters know which proposals to keep tabs on rather than fire-and-forget.

**Notification badge (`components/NotificationBadge.jsx`):**
- Floor-approach notifications added to the existing badge dropdown

**Help documentation:**
- New page `frontend/src/pages/SustainedMajorityHelp.jsx` linked from org admin settings and proposal creation help text. Plain language. Covers what it is, when to use it, what each failure mode does, what happens to delegators when the floor is approached.

---

## Test Coverage

**Backend unit tests (target +25 to +30 tests):**
- Pure-function tests for `is_above_floor`, `winner_stable`, `should_trigger_failure`
- Org-config CRUD: setting all five keys, JSON-mutation correctness, validation errors
- Per-proposal override: respected when org allows, rejected when org doesn't
- Failure mode handling: each of `fail` / `extend` / `escalate` behaves correctly
- Multi-option stable-result: winner change in final 25% triggers, winner change before final 25% doesn't
- Audit log entries are created for every state-changing event in this feature

**Backend integration tests:**
- Background job picks up an active proposal, evaluates correctly, applies failure mode
- Multi-instance protection: when the env-var lock is set to a different instance, the job doesn't run
- Snapshot pipeline produces the right snapshots at the right cadence (mock the time provider)

**PostgreSQL smoke test:**
- Required. Schema migration involves a new column on `Proposal`, JSON-mutation patterns are SQLite-vs-Postgres-sensitive territory, and the snapshot table will see significantly more writes. Test on Postgres.

**Frontend tests (browser-driven, Suite P):**
- P1: Admin enables sustained-majority at org level, default is applied to new proposals
- P2: Author overrides org default per proposal
- P3: Per-proposal override blocked when org disallows
- P4: Proposal detail page shows correct sustained-majority status during active voting
- P5: Floor-approach banner appears when within 5pp
- P6: Failure mode `fail` — proposal moves to failed when floor breached
- P7: Failure mode `extend` — window extends once, second breach fails
- P8: Failure mode `escalate` — proposal moves to unresolved, admin resolution UI works
- P9: Multi-option stable-result lock visible in final 25% of window
- P10: Audit log captures all sustained-majority events with correct details

**Browser-driven prod sanity after Railway deploy:**
- Org settings page renders the new section
- Creating a test proposal with sustained-majority enabled produces correct UI state
- Background job is running (verifiable via a fresh snapshot appearing within 5-6 minutes of voting status)

---

## Out of Scope

- Sustained-majority for sub-org proposals (Phase 8.5 scope)
- Email notifications for floor approaches (Phase 10 if notifications system lands first)
- Real-time (sub-minute) snapshot evaluation
- Sustained-majority during deliberation phase
- Cross-org sustained-majority defaults (no platform-wide config; each org configures independently)
- Migration of existing failed/passed proposals (they stay in their current status; sustained-majority only affects proposals created after the feature is enabled)

---

## Acceptance Criteria

1. Org admin can configure all five sustained-majority settings through the admin UI; configuration persists correctly across navigation (Phase 4 Cleanup Fix 1 pattern verified for these new keys).
2. Proposal author can override per-proposal where the org allows it; the override is correctly respected by the background job.
3. Background job runs continuously during active voting windows, evaluates proposals at the configured cadence, and applies the correct failure mode when triggered.
4. All three failure modes (`fail`, `extend`, `escalate`) work end-to-end, with appropriate UI for each.
5. Multi-option stable-result semantics implemented and tested.
6. Floor-approach notifications appear in-app for users whose effective ballot is contributing to an at-risk proposal.
7. Every state-changing event has a corresponding audit log entry with appropriate detail (no ballot content; respects Phase 7.5 redaction).
8. PostgreSQL smoke test passes.
9. Suite P (10 tests) committed to `browser_testing_playbook.md` with PASS results.
10. Screenshots committed to `test_results/phase8_screenshots/` with `README.md` index.
11. PROGRESS.md updated with Phase 8 entry covering scope, design decisions, and test results.
12. Browser-driven prod verification noted in PROGRESS.md.

---

## Notes for the Dev Team

- **The org-settings JSON-mutation pattern is non-obvious and has bitten us before.** Every endpoint that updates `Organization.settings` must use `org.settings = {**(org.settings or {}), **body.settings}` — not `org.settings.update(body.settings)`. SQLAlchemy doesn't detect in-place mutations. Verify this against Phase 4 Cleanup Fix 1's tests.
- **The background job is the riskiest piece.** Test it carefully against time mocks. Verify it doesn't double-run actions if it's restarted mid-cycle. Verify multi-instance protection works.
- **Multi-option stable-result is subtle.** A winner changing in the final 25% should trigger failure; a winner changing earlier shouldn't. Test the boundary (right at 25% remaining) carefully.
- **The existing seed-data demo proposals don't use sustained-majority.** No migration concerns there. New seed scenarios that exercise the feature would be useful for QA — consider adding 1-2 demo proposals (one binary with `extend`, one approval with `escalate`) to the additive seed if it makes sense.
- **Pacing:** moderate complexity, not a polish pass. Quality of the background job and audit logging matters more than speed.