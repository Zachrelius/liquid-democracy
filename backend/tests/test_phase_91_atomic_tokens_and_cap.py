"""Phase 91: token secrecy/single-use and authorized-cap serialization."""
from __future__ import annotations

import hashlib
import inspect
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

import models
import share_distribution
import share_service
from pending_actions import share_actions
from routes import auth as auth_routes
from routes import organizations


def test_refresh_digest_is_stable_and_does_not_contain_secret():
    raw = "a-client-held-refresh-secret"
    digest = auth_routes._refresh_token_hash(raw)
    assert digest == hashlib.sha256(raw.encode()).hexdigest()
    assert len(digest) == 64
    assert raw not in digest


def test_new_refresh_token_is_hash_only(db):
    user = models.User(
        username="p91hash", display_name="P91 Hash", email="p91hash@example.test",
        email_verified=True, password_hash="unused",
    )
    db.add(user)
    db.flush()
    raw = auth_routes._create_refresh_token(db, user.id)
    row = db.query(models.RefreshToken).filter_by(user_id=user.id).one()
    assert row.token is None
    assert row.token_hash == auth_routes._refresh_token_hash(raw)


def test_legacy_refresh_row_is_upgraded_in_place(db):
    user = models.User(
        username="p91legacy", display_name="P91 Legacy",
        email="p91legacy@example.test", email_verified=True, password_hash="unused",
    )
    db.add(user)
    db.flush()
    row = models.RefreshToken(
        user_id=user.id, token="legacy-plaintext", token_hash=None,
        expires_at=auth_routes._now(),
    )
    auth_routes._upgrade_legacy_refresh_token(row, "legacy-plaintext")
    assert row.token is None
    assert row.token_hash == auth_routes._refresh_token_hash("legacy-plaintext")


def test_refresh_claim_and_all_cap_paths_use_row_locks():
    """Structural regression guard for the shared PostgreSQL mutex protocol."""
    assert ".with_for_update()" in inspect.getsource(auth_routes.refresh_token)
    for fn in (
        share_service.set_member_weight,
        share_distribution.run_rule,
        share_actions._exec_cap_raise,
        organizations.update_organization,
    ):
        assert ".with_for_update()" in inspect.getsource(fn), fn.__qualname__


def test_distribution_resolves_members_only_after_org_lock():
    """Do not cache balances before waiting on the per-org issuance mutex."""
    source = inspect.getsource(share_distribution.run_rule)
    lock_at = source.index(".with_for_update()")
    targets_at = source.index("targeted = resolve_targeted_members")
    assert lock_at < targets_at
    assert ".populate_existing()" in inspect.getsource(
        share_distribution._active_members
    )


def test_for_update_compiles_for_postgresql():
    stmt = sa.select(models.Organization).where(
        models.Organization.id == "org-id"
    ).with_for_update()
    rendered = str(stmt.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in rendered


_BACKEND = Path(__file__).resolve().parents[1]
_PRIOR = "b4c5d6e7f8a9"


def _run(db_url: str, *args: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = db_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=_BACKEND,
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_phase_91_migration_cycle_and_plaintext_backfill():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        env = os.environ.copy()
        env["DATABASE_URL"] = db_url
        create = subprocess.run(
            [sys.executable, "-c", "from database import create_tables; create_tables()"],
            cwd=_BACKEND, env=env, capture_output=True, text=True,
        )
        assert create.returncode == 0, create.stdout + create.stderr
        _run(db_url, "stamp", "head")
        _run(db_url, "downgrade", _PRIOR)

        engine = sa.create_engine(db_url)
        with engine.begin() as conn:
            cols = {c["name"] for c in sa.inspect(conn).get_columns("refresh_tokens")}
            assert "token_hash" not in cols
            conn.execute(sa.text(
                "INSERT INTO refresh_tokens "
                "(user_id, token, expires_at, revoked_at, created_at) VALUES "
                "('legacy-user', 'live-client-token', CURRENT_TIMESTAMP, NULL, CURRENT_TIMESTAMP)"
            ))
        engine.dispose()

        _run(db_url, "upgrade", "head")
        engine = sa.create_engine(db_url)
        with engine.connect() as conn:
            row = conn.execute(sa.text(
                "SELECT token, token_hash FROM refresh_tokens"
            )).mappings().one()
            assert row["token"] is None
            assert row["token_hash"] == hashlib.sha256(b"live-client-token").hexdigest()
        engine.dispose()

        _run(db_url, "downgrade", _PRIOR)
        engine = sa.create_engine(db_url)
        with engine.connect() as conn:
            cols = {c["name"] for c in sa.inspect(conn).get_columns("refresh_tokens")}
            assert "token_hash" not in cols
            restored = conn.execute(sa.text("SELECT token FROM refresh_tokens")).scalar_one()
            assert restored == hashlib.sha256(b"live-client-token").hexdigest()
        engine.dispose()

        _run(db_url, "upgrade", "head")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
