#!/bin/bash
set -e

# ── Schema bootstrap / migration (Phase 8.6 Item 3 ordering invariant) ──────
#
# Invariant: alembic is the sole authority on schema for any DB that has
# already been stamped. ``create_tables()`` (SQLAlchemy ``create_all``) only
# runs on the fresh-DB branch, before stamping head — never on an existing
# DB that's about to receive pending migrations.
#
# Why: ``create_all`` is "create-only" + idempotent at the table-existence
# level, but it builds tables based on **current** model definitions. If a
# pending migration adds a table (e.g., Phase 8.5's ``sub_org_memberships``),
# running ``create_all`` first lays that table down, then ``alembic upgrade
# head`` re-creates the same table — collision, container fails to start.
# That was the 15-minute 502 incident on the Phase 8.5 deploy
# (hot-fixed in b1ab5db by making the migration idempotent; this is the
# durable fix at the ordering layer).
#
# Why ``create_all`` is still needed on the fresh-DB branch: the alembic
# chain's base revision (``58de3df8727f``) ALTERs the ``users`` table — it
# assumes ``users`` and other Phase-1/2 tables already exist (the alembic
# chain was added post-hoc to an already-shipped schema). So a true fresh
# DB cannot apply ``alembic upgrade head`` without those base tables, and
# ``create_all`` provides them in the fresh-DB branch only.
#
# Fresh-DB branch: ``create_all`` builds today's full schema, then
# ``alembic stamp head`` records the chain head without re-applying any
# migration. Existing-DB branch: skip ``create_all`` entirely; let alembic
# apply only the pending revisions.

# NB: Match 12+ alphanumeric chars (not just hex). Hand-crafted Alembic
# revision IDs can start with non-hex chars (e.g. Phase 48 used
# 'g5a8b1c93412' + 'h6b9c2d04523'); a hex-only regex mis-detects those
# as "fresh DB" and runs create_all + stamp head, which silently skips
# every pending migration. That bit Phase 48 Stage 2 on prod (column
# election_slate_mode never applied). Alphanumeric matches both
# auto-generated hex revs and hand-rolled ones.
#
# Phase 48 Stage 2 hardening — the stamp-head-masks-pending-migration
# hazard is a class beyond the regex. Even if a future detection bug
# fires the fresh-DB branch on a non-fresh DB, the fresh-DB branch
# itself now guards against it: it queries the DB for the presence of
# `users` (the canonical "this isn't a fresh DB" probe — the users
# table is created in the very first migration `58de3df8727f` and has
# never been dropped). If `users` exists, abort loudly with operator
# guidance rather than silently stamping head over a misdetection.
if alembic current 2>/dev/null | grep -q '[[:alnum:]]\{12,\}'; then
    echo "Alembic-stamped DB detected — applying pending migrations…"
    alembic upgrade head
