# Phase 109 — Experimental single-winner voting

Status: W0–W5 DONE. Deployed and production-verified October 8, 2026.
Approved specification: `phase109_experimental_single_winner_methods_spec.md`.

## Delivery

Organizations can independently opt into STAR, Score, Ranked Pairs and Majority
Judgment for ordinary single-winner proposals. All four are off by default.
Existing methods and officeholder elections retain their prior behavior.
Each method preserves whole-ballot delegation, represented-member weights,
direct and neutral overrides, explicit abstention, late write-ins, preliminary
ballot privacy, authorization and organization/subgroup inheritance.

New proposals commit to a reproducible final draw order before voting. Final
results preserve rule version, original option labels, exact aggregates,
participation, count mode, actual close time and revealed seed. Closing and
ballot/option changes serialize on the proposal row. Finalization, audit and
persisted notification intent share a transaction; retries do not duplicate them.

| Workstream | Status | Evidence |
| --- | --- | --- |
| W0 shared contracts/migration | DONE | Strict schemas/defaults, SQLite migration cycle, PostgreSQL fresh/upgrade |
| W1 STAR | DONE | 2,000 profiles versus pinned starvote 2.1.5; local and production rendered journeys |
| W2 Score | DONE | 2,000 independent exact-sum profiles; local and production rendered journeys |
| W3 Ranked Pairs | DONE | 1,000 independent topological-reference profiles; local and production rendered journeys |
| W4 Majority Judgment | DONE | 82,993 exhaustive histogram pairs and 2,000 random literal-removal comparisons; rendered journeys |
| W5 release | DONE | Full integration checks, exact deployments, production API/browser/worker QA and healthy final smoke |

No reference disagreements remain. STAR's test-only reference is MIT-licensed
`starvote==2.1.5`; it is absent from production dependencies. Other references
are independently authored test oracles pinned by the method commits. See the
four `docs/phase109_*_backend_evidence.md` files for rules and measurements.

## Verification

Backend full regression: **3,602 passed / 21 skipped / zero failures** in
1,499.91 seconds with four pytest workers. The latest seven worker-helper tests
passed separately, giving **3,609 distinct passing cases**, **+365** from
Phase 108's 3,244. This is not a claim that one suite run executed 3,609 cases.
The optional STAR oracle skip was separately verified against 2,000 profiles;
other recorded environment skips remain. The interrupted sequential run is
not counted. Completed full suites were not repeated for the helper-only fix.

Frontend: **124 passed**, production build PASS, bundle `index-BYrMsS6k.js`.
Whole-phase ESLint's ten errors/one warning reproduce on baseline `0096997`;
no new findings remain. The focused Didit guard and all six guard tests pass.
Source/diff and independent integration review passed.

Migration `a109b0c1d2e3` above `f8a9b0c1d2e3` passed subprocess SQLite
upgrade/downgrade/upgrade and PostgreSQL 16 fresh/prior-head-upgrade smoke.
Production is on `a109b0c1d2e3`. No later method/helper patch adds a migration.
Each method passed 40 concurrent PostgreSQL HTTP/snapshot operations using
five connections, with no leaked connections, pool timeouts or waiting locks.
Actual option-add/close races passed for all four methods.

Pure-counter random-profile timings (Windows 10 build 19045, Python 3.12.13,
eight logical processors; prebuilt input excluded; zero SQL queries):

| Profile | STAR | Score | Ranked Pairs | Majority Judgment |
| --- | --- | --- | --- | --- |
| 1,000 ballots / 20 options | 10.4 ms | 10.6 ms | 31.0 ms | 9.3 ms |
| 10,000 / 20 | 103.1 ms | 106.2 ms | 314.0 ms | 88.3 ms |
| 1,000 / 120 | 55.0 ms | 56.5 ms | 1,024.2 ms | 48.1 ms |

The evidence files include allocations, query counts, delegation/concurrency
latencies and tied billion/trillion-weight profiles. Multiplying represented
weight by 1,000 does not expand ballots or scale runtime/memory by 1,000.
The 120-option Ranked Pairs case is substantially more costly; these local
measurements are not production throughput guarantees.

## Browser and production QA

All four methods passed local desktop/380px/keyboard/focus, cast/change/retract,
delegation, late options, explicit abstention, private early voting and admin
close/frozen-result journeys. Browser review fixed duplicate STAR results,
stale hidden preliminary ballots, scheduled dates displayed as close dates,
archived winners labeled provisional and archived write-in removal controls.
Corrected journeys were reverified. Local screenshots remain in
`test_results/phase109/`.

