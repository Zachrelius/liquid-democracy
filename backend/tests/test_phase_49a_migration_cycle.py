"""Phase 49a migration cycle test."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_49A_REVISION = "b9c2e0f43215"
_PRIOR_REVISION = "a7c1d8e94521"  # Phase 49 (scheduled / term elections)


def _run_alembic(db_url: str, *args: str) -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    res = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=_BACKEND_DIR, env=env,
        capture_output=True, text=True,
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


def _columns(db_url: str, table: str) -> set[str]:
    engine = sa.create_engine(db_url)
    try:
        return {c["name"] for c in sa.inspect(engine).get_columns(table)}
    finally:
        engine.dispose()


def _build_pre_49a(db_url: str) -> None:
    """Build the pre-Phase-49a schema: create today's schema via
    ``create_tables`` (note: today's schema NO LONGER has
    ``proposal_creation_mode`` on the model, so create_all skips it),
    stamp at head, downgrade to the Phase 49 revision (Phase 49a's
    downgrade re-adds the column). Net: a schema matching the pre-49a
    end-state with the column present."""
    _create_all_subprocess(db_url)
    _run_alembic(db_url, "stamp", "head")
    _run_alembic(db_url, "downgrade", _PRIOR_REVISION)


def test_phase_49a_upgrade_drops_proposal_creation_mode():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_49a(db_url)
        assert "proposal_creation_mode" in _columns(db_url, "organizations"), (
            "pre-Phase-49a state should have the column present"
        )

        _run_alembic(db_url, "upgrade", "head")
        assert "proposal_creation_mode" not in _columns(db_url, "organizations"), (
            "Phase 49a's upgrade should drop the column"
        )
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase_49a_upgrade_downgrade_upgrade_cycle():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_49a(db_url)

        _run_alembic(db_url, "upgrade", "head")
        assert "proposal_creation_mode" not in _columns(db_url, "organizations")

        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        assert "proposal_creation_mode" in _columns(db_url, "organizations")

        _run_alembic(db_url, "upgrade", "head")
        assert "proposal_creation_mode" not in _columns(db_url, "organizations")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
