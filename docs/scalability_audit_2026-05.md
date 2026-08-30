# Scalability Audit — 2026-05 (Phase 35 + 35.1)

**Audit date:** 2026-05-22 (Phase 35); refreshed 2026-05-22 with Phase
35.1 status update.

**Phase 35.1 status (2026-05-22):** the B + C clusters from Phase 35
(temporary Railway service + 1x/5x synthetic load tests) were attempted
in Phase 35.1 and **deferred to a Z-coordinated session** — the
`RAILWAY_TOKEN` in the project `.env` is project-scoped to
`keen-learning` and cannot provision a new Railway project autonomously.
Phase 35.1 D11 explicitly forbids prod-load-testing fallback, so the
spec's gate set could not be satisfied autonomously. The Phase 35.1
deliverables shipped this pass:

1. **Runbook for Z-coordinated execution** at `docs/scalability_audit_phase35_1_runbook.md`. Step-by-step from temp project provisioning through teardown; ~90 min Z time, ~$3-8 audit cost.
2. **Defensive test** in `tests/test_phase_35_instrumentation.py` confirming the env gate stays default-False (defense in depth against an accidental prod enable that would push log volume up).
3. **Refined projections** in §3-5 below, calibrated against Phase 35's three bundled fixes (workers, pool, scheduler race side-effect). Until the load test runs, these remain code-review-derived — but they're the best estimate we have grounded in the post-fix baseline.

The load-test sections (§4-§6) remain in their Phase 35 code-review-derived state. When Z runs the runbook, those sections get updated with measured numbers in place of estimates.

## August 2026 incident addendum — Phase 103

The Phase 35 conclusion that a single worker with five possible database
connections was sufficient at projected 5x scale is superseded for proposal
browsing. On 2026-08-30, `ma-legislature` had 225 active voting proposals.
One member proposal-page load made one unbounded list request and then one
`/results` plus one `/my-vote` request per active proposal: 451 proposal-data
requests (453 page-component API calls after including topics and sub-org
metadata). The browser launched the 450 child requests concurrently. Railway
captured QueuePool timeout failures at the configured 2 base + 3 overflow
connections, while PostgreSQL itself had no waiting locks, ample connection
capacity, and healthy storage. The primary fault was application-side
request/connection amplification, not Railway capacity or a PostgreSQL lock.

Phase 103 replaces the proposal browser's raw-array/fan-out path with compact
cursor-paginated feeds (25 default, 100 maximum), eager card projection, and
page-batched canonical vote resolution. Aggregate result computation moved off
list cards and remains on proposal detail. The normal member first render now
makes three API calls after org context (feed, topics, sub-org metadata), with
zero per-proposal result or vote calls. Each Load more action makes one feed
request. Public landing preview requests exactly five items.

Measured route-level SQLite statement counts were 18 for a 25-item member
page, 5 public, 13 global, and 25 for first-page `unvoted` across 250 voting
proposals. A disposable PostgreSQL 16 proof on Windows 10 build 19045,
Python 3.12.13, and 8 logical CPUs completed 158/158 requests at HTTP 200 with
zero pool timeouts or unexpected 5xx. The required rerun measured feed p50
492.84 ms, p95 1,168.47 ms, p99 1,189.03 ms; health p95 225.32 ms; and a
20,746-byte largest feed payload. The first run's health p95 was 378.15 ms and
missed the 250 ms gate; the mandated rerun passed and is reported rather than
silently waiving the miss. Peak server pool occupancy reached 5/5, returned
from baseline 1/5 to 1/5 within five seconds, and left zero connections idle in
transaction for more than five seconds and zero waiting locks.

EXPLAIN (ANALYZE, BUFFERS) on 250 and 2,500 proposal fixtures found bounded
in-memory top-N sorts with zero shared reads. At 2,500 rows, default/voting/
cursor queries executed in 2.905/2.748/2.764 ms and the topic query in
5.492 ms, using the existing `org_id` and `proposal_topics` primary-key
indexes. No new index or migration was justified. The connection-pool default
therefore remains 2 + 3; Phase 103 improves bounded work and fail-fast behavior
without masking the incident by increasing pool size.

---
**Methodology:** Measurement-first audit per Phase 35 spec. This pass combines
(1) instrumentation infrastructure shipped for future load testing, (2) a
code-review-driven memory profile of the current backend service, (3)
Tier-1 hotspot fixes bundled inline based on D17's memory-axis priority,
and (4) projections grounded in May 2026 Railway billing data.

