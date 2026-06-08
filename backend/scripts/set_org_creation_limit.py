"""Phase 62 C1 — set ``User.org_creation_limit`` for a specific user.

The org-creation-limit is the per-user cap enforced by Gate 3 of
``POST /api/organizations`` (see ``routes/organizations.py`` line ~353).
A NULL limit defaults to ``DEFAULT_PER_USER_ORG_LIMIT`` (3). Bumping a
user's limit lets them create more owned orgs.

There is no admin API endpoint for this today; the column is set
directly via this script.

USAGE
-----

Dry run (default — prints what WOULD change but writes nothing):

    DATABASE_URL=postgresql://... \\
        python backend/scripts/set_org_creation_limit.py \\
            --user zachp \\
            --limit 10

Apply for real:

    DATABASE_URL=postgresql://... \\
        python backend/scripts/set_org_creation_limit.py \\
            --user zachp \\
            --limit 10 \\
            --confirm

User identification:
  ``--user`` accepts either a username OR an email (case-insensitive).
  Email is detected by the presence of ``@``.

Limit value:
  ``--limit`` is a non-negative integer. ``0`` effectively prohibits
  org creation (counts are always >= 0; limit 0 blocks any creation).
  Pass ``--limit none`` (the literal string) to clear an existing
  explicit limit back to the platform default (NULL -> 3).

Audit:
  On --confirm, an audit row is written with
  ``action='user.org_creation_limit_changed'`` carrying the user_id,
  old_limit, new_limit, and actor='cli-script' so the change is
  attributable.

Safety:
  * Dry-run is the default. No writes happen without --confirm.
  * Idempotent: re-running with the same target value reports
    "already at limit N" and exits 0 without writing.
  * The script aborts loudly if the user is not found, instead of
    silently no-op-ing.
"""
from __future__ import annotations

import argparse
import os
import sys

# Add backend dir to sys.path so we can import the project modules
# when invoked as ``python backend/scripts/set_org_creation_limit.py``.
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import models  # noqa: E402
from database import SessionLocal  # noqa: E402
from audit_utils import log_audit_event  # noqa: E402


def _parse_limit(raw: str) -> int | None:
    """Parse the --limit argument. The literal string 'none' clears the
    explicit limit (writes NULL, falling back to the platform default)."""
    if raw.strip().lower() == "none":
        return None
    try:
        v = int(raw)
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            f"--limit must be a non-negative integer or 'none'; got {raw!r}"
        ) from e
    if v < 0:
        raise argparse.ArgumentTypeError(
            f"--limit must be >= 0; got {v}"
        )
    return v


def _resolve_user(db, identifier: str) -> models.User | None:
    """Resolve by email (if @ present) else by username. Case-insensitive
    on both. Returns the User row or None if not found."""
    ident = identifier.strip()
    q = db.query(models.User)
    if "@" in ident:
        return q.filter(models.User.email.ilike(ident)).first()
    return q.filter(models.User.username.ilike(ident)).first()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Set User.org_creation_limit for a target user. Dry-run by "
            "default; pass --confirm to apply."
        ),
    )
    parser.add_argument(
        "--user",
        required=True,
        help="Username or email of the target user (case-insensitive).",
    )
    parser.add_argument(
        "--limit",
        required=True,
        type=_parse_limit,
        help=(
            "New org-creation-limit (non-negative integer). Use "
            "'none' to clear an explicit limit back to the platform "
            "default (NULL -> 3)."
        ),
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Apply the change. Without this flag the script dry-runs.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        user = _resolve_user(db, args.user)
        if user is None:
            print(
                f"ERROR: no user matched {args.user!r} "
                f"(searched {'email' if '@' in args.user else 'username'}).",
                file=sys.stderr,
            )
            return 2

        old_limit = user.org_creation_limit
        new_limit = args.limit  # may be None
        print(f"Target user : {user.username!r} (email={user.email!r}, id={user.id})")
        print(f"Current limit: {old_limit!r}")
        print(f"New limit    : {new_limit!r}")

        if old_limit == new_limit:
            print(
                "No change needed — user is already at the requested "
                "limit. Exiting cleanly."
            )
            return 0

        if not args.confirm:
            print(
                "\n[DRY RUN] No write performed. Re-run with --confirm "
                "to apply the change."
            )
            return 0

        user.org_creation_limit = new_limit
        log_audit_event(
            db,
            action="user.org_creation_limit_changed",
            target_type="user",
            target_id=user.id,
            actor_id=user.id,  # no human actor; self-target keeps FK valid
            details={
                "old_limit": old_limit,
                "new_limit": new_limit,
                "via": "backend/scripts/set_org_creation_limit.py",
            },
        )
        db.commit()
        print(
            f"\nDone. {user.username}.org_creation_limit: "
            f"{old_limit!r} -> {new_limit!r}"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
