"""Phase 13.3 — Delete orphaned NotificationPreference rows for the
deleted ``sustained_majority.floor_approached`` event type.

Idempotent. Safe to run multiple times. Run via railway ssh as a backup
to the migration's inline DELETE.

Usage from backend/:

    .venv/Scripts/python.exe scripts/phase13_3_cleanup_floor_approached_prefs.py
"""
from __future__ import annotations

import os
import sys

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from sqlalchemy.orm import Session  # noqa: E402

from database import SessionLocal  # noqa: E402
import models  # noqa: E402


def main() -> int:
    db: Session = SessionLocal()
    try:
        deleted = (
            db.query(models.NotificationPreference)
            .filter(
                models.NotificationPreference.event_type
                == "sustained_majority.floor_approached"
            )
            .delete(synchronize_session=False)
        )
        db.commit()
        print(
            f"phase13_3 cleanup: deleted {deleted} orphaned "
            "NotificationPreference rows for "
            "'sustained_majority.floor_approached'."
        )
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
