"""Phase 12 Stage 1 migration: verify upgrade -> downgrade -> upgrade on
SQLite, plus data-correctness assertions.

Mirrors ``test_phase_10_migration_cycle.py``: runs alembic via subprocess
so each invocation gets a fresh DATABASE_URL. The cycle test exercises
the full data path: it seeds an org with several string-role memberships
(including ``"owner"``) at the prior schema, runs the upgrade, asserts the
backfill mapped every row to a role_id row whose role.system_key matches
the rename ("owner" -> "steward"; everything else unchanged), then
downgrades and re-upgrades to prove idempotency.
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


def _table_exists(engine, table: str) -> bool:
    insp = sa.inspect(engine)
    return table in set(insp.get_table_names())


def _has_column(engine, table: str, column: str) -> bool:
    insp = sa.inspect(engine)
    if table not in set(insp.get_table_names()):
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


def _build_legacy_schema(db_url: str) -> None:
    """Build the post-Phase-10 schema (with legacy ``org_memberships.role``
    string column) and stamp at b2d5f1a3c7e4. We can't just call
    ``create_tables()`` because models.py now reflects the post-Phase-12
    shape (no ``role`` column). Instead, build the prior shape via raw DDL
    that mirrors the pre-Phase-12 model definition for org_memberships.
    """
    _create_all_subprocess(db_url)
    engine = sa.create_engine(db_url)
    try:
        with engine.begin() as conn:
            insp = sa.inspect(conn)
            tables = set(insp.get_table_names())

            # Drop the new tables so we exercise their create path during
            # upgrade. (create_all installed them because models.py declares
            # them.)
            if "role_permissions" in tables:
                conn.execute(sa.text("DROP TABLE role_permissions"))
            tables = set(sa.inspect(conn).get_table_names())
            if "roles" in tables:
                conn.execute(sa.text("DROP TABLE roles"))

            # Rebuild org_memberships in its pre-Phase-12 shape (no role_id
            # column, with the legacy `role` string column). Drop the
            # post-Phase-12 table and recreate.
            conn.execute(sa.text("DROP TABLE org_memberships"))
            conn.execute(sa.text(
                "CREATE TABLE org_memberships ("
                "id VARCHAR PRIMARY KEY, "
                "user_id VARCHAR NOT NULL REFERENCES users(id), "
                "org_id VARCHAR NOT NULL REFERENCES organizations(id), "
                "role VARCHAR DEFAULT 'member', "
                "status VARCHAR DEFAULT 'active', "
                "joined_at DATETIME, "
                "UNIQUE(user_id, org_id)"
                ")"
            ))
    finally:
        engine.dispose()
    _run_alembic(db_url, "stamp", "b2d5f1a3c7e4")


def _seed_legacy_data(db_url: str) -> dict:
    """Insert two orgs and a handful of memberships (incl. ``role='owner'``)
    using the legacy schema. Returns a dict of seeded ids for assertions.
    """
    engine = sa.create_engine(db_url)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    org_a_id = str(uuid.uuid4())
    org_b_id = str(uuid.uuid4())
    user_ids = [str(uuid.uuid4()) for _ in range(5)]
    membership_ids: list[str] = []
    expected: list[tuple[str, str, str]] = []  # (membership_id, org_id, original_role)

    try:
        with engine.begin() as conn:
            for u in user_ids:
                conn.execute(sa.text(
                    "INSERT INTO users (id, username, display_name, "
                    "password_hash, is_admin, user_type, "
                    "delegation_strategy, email_verified, "
                    "default_follow_policy, created_at) "
                    "VALUES (:id, :u, :dn, 'x', 0, 'human', "
                    "'strict_precedence', 0, 'require_approval', :now)"
                ), {"id": u, "u": f"user_{u[:6]}", "dn": "User", "now": now})

            for org_id, slug in [(org_a_id, "alpha"), (org_b_id, "beta")]:
                conn.execute(sa.text(
                    "INSERT INTO organizations "
                    "(id, name, slug, description, join_policy, settings, "
                    "created_at, updated_at) "
                    "VALUES (:id, :n, :s, '', 'open', '{}', :now, :now)"
                ), {"id": org_id, "n": slug.title(), "s": slug, "now": now})

            # org_a memberships: owner, admin, moderator, member, member
            scenarios = [
                (org_a_id, user_ids[0], "owner"),
                (org_a_id, user_ids[1], "admin"),
                (org_a_id, user_ids[2], "moderator"),
                (org_a_id, user_ids[3], "member"),
                (org_b_id, user_ids[0], "owner"),
                (org_b_id, user_ids[4], "moderator"),
            ]
            for org_id, uid, role_str in scenarios:
                m_id = str(uuid.uuid4())
                membership_ids.append(m_id)
                expected.append((m_id, org_id, role_str))
                conn.execute(sa.text(
                    "INSERT INTO org_memberships "
                    "(id, user_id, org_id, role, status, joined_at) "
                    "VALUES (:id, :u, :o, :r, 'active', :now)"
                ), {
                    "id": m_id, "u": uid, "o": org_id, "r": role_str,
                    "now": now,
                })
    finally:
        engine.dispose()

    return {
        "org_a_id": org_a_id,
        "org_b_id": org_b_id,
        "memberships": expected,
    }


def test_upgrade_downgrade_upgrade_cycle():
    """Migration is reversible and idempotent on SQLite."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"

    try:
        _build_legacy_schema(db_url)
        seeded = _seed_legacy_data(db_url)

        # Sanity: we're at the pre-Phase-12 shape.
        engine = sa.create_engine(db_url)
        assert _has_column(engine, "org_memberships", "role"), (
            "Legacy schema must have org_memberships.role column"
        )
        assert not _table_exists(engine, "roles")
        assert not _table_exists(engine, "role_permissions")
        engine.dispose()

        # Pre-migration row count for org_memberships.
        engine = sa.create_engine(db_url)
        with engine.connect() as conn:
            pre_count = conn.execute(
                sa.text("SELECT COUNT(*) FROM org_memberships")
            ).scalar()
        engine.dispose()

        # 1. Upgrade head
        _run_alembic(db_url, "upgrade", "head")
        engine = sa.create_engine(db_url)
        assert _table_exists(engine, "roles")
        assert _table_exists(engine, "role_permissions")
        assert _has_column(engine, "org_memberships", "role_id")
        assert not _has_column(engine, "org_memberships", "role"), (
            "Legacy `role` column must be dropped after upgrade"
        )

        with engine.connect() as conn:
            post_count = conn.execute(
                sa.text("SELECT COUNT(*) FROM org_memberships")
            ).scalar()
            null_role_id_count = conn.execute(
                sa.text(
                    "SELECT COUNT(*) FROM org_memberships WHERE role_id IS NULL"
                )
            ).scalar()
            owner_string_count = conn.execute(
                sa.text(
                    "SELECT COUNT(*) FROM roles WHERE system_key = 'owner'"
                )
            ).scalar()
            roles_per_org_a = conn.execute(
                sa.text(
                    "SELECT COUNT(*) FROM roles WHERE org_id = :id"
                ),
                {"id": seeded["org_a_id"]},
            ).scalar()
            roles_per_org_b = conn.execute(
                sa.text(
                    "SELECT COUNT(*) FROM roles WHERE org_id = :id"
                ),
                {"id": seeded["org_b_id"]},
            ).scalar()
        engine.dispose()

        # Pre/post org_memberships row count is identical.
        assert pre_count == post_count == 6

        # Every OrgMembership row has non-null role_id.
        assert null_role_id_count == 0

        # No row anywhere references the legacy "owner" system_key.
        assert owner_string_count == 0

        # Every org has exactly 4 roles.
        assert roles_per_org_a == 4
        assert roles_per_org_b == 4

        # 2. Downgrade to b2d5f1a3c7e4 (Phase 10) -> roles tables gone,
        # legacy `role` restored. Targeting an explicit revision rather
        # than a relative offset so this test stays correct as new
        # migrations are appended on top of Stage 1.
        _run_alembic(db_url, "downgrade", "b2d5f1a3c7e4")
        engine = sa.create_engine(db_url)
        assert not _table_exists(engine, "roles")
        assert not _table_exists(engine, "role_permissions")
        assert _has_column(engine, "org_memberships", "role")
        assert not _has_column(engine, "org_memberships", "role_id")

        # Verify the inverse rename: rows that were "owner" pre-migration
        # are "owner" again post-downgrade (steward -> owner roundtrip).
        with engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT id, role FROM org_memberships ORDER BY id"
                )
            ).fetchall()
        engine.dispose()
        roles_by_id = {r[0]: r[1] for r in rows}
        for m_id, _, original_role in seeded["memberships"]:
            assert roles_by_id[m_id] == original_role, (
                f"membership {m_id} expected role={original_role!r}, "
                f"got {roles_by_id[m_id]!r} after downgrade"
            )

        # 3. Re-upgrade head (idempotency)
        _run_alembic(db_url, "upgrade", "head")
        engine = sa.create_engine(db_url)
        assert _table_exists(engine, "roles")
        assert _table_exists(engine, "role_permissions")
        with engine.connect() as conn:
            post2_count = conn.execute(
                sa.text("SELECT COUNT(*) FROM org_memberships")
            ).scalar()
            roles_per_org_a_2 = conn.execute(
                sa.text(
                    "SELECT COUNT(*) FROM roles WHERE org_id = :id"
                ),
                {"id": seeded["org_a_id"]},
            ).scalar()
        engine.dispose()
        assert post2_count == 6
        # No duplicate roles after re-upgrade.
        assert roles_per_org_a_2 == 4
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_role_permissions_seeded_per_preset_role():
    """After running the FULL migration chain to head (Stage 1 + Stage 2):
    each preset role has the expected number of role_permissions rows.

    Stage 1 seeded 23/23/8/0 (only TRUE grants are inserted). Stage 2's
    migration inserts a `role_permissions.edit` row for ALL FOUR preset
    roles per spec lines 162-164: steward=True, admin=True, moderator=False,
    member=False. So:
      - steward: 23 (Stage 1 trues) + 1 (Stage 2 true) = 24
      - admin:   23 (Stage 1 trues) + 1 (Stage 2 true) = 24
      - moderator: 8 (Stage 1 trues) + 1 (Stage 2 false) = 9
      - member:    0 (Stage 1 trues) + 1 (Stage 2 false) = 1

    has_permission falls through to False on missing rows so the False rows
    are functionally indistinguishable from the absence of a row at the
    permission-resolution layer; they're inserted explicitly so the matrix
    GET endpoint can echo the cell state from the DB without inferring it.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"

    try:
        _build_legacy_schema(db_url)
        seeded = _seed_legacy_data(db_url)
        _run_alembic(db_url, "upgrade", "head")

        engine = sa.create_engine(db_url)
        with engine.connect() as conn:
            for org_id in (seeded["org_a_id"], seeded["org_b_id"]):
                rows = conn.execute(
                    sa.text(
                        "SELECT r.system_key, COUNT(rp.id) "
                        "FROM roles r "
                        "LEFT JOIN role_permissions rp ON rp.role_id = r.id "
                        "WHERE r.org_id = :org_id "
                        "GROUP BY r.system_key"
                    ),
                    {"org_id": org_id},
                ).fetchall()
                counts = {sk: cnt for sk, cnt in rows}
                # Phase 60 Bucket 2 — bumped expected counts after
                # Phase 47 (title.manage) + Phase 49a
                # (org.approve_cosign_petition) additions. Phase 68b adds
                # proposal.archive, bumping steward + admin to 29 (the
                # backfill migration writes the row for both tiers).
                # moderator/member are unchanged (no proposal.archive row).
                assert counts.get("steward") == 30, (
                    f"org {org_id}: steward should have 30 permissions "
                    f"(Phase 68b's proposal.archive is the latest "
                    f"addition), got {counts.get('steward')}"
                )
                assert counts.get("admin") == 30, (
                    f"org {org_id}: admin should have 30 permissions "
                    f"(lockstep with steward), got {counts.get('admin')}"
                )
                # Phase 71a — backfill migration c1d2e3f4a5b6 adds two
                # net-new moderator rows (member.suspend + polis.manage;
                # the other newly-enforced moderator keys were already
                # seeded at Stage 1), bumping moderator 11 → 13.
                assert counts.get("moderator") == 13, (
                    f"org {org_id}: moderator should have 13 permission "
                    f"rows (prior 11 + Phase 71a's member.suspend + "
                    f"polis.manage backfill rows), "
                    f"got {counts.get('moderator')}"
                )
                assert counts.get("member") == 3, (
                    f"org {org_id}: member should have 3 permission rows "
                    f"(role_permissions.edit / set_thresholds / "
                    f"set_durations — all enabled=False; Phase 47+49a "
                    f"did NOT add additional member rows), "
                    f"got {counts.get('member')}"
                )
        engine.dispose()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_membership_role_id_maps_to_correct_role_with_owner_to_steward_rename():
    """After upgrade: every legacy ``role='owner'`` membership now points at
    the role row whose ``system_key='steward'``; other roles map identity."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"

    try:
        _build_legacy_schema(db_url)
        seeded = _seed_legacy_data(db_url)
        _run_alembic(db_url, "upgrade", "head")

        engine = sa.create_engine(db_url)
        with engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT om.id, r.system_key "
                    "FROM org_memberships om "
                    "JOIN roles r ON r.id = om.role_id"
                )
            ).fetchall()
        engine.dispose()

        actual_by_id = {r[0]: r[1] for r in rows}
        rename = {
            "owner": "steward",
            "admin": "admin",
            "moderator": "moderator",
            "member": "member",
        }
        for m_id, _, original_role in seeded["memberships"]:
            expected_sk = rename[original_role]
            assert actual_by_id[m_id] == expected_sk, (
                f"membership {m_id} (legacy role={original_role!r}) "
                f"expected system_key={expected_sk!r}, "
                f"got {actual_by_id[m_id]!r}"
            )
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
