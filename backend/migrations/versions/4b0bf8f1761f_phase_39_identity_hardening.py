"""phase 39 identity hardening

Adds three columns to ``users`` for soft-revocation + soft-lockout:

  * ``is_active`` (Boolean, NOT NULL, server_default true) — Phase 39 B1.
    Soft-revocation lever. ``_get_user_from_token`` and ``refresh_token``
    consult this on every auth-token use.
  * ``failed_login_count`` (Integer, NOT NULL, server_default 0) — Phase 39
    B4. Per-username counter incremented on bad-password attempts; reset
    on successful login + password reset.
  * ``locked_until`` (DateTime, nullable) — Phase 39 B4. Set to
    ``now + 15min`` when ``failed_login_count`` crosses the threshold.
    Login rejects with 401 while ``locked_until > now``.

All three columns ship in one revision (Phase 39 spec D11/sequencing —
"one migration, three columns") so the User-table identity-column adds
land atomically. Server defaults ensure existing rows backfill at the
SQL layer; ORM defaults mirror them so freshly-constructed ``User()``
instances pick up the same values pre-flush.

Revision ID: 4b0bf8f1761f
Revises: b6d8e2f1a350
Create Date: 2026-05-27 13:36:58.300774

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4b0bf8f1761f'
down_revision: Union[str, None] = 'b6d8e2f1a350'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _users_columns() -> set[str]:
    """Return the set of column names currently present on ``users``.

    Used to make this migration idempotent: pg_smoke's ``upgrade`` mode
    runs ``create_all`` (which builds the Phase 39 columns from the
    post-Phase-39 ``models.py``) BEFORE ``alembic stamp <prior>`` +
    ``upgrade head``, so naive ``op.add_column`` would collide. CLAUDE.md's
    "idempotent migration guards" convention covers this case: pre-
    inspect, no-op if the column is already present, add otherwise.
    """
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_columns("users")}


def upgrade() -> None:
    existing = _users_columns()
    if "is_active" not in existing:
        op.add_column(
            "users",
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
        )
    if "failed_login_count" not in existing:
        op.add_column(
            "users",
            sa.Column(
                "failed_login_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
    if "locked_until" not in existing:
        op.add_column(
            "users",
            sa.Column(
                "locked_until",
                sa.DateTime(timezone=False),
                nullable=True,
            ),
        )


def downgrade() -> None:
    existing = _users_columns()
    if "locked_until" in existing:
        op.drop_column("users", "locked_until")
    if "failed_login_count" in existing:
        op.drop_column("users", "failed_login_count")
    if "is_active" in existing:
        op.drop_column("users", "is_active")
