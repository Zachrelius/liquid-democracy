# Phase 109 W0/W1 backend evidence

Recorded October 8, 2026. This records completed backend checks, not completion
of the full W1 gate or release authorization. Rendered browser QA and the lead's
complete API/privacy matrix remain separate gates. No production data was used.

## Foundation

- W0 commit `c9c837b`: registry separates default legacy methods from planned
  experiments; no experiment is released by this commit. Protected random rules,
  public allowlist projection, strict stored/input ballot validation, nullable
  proposal fields, reversible migration.
- Prior Alembic head verified as `f8a9b0c1d2e3`; new revision `a109b0c1d2e3`.
- W0 helper suite: 56 passed, including subprocess SQLite upgrade/downgrade/upgrade.
- PostgreSQL 16 `pg_smoke.py --mode both --prior-revision f8a9b0c1d2e3` passed
  fresh and bootstrap-over-shaped upgrade paths. Disposable containers removed.
  Initial sandbox Docker denial was resolved through approved escalation.

## STAR counter, delegation and stability

- W1 commit `8edd136`, supplemented by `f82de7f`.
- STAR hand counts, exact large integers, abstention/neutral distinction,
  direct override/retraction, represented-member weights, frozen real-model
  final records, snapshot persistence, worker finalization/retry audit checks.
- Additional regressions cover whole-ballot relevance resolution, a 100-node
  delegation graph preserving the existing direct-or-one-sub-delegate policy,
  late-option zero defaults without rewriting saved ballots, malformed ballots
  and corrupted final records. Deep graphs do not enable unlimited delegation.
- STAR suite 23 passed, stability suite 11 passed. Earlier broader compatibility
  run: 144 passed across STAR/stability, legacy SRR/worker, deadline close,
  relevance and weighted voting. Seven later STAR cases separately pass.
- Pure counters issue zero database queries and never expand voting shares.
- New snapshots keep exact experimental counts in JSON. Legacy PG int32 count
  columns are zero placeholders; experimental readers use the JSON payload.
- Stability requires a sample at/before the window boundary, consistent winner
  and option-set version, meaningful result, quorum, and no arbitrary-priority
  dependence. Missing/incompatible data fails closed.
- Final reads restore persisted aggregates without resolving current voters or
  weights. Seed disclosure belongs to the finalized aggregate, never ordinary
  rules metadata. Output integer conversion preserves bools and exact counts.

## Independent reference

Pinned reference: `starvote==2.1.5`, Larry Hastings, MIT license. Downloaded into
an ignored local validation directory, not added as a runtime dependency. No
reference implementation source was copied into production.

`test_phase_109_star_reference.py` compares 2,000 seeded synthetic profiles with
2-8 options, 1-12 weighted input ballots, weights 1-4 and all 0-5 ratings. Small
reference inputs alone expand shares. The reference receives the same candidate
priority order as the committed platform draw, avoiding unrelated lottery
differences. All comparisons passed, including after tie-count optimization.

The platform's explicit no-result rules for all-bottom ballots, no positive
preference weight and fewer than two options intentionally differ from the
reference and have independent hand-expected tests.

Reproduce with an isolated pip target and `STARVOTE_REFERENCE_PATH` pointing to
it, then run `pytest tests/test_phase_109_star_reference.py`. The optional test
skips without that package; this document records an actual successful run.

## Pure-counter performance

Windows 10 build 19045, Python 3.12.13, eight logical processors. Processor model
was not exposed in the process environment. Deterministic random seed 109.
`backend/scripts/benchmark_phase109_star.py` separates uninstrumented timing
from an allocation-traced repeat; memory below excludes already-built inputs.

| Voters | Options | Weight | Profile | Time | Peak counter bytes |
| --- | --- | --- | --- | --- | --- |
| 1,000 | 20 | 1 | Random | 10.4 ms | 476,137 |
| 10,000 | 20 | 1 | Random | 103.1 ms | 5,180,353 |
| 1,000 | 120 | 1 | Random | 55.0 ms | 3,370,257 |
| 1,000 | 120 | 1 billion | All tied | 77.8 ms | 3,387,538 |
| 1,000 | 20 | 1 billion | Random | 12.2 ms | 480,941 |
| 1,000 | 20 | 1 trillion | Random | 11.2 ms | 480,541 |

Initial all-tie 120-option counting took 1.45 seconds. Replacing repeated
pairwise comparisons with a fixed six-bin frequency sum reduced that to 77.8ms
while preserving exact preference sums and all reference outcomes. A 1,000-fold
increase in share magnitude did not produce proportional time or memory growth.

## PostgreSQL route/snapshot concurrency

`backend/scripts/benchmark_phase109_pg.py` creates and removes its own local
PostgreSQL 16 container at port 55519. It refuses nonfixture URLs. Fixture:
1,000 synthetic members, 20 options, 900 direct ballots, 100-node delegation
graph. Four concurrent in-process ASGI requests plus a separate snapshot thread;
real authentication, route dependencies and DB sessions; no app startup workers.
Pool configuration 2 base + 3 overflow, five-second checkout timeout.

| Operation | Count | p50 | p95 | SQL statements per operation |
| --- | --- | --- | --- | --- |
| Cast/change vote | 16 | 571.07 ms | 905.24 ms | 21 |
| Read result tally | 16 | 567.81 ms | 911.96 ms | 13 |
| Capture locked snapshot | 8 | 239.59 ms | 335.45 ms | 12 |

Uninstrumented run took 4.46 seconds; 40/40 operations succeeded, no error or
pool timeout. Peak occupancy was 5/5; all connections returned (zero checkouts).
Post-run queries found zero waiting locks and zero transactions idle >5 seconds.

Separate allocation-traced run: 40/40 success, 13.36 seconds, 13,022,999 peak
load bytes. Its approximately two-second request p95 includes tracing overhead
and is not substituted for the uninstrumented numbers above. Set
`PHASE109_TRACE_MEMORY=YES` to reproduce that measurement.

The first seed attempt failed before load because the synthetic user omitted a
required display name; the fixture was corrected and that container removed.
Both measured containers also removed on completion. No external email or
identity-provider calls, production load, infrastructure changes, or secrets.

These bounded local results do not establish internet latency, Railway capacity,
multi-instance safety, or an indefinite sustained-load guarantee.
