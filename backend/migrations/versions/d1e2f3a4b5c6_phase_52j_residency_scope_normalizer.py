"""phase 52j — residency scope settings normalizer

Phase 52j J1 promotes residency geography from per-gate single-value
settings to an org-level **set** of allowed ``{state, city?}``
localities. The old keys this migration folds are:

  * ``verification_membership_jurisdiction`` — the single state
    (e.g. ``"MA"``) used as the floor-jurisdiction by the
    membership gate, AND used as the state component when hashing
    the city in the old single-value locality model.
  * ``verification_membership_locality`` — the single city (e.g.
    ``"Somerville"``) the user must hash-match against.

For each org that carries either old key, this migration writes:

  * ``verification_residency_scope`` — a one-entry list
    ``[{"state": <old jurisdiction>, "city": <old locality or
    omitted>}]`` (omitting city when the old locality was unset).
  * ``verification_membership_require_residency`` — ``True`` so the
    membership gate continues to enforce the scope it was enforcing
    pre-J1.

The old keys are left in place (the spec's stated convention — same
posture as other deprecated settings). The new gate predicate
(``user_satisfies_residency_scope``) reads ONLY the new key.

The migration is **data-shape only** — no schema change, no column
add/drop, no index. The ``upgrade()`` walks ``Organization.settings``
JSON rows and rewrites those that carry the old keys; ``downgrade()``
removes the new keys it added (a clean revert).

The migration is **idempotent**: re-running ``upgrade()`` against an
already-normalized org is a no-op (it detects the new key already
present and skips).

Confirmed against current prod: per the Phase 52i closeout + the
52j spec's locked-decisions section, NO real orgs carry the old
keys today (only Z's demo orgs have any verification settings, and
none have a city gate configured). The migration may therefore be a
no-op on prod; it ships anyway for correctness + the parity test
+ for any org that may have added the old keys after that audit.
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "d1e2f3a4b5c6"
down_revision = "c0d1e2f3a4b5"
branch_labels = None
depends_on = None


_OLD_JURISDICTION_KEY = "verification_membership_jurisdiction"
_OLD_LOCALITY_KEY = "verification_membership_locality"
_NEW_SCOPE_KEY = "verification_residency_scope"
_NEW_REQUIRE_KEY = "verification_membership_require_residency"


def _load_settings(raw):
    """Tolerate the JSON column being delivered as either a dict
    (PostgreSQL JSON / JSONB) or a string (SQLite JSON-as-TEXT).
    Returns a dict or None."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            val = json.loads(raw)
            return val if isinstance(val, dict) else None
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def _dump_settings(d, original_raw):
    """Match the input shape — stringify back when the source was a
    string, leave as dict otherwise."""
    if isinstance(original_raw, str):
        return json.dumps(d)
    return d


def upgrade() -> None:
    bind = op.get_bind()
    org_table = sa.Table(
        "organizations",
        sa.MetaData(),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("settings", sa.JSON()),
    )

    rows = bind.execute(
        sa.select(org_table.c.id, org_table.c.settings)
    ).fetchall()

    for row in rows:
        org_id = row.id
        raw = row.settings
        settings = _load_settings(raw)
        if not isinstance(settings, dict):
            continue

        # Idempotency: if the org already has the new scope key, skip.
        # This makes a re-run a no-op for already-normalized orgs.
        if _NEW_SCOPE_KEY in settings:
            continue

        old_jurisdiction = settings.get(_OLD_JURISDICTION_KEY)
        old_locality = settings.get(_OLD_LOCALITY_KEY)

        if not (
            isinstance(old_jurisdiction, str) and old_jurisdiction.strip()
        ) and not (
            isinstance(old_locality, str) and old_locality.strip()
        ):
            # Org has neither old key — nothing to fold.
            continue

        # The old locality model required a jurisdiction (see 52i
        # _gate_city_for_org). If only locality is set without
        # jurisdiction, the old gate was silently inert; we preserve
        # that by skipping (no scope written).
        if not (
            isinstance(old_jurisdiction, str) and old_jurisdiction.strip()
        ):
            continue

        entry: dict = {"state": old_jurisdiction.strip().upper()}
        if isinstance(old_locality, str) and old_locality.strip():
            entry["city"] = old_locality.strip()

        new_settings = dict(settings)
        new_settings[_NEW_SCOPE_KEY] = [entry]
        new_settings[_NEW_REQUIRE_KEY] = True

        bind.execute(
            sa.update(org_table)
            .where(org_table.c.id == org_id)
            .values(settings=_dump_settings(new_settings, raw))
        )


def downgrade() -> None:
    """Remove the new keys this migration added. Leaves the old keys
    in place (they were left in place on upgrade too)."""
    bind = op.get_bind()
    org_table = sa.Table(
        "organizations",
        sa.MetaData(),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("settings", sa.JSON()),
    )

    rows = bind.execute(
        sa.select(org_table.c.id, org_table.c.settings)
    ).fetchall()

    for row in rows:
        org_id = row.id
        raw = row.settings
        settings = _load_settings(raw)
        if not isinstance(settings, dict):
            continue
        if _NEW_SCOPE_KEY not in settings and _NEW_REQUIRE_KEY not in settings:
            continue
        new_settings = {
            k: v for k, v in settings.items()
            if k not in (_NEW_SCOPE_KEY, _NEW_REQUIRE_KEY)
        }
        bind.execute(
            sa.update(org_table)
            .where(org_table.c.id == org_id)
            .values(settings=_dump_settings(new_settings, raw))
        )
