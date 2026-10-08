# Phase 109 — Experimental single-winner voting

Status: W0–W4 complete locally; W5 integration and release verification in progress.
Not merged or deployed yet. Approved specification:
`phase109_experimental_single_winner_methods_spec.md`.

## Delivery

Organizations can opt into STAR, Score, Ranked Pairs and Majority Judgment for
ordinary single-winner proposals. Existing defaults and officeholder elections
remain unchanged. Each method preserves whole-ballot delegation, represented
member weights, direct and neutral overrides, abstention, late write-ins,
early-vote privacy and existing authorization boundaries.

New proposals commit to a reproducible final draw order. Final results preserve
the rule version, original option labels, exact aggregate counts, participation,
count mode, actual close time and revealed seed. Closing and ballot/option
changes serialize on the proposal row. Finalization, audit and persisted
notification intent share one transaction; retries do not duplicate them.

| Workstream | Local status | Evidence |
| --- | --- | --- |
| W0 shared contracts/migration | DONE | Strict schemas, registry, defaults, SQLite cycle and PostgreSQL smoke |
| W1 STAR | DONE | 2,000 profiles versus isolated pinned starvote 2.1.5; full local browser journey |
| W2 Score | DONE | 2,000 independent exact-sum reference profiles; full local browser journey |
| W3 Ranked Pairs | DONE | 1,000 independent topological-reference profiles; full local browser journey |
| W4 Majority Judgment | DONE | 82,993 exhaustive histogram pairs and 2,000 random literal-removal comparisons; full local browser journey |
| W5 release | IN PROGRESS | Full regression passed; production verification pending |

The Majority Judgment counter interleaves compact runs from the sorted lower
and upper histogram halves. It reproduces repeated lower-median removal without
looping once per represented share. Ranked Pairs uses incremental reachability
for cycle rejection and never enumerates all tie permutations. Exact aggregates
are decimal strings at public boundaries; grade identifiers remain numeric.

## Verification and fixes found

Each method passed desktop and 380px Chrome checks for keyboard controls,
casting, changing, abstaining, retracting, delegation, late options, private
early voting and manual close. Majority Judgment's actual tied-median display
was checked against its original distributions. Final audit disclosures and
actual close dates were verified. Screenshots: `test_results/phase109/`.

Browser review fixed duplicate full STAR results, stale saved early ballots
when hidden results returned 404, and scheduled dates shown as actual close
dates. Integration review fixed archived frozen winners being called provisional;
subsequent browser QA also removed unusable write-in removal controls from
archived finalized proposals. The corrected archive journey was reverified.

Final frontend: 124 tests passed; build `index-BYrMsS6k.js`. Ten lint errors and
one warning were reproduced in baseline `0096997`; all new lint findings are
resolved. The focused Didit assignment guard and its six tests pass.

Final backend full regression: **3,602 passed, 21 skipped, zero failures** in
1,499.91 seconds with four pytest workers. Six worker-helper tests added after
collection also passed separately: **3,608 distinct passing cases**, up **364**
from Phase 108's 3,244. The 21 skips include the isolated optional STAR oracle,
which separately passed its 2,000-profile comparison, and existing environment
skips. The earlier interrupted sequential run is not counted as a pass.

Migration `a109b0c1d2e3` above `f8a9b0c1d2e3` passed SQLite
upgrade/downgrade/upgrade and disposable PostgreSQL fresh/upgrade smoke. No
later method adds another migration. Each method passed 40 concurrent
PostgreSQL HTTP/snapshot operations with a bounded five-connection pool and
no leaked connections or residual waiting locks. Actual option-add/close races
passed for all four methods, with frozen option sets matching committed rows.

Detailed counter, memory, SQL and latency measurements are in the four
`docs/phase109_*_backend_evidence.md` files. The dense 120-option Ranked Pairs
case costs substantially more than the other methods; local measurements are
not a production capacity guarantee.

## Release and operational boundaries

Branch: `phase-109/experimental-single-winner-methods`, based on `0096997`.
The original dirty planning checkout remains untouched. Final merge SHA,
backend Railway deployment, frontend bundle and production sanity: PENDING.

Release QA is limited to a hidden, invite-only synthetic organization and two
new non-platform-admin accounts using `demo.example` addresses. Every registered
notification channel is opted out. The additive bootstrap refuses any identity
or organization collision and prints no passwords or tokens. It has been
locally tested but has not run in production yet. Normal API/UI creation will
initialize the actual QA proposal rules.

Existing immediate-email background tasks are not a durable outbox. Atomic
close tests cover the existing persisted notification intent, not guaranteed
immediate email delivery across crashes. This pre-existing limitation remains.
The legacy full-suite demo reset fixtures repeatedly perform real bcrypt
hashing; they dominate the final regression tail. The suite was left running
to completion rather than treating the slow tail as a passed gate.
No infrastructure, provider secrets, paid capacity, history rewrites or
destructive production cleanup is included. Officeholder elections,
multiwinner variants and custom grade scales remain outside this phase.