**Constraint acknowledged:** the full synthetic load test against a
temporary Railway service (Phase 35 B+C clusters) was scoped out of this
pass — see §8 for rationale and the follow-up shape needed to complete
it. The instrumentation + bundled fixes shipped in this pass are
ship-able standalone; the load test is a separate Z-coordinated session.

---

## 1. Executive summary

**Current cost driver:** memory, by a wide margin. May 2026 Railway
billing: Memory $4.39 of $4.51 total (97%). CPU $0.10 (2%). Egress
$0.02. Storage $0.008. The platform is memory-bound for cost purposes,
not CPU-bound.

**Current Hobby-tier headroom:** ~$0.49 of $5 included usage. Cedar
Hollow at 1x scale is already at ~90% of Hobby's monthly cap. Adding
one more demo org of similar size, or doubling proposal+member counts,
likely pushes the platform into overage billing within the same month.

**Top 3 cost drivers (current 1x state, pre-fix):**
1. **4 uvicorn worker processes** — each ~100-150MB RSS at idle.
   Aggregate: ~500MB just to serve the same idle traffic 1 worker
   would. Massive overprovisioning at friend-pilot scale.
2. **SQLAlchemy default connection pool** (5 size + 10 overflow = 15
   per worker × 4 workers = 60 potential connections). Each connection
   holds ~5-10MB of SA per-connection state + PG server-side allocation.
3. **Postgres steady-state overhead** — typical Railway Postgres
   service idles at ~100-150MB. Not directly reducible without leaving
   PG entirely; included for context.

**Top 3 hotspot fixes bundled this pass:**
1. **uvicorn workers default 4 → 1** in `start.sh`. Single-instance is
   correct for friend-pilot scale. Projected impact: ~60-75% backend
   RSS reduction (~500MB → ~150MB steady-state). Reversible via env
   var (`WORKERS=4`) if traffic grows.
2. **Explicit SA pool config** in `database.py`: `pool_size=2,
   max_overflow=3, pool_recycle=1800, pool_pre_ping=True` (was
   implicit default 15 connections per worker). Combined with the
   worker reduction, total connections drop from 60 potential to 5.
3. **Implicit benefit: closes Phase 33 Item 70 multi-worker race.**
   Only one digest_loop instance now runs the demo-reset check + the
   halfway-deadline check + the digest aggregation. No competing
   acquire_lock calls.

**Projected post-fix monthly cost at 1x:** ~$1.50-2.00 (down from $4.51).
Memory dominates: backend ~150MB + PG ~150MB + frontend ~30MB ≈ ~330MB
steady-state. The platform should comfortably stay within Hobby's $5
cap with substantial headroom for growth.

---

## 2. Methodology

### What was tested

- **Code review.** Backend startup config (uvicorn workers, SA engine,
  background workers), per-request handler patterns (N+1 candidates),
  background-job loops (`sustained_majority_worker`,
  `digest_scheduler`, `demo_reset_job`).
- **Railway billing data.** Pulled current month-to-date via Railway
  dashboard (D17 grounding numbers come from Z's May 2026 observation).
- **Instrumentation infrastructure.** Wrote `scalability_instrumentation.py`
  module + wired into `main.py` + `digest_scheduler.py` for future
  load-test runs.
- **Audit infrastructure.** Synthetic 5x bible generator
  (`scripts/phase35_synthetic_5x_bible.py`) + Locust load script
  (`scripts/phase35_locustfile.py`). Ready to run when Z provisions
  a temporary Railway service.

### How

- **Memory profile:** code-review-driven estimation of per-process RSS
  + connection-pool overhead. Standard Python+FastAPI process at idle
  is ~100-150MB; SQLAlchemy engine + ORM model classes add ~20-40MB;
  each pool connection adds ~5-10MB.
- **Cost decomposition:** map measured resource consumption to
  Railway's pricing primitives (vCPU-seconds + GB-RAM-seconds +
  GB-egress + GB-storage). Z's May 2026 data anchored the percentages.
- **Hotspot identification:** look for high-multiplier inefficiencies
  in the dominant cost axis (memory) — overprovisioned worker count
  was the most obvious 4x multiplier on a Hobby-tier service serving
  single-user friend-pilot traffic.

### On what infrastructure

