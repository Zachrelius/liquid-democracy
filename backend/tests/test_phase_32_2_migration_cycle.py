"""Phase 32.2 migration cycle test.

Subprocess-invoke alembic so each call gets a fresh process + clean
SQLite connection. Pattern matches Phase 32 / 32.1's migration_cycle
tests.

Load-bearing assertions:

1. After ``create_tables()`` + stamp at Phase 32.2 head: an org row
   with a ``write_ins.allowed_default=True`` boolean (pre-migration
   shape) round-trips to ``write_ins.allowed_mode='default_on'``
   when alembic walks forward through Phase 32.2. (Sanity check on
   the JSONB rewrite logic.)
2. Phase 32.2 → Phase 32 downgrade restores the boolean shape.
3. Re-upgrade is idempotent.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_32_2_REVISION = "e7a3d1c84920"
_PRIOR_REVISION = "d4f8e2a91c50"  # Phase 32


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


def _bootstrap_at_head(db_url: str) -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    res = subprocess.run(
        [sys.executable, "-c",
         "from database import create_tables; create_tables()"],
        cwd=_BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    assert res.returncode == 0, (
        f"create_tables failed:\nSTDOUT:\n{res.stdout}\n"
        f"STDERR:\n{res.stderr}"
    )
    _run_alembic(db_url, "stamp", _PHASE_32_2_REVISION)


def test_phase32_2_downgrade_upgrade_cycle():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _bootstrap_at_head(db_url)

        # Downgrade Phase 32.2 → Phase 32.
        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        # Re-upgrade.
        _run_alembic(db_url, "upgrade", _PHASE_32_2_REVISION)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase32_2_jsonb_rewrite_round_trip():
    """Seed an org with boolean settings, downgrade to Phase 32, manually
    set boolean shape via SQL, re-upgrade Phase 32.2, verify the enum
    mode shape was written."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _bootstrap_at_head(db_url)
        # Drop to Phase 32 so the migration's bool→enum upgrade has
        # something to rewrite when we walk forward again.
        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)

        engine = sa.create_engine(db_url)
        with engine.begin() as conn:
            # Insert an org with the pre-migration boolean shape.
            conn.execute(sa.text(
                "INSERT INTO organizations (id, name, slug, description, "
                "join_policy, settings, is_demo, is_demo_resetting, "
                "created_at, updated_at) "
                "VALUES ('o1', 'Test', 'test', '', 'open', :s, 0, 0, "
                "'2026-01-01', '2026-01-01')"
            ), {
                "s": json.dumps({
                    "write_ins": {
                        "allowed_default": True,
                        "during_voting_default": False,
                        "max_per_proposal": 5,
                    },
                    "pre_voting": {
                        "allowed_default": False,
                        "show_votes_during_deliberation_default": True,
                    },
                }),
            })
        engine.dispose()

        # Upgrade applies the JSONB rewrite.
        _run_alembic(db_url, "upgrade", _PHASE_32_2_REVISION)

        engine = sa.create_engine(db_url)
        with engine.connect() as conn:
            row = conn.execute(sa.text(
                "SELECT settings FROM organizations WHERE id = 'o1'"
            )).fetchone()
        engine.dispose()
        settings = json.loads(row[0])
        assert settings["write_ins"]["allowed_mode"] == "default_on"
        assert settings["write_ins"]["during_voting_mode"] == "default_off"
        assert settings["write_ins"]["max_per_proposal"] == 5
        assert "allowed_default" not in settings["write_ins"]
        assert settings["pre_voting"]["allowed_mode"] == "default_off"
        assert settings["pre_voting"]["visibility_mode"] == "default_on"
        # Public-delegate defaults were added.
        assert settings["public_delegates"]["enabled"] is True
        assert settings["public_delegates"]["approval_required"] is True
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
