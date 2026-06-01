"""Phase 48 Stage 2 — emergency prod DB patch.

start.sh's fresh-DB regex (`[a-f0-9]\\{12\\}`) does not match
revision IDs starting with non-hex chars (e.g. 'g5a8b1c93412',
'h6b9c2d04523'). After Stage 1 stamped 'g5a8b1c93412' as the
alembic head, Stage 2's start.sh mis-detected the DB as fresh,
ran ``create_all`` (no-op on existing tables — doesn't add new
columns) and stamped 'h6b9c2d04523' as head. Result: alembic
thinks the migration is applied but the actual column is missing.

This script:
  1. Checks current alembic_version.
  2. Verifies the column is missing.
  3. Adds the column with the same shape the migration would.
  4. Verifies the column now exists.

Run via DATABASE_PUBLIC_URL with the Railway TCP proxy:

    DATABASE_URL=postgresql://...@shuttle.proxy.rlwy.net:<port>/railway \\
        python scripts/fix_stage2_column.py
"""
from __future__ import annotations

import os
import sys

import psycopg2


def main() -> int:
    db_url = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")
    if not db_url:
        print("ERROR: DATABASE_URL (or DATABASE_PUBLIC_URL) must be set.")
        return 2

    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    cur = conn.cursor()

    cur.execute("SELECT version_num FROM alembic_version")
    rows = cur.fetchall()
    print(f"alembic_version rows: {rows}")

    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'proposals' AND column_name = 'election_slate_mode'"
    )
    pre = cur.fetchall()
    print(f"election_slate_mode before: {pre}")

    if not pre:
        print("Adding column election_slate_mode...")
        cur.execute(
            "ALTER TABLE proposals ADD COLUMN election_slate_mode "
            "VARCHAR(16) NOT NULL DEFAULT 'fill_vacancies'"
        )
        conn.commit()
        print("Column added + committed.")
    else:
        print("Column already exists; no-op.")

    cur.execute(
        "SELECT column_name, data_type, is_nullable, column_default "
        "FROM information_schema.columns "
        "WHERE table_name = 'proposals' AND column_name = 'election_slate_mode'"
    )
    post = cur.fetchall()
    print(f"election_slate_mode after: {post}")

    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
