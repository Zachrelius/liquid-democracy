"""phase 57 — three-axis access model (join_policy × discoverability × activity_visibility)

Phase 14 conflated "how you join" and "whether outsiders can find/see the
org" into a single ``join_policy`` string with four values
(``open``/``approval_required``/``invite_only_public``/``invite_only_secret``).
Phase 57 separates these into three independent columns:

  * ``join_policy`` — REPURPOSED to hold the new three-value join
    semantics: ``open`` / ``approval`` / ``invite``. The column name
    stays so that read sites can keep reading ``org.join_policy``; the
    *values* are rewritten by this migration.
  * ``discoverability`` — NEW ``String(16)``, values
    ``listed`` / ``unlisted`` / ``hidden``. Drives the Phase 55
    ``/explore`` filter (was keyed on the old ``invite_only_secret``
    join_policy literal) and the Phase 14 public-landing 404 check
    (was keyed on the same literal).
  * ``activity_visibility`` — NEW ``String(16)``, values
    ``public`` / ``members_only``. When ``public``, non-members can see
    the org's proposal list + aggregate tallies + comments read-only.
    Individual delegate-vote visibility STILL routes through the
    Phase 30.3 ``can_see_votes`` gate; this column does NOT bypass it.

Migration mapping (preserves current per-org behavior exactly):

  | OLD join_policy       | → join_policy | discoverability | activity_visibility |
  |-----------------------|---------------|-----------------|---------------------|
  | open                  | open          | listed          | members_only        |
  | approval_required     | approval      | listed          | members_only        |
  | invite_only_public    | invite        | listed          | members_only        |
  | invite_only_secret    | invite        | hidden          | members_only        |

All existing orgs default ``activity_visibility=members_only`` (current
behavior: no org exposes activity today). Discoverability defaults
preserve current ``/explore`` presence: everything except
``invite_only_secret`` was listed, so everything except it stays
``listed``; ``invite_only_secret`` was the only thing 404'ing on the
public landing, and it maps to ``hidden`` here.

DANGEROUS seed-path: this migration REWRITES existing values AND adds
two NOT NULL columns with a data-dependent backfill. The server_default
on each new column satisfies the NOT NULL constraint for any in-flight
INSERT racing with the migration; the per-row UPDATEs below then
overwrite the defaults to the table's actual mapping.

Reversible ``downgrade()``: maps the three-axis space back onto the
four old ``join_policy`` values. The (invite, unlisted) combination
has no clean pre-Phase-57 representation (``unlisted`` is a Phase 57
invention); downgrade documents this as LOSSY and folds
(invite, unlisted) onto ``invite_only_public`` (the closest
non-secret invite).

Hex-prefix revision id (Phase 48 Stage 2 convention).

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-06-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DISCOVERABILITY_INDEX = "ix_organizations_discoverability"


def _existing_columns(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return set()


def _existing_indexes(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return {ix["name"] for ix in insp.get_indexes(table)}
    except Exception:
        return set()


def upgrade() -> None:
    cols = _existing_columns("organizations")

    # Add new columns NOT NULL with server_defaults so any in-flight
    # INSERT mid-migration satisfies the constraint with sane values.
    if "discoverability" not in cols:
        op.add_column(
            "organizations",
            sa.Column(
                "discoverability",
                sa.String(length=16),
                nullable=False,
                server_default="listed",
            ),
        )
    if "activity_visibility" not in cols:
        op.add_column(
            "organizations",
            sa.Column(
                "activity_visibility",
                sa.String(length=16),
                nullable=False,
                server_default="members_only",
            ),
        )

    # Backfill discoverability + rewrite join_policy values per the mapping.
    # Run as a batch UPDATE keyed on the old join_policy value so the
    # rewrites are atomic at the per-row level. Order matters: do the
    # discoverability writes BEFORE rewriting join_policy values, so the
    # WHERE clauses still match the old vocabulary.
    bind = op.get_bind()
    # invite_only_secret → discoverability='hidden' + join_policy='invite'
    bind.execute(sa.text(
        "UPDATE organizations "
        "SET discoverability = 'hidden' "
        "WHERE join_policy = 'invite_only_secret'"
    ))
    # The other three → discoverability='listed' (already the server_default,
    # but we set it explicitly for the parity test's sake — server_default
    # only applies to rows inserted WITHOUT the column; existing rows had
    # NULL before this migration and got picked up by Alembic's NOT NULL
    # adjustment with the default. Belt-and-suspenders for tests that
    # exercise raw-SQL inserts pre-migration.)
    bind.execute(sa.text(
        "UPDATE organizations "
        "SET discoverability = 'listed' "
        "WHERE join_policy IN ('open', 'approval_required', 'invite_only_public')"
    ))
    # activity_visibility stays at the server_default 'members_only'
    # everywhere — no existing org exposes activity today.

    # Rewrite join_policy values. Single statement per old→new mapping.
    bind.execute(sa.text(
        "UPDATE organizations "
        "SET join_policy = 'approval' "
        "WHERE join_policy = 'approval_required'"
    ))
    bind.execute(sa.text(
        "UPDATE organizations "
        "SET join_policy = 'invite' "
        "WHERE join_policy IN ('invite_only_public', 'invite_only_secret')"
    ))
    # 'open' is unchanged.

    # Index on discoverability — the /explore filter queries it.
    idx = _existing_indexes("organizations")
    if DISCOVERABILITY_INDEX not in idx:
        op.create_index(
            DISCOVERABILITY_INDEX, "organizations", ["discoverability"],
        )


def downgrade() -> None:
    """Reverse the value rewrite + drop the new columns.

    Mapping back from the three-axis space to the four old values:

      (open,     listed)    → open
      (approval, listed)    → approval_required
      (invite,   listed)    → invite_only_public
      (invite,   hidden)    → invite_only_secret
      (invite,   unlisted)  → invite_only_public  ← LOSSY (Phase 57 invention)

    Non-invite + non-listed combinations (open+hidden, approval+unlisted,
    etc.) are not produced by the upgrade backfill and represent
    deliberate post-Phase-57 stewardship — those fold onto the closest
    pre-Phase-57 value documented above. Downgrade is intended as a
    rollback safety net, not a routine round-trip.
    """
    idx = _existing_indexes("organizations")
    if DISCOVERABILITY_INDEX in idx:
        op.drop_index(DISCOVERABILITY_INDEX, table_name="organizations")

    bind = op.get_bind()
    # Reverse value rewrites BEFORE dropping discoverability (we still
    # need to read it to disambiguate invite_only_public vs
    # invite_only_secret).
    cols = _existing_columns("organizations")
    if "discoverability" in cols:
        # join_policy='invite' AND discoverability='hidden' → invite_only_secret
        bind.execute(sa.text(
            "UPDATE organizations "
            "SET join_policy = 'invite_only_secret' "
            "WHERE join_policy = 'invite' AND discoverability = 'hidden'"
        ))
        # join_policy='invite' AND discoverability IN ('listed', 'unlisted')
        #   → invite_only_public (LOSSY for the unlisted case)
        bind.execute(sa.text(
            "UPDATE organizations "
            "SET join_policy = 'invite_only_public' "
            "WHERE join_policy = 'invite' AND discoverability IN ('listed', 'unlisted')"
        ))
        # approval → approval_required (regardless of discoverability)
        bind.execute(sa.text(
            "UPDATE organizations "
            "SET join_policy = 'approval_required' "
            "WHERE join_policy = 'approval'"
        ))
        # 'open' stays 'open'.

    if "activity_visibility" in cols:
        op.drop_column("organizations", "activity_visibility")
    if "discoverability" in cols:
        op.drop_column("organizations", "discoverability")
