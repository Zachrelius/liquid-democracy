#!/bin/bash
set -e

# Ensure base schema exists (create_all is idempotent).
# This makes the container startup work on a fresh database where the
# alembic chain assumes pre-existing tables (migrations were added post-hoc
# to an already-shipped schema).
echo "Ensuring base schema exists (SQLAlchemy create_all)…"
python -c "from database import create_tables; create_tables()"

echo "Running database migrations…"
if alembic current 2>/dev/null | grep -q '[a-f0-9]\{12\}'; then
    # Already stamped — apply any pending migrations.
    alembic upgrade head
else
    # Fresh DB: stamp head since create_tables already built the current schema.
    echo "Fresh database detected — stamping alembic head."
    alembic stamp head
fi

if [ "${IS_PUBLIC_DEMO}" = "true" ]; then
    echo "Public demo mode — ensuring demo seed data…"
    python seed_if_empty.py
fi

echo "Starting application…"
exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers ${WORKERS:-4}
