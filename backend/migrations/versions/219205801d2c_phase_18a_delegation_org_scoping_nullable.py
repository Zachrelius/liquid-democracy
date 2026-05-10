"""Phase 18a: delegation org-scoping — nullable columns + backfill + constraint update.

Revision ID: 219205801d2c
Revises: d2a17cb3e45c
Create Date: 2026-05-09 00:00:00.000000

What this does
--------------

Phase 4c retrofit closure for the four relationship tables that were missed
when the multi-tenancy layer landed (``Delegation``, ``DelegationIntent``,
``FollowRelationship``, ``FollowRequest``). The diagnostic at
``delegation_org_scoping_diagnostic_2026-05.md`` enumerates the prod blast
radius (~4 rows) and §10 records Z's locked decisions D1–D9.

This is **phase 1** of a two-phase migration (D6 — two-phase). Phase 1 adds
``org_id`` (and ``sub_org_id`` on the delegation tables) as **nullable**,
runs the backfill, and updates the unique constraints to include the new
columns. Phase 2 (B1b, separate revision) flips ``org_id`` to ``NOT NULL``
once Z has verified the backfill on staging or a PG snapshot.

Schema additions
~~~~~~~~~~~~~~~~

- ``delegations.org_id``       — Optional[str], FK organizations.id, indexed
- ``delegations.sub_org_id``   — Optional[str], FK organizations.id, indexed (D4)
- ``delegation_intents.org_id``       — same shape
- ``delegation_intents.sub_org_id``   — same shape
- ``follow_relationships.org_id``     — Optional[str], FK organizations.id, indexed (D2)
- ``follow_requests.org_id``          — Optional[str], FK organizations.id, indexed (D2)

Backfill — three sweeps for ``Delegation``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. **Topic-scoped rows** (``topic_id IS NOT NULL``): copy
   ``org_id`` / ``sub_org_id`` from the row's ``topics`` join.
2. **Global rows where the parties share exactly one org**: set
   ``org_id`` to that one shared org. (Diagnostic §7: 2 of 3 prod globals.)
3. **Global rows where the parties share multiple orgs (D1 — C&Z)**: pick
   the org where the **delegate** has been most recently active, ranked by
   ``MAX(votes.cast_at)`` joined to org via the proposal. Fallback: the
   delegation's own ``updated_at`` against the candidate orgs' settings
   timestamps (any tie → pick by org id sorted ASC for determinism). Logs
   INFO with chosen + alternative orgs for Z's post-deploy audit review.

Same shape applies to ``DelegationIntent``.

Backfill — ``FollowRelationship`` / ``FollowRequest``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- For follows / requests with ``permission_level == 'delegation_allowed'`` AND
  parties share at least one org: shared-org-or-most-recent-activity heuristic.
- For pure ``view_only`` follows / requests: set ``org_id`` to the followed
  user's primary org (the org they're most active in, by recent vote count).

Backfill safety
~~~~~~~~~~~~~~~

If a row's parties share zero orgs (shouldn't happen in prod but guard for
it), log a WARNING and leave that row's ``org_id`` NULL. Phase 1 does NOT
abort on edge cases — Phase 2 (B1b) will catch any remaining NULLs at
``ALTER COLUMN ... SET NOT NULL`` time, where Z can intervene before deploy
flips the constraint.

Unique constraint updates
~~~~~~~~~~~~~~~~~~~~~~~~~

- Drop ``uq_delegation_delegator_topic`` and replace with
  ``uq_delegation_delegator_org_subor_topic`` over
  ``(delegator_id, org_id, sub_org_id, topic_id)``. SQLAlchemy / Postgres
  treat NULL as distinct in UNIQUE, so a user can have one global-per-org
  delegation (``topic_id NULL``, ``sub_org_id NULL``) per org, plus one
  global-per-sub-org delegation per sub-org.
- Drop ``uq_delegation_intent`` and replace with
  ``uq_delegation_intent_org_subor`` over the same shape.

Audit log
~~~~~~~~~

Each backfilled row emits a ``delegation.org_id_backfilled`` (or
``delegation_intent.org_id_backfilled`` / ``follow_relationship.org_id_backfilled``
/ ``follow_request.org_id_backfilled``) audit row with
``{old_state, new_state, sweep_number, ambiguity_resolution}`` details. This
is the forensic trail Z reviews post-deploy.

Idempotency
-----------

The column-add steps guard via ``inspector.get_columns`` — only add the
column if not already present. The backfill skips rows whose ``org_id`` is
already non-NULL (so re-running on a partially-applied DB is a no-op).
Constraint drops are guarded via ``inspector.get_unique_constraints``.

Downgrade
---------

Drops the new columns and reinstates the prior unique constraints.
**Backfill is NOT reversed** — downgrading is best-effort and would lose
the org context that was inferred. Document any divergence in the closeout
if a downgrade is ever exercised.
"""
from datetime import datetime, timezone
from typing import Sequence, Union
import json
import logging
import uuid

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '219205801d2c'
down_revision: Union[str, None] = 'd2a17cb3e45c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_LOG = logging.getLogger("alembic.phase18a")


