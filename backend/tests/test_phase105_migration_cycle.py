from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PRIOR = "e7f8a9b0c1d2"


def _alembic(db_url: str, *args: str) -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=_BACKEND_DIR,
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _columns(url: str) -> set[str]:
    engine = sa.create_engine(url)
    try:
        return {column["name"] for column in sa.inspect(engine).get_columns("proposals")}
    finally:
        engine.dispose()


def test_phase105_upgrade_downgrade_upgrade_cycle():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    url = f"sqlite:///{path}"
    try:
        env = dict(os.environ)
        env["DATABASE_URL"] = url
        create = subprocess.run(
            [sys.executable, "-c", "from database import create_tables; create_tables()"],
            cwd=_BACKEND_DIR, env=env, capture_output=True, text=True,
        )
        assert create.returncode == 0, create.stdout + create.stderr
        _alembic(url, "stamp", "head")
        _alembic(url, "downgrade", _PRIOR)
        assert "verification_require_residency" not in _columns(url)
        _alembic(url, "upgrade", "head")
        assert "verification_require_residency" in _columns(url)
        _alembic(url, "downgrade", _PRIOR)
        assert "verification_require_residency" not in _columns(url)
        _alembic(url, "upgrade", "head")
        assert "verification_require_residency" in _columns(url)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
