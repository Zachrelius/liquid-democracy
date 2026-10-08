# Phase 109 W3 Ranked Pairs backend evidence

Verified October 8, 2026. Synthetic ballots only. Environment: Windows 10 build 19045, Python 3.12.13, eight logical processors.

## Rule and verification

`ranked_pairs_margins_v1` counts each represented member's whole ranking using that member's effective weight. Equal groups are tied; omitted options are tied below all listed groups. Victories sort by descending margin, descending winning support, then committed winner/loser priority. Incremental bitset reachability rejects cycle-closing edges. All options remain graph nodes; multiple sources use final priority. Any consulted equal-strength edge priority is disclosed and disqualifies that snapshot from early stable closure.

The independent locally authored reference is `rp-margins-topological-oracle-v1` in `backend/tests/test_phase_109_ranked_pairs.py`, pinned by the W3 commit. It sums each ordered candidate pair independently and tests prospective graphs with Kahn topological elimination, rather than production's incremental reachability. No external counting dependency or borrowed code. Under controlled lexical final priority, 1,000 deterministic synthetic profiles agree on matrix, accepted edges, rejected edges and winner. Reversed input order, small share-expansion parity and the Condorcet-winner property also pass.

Hand fixtures include the approved 3/2/2 cycle, equal-strength cycle, tied ranks, incomplete rankings, balanced strict preferences, and a separate equal-margin/different-support example proving that support takes precedence over final priority. Empty/all-tied rankings are neutral; all-abstain and zero-power cases do not invent a winner. Strict opposing preferences whose aggregate pairwise counts balance remain a meaningful final tie.

Focused run: 206 passing across Ranked Pairs API/counting, STAR/Score counters, three-method SRR and shared contracts. Six additional real-database scope tests pass: subgroup membership excludes parent-only and unrelated members; foreign-org delegation is ignored; parent weights and one-per-member mode are respected; valid subgroup delegation carries the owner's weight. Additional RP fixtures cover relevance selection, existing two-hop chain limits and direct neutral/abstain overrides.

Frozen records validate the matrix bounds, diagonal, voting-power limits, no-result reason and version. Full production records rebuild the graph from frozen matrix and committed rules/seed to verify the recorded edge order, lock decisions, sources and winner. They do not reread current ballots or memberships. Real-model frozen reads and atomic worker notification failure/rollback/retry pass for all three methods. Defaults remain unchanged; Majority Judgment remains unavailable. No W3 migration.

## Counter performance

Command: `python scripts/benchmark_phase109_star.py ranked_pairs`. Inputs prebuilt; peaks are incremental counter allocations; zero SQL queries. Matrix construction is O(ballots × candidates²); share magnitude does not expand ballots. There is no enumeration of tie permutations.

| Voters/options | Weight/profile | Time | Peak bytes |
| --- | --- | --- | --- |
| 1,000 / 20 | 1, random tied groups | 31.0 ms | 142,389 |
| 10,000 / 20 | 1, random tied groups | 314.0 ms | 147,781 |
| 1,000 / 120 | 1, random tied groups | 1,024.2 ms | 5,587,905 |
| 1,000 / 120 | billion, all victory strengths tied | 960.2 ms | 5,190,773 |
| 1,000 / 20 | billion, random | 33.0 ms | 149,897 |
| 1,000 / 20 | trillion, random | 33.3 ms | 149,897 |

The benchmark's `all_tie` Ranked Pairs profile uses identical complete rankings: every victory has the same strength, stressing all edge-priority comparisons and dense graph locking. It does not mean an all-equal neutral ranking, which would exit without graph construction.

## PostgreSQL contention

`PHASE109_BENCHMARK_METHOD=ranked_pairs python scripts/benchmark_phase109_pg.py` runs actual authenticated in-process ASGI casts/results and a concurrent snapshot worker against disposable local PostgreSQL 16. Fixture: 1,000 members, 20 options, 900 direct ballots, a 100-node delegation graph; four HTTP tasks plus one worker, pool two plus three overflow, five-second pool timeout.

Uninstrumented run: all 40 operations returned 200, total 7.59 s. Cast p50/p95 904/1,356 ms, result 911/1,351 ms, snapshot 346/478 ms. Query counts: cast 22–23, result 13, snapshot 12. Peak connections five, returned to zero, no remaining waiting locks or idle transactions over five seconds. This run preceded the rank-lookup optimization measured in the pure table above.

Separate optimized run with `PHASE109_TRACE_MEMORY=YES`: all 40 passed; 22,854,375-byte peak allocations, 26.12 s instrumented wall time. Instrumented latency is not normal request latency. Both disposable containers were removed.

These are bounded local measurements, not a production SLA. The 120-option case is substantially more costly than 20 options; avoid claiming equal capacity across option counts. Rendered QA, final whole-pass regression and deployment remain separate lead-owned gates. Existing immediate-email background-task durability limitations remain unchanged.
