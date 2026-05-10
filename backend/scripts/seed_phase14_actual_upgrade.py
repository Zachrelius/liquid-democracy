"""Phase 14 actual-upgrade-path seed module — Phase 15 G5 equivalence test.

Re-implements the seed + verify logic from
``phase14_actual_upgrade_path_check.py`` against the standard
``pg_smoke.py --mode actual-upgrade`` interface. Used as a regression
gate when introducing the new mode — running this against
``--prior-revision b9e2f4a17c83`` should produce equivalent pre/post
counts to the single-purpose script.

Module contract (per pg_smoke G5):

  - seed(engine)   — required; populates the affected tables with
                     legacy-shaped data the migration must transform.
  - verify(engine) — optional; asserted post-upgrade.
  - reshape(engine) — optional; pre-seed schema reshape if the migration
                     drops/adds columns.

Phase 14's only change is a value rename (``invite_only`` →
``invite_only_secret``); no schema reshape needed.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone


# Slug → join_policy values seeded. The two ``invite_only`` rows are the
# load-bearing test (count must drop to 0 post-upgrade).
_SEED_ORGS: tuple[tuple[str, str], ...] = (
    ("legacy-1", "invite_only"),
    ("legacy-2", "invite_only"),
    ("ar-org", "approval_required"),
    ("open-org", "open"),
)


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def seed(engine) -> None:
    from sqlalchemy import text
    now = _now_naive()
    with engine.begin() as conn:
        for slug, join_policy in _SEED_ORGS:
            conn.execute(text(
                "INSERT INTO organizations "
                "(id, name, slug, description, join_policy, settings, "
                " parent_org_id, created_at, updated_at) "
                "VALUES (:id, :n, :s, '', :jp, '{}', NULL, :now, :now)"
            ), {
                "id": str(uuid.uuid4()), "n": slug.title(), "s": slug,
                "jp": join_policy, "now": now,
            })


def verify(engine) -> None:
    """Post-upgrade assertions identical to the single-purpose script."""
    from sqlalchemy import text
    with engine.connect() as conn:
        def count(value: str) -> int:
            return int(conn.execute(text(
                "SELECT COUNT(*) FROM organizations WHERE join_policy = :v"
            ), {"v": value}).scalar() or 0)

        post_legacy = count("invite_only")
        post_secret = count("invite_only_secret")
        post_ar = count("approval_required")
        post_open = count("open")

        print(
            f"[seed_phase14] POST-upgrade counts: invite_only={post_legacy}, "
            f"invite_only_secret={post_secret}, "
            f"approval_required={post_ar}, open={post_open}",
            flush=True,
        )

        assert post_legacy == 0, (
            f"expected 0 invite_only rows post-upgrade, got {post_legacy}"
        )
        assert post_secret == 2, (
            f"expected 2 invite_only_secret rows post-upgrade, got {post_secret}"
        )
        assert post_ar == 1, (
            f"approval_required count should be unchanged, got {post_ar}"
        )
        assert post_open == 1, (
            f"open count should be unchanged, got {post_open}"
        )
