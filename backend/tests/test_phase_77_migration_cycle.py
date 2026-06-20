"""Phase 77 migration cycle + permission-backfill parity test."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_REV = "c2d3e4f5a6b7"
_PRIOR = "b1c2d3e4f5a6"  # Phase 76c
_TABLES = ("conversations", "messages", "conversation_reads", "message_blocks")


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


def _tables(db_url: str) -> set[str]:
    engine = sa.create_engine(db_url)
    try:
        return set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()


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


def test_upgrade_creates_tables_and_cycles():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre(db_url)
        assert not any(t in _tables(db_url) for t in _TABLES)
        assert "dm_disabled" not in _columns(db_url, "users")
        _run_alembic(db_url, "upgrade", "head")
        assert all(t in _tables(db_url) for t in _TABLES)
        assert "dm_disabled" in _columns(db_url, "users")
        _run_alembic(db_url, "downgrade", _PRIOR)
        assert not any(t in _tables(db_url) for t in _TABLES)
        assert "dm_disabled" not in _columns(db_url, "users")
        _run_alembic(db_url, "upgrade", "head")
        assert all(t in _tables(db_url) for t in _TABLES)
    finally:
        try: os.unlink(path)
        except OSError: pass


def test_backfill_grants_org_inbox_view_to_existing_steward_admin():
    """An existing org (roles present, no org_inbox.view rows) gets the key
    backfilled onto steward + admin — and NOT onto moderator/member."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre(db_url)  # at prior revision; roles/role_permissions exist
        engine = sa.create_engine(db_url)
        with engine.begin() as conn:
            conn.execute(sa.text(
                "INSERT INTO organizations (id, name, slug, description, "
                "created_at, updated_at) VALUES "
                "('org1','Org One','org-one','', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))
            for rid, sk in [
                ("r_steward", "steward"), ("r_admin", "admin"),
                ("r_mod", "moderator"), ("r_member", "member"),
            ]:
                conn.execute(sa.text(
                    "INSERT INTO roles (id, org_id, name, system_key, "
                    "is_system_preset, display_order, created_at) VALUES "
                    "(:id,'org1',:nm,:sk,1,0, CURRENT_TIMESTAMP)"
                ), {"id": rid, "nm": sk.title(), "sk": sk})
        engine.dispose()

        _run_alembic(db_url, "upgrade", "head")

        engine = sa.create_engine(db_url)
        try:
            with engine.connect() as conn:
                rows = conn.execute(sa.text(
                    "SELECT r.system_key, rp.enabled FROM role_permissions rp "
                    "JOIN roles r ON rp.role_id = r.id "
                    "WHERE rp.permission_key = 'org_inbox.view'"
                )).fetchall()
        finally:
            engine.dispose()
        granted = {sk for sk, _ in rows}
        assert granted == {"steward", "admin"}, granted
        assert all(bool(en) for _, en in rows)
    finally:
        try: os.unlink(path)
        except OSError: pass
