"""Idempotent demo-data seeding for the public demo deployment.

Runs at container start (via start.sh) when IS_PUBLIC_DEMO=true. If the
users table is empty, runs the full demo seed; otherwise skips. Keeps the
public demo self-healing across redeploys and fresh databases without ever
wiping visitor-created content.
"""

from database import SessionLocal
from models import User
from seed_data import run_seed

db = SessionLocal()
try:
    user_count = db.query(User).count()
    if user_count == 0:
        print("Public demo — users table empty, running run_seed(db)…", flush=True)
        result = run_seed(db)
        print(f"Public demo — seed complete: {result}", flush=True)
    else:
        print(f"Public demo — seed skipped ({user_count} users already present).", flush=True)
finally:
    db.close()
