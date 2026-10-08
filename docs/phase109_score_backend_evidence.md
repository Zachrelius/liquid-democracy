# Phase 109 W2 Score backend evidence

Verified October 8, 2026, on Windows 10 build 19045, Python 3.12.13, eight logical processors. Synthetic ballots only; no production data or services.

## Counting and integration

Score uses `score_0_5_sum_v1`: highest weighted total, then committed candidate priority on equal maxima. It reuses rating aggregation, whole-ballot delegation, represented-member weights, no-result guards and final-record transport. It has no STAR runoff or five-star tiebreak. The approved 3 A5/B4 plus 2 B4/C5 fixture gives A15/B20/C10 and elects B.

Independent reference is the locally authored `score-sum-oracle-v1` test in `backend/tests/test_phase_109_score.py`, pinned to its W2 Git revision. It sums candidate columns independently and compares 2,000 deterministic synthetic profiles, controlled lexical priority ties, reversed input order and small weight expansion. No external dependency or borrowed implementation. Zero disagreements. STAR's separate pinned starvote 2.1.5 comparison also passed after the shared aggregation change.

Final focused run: 106 passing tests across Score counting, STAR counting, both methods' Stable Result Required worker paths, and Score API integration. Earlier registry/STAR API run: 93 passing; STAR reference plus legacy RCV: 44 passing; early override/archive regression cases: 7 passing. Counts overlap and should not be added as a unique whole-suite total.

Coverage includes empty/neutral/abstaining ballots, late-option omitted zeros and common denominators, large integer transport, exact quorum, delegation overrides/retraction/relevance/deep chain behavior, real stored JSON, frozen reads after membership changes, contradictory persisted method/rule metadata, bounded extensions without snapshot history, atomic notification failure rollback and retry. Registry exposes Score while default-enabled methods remain the five legacy methods. No W2 migration; W0 migration verification remains applicable.

## Pure-counter measurements

Command: `python scripts/benchmark_phase109_star.py score`. Counter-only timings; zero SQL queries. Peak allocations exclude prebuilt inputs.

| Voters/options | Weight/profile | Time | Peak bytes |
| --- | --- | --- | --- |
| 1,000 / 20 | 1, random | 10.6 ms | 476,137 |
| 10,000 / 20 | 1, random | 106.2 ms | 5,180,353 |
| 1,000 / 120 | 1, random | 56.5 ms | 3,370,257 |
| 1,000 / 120 | billion, all tied | 60.1 ms | 3,375,061 |
| 1,000 / 20 | billion, random | 11.3 ms | 480,541 |
| 1,000 / 20 | trillion, random | 11.3 ms | 480,541 |

Multiplying weight magnitude by 1,000 did not increase allocations or measured runtime; no expansion into per-share ballots occurs.

## Real PostgreSQL concurrency

`PHASE109_BENCHMARK_METHOD=score python scripts/benchmark_phase109_pg.py` provisions and tears down a disposable local PostgreSQL 16 container. Fixture: 1,000 members, 20 options, 900 direct ballots and a 100-node delegation graph. Four concurrent authenticated in-process ASGI requests plus a snapshot thread; 16 casts, 16 result reads and eight captures. Pool configured at two connections plus three overflow, five-second acquisition timeout.

All 40 operations returned 200. Wall time 5.19 s; maximum checked-out connections five, returned to zero. No remaining waiting locks or idle transactions over five seconds. Latency p50/p95: cast 589/996 ms, result 592/1,210 ms, snapshot 218/292 ms. SQL counts: cast 23, result 13, snapshot 12. A second uninstrumented run also passed (5.08 s).

A separate run with `PHASE109_TRACE_MEMORY=YES` passed all 40 operations with 18,726,381 bytes peak traced allocations; wall time 13.22 s. Instrumentation timings are not normal request-latency measurements. Every generated container was removed.

This is a bounded local contention smoke, not a production throughput SLA or external-network benchmark. W2 rendered QA, broader final regression, and deployment are separate lead-owned gates. Existing immediate-email background-task durability limitations documented in W1 remain unchanged.
