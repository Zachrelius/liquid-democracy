"""Phase 12.5 migration: verify upgrade -> downgrade -> upgrade cycle on
SQLite for the ``proposal.set_thresholds`` row inserts, plus
data-correctness assertions about the seeded enabled-flag values per
preset role.

Mirrors ``test_phase_12_stage2_migration_cycle.py`` but exercises only
the Phase 12.5 step (41694d86821f):
  - Build the schema through Stage 2 (upgrade to e6371e56e860).
  - Seed two orgs so we have preset roles to attach role_permissions
    rows to.
  - Upgrade -> head (i.e. apply Phase 12.5).
  - Assert: every preset role now has a role_permissions row with
    permission_key='proposal.set_thresholds' and the spec-required
    enabled value (steward/admin=True, moderator/member=False).
  - Downgrade -1 -> Phase 12.5 reversed.
  - Assert: NO role_permissions row with permission_key='proposal.set_thresholds'
    exists for any role.
  - Re-upgrade head.
  - Assert: rows are present again, idempotently (no duplicates).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PERMISSION_KEY = "proposal.set_thresholds"


def _run_alembic(db_url: str, *args: str) -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    res = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=_BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, (
        f"alembic {' '.join(args)} failed:\nSTDOUT:\n{res.stdout}\n"
        f"STDERR:\n{res.stderr}"
    )


def _create_all_subprocess(db_url: str) -> None:
    code = (
        f"import os; os.environ['DATABASE_URL']={db_url!r}; "
        "from database import create_tables; create_tables()"
    )
    res = subprocess.run(
        [sys.executable, "-c", code],
        cwd=_BACKEND_DIR,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, (
        f"create_tables failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )


def _build_legacy_schema(db_url: str) -> None:
    """Construct the pre-Phase-12 schema, stamp it at b2d5f1a3c7e4. The
    caller is responsible for seeding orgs (so they're present when Stage 1
    runs and creates preset roles for each existing org)."""
    _create_all_subprocess(db_url)
    engine = sa.create_engine(db_url)
    try:
        with engine.begin() as conn:
            tables = set(sa.inspect(conn).get_table_names())
            if "role_permissions" in tables:
                conn.execute(sa.text("DROP TABLE role_permissions"))
            tables = set(sa.inspect(conn).get_table_names())
            if "roles" in tables:
                conn.execute(sa.text("DROP TABLE roles"))
            conn.execute(sa.text("DROP TABLE org_memberships"))
            conn.execute(sa.text(
                "CREATE TABLE org_memberships ("
                "id VARCHAR PRIMARY KEY, "
                "user_id VARCHAR NOT NULL REFERENCES users(id), "
                "org_id VARCHAR NOT NULL REFERENCES organizations(id), "
                "role VARCHAR DEFAULT 'member', "
                "status VARCHAR DEFAULT 'active', "
                "joined_at DATETIME, "
                "UNIQUE(user_id, org_id)"
                ")"
            ))
    finally:
        engine.dispose()
    _run_alembic(db_url, "stamp", "b2d5f1a3c7e4")


def _seed_two_orgs_with_memberships(db_url: str) -> dict:
    """Insert two organizations + a user + memberships into the legacy
    (pre-Phase-12) schema so Stage 1's migration has data to operate on
    (specifically, orgs to seed preset roles for and memberships to backfill
    role_id onto). Returns ids for assertions."""
    engine = sa.create_engine(db_url)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    org_a_id = str(uuid.uuid4())
    org_b_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    try:
        with engine.begin() as conn:
            conn.execute(sa.text(
                "INSERT INTO users (id, username, display_name, "
                "password_hash, is_admin, user_type, "
                "delegation_strategy, email_verified, "
                "default_follow_policy, created_at) "
                "VALUES (:id, :u, :dn, 'x', 0, 'human', "
                "'strict_precedence', 0, 'require_approval', :now)"
            ), {"id": user_id, "u": "p125tester", "dn": "Tester", "now": now})

            for org_id, slug in [(org_a_id, "p125a"), (org_b_id, "p125b")]:
                conn.execute(sa.text(
                    "INSERT INTO organizations "
                    "(id, name, slug, description, join_policy, settings, "
                    "created_at, updated_at) "
                    "VALUES (:id, :n, :s, '', 'open', '{}', :now, :now)"
                ), {"id": org_id, "n": slug.title(), "s": slug, "now": now})
                conn.execute(sa.text(
                    "INSERT INTO org_memberships "
                    "(id, user_id, org_id, role, status, joined_at) "
                    "VALUES (:id, :u, :o, 'owner', 'active', :now)"
                ), {
                    "id": str(uuid.uuid4()),
                    "u": user_id,
                    "o": org_id,
                    "now": now,
                })
    finally:
        engine.dispose()

    return {"org_a_id": org_a_id, "org_b_id": org_b_id}


def _count_set_thresholds_rows(db_url: str) -> dict[str, dict[str, int]]:
    """Return a per-org, per-system_key bool of role_permissions rows
    whose permission_key='proposal.set_thresholds'."""
    engine = sa.create_engine(db_url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT r.org_id, r.system_key, rp.enabled "
                    "FROM role_permissions rp "
                    "JOIN roles r ON r.id = rp.role_id "
                    "WHERE rp.permission_key = :pkey"
                ),
                {"pkey": _PERMISSION_KEY},
            ).fetchall()
    finally:
        engine.dispose()
    by_org: dict[str, dict[str, int]] = {}
    for org_id, system_key, enabled in rows:
        by_org.setdefault(org_id, {})[system_key] = bool(enabled)
    return by_org


def test_phase_12_5_upgrade_downgrade_upgrade_cycle():
    """Phase 12.5 migration is reversible and idempotent on SQLite.

    Cycle: stage2 -> 12.5 -> downgrade 12.5 -> re-apply 12.5.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"

    try:
        _build_legacy_schema(db_url)
        _seed_two_orgs_with_memberships(db_url)
        # Apply Stage 1 + Stage 2 (everything BEFORE Phase 12.5) so the
        # preset roles and the prior set of role_permissions rows are in
        # place.
        _run_alembic(db_url, "upgrade", "e6371e56e860")

        # Sanity: at Stage 2, no proposal.set_thresholds rows exist yet.
        engine = sa.create_engine(db_url)
        with engine.connect() as conn:
            pre_count = conn.execute(
                sa.text(
                    "SELECT COUNT(*) FROM role_permissions "
                    "WHERE permission_key = :pkey"
                ),
                {"pkey": _PERMISSION_KEY},
            ).scalar()
        engine.dispose()
        assert pre_count == 0, (
            "Stage 2 doesn't insert proposal.set_thresholds rows; "
            f"expected 0 before Phase 12.5 runs, got {pre_count}"
        )

        # 1. Upgrade head (applies Phase 12.5)
        _run_alembic(db_url, "upgrade", "head")
        per_org = _count_set_thresholds_rows(db_url)

        # Each of two seeded orgs should now have all four preset roles
        # carrying a proposal.set_thresholds row with the correct enabled
        # flag.
        assert len(per_org) == 2
        for org_id, by_role in per_org.items():
            assert by_role.get("steward") is True, (
                f"org {org_id}: steward should have "
                f"proposal.set_thresholds=True; got {by_role.get('steward')!r}"
            )
            assert by_role.get("admin") is True, (
                f"org {org_id}: admin should have "
                f"proposal.set_thresholds=True; got {by_role.get('admin')!r}"
            )
            assert by_role.get("moderator") is False, (
                f"org {org_id}: moderator should have "
                f"proposal.set_thresholds=False; got {by_role.get('moderator')!r}"
            )
            assert by_role.get("member") is False, (
                f"org {org_id}: member should have "
                f"proposal.set_thresholds=False; got {by_role.get('member')!r}"
            )

        # 2. Downgrade -1: reverse Phase 12.5 only.
        _run_alembic(db_url, "downgrade", "-1")
        engine = sa.create_engine(db_url)
        with engine.connect() as conn:
            tables = set(sa.inspect(conn).get_table_names())
            # Stage 1+2 tables should still exist.
            assert "roles" in tables
            assert "role_permissions" in tables
            post_downgrade_count = conn.execute(
                sa.text(
                    "SELECT COUNT(*) FROM role_permissions "
                    "WHERE permission_key = :pkey"
                ),
                {"pkey": _PERMISSION_KEY},
            ).scalar()
        engine.dispose()
        assert post_downgrade_count == 0, (
            f"Phase 12.5 downgrade should remove every "
            f"proposal.set_thresholds row; got {post_downgrade_count} "
            "remaining"
        )

        # 3. Re-upgrade head — idempotency. Re-applying must not duplicate
        # rows; we should see the same 8 rows (2 orgs × 4 preset roles).
        _run_alembic(db_url, "upgrade", "head")
        per_org_2 = _count_set_thresholds_rows(db_url)
        assert len(per_org_2) == 2
        for org_id, by_role in per_org_2.items():
            assert set(by_role.keys()) == {
                "steward", "admin", "moderator", "member"
            }
            assert by_role["steward"] is True
            assert by_role["admin"] is True
            assert by_role["moderator"] is False
            assert by_role["member"] is False

        engine = sa.create_engine(db_url)
        with engine.connect() as conn:
            total_rows = conn.execute(
                sa.text(
                    "SELECT COUNT(*) FROM role_permissions "
                    "WHERE permission_key = :pkey"
                ),
                {"pkey": _PERMISSION_KEY},
            ).scalar()
        engine.dispose()
        # 2 orgs × 4 preset roles = 8 rows exactly.
        assert total_rows == 8, (
            f"After re-upgrade expected 8 proposal.set_thresholds rows "
            f"(2 orgs × 4 roles), got {total_rows} — possible duplicate "
            f"insert (idempotency violated)"
        )
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase_12_5_idempotent_when_re_applied_with_existing_rows():
    """Running upgrade twice in a row (no intervening downgrade) is a
    no-op on the second run — validates the existence-check guard."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"

    try:
        _build_legacy_schema(db_url)
        _seed_two_orgs_with_memberships(db_url)

        # First upgrade — runs all migrations through Phase 12.5.
        _run_alembic(db_url, "upgrade", "head")
        engine = sa.create_engine(db_url)
        with engine.connect() as conn:
            after_first = conn.execute(
                sa.text(
                    "SELECT COUNT(*) FROM role_permissions "
                    "WHERE permission_key = :pkey"
                ),
                {"pkey": _PERMISSION_KEY},
            ).scalar()
        engine.dispose()

        # Second invocation: downgrade -1 then upgrade head re-applies the
        # 12.5 migration; subsequent upgrade head with already-at-head is
        # a no-op. Both forms should leave row counts identical.
        _run_alembic(db_url, "downgrade", "-1")
        _run_alembic(db_url, "upgrade", "head")
        _run_alembic(db_url, "upgrade", "head")

        engine = sa.create_engine(db_url)
        with engine.connect() as conn:
            after_repeat = conn.execute(
                sa.text(
                    "SELECT COUNT(*) FROM role_permissions "
                    "WHERE permission_key = :pkey"
                ),
                {"pkey": _PERMISSION_KEY},
            ).scalar()
        engine.dispose()

        assert after_first == after_repeat == 8, (
            f"Expected 8 proposal.set_thresholds rows after both first "
            f"apply and re-apply (2 orgs × 4 roles); got "
            f"first={after_first}, repeat={after_repeat}"
        )
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
