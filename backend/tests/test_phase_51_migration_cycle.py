"""Phase 51 migration cycle test."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_51_REVISION = "c8d3e1f56432"
_PRIOR_REVISION = "b9c2e0f43215"  # Phase 49a — proposal_creation_remap


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


def _build_pre_51(db_url: str) -> None:
    """Build pre-Phase-51 schema: create_tables (current models),
    stamp head, downgrade to the Phase 49a revision (Phase 51's
    downgrade drops the verification columns)."""
    _create_all_subprocess(db_url)
    _run_alembic(db_url, "stamp", "head")
    _run_alembic(db_url, "downgrade", _PRIOR_REVISION)


def test_phase_51_upgrade_adds_verification_columns():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_51(db_url)
        pre_cols = _columns(db_url, "users")
        assert "verification_state" not in pre_cols
        assert "verification_jurisdiction" not in pre_cols
        assert "verification_attestation_id" not in pre_cols
        assert "verification_nullifier" not in pre_cols
        assert "verification_provenance" not in pre_cols
        assert "verification_updated_at" not in pre_cols

        _run_alembic(db_url, "upgrade", "head")
        post_cols = _columns(db_url, "users")
        for c in (
            "verification_state",
            "verification_jurisdiction",
            "verification_attestation_id",
            "verification_nullifier",
            "verification_provenance",
            "verification_updated_at",
        ):
            assert c in post_cols, f"missing column after upgrade: {c}"
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase_51_upgrade_downgrade_upgrade_cycle():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_51(db_url)

        _run_alembic(db_url, "upgrade", "head")
        assert "verification_state" in _columns(db_url, "users")

        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        post_down = _columns(db_url, "users")
        for c in (
            "verification_state",
            "verification_jurisdiction",
            "verification_attestation_id",
            "verification_nullifier",
            "verification_provenance",
            "verification_updated_at",
        ):
            assert c not in post_down, f"column survived downgrade: {c}"

        _run_alembic(db_url, "upgrade", "head")
        assert "verification_state" in _columns(db_url, "users")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
