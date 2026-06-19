"""Phase 76c migration cycle + backfill test."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_REV = "b1c2d3e4f5a6"
_PRIOR = "a5b6c7d8e9f0"  # Phase 74a (current head before 76c)


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


def _columns(db_url: str, table: str) -> set[str]:
    engine = sa.create_engine(db_url)
    try:
        return {c["name"] for c in sa.inspect(engine).get_columns(table)}
    finally:
        engine.dispose()


def _build_pre(db_url: str) -> None:
    _create_all_subprocess(db_url)
    _run_alembic(db_url, "stamp", "head")
    _run_alembic(db_url, "downgrade", _PRIOR)


def test_upgrade_adds_country_column_and_cycle():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre(db_url)
        assert "verification_country" not in _columns(db_url, "users")
        _run_alembic(db_url, "upgrade", "head")
        assert "verification_country" in _columns(db_url, "users")
        _run_alembic(db_url, "downgrade", _PRIOR)
        assert "verification_country" not in _columns(db_url, "users")
        _run_alembic(db_url, "upgrade", "head")
        assert "verification_country" in _columns(db_url, "users")
    finally:
        try: os.unlink(path)
        except OSError: pass


def test_backfill_sets_us_for_state_verified_members():
    """The upgrade backfills verification_country='US' for members with a
    non-DEMO US state on file; null jurisdiction + the DEMO sentinel stay
    null."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre(db_url)  # users table at _PRIOR (no verification_country)
        engine = sa.create_engine(db_url)
        with engine.begin() as conn:
            # Insert minimal rows directly. Only the columns the backfill
            # reads/writes matter; the rest default at the DB layer.
            cols = (
                "id, username, display_name, email, password_hash, is_admin, "
                "user_type, delegation_strategy, email_verified, "
                "default_follow_policy, verification_state, "
                "verification_provenance, verification_jurisdiction, created_at"
            )
            base = (
                "0,'human','relevance_weighted',1,'require_approval'"
            )

            def _row(uid, prov, juris):
                j = "NULL" if juris is None else f"'{juris}'"
                return (
                    f"('{uid}','{uid}','{uid}','{uid}@t.ex','h',{base},"
                    f"'address_on_id','{prov}',{j}, CURRENT_TIMESTAMP)"
                )
            conn.execute(sa.text(
                f"INSERT INTO users ({cols}) VALUES "
                + ", ".join([
                    _row("u_ma", "didit", "MA"),
                    _row("u_none", "didit", None),
                    _row("u_demo", "demo_stub", "DEMO"),
                ])
            ))
        engine.dispose()

        _run_alembic(db_url, "upgrade", "head")

        engine = sa.create_engine(db_url)
        try:
            with engine.connect() as conn:
                rows = dict(conn.execute(sa.text(
                    "SELECT id, verification_country FROM users"
                )).all())
        finally:
            engine.dispose()
        assert rows["u_ma"] == "US"      # US state → backfilled
        assert rows["u_none"] is None    # no jurisdiction → untouched
        assert rows["u_demo"] is None    # DEMO sentinel excluded
    finally:
        try: os.unlink(path)
        except OSError: pass
