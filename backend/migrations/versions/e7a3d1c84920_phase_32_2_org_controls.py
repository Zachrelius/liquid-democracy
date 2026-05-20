"""Phase 32.2 — org controls: 4-option enum modes + org.edit_proposal seed + public-delegate toggles.

Revision ID: e7a3d1c84920
Revises: d4f8e2a91c50
Create Date: 2026-05-20 13:00:00.000000

Three changes packed into one migration:

1. **M1 — 4-option enum migration.** Convert four boolean fields on every
   ``organizations.settings`` JSONB to enum-typed strings. Mapping:
   ``True → "default_on"``, ``False → "default_off"``. Existing settings
   without the boolean key get the platform default ``"default_off"``.

   Boolean → mode key renames:
     - ``write_ins.allowed_default``  → ``write_ins.allowed_mode``
     - ``write_ins.during_voting_default`` → ``write_ins.during_voting_mode``
     - ``pre_voting.allowed_default`` → ``pre_voting.allowed_mode``
     - ``pre_voting.show_votes_during_deliberation_default``
       → ``pre_voting.visibility_mode``

   Numeric fields (``write_ins.max_per_proposal``,
   ``proposal_edits.lockout_fraction``) are unchanged.

2. **M2 — Permission key seed.** ``org.edit_proposal`` is now declared in
   ``permission_registry.py`` (app-level). For each existing org, this
   migration inserts ``role_permissions`` rows so admin + steward
   actually have the key on day one. New orgs get it via the existing
   ``role_seed`` path that reads ``DEFAULT_GRANTS``.

3. **M3 — Public delegate org settings.** Add
   ``public_delegates.enabled`` (default True) and
   ``public_delegates.approval_required`` (default True) to every org's
   settings JSONB if not already present. ``public_delegates.enabled``
   defaults to True so existing orgs see no behavior change; the
   ``approval_required`` default of True preserves Phase 19's
   approval workflow.

Downgrade reverses the JSONB rewrites and removes the seeded
role_permissions rows, leaving the permission key in the registry (app
constant, not data). Mapping: ``"always_on" + "default_on" → True``,
``"always_off" + "default_off" → False``. The ``always_*`` modes carry
information the boolean shape can't represent, so downgrade is
operational rollback only.

Spec: phase32_2_org_controls_and_bug_fixes_spec.md
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e7a3d1c84920"
down_revision = "d4f8e2a91c50"
branch_labels = None
depends_on = None


# Boolean key → enum mode key. Applied to every org's settings JSONB.
_BOOL_TO_MODE_RENAMES = [
    ("write_ins", "allowed_default", "allowed_mode"),
    ("write_ins", "during_voting_default", "during_voting_mode"),
    ("pre_voting", "allowed_default", "allowed_mode"),
    (
        "pre_voting",
        "show_votes_during_deliberation_default",
        "visibility_mode",
    ),
]


def _mode_from_bool(value):
    """True → 'default_on', False → 'default_off', None → 'default_off'."""
    if value is True:
        return "default_on"
    return "default_off"


def _bool_from_mode(value):
    """'always_on' + 'default_on' → True; 'always_off' + 'default_off' →
    False. Anything else (including None) → False."""
    if value in ("always_on", "default_on"):
        return True
    return False


def upgrade() -> None:
    bind = op.get_bind()

    # ---- M1 — settings JSONB boolean → enum mode rewrite ----------------
    orgs = bind.execute(sa.text(
        "SELECT id, settings FROM organizations"
    )).fetchall()
    for org_id, settings in orgs:
        if isinstance(settings, str):
            import json
            try:
                settings = json.loads(settings) if settings else {}
            except (ValueError, TypeError):
                settings = {}
        if not isinstance(settings, dict):
            settings = {}
        for section, bool_key, mode_key in _BOOL_TO_MODE_RENAMES:
            section_dict = settings.get(section)
            if not isinstance(section_dict, dict):
                section_dict = {}
            # Read whichever shape is present; bool wins if both somehow set.
            if bool_key in section_dict:
                section_dict[mode_key] = _mode_from_bool(section_dict[bool_key])
                del section_dict[bool_key]
            elif mode_key not in section_dict:
                section_dict[mode_key] = "default_off"
            settings[section] = section_dict

        # ---- M3 — public_delegates defaults --------------------------
        pd = settings.get("public_delegates")
        if not isinstance(pd, dict):
            pd = {}
        pd.setdefault("enabled", True)
        pd.setdefault("approval_required", True)
        settings["public_delegates"] = pd

        bind.execute(
            sa.text("UPDATE organizations SET settings = :s WHERE id = :id")
            .bindparams(sa.bindparam("s", type_=sa.JSON()))
            ,
            {"s": settings, "id": org_id},
        )

    # ---- M2 — Seed org.edit_proposal into admin + steward role_permissions
    # rows for every existing org. The permission key itself is declared
    # at the app level (permission_registry.py); this is the data step
    # that brings existing orgs in line with the new DEFAULT_GRANTS.
    # Idempotent: ON CONFLICT DO NOTHING for the unique (role_id, key).
    role_rows = bind.execute(sa.text(
        "SELECT id FROM roles WHERE system_key IN ('admin', 'steward')"
    )).fetchall()
    is_pg = bind.dialect.name == "postgresql"
    for (role_id,) in role_rows:
        # Phase 12 role_permissions has a unique constraint on
        # (role_id, permission_key); skip if already present.
        existing = bind.execute(
            sa.text(
                "SELECT 1 FROM role_permissions "
                "WHERE role_id = :rid AND permission_key = :pk"
            ),
            {"rid": role_id, "pk": "org.edit_proposal"},
        ).fetchone()
        if existing is not None:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO role_permissions "
                "(id, role_id, permission_key, enabled, created_at) "
                "VALUES (:id, :rid, :pk, :g, :now)"
            ),
            {
                "id": _gen_uuid(),
                "rid": role_id,
                "pk": "org.edit_proposal",
                "g": True if is_pg else 1,
                "now": _now_naive(),
            },
        )


def downgrade() -> None:
    bind = op.get_bind()

    # ---- M1 reverse — enum mode → boolean ----------------------------
    orgs = bind.execute(sa.text(
        "SELECT id, settings FROM organizations"
    )).fetchall()
    for org_id, settings in orgs:
        if isinstance(settings, str):
            import json
            try:
                settings = json.loads(settings) if settings else {}
            except (ValueError, TypeError):
                settings = {}
        if not isinstance(settings, dict):
            settings = {}
        for section, bool_key, mode_key in _BOOL_TO_MODE_RENAMES:
            section_dict = settings.get(section)
            if not isinstance(section_dict, dict):
                continue
            if mode_key in section_dict:
                section_dict[bool_key] = _bool_from_mode(section_dict[mode_key])
                del section_dict[mode_key]
            settings[section] = section_dict

        # ---- M3 reverse — drop public_delegates.approval_required ---
        # Leave .enabled in place; it's a generic toggle that's useful
        # regardless of this pass.
        pd = settings.get("public_delegates")
        if isinstance(pd, dict):
            pd.pop("approval_required", None)
            settings["public_delegates"] = pd

        bind.execute(
            sa.text("UPDATE organizations SET settings = :s WHERE id = :id")
            .bindparams(sa.bindparam("s", type_=sa.JSON()))
            ,
            {"s": settings, "id": org_id},
        )

    # ---- M2 reverse — drop org.edit_proposal role_permissions rows --
    bind.execute(sa.text(
        "DELETE FROM role_permissions "
        "WHERE permission_key = 'org.edit_proposal'"
    ))


def _gen_uuid() -> str:
    """Cheap UUID for INSERT — matches the rest of the codebase's id default."""
    import uuid
    return str(uuid.uuid4())


def _now_naive():
    """Naive UTC for the created_at / updated_at columns."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(tzinfo=None)
