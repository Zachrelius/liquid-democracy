# Phase 109 execution evidence

Started October 8, 2026 from refreshed origin/master `0096997` in isolated
`phase-109/experimental-single-winner-methods`. Original dirty checkout preserved.

## W0 — shared foundation: PASS

- Approved spec committed first: `ce16797`.
- Backend registry separates legacy defaults, planned methods, and released methods.
- Versioned server rules, protected cryptographic draw seed and public commitment;
  strict scores/grades/rank-group validation and bounded option references.
- Nullable reversible migration `a109b0c1d2e3` above `f8a9b0c1d2e3`.
- 56 helper tests including subprocess SQLite upgrade/downgrade/upgrade passed.
- 88 schema/legacy RCV/organization-creation checks passed.
- 82 frontend tests passed; defaults and old feed labels retained.
- Independent cross-review found no blocking contract defect.
- PostgreSQL 16 fresh and prior-head upgrade smoke passed. Docker initially stopped;
  starting installed Docker resolved it. Concurrent default-port use was avoided
  with port 55509 for lead's independent run; both disposable containers removed.

## W1 — STAR: in progress, NOT release verified

- Pure counter compared with pinned test-only `starvote==2.1.5`, MIT license,
  against 2,000 synthetic profiles. No reference dependency in production.
- Exact integer scoring/runoff and histogram tiebreaks, represented-member weights,
  final immutable result, seed reveal only in final aggregate, new ballot UI,
  opt-in settings, early voting/write-ins, trajectories, and lifecycle integration.
- 144 focused core/SRR/legacy checks passed; subsequent extra STAR tests and
  performance checks are recorded by the backend workstream.
- 27 route regressions passed; broad W0/W1/import/edit compatibility:157 passed,
  one migration fixture setup failed from restricted system temp permissions.
  Exact migration rerun with workspace-local base temp passed; no code failure.
- Frontend 92 tests pass, production build passes (`index-DRsQa-g0.js`). Eight ESLint errors plus one
  warning in legacy components reproduced verbatim on pre-W1 source; new files clean.
- Actual rendered Chrome session reached synthetic local login, then tool reported
  another extension UI open, requiring user completion/dismissal. Required browser
  journey is BLOCKED, not replaced by React server rendering or source checks.
- Recheck on a new tab in the same Chrome session again stopped while filling
  synthetic login, with the explicit message: "Google Chrome is blocking
  automation because another extension UI is open on this page. Complete or
  dismiss that extension UI in Google Chrome, then ask me to continue."
- Full backend regression: **3,379 passed, 21 skipped**, 796.92 seconds. This
  collection preceded the final review additions. Latest focused W0/W1 plus
  lifecycle/privacy regression: **178 passed, 1 optional-oracle skip**. The oracle
  was separately rerun with its isolated package and passed all 2,000 profiles.
  Restricted execution could not read that installed package; the same command
  with authorized package access passed. Latest STAR/delegate-notification
  regression: **87 passed**. Phase 109 adds **160 collected backend tests**.
- Review fixed manual/worker close transaction atomicity (final result, audit,
  persisted notification intent), retry behavior, missing stability history,
  draft multiwinner transitions, archive serialization, preliminary-result
  visibility, current membership/active-account notification scope, exact
  large weights and frozen rule scale, and readable private profile summaries.
  Actual injected notification failures prove rollback; retries produce one
  close audit and notice. Existing legacy behavior is retained outside this slice.
- PostgreSQL synthetic concurrency: 40/40 operations succeeded with a bounded
  five-connection pool, no checkout timeouts or residual waiting locks. Detailed
  latency, memory, reference and algorithm measurements are in
  `docs/phase109_star_backend_evidence.md`.
- Source availability currently enables STAR for integrated local testing only.
  No branch push, merge, or production deployment yet.

## W2–W5

NOT STARTED. Sequential method gates prohibit starting Score until W1 rendered
verification and remaining compatibility/performance review pass. Ranked Pairs,
Majority Judgment, release integration and production QA remain pending.

No production data, secrets, or infrastructure configuration changed.

## Remaining gates and known limitations

W1 still needs the full rendered desktop/mobile/keyboard ballot, re-vote,
retraction, delegation, write-in and final-result journeys. Dismissing the
blocking Chrome extension UI is the external action required to resume them.
Do not begin W2 until W1 passes; do not deploy this partial phase.

The existing immediate-email mechanism is not a durable outbox, and worker
`BackgroundTasks` lack an HTTP response cycle. Atomic close coverage applies to
the existing persisted opted-in notification intent; this is not a guarantee of
immediate email delivery across crashes. No mail infrastructure was changed.

Local synthetic QA servers are available at frontend `127.0.0.1:5173` and backend
`127.0.0.1:8001`; fixture creation is documented by
`backend/scripts/phase109_localqa.py`. No production authentication is involved.
The untracked full-suite log and pytest temporary directory are local test
artifacts, excluded from commits. Original dirty root files remain untouched.
