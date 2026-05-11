"""Phase 20 migration cycle: rename Proposal.sustained_majority_enabled
-> stable_result_required.

Pattern mirrors Phase 15's migration-cycle test: bootstrap schema via
`create_tables()`, stamp at the prior revision, optionally seed data
that the rename should preserve, then upgrade -> assert post-state ->
downgrade -> assert pre-state -> re-upgrade.

The load-bearing assertions are:

1. Post-upgrade: column exists as `stable_result_required`; the legacy
   `sustained_majority_enabled` column is gone.
2. Post-upgrade: existing values (NULL / True / False) are preserved.
3. Post-downgrade: column comes back as `sustained_majority_enabled`;
   `stable_result_required` is gone; values still preserved.
4. Re-upgrade: idempotent; values preserved again.
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
_PHASE_20_REVISION = "9a8920b1f3c7"
_PRIOR_REVISION = "47eb5d38eb58"


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


def _build_pre_phase_20_schema(db_url: str) -> None:
    """Build today's schema via create_all, then drop the renamed column
    and re-add it under the legacy name, then stamp at the prior revision.

    Because models.py reflects the post-Phase-20 column name, we need
    to manually rebuild the column under the legacy name to simulate
    a pre-Phase-20 state.
    """
    _create_all_subprocess(db_url)
    engine = sa.create_engine(db_url)
    try:
        with engine.begin() as conn:
            # On SQLite we cannot drop / rename a column with raw ALTER;
            # use batch-style rebuild via a temp column. Simplest: run
            # the inverse of the Phase 20 upgrade as raw SQL.
            # SQLite >=3.25 supports ALTER TABLE ... RENAME COLUMN.
            conn.execute(sa.text(
                "ALTER TABLE proposals "
                "RENAME COLUMN stable_result_required "
                "TO sustained_majority_enabled"
            ))
    finally:
        engine.dispose()
    _run_alembic(db_url, "stamp", _PRIOR_REVISION)


def _seed_proposal_with_value(db_url: str, value) -> str:
    """Insert a minimum proposal row with the given sustained_majority_enabled
    value (None, True, or False). Returns the proposal id.
    """
    engine = sa.create_engine(db_url)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    user_id = str(uuid.uuid4())
    org_id = str(uuid.uuid4())
    prop_id = str(uuid.uuid4())
    try:
        with engine.begin() as conn:
            conn.execute(sa.text(
                "INSERT INTO users (id, username, display_name, "
                "password_hash, is_admin, user_type, "
                "delegation_strategy, email_verified, "
                "default_follow_policy, created_at) "
                "VALUES (:id, :u, 'u', 'x', 0, 'human', "
                "'strict_precedence', 0, 'require_approval', :now)"
            ), {"id": user_id, "u": f"u_{prop_id[:6]}", "now": now})

            conn.execute(sa.text(
                "INSERT INTO organizations "
                "(id, name, slug, description, join_policy, settings, "
                "parent_org_id, created_at, updated_at) "
                "VALUES (:id, 'Org', :slug, '', 'open', '{}', "
                "NULL, :now, :now)"
            ), {"id": org_id, "slug": f"org-{prop_id[:6]}", "now": now})

            conn.execute(sa.text(
                "INSERT INTO proposals "
                "(id, title, body, author_id, org_id, status, "
                "voting_method, num_winners, pass_threshold, "
                "quorum_threshold, sustained_majority_enabled, "
                "created_at, updated_at) "
                "VALUES (:id, 'T', '', :uid, :oid, 'draft', "
                "'binary', 1, 0.5, 0.4, :smv, :now, :now)"
            ), {"id": prop_id, "uid": user_id, "oid": org_id,
                "smv": value, "now": now})
    finally:
        engine.dispose()
    return prop_id


def test_phase20_upgrade_renames_column():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_phase_20_schema(db_url)
        engine = sa.create_engine(db_url)
        try:
            assert _has_column(engine, "proposals", "sustained_majority_enabled")
            assert not _has_column(engine, "proposals", "stable_result_required")
        finally:
            engine.dispose()

        _run_alembic(db_url, "upgrade", _PHASE_20_REVISION)

        engine = sa.create_engine(db_url)
        try:
            assert _has_column(engine, "proposals", "stable_result_required")
            assert not _has_column(engine, "proposals", "sustained_majority_enabled")
        finally:
            engine.dispose()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase20_upgrade_preserves_values():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_phase_20_schema(db_url)
        # Seed three proposals with the three possible values.
        p_null = _seed_proposal_with_value(db_url, None)
        p_true = _seed_proposal_with_value(db_url, True)
        p_false = _seed_proposal_with_value(db_url, False)

        _run_alembic(db_url, "upgrade", _PHASE_20_REVISION)

        engine = sa.create_engine(db_url)
        try:
            with engine.connect() as conn:
                rows = conn.execute(sa.text(
                    "SELECT id, stable_result_required FROM proposals "
                    "WHERE id IN (:a, :b, :c)"
                ), {"a": p_null, "b": p_true, "c": p_false}).fetchall()
        finally:
            engine.dispose()

        by_id = {r[0]: r[1] for r in rows}
        # SQLite stores Booleans as 0/1; None preserved as None.
        assert by_id[p_null] is None
        assert bool(by_id[p_true]) is True
        assert bool(by_id[p_false]) is False
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase20_upgrade_downgrade_upgrade_cycle():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_phase_20_schema(db_url)
        p_true = _seed_proposal_with_value(db_url, True)

        # 1. Upgrade.
        _run_alembic(db_url, "upgrade", _PHASE_20_REVISION)
        engine = sa.create_engine(db_url)
        try:
            assert _has_column(engine, "proposals", "stable_result_required")
            assert not _has_column(engine, "proposals", "sustained_majority_enabled")
        finally:
            engine.dispose()

        # 2. Downgrade to prior revision.
        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        engine = sa.create_engine(db_url)
        try:
            assert _has_column(engine, "proposals", "sustained_majority_enabled")
            assert not _has_column(engine, "proposals", "stable_result_required")
            with engine.connect() as conn:
                row = conn.execute(sa.text(
                    "SELECT sustained_majority_enabled FROM proposals "
                    "WHERE id = :i"
                ), {"i": p_true}).first()
        finally:
            engine.dispose()
        assert row is not None and bool(row[0]) is True

        # 3. Re-upgrade: idempotent.
        _run_alembic(db_url, "upgrade", _PHASE_20_REVISION)
        engine = sa.create_engine(db_url)
        try:
            assert _has_column(engine, "proposals", "stable_result_required")
            with engine.connect() as conn:
                row = conn.execute(sa.text(
                    "SELECT stable_result_required FROM proposals "
                    "WHERE id = :i"
                ), {"i": p_true}).first()
        finally:
            engine.dispose()
        assert row is not None and bool(row[0]) is True
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
