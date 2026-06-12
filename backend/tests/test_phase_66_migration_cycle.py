"""Phase 66 — proposals.approval_winner_config migration cycle test.

Subprocess upgrade → downgrade → upgrade on SQLite proving the
``a3f6c8e21b94`` migration is reversible, plus the explicit parity
assertion that PRE-EXISTING proposal rows read
``approval_winner_config=NULL`` after upgrade (NULL = legacy
single-winner behavior; no data backfill step).

Pattern mirrors test_phase_65_migration_cycle.py.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_REV = "a3f6c8e21b94"
_PRIOR = "e7a9c4d2b8f1"  # Phase 65


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


def _build_pre(db_url: str) -> None:
    """Build schema + stamp + downgrade to the migration prior (this
    exercises downgrade() once, dropping the new column)."""
    _create_all_subprocess(db_url)
    _run_alembic(db_url, "stamp", "head")
    _run_alembic(db_url, "downgrade", _PRIOR)


def _proposals_columns(db_url: str) -> set[str]:
    engine = sa.create_engine(db_url)
    try:
        insp = sa.inspect(engine)
        return {c["name"] for c in insp.get_columns("proposals")}
    finally:
        engine.dispose()


def _seed_pre_existing_proposal(db_url: str, *, proposal_id: str) -> None:
    """Insert a proposal row at the pre-66 schema (no
    approval_winner_config). The author FK is not enforced on this raw
    SQLite connection (PRAGMA foreign_keys defaults to OFF), so no user
    row is needed."""
    engine = sa.create_engine(db_url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text(
                "INSERT INTO proposals "
                "(id, title, body, author_id, status, voting_method, "
                " num_winners, pass_threshold, quorum_threshold, "
                " is_cosign_gated, is_election, election_slate_mode, "
                " created_at, updated_at) "
                "VALUES (:id, 'Pre66', '', 'u-old', 'draft', 'approval', "
                "        1, 0.5, 0.4, 0, 0, 'fill_vacancies', "
                "        '2026-01-01', '2026-01-01')"
            ), {"id": proposal_id})
    finally:
        engine.dispose()


def _read_config(db_url: str, proposal_id: str):
    engine = sa.create_engine(db_url)
    try:
        with engine.begin() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT approval_winner_config FROM proposals "
                    "WHERE id=:i"
                ),
                {"i": proposal_id},
            ).first()
            assert row is not None
            return row[0]
    finally:
        engine.dispose()


def test_phase_66_migration_cycle():
    """upgrade → downgrade → upgrade, with the existing-rows parity
    assertion (pre-existing proposal reads approval_winner_config=NULL
    after upgrade — NULL = legacy single-winner behavior)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre(db_url)
        assert "approval_winner_config" not in _proposals_columns(db_url), (
            "downgrade to prior did not drop approval_winner_config"
        )

        # A proposal created BEFORE the Phase 66 migration ran.
        _seed_pre_existing_proposal(db_url, proposal_id="p-old")

        # Upgrade — column added; existing row reads NULL (legacy
        # single-winner), no data backfill step.
        _run_alembic(db_url, "upgrade", _REV)
        assert "approval_winner_config" in _proposals_columns(db_url)
        assert _read_config(db_url, "p-old") is None, (
            "pre-existing proposal should read approval_winner_config "
            "NULL after upgrade"
        )

        # Downgrade — column dropped, row survives.
        _run_alembic(db_url, "downgrade", _PRIOR)
        assert "approval_winner_config" not in _proposals_columns(db_url)
        engine = sa.create_engine(db_url)
        try:
            with engine.begin() as conn:
                n = conn.execute(
                    sa.text("SELECT COUNT(*) FROM proposals"),
                ).scalar()
                assert n == 1
        finally:
            engine.dispose()

        # Second upgrade — idempotent re-add, same NULL default.
        _run_alembic(db_url, "upgrade", _REV)
        assert "approval_winner_config" in _proposals_columns(db_url)
        assert _read_config(db_url, "p-old") is None
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
