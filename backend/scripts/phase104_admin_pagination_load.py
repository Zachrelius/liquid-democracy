#!/usr/bin/env python3
"""Deterministic Phase 104 PostgreSQL fixture, plans, and load proof.

The command refuses SQLite, known Railway hosts, and any run without the
explicit disposable-database acknowledgement. Typical local use is::

    python backend/scripts/phase104_admin_pagination_load.py seed --count 250
    python backend/scripts/phase104_admin_pagination_load.py load
    python backend/scripts/phase104_admin_pagination_load.py explain

Use a fresh database and ``seed --count 2500`` for the plan-scale proof.
No production data is read or printed.
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
from sqlalchemy import cast, func, literal_column, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import load_only

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import auth
from database import SessionLocal, engine
import models
from proposal_management import structural_eligibility_predicate
from proposal_pagination import (
    created_after_cursor,
    proposal_after_cursor,
    proposal_ordering,
    proposal_row_key,
)
from role_seed import seed_default_roles_for_org


NS = uuid.UUID("9eb9142c-2028-5103-8104-000000000104")
ORG_ID = str(uuid.uuid5(NS, "parent-org"))
ORG_SLUG = "phase104-load-fixture"
PUBLIC_SUB_ID = str(uuid.uuid5(NS, "public-sub-org"))
PUBLIC_SUB_SLUG = "phase104-public-sub"
PRIVATE_SUB_ID = str(uuid.uuid5(NS, "private-sub-org"))
PRIVATE_SUB_SLUG = "phase104-private-sub"
POLIS_ZERO_ID = str(uuid.uuid5(NS, "polis-zero"))
POLIS_ONE_ID = str(uuid.uuid5(NS, "polis-one"))
POLIS_25_ID = str(uuid.uuid5(NS, "polis-25"))
POLIS_MANY_ID = str(uuid.uuid5(NS, "polis-many"))


def stable_id(label: str) -> str:
    return str(uuid.uuid5(NS, label))


def assert_disposable_postgres() -> None:
    url = str(engine.url).lower()
    if not url.startswith("postgresql"):
        raise SystemExit("Refusing: DATABASE_URL must be disposable PostgreSQL.")
    if any(marker in url for marker in ("railway.app", "railway.internal", "rlwy.net")):
        raise SystemExit("Refusing known Railway host; never load production.")
    if os.environ.get("PHASE104_DISPOSABLE_DB") != "YES":
        raise SystemExit("Set PHASE104_DISPOSABLE_DB=YES for a disposable local DB.")


def seed(count: int) -> dict:
    """Seed exactly *count* mixed proposals with deterministic UUID5 keys."""
    assert_disposable_postgres()
    db = SessionLocal()
    try:
        if db.get(models.Organization, ORG_ID) is not None:
            raise SystemExit(f"Fixture {ORG_SLUG} exists; use a fresh database.")
        parent = models.Organization(
            id=ORG_ID,
            name="Phase 104 Load Fixture",
            slug=ORG_SLUG,
            join_policy="invite",
            discoverability="listed",
            activity_visibility="public",
            settings={"private": False},
        )
        public_sub = models.Organization(
            id=PUBLIC_SUB_ID,
            name="Phase 104 Public Sub-org",
            slug=PUBLIC_SUB_SLUG,
            parent_org_id=ORG_ID,
            settings={"private": False},
        )
        private_sub = models.Organization(
            id=PRIVATE_SUB_ID,
            name="Phase 104 Private Sub-org",
            slug=PRIVATE_SUB_SLUG,
            parent_org_id=ORG_ID,
            settings={"private": True},
        )
        db.add_all([parent, public_sub, private_sub])
        db.flush()
        roles = seed_default_roles_for_org(db, ORG_ID)

        viewer = models.User(
            id=stable_id("viewer"),
            username="phase104_load_admin",
            display_name="Phase 104 Load Admin",
            email="phase104-load-admin@example.invalid",
            email_verified=True,
            password_hash=auth.hash_password("disposable-only"),
            is_admin=True,
        )
        db.add(viewer)
        db.add(models.OrgMembership(
            id=stable_id("viewer-parent-membership"),
            user_id=viewer.id,
            org_id=ORG_ID,
            role_id=roles["steward"].id,
            status="active",
        ))
        db.add(models.SubOrgMembership(
            id=stable_id("viewer-private-membership"),
            user_id=viewer.id,
            sub_org_id=PRIVATE_SUB_ID,
            role_id=roles["steward"].id,
            status="active",
        ))

        polises = (
            (POLIS_ZERO_ID, "Zero linked proposals"),
            (POLIS_ONE_ID, "One linked proposal"),
            (POLIS_25_ID, "Twenty-five linked proposals"),
            (POLIS_MANY_ID, "More than twenty-five linked proposals"),
        )
        for index, (polis_id, title) in enumerate(polises):
            db.add(models.Polis(
                id=polis_id,
                org_id=ORG_ID,
                title=title,
                prompt="Deterministic disposable load fixture.",
                created_by=viewer.id,
                status="active",
                polis_conversation_id=f"phase104-load-{index}",
            ))

        statuses = (
            "voting",
            "deliberation",
            "draft",
            "passed",
            "failed",
            "unresolved",
            "expired_unsigned",
            "withdrawn",
        )
        methods = (
            "binary", "approval", "ranked_choice", "budget_allocation", "budget_project",
        )
        base = datetime(2026, 8, 30, 12, 0)
        scope_counts = Counter()
        status_counts = Counter()
        link_counts = Counter()
        for index in range(count):
            status = statuses[index % len(statuses)]
            scope_slot = index % 10
            sub_org_id = (
                PUBLIC_SUB_ID if scope_slot in (0, 1)
                else PRIVATE_SUB_ID if scope_slot in (2, 3)
                else None
            )
            links: list[str] = []
            if index == 0:
                links.append(POLIS_ONE_ID)
            if index < min(25, count):
                links.append(POLIS_25_ID)
            if index < min(63, count):
                links.append(POLIS_MANY_ID)
            if index == min(64, count - 1):
                links.extend([f"{POLIS_MANY_ID}-suffix", f"prefix-{POLIS_MANY_ID}"])
            for link in links:
                if link in {POLIS_ONE_ID, POLIS_25_ID, POLIS_MANY_ID}:
                    link_counts[link] += 1

            created = base - timedelta(minutes=index % 13)
            updated = base - timedelta(minutes=index % 7)
            voting_end = None
            if status == "voting" and index % 4:
                voting_end = base + timedelta(days=(index % 5) + 1)
            proposal = models.Proposal(
                id=stable_id(f"proposal-{index}"),
                title=f"Synthetic Phase 104 Proposal {index:04d} 100%_literal",
                body="B" * 20_000,
                author_id=viewer.id,
                org_id=ORG_ID,
                sub_org_id=sub_org_id,
                status=status,
                voting_method=methods[index % len(methods)],
                num_winners=(index % 3) + 1,
                created_at=created,
                updated_at=updated,
                deliberation_start=(base - timedelta(days=1) if status == "deliberation" else None),
                deliberation_end=(base + timedelta(days=2) if status == "deliberation" and index % 3 else None),
                voting_start=(base - timedelta(hours=2) if status == "voting" else None),
                voting_end=voting_end,
                voting_end_date=(base + timedelta(days=8) if index % 11 == 0 else None),
                is_cosign_gated=(status == "deliberation" and index % 4 == 1),
                cosign_threshold_snapshot=(5 if status == "deliberation" and index % 4 == 1 else None),
                cosign_expires_at=(base + timedelta(days=7) if status == "deliberation" and index % 4 == 1 else None),
                linked_polis_ids=links or None,
            )
            db.add(proposal)
            scope_counts[str(sub_org_id)] += 1
            status_counts[status] += 1
        db.commit()
        return {
            "fixture": "deterministic_uuid5",
            "proposals": count,
            "statuses": dict(status_counts),
            "scopes": dict(scope_counts),
            "polis_exact_links": dict(link_counts),
            "polis_zero": 0,
            "lookalike_only_rows": 1,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _plan_summary(plan: list) -> dict:
    top = plan[0]
    root = top["Plan"]
    interesting = []

    def visit(node: dict) -> None:
        if node.get("Node Type") in {
            "Sort", "Incremental Sort", "Seq Scan", "Index Scan",
            "Index Only Scan", "Bitmap Heap Scan", "Bitmap Index Scan",
        }:
            interesting.append({
                "node": node.get("Node Type"),
                "relation": node.get("Relation Name"),
                "index": node.get("Index Name"),
                "actual_rows": node.get("Actual Rows"),
                "rows_removed": node.get("Rows Removed by Filter"),
                "sort_key": node.get("Sort Key"),
                "sort_method": node.get("Sort Method"),
                "shared_hit_blocks": node.get("Shared Hit Blocks"),
                "shared_read_blocks": node.get("Shared Read Blocks"),
            })
        for child in node.get("Plans", []):
            visit(child)

    visit(root)
    return {
        "planning_ms": top.get("Planning Time"),
        "execution_ms": top.get("Execution Time"),
        "root": root.get("Node Type"),
        "actual_rows": root.get("Actual Rows"),
        "scan_sort_nodes": interesting,
        "plan": root,
    }


def _explain_query(db, query) -> dict:
    compiled = query.statement.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    )
    plan = db.execute(text(
        f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {compiled}"
    )).scalar_one()
    return _plan_summary(plan)


def _compact_query(db):
    return db.query(models.Proposal).options(load_only(
        models.Proposal.id,
        models.Proposal.title,
        models.Proposal.status,
        models.Proposal.voting_method,
        models.Proposal.num_winners,
        models.Proposal.created_at,
        models.Proposal.updated_at,
        models.Proposal.sub_org_id,
        models.Proposal.deliberation_end,
        models.Proposal.voting_end_date,
        models.Proposal.voting_end,
        models.Proposal.is_cosign_gated,
    )).filter(models.Proposal.org_id == ORG_ID)


def explain() -> dict:
    """Run real projection/order/predicate plans, including true keyset logic."""
    assert_disposable_postgres()
    db = SessionLocal()
    try:
        total = db.query(func.count(models.Proposal.id)).filter(
            models.Proposal.org_id == ORG_ID,
        ).scalar()
        default_q = _compact_query(db).order_by(*proposal_ordering()).limit(51)
        filtered_q = _compact_query(db).filter(
            models.Proposal.status == "deliberation",
            models.Proposal.sub_org_id == PRIVATE_SUB_ID,
            # This proof pattern contains no wildcard literals, so omitting
            # ESCAPE keeps literal-binds EXPLAIN portable through psycopg2.
            # Route-level literal %, _, and backslash semantics are covered
            # separately by the focused endpoint regression.
            func.lower(models.Proposal.title).like("%phase 104%"),
            structural_eligibility_predicate("set_end"),
        ).order_by(*proposal_ordering()).limit(51)

        cursor_row = default_q.limit(50).all()[-1]
        next_q = _compact_query(db).filter(
            proposal_after_cursor(proposal_row_key(cursor_row)),
        ).order_by(*proposal_ordering()).limit(51)

        polis_base = _compact_query(db).filter(
            cast(models.Proposal.linked_polis_ids, JSONB).op("@>")(
                literal_column(f"'[{json.dumps(POLIS_MANY_ID)}]'::jsonb")
            ),
        )
        polis_first = polis_base.order_by(
            models.Proposal.created_at.desc(), models.Proposal.id.asc(),
        ).limit(25).all()[-1]
        polis_next = polis_base.filter(
            created_after_cursor((polis_first.created_at, polis_first.id)),
        ).order_by(
            models.Proposal.created_at.desc(), models.Proposal.id.asc(),
        ).limit(26)

        return {
            "proposal_rows": int(total),
            "management_default": _explain_query(db, default_q),
            "management_filters": _explain_query(db, filtered_q),
            "management_next_page": _explain_query(db, next_q),
            "polis_exact_reverse_next_page": _explain_query(db, polis_next),
        }
    finally:
        db.close()


async def load(base_url: str, clients: int) -> dict:
    assert_disposable_postgres()
    token = auth.create_access_token(stable_id("viewer"))
    headers = {"Authorization": f"Bearer {token}"}
    latencies: dict[str, list[float]] = {}
    statuses = Counter()
    failures = []
    management_payloads = []

    fixture_db = SessionLocal()
    try:
        expected_all = {
            row.id for row in fixture_db.query(models.Proposal.id).filter(
                models.Proposal.org_id == ORG_ID,
            ).all()
        }
        expected_sub = {
            row.id for row in fixture_db.query(models.Proposal.id).filter(
                models.Proposal.sub_org_id == PUBLIC_SUB_ID,
            ).all()
        }
        expected_polis = {
            row.id for row in fixture_db.query(models.Proposal.id).filter(
                cast(models.Proposal.linked_polis_ids, JSONB).contains([POLIS_MANY_ID]),
            ).all()
        }
    finally:
        fixture_db.close()

    async with httpx.AsyncClient(base_url=base_url, timeout=20.0) as client:
        async def request(label: str, path: str, *, authenticated: bool = True):
            started = time.perf_counter()
            response = await client.get(path, headers=headers if authenticated else None)
            latencies.setdefault(label, []).append((time.perf_counter() - started) * 1000)
            statuses[response.status_code] += 1
            if response.status_code >= 500:
                failures.append({"label": label, "status": response.status_code})
            if label.startswith("management"):
                management_payloads.append(len(response.content))
            return response

        async def pool_component() -> dict:
            response = await client.get("/api/health/monitor")
            try:
                return response.json().get("components", {}).get("database_pool", {})
            except Exception:
                return {}

        pool_baseline = await pool_component()
        pool_samples = [pool_baseline.get("checked_out")]
        stop_sampling = asyncio.Event()

        async def sample_pool() -> None:
            while not stop_sampling.is_set():
                component = await pool_component()
                pool_samples.append(component.get("checked_out"))
                try:
                    await asyncio.wait_for(stop_sampling.wait(), timeout=0.5)
                except asyncio.TimeoutError:
                    pass

        sampler = asyncio.create_task(sample_pool())

        async def traverse(label: str, path: str, id_path: tuple[str, ...]) -> list[str]:
            seen: list[str] = []
            cursor = None
            while True:
                separator = "&" if "?" in path else "?"
                cursor_arg = f"{separator}cursor={cursor}" if cursor else ""
                response = await request(label, f"{path}{cursor_arg}")
                response.raise_for_status()
                body = response.json()
                for item in body["items"]:
                    value = item
                    for key in id_path:
                        value = value[key]
                    seen.append(value)
                if not body["has_more"]:
                    break
                cursor = body["next_cursor"]
            return seen

        management_seen = await traverse(
            "management_traversal",
            f"/api/orgs/{ORG_SLUG}/proposal-management-feed?limit=25",
            ("id",),
        )
        sub_seen = await traverse(
            "management_sub_traversal",
            f"/api/orgs/{ORG_SLUG}/proposal-management-feed?limit=25&sub_org_id={PUBLIC_SUB_ID}",
            ("id",),
        )
        polis_seen = await traverse(
            "polis_traversal",
            f"/api/orgs/{ORG_SLUG}/polises/{POLIS_MANY_ID}/proposal-links?limit=25",
            ("id",),
        )

        legacy = {}
        for name, path, authenticated in (
            ("org", f"/api/orgs/{ORG_SLUG}/proposals?limit=50", True),
            ("public", f"/api/orgs/{ORG_SLUG}/public/proposals?limit=50", False),
            ("global", "/api/proposals?limit=50", True),
        ):
            response = await request(f"legacy_{name}", path, authenticated=authenticated)
            response.raise_for_status()
            legacy[name] = {
                "rows": len(response.json()),
                "deprecation": response.headers.get("Deprecation"),
                "has_more": response.headers.get("X-Has-More"),
                "next_offset": response.headers.get("X-Next-Offset"),
                "link": response.headers.get("Link"),
            }

        mixed = (
            ("management", f"/api/orgs/{ORG_SLUG}/proposal-management-feed?limit=50", True),
            ("management_sub", f"/api/orgs/{ORG_SLUG}/proposal-management-feed?limit=25&sub_org_id={PRIVATE_SUB_ID}", True),
            ("polis", f"/api/orgs/{ORG_SLUG}/polises/{POLIS_MANY_ID}/proposal-links?limit=25", True),
            ("impact", f"/api/orgs/{ORG_SLUG}/sub-orgs/{PRIVATE_SUB_SLUG}/deletion-impact", True),
            ("health", "/api/health", False),
            ("readiness", "/api/health/ready", False),
        )
        await asyncio.gather(*[
            request(*mixed[index % len(mixed)][:2], authenticated=mixed[index % len(mixed)][2])
            for index in range(clients)
        ])

        async def filter_load_more(index: int) -> None:
            operation = ("draft_to_deliberation", "set_end")[index % 2]
            first = await request(
                "management_cycles",
                f"/api/orgs/{ORG_SLUG}/proposal-management-feed?limit=10&eligible_for={operation}",
            )
            first.raise_for_status()
            body = first.json()
            if body["has_more"]:
                await request(
                    "management_cycles",
                    f"/api/orgs/{ORG_SLUG}/proposal-management-feed?limit=10&eligible_for={operation}&cursor={body['next_cursor']}",
                )

        for _cycle in range(5):
            await asyncio.gather(*[filter_load_more(index) for index in range(clients)])

        stop_sampling.set()
        await sampler
        await asyncio.sleep(5)
        pool_post = await pool_component()

    db = SessionLocal()
    try:
        states = db.execute(text("""
            SELECT state, count(*) FROM pg_stat_activity
            WHERE datname=current_database() AND pid <> pg_backend_pid()
            GROUP BY state
        """)).all()
        idle_old = db.execute(text("""
            SELECT count(*) FROM pg_stat_activity
            WHERE datname=current_database() AND state='idle in transaction'
              AND now() - state_change > interval '5 seconds'
        """)).scalar_one()
        waiting_locks = db.execute(text("SELECT count(*) FROM pg_locks WHERE NOT granted")).scalar_one()
    finally:
        db.close()

    def percentile(values: list[float], p: float):
        ordered = sorted(values)
        if not ordered:
            return None
        return round(ordered[min(len(ordered) - 1, math.ceil(p * len(ordered)) - 1)], 2)

    management_values = [
        value for key, values in latencies.items()
        if key.startswith("management") for value in values
    ]
    pool_values = [int(value) for value in pool_samples if value is not None]

    def traversal(seen: list[str], expected: set[str]) -> dict:
        return {
            "rows": len(seen),
            "unique": len(set(seen)),
            "expected": len(expected),
            "duplicates": len(seen) - len(set(seen)),
            "missing": len(expected - set(seen)),
            "unexpected": len(set(seen) - expected),
        }

    return {
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
            "clients": clients,
        },
        "requests": sum(statuses.values()),
        "statuses": dict(statuses),
        "unexpected_5xx": len(failures),
        "pool_timeout_503s": statuses[503],
        "failure_samples": failures[:10],
        "traversal": {
            "management": traversal(management_seen, expected_all),
            "sub_org": traversal(sub_seen, expected_sub),
            "polis_exact": traversal(polis_seen, expected_polis),
        },
        "legacy": legacy,
        "management_latency_ms": {
            "p50": percentile(management_values, 0.50),
            "p95": percentile(management_values, 0.95),
            "p99": percentile(management_values, 0.99),
        },
        "health_p95_ms": percentile(latencies.get("health", []), 0.95),
        "max_management_payload_bytes": max(management_payloads, default=0),
        "pool": {
            "baseline": pool_baseline,
            "peak_checked_out": max(pool_values, default=None),
            "samples": len(pool_values),
            "post_5s": pool_post,
        },
        "post_load": {
            "pg_states": dict(states),
            "idle_in_transaction_over_5s": int(idle_old),
            "waiting_locks": int(waiting_locks),
        },
    }


def main_cli() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    seed_parser = sub.add_parser("seed")
    seed_parser.add_argument("--count", type=int, default=250, choices=(250, 2500))
    sub.add_parser("explain")
    load_parser = sub.add_parser("load")
    load_parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    load_parser.add_argument("--clients", type=int, default=20)
    args = parser.parse_args()
    if args.command == "seed":
        result = seed(args.count)
    elif args.command == "explain":
        result = explain()
    else:
        result = asyncio.run(load(args.base_url.rstrip("/"), args.clients))
    print(json.dumps(result, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main_cli()
