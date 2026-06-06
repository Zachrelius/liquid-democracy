"""Phase 57 migration cycle test — value rewrite + two new NOT NULL columns.

Asserts:
  * upgrade adds `discoverability` + `activity_visibility` columns.
  * Each of the four old join_policy values maps to the correct triple
    (join_policy, discoverability, activity_visibility) per the spec table.
  * downgrade reverses the value rewrite + drops the two new columns.
  * Parity: an org created post-migration (via the model + server_defaults)
    gets the same defaults the migration assigns to a fresh row.

This is the "dangerous seed-path" case (data-dependent backfill + value
rewrite) so the parity assertion is mandatory per CLAUDE.md.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_57_REVISION = "b9c0d1e2f3a4"
_PRIOR_REVISION = "a8b9c0d1e2f3"  # Phase 52i (current head as of 2026-06-06)


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


def _build_pre_57(db_url: str) -> None:
    _create_all_subprocess(db_url)
    _run_alembic(db_url, "stamp", "head")
    _run_alembic(db_url, "downgrade", _PRIOR_REVISION)


def _seed_legacy_orgs(db_url: str) -> dict[str, str]:
    """Insert one org per pre-Phase-57 join_policy value via raw SQL so
    the model validator doesn't intercept and rewrite the value before
    the migration runs. Returns a dict {old_value: org_id}.

    All NOT NULL columns lacking a server_default must be supplied
    explicitly (description, created_at, updated_at). The new
    discoverability + activity_visibility columns don't exist yet at
    this point (this runs pre-Phase-57 against the prior schema)."""
    inserts = {
        "open": "phase57_org_open",
        "approval_required": "phase57_org_approval",
        "invite_only_public": "phase57_org_iop",
        "invite_only_secret": "phase57_org_ios",
    }
    code_lines = [
        f"import os; os.environ['DATABASE_URL']={db_url!r}",
        "import sqlalchemy as sa",
        "from datetime import datetime",
        f"engine = sa.create_engine({db_url!r})",
        "now = datetime.utcnow().isoformat()",
        "with engine.begin() as conn:",
    ]
    for legacy_value, oid in inserts.items():
        code_lines.append(
            f"    conn.execute(sa.text("
            f"\"INSERT INTO organizations "
            f"(id, name, slug, description, join_policy, settings, created_at, updated_at) "
            f"VALUES ('{oid}', 'Org {oid}', '{oid}', '', '{legacy_value}', '{{}}', :n, :n)\""
            f"), {{'n': now}})"
        )
    res = subprocess.run(
        [sys.executable, "-c", "\n".join(code_lines)],
        cwd=_BACKEND_DIR, capture_output=True, text=True,
    )
    assert res.returncode == 0, (
        f"seed legacy failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )
    return inserts


def _read_triple(db_url: str, oid: str) -> tuple[str, str, str]:
    engine = sa.create_engine(db_url)
    try:
        with engine.connect() as conn:
            row = conn.execute(sa.text(
                "SELECT join_policy, discoverability, activity_visibility "
                "FROM organizations WHERE id = :i"
            ), {"i": oid}).first()
            assert row is not None, f"org {oid!r} missing"
            return row[0], row[1], row[2]
    finally:
        engine.dispose()


# ===========================================================================
# Columns
# ===========================================================================


def test_phase_57_upgrade_adds_columns():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_57(db_url)
        pre = _columns(db_url, "organizations")
        assert "discoverability" not in pre
        assert "activity_visibility" not in pre

        _run_alembic(db_url, "upgrade", "head")
        post = _columns(db_url, "organizations")
        assert "discoverability" in post
        assert "activity_visibility" in post
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# ===========================================================================
# Value mapping (per spec table)
# ===========================================================================


def test_phase_57_upgrade_maps_each_legacy_value():
    """The four old join_policy values each map to the correct triple."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_57(db_url)
        seeded = _seed_legacy_orgs(db_url)
        _run_alembic(db_url, "upgrade", "head")

        expected = {
            "open": ("open", "listed", "members_only"),
            "approval_required": ("approval", "listed", "members_only"),
            "invite_only_public": ("invite", "listed", "members_only"),
            "invite_only_secret": ("invite", "hidden", "members_only"),
        }
        for legacy_value, oid in seeded.items():
            triple = _read_triple(db_url, oid)
            assert triple == expected[legacy_value], (
                f"legacy {legacy_value!r} → {triple}, "
                f"expected {expected[legacy_value]}"
            )
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# ===========================================================================
# Cycle (up → down → up)
# ===========================================================================


