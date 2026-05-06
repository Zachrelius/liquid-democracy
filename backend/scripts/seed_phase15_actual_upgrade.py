"""Phase 15 Cluster S actual-upgrade-path seed module.

Consumed by ``pg_smoke.py --mode actual-upgrade --prior-revision
c0a3e5d12f4a --sample-data-script scripts/seed_phase15_actual_upgrade.py``.

Phase 15 Cluster S converts ``SubOrgMembership.role`` from a string
column to a ``role_id`` FK to the parent's Role row, with the
load-bearing ``"owner" → "steward"`` rename. The actual-upgrade-path
verification gap-closer:

  - ``reshape(engine)`` undoes today's schema additions on
    ``sub_org_memberships``: drops ``role_id`` (added by Phase 15) and
    re-adds the legacy ``role`` string column. We need the prior shape
    so we can seed legacy-shaped rows the migration must transform.
  - ``seed(engine)`` inserts a parent + sub-org pair plus four
    SubOrgMembership rows (one per legacy value: member, moderator,
    admin, owner). The parent's preset Role rows are already seeded by
    Phase 12 Stage 1's migration which ran during ``create_tables`` on
    the test container; we don't re-seed them.
  - ``verify(engine)`` asserts the four legacy values resolved to the
    expected parent Role rows, with ``owner → steward`` mapping
    verified explicitly. Reports pre/post counts.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Track the seeded ids so verify() can re-check the same rows.
_SEED_STATE: dict = {}


def reshape(engine) -> None:
    """Undo Phase 15's schema additions to bring sub_org_memberships
    back to the c0a3e5d12f4a (Phase 14 head) shape."""
    from sqlalchemy import text, inspect
    with engine.begin() as conn:
        cols = {c["name"] for c in inspect(conn).get_columns("sub_org_memberships")}
        # Drop role_id column + index/FK if create_all built them. PG
        # supports DROP COLUMN ... CASCADE which also yanks the FK.
        if "role_id" in cols:
            conn.execute(text(
                "ALTER TABLE sub_org_memberships "
                "DROP COLUMN IF EXISTS role_id CASCADE"
            ))
        # Drop the index too if it exists (PG-specific).
        try:
            conn.execute(text(
                "DROP INDEX IF EXISTS ix_sub_org_memberships_role_id"
            ))
        except Exception:
            pass
        # Re-add the legacy string column if create_all dropped it.
        cols = {c["name"] for c in inspect(conn).get_columns("sub_org_memberships")}
        if "role" not in cols:
            conn.execute(text(
                "ALTER TABLE sub_org_memberships ADD COLUMN role "
                "VARCHAR NOT NULL DEFAULT 'member'"
            ))


def seed(engine) -> None:
    """Insert a parent + sub-org pair, four users, and four
    SubOrgMembership rows using each legacy role string."""
    from sqlalchemy import text
    now = _now_naive()
    parent_id = str(uuid.uuid4())
    sub_id = str(uuid.uuid4())
    user_ids: dict[str, str] = {}
    membership_ids: dict[str, str] = {}

    legacy_roles = ("member", "moderator", "admin", "owner")
    with engine.begin() as conn:
        for role in legacy_roles:
            uid = str(uuid.uuid4())
            user_ids[role] = uid
            conn.execute(text(
                "INSERT INTO users (id, username, display_name, "
                "password_hash, is_admin, user_type, "
                "delegation_strategy, email_verified, "
                "default_follow_policy, created_at) "
                "VALUES (:id, :u, :dn, 'x', FALSE, 'human', "
                "'strict_precedence', FALSE, 'require_approval', :now)"
            ), {"id": uid, "u": f"u_phase15_{role}",
                 "dn": f"User {role}", "now": now})

        # Parent + sub-org. Uses join_policy='invite_only_secret' since
        # we're past Phase 14's rename.
        conn.execute(text(
            "INSERT INTO organizations "
            "(id, name, slug, description, join_policy, settings, "
            "parent_org_id, created_at, updated_at) "
            "VALUES (:id, 'Phase15Parent', 'phase15parent', '', "
            "'open', '{}', NULL, :now, :now)"
        ), {"id": parent_id, "now": now})
        conn.execute(text(
            "INSERT INTO organizations "
            "(id, name, slug, description, join_policy, settings, "
            "parent_org_id, created_at, updated_at) "
            "VALUES (:id, 'Phase15Sub', 'phase15sub', '', "
            "'invite_only_secret', '{}', :pid, :now, :now)"
        ), {"id": sub_id, "pid": parent_id, "now": now})

        # The parent org needs preset Role rows (Phase 12 Stage 1's
        # migration ran during create_tables but only seeded for orgs
        # that EXISTED at that point — we just inserted a new org via
        # raw SQL after the migration ran, so we have to seed manually).
        for sk, name in (
            ("steward", "Steward"), ("admin", "Admin"),
            ("moderator", "Moderator"), ("member", "Member"),
        ):
            conn.execute(text(
                "INSERT INTO roles "
                "(id, org_id, name, system_key, is_system_preset, "
                "display_order, created_at) "
                "VALUES (:id, :org_id, :n, :sk, TRUE, 0, :now)"
            ), {
                "id": str(uuid.uuid4()), "org_id": parent_id,
                "n": name, "sk": sk, "now": now,
            })

        for role in legacy_roles:
            m_id = str(uuid.uuid4())
            membership_ids[role] = m_id
            conn.execute(text(
                "INSERT INTO sub_org_memberships "
                "(id, user_id, sub_org_id, role, status, joined_at) "
                "VALUES (:id, :u, :so, :r, 'active', :now)"
            ), {
                "id": m_id, "u": user_ids[role], "so": sub_id,
                "r": role, "now": now,
            })

    # Report PRE-upgrade counts.
    with engine.connect() as conn:
        pre_count = conn.execute(text(
            "SELECT COUNT(*) FROM sub_org_memberships "
            "WHERE sub_org_id = :i"
        ), {"i": sub_id}).scalar() or 0
        per_value = {}
        for role in legacy_roles:
            per_value[role] = conn.execute(text(
                "SELECT COUNT(*) FROM sub_org_memberships "
                "WHERE sub_org_id = :i AND role = :r"
            ), {"i": sub_id, "r": role}).scalar() or 0
    print(
        f"[seed_phase15] PRE-upgrade: sub_org_memberships in test sub-org = "
        f"{pre_count} (per legacy value: {per_value})",
        flush=True,
    )

    _SEED_STATE.update({
        "parent_id": parent_id,
        "sub_id": sub_id,
        "user_ids": user_ids,
        "membership_ids": membership_ids,
    })


def verify(engine) -> None:
    """Assert post-upgrade shape: every membership has a role_id FK
    that resolves to the parent's matching Role row, with the
    ``owner → steward`` rename load-bearing.
    """
    from sqlalchemy import text, inspect

    sub_id = _SEED_STATE["sub_id"]
    parent_id = _SEED_STATE["parent_id"]
    membership_ids = _SEED_STATE["membership_ids"]

    with engine.connect() as conn:
        cols = {
            c["name"] for c in inspect(conn).get_columns("sub_org_memberships")
        }
        assert "role_id" in cols, (
            "Phase 15 upgrade should add role_id column"
        )
        assert "role" not in cols, (
            "Phase 15 upgrade should drop legacy role string column"
        )

        # Pre-mapped rename for assertions.
        expected_rename = {
            "member": "member",
            "moderator": "moderator",
            "admin": "admin",
            "owner": "steward",  # The load-bearing one.
        }

        # Per-membership FK resolution check.
        for legacy_role, m_id in membership_ids.items():
            row = conn.execute(text(
                "SELECT r.system_key, r.org_id "
                "FROM sub_org_memberships som "
                "JOIN roles r ON r.id = som.role_id "
                "WHERE som.id = :i"
            ), {"i": m_id}).first()
            assert row is not None, (
                f"membership for legacy role {legacy_role!r} (id={m_id}) "
                "did not resolve a Role via role_id FK"
            )
            actual_sk, actual_org_id = row
            expected_sk = expected_rename[legacy_role]
            assert actual_sk == expected_sk, (
                f"membership for legacy role {legacy_role!r}: expected "
                f"system_key={expected_sk!r}, got {actual_sk!r}"
            )
            # Role row lives on the PARENT, not the sub-org.
            assert actual_org_id == parent_id, (
                f"membership for {legacy_role!r}: role.org_id should be "
                f"the parent org ({parent_id!r}), got {actual_org_id!r}"
            )

        # No row references a Role with system_key='owner' anywhere
        # (post-Phase-12 there's no such Role; the Phase 15 backfill
        # must rename owner → steward).
        owner_count = conn.execute(text(
            "SELECT COUNT(*) FROM sub_org_memberships som "
            "JOIN roles r ON r.id = som.role_id "
            "WHERE som.sub_org_id = :i AND r.system_key = 'owner'"
        ), {"i": sub_id}).scalar() or 0
        assert owner_count == 0, (
            f"expected 0 sub_org_memberships with system_key='owner' "
            f"post-upgrade (the rename should have caught them), "
            f"got {owner_count}"
        )

        # Post-upgrade per-system_key counts on this sub-org.
        post_counts = {}
        for sk in ("member", "moderator", "admin", "steward"):
            post_counts[sk] = conn.execute(text(
                "SELECT COUNT(*) FROM sub_org_memberships som "
                "JOIN roles r ON r.id = som.role_id "
                "WHERE som.sub_org_id = :i AND r.system_key = :sk"
            ), {"i": sub_id, "sk": sk}).scalar() or 0

    print(
        f"[seed_phase15] POST-upgrade: sub_org_memberships per role "
        f"system_key = {post_counts} "
        f"(expected: 1 each, including owner -> steward rename)",
        flush=True,
    )
    assert post_counts == {"member": 1, "moderator": 1,
                            "admin": 1, "steward": 1}, (
        f"expected one row per system_key, got {post_counts}"
    )
