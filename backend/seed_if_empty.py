"""Idempotent demo-data seeding for the public demo deployment.

Runs at container start (via start.sh) when IS_PUBLIC_DEMO=true. Phase 7C.1:
the seed is now fully additive — every helper checks for existing rows
before inserting, never overwrites. So we always run it on every boot.
First-time runs populate everything; subsequent runs add only new content
that's been added since the last run, leaving existing visitor data alone.
"""

from database import SessionLocal
from models import User
from seed_data import run_seed

db = SessionLocal()
try:
    user_count = db.query(User).count()
    if user_count == 0:
        print("Public demo — first-time seed (empty users table)…", flush=True)
    else:
        print(f"Public demo — additive seed (existing users: {user_count})…", flush=True)
    result = run_seed(db)
    print(f"Public demo — seed complete: {result}", flush=True)
finally:
    db.close()
