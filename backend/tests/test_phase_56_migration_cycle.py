"""Phase 56 migration cycle test — additive nullable purpose + category."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_56_REVISION = "b3c4d5e6f7a8"
_PRIOR_REVISION = "a2b3c4d5e6f7"  # Phase 52b


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


def _build_pre_56(db_url: str) -> None:
    _create_all_subprocess(db_url)
    _run_alembic(db_url, "stamp", "head")
    _run_alembic(db_url, "downgrade", _PRIOR_REVISION)


def test_phase_56_upgrade_adds_purpose_and_category():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_56(db_url)
        pre = _columns(db_url, "topics")
        assert "purpose" not in pre
        assert "category" not in pre

        _run_alembic(db_url, "upgrade", "head")
        post = _columns(db_url, "topics")
        assert "purpose" in post
        assert "category" in post
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase_56_downgrade_upgrade_cycle():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_56(db_url)
        _run_alembic(db_url, "upgrade", "head")
        assert "purpose" in _columns(db_url, "topics")
        assert "category" in _columns(db_url, "topics")

        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        post_down = _columns(db_url, "topics")
        assert "purpose" not in post_down
        assert "category" not in post_down

        _run_alembic(db_url, "upgrade", "head")
        assert "purpose" in _columns(db_url, "topics")
        assert "category" in _columns(db_url, "topics")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase_56_existing_topic_rows_get_null_purpose_and_category():
    """Pre-Phase-33-style topics (no purpose, no category) created BEFORE
    the migration should serialize cleanly post-upgrade with NULL on both
    new columns. This is the graceful-NULL-handling property the spec
    cites for skipping the backfill."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_56(db_url)
        # Insert a row at the pre-Phase-56 column shape (no purpose / no
        # category) using raw SQL via subprocess (avoids ORM picking up
        # the new model columns and rejecting the insert).
        seed_code = (
            f"import os; os.environ['DATABASE_URL']={db_url!r}\n"
            "import sqlalchemy as sa\n"
            f"engine = sa.create_engine({db_url!r})\n"
            "with engine.begin() as conn:\n"
            "    conn.execute(sa.text(\""
            "INSERT INTO topics (id, name, color) "
            "VALUES ('legacy-1', 'Legacy Topic', '#abcdef')\""
            "))\n"
        )
        seed_res = subprocess.run(
            [sys.executable, "-c", seed_code],
            cwd=_BACKEND_DIR, capture_output=True, text=True,
        )
        assert seed_res.returncode == 0, seed_res.stderr

        _run_alembic(db_url, "upgrade", "head")

        check_code = (
            f"import os; os.environ['DATABASE_URL']={db_url!r}\n"
            "import sqlalchemy as sa\n"
            f"engine = sa.create_engine({db_url!r})\n"
            "with engine.begin() as conn:\n"
            "    row = conn.execute(sa.text("
            "\"SELECT purpose, category FROM topics WHERE id='legacy-1'\""
            ")).first()\n"
            "    assert row is not None, 'legacy row vanished'\n"
            "    assert row[0] is None, f'purpose={row[0]!r}'\n"
            "    assert row[1] is None, f'category={row[1]!r}'\n"
            "    print('LEGACY OK')\n"
        )
        check_res = subprocess.run(
            [sys.executable, "-c", check_code],
            cwd=_BACKEND_DIR, capture_output=True, text=True,
        )
        assert check_res.returncode == 0, check_res.stderr
        assert "LEGACY OK" in check_res.stdout
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
