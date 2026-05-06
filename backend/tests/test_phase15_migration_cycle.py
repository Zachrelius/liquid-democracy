"""Phase 15 Cluster S migration: verify upgrade -> downgrade -> upgrade
on SQLite, plus the load-bearing ``"owner" → "steward"`` mapping.

Mirrors ``test_phase_12_migration_cycle.py``'s shape since this
migration parallels Phase 12 Stage 1's OrgMembership.role string →
role_id FK pattern (the sub-org analog).

The cycle test exercises the full data path: it builds the prior
schema (sub_org_memberships with the legacy ``role`` string column),
seeds a sub-org with all four legacy values (``member``, ``moderator``,
``admin``, ``owner``), runs the upgrade, asserts the backfill mapped
each row to the parent's matching Role row (with ``"owner" → "steward"``
rename baked in), then downgrades and re-upgrades to prove
reversibility + idempotency.

The four-value mapping check (one test per legacy value) is the
load-bearing assertion. ``"owner" → "steward"`` is the most
error-prone and gets its own focused test.
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
_PHASE_15_REVISION = "98dcd0058ba2"
_PRIOR_REVISION = "c0a3e5d12f4a"


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


def _has_column(engine, table: str, column: str) -> bool:
    insp = sa.inspect(engine)
    if table not in set(insp.get_table_names()):
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


def _build_pre_phase_15_schema(db_url: str) -> None:
    """Build today's schema, then drop sub_org_memberships and rebuild it
    in the pre-Phase-15 shape (legacy ``role`` string column, no
    ``role_id`` FK), then stamp at the prior revision.

    We can't just call ``create_tables()`` because models.py reflects
    the post-Phase-15 shape. Drop + raw DDL gets us to a faithful
    pre-Phase-15 schema-shape; the alembic stamp tells alembic the
    chain is at c0a3e5d12f4a.
    """
    _create_all_subprocess(db_url)
    engine = sa.create_engine(db_url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("DROP TABLE sub_org_memberships"))
            conn.execute(sa.text(
                "CREATE TABLE sub_org_memberships ("
                "id VARCHAR PRIMARY KEY, "
                "user_id VARCHAR NOT NULL REFERENCES users(id), "
                "sub_org_id VARCHAR NOT NULL REFERENCES organizations(id), "
                "role VARCHAR DEFAULT 'member', "
                "status VARCHAR DEFAULT 'active', "
                "joined_at DATETIME, "
                "UNIQUE(user_id, sub_org_id)"
                ")"
            ))
    finally:
        engine.dispose()
    _run_alembic(db_url, "stamp", _PRIOR_REVISION)


def _seed_legacy_data(db_url: str) -> dict:
    """Insert a parent + sub-org pair, then four sub-org memberships
    using each legacy role string. Returns ids for assertions.
    """
    engine = sa.create_engine(db_url)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    parent_id = str(uuid.uuid4())
    sub_id = str(uuid.uuid4())
    user_ids = {role: str(uuid.uuid4()) for role in
                ("member", "moderator", "admin", "owner")}
    membership_ids: dict[str, str] = {}

    try:
        with engine.begin() as conn:
            for role, uid in user_ids.items():
                conn.execute(sa.text(
                    "INSERT INTO users (id, username, display_name, "
                    "password_hash, is_admin, user_type, "
                    "delegation_strategy, email_verified, "
                    "default_follow_policy, created_at) "
                    "VALUES (:id, :u, :dn, 'x', 0, 'human', "
                    "'strict_precedence', 0, 'require_approval', :now)"
                ), {"id": uid, "u": f"user_{role}", "dn": role,
                     "now": now})

            conn.execute(sa.text(
                "INSERT INTO organizations "
                "(id, name, slug, description, join_policy, settings, "
                "parent_org_id, created_at, updated_at) "
                "VALUES (:id, 'Parent', 'parent', '', 'open', '{}', "
                "NULL, :now, :now)"
            ), {"id": parent_id, "now": now})
            conn.execute(sa.text(
                "INSERT INTO organizations "
                "(id, name, slug, description, join_policy, settings, "
                "parent_org_id, created_at, updated_at) "
                "VALUES (:id, 'Sub', 'sub', '', 'invite_only_secret', "
                "'{}', :pid, :now, :now)"
            ), {"id": sub_id, "pid": parent_id, "now": now})

            # Phase 12 Stage 1's migration ran during create_tables's
            # alembic stamp head + create_all path; the parent's preset
            # roles are not auto-seeded for orgs we INSERT directly
            # via raw SQL. We need them for the backfill to find a
            # target. Insert the four preset Role rows.
            for sk, name in (
                ("steward", "Steward"), ("admin", "Admin"),
                ("moderator", "Moderator"), ("member", "Member"),
            ):
                conn.execute(sa.text(
                    "INSERT INTO roles "
                    "(id, org_id, name, system_key, is_system_preset, "
                    "display_order, created_at) "
                    "VALUES (:id, :org_id, :n, :sk, 1, 0, :now)"
                ), {
                    "id": str(uuid.uuid4()), "org_id": parent_id,
                    "n": name, "sk": sk, "now": now,
                })

            # Insert sub_org_memberships with the four legacy values.
            for role, uid in user_ids.items():
                m_id = str(uuid.uuid4())
                membership_ids[role] = m_id
                conn.execute(sa.text(
                    "INSERT INTO sub_org_memberships "
                    "(id, user_id, sub_org_id, role, status, joined_at) "
                    "VALUES (:id, :u, :so, :r, 'active', :now)"
                ), {"id": m_id, "u": uid, "so": sub_id, "r": role,
                     "now": now})
    finally:
        engine.dispose()

    return {
        "parent_id": parent_id,
        "sub_id": sub_id,
        "user_ids": user_ids,
        "membership_ids": membership_ids,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_phase15_upgrade_adds_role_id_drops_role_string():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_phase_15_schema(db_url)
        engine = sa.create_engine(db_url)
        try:
            assert _has_column(engine, "sub_org_memberships", "role")
            assert not _has_column(engine, "sub_org_memberships", "role_id")
        finally:
            engine.dispose()

        _run_alembic(db_url, "upgrade", "head")

        engine = sa.create_engine(db_url)
        try:
            assert _has_column(engine, "sub_org_memberships", "role_id")
            assert not _has_column(engine, "sub_org_memberships", "role"), (
                "Legacy `role` column must be dropped after upgrade"
            )
        finally:
            engine.dispose()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase15_upgrade_maps_each_legacy_value_correctly():
    """Each of the four legacy strings maps to the correct parent Role
    row post-upgrade. ``owner`` → Steward is the load-bearing rename;
    the others map identity.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_phase_15_schema(db_url)
        seeded = _seed_legacy_data(db_url)
        _run_alembic(db_url, "upgrade", "head")

        engine = sa.create_engine(db_url)
        try:
            with engine.connect() as conn:
                rows = conn.execute(sa.text(
                    "SELECT som.id, r.system_key, r.org_id "
                    "FROM sub_org_memberships som "
                    "JOIN roles r ON r.id = som.role_id"
                )).fetchall()
        finally:
            engine.dispose()

        actual_by_id = {r[0]: (r[1], r[2]) for r in rows}
        expected_rename = {
            "member": "member",
            "moderator": "moderator",
            "admin": "admin",
            "owner": "steward",
        }
        for legacy_role, m_id in seeded["membership_ids"].items():
            actual_sk, actual_org_id = actual_by_id[m_id]
            assert actual_sk == expected_rename[legacy_role], (
                f"membership for legacy role {legacy_role!r}: "
                f"expected system_key={expected_rename[legacy_role]!r}, "
                f"got {actual_sk!r}"
            )
            # Role lives on the PARENT org, not the sub-org.
            assert actual_org_id == seeded["parent_id"], (
                f"membership for {legacy_role!r}: role.org_id should "
                f"be the parent org, got {actual_org_id!r}"
            )
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase15_owner_to_steward_rename_is_load_bearing():
    """The ``"owner" → "steward"`` mapping is the most error-prone case;
    this focused test asserts only that. After upgrade, no row in
    ``sub_org_memberships`` references a Role with ``system_key='owner'``
    (because no such Role row exists post-Phase-12).
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_phase_15_schema(db_url)
        seeded = _seed_legacy_data(db_url)
        _run_alembic(db_url, "upgrade", "head")

        engine = sa.create_engine(db_url)
        try:
            with engine.connect() as conn:
                # No row references a 'owner' system_key Role.
                count_owner = conn.execute(sa.text(
                    "SELECT COUNT(*) FROM sub_org_memberships som "
                    "JOIN roles r ON r.id = som.role_id "
                    "WHERE r.system_key = 'owner'"
                )).scalar() or 0
                assert count_owner == 0

                # The previously-"owner" membership now points at Steward.
                owner_id = seeded["membership_ids"]["owner"]
                row = conn.execute(sa.text(
                    "SELECT r.system_key FROM sub_org_memberships som "
                    "JOIN roles r ON r.id = som.role_id "
                    "WHERE som.id = :i"
                ), {"i": owner_id}).first()
                assert row is not None and row[0] == "steward"
        finally:
            engine.dispose()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase15_role_id_is_not_null_post_upgrade():
    """Step 3 of the migration flips ``role_id`` to NOT NULL after the
    backfill. The cycle test pins this so a backfill bug that leaves
    NULLs is caught here rather than at next-deploy."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_phase_15_schema(db_url)
        _seed_legacy_data(db_url)
        _run_alembic(db_url, "upgrade", "head")

        engine = sa.create_engine(db_url)
        try:
            with engine.connect() as conn:
                null_count = conn.execute(sa.text(
                    "SELECT COUNT(*) FROM sub_org_memberships "
                    "WHERE role_id IS NULL"
                )).scalar() or 0
                assert null_count == 0
        finally:
            engine.dispose()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase15_upgrade_downgrade_upgrade_cycle():
    """Full reversibility: upgrade → downgrade → upgrade leaves the
    membership rows correct at each step. Downgrade is lossy on
    Steward → ``"owner"`` (acceptable per Phase 12 Stage 1 precedent).
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_phase_15_schema(db_url)
        seeded = _seed_legacy_data(db_url)

        # 1. Upgrade head.
        _run_alembic(db_url, "upgrade", "head")
        engine = sa.create_engine(db_url)
        try:
            assert _has_column(engine, "sub_org_memberships", "role_id")
            assert not _has_column(engine, "sub_org_memberships", "role")
        finally:
            engine.dispose()

        # 2. Downgrade to the prior revision: legacy ``role`` column
        # comes back, populated from role.system_key with the inverse
        # rename.
        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        engine = sa.create_engine(db_url)
        try:
            assert not _has_column(engine, "sub_org_memberships", "role_id")
            assert _has_column(engine, "sub_org_memberships", "role")
            with engine.connect() as conn:
                rows = conn.execute(sa.text(
                    "SELECT id, role FROM sub_org_memberships"
                )).fetchall()
        finally:
            engine.dispose()
        roles_by_id = {r[0]: r[1] for r in rows}
        # member, moderator, admin map identity. owner round-trips
        # (Steward → "owner") losslessly because no custom Steward
        # state was created in the test fixture.
        for legacy_role, m_id in seeded["membership_ids"].items():
            assert roles_by_id[m_id] == legacy_role, (
                f"membership for {legacy_role!r}: expected "
                f"role={legacy_role!r} after downgrade, got "
                f"{roles_by_id[m_id]!r}"
            )

        # 3. Re-upgrade head: idempotent.
        _run_alembic(db_url, "upgrade", "head")
        engine = sa.create_engine(db_url)
        try:
            assert _has_column(engine, "sub_org_memberships", "role_id")
            with engine.connect() as conn:
                count = conn.execute(sa.text(
                    "SELECT COUNT(*) FROM sub_org_memberships"
                )).scalar()
            assert count == 4
        finally:
            engine.dispose()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
