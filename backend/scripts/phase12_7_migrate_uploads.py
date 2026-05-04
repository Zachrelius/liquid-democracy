"""Phase 12.7 I3 — one-shot copy of legacy ephemeral-disk uploads to Railway Volume.

Run via:

    railway ssh "cd /app && python scripts/phase12_7_migrate_uploads.py"

Reads from the previous default upload base (``backend/uploads``, which
was the in-image ephemeral path through Phase 12.6) and copies any
existing files to whatever ``UPLOADS_BASE_DIR`` resolves to NOW (which
is ``/data/uploads`` on Railway with the Volume provisioned per Phase
12.7 D1).

Idempotent: skips files that already exist at the destination so the
script is safe to re-run if the first invocation was interrupted or the
Volume was reset.

No action is taken for files that were referenced in DB columns
(``users.avatar_url``, ``Organization.settings.branding.logo_url``) but
have already gone missing on the ephemeral disk in prior deploys — the
existing initials-fallback for avatars and the no-logo fallback for orgs
both cover them, so no recreation is necessary or possible.

Output is a single line ``copied=N skipped=N`` for easy verification
from the Railway shell. Exits non-zero only on a Python-level error
(missing dependency, permission denied creating dst dir, etc.).
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

# Source: the legacy ephemeral path that was the default before Phase
# 12.7 I2's _resolve_uploads_base() refactor. Hardcoded so the script
# doesn't depend on the resolved value (which would be the destination,
# not the source).
LEGACY_BASE: Path = Path(__file__).resolve().parent.parent / "uploads"


def main() -> int:
    # Late import so the script can be discovered/inspected without
    # spinning up the FastAPI dependency tree at module-import time.
    # Add backend/ to sys.path so the script works whether invoked as
    # `python scripts/phase12_7_migrate_uploads.py` from backend/ or
    # `python backend/scripts/phase12_7_migrate_uploads.py` from repo
    # root. Mirrors how other one-shot scripts in this directory behave.
    backend_dir = Path(__file__).resolve().parent.parent
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))

    from routes.avatars import UPLOADS_BASE_DIR  # noqa: E402

    if not LEGACY_BASE.exists():
        print(f"Legacy {LEGACY_BASE} doesn't exist — nothing to migrate.")
        return 0

    if LEGACY_BASE.resolve() == UPLOADS_BASE_DIR.resolve():
        # Local dev OR prod-without-volume: source and destination are
        # the same path. Nothing to do — files are already in place.
        print(
            f"Legacy and current paths identical ({LEGACY_BASE}) — running on "
            f"local dev or Volume not mounted. No action taken."
        )
        return 0

    copied = 0
    skipped = 0
    for src in LEGACY_BASE.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(LEGACY_BASE)
        dst = UPLOADS_BASE_DIR / rel
        if dst.exists():
            skipped += 1
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1

    print(f"copied={copied} skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