Production Chrome Person 1 reused the authenticated fictional owner session.
All four passed desktop and 380px ballot controls, keyboard selections, direct
cast/revote, late write-in creation, omission defaults, explicit abstention and
retraction restoring the whole delegate ballot. Ranked Pairs tied groups and
Move down changes persisted; its matrix/locking details were expanded. Score
and Majority Judgment keyboard checks observed both checked state and focus.
All four were closed through the actual Proposal Management UI, then their
final winners, method aggregates, actual dates, rule/commitment/seed reveal
and locked ballot/write-in controls were checked. Production screenshots are
`test_results/phase109/prod-*.jpg`; final/mobile pairs cover every method.
Long-page capture timed out for STAR; viewport captures supplied the evidence.

The one-shot production API driver passed parent/subgroup opt-ins, delegated
early votes, hidden early totals, neutral override, abstention/retraction,
late options, revoting, manual close, frozen rereads and post-close rejection
for all four methods. It was not rerun. Its isolated private org is
`phase109-release-qa-20261008` (`c562b775-95d8-4782-af79-423afb35b667`).
The two fictional non-platform-admin accounts have every notification channel
disabled. Only synthetic fixtures were changed; no real org policy or ballots
were mutated. Credentials remain outside the repository and report.

Scoped production worker verification passed on four exact additional fixtures:

| Method | Proposal ID | Outcome |
| --- | --- | --- |
| STAR | `3efcc6fc-4e84-4217-ae3a-902889ad386c` | passed, closed_on_time, one new audit, staging true, retry no-op |
| Score | `93686884-ce33-48d0-9dc9-b709acfdcd20` | passed, closed_on_time, one new audit, staging true, retry no-op |
| Ranked Pairs | `a304c2ef-516e-45e7-9840-7adbdb5e0a12` | passed, closed_on_time, one new audit, staging true, retry no-op |
| Majority Judgment | `c766766d-6399-4211-bab1-3de901195c19` | passed, closed_on_time, one new audit, staging true, retry no-op |

The first helper attempt rolled back: production `SessionLocal.autoflush=False`
left correctly staged audit rows pending before the helper counted them.
Fix `c754834` explicitly flushes the helper's transaction before assertion;
application behavior is unchanged. Seven tests mirror production's flush policy
and prove rollback after the second staged close and successful clean retry.
Before production retry, all four rows were read as voting/unfinalized with
one meaningful ballot each. After the patch deployed, the helper committed
all four together and verified frozen results, audit counts, staging and no-op
retry. The global worker tick was never invoked.

A STAR ballot refresh timed out during the rolling helper deployment; the
visible retry control recovered the saved ballot after deployment. Subsequent
journeys passed. This transient is recorded rather than treated as an app fix.

## Release and repository state

Live URL: https://www.liquiddemocracy.us/
Branch: `phase-109/experimental-single-winner-methods`, baseline `0096997`.
The dirty original planning checkout is preserved; integration used the isolated
detached checkout and normal no-ff merges. No reset, clean or force push.

| Release | Commit | Railway result |
| --- | --- | --- |
| Four-method application release | `09b9da0b56036ae81946d1eeeb409f98689bb1c8` | backend `321c6d2d-32fc-4af4-bd5e-ce5414563667` SUCCESS; frontend `0edea2f0-9438-4357-975b-7470e3cf0593` SUCCESS |
| Helper fix no-ff integration | `550a521d45bcb0c58c665411e9f40184cd12e8a1` | backend `639f499a-34cf-46d4-891b-5cfe660fca2b` SUCCESS |

Frontend appropriately skipped helper-only merge (`b48869a3-ee54-4e1d-8939-5e1b768041e6`)
and still serves `index-BYrMsS6k.js`. After browser/worker QA, homepage, health,
readiness and monitor returned HTTP 200; DB connected, monitor ok/no issues,
zero rolling 5xx and pool timeouts, pool occupancy 1/5. Documentation closeout
is integrated separately; it changes no watched service source.

Changed-file inventory: `docs/phase109_changed_files.txt`. Implementation and
integration commits through the helper release: `docs/phase109_commits.txt`.
This closeout's documentation commit/merge are reported in the visible final
response. Untracked full-suite logs/temp directories are preserved local
artifacts and excluded from commits.

## Remaining boundaries

No blocking defects remain in this phase. Existing immediate-email background
tasks are not a durable outbox; staged notification intent does not guarantee
immediate email delivery across crashes. Dense Ranked Pairs cost and existing
baseline lint/bundle warnings remain documented debt. No infrastructure,
secret/provider settings, paid capacity or destructive production cleanup was
changed. No production backfill was required or run.

Single-seat officeholder methods, multiwinner variants and custom scales are
**NOT STARTED**, as scoped by the spec. No automatic follow-up was scheduled.
