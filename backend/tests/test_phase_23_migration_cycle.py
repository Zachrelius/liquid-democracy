"""Phase 23 migration cycle: verify upgrade -> downgrade -> upgrade for
the demo-reset-infrastructure column additions.

Pattern mirrors ``test_phase_20_migration_cycle.py``:

1. Build today's schema via ``create_tables()`` (which reflects models.py,
   including the Phase 23 column additions).
2. Drop the Phase 23 columns / index manually to simulate a
   pre-Phase-23 state.
3. Stamp at the prior revision (``9a8920b1f3c7`` = Phase 20 head).
4. Upgrade to Phase 23 (``c7e8a3d419f5``).
5. Assert all 8 organizations columns + the index + users.headshot_url
   exist post-upgrade.
6. Seed an organization row + a user row to verify defaults work.
7. Downgrade to the prior revision.
8. Assert all Phase 23 columns + the index are gone.
9. Re-upgrade. Assert idempotent: columns return; seeded row's other
   fields are preserved.
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
_PHASE_23_REVISION = "c7e8a3d419f5"
_PRIOR_REVISION = "9a8920b1f3c7"

# Columns added to organizations in Phase 23 B1.
_NEW_ORG_COLUMNS = (
    "is_demo",
    "is_demo_resetting",
    "governance_type",
    "display_order",
    "personas",
    "brand_color",
    "brand_secondary_color",
    "logo_url",
)
_NEW_INDEX_NAME = "ix_organizations_is_demo"
_NEW_USER_COLUMN = "headshot_url"


def _run_alembic(db_url: str, *args: str) -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    res = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=_BACKEND_DIR, env=env, capture_output=True, text=True,
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
        cwd=_BACKEND_DIR, capture_output=True, text=True,
    )
    assert res.returncode == 0, (
        f"create_tables failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )


def _has_column(engine, table: str, column: str) -> bool:
    insp = sa.inspect(engine)
    if table not in set(insp.get_table_names()):
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


def _has_index(engine, table: str, index_name: str) -> bool:
    insp = sa.inspect(engine)
    if table not in set(insp.get_table_names()):
        return False
    return index_name in {ix["name"] for ix in insp.get_indexes(table)}


def _build_pre_phase_23_schema(db_url: str) -> None:
    """Build today's schema (which has the Phase 23 columns) then drop
    the Phase 23 columns + index to simulate the pre-Phase-23 state.

    SQLite >= 3.35 supports ``ALTER TABLE ... DROP COLUMN`` natively. The
    bundled SQLite in CPython 3.10+ on Windows is well above that; if
    this test ever runs on an older SQLite, swap to a manual rebuild.
    """
    _create_all_subprocess(db_url)
    engine = sa.create_engine(db_url)
    try:
        with engine.begin() as conn:
            # Drop the index first (or the column-drop will complain on
            # some SQLite builds).
            existing_indexes = {
                ix["name"] for ix in sa.inspect(conn).get_indexes("organizations")
            }
            if _NEW_INDEX_NAME in existing_indexes:
                conn.execute(sa.text(f"DROP INDEX {_NEW_INDEX_NAME}"))

            # Drop each Phase 23 organizations column.
            existing_org_cols = {
                c["name"] for c in sa.inspect(conn).get_columns("organizations")
            }
            for col in _NEW_ORG_COLUMNS:
                if col in existing_org_cols:
                    conn.execute(
                        sa.text(f"ALTER TABLE organizations DROP COLUMN {col}")
                    )

            # Drop users.headshot_url.
            existing_user_cols = {
                c["name"] for c in sa.inspect(conn).get_columns("users")
            }
            if _NEW_USER_COLUMN in existing_user_cols:
                conn.execute(
                    sa.text(f"ALTER TABLE users DROP COLUMN {_NEW_USER_COLUMN}")
                )
    finally:
        engine.dispose()
    _run_alembic(db_url, "stamp", _PRIOR_REVISION)


def _seed_minimal_org_and_user(db_url: str) -> tuple[str, str]:
    """Insert a minimal organization + user pair. Returns (org_id, user_id).

    Used to verify defaults / value preservation across the migration cycle.
    """
    engine = sa.create_engine(db_url)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    org_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    try:
        with engine.begin() as conn:
            conn.execute(sa.text(
                "INSERT INTO users (id, username, display_name, "
                "password_hash, is_admin, user_type, "
                "delegation_strategy, email_verified, "
                "default_follow_policy, created_at) "
                "VALUES (:id, :u, 'U', 'x', 0, 'human', "
                "'strict_precedence', 0, 'require_approval', :now)"
            ), {"id": user_id, "u": f"u_{user_id[:6]}", "now": now})

            conn.execute(sa.text(
                "INSERT INTO organizations "
                "(id, name, slug, description, join_policy, settings, "
                "parent_org_id, created_at, updated_at) "
                "VALUES (:id, 'Org', :slug, '', 'open', '{}', "
                "NULL, :now, :now)"
            ), {"id": org_id, "slug": f"org-{org_id[:6]}", "now": now})
    finally:
        engine.dispose()
    return org_id, user_id


def test_phase23_upgrade_adds_all_columns():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_phase_23_schema(db_url)
        engine = sa.create_engine(db_url)
        try:
            # Pre-state: none of the new columns / index exist.
            for col in _NEW_ORG_COLUMNS:
                assert not _has_column(engine, "organizations", col), (
                    f"pre-upgrade: organizations.{col} should be absent"
                )
            assert not _has_index(engine, "organizations", _NEW_INDEX_NAME)
            assert not _has_column(engine, "users", _NEW_USER_COLUMN)
        finally:
            engine.dispose()

        _run_alembic(db_url, "upgrade", _PHASE_23_REVISION)

        engine = sa.create_engine(db_url)
        try:
            for col in _NEW_ORG_COLUMNS:
                assert _has_column(engine, "organizations", col), (
                    f"post-upgrade: organizations.{col} should exist"
                )
            assert _has_index(engine, "organizations", _NEW_INDEX_NAME)
            assert _has_column(engine, "users", _NEW_USER_COLUMN)
        finally:
            engine.dispose()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase23_upgrade_applies_defaults_to_existing_rows():
    """Seed an org + user BEFORE upgrade; after upgrade, the new NOT NULL
    Boolean columns should have the server default applied (False / 0).
    Nullable columns should be NULL.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_phase_23_schema(db_url)
        org_id, user_id = _seed_minimal_org_and_user(db_url)

        _run_alembic(db_url, "upgrade", _PHASE_23_REVISION)

        engine = sa.create_engine(db_url)
        try:
            with engine.connect() as conn:
                row = conn.execute(sa.text(
                    "SELECT is_demo, is_demo_resetting, governance_type, "
                    "display_order, personas, brand_color, "
                    "brand_secondary_color, logo_url "
                    "FROM organizations WHERE id = :i"
                ), {"i": org_id}).first()
                user_row = conn.execute(sa.text(
                    "SELECT headshot_url FROM users WHERE id = :i"
                ), {"i": user_id}).first()
        finally:
            engine.dispose()

        assert row is not None
        # is_demo, is_demo_resetting: default False (0 on SQLite).
        assert bool(row[0]) is False
        assert bool(row[1]) is False
        # All nullable fields default to NULL.
        assert row[2] is None  # governance_type
        assert row[3] is None  # display_order
        assert row[4] is None  # personas
        assert row[5] is None  # brand_color
        assert row[6] is None  # brand_secondary_color
        assert row[7] is None  # logo_url

        assert user_row is not None
        assert user_row[0] is None  # headshot_url
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase23_upgrade_downgrade_upgrade_cycle():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_phase_23_schema(db_url)
        org_id, user_id = _seed_minimal_org_and_user(db_url)

        # 1. Upgrade.
        _run_alembic(db_url, "upgrade", _PHASE_23_REVISION)
        engine = sa.create_engine(db_url)
        try:
            for col in _NEW_ORG_COLUMNS:
                assert _has_column(engine, "organizations", col)
            assert _has_index(engine, "organizations", _NEW_INDEX_NAME)
            assert _has_column(engine, "users", _NEW_USER_COLUMN)
        finally:
            engine.dispose()

        # 2. Downgrade to the prior revision.
        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        engine = sa.create_engine(db_url)
        try:
            for col in _NEW_ORG_COLUMNS:
                assert not _has_column(engine, "organizations", col), (
                    f"post-downgrade: organizations.{col} should be gone"
                )
            assert not _has_index(
                engine, "organizations", _NEW_INDEX_NAME
            )
            assert not _has_column(engine, "users", _NEW_USER_COLUMN)
            # The seeded organization + user rows must still exist (we
            # only dropped columns, not data).
            with engine.connect() as conn:
                org_count = conn.execute(sa.text(
                    "SELECT COUNT(*) FROM organizations WHERE id = :i"
                ), {"i": org_id}).scalar()
                user_count = conn.execute(sa.text(
                    "SELECT COUNT(*) FROM users WHERE id = :i"
                ), {"i": user_id}).scalar()
        finally:
            engine.dispose()
        assert org_count == 1
        assert user_count == 1

        # 3. Re-upgrade: idempotent. Columns and index return; seeded rows
        # take the server defaults.
        _run_alembic(db_url, "upgrade", _PHASE_23_REVISION)
        engine = sa.create_engine(db_url)
        try:
            for col in _NEW_ORG_COLUMNS:
                assert _has_column(engine, "organizations", col)
            assert _has_index(engine, "organizations", _NEW_INDEX_NAME)
            assert _has_column(engine, "users", _NEW_USER_COLUMN)
            with engine.connect() as conn:
                row = conn.execute(sa.text(
                    "SELECT is_demo, is_demo_resetting "
                    "FROM organizations WHERE id = :i"
                ), {"i": org_id}).first()
        finally:
            engine.dispose()
        assert row is not None
        assert bool(row[0]) is False
        assert bool(row[1]) is False
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
