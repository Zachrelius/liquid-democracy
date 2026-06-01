"""phase 47 org titles

Adds the first-class title/office concept (decoupled from but
optionally bound to platform roles):

  * ``org_titles`` table — per-org named offices with optional
    ``bound_role``, ``cardinality_mode`` (single/multi), optional
    ``max_holders`` cap, ``fill_method`` (assigned/elected/both),
    ``is_system`` flag for built-in seeded titles, ``display_order``.
  * ``org_title_assignments`` table — one row per (title, holder) for
    CUSTOM titles only. System titles (Steward, Admin) are derived
    from the membership role at response-build time per Phase 47 D6;
    storing them as assignments would create a role-vs-title sync
    problem.

Backfill: seed two system titles per existing org — "Steward" binding
the steward role, "Admin" binding the admin role. Per D6 these are
label-layer titles over the existing roles; the role remains the
source of truth for permissions and the governance.py floor.

Revision ID: f3c7e9b48201
Revises: e8b4d6f31a92
Create Date: 2026-06-01 06:00:00.000000

"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "f3c7e9b48201"
down_revision: Union[str, None] = "e8b4d6f31a92"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables() -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return set(insp.get_table_names())


def upgrade() -> None:
    existing = _existing_tables()

    if "org_titles" not in existing:
        op.create_table(
            "org_titles",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "org_id",
                sa.String(),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False, index=True,
            ),
            sa.Column("name", sa.String(length=80), nullable=False),
            sa.Column("bound_role", sa.String(length=16), nullable=True),
            sa.Column(
                "cardinality_mode", sa.String(length=8),
                nullable=False, server_default="single",
            ),
            sa.Column("max_holders", sa.Integer(), nullable=True),
            sa.Column(
                "fill_method", sa.String(length=12),
                nullable=False, server_default="assigned",
            ),
            sa.Column(
                "is_system", sa.Boolean(),
                nullable=False, server_default=sa.false(),
            ),
            sa.Column(
                "display_order", sa.Integer(),
                nullable=False, server_default="0",
            ),
            sa.Column(
                "created_at", sa.DateTime(),
                nullable=False, server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "org_id", "name", name="uq_org_titles_org_name",
            ),
        )

    existing = _existing_tables()
    if "org_title_assignments" not in existing:
        op.create_table(
            "org_title_assignments",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "title_id", sa.String(),
                sa.ForeignKey("org_titles.id", ondelete="CASCADE"),
                nullable=False, index=True,
            ),
            sa.Column(
                "user_id", sa.String(),
                sa.ForeignKey("users.id"),
                nullable=False, index=True,
            ),
            sa.Column(
                "granted_by", sa.String(),
                sa.ForeignKey("users.id"),
                nullable=True,
            ),
            sa.Column(
                "granted_at", sa.DateTime(),
                nullable=False, server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "title_id", "user_id",
                name="uq_org_title_assignments_title_user",
            ),
        )

    # Backfill: seed two system titles per existing org (Steward + Admin).
    # New orgs get these via the create_organization route from this pass on.
    # Uses parameterized booleans so the same SQL works on both SQLite (which
    # silently coerces) and Postgres (strict boolean type).
    bind = op.get_bind()
    org_rows = bind.execute(sa.text(
        "SELECT id FROM organizations WHERE id NOT IN ("
        " SELECT org_id FROM org_titles WHERE is_system = :true_val"
        ")"
    ), {"true_val": True}).fetchall()
    for row in org_rows:
        org_id = row[0]
        bind.execute(sa.text(
            "INSERT INTO org_titles "
            "(id, org_id, name, bound_role, cardinality_mode, "
            " max_holders, fill_method, is_system, display_order, created_at) "
            "VALUES (:id, :oid, 'Steward', 'steward', 'single', NULL, "
            " 'assigned', :sys, 0, CURRENT_TIMESTAMP)"
        ), {"id": str(uuid.uuid4()), "oid": org_id, "sys": True})
        bind.execute(sa.text(
            "INSERT INTO org_titles "
            "(id, org_id, name, bound_role, cardinality_mode, "
            " max_holders, fill_method, is_system, display_order, created_at) "
            "VALUES (:id, :oid, 'Admin', 'admin', 'multi', NULL, "
            " 'assigned', :sys, 10, CURRENT_TIMESTAMP)"
        ), {"id": str(uuid.uuid4()), "oid": org_id, "sys": True})


def downgrade() -> None:
    existing = _existing_tables()
    if "org_title_assignments" in existing:
        op.drop_table("org_title_assignments")
    existing = _existing_tables()
    if "org_titles" in existing:
        op.drop_table("org_titles")