def test_phase_57_downgrade_upgrade_cycle():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_57(db_url)
        seeded = _seed_legacy_orgs(db_url)
        _run_alembic(db_url, "upgrade", "head")
        # Sanity check post-upgrade state.
        assert _read_triple(db_url, seeded["invite_only_secret"]) == (
            "invite", "hidden", "members_only",
        )

        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        post_down = _columns(db_url, "organizations")
        assert "discoverability" not in post_down
        assert "activity_visibility" not in post_down

        # join_policy values should be back to the four old vocabulary.
        engine = sa.create_engine(db_url)
        try:
            with engine.connect() as conn:
                rows = {
                    r[0]: r[1] for r in conn.execute(sa.text(
                        "SELECT id, join_policy FROM organizations"
                    )).all()
                }
        finally:
            engine.dispose()
        assert rows[seeded["open"]] == "open"
        assert rows[seeded["approval_required"]] == "approval_required"
        # The lossy collapse only matters for (invite, unlisted); these
        # four legacy seeds round-trip cleanly because they're the
        # canonical pre-Phase-57 values.
        assert rows[seeded["invite_only_public"]] == "invite_only_public"
        assert rows[seeded["invite_only_secret"]] == "invite_only_secret"

        # Re-upgrade returns to the post-upgrade state.
        _run_alembic(db_url, "upgrade", "head")
        assert _read_triple(db_url, seeded["invite_only_secret"]) == (
            "invite", "hidden", "members_only",
        )
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# ===========================================================================
# Parity: existing-vs-new org get the same default triple
# ===========================================================================


def test_phase_57_parity_existing_vs_new_org_defaults_match():
    """Per CLAUDE.md seed-path rule: an existing org migrated through
    Phase 57 ends with the same default triple as an org created fresh
    post-migration using today's default constructor."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_57(db_url)
        # Existing org (default Phase 14 join_policy when created via
        # the legacy code path was 'approval_required').
        seed_code = (
            f"import os; os.environ['DATABASE_URL']={db_url!r}\n"
            "import sqlalchemy as sa\n"
            "from datetime import datetime\n"
            f"engine = sa.create_engine({db_url!r})\n"
            "now = datetime.utcnow().isoformat()\n"
            "with engine.begin() as conn:\n"
            "    conn.execute(sa.text(\""
            "INSERT INTO organizations (id, name, slug, description, join_policy, settings, created_at, updated_at) "
            "VALUES ('legacy_default', 'Legacy', 'legacy', '', 'approval_required', '{}', :n, :n)\""
            "), {'n': now})\n"
        )
        res = subprocess.run(
            [sys.executable, "-c", seed_code], cwd=_BACKEND_DIR,
            capture_output=True, text=True,
        )
        assert res.returncode == 0, res.stderr

        _run_alembic(db_url, "upgrade", "head")
        existing_triple = _read_triple(db_url, "legacy_default")

        # Fresh org created via the model (post-migration).
        fresh_code = (
            f"import os; os.environ['DATABASE_URL']={db_url!r}\n"
            "import models\n"
            "from database import SessionLocal\n"
            "s = SessionLocal()\n"
            "o = models.Organization(name='Fresh', slug='fresh')\n"
            "s.add(o); s.commit()\n"
            f"import sqlalchemy as sa; engine = sa.create_engine({db_url!r})\n"
            "with engine.connect() as conn:\n"
            "    row = conn.execute(sa.text("
            "\"SELECT join_policy, discoverability, activity_visibility "
            "FROM organizations WHERE slug='fresh'\""
            ")).first()\n"
            "    print('TRIPLE', row[0], row[1], row[2])\n"
            "s.close()\n"
        )
        res2 = subprocess.run(
            [sys.executable, "-c", fresh_code], cwd=_BACKEND_DIR,
            capture_output=True, text=True,
        )
        assert res2.returncode == 0, res2.stderr
        # Parse the TRIPLE line.
        fresh_triple = None
        for line in res2.stdout.splitlines():
            if line.startswith("TRIPLE "):
                _, jp, disc, av = line.split()
                fresh_triple = (jp, disc, av)
                break
        assert fresh_triple is not None, f"could not parse: {res2.stdout!r}"

        # Both must land at (approval, listed, members_only) — the
        # canonical default. The fresh constructor uses the model's
        # `default=` per column; the migration's mapping for
        # 'approval_required' uses the same triple. These have to
        # agree byte-for-byte or future fresh-org creates would diverge
        # from migrated rows.
        assert existing_triple == ("approval", "listed", "members_only"), (
            f"existing migrated triple: {existing_triple}"
        )
        assert fresh_triple == ("approval", "listed", "members_only"), (
            f"fresh post-migration triple: {fresh_triple}"
        )
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
