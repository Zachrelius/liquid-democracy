"""Disposable PG16 bounded STAR route/tally/snapshot concurrency smoke.

Creates its own local container and destroys only that generated container.
Run from backend: python scripts/benchmark_phase109_pg.py
Uses in-process ASGI HTTP, real authentication/dependency/route/PG paths and a
parallel worker thread; it is not a production or external-network load test.
"""
import asyncio
from collections import Counter
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import platform
import random
import subprocess
import sys
import threading
import time
import tracemalloc
from uuid import uuid4

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def child():
    if os.environ.get("PHASE109_DISPOSABLE") != "YES" or not os.environ["DATABASE_URL"].startswith("postgresql://smoke:smoke@localhost:55519/"):
        raise SystemExit("Refusing any database except the generated local fixture")
    import httpx
    from sqlalchemy import event, text
    import auth
    from database import Base, engine, SessionLocal
    import models
    from main import app
    from role_seed import seed_default_roles_for_org
    from sustained_majority_service import capture_snapshot
    from experimental_voting import lock_proposal
    from voting_methods import new_voting_rules

    logging.disable(logging.CRITICAL)
    Base.metadata.create_all(engine)
    rng = random.Random(109)
    with SessionLocal() as db:
        org = models.Organization(name="Phase109 synthetic", slug="phase109-pg-benchmark",
                                  settings={"allowed_voting_methods": ["star"]})
        db.add(org); db.flush()
        roles = seed_default_roles_for_org(db, org.id)
        users = [models.User(id=str(uuid4()), username=f"p109_{i}", display_name=f"Synthetic {i}", email=f"p109_{i}@demo.example",
                             password_hash="synthetic-no-login", email_verified=True) for i in range(1000)]
        db.add_all(users); db.flush()
        db.add_all([models.OrgMembership(org_id=org.id, user_id=u.id, role_id=roles["member"].id,
                                        status="active") for u in users])
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        proposal = models.Proposal(title="Synthetic STAR concurrency", body="Synthetic",
                                   org_id=org.id, author_id=users[0].id, voting_method="star",
                                   status="voting", voting_start=now, voting_end=now+timedelta(days=1))
        db.add(proposal); db.flush()
        proposal.voting_rules = new_voting_rules("star", proposal.id)
        options = [models.ProposalOption(proposal_id=proposal.id, label=f"Option{i}") for i in range(20)]
        db.add_all(options); db.flush()
        option_ids = [o.id for o in options]
        # 100-node deep graph preserves existing two-hop accept_sub policy.
        for i in range(100, 200):
            db.add(models.Delegation(org_id=org.id, delegator_id=users[i].id,
                                     delegate_id=users[i+1].id, chain_behavior="accept_sub"))
        db.add_all([models.Vote(proposal_id=proposal.id, user_id=u.id, cast_by_id=u.id,
                               is_direct=True, ballot={"scores": {oid: rng.randrange(6) for oid in option_ids}})
                    for i, u in enumerate(users) if not 100 <= i < 200])
        proposal_id = proposal.id
        token = auth.create_access_token(users[0].id)
        db.commit()

    counts = ContextVar("phase109_queries", default=None)
    @event.listens_for(engine, "before_cursor_execute")
    def count_query(*_):
        counter = counts.get()
        if counter is not None:
            counter[0] += 1

    metrics = []
    samples = []
    stop = threading.Event()
    def sample_pool():
        while not stop.wait(0.01):
            samples.append(engine.pool.checkedout())
    sampler = threading.Thread(target=sample_pool, daemon=True)
    sampler.start()

    async def load():
        gate = asyncio.Semaphore(4)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver",
                                    headers={"Authorization": f"Bearer {token}"}) as client:
            async def request(i):
                async with gate:
                    counter = [0]
                    reset = counts.set(counter)
                    start = time.perf_counter()
                    kind = "vote" if i % 2 == 0 else "tally"
                    path = f"/api/proposals/{proposal_id}"
                    try:
                        if kind == "vote":
                            response = await client.post(path+"/vote", json={"scores": {option_ids[0]: 5, option_ids[1]: i % 5}})
                        else:
                            response = await client.get(path+"/results")
                        metrics.append(dict(kind=kind, seconds=time.perf_counter()-start,
                                            status=response.status_code, queries=counter[0]))
                        if response.status_code != 200:
                            raise AssertionError(f"Unexpected {kind} status {response.status_code}: {response.text[:200]}")
                    finally:
                        counts.reset(reset)

            def snapshot(i):
                counter = [0]
                reset = counts.set(counter)
                start = time.perf_counter()
                try:
                    with SessionLocal() as db:
                        proposal = db.get(models.Proposal, proposal_id)
                        lock_proposal(db, proposal)
                        capture_snapshot(db, proposal)
                        db.commit()
                    metrics.append(dict(kind="snapshot", seconds=time.perf_counter()-start,
                                        status=200, queries=counter[0]))
                finally:
                    counts.reset(reset)

            async def snapshots():
                for i in range(8):
                    await asyncio.to_thread(snapshot, i)
                    await asyncio.sleep(0.02)
            await asyncio.gather(*(request(i) for i in range(32)), snapshots())

    trace_memory = os.environ.get("PHASE109_TRACE_MEMORY") == "YES"
    if trace_memory:
        tracemalloc.start()
    started = time.perf_counter()
    try:
        asyncio.run(load())
    finally:
        stop.set(); sampler.join()
    elapsed = time.perf_counter()-started
    peak = None
    if trace_memory:
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    checked_out_after = engine.pool.checkedout()
    with engine.connect() as connection:
        waiting = connection.execute(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock'")).scalar()
        idle = connection.execute(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND state='idle in transaction' AND now()-xact_start > interval '5 seconds'")).scalar()
    summary = {}
    for kind in ("vote", "tally", "snapshot"):
        rows = [r for r in metrics if r["kind"] == kind]
        times = sorted(r["seconds"] for r in rows)
        summary[kind] = {"count": len(rows), "p50_ms": round(times[len(times)//2]*1000, 2),
                         "p95_ms": round(times[min(len(times)-1, int(len(times)*0.95))]*1000, 2),
                         "max_queries": max(r["queries"] for r in rows),
                         "min_queries": min(r["queries"] for r in rows)}
    report = {"python": platform.python_version(), "platform": platform.platform(),
              "logical_processors": os.cpu_count(), "fixture": "1000 members/20 options/900 direct ballots/100-node delegation graph",
              "seconds": round(elapsed, 2), "tracemalloc_enabled": trace_memory, "peak_load_bytes": peak,
              "pool_capacity": 5, "peak_checked_out": max(samples or [0]),
              "checked_out_after": checked_out_after, "waiting_locks_after": waiting,
              "idle_in_transaction_over_5s_after": idle,
              "statuses": dict(Counter(str(r["status"]) for r in metrics)), "operations": summary}
    assert checked_out_after == 0 and waiting == 0 and idle == 0
    print(json.dumps(report, indent=2))
    engine.dispose()


if __name__ == "__main__":
    if "--child" in sys.argv:
        child()
    else:
        from pg_smoke import _pg_container
        with _pg_container(port=55519) as (_, url):
            env = {**os.environ, "DATABASE_URL": url, "PHASE109_DISPOSABLE": "YES",
                   "DB_POOL_SIZE": "2", "DB_MAX_OVERFLOW": "3", "DB_POOL_TIMEOUT_SECONDS": "5",
                   "RESEND_API_KEY": "", "SMTP_HOST": "", "LOG_LEVEL": "ERROR"}
            subprocess.run([sys.executable, __file__, "--child"], env=env, cwd=BACKEND, check=True, timeout=180)
