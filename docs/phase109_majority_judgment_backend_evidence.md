# Phase 109 W4 Majority Judgment backend evidence

Verified October 8, 2026. Synthetic data only. Windows 10 build 19045, Python 3.12.13, eight logical processors.

## Exact lower median and compact tie comparison

`majority_judgment_lower_median_v1` uses the six approved verbal grades. Codes express order, not additive scores. Every effective non-abstaining ballot contributes represented-member weight to each option's histogram, with omissions at Reject. Neutral ballots participate; abstentions are excluded from histograms. Original histograms and initial majority grades remain unchanged by tie comparison.

For N=2k sorted grades, repeated lower-median removal visits original positions k, k+1, k−1, k+2, and so on. For N=2k+1, it visits k+1 first, then k, k+2, k−1, k+3. Thus the sequence is an interleaving of the descending lower half and ascending upper half, preceded by the central item for odd N. Production encodes these halves as histogram runs and skips complete common pairs, eliminating candidates at the first differing median. Six bins produce at most eleven pair runs per candidate. The algorithm does not perform one iteration per share, including when medians alternate between two different grades for trillions of steps. Identical distributions use committed final priority.

The independent locally authored reference is `mj-literal-removal-v1` in `backend/tests/test_phase_109_majority_judgment.py`, pinned by the W4 commit. It expands only small synthetic test histograms, repeatedly selects the lower middle item, removes one item from each tied candidate, and repeats. No external dependency or borrowed code. Exhaustive comparison covers all 82,993 ordered pairs of six-bin histograms with equal totals one through five, including even totals. Another 2,000 randomized multi-candidate profiles up to 59 shares agree. A further 300 ballot profiles verify input-order and weighted-versus-expanded parity. Zero disagreements.

A stress fixture has a common alternating center pair repeated 10^30 times and differences only at the extremes. The implementation jumps those removals and selects the correct candidate; identical huge distributions terminate with final priority. The approved mean-versus-median, even-population and median-removal fixtures pass. Tiebreak traces report exact removals before the separating median, while displayed initial grades remain intact.

## Shared integration

Final focused run: 247 passing tests across all four counters, four-method stable-result/atomic close tests, real stored-ballot/frozen-read tests, shared contracts and org/sub-org scope. Lead's separate 14 MJ route tests passed. Counts overlap with earlier stage runs and are not a whole-suite count.

Additional cases cover whole-ballot relevance, owner weights, neutral/abstention overrides and withdrawal, late omitted Reject grades, malformed fields and type coercion, frozen histogram/grade/winner integrity, exact large-number transport, subgroup eligibility, foreign-org delegation exclusion, weighted/headcount modes, worker snapshot failure, bounded extensions and notification rollback/retry. Public grade codes remain integers; frequency/removal counts are exact decimal strings.

All four new methods are available for explicit organization opt-in; the default-enabled list remains unchanged. No W4 migration. Browser QA, final integration and deployment are separate lead-owned gates.

## Performance

Command: `python scripts/benchmark_phase109_star.py majority_judgment`. Prebuilt inputs excluded from peak allocation figures; zero SQL queries.

| Voters/options | Weight/profile | Time | Peak bytes |
| --- | --- | --- | --- |
| 1,000 / 20 | 1, random | 9.3 ms | 11,413 |
| 10,000 / 20 | 1, random | 88.3 ms | 16,045 |
| 1,000 / 120 | 1, random | 48.1 ms | 77,273 |
| 1,000 / 120 | billion, identical grades | 48.7 ms | 82,645 |
| 1,000 / 20 | billion, random | 9.3 ms | 17,569 |
| 1,000 / 20 | trillion, random | 9.4 ms | 17,569 |

Actual authenticated ASGI/PG16 load (`PHASE109_BENCHMARK_METHOD=majority_judgment python scripts/benchmark_phase109_pg.py`): 1,000 members, 20 options, 900 direct ballots, 100-node delegation graph; four concurrent HTTP requests plus a snapshot thread, connection pool two plus three overflow. All 40 operations succeeded. Uninstrumented wall time 5.11 s; cast p50/p95 636/1,012 ms, result 673/1,017 ms, snapshot 283/319 ms. Query counts 23/13/12. Peak checked-out connections five, returned to zero; no waiting locks or idle transactions over five seconds.

Separate `PHASE109_TRACE_MEMORY=YES` run: all 40 succeeded; 16,411,004-byte peak allocation, 12.95 s instrumented wall time. This latency is not a normal request measurement. Both disposable containers were removed. These bounded local measurements are not production throughput guarantees.

## Actual option-add/close races, all four methods

The PostgreSQL benchmark now performs a separate concurrent add-option request and close request for each of STAR, Score, Ranked Pairs and Majority Judgment. In this run, each addition acquired the serialization lock first (201), then close completed (200). Each frozen label set and method aggregate option set exactly matched current database options, including the new option. Each close produced one status audit and recorded notification staging. A subsequent add after close returned 400 for every method. This verifies actual PostgreSQL row-lock serialization; it is separate from the measured 40-operation workload and does not claim both lock orders happened in this one run.

Existing immediate-email background-task durability limitations documented in W1 remain unchanged.
