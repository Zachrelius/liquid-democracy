"""Phase 90e migration cycle: adds proposals.is_issuance / issuance_payload /
issuance_executed."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_90E = "b4c5d6e7f8a9"
_PRIOR = "a3b4c5d6e7f8"
_NEW = {"is_issuance", "issuance_payload", "issuance_executed"}


def _run(db_url, *args):
    env = dict(os.environ); env["DATABASE_URL"] = db_url
    res = subprocess.run([sys.executable, "-m", "alembic", *args],
                         cwd=_BACKEND_DIR, env=env, capture_output=True, text=True)
    assert res.returncode == 0, f"{' '.join(args)}:\n{res.stdout}\n{res.stderr}"


def _create_all(db_url):
    code = (f"import os; os.environ['DATABASE_URL']={db_url!r}; "
            "from database import create_tables; create_tables()")
    res = subprocess.run([sys.executable, "-c", code], cwd=_BACKEND_DIR,
                         capture_output=True, text=True)
    assert res.returncode == 0, f"{res.stdout}\n{res.stderr}"


def _cols(db_url, table):
    e = sa.create_engine(db_url)
    try:
        return {c["name"] for c in sa.inspect(e).get_columns(table)}
    finally:
        e.dispose()


def test_phase90e_migration_cycle():
    fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _create_all(db_url)
        _run(db_url, "stamp", _PRIOR)
        _run(db_url, "upgrade", _PHASE_90E)
        assert _NEW <= _cols(db_url, "proposals")
        _run(db_url, "downgrade", _PRIOR)
        assert not (_NEW & _cols(db_url, "proposals"))
        _run(db_url, "upgrade", _PHASE_90E)
        assert _NEW <= _cols(db_url, "proposals")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