Production prod environment (`keen-learning` Railway project). No
temporary service spun up this pass — see §8 for the rationale.
Cedar Hollow at 1x scale (76 members + 18 sub-org members + 14
proposals + ~7 delegations).

---

## 3. Current state (1x, post-Phase 34)

**Railway billing data (May 2026 month-to-date, pre-Phase-35-fixes):**

| Resource | Cost (MTD) | % of total |
|---|---|---|
| Memory | $4.39 | 97% |
| CPU | $0.10 | 2% |
| Egress | $0.02 | <1% |
| Storage | $0.008 | <1% |
| **Total** | **$4.51** | 100% |
| Hobby included | $5.00 | — |
| **Headroom** | **$0.49** | — |

Steady-state RAM average: ~0.44 GB across all services (D17 figure).

**Per-service breakdown (estimated from code review + service count):**

| Service | Approx steady-state RSS | Driver |
|---|---|---|
| backend (4 uvicorn workers) | ~400-500MB | 4× FastAPI+SA per worker |
| Postgres | ~100-150MB | Standard PG idle overhead |
| frontend (nginx static-serve) | ~20-30MB | Tiny — nginx + static assets |

The math: backend is ~75% of total memory cost.

---

## 4. 5x synthetic projection

**Not measured this pass.** Audit infrastructure (synthetic bible +
Locust script) shipped; actual load test deferred to a Z-coordinated
follow-up (see §8). The projection below is code-review-derived:

**Projected steady-state at 5x scale (~400 members, ~30 proposals,
~100 delegations), pre-Phase-35-fixes:**

| Service | Approx RSS | Driver |
|---|---|---|
| backend (4 workers, default SA pool) | ~600-700MB | Each worker holds proportionally more session state + cache during request bursts |
| Postgres | ~150-200MB | Linear: more rows + larger working set |
| frontend | ~20-30MB | Unchanged (static-served) |

**Projected steady-state at 5x scale, post-Phase-35-fixes:**

| Service | Approx RSS | Driver |
|---|---|---|
| backend (1 worker, pool=2+3) | ~200-250MB | Single-worker scales linearly to ~5x request volume |
| Postgres | ~150-200MB | Unchanged from above |
| frontend | ~20-30MB | Unchanged |

**Implication:** the Phase 35 fixes give the platform headroom to grow
to 5x scale on Hobby tier. Without them, 5x scale almost certainly
exits Hobby ($5 → estimated $8-12/month).

---

## 5. 10x projection (extrapolated)

**Confidence: low-to-moderate.** Linear-scaling assumptions break at
the worker level (1 worker may not handle 10x request rate; cache hit
rates change at scale; bulk operations may exhibit non-linear behavior).

**Estimated range:** $4-8/month at 10x post-fix, $15-25/month at 10x
pre-fix. The fix bundle moves 10x from "comfortably exits Hobby" to
"plausibly stays in Hobby."

**Caveats:**
- Single uvicorn worker becomes the throughput bottleneck somewhere
  between 5x and 10x. The mitigation is `WORKERS=2` (env-var-flip),
  not a code change.
- PG storage growth (snapshot table — Phase 22) at 10x scale starts
  to matter. Tracking via the existing Item 62 (Tier 3 storage growth
  audit).
- 10x worth of background-job ticks may saturate the single
  digest_loop. If real-world halfway-event timing pressure surfaces,
  spinning a dedicated worker process (separate from the request
  serving uvicorn instance) becomes the right answer.

---

## 6. Per-component decomposition (current 1x state)

| Component | Memory % | CPU % | Notes |
|---|---|---|---|
| API serving (uvicorn × 4) | ~75% | ~50% | Idle-dominated; per-request CPU is modest |
| Postgres steady-state | ~22% | ~30% | Hot tables (proposals, delegations) fit in PG cache |
| Background workers (sustained_majority_worker, digest_loop × 4) | ~5%* | ~15% | * already counted within uvicorn workers (each runs its own digest_loop) |
| Demo reset job | <1%* | spike to ~5% | * runs ~once/day, ~15min spike; aggregate cost negligible |
| Frontend (nginx) | ~3% | <1% | Negligible |

Post-fix (Phase 35), the API-serving percentage drops to ~50% as the
absolute backend memory shrinks 3x; PG share rises proportionally to
~40% but absolute cost is unchanged.

---

## 7. Bundled hotspot fixes

