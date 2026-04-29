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

if alembic current 2>/dev/null | grep -q '[a-f0-9]\{12\}'; then
    echo "Alembic-stamped DB detected — applying pending migrations…"
    alembic upgrade head
else
    echo "Fresh database detected — bootstrapping via create_all + stamp head."
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
exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers ${WORKERS:-4}
