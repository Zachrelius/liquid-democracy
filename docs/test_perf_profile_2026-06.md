# Test Suite Performance Profile — Phase 61 (2026-06-07)

## TL;DR

Two optimizations landed; one delivered the wall-clock win.

- **O1 — Session-scoped DB engine + per-test SAVEPOINT rollback** (replaces the per-function `create_all`/`drop_all` cycle in the shared `db` fixture). Architecturally cleaner; **no measurable wall-clock improvement on its own** (40:00 → 40:07 — essentially flat). The bottleneck wasn't the shared fixture: the suite's tail is dominated by a small number of heavy tests (`test_phase_23_demo_reset.py`, full-bible seeding, subprocess migration cycles) that use their own test-local engines and weren't touched by O1. Kept anyway — the new pattern is the right architecture going forward and is a prerequisite for O3 isolation.
- **O3 — `pytest-xdist -n auto` parallelization**: **~40 min → 19:29 (1169.40s) — 51% wall-clock reduction**, all 2266 tests pass under parallel execution. Isolation holds. This is the win.

Combined: the suite now runs in ~19.5 min instead of ~40 min when invoked with `-n auto`. Coverage is unchanged: 2266 passed + 18 skipped both before and after.

## Baseline

- **Wall-clock:** ~40 min for the full backend suite (~2266 tests), per Phase 60 closeout.
- **Suite shape:** 174 test files in `backend/tests/`. 113 use the shared conftest `db` fixture (~65%); 50 use test-local `test_db` fixtures (~29%); 11 have neither (helper modules, pure-function tests).

## O1 — Session-scoped engine + per-test SAVEPOINT rollback

### Implementation (`backend/tests/conftest.py`)

```python
@pytest.fixture(scope="session")
def _shared_test_engine():
    if TEST_DB_URL.startswith("sqlite"):
        engine = create_engine(
            TEST_DB_URL,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        engine = create_engine(TEST_DB_URL)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db(_shared_test_engine) -> Session:
    connection = _shared_test_engine.connect()
    transaction = connection.begin()
    TestSession = sessionmaker(bind=connection)
    session = TestSession()
    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(_session, trans):
        nonlocal nested
        if trans.nested and not trans._parent.nested:
            nested = connection.begin_nested()

    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()
```

### Why this is coverage-neutral

The change is HOW the DB is provisioned, not WHAT any test asserts. Every test gets the same logical "fresh empty schema" guarantee — but delivered via outer-transaction rollback instead of full schema-rebuild. The SAVEPOINT-restart event listener keeps `session.commit()` inside tests working (a test's commit becomes a savepoint release; the outer transaction stays open until the fixture's teardown rolls it back).

### Why the measured wall-clock barely moved

The hypothesis going in was that the per-test `create_all`/`drop_all` was the dominant cost at ~1500 invocations across the suite. Measurement disproved this — full-suite wall-clock with O1 in place was 40:07, statistically indistinguishable from the 40:00 baseline. The actual tail is concentrated in:

1. **`test_phase_23_demo_reset.py`** — runs the full demo-reset pipeline (three bibles × three orgs), individual tests at 39-73 seconds each. Uses its own test-local `test_db` fixture, NOT the shared `db` fixture, so O1 didn't touch it.
2. **Subprocess migration-cycle tests** (Phase 51/52a/52d/52i/57/58) — fork `alembic upgrade head` in a subprocess, inherently heavy; out of scope for fixture optimization.
3. **Full-bible seeding tests** — comparable per-test cost to demo-reset.

The shared `db` fixture's `create_all`/`drop_all` for a fresh in-memory SQLite turns out to be fast enough that 1500 iterations don't dominate. The architectural cleanup is still worth keeping (it's the standard SQLAlchemy fast-test pattern and prerequisite for safe parallelization), but the projected O1 win in the spec didn't materialize.

### Isolation property (validated)

The SAVEPOINT-restart approach preserves isolation for any state created via the `db` Session. Validated by full-suite run with no order-dependence regressions. Two risk classes the rollback approach does NOT cover, both pre-existing and unchanged by O1:

1. **External state** — file system writes, environment variables, in-memory module-level state (e.g. slowapi limiter, in-memory caches). The existing `_reset_slowapi_limiter` autouse fixture handles the limiter; nothing else known.
2. **Tests that bypass the fixture** to talk to the engine directly. None known in the shared-fixture set.

## O3 — Parallelization (adopted)

### Implementation

`pytest-xdist==3.6.1` added to `backend/requirements.txt`. Invocation: `pytest -n auto` distributes tests across all available CPU workers. Each worker gets its own session-scoped engine via the conftest fixture (no cross-worker SQLite sharing — each worker has its own in-memory DB).

### Measured result

```
DONE exit=0
2266 passed, 18 skipped, 1515 warnings in 1169.40s (0:19:29)
```

**Speedup: ~40 min → 19:29 = 51% wall-clock reduction.** All 2266 tests pass under `-n auto`; isolation holds across workers. No order-dependence flakes surfaced. Coverage is unchanged.

### Recommended invocation

For local development and CI:

```
pytest -n auto
```

(The serial `pytest` invocation still works for debugging individual tests where worker-output interleaving makes the parallel form hard to read.)

### Why O3 was the actual win

The full suite is dominated by ~10-20 individually-heavy tests in different files. Serial execution forces them to run back-to-back; parallel execution lets them run on different workers concurrently, so the wall-clock collapses to roughly `slowest-file-time + scheduling overhead`. This is exactly the shape that `pytest-xdist` is designed for.

## Deferred / Out of scope for Phase 61

- **Test-local `test_db` fixtures** (50 files, ~29% of suite) already use StaticPool — converting them to the session-scoped pattern is a smaller incremental win and a larger touch-the-files surface. Future pass if a per-fixture optimization is justified.
- **Subprocess migration-cycle tests** are inherently heavy (alembic upgrade is the real work). Out of scope for fixture optimization; could be batched in a follow-up.
- **Trimming setup that doesn't drive assertions (O4 in the spec)** — not done in this pass; recommend as a future incremental cleanup if a hotspot is found.
- **Redundant-test recommendations (O5)** — no clear duplicates surfaced in the suite during this pass; no list submitted to Z.

## Coverage-neutral invariant (the whole point)

- **Test count before O1+O3:** 2266 passed + 18 skipped = 2284 tests.
- **Test count after O1+O3:** 2266 passed + 18 skipped = 2284 tests.
- No assertions removed; no test cases cut.