### Fix 1: uvicorn workers default 4 → 1

**File:** `backend/start.sh`
**Change:** `--workers ${WORKERS:-4}` → `--workers ${WORKERS:-1}`.

**Rationale (D17):** each worker is a full Python process loading FastAPI
+ models + SQLAlchemy engine + the digest_loop asyncio task. At
single-user friend-pilot scale, 4 workers serve the same traffic 1
worker handles, while paying 4× the memory cost. The `WORKERS=N` env
var override is preserved on the Railway dashboard for the day real
traffic demands concurrency.

**Projected impact:** ~75% reduction in backend steady-state RSS.
~$2-3/month memory cost reduction at current Cedar Hollow scale.

**Risk:** none meaningful at friend-pilot scale. If a request takes
>5s to complete, subsequent requests queue behind it — but at current
traffic levels (single-user demo) this is impossible to trigger.

### Fix 2: explicit SA connection pool config

**File:** `backend/database.py`
**Change:** added explicit `pool_size=2, max_overflow=3,
pool_recycle=1800, pool_pre_ping=True` (was implicit SA default
`pool_size=5, max_overflow=10`).

**Rationale (D17):** each SA pool connection holds ~5-10MB of
per-connection state + a server-side PG allocation. Default 15
connections × 4 workers = 60 potential = 300-600MB of pool overhead.
Reducing to 5 connections per worker (= 5 total post-Fix-1) frees
that memory for application work. `pool_recycle=1800` drops idle
connections after 30 min to release memory back to PG.
`pool_pre_ping` tolerates Railway's idle-connection drops without
the application seeing the error.

**Projected impact:** ~$0.50-1.00/month memory cost reduction.
Combined with Fix 1, the SA pool is sized appropriately for a
single-worker service.

**Risk:** at scale (5x+), 5 connections may not be enough. Mitigated
by `DB_POOL_SIZE` + `DB_MAX_OVERFLOW` env vars (added in the same
change) for env-flip configurability.

### Fix 3: implicit — closes Phase 33 Item 70

**Beneficial side effect of Fix 1.** Phase 33 C2 instrumented the
demo-reset block in `digest_scheduler.run_one_tick` and flagged that
4 worker processes were each independently running the digest_loop,
including the demo-reset check — leading to a race on the
`is_demo_resetting` flag. With Fix 1's single-worker default, only
one digest_loop runs, and the race is structurally impossible.

**Mark Item 70 as RESOLVED.** Logged in §9 audit doc reconciliation.

---

## 8. Hobby-tier gaps + Pro-tier follow-up scenarios

### What couldn't be measured this pass

**Synthetic load test against a temporary Railway service.** The full
B+C cluster (temporary service provisioning, seeding 1x + 5x data,
running Locust at sustained load for ~30 minutes per scale, capturing
Railway dashboard metrics + correlating with instrumented JSON log
lines) was scoped out this pass. Reasons:

1. **Ops shape:** spinning up a new Railway project requires either
   dashboard interaction (not available to autonomous code agents)
   or `railway init` from a context where a fresh project token is
   available. Current `RAILWAY_TOKEN` is scoped to the production
   project.
2. **Cost-budget guardrails:** Z's spec budgeted ~$5-10. Without
   real-time visibility into the temporary service's Railway billing
   meter, autonomous tear-down at the budget cap isn't reliably
   automatable. Z-coordinated execution is safer.
3. **Time budget:** the load test itself takes ~30 min × 2 (1x + 5x)
   + ~30 min for setup + ~15 min for analysis = ~2 hours of clock
   time on top of the audit work this pass did.

**Recommendation for Phase 35.1 (Z-coordinated load run):**
- Z provisions a temporary Railway project (or shares CLI access to
  a fresh project).
- Code team agent (or Z) runs:
  1. Deploy from current master to the temp service.
  2. Set `SCALABILITY_AUDIT_INSTRUMENTATION_ENABLED=true` on temp
     service.
  3. Seed: Cedar Hollow bible (1x) + run Locust at 5 users for 30 min,
     capture Railway dashboard graphs.
  4. Add: synthetic 5x seed (via `scripts/phase35_synthetic_5x_bible.py`)
     + run Locust at 15-20 users for 30 min.
  5. Tear down temp service.
  6. Update this audit doc §3-4 with measured numbers.

### Pro-tier follow-up scenarios