def _now_naive() -> datetime:
    """UTC timestamp without tzinfo (matches the DB column shape)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _maybe_add_column(bind, inspector, table: str, column_name: str,
                      column: sa.Column, fk_name: str,
                      fk_target_table: str, index_name: str) -> None:
    """Add a column + index + FK only if the column doesn't already exist.

    Uses batch_alter_table so SQLite (which can't ALTER FKs in place) gets
    the table-rebuild treatment. Postgres handles the in-place ALTER fine.
    """
    existing_cols = {c["name"] for c in inspector.get_columns(table)}
    if column_name in existing_cols:
        return

    with op.batch_alter_table(table, schema=None) as batch_op:
        batch_op.add_column(column)
        batch_op.create_index(index_name, [column_name], unique=False)
        batch_op.create_foreign_key(
            fk_name, fk_target_table, [column_name], ["id"],
        )


def _maybe_drop_unique(bind, inspector, table: str, name: str) -> None:
    """Drop a unique constraint by name if it exists."""
    existing_uniques = {
        uq["name"] for uq in inspector.get_unique_constraints(table)
        if uq.get("name")
    }
    if name not in existing_uniques:
        return
    with op.batch_alter_table(table, schema=None) as batch_op:
        batch_op.drop_constraint(name, type_="unique")


def _maybe_create_unique(bind, inspector, table: str, name: str,
                         columns: list[str]) -> None:
    """Create a unique constraint by name if it doesn't already exist."""
    existing_uniques = {
        uq["name"] for uq in inspector.get_unique_constraints(table)
        if uq.get("name")
    }
    if name in existing_uniques:
        return
    with op.batch_alter_table(table, schema=None) as batch_op:
        batch_op.create_unique_constraint(name, columns)


def _audit(bind, action: str, target_type: str, target_id: str,
           details: dict) -> None:
    """Append a row to ``audit_log``. Skips silently if the table is
    missing (defensive — shouldn't happen post-Phase-4c)."""
    inspector = sa.inspect(bind)
    if "audit_log" not in inspector.get_table_names():
        return
    bind.execute(
        sa.text(
            "INSERT INTO audit_log "
            "(id, timestamp, actor_id, action, target_type, target_id, "
            " details, ip_address) "
            "VALUES (:id, :ts, NULL, :action, :ttype, :tid, "
            "        :details, NULL)"
        ),
        {
            "id": str(uuid.uuid4()),
            "ts": _now_naive(),
            "action": action,
            "ttype": target_type,
            "tid": target_id,
            "details": json.dumps(details),
        },
    )


def _shared_org_ids(bind, user_a: str, user_b: str) -> list[str]:
    """Return the org ids where both users have an active org_membership."""
    rows = bind.execute(
        sa.text(
            "SELECT m1.org_id "
            "FROM org_memberships m1 "
            "JOIN org_memberships m2 "
            "  ON m2.user_id = :user_b "
            " AND m2.org_id = m1.org_id "
            " AND m2.status = 'active' "
            "WHERE m1.user_id = :user_a "
            "  AND m1.status = 'active' "
            "ORDER BY m1.org_id ASC"
        ),
        {"user_a": user_a, "user_b": user_b},
    ).fetchall()
    return [r[0] for r in rows]


def _user_recent_org(bind, user_id: str,
                     candidate_org_ids: list[str]) -> tuple[str | None, dict]:
    """Pick the org from ``candidate_org_ids`` where ``user_id`` has been
    most recently active by ``MAX(votes.cast_at)``. Returns
    ``(chosen_org_id, {"per_org": {org_id: latest_cast_at_iso}, ...})``.

    Falls back to first-by-id if no vote activity in any candidate.
    """
    if not candidate_org_ids:
        return None, {"per_org": {}, "fallback": "no_candidates"}

    per_org: dict[str, str | None] = {}
    for org_id in candidate_org_ids:
        row = bind.execute(
            sa.text(
                "SELECT MAX(v.cast_at) "
                "FROM votes v "
                "JOIN proposals p ON p.id = v.proposal_id "
                "WHERE v.user_id = :uid "
                "  AND p.org_id = :oid"
            ),
            {"uid": user_id, "oid": org_id},
        ).first()
        # SQLite returns timestamps as ISO strings; PG returns datetime.
        # Normalize to str-or-None either way.
        if row and row[0]:
            val = row[0]
            per_org[org_id] = val.isoformat() if hasattr(val, "isoformat") else str(val)
        else:
            per_org[org_id] = None

    # Pick the org with the latest cast_at; ignore None entries first.
    sortable = [(v, k) for k, v in per_org.items() if v is not None]
    if sortable:
        sortable.sort(reverse=True)
        chosen = sortable[0][1]
        return chosen, {"per_org": per_org, "tiebreak": "max_vote_cast_at"}

    # No vote activity at all → fallback to deterministic first-by-id.
    chosen = sorted(candidate_org_ids)[0]
    return chosen, {"per_org": per_org, "tiebreak": "first_by_org_id"}


# ---------------------------------------------------------------------------
# Backfill: Delegation
# ---------------------------------------------------------------------------


def _backfill_delegations(bind) -> dict:
    """Three sweeps as described in the module docstring.

    Returns a small stats dict that's also logged to INFO.
    """
    inspector = sa.inspect(bind)
    if "delegations" not in inspector.get_table_names():
        return {"sweep1": 0, "sweep2": 0, "sweep3": 0, "warnings": 0}

    stats = {"sweep1": 0, "sweep2": 0, "sweep3": 0, "warnings": 0}

    # ----- Sweep 1: topic-scoped rows. -----
    rows = bind.execute(
        sa.text(
            "SELECT d.id, d.delegator_id, d.delegate_id, d.topic_id, "
            "       t.org_id, t.sub_org_id "
            "FROM delegations d "
            "JOIN topics t ON t.id = d.topic_id "
            "WHERE d.topic_id IS NOT NULL "
            "  AND (d.org_id IS NULL OR d.org_id = '')"
        )
    ).fetchall()
    for row in rows:
        d_id, delegator_id, delegate_id, topic_id, t_org_id, t_sub_org_id = row
        if not t_org_id:
            # Topic without org_id — shouldn't happen post-Phase-4c. Skip.
            stats["warnings"] += 1
            _LOG.warning(
                "Phase 18a: delegation %s topic %s has no org_id; "
                "leaving delegation org_id NULL.",
                d_id, topic_id,
            )
            continue
        bind.execute(
            sa.text(
                "UPDATE delegations SET org_id = :oid, sub_org_id = :soid "
                "WHERE id = :did"
            ),
            {"oid": t_org_id, "soid": t_sub_org_id, "did": d_id},
        )
        _audit(
            bind,
            action="delegation.org_id_backfilled",
            target_type="delegation",
            target_id=d_id,
            details={
                "old_state": {"org_id": None, "sub_org_id": None},
                "new_state": {"org_id": t_org_id, "sub_org_id": t_sub_org_id},
                "sweep_number": 1,
                "ambiguity_resolution": "topic_join",
            },
        )
        stats["sweep1"] += 1

    # ----- Sweep 2 + 3: global rows (topic_id IS NULL). -----
    global_rows = bind.execute(
        sa.text(
            "SELECT id, delegator_id, delegate_id, updated_at "
            "FROM delegations "
            "WHERE topic_id IS NULL "
            "  AND (org_id IS NULL OR org_id = '')"
        )
    ).fetchall()

    for d_id, delegator_id, delegate_id, updated_at in global_rows:
        shared = _shared_org_ids(bind, delegator_id, delegate_id)
        if not shared:
            stats["warnings"] += 1
            _LOG.warning(
                "Phase 18a: delegation %s (delegator=%s, delegate=%s) "
                "shares zero orgs; leaving org_id NULL — Phase 1b will "
                "catch this if not resolved manually.",
                d_id, delegator_id, delegate_id,
            )
            continue

        if len(shared) == 1:
            chosen = shared[0]
            bind.execute(
                sa.text("UPDATE delegations SET org_id = :oid WHERE id = :did"),
                {"oid": chosen, "did": d_id},
            )
            _audit(
                bind,
                action="delegation.org_id_backfilled",
                target_type="delegation",
                target_id=d_id,
                details={
                    "old_state": {"org_id": None},
                    "new_state": {"org_id": chosen},
                    "sweep_number": 2,
                    "ambiguity_resolution": "single_shared_org",
                    "shared_orgs": shared,
                },
            )
            stats["sweep2"] += 1
            continue

        # Sweep 3: multi-shared-orgs (the C&Z heuristic).
        chosen, telemetry = _user_recent_org(bind, delegate_id, shared)
        alternatives = [o for o in shared if o != chosen]
        _LOG.info(
            "Phase 18a sweep 3 (delegation %s): delegator=%s delegate=%s "
            "shared_orgs=%s chose=%s alternatives=%s tiebreak=%s "
            "vote_activity=%s",
            d_id, delegator_id, delegate_id, shared, chosen, alternatives,
            telemetry.get("tiebreak"), telemetry.get("per_org"),
        )
        bind.execute(
            sa.text("UPDATE delegations SET org_id = :oid WHERE id = :did"),
            {"oid": chosen, "did": d_id},
        )
        _audit(
            bind,
            action="delegation.org_id_backfilled",
            target_type="delegation",
            target_id=d_id,
            details={
                "old_state": {"org_id": None},
                "new_state": {"org_id": chosen},
                "sweep_number": 3,
                "ambiguity_resolution": "multi_shared_org_recent_activity",
                "shared_orgs": shared,
                "alternatives": alternatives,
                "tiebreak": telemetry.get("tiebreak"),
                "vote_activity": telemetry.get("per_org"),
            },
        )
        stats["sweep3"] += 1

    return stats


# ---------------------------------------------------------------------------
# Backfill: DelegationIntent
# ---------------------------------------------------------------------------


def _backfill_delegation_intents(bind) -> dict:
    """Same shape as Delegation, applied to DelegationIntent rows.

    Topic-scoped intents inherit org from the topic; globals get the
    shared-org-or-most-recent-activity heuristic.
    """
    inspector = sa.inspect(bind)
    if "delegation_intents" not in inspector.get_table_names():
        return {"sweep1": 0, "sweep2": 0, "sweep3": 0, "warnings": 0}

    stats = {"sweep1": 0, "sweep2": 0, "sweep3": 0, "warnings": 0}

    # Topic-scoped intents.
    rows = bind.execute(
        sa.text(
            "SELECT i.id, i.delegator_id, i.delegate_id, i.topic_id, "
            "       t.org_id, t.sub_org_id "
            "FROM delegation_intents i "
            "JOIN topics t ON t.id = i.topic_id "
            "WHERE i.topic_id IS NOT NULL "
            "  AND (i.org_id IS NULL OR i.org_id = '')"
        )
    ).fetchall()
    for row in rows:
        i_id, delegator_id, delegate_id, topic_id, t_org_id, t_sub_org_id = row
        if not t_org_id:
            stats["warnings"] += 1
            _LOG.warning(
                "Phase 18a: delegation_intent %s topic %s has no org_id; "
                "leaving intent org_id NULL.",
                i_id, topic_id,
            )
            continue
        bind.execute(
            sa.text(
                "UPDATE delegation_intents "
                "SET org_id = :oid, sub_org_id = :soid "
                "WHERE id = :iid"
            ),
            {"oid": t_org_id, "soid": t_sub_org_id, "iid": i_id},
        )
        _audit(
            bind,
            action="delegation_intent.org_id_backfilled",
            target_type="delegation_intent",
            target_id=i_id,
            details={
                "old_state": {"org_id": None, "sub_org_id": None},
                "new_state": {"org_id": t_org_id, "sub_org_id": t_sub_org_id},
                "sweep_number": 1,
                "ambiguity_resolution": "topic_join",
            },
        )
        stats["sweep1"] += 1

    # Global intents.
    global_rows = bind.execute(
        sa.text(
            "SELECT id, delegator_id, delegate_id "
            "FROM delegation_intents "
            "WHERE topic_id IS NULL "
            "  AND (org_id IS NULL OR org_id = '')"
        )
    ).fetchall()
    for i_id, delegator_id, delegate_id in global_rows:
        shared = _shared_org_ids(bind, delegator_id, delegate_id)
        if not shared:
            stats["warnings"] += 1
            _LOG.warning(
                "Phase 18a: delegation_intent %s shares zero orgs; "
                "leaving org_id NULL.",
                i_id,
            )
            continue
        if len(shared) == 1:
            chosen = shared[0]
            sweep_n = 2
            details_extra = {
                "ambiguity_resolution": "single_shared_org",
                "shared_orgs": shared,
            }
        else:
            chosen, telemetry = _user_recent_org(bind, delegate_id, shared)
            alternatives = [o for o in shared if o != chosen]
            _LOG.info(
                "Phase 18a sweep 3 (delegation_intent %s): chose=%s "
                "alternatives=%s tiebreak=%s",
                i_id, chosen, alternatives, telemetry.get("tiebreak"),
            )
            sweep_n = 3
            details_extra = {
                "ambiguity_resolution": "multi_shared_org_recent_activity",
                "shared_orgs": shared,
                "alternatives": alternatives,
                "tiebreak": telemetry.get("tiebreak"),
                "vote_activity": telemetry.get("per_org"),
            }
        bind.execute(
            sa.text(
                "UPDATE delegation_intents SET org_id = :oid WHERE id = :iid"
            ),
            {"oid": chosen, "iid": i_id},
        )
        _audit(
            bind,
            action="delegation_intent.org_id_backfilled",
            target_type="delegation_intent",
            target_id=i_id,
            details={
                "old_state": {"org_id": None},
                "new_state": {"org_id": chosen},
                "sweep_number": sweep_n,
                **details_extra,
            },
        )
        if sweep_n == 2:
            stats["sweep2"] += 1
        else:
            stats["sweep3"] += 1

    return stats


# ---------------------------------------------------------------------------
# Backfill: FollowRelationship + FollowRequest
# ---------------------------------------------------------------------------


def _user_primary_org(bind, user_id: str) -> tuple[str | None, dict]:
    """The user's primary org by recent vote count. Used for view_only
    follows where the followed user's "where they live" is the right anchor.

    Falls back to the user's first active org_membership by org_id ASC if
    they have no votes anywhere.
    """
    rows = bind.execute(
        sa.text(
            "SELECT p.org_id, COUNT(v.id) AS vote_count, MAX(v.cast_at) AS latest "
            "FROM votes v "
            "JOIN proposals p ON p.id = v.proposal_id "
            "WHERE v.user_id = :uid "
            "  AND p.org_id IS NOT NULL "
            "GROUP BY p.org_id "
            "ORDER BY vote_count DESC, latest DESC"
        ),
        {"uid": user_id},
    ).fetchall()
    def _norm(val):
        if val is None:
            return None
        return val.isoformat() if hasattr(val, "isoformat") else str(val)

    per_org = {r[0]: {"votes": r[1], "latest": _norm(r[2])}
               for r in rows}
    if rows:
        return rows[0][0], {"per_org": per_org, "tiebreak": "max_vote_count"}

    # Fallback: any active org_membership.
    fallback = bind.execute(
        sa.text(
            "SELECT org_id FROM org_memberships "
            "WHERE user_id = :uid AND status = 'active' "
            "ORDER BY org_id ASC LIMIT 1"
        ),
        {"uid": user_id},
    ).first()
    if fallback:
        return fallback[0], {"per_org": {}, "tiebreak": "first_active_membership"}
    return None, {"per_org": {}, "tiebreak": "no_membership"}


def _backfill_follow_relationships(bind) -> dict:
    inspector = sa.inspect(bind)
    if "follow_relationships" not in inspector.get_table_names():
        return {"delegation_allowed": 0, "view_only": 0, "warnings": 0}

    stats = {"delegation_allowed": 0, "view_only": 0, "warnings": 0}
    rows = bind.execute(
        sa.text(
            "SELECT id, follower_id, followed_id, permission_level "
            "FROM follow_relationships "
            "WHERE org_id IS NULL OR org_id = ''"
        )
    ).fetchall()
    for r_id, follower_id, followed_id, perm in rows:
        if perm == "delegation_allowed":
            shared = _shared_org_ids(bind, follower_id, followed_id)
            if not shared:
                stats["warnings"] += 1
                _LOG.warning(
                    "Phase 18a: follow_relationship %s (delegation_allowed) "
                    "shares zero orgs; leaving org_id NULL.",
                    r_id,
                )
                continue
            if len(shared) == 1:
                chosen = shared[0]
                resolution = "single_shared_org"
                details_extra = {"shared_orgs": shared}
            else:
                chosen, telemetry = _user_recent_org(bind, followed_id, shared)
                alternatives = [o for o in shared if o != chosen]
                _LOG.info(
                    "Phase 18a (follow_relationship %s, delegation_allowed): "
                    "chose=%s alternatives=%s tiebreak=%s",
                    r_id, chosen, alternatives, telemetry.get("tiebreak"),
                )
                resolution = "multi_shared_org_recent_activity"
                details_extra = {
                    "shared_orgs": shared,
                    "alternatives": alternatives,
                    "tiebreak": telemetry.get("tiebreak"),
                    "vote_activity": telemetry.get("per_org"),
                }
            stats["delegation_allowed"] += 1
        else:
            # view_only
            chosen, telemetry = _user_primary_org(bind, followed_id)
            if not chosen:
                stats["warnings"] += 1
                _LOG.warning(
                    "Phase 18a: follow_relationship %s (view_only) — "
                    "followed user %s has no resolvable primary org; "
                    "leaving org_id NULL.",
                    r_id, followed_id,
                )
                continue
            resolution = "view_only_followed_primary_org"
            details_extra = {
                "tiebreak": telemetry.get("tiebreak"),
                "vote_activity": telemetry.get("per_org"),
            }
            stats["view_only"] += 1

        bind.execute(
            sa.text(
                "UPDATE follow_relationships SET org_id = :oid WHERE id = :rid"
            ),
            {"oid": chosen, "rid": r_id},
        )
        _audit(
            bind,
            action="follow_relationship.org_id_backfilled",
            target_type="follow_relationship",
            target_id=r_id,
            details={
                "old_state": {"org_id": None},
                "new_state": {"org_id": chosen},
                "permission_level": perm,
                "ambiguity_resolution": resolution,
                **details_extra,
            },
        )
    return stats


def _backfill_follow_requests(bind) -> dict:
    inspector = sa.inspect(bind)
    if "follow_requests" not in inspector.get_table_names():
        return {"delegation_allowed": 0, "view_only": 0, "warnings": 0}

    stats = {"delegation_allowed": 0, "view_only": 0, "warnings": 0}
    rows = bind.execute(
        sa.text(
            "SELECT id, requester_id, target_id, permission_level "
            "FROM follow_requests "
            "WHERE org_id IS NULL OR org_id = ''"
        )
    ).fetchall()
    for r_id, requester_id, target_id, perm in rows:
        # Treat NULL permission_level (legacy) as view_only — same backfill.
        is_delegation = perm == "delegation_allowed"
        if is_delegation:
            shared = _shared_org_ids(bind, requester_id, target_id)
            if not shared:
                stats["warnings"] += 1
                _LOG.warning(
                    "Phase 18a: follow_request %s (delegation_allowed) "
                    "shares zero orgs; leaving org_id NULL.",
                    r_id,
                )
                continue
            if len(shared) == 1:
                chosen = shared[0]
                resolution = "single_shared_org"
                details_extra = {"shared_orgs": shared}
            else:
                chosen, telemetry = _user_recent_org(bind, target_id, shared)
                alternatives = [o for o in shared if o != chosen]
                _LOG.info(
                    "Phase 18a (follow_request %s, delegation_allowed): "
                    "chose=%s alternatives=%s tiebreak=%s",
                    r_id, chosen, alternatives, telemetry.get("tiebreak"),
                )
                resolution = "multi_shared_org_recent_activity"
                details_extra = {
                    "shared_orgs": shared,
                    "alternatives": alternatives,
                    "tiebreak": telemetry.get("tiebreak"),
                    "vote_activity": telemetry.get("per_org"),
                }
            stats["delegation_allowed"] += 1
        else:
            chosen, telemetry = _user_primary_org(bind, target_id)
            if not chosen:
                stats["warnings"] += 1
                _LOG.warning(
                    "Phase 18a: follow_request %s (view_only/null) — "
                    "target user %s has no resolvable primary org; "
                    "leaving org_id NULL.",
                    r_id, target_id,
                )
                continue
            resolution = "view_only_target_primary_org"
            details_extra = {
                "tiebreak": telemetry.get("tiebreak"),
                "vote_activity": telemetry.get("per_org"),
            }
            stats["view_only"] += 1

        bind.execute(
            sa.text(
                "UPDATE follow_requests SET org_id = :oid WHERE id = :rid"
            ),
            {"oid": chosen, "rid": r_id},
        )
        _audit(
            bind,
            action="follow_request.org_id_backfilled",
            target_type="follow_request",
            target_id=r_id,
            details={
                "old_state": {"org_id": None},
                "new_state": {"org_id": chosen},
                "permission_level": perm,
                "ambiguity_resolution": resolution,
                **details_extra,
            },
        )
    return stats


# ---------------------------------------------------------------------------
# upgrade / downgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ----- 1. Add columns. -----
    if "delegations" in inspector.get_table_names():
        _maybe_add_column(
            bind, inspector, "delegations", "org_id",
            sa.Column("org_id", sa.String(), nullable=True),
            "fk_delegations_org_id", "organizations",
            "ix_delegations_org_id",
        )
        # Re-inspect after the column add so the next call sees fresh state.
        inspector = sa.inspect(bind)
        _maybe_add_column(
            bind, inspector, "delegations", "sub_org_id",
            sa.Column("sub_org_id", sa.String(), nullable=True),
            "fk_delegations_sub_org_id", "organizations",
            "ix_delegations_sub_org_id",
        )
        inspector = sa.inspect(bind)

    if "delegation_intents" in inspector.get_table_names():
        _maybe_add_column(
            bind, inspector, "delegation_intents", "org_id",
            sa.Column("org_id", sa.String(), nullable=True),
            "fk_delegation_intents_org_id", "organizations",
            "ix_delegation_intents_org_id",
        )
        inspector = sa.inspect(bind)
        _maybe_add_column(
            bind, inspector, "delegation_intents", "sub_org_id",
            sa.Column("sub_org_id", sa.String(), nullable=True),
            "fk_delegation_intents_sub_org_id", "organizations",
            "ix_delegation_intents_sub_org_id",
        )
        inspector = sa.inspect(bind)

    if "follow_relationships" in inspector.get_table_names():
        _maybe_add_column(
            bind, inspector, "follow_relationships", "org_id",
            sa.Column("org_id", sa.String(), nullable=True),
            "fk_follow_relationships_org_id", "organizations",
            "ix_follow_relationships_org_id",
        )
        inspector = sa.inspect(bind)

    if "follow_requests" in inspector.get_table_names():
        _maybe_add_column(
            bind, inspector, "follow_requests", "org_id",
            sa.Column("org_id", sa.String(), nullable=True),
            "fk_follow_requests_org_id", "organizations",
            "ix_follow_requests_org_id",
        )
        inspector = sa.inspect(bind)

    # ----- 2. Backfills. -----
    delegation_stats = _backfill_delegations(bind)
    intent_stats = _backfill_delegation_intents(bind)
    follow_rel_stats = _backfill_follow_relationships(bind)
    follow_req_stats = _backfill_follow_requests(bind)

    _LOG.info(
        "Phase 18a backfill summary: delegations=%s intents=%s "
        "follow_relationships=%s follow_requests=%s",
        delegation_stats, intent_stats, follow_rel_stats, follow_req_stats,
    )

    # ----- 3. Unique constraint updates. -----
    inspector = sa.inspect(bind)

    # Delegation: drop old (delegator_id, topic_id), add (delegator_id,
    # org_id, sub_org_id, topic_id).
    _maybe_drop_unique(
        bind, inspector, "delegations", "uq_delegation_delegator_topic",
    )
    inspector = sa.inspect(bind)
    _maybe_create_unique(
        bind, inspector, "delegations",
        "uq_delegation_delegator_org_subor_topic",
        ["delegator_id", "org_id", "sub_org_id", "topic_id"],
    )

    # DelegationIntent: drop old (delegator_id, delegate_id, topic_id), add
    # (delegator_id, delegate_id, org_id, sub_org_id, topic_id) — keep the
    # delegate_id in the constraint per the existing intent shape.
    inspector = sa.inspect(bind)
    _maybe_drop_unique(
        bind, inspector, "delegation_intents", "uq_delegation_intent",
    )
    inspector = sa.inspect(bind)
    _maybe_create_unique(
        bind, inspector, "delegation_intents",
        "uq_delegation_intent_org_subor",
        ["delegator_id", "delegate_id", "org_id", "sub_org_id", "topic_id"],
    )


def downgrade() -> None:
    """Drop the new columns and reinstate the prior unique constraints.

    NOT NULL backfill is irreversible — downgrading loses the inferred org
    context. Best-effort schema rollback only.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Drop the new constraints first, restore the originals.
    _maybe_drop_unique(
        bind, inspector, "delegations",
        "uq_delegation_delegator_org_subor_topic",
    )
    inspector = sa.inspect(bind)
    _maybe_create_unique(
        bind, inspector, "delegations", "uq_delegation_delegator_topic",
        ["delegator_id", "topic_id"],
    )

    inspector = sa.inspect(bind)
    _maybe_drop_unique(
        bind, inspector, "delegation_intents",
        "uq_delegation_intent_org_subor",
    )
    inspector = sa.inspect(bind)
    _maybe_create_unique(
        bind, inspector, "delegation_intents", "uq_delegation_intent",
        ["delegator_id", "delegate_id", "topic_id"],
    )

    # Drop the columns. Use batch_alter_table to handle SQLite.
    inspector = sa.inspect(bind)

    def _maybe_drop_col(table: str, col_name: str, fk_name: str,
                        ix_name: str) -> None:
        existing_cols = {c["name"] for c in inspector.get_columns(table)}
        if col_name not in existing_cols:
            return
        with op.batch_alter_table(table, schema=None) as batch_op:
            try:
                batch_op.drop_constraint(fk_name, type_="foreignkey")
            except Exception:
                # SQLite may not have the FK as a named constraint; ignore.
                pass
            try:
                batch_op.drop_index(ix_name)
            except Exception:
                pass
            batch_op.drop_column(col_name)

    if "delegations" in inspector.get_table_names():
        _maybe_drop_col(
            "delegations", "sub_org_id",
            "fk_delegations_sub_org_id", "ix_delegations_sub_org_id",
        )
        inspector = sa.inspect(bind)
        _maybe_drop_col(
            "delegations", "org_id",
            "fk_delegations_org_id", "ix_delegations_org_id",
        )
        inspector = sa.inspect(bind)

    if "delegation_intents" in inspector.get_table_names():
        _maybe_drop_col(
            "delegation_intents", "sub_org_id",
            "fk_delegation_intents_sub_org_id",
            "ix_delegation_intents_sub_org_id",
        )
        inspector = sa.inspect(bind)
        _maybe_drop_col(
            "delegation_intents", "org_id",
            "fk_delegation_intents_org_id",
            "ix_delegation_intents_org_id",
        )
        inspector = sa.inspect(bind)

    if "follow_relationships" in inspector.get_table_names():
        _maybe_drop_col(
            "follow_relationships", "org_id",
            "fk_follow_relationships_org_id",
            "ix_follow_relationships_org_id",
        )
        inspector = sa.inspect(bind)

    if "follow_requests" in inspector.get_table_names():
        _maybe_drop_col(
            "follow_requests", "org_id",
            "fk_follow_requests_org_id",
            "ix_follow_requests_org_id",
        )
