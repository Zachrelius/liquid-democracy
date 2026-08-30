#!/usr/bin/env python3
"""Deterministic Phase 103 PostgreSQL fixture, EXPLAIN, and load proof.

This tool refuses SQLite and known Railway hosts.  Point DATABASE_URL at a
disposable, migrated local PostgreSQL database, then run:

  python backend/scripts/phase103_feed_load.py seed
  python backend/scripts/phase103_feed_load.py explain
  python backend/scripts/phase103_feed_load.py load --base-url http://127.0.0.1:8000

Use ``seed --voting-count 2500`` for the separate query-plan-scale fixture.
No production proposal titles, users, ballots, or tokens are read or printed.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timedelta
import json
import math
import os
import platform
from pathlib import Path
import sys
import time
import uuid

import httpx
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import auth
from database import SessionLocal, engine
import models
from role_seed import seed_default_roles_for_org


NS = uuid.UUID("9eb9142c-2028-5103-8103-000000000103")
ORG_ID = str(uuid.uuid5(NS, "org"))
ORG_SLUG = "phase103-load-fixture"


def stable_id(label: str) -> str:
    return str(uuid.uuid5(NS, label))


def assert_disposable_postgres() -> None:
    url = str(engine.url).lower()
    if not url.startswith("postgresql"):
        raise SystemExit("Refusing: DATABASE_URL must be disposable PostgreSQL (not SQLite).")
    if any(marker in url for marker in ("railway.app", "railway.internal", "rlwy.net")):
        raise SystemExit("Refusing known Railway host. This tool must never load production.")
    if os.environ.get("PHASE103_DISPOSABLE_DB") != "YES":
        raise SystemExit("Set PHASE103_DISPOSABLE_DB=YES to acknowledge the disposable local DB.")


def seed(voting_count: int) -> dict:
    assert_disposable_postgres()
    db = SessionLocal()
    try:
        if db.get(models.Organization, ORG_ID) is not None:
            raise SystemExit(f"Fixture {ORG_SLUG} already exists; use a fresh disposable database.")
        org = models.Organization(
            id=ORG_ID, name="Phase 103 Load Fixture", slug=ORG_SLUG,
            discoverability="listed", activity_visibility="public",
            join_policy="invite", settings={"private": False},
        )
        db.add(org)
        db.flush()
        roles = seed_default_roles_for_org(db, ORG_ID)
        users = []
        for index in range(100):
            user = models.User(
                id=stable_id(f"user-{index}"), username=f"phase103_load_{index:03d}",
                display_name=f"Load Member {index:03d}",
                email=f"phase103-{index:03d}@load-proof.example.org", email_verified=True,
                password_hash=auth.hash_password("phase103-disposable-only"),
                is_admin=(index == 0),
            )
            users.append(user)
            db.add(user)
            db.add(models.OrgMembership(
                id=stable_id(f"membership-{index}"), user_id=user.id, org_id=ORG_ID,
                role_id=roles["member"].id, status="active", voting_weight=(index % 7) + 1,
            ))
        topics = []
        for index in range(5):
            topic = models.Topic(
                id=stable_id(f"topic-{index}"), org_id=ORG_ID,
                name=f"Load Topic {index}", color=f"#{index + 1:02x}5577",
            )
            topics.append(topic)
            db.add(topic)
        db.flush()

        methods = ("binary", "approval", "ranked_choice", "budget_allocation", "budget_project")
        base = datetime(2026, 8, 30, 12, 0)
        proposals = []
        for index in range(voting_count):
            method = methods[index % len(methods)]
            proposal = models.Proposal(
                id=stable_id(f"proposal-voting-{index}"), title=f"Synthetic Proposal {index:04d}",
                body="Deterministic disposable load fixture.", author_id=users[index % 100].id,
                org_id=ORG_ID, status="voting", voting_method=method,
                created_at=base - timedelta(minutes=index % 17),
                updated_at=base, voting_start=base - timedelta(days=1),
                voting_end=base + timedelta(days=(index % 7) + 1),
            )
            proposals.append(proposal)
            db.add(proposal)
            db.add(models.ProposalTopic(
                proposal_id=proposal.id, topic_id=topics[index % 5].id,
                relevance=1.0,
            ))
            # Two compact options keep option_count and mixed-method payloads
            # production-shaped without importing real content.
            for option_index in range(2):
                db.add(models.ProposalOption(
                    id=stable_id(f"option-{index}-{option_index}"),
                    proposal_id=proposal.id,
                    label=f"Synthetic option {option_index + 1}",
                    description="Disposable load-fixture option.",
                    display_order=option_index,
                ))
        for status, count in (("deliberation", 8), ("passed", 4), ("failed", 4), ("withdrawn", 4)):
            for index in range(count):
                db.add(models.Proposal(
                    id=stable_id(f"proposal-{status}-{index}"), title=f"Synthetic {status} {index}",
                    body="Deterministic disposable load fixture.", author_id=users[index].id,
                    org_id=ORG_ID, status=status, voting_method="binary",
                    created_at=base - timedelta(days=index), updated_at=base - timedelta(hours=index),
                ))
        db.flush()

        # The load viewer has both an org-wide fallback and a higher-priority
        # topic-specific delegation; direct ballots below override both.
        db.add_all([
            models.Delegation(
                id=stable_id("delegation-viewer-global"),
                delegator_id=users[0].id, delegate_id=users[40].id,
                org_id=ORG_ID, topic_id=None, chain_behavior="accept_sub",
            ),
            models.Delegation(
                id=stable_id("delegation-viewer-topic"),
                delegator_id=users[0].id, delegate_id=users[41].id,
                org_id=ORG_ID, topic_id=topics[0].id, chain_behavior="accept_sub",
            ),
            models.TopicPrecedence(
                id=stable_id("precedence-viewer-topic"), user_id=users[0].id,
                topic_id=topics[0].id, priority=0,
            ),
        ])

        for user_index in range(1, 40):
            delegate_index = 40 + (user_index % 20)
            db.add(models.Delegation(
                id=stable_id(f"delegation-{user_index}"),
                delegator_id=users[user_index].id, delegate_id=users[delegate_index].id,
                org_id=ORG_ID, topic_id=None, chain_behavior="accept_sub",
            ))
        # Explicit two-hop chain; several delegates intentionally never vote.
        db.add(models.Delegation(
            id=stable_id("delegation-two-hop"), delegator_id=users[60].id,
            delegate_id=users[61].id, org_id=ORG_ID, topic_id=None,
            chain_behavior="accept_sub",
        ))
        # Defensive cycle fixture (direct DB seed); the pure resolver must
        # terminate and report unvoted rather than recurse or leak a ballot.
        db.add_all([
            models.Delegation(
                id=stable_id("delegation-cycle-a"), delegator_id=users[90].id,
                delegate_id=users[91].id, org_id=ORG_ID, topic_id=None,
                chain_behavior="accept_sub",
            ),
            models.Delegation(
                id=stable_id("delegation-cycle-b"), delegator_id=users[91].id,
                delegate_id=users[90].id, org_id=ORG_ID, topic_id=None,
                chain_behavior="accept_sub",
            ),
        ])
        db.add(models.Delegation(
            id=stable_id("delegation-two-hop-final"), delegator_id=users[61].id,
            delegate_id=users[62].id, org_id=ORG_ID, topic_id=None,
            chain_behavior="accept_sub",
        ))
        for proposal_index, proposal in enumerate(proposals):
            method = proposal.voting_method
            voter_indexes = list(range(40, 80))
            if proposal_index % 10 == 0:
                voter_indexes.append(0)  # direct-vote precedence for load viewer
            for user_index in voter_indexes:
                if (proposal_index + user_index) % 4:
                    continue
                ballot = None
                value = None
                if method == "binary":
                    value = ("yes", "no", "abstain")[(proposal_index + user_index) % 3]
                elif method == "approval":
                    ballot = {"approvals": [stable_id(f"option-{proposal_index}-0")]}
                elif method == "ranked_choice":
                    ballot = {"ranking": [stable_id(f"option-{proposal_index}-0"), stable_id(f"option-{proposal_index}-1")]}
                elif method == "budget_allocation":
                    ballot = {"allocations": {stable_id(f"option-{proposal_index}-0"): 25.0}}
                else:
                    ballot = {"ranked": [{"option_id": stable_id(f"option-{proposal_index}-0"), "tier_id": None}]}
                db.add(models.Vote(
                    id=stable_id(f"vote-{proposal_index}-{user_index}"),
                    proposal_id=proposal.id, user_id=users[user_index].id,
                    cast_by_id=users[user_index].id, vote_value=value, ballot=ballot,
                    is_direct=True,
                ))
        db.commit()
        return {
            "org_slug": ORG_SLUG, "voting_proposals": voting_count,
            "representative_non_voting": 20, "members": 100,
            "methods": list(methods), "fixture": "deterministic_uuid5",
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def explain() -> dict:
    assert_disposable_postgres()
    db = SessionLocal()
    try:
        topic_id = stable_id("topic-0")
        queries = {
            "default": ("WHERE org_id = :org AND status <> 'withdrawn'", {}),
            "voting": ("WHERE org_id = :org AND status = 'voting'", {}),
            "topic": (
                "JOIN proposal_topics pt ON pt.proposal_id = proposals.id "
                "WHERE org_id = :org AND pt.topic_id = :topic", {"topic": topic_id},
            ),
            "cursor_next": (
                "WHERE org_id = :org AND status = 'voting' AND "
                "(COALESCE(voting_end, TIMESTAMP '9999-12-31 23:59:59') > :voting_end OR "
                " (COALESCE(voting_end, TIMESTAMP '9999-12-31 23:59:59') = :voting_end AND created_at < :created_at) OR "
                " (COALESCE(voting_end, TIMESTAMP '9999-12-31 23:59:59') = :voting_end AND created_at = :created_at AND id > :proposal_id))",
                {"voting_end": datetime(2026, 8, 31, 12), "created_at": datetime(2026, 8, 30, 12),
                 "proposal_id": stable_id("proposal-voting-0")},
            ),
        }
        order = """ORDER BY
          CASE WHEN status='voting' THEN 0 WHEN status='deliberation' THEN 1
               WHEN status IN ('passed','failed','withdrawn','unresolved','expired_unsigned') THEN 2 ELSE 3 END,
          CASE WHEN status='voting' THEN COALESCE(voting_end, TIMESTAMP '9999-12-31 23:59:59')
               ELSE TIMESTAMP '9999-12-31 23:59:59' END,
          CASE WHEN status='deliberation' THEN created_at
               WHEN status IN ('passed','failed','withdrawn','unresolved','expired_unsigned') THEN COALESCE(updated_at,created_at)
               ELSE created_at END DESC,
          created_at DESC, id ASC LIMIT 26"""
        output = {}
        def plan_nodes(node):
            rows = []
            if node.get("Node Type") in {"Sort", "Incremental Sort", "Seq Scan", "Index Scan", "Index Only Scan", "Bitmap Heap Scan"}:
                rows.append({
                    "node": node.get("Node Type"), "relation": node.get("Relation Name"),
                    "index": node.get("Index Name"), "sort_key": node.get("Sort Key"),
                    "actual_rows": node.get("Actual Rows"), "rows_removed": node.get("Rows Removed by Filter"),
                    "shared_hit_blocks": node.get("Shared Hit Blocks"),
                    "shared_read_blocks": node.get("Shared Read Blocks"),
                })
            for child in node.get("Plans", []):
                rows.extend(plan_nodes(child))
            return rows
        for name, (where, extra) in queries.items():
            plan = db.execute(
                text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT proposals.* FROM proposals {where} {order}"),
                {"org": ORG_ID, **extra},
            ).scalar_one()
            root = plan[0]["Plan"] if isinstance(plan, list) else plan
            output[name] = {
                "planning_ms": plan[0].get("Planning Time") if isinstance(plan, list) else None,
                "execution_ms": plan[0].get("Execution Time") if isinstance(plan, list) else None,
                "root_node": root.get("Node Type"),
                "actual_rows": root.get("Actual Rows"),
                "shared_hit_blocks": root.get("Shared Hit Blocks"),
                "shared_read_blocks": root.get("Shared Read Blocks"),
                "scan_sort_nodes": plan_nodes(root),
                "plan": root,
            }
        return output
    finally:
        db.close()


async def load(base_url: str, clients: int) -> dict:
    assert_disposable_postgres()
    token = auth.create_access_token(stable_id("user-0"))
    headers = {"Authorization": f"Bearer {token}"}
    latencies: dict[str, list[float]] = {}
    statuses = Counter()
    payload_sizes = []
    failures = []
    fixture_db = SessionLocal()
    try:
        expected_ids = {
            row.id for row in fixture_db.query(models.Proposal.id).filter(
                models.Proposal.org_id == ORG_ID,
                models.Proposal.status != "withdrawn",
            ).all()
        }
    finally:
        fixture_db.close()

    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
        async def request(label: str, path: str, *, authenticated=True):
            started = time.perf_counter()
            response = await client.get(path, headers=headers if authenticated else None)
            latencies.setdefault(label, []).append((time.perf_counter() - started) * 1000)
            statuses[response.status_code] += 1
            if response.status_code >= 500:
                failures.append({"label": label, "status": response.status_code})
            if "proposal-feed" in path:
                payload_sizes.append(len(response.content))
            return response

        async def pool_component():
            response = await client.get("/api/health/monitor")
            try:
                return response.json().get("components", {}).get("database_pool", {})
            except Exception:
                return {}

        pool_baseline = await pool_component()
        pool_samples = [pool_baseline.get("checked_out")]
        stop_sampling = asyncio.Event()

        async def sample_pool():
            while not stop_sampling.is_set():
                component = await pool_component()
                pool_samples.append(component.get("checked_out"))
                try:
                    # Coarse sampling only: the monitor is itself DB-backed,
                    # so a 50ms poll would materially distort the load under
                    # measurement. Two samples/second is enough to catch peaks
                    # across the repeated 20-client bursts.
                    await asyncio.wait_for(stop_sampling.wait(), timeout=0.5)
                except asyncio.TimeoutError:
                    pass

        sampler = asyncio.create_task(sample_pool())

        # Filters and sequential cursor traversal (duplicate/missing proof).
        for status in ("all", "voting", "unvoted", "deliberation", "passed", "failed", "archived"):
            response = await request("filter", f"/api/orgs/{ORG_SLUG}/proposal-feed?status={status}")
            response.raise_for_status()
        seen = []
        cursor = None
        while True:
            suffix = f"&cursor={cursor}" if cursor else ""
            response = await request("traversal", f"/api/orgs/{ORG_SLUG}/proposal-feed?limit=25{suffix}")
            response.raise_for_status()
            body = response.json()
            seen.extend(item["proposal"]["id"] for item in body["items"])
            if not body["has_more"]:
                break
            cursor = body["next_cursor"]

        await asyncio.gather(*[
            request("member_20", f"/api/orgs/{ORG_SLUG}/proposal-feed") for _ in range(clients)
        ])
        mixed = (
            (f"/api/orgs/{ORG_SLUG}/proposal-feed", True, "mixed_member"),
            (f"/api/orgs/{ORG_SLUG}/public/proposal-feed", False, "mixed_public"),
            (f"/api/orgs/{ORG_SLUG}/proposal-feed?status=unvoted", True, "mixed_unvoted"),
            ("/api/health", False, "health"),
            ("/api/health/ready", False, "readiness"),
        )
        await asyncio.gather(*[
            request(mixed[index % len(mixed)][2], mixed[index % len(mixed)][0],
                    authenticated=mixed[index % len(mixed)][1])
            for index in range(clients)
        ])
        for _cycle in range(5):
            await asyncio.gather(*[
                request("cycles", f"/api/orgs/{ORG_SLUG}/proposal-feed?status={('all','voting','unvoted')[index % 3]}")
                for index in range(clients)
            ])
        stop_sampling.set()
        await sampler
        await asyncio.sleep(5)
        pool_post = await pool_component()

    db = SessionLocal()
    try:
        activity = db.execute(text("""
            SELECT state, count(*) FROM pg_stat_activity
            WHERE datname=current_database() AND pid <> pg_backend_pid()
            GROUP BY state
        """)).all()
        idle_old = db.execute(text("""
            SELECT count(*) FROM pg_stat_activity
            WHERE datname=current_database() AND state='idle in transaction'
              AND now() - state_change > interval '5 seconds'
        """)).scalar_one()
        waiting_locks = db.execute(text("""
            SELECT count(*) FROM pg_locks WHERE NOT granted
        """)).scalar_one()
    finally:
        db.close()

    def percentile(values, p):
        ordered = sorted(values)
        return round(ordered[min(len(ordered) - 1, math.ceil(p * len(ordered)) - 1)], 2) if ordered else None

    all_feed = [value for key, values in latencies.items() if "health" not in key and key != "readiness" for value in values]
    health_values = latencies.get("health", [])
    valid_pool_samples = [int(value) for value in pool_samples if value is not None]
    missing_ids = sorted(expected_ids - set(seen))
    unexpected_ids = sorted(set(seen) - expected_ids)
    return {
        "runtime": {
            "python": platform.python_version(), "platform": platform.platform(),
            "processor": platform.processor(), "cpu_count": os.cpu_count(),
            "clients": clients,
        },
        "requests": sum(statuses.values()), "statuses": dict(statuses),
        "unexpected_5xx": len(failures), "failure_samples": failures[:10],
        "traversal": {
            "rows": len(seen), "unique": len(set(seen)), "expected": len(expected_ids),
            "duplicates": len(seen)-len(set(seen)), "missing": len(missing_ids),
            "unexpected": len(unexpected_ids),
        },
        "feed_latency_ms": {
            "p50": percentile(all_feed, .50), "p95": percentile(all_feed, .95), "p99": percentile(all_feed, .99),
        },
        "health_p95_ms": percentile(health_values, .95),
        "max_feed_payload_bytes": max(payload_sizes, default=0),
        "pool": {
            "baseline": pool_baseline,
            "peak_checked_out": max(valid_pool_samples, default=None),
            "samples": len(valid_pool_samples),
            "post_5s": pool_post,
        },
        "post_load": {
            "pg_states": dict(activity), "idle_in_transaction_over_5s": int(idle_old),
            "waiting_locks": int(waiting_locks),
        },
    }


def main_cli() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    seed_parser = sub.add_parser("seed")
    seed_parser.add_argument("--voting-count", type=int, default=250, choices=(250, 2500))
    sub.add_parser("explain")
    load_parser = sub.add_parser("load")
    load_parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    load_parser.add_argument("--clients", type=int, default=20)
    args = parser.parse_args()
    if args.command == "seed":
        result = seed(args.voting_count)
    elif args.command == "explain":
        result = explain()
    else:
        result = asyncio.run(load(args.base_url.rstrip("/"), args.clients))
    print(json.dumps(result, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main_cli()
