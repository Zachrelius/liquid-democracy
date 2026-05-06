"""Phase 14 migration: verify upgrade -> downgrade -> upgrade cycle on
SQLite, plus the data-migration step that renames
``join_policy='invite_only'`` to ``'invite_only_secret'`` and the lossy
collapse of ``invite_only_public`` to ``invite_only`` on downgrade.

Mirrors ``test_phase13_3_migration_cycle.py``'s shape:

  - Stamps at the Phase 13.3 head (b9e2f4a17c83) so the upgrade runs the
    Phase 14 migration only.
  - Seeds Organization rows with each of the four pre/post values across
    cycles to verify the rename is correct AND that
    ``approval_required`` / ``open`` rows are untouched.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_14_REVISION = "c0a3e5d12f4a"
_PRIOR_REVISION = "b9e2f4a17c83"


def _run_alembic(db_url: str, *args: str) -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    res = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=_BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
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
        cwd=_BACKEND_DIR,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, (
        f"create_tables failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )


def _build_pre_phase_14_schema(db_url: str) -> None:
    """Build today's schema via create_tables, then stamp at the prior
    revision (b9e2f4a17c83) so ``upgrade head`` runs the Phase 14
    migration on top.

    join_policy is a plain String column — no DDL reshape needed (today's
    column shape is identical to what existed at the prior revision; the
    only change in 14 is a data rename of value strings).
    """
    _create_all_subprocess(db_url)
    _run_alembic(db_url, "stamp", _PRIOR_REVISION)


def _seed_org(
    db_url: str, *, slug: str, join_policy: str,
) -> str:
    """Insert an Organization with the given join_policy."""
    engine = sa.create_engine(db_url)
    org_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text(
                "INSERT INTO organizations "
                "(id, name, slug, description, join_policy, settings, "
                " parent_org_id, created_at, updated_at) "
                "VALUES (:id, :n, :s, '', :jp, '{}', NULL, :now, :now)"
            ), {
                "id": org_id, "n": slug.title(), "s": slug,
                "jp": join_policy, "now": now,
            })
    finally:
        engine.dispose()
    return org_id


def _join_policy(db_url: str, org_id: str) -> str:
    engine = sa.create_engine(db_url)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                sa.text("SELECT join_policy FROM organizations WHERE id = :i"),
                {"i": org_id},
            ).first()
            return row[0] if row else None
    finally:
        engine.dispose()


def _count_with_policy(db_url: str, value: str) -> int:
    engine = sa.create_engine(db_url)
    try:
        with engine.connect() as conn:
            return conn.execute(sa.text(
                "SELECT COUNT(*) FROM organizations WHERE join_policy = :v"
            ), {"v": value}).scalar() or 0
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_phase14_upgrade_renames_invite_only_to_secret():
    """invite_only org → invite_only_secret post-upgrade."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_phase_14_schema(db_url)
        oid = _seed_org(db_url, slug="legacy-secret", join_policy="invite_only")
        assert _join_policy(db_url, oid) == "invite_only"

        _run_alembic(db_url, "upgrade", "head")

        assert _join_policy(db_url, oid) == "invite_only_secret"
        # No rows left with the legacy value anywhere.
        assert _count_with_policy(db_url, "invite_only") == 0
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase14_upgrade_leaves_approval_required_unchanged():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_phase_14_schema(db_url)
        oid = _seed_org(db_url, slug="ar-org", join_policy="approval_required")
        _run_alembic(db_url, "upgrade", "head")
        assert _join_policy(db_url, oid) == "approval_required"
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase14_upgrade_leaves_open_unchanged():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_phase_14_schema(db_url)
        oid = _seed_org(db_url, slug="open-org", join_policy="open")
        _run_alembic(db_url, "upgrade", "head")
        assert _join_policy(db_url, oid) == "open"
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase14_upgrade_idempotent_no_op_on_rerun():
    """A second upgrade head leaves the renamed rows alone (no rows match
    the WHERE clause). The migration is at head after the first run, so
    alembic doesn't re-execute upgrade(); but the SQL itself is idempotent
    if the migration WERE re-run."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_phase_14_schema(db_url)
        oid = _seed_org(db_url, slug="idem-org", join_policy="invite_only")
        _run_alembic(db_url, "upgrade", "head")
        assert _join_policy(db_url, oid) == "invite_only_secret"

        # Re-run upgrade head — alembic no-ops since we're at head.
        _run_alembic(db_url, "upgrade", "head")
        assert _join_policy(db_url, oid) == "invite_only_secret"
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase14_upgrade_downgrade_upgrade_cycle():
    """Full cycle reversibility on SQLite. Downgrade restores
    ``invite_only`` for ``invite_only_secret`` rows; the lossy collapse
    of ``invite_only_public`` to ``invite_only`` is also exercised."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_phase_14_schema(db_url)
        legacy = _seed_org(db_url, slug="legacy", join_policy="invite_only")
        ar = _seed_org(db_url, slug="ar", join_policy="approval_required")
        op_org = _seed_org(db_url, slug="open", join_policy="open")

        # 1. Upgrade head: invite_only -> invite_only_secret.
        _run_alembic(db_url, "upgrade", "head")
        assert _join_policy(db_url, legacy) == "invite_only_secret"
        assert _join_policy(db_url, ar) == "approval_required"
        assert _join_policy(db_url, op_org) == "open"

        # Simulate a steward switching one org to invite_only_public
        # post-deploy (the value is allowed at the application layer).
        engine = sa.create_engine(db_url)
        try:
            with engine.begin() as conn:
                conn.execute(sa.text(
                    "UPDATE organizations SET join_policy = "
                    "'invite_only_public' WHERE id = :i"
                ), {"i": ar})
        finally:
            engine.dispose()
        assert _join_policy(db_url, ar) == "invite_only_public"

        # 2. Downgrade -1: secret -> invite_only AND public -> invite_only.
        _run_alembic(db_url, "downgrade", "-1")
        assert _join_policy(db_url, legacy) == "invite_only"
        assert _join_policy(db_url, ar) == "invite_only"  # lossy collapse
        assert _join_policy(db_url, op_org) == "open"

        # 3. Re-upgrade head: invite_only -> invite_only_secret again
        # (both legacy and ar — ar lost its public distinction
        # in the downgrade and is now treated as a former-invite_only).
        _run_alembic(db_url, "upgrade", "head")
        assert _join_policy(db_url, legacy) == "invite_only_secret"
        assert _join_policy(db_url, ar) == "invite_only_secret"
        assert _join_policy(db_url, op_org) == "open"
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase14_upgrade_mixed_population_counts():
    """Multiple orgs across all three pre-migration values; verify counts
    pre/post upgrade match the rename."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_phase_14_schema(db_url)
        # Two invite_only, three approval_required, one open.
        for i in range(2):
            _seed_org(db_url, slug=f"inv-{i}", join_policy="invite_only")
        for i in range(3):
            _seed_org(db_url, slug=f"ar-{i}", join_policy="approval_required")
        _seed_org(db_url, slug="op-0", join_policy="open")

        assert _count_with_policy(db_url, "invite_only") == 2
        assert _count_with_policy(db_url, "approval_required") == 3
        assert _count_with_policy(db_url, "open") == 1

        _run_alembic(db_url, "upgrade", "head")

        assert _count_with_policy(db_url, "invite_only") == 0
        assert _count_with_policy(db_url, "invite_only_secret") == 2
        assert _count_with_policy(db_url, "approval_required") == 3
        assert _count_with_policy(db_url, "open") == 1
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