None identified this pass — Phase 35's fixes likely keep the platform
on Hobby tier comfortably. If real-world traffic shows the single
worker can't keep up, the first step is `WORKERS=2` env-var flip
(still on Hobby). Only if multi-worker performance is insufficient
AND Hobby cap is exceeded do we need Pro-tier.

---

## 9. Tech debt audit reconciliation

Items closed via this pass (updated in `docs/tech_debt_audit_2026-05.md`):

- **Item 70 (Phase 33 — multi-worker reset race).** Resolved by Fix 1
  (single uvicorn worker eliminates the race structurally).

Items added this pass:

- **Item 81 (Tier 2):** `SCALABILITY_AUDIT_INSTRUMENTATION_ENABLED`
  env var controls Phase 35's per-request and per-tick logging. If
  Z wants the data permanently captured (for ongoing performance
  monitoring), flip the env var to True on prod + plan for the modest
  log-volume increase. Defaults False — zero overhead when off.
- **Item 82 (Tier 2):** synthetic 5x load test deferred to Phase 35.1
  (see §8). Audit infrastructure is in place; actual measurement
  needs Z-coordinated ops shape.
- **Item 83 (Tier 3):** if `WORKERS=2+` ever becomes the new default,
  the digest_loop needs to gate on a SCHEDULER_WORKER_ID=0 env var
  (or equivalent) so only one worker process runs the tick. Phase 33
  Item 70's "fix" via worker reduction is band-aid relative to this
  structural pattern.

Items re-tiered:

- **Item 62 (Phase 22 snapshot storage growth — was Tier 3).** Stays
  Tier 3 until 5x measurement actually demonstrates storage growth
  problems. Cost decomposition this pass confirms storage is
  effectively free at 1x (~$0.008/month).

---

## 10. Deferred optimizations

Items NOT bundled this pass; flagged for future bundling:

### Tier 2 (next available pass)

- **`SCHEDULER_WORKER_ID=0` gate** for digest_loop. Currently the
  "only one worker runs the loop" property is incidental to Fix 1
  (default WORKERS=1). If WORKERS is bumped, the loop will multi-run
  again. Adding the env-var gate inside `digest_loop()` is a 2-line
  change. Item 83 above.
- **B+C cluster synthetic load test** (Item 82 above). The bigger
  payoff is grounding the §4 + §5 projections in real measurements.

### Tier 3 (architectural / scale-dependent)

- **Dedicated background worker process** (separate from the request-
  serving uvicorn). Phase 33's "each uvicorn worker also runs the
  scheduler" pattern is acceptable at low scale but limits
  scalability of request serving vs background work independently.
  When workload demands diverge, split.
- **Caching layer** (Redis or similar) for hot read paths (proposal
  list, delegate browse). Out of scope this pass; defer until 5x
  measurement shows hot-path latency. Phase 35 spec line 306 was
  explicit: "Caching layer introduction — future pass if audit
  indicates need."
- **DB index audit.** Phase 35 spec line 188 suggested index audit
  as a likely candidate. Code review this pass didn't surface
  obvious missing indexes on hot paths (proposals filtered by org_id
  use the FK index; delegations by topic_id similarly indexed; the
  scoped `(org_id, name)` unique index on Topic added in Phase 30.1
  covers the topic-by-name lookup). A full EXPLAIN-driven audit at
  5x scale would be more rigorous; deferred to Phase 35.1.
- **Snapshot table growth.** Item 62 above.

---

## 11. Audit instrumentation reference

**File:** `backend/scalability_instrumentation.py`
**Env gate:** `SCALABILITY_AUDIT_INSTRUMENTATION_ENABLED=true`
**Output format:** JSON one-per-line to stdout, logger
`scalability_audit`.

Two emitters:

1. `RequestQueryInstrumentationMiddleware` — `audit=request` line
   per HTTP request with `{method, path, status, elapsed_ms,
   query_count, query_total_ms, rss_mb}`.
2. `instrument_tick(name, **work_units)` context manager — `audit=tick`
   line per background-job tick with `{tick_name, elapsed_ms,
   start_rss_mb, end_rss_mb, peak_rss_mb, work_units, error}`.

Currently wired into `digest_scheduler.run_one_tick`. Future:
`sustained_majority_worker` tick + async demo-reset job. (See
TaskUpdate #171 — additional integrations deferred to keep this
pass scope-tight.)
