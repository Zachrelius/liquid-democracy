"""Phase 52d migration cycle test."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_52D_REVISION = "f1a2b3c4d5e6"
_PRIOR_REVISION = "e0a1b2c3d4f5"  # Phase 52a
DOC_NUMBER_UNIQUE_INDEX = "ix_users_doc_number_hash_unique"


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


def _indexes(db_url: str, table: str) -> set[str]:
    engine = sa.create_engine(db_url)
    try:
        return {ix["name"] for ix in sa.inspect(engine).get_indexes(table)}
    finally:
        engine.dispose()


def _build_pre_52d(db_url: str) -> None:
    _create_all_subprocess(db_url)
    _run_alembic(db_url, "stamp", "head")
    _run_alembic(db_url, "downgrade", _PRIOR_REVISION)


def test_phase_52d_upgrade_adds_columns_and_indexes():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_52d(db_url)
        pre = _columns(db_url, "users")
        assert "doc_number_hash" not in pre
        assert "name_dob_address_hash" not in pre
        assert "name_dob_hash" not in pre
        assert "uniqueness_strength" not in pre

        _run_alembic(db_url, "upgrade", _PHASE_52D_REVISION)
        post = _columns(db_url, "users")
        assert "doc_number_hash" in post
        assert "name_dob_address_hash" in post
        assert "name_dob_hash" in post
        assert "uniqueness_strength" in post
        # Deprecated column NOT dropped (we keep it to avoid the
        # partial-unique drop risk on PG).
        assert "verification_nullifier" in post

        idx = _indexes(db_url, "users")
        assert DOC_NUMBER_UNIQUE_INDEX in idx
    finally:
        try: os.unlink(path)
        except OSError: pass


def test_phase_52d_downgrade_upgrade_cycle():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_52d(db_url)
        _run_alembic(db_url, "upgrade", _PHASE_52D_REVISION)
        assert "doc_number_hash" in _columns(db_url, "users")
        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        post_down = _columns(db_url, "users")
        for c in ("doc_number_hash", "name_dob_address_hash",
                  "name_dob_hash", "uniqueness_strength"):
            assert c not in post_down
        _run_alembic(db_url, "upgrade", _PHASE_52D_REVISION)
        assert "doc_number_hash" in _columns(db_url, "users")
        assert DOC_NUMBER_UNIQUE_INDEX in _indexes(db_url, "users")
    finally:
        try: os.unlink(path)
        except OSError: pass


def test_doc_number_hash_unique_allows_multiple_nulls():
    """Same partial-unique tolerance check Phase 52a's migration test
    runs for the nullifier index: on SQLite the unique index treats
    NULLs as distinct; the PG partial-WHERE branch is exercised by
    PG smoke."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    code = (
        f"import os; os.environ['DATABASE_URL']={db_url!r}\n"
        "import models\n"
        "from database import SessionLocal\n"
        "s = SessionLocal()\n"
        "u1 = models.User(username='a', email='a@example.com', password_hash='x', display_name='a')\n"
        "u2 = models.User(username='b', email='b@example.com', password_hash='x', display_name='b')\n"
        "s.add_all([u1, u2]); s.commit()\n"
        "assert u1.doc_number_hash is None\n"
        "assert u2.doc_number_hash is None\n"
        "s.close()\n"
    )
    try:
        _build_pre_52d(db_url)
        # Upgrade fully to head — the ORM ``models.User`` carries
        # later-phase columns (legal_first_name, age band fields,
        # etc.) that aren't in the 52d-only schema, so the ORM-based
        # insert needs the full schema. The "multi-NULL on
        # doc_number_hash" property holds at every later revision
        # too (52h Stage 2 drops the UNIQUE index, making NULL
        # tolerance trivially preserved).
        _run_alembic(db_url, "upgrade", "head")
        res = subprocess.run(
            [sys.executable, "-c", code],
            cwd=_BACKEND_DIR, capture_output=True, text=True,
        )
        assert res.returncode == 0, (
            f"multi-null insert failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
        )
    finally:
        try: os.unlink(path)
        except OSError: pass