else
    echo "Fresh-database branch triggered — verifying DB is actually fresh…"
    USERS_EXISTS=$(python -c "
from sqlalchemy import inspect
from database import engine
print('1' if 'users' in inspect(engine).get_table_names() else '0')
" 2>/dev/null)
    if [ "${USERS_EXISTS}" = "1" ]; then
        echo "ERROR: 'users' table exists but alembic_version is missing/unrecognized." >&2
        echo "       This means alembic stamp state was lost or the version" >&2
        echo "       string is in an unexpected format. REFUSING to run" >&2
        echo "       create_all + stamp head because that would mask the" >&2
        echo "       missing migrations (e.g. Phase 48 Stage 2 incident)." >&2
        echo "" >&2
        echo "       To recover, connect to the DB and run:" >&2
        echo "         alembic current        # inspect output format" >&2
        echo "         alembic history --verbose  # confirm chain head" >&2
        echo "       Then either:" >&2
        echo "         (a) alembic stamp <correct-prior-revision> && alembic upgrade head" >&2
        echo "         (b) manually run any unapplied migrations via direct SQL" >&2
        echo "             + correct the alembic_version row." >&2
        echo "       See backend/scripts/fix_stage2_column.py for the template." >&2
        exit 1
    fi
    echo "Fresh database confirmed (no 'users' table) — bootstrapping via create_all + stamp head."
    python -c "from database import create_tables; create_tables()"
    alembic stamp head
fi

if [ "${IS_PUBLIC_DEMO}" = "true" ]; then
    echo "Public demo mode — ensuring demo seed data…"
    python seed_if_empty.py
fi

# Phase 8 — Sustained-Majority background worker.
# Runs as a side process; multi-instance protection lives in the worker
# itself via SUSTAINED_MAJORITY_WORKER_INSTANCE_ID. Disable entirely with
# SUSTAINED_MAJORITY_WORKER_DISABLE=true.
if [ "${SUSTAINED_MAJORITY_WORKER_DISABLE}" != "true" ]; then
    echo "Starting sustained-majority worker…"
    python -m sustained_majority_worker &
    SM_WORKER_PID=$!
    echo "Sustained-majority worker PID: ${SM_WORKER_PID}"
fi

echo "Starting application…"
# Phase 35 D17 — Memory is the primary cost axis (97% of May 2026 usage).
# Each uvicorn worker is a full Python process loading FastAPI + models +
# SQLAlchemy engine + the digest_loop asyncio task. At Cedar Hollow scale
# (76 members, single-instance friend pilot) 4 workers is massive
# overprovisioning: each worker ~100-150MB RSS, so 4 workers ≈ 500MB
# steady-state just to serve the same idle traffic 1 worker would.
# Phase 33 also flagged the multi-worker scheduler race (Item 70) — 4
# parallel digest ticks competing for the same demo-reset lock.
#
# Defaulting to 1 worker. WORKERS env var can override at the Railway
# dashboard if real traffic ever demands concurrency. Single-worker is
# more than enough for friend-pilot scale; adding workers when traffic
# grows is a flip-the-env-var change, not a code change.
# Phase 38 ride-along — trust Railway-edge forwarded headers so the actual
# client IP (X-Forwarded-For) propagates into request.client.host. Without
# this flag, uvicorn defaults --forwarded-allow-ips to 127.0.0.1 only, so
# the Railway-edge IP becomes request.client.host and every slowapi rate
# limiter is effectively keyed per-edge-IP instead of per-client-IP. Also
# fixes audit-log IP fidelity (Tier-2 tech debt from the Phase 37 closeout).
#
# Phase 40a B1 (2026-05-28) — start.sh stays as PID 1; uvicorn launches as
# a background child instead of via `exec`. Pre-Phase-40a the SM worker
# (child of PID 1) received no signal on Railway redeploy because Railway
# sends SIGTERM to PID 1 only, not cgroup-wide — the worker was SIGKILLed
# during force-stop. Post-fix the trap below forwards SIGTERM/SIGINT to
# both children so each runs its graceful shutdown path. Confirmed
# behavior is documented in DEPLOYMENT.md "Worker signal handling."
uvicorn main:app --host 0.0.0.0 --port 8000 --workers ${WORKERS:-1} \
    --proxy-headers --forwarded-allow-ips '*' &
UVICORN_PID=$!
echo "Uvicorn PID: ${UVICORN_PID}"

_cleanup() {
    echo "[start.sh] Received shutdown signal; forwarding to children…"
    # Worker first — needs time to finish current tick. Tolerate the worker
    # not being set (SUSTAINED_MAJORITY_WORKER_DISABLE=true skipped its
    # launch) by guarding on the PID being non-empty.
    if [ -n "${SM_WORKER_PID:-}" ]; then
        kill -TERM "${SM_WORKER_PID}" 2>/dev/null || true
    fi
    sleep 1
    # Then uvicorn.
    kill -TERM "${UVICORN_PID}" 2>/dev/null || true
    # Wait for both to exit. `wait` on an already-reaped PID is a no-op;
    # `|| true` swallows any non-zero exit status so `set -e` doesn't kill
    # the trap mid-cleanup.
    if [ -n "${SM_WORKER_PID:-}" ]; then
        wait "${SM_WORKER_PID}" 2>/dev/null || true
    fi
    wait "${UVICORN_PID}" 2>/dev/null || true
    echo "[start.sh] All children exited; goodbye."
    exit 0
}

trap _cleanup SIGTERM SIGINT

# Block until any child exits. If uvicorn or the worker dies for unrelated
# reasons (OOM, crash), we fall through to the cleanup path and bring the
# other child down too — no orphans.
wait -n
echo "[start.sh] A child process exited unexpectedly; shutting down…"
_cleanup
