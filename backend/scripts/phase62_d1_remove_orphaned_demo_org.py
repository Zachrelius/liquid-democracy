"""Phase 62 D1 — replacement for the Phase 59 cleanup script.

Phase 59 shipped a removal script for the orphaned ``slug='demo'`` org
but used ORM bulk-delete (``query.delete()``), which in SQLAlchemy 2.x
does NOT trigger relationship cascades. Against real prod data (with
proposal_topics + votes + a sub-org + delegate_vote_rationales) the
run failed with successive FK violations.

This script enumerates every NO-ACTION FK targeting our deletion set
(orgs, proposals, topics, votes, roles) and clears them in dependency
order before deleting the parent rows. Wrapped in a single
transaction so a mid-run failure leaves prod untouched.

USAGE
-----

Dry-run (default):

    DATABASE_URL=postgresql://... \\
        python backend/scripts/phase62_d1_remove_orphaned_demo_org.py

Apply:

    DATABASE_URL=postgresql://... \\
        python backend/scripts/phase62_d1_remove_orphaned_demo_org.py --confirm

Safety:
  * Aborts if any org in the set has ``is_demo=True``, ``personas``,
    or ``governance_type`` set — those are 3-bible managed orgs that
    must not be touched.
  * Aborts if the root slug isn't ``demo``.
  * Single-transaction commit. Failure rolls everything back.
  * Audit ``org.deleted`` rows written per deleted org.
"""
from __future__ import annotations

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from sqlalchemy import text  # noqa: E402

import models  # noqa: E402
from database import SessionLocal  # noqa: E402
from audit_utils import log_audit_event  # noqa: E402


ORPHAN_SLUG = "demo"


def _safe_to_delete(org: "models.Organization") -> tuple[bool, str]:
    if org.is_demo:
        return False, f"org {org.slug!r} has is_demo=True (bible-managed)"
    if org.personas:
        return False, f"org {org.slug!r} has personas set (bible-managed)"
    if org.governance_type:
        return False, (
            f"org {org.slug!r} has governance_type set "
            f"({org.governance_type!r}) — looks bible-managed"
        )
    return True, ""


def _try(db, stmt_str: str, params: dict) -> None:
    """Run a delete/update statement under a SAVEPOINT. Failures (missing
    table, missing column) roll back the savepoint and continue."""
    sp = db.begin_nested()
    try:
        db.execute(text(stmt_str), params)
        sp.commit()
    except Exception as ex:
        sp.rollback()
        print(f"  [_try] swallowed: {stmt_str[:60]!r} -> {ex.__class__.__name__}: {str(ex)[:100]}")


def _delete_org_tree(db, org_id: str) -> None:
    """Hard-delete one org's dependents in FK-dependency order.

    Caller is responsible for the org row delete itself (this function
    only clears references). Caller is responsible for the transaction.
    """
    params = {"org_id": org_id}

    # ── 0. Clear cross-org sub_org_id refs FIRST so this org can be
    # the target of a delete even if other orgs scoped data to it.
    # No savepoint — these are plain UPDATEs that always work for
    # tables we know exist.
    for stmt in (
        "UPDATE topics SET sub_org_id = NULL WHERE sub_org_id = :org_id",
        "UPDATE proposals SET sub_org_id = NULL WHERE sub_org_id = :org_id",
        (
            "UPDATE delegate_profiles SET sub_org_id = NULL "
            "WHERE sub_org_id = :org_id"
        ),
        (
            "UPDATE delegation_intents SET sub_org_id = NULL "
            "WHERE sub_org_id = :org_id"
        ),
        (
            "UPDATE delegations SET sub_org_id = NULL "
            "WHERE sub_org_id = :org_id"
        ),
        "UPDATE polises SET sub_org_id = NULL WHERE sub_org_id = :org_id",
    ):
        db.execute(text(stmt), params)

    # ── 1. Gather proposal_ids + topic_ids owned by this org.
    proposal_ids = [
        r[0] for r in db.execute(
            text("SELECT id FROM proposals WHERE org_id = :org_id"),
            params,
        ).fetchall()
    ]
    topic_ids = [
        r[0] for r in db.execute(
            text("SELECT id FROM topics WHERE org_id = :org_id"),
            params,
        ).fetchall()
    ]
    vote_ids = []
    if proposal_ids:
        vote_ids = [
            r[0] for r in db.execute(
                text("SELECT id FROM votes WHERE proposal_id IN :ids"),
                {"ids": tuple(proposal_ids)},
            ).fetchall()
        ]

    # ── 2. Vote-level dependents (delegate_vote_rationales).
    if vote_ids:
        in_v = {"ids": tuple(vote_ids)}
        for stmt in (
            "DELETE FROM delegate_vote_rationales WHERE vote_id IN :ids",
        ):
            _try(db, stmt, in_v)

    # ── 3. Proposal-level dependents (NO ACTION FKs). Must succeed —
    # any failure here means we missed a FK and the org delete will
    # fail loudly downstream. No savepoint wrapper; raise on error.
    if proposal_ids:
        in_p = {"ids": tuple(proposal_ids)}
        for stmt in (
            "DELETE FROM proposal_topics WHERE proposal_id IN :ids",
            "DELETE FROM proposal_options WHERE proposal_id IN :ids",
            "DELETE FROM vote_snapshots WHERE proposal_id IN :ids",
            "DELETE FROM votes WHERE proposal_id IN :ids",
            "DELETE FROM proposal_revisions WHERE proposal_id IN :ids",
        ):
            db.execute(text(stmt), in_p)

    # ── 4. Delete proposals.
    db.execute(
        text("DELETE FROM proposals WHERE org_id = :org_id"),
        params,
    )

    # ── 5a. Delete delegate_profiles FIRST (their topic_id FK is
    # NOT NULL, so we can't NULL it; deletion is the only path).
    db.execute(
        text("DELETE FROM delegate_profiles WHERE org_id = :org_id"),
        params,
    )

    # ── 5b. Topic-referencing tables — clear nullable refs first.
    if topic_ids:
        in_t = {"ids": tuple(topic_ids)}
        for stmt in (
            "UPDATE delegations SET topic_id = NULL WHERE topic_id IN :ids",
            (
                "UPDATE delegation_intents SET topic_id = NULL "
                "WHERE topic_id IN :ids"
            ),
            "DELETE FROM topic_precedences WHERE topic_id IN :ids",
        ):
            db.execute(text(stmt), in_t)

    db.execute(text("DELETE FROM topics WHERE org_id = :org_id"), params)

    # ── 6. Org-level direct (NO ACTION org_id FKs). The order matters:
    # delegation_intents must be deleted before follow_requests
    # because delegation_intents.follow_request_id has a NO-ACTION FK,
    # AND we must catch delegation_intents whose org_id is DIFFERENT
    # but whose follow_request_id points at the orphan (data
    # anomaly seen on prod). Same shape applies to delegations vs
    # follow_relationships.
    db.execute(
        text(
            "DELETE FROM delegation_intents "
            "WHERE org_id = :org_id "
            "OR follow_request_id IN ("
            "  SELECT id FROM follow_requests WHERE org_id = :org_id"
            ")"
        ),
        params,
    )
    for stmt in (
        "DELETE FROM delegations WHERE org_id = :org_id",
        "DELETE FROM follow_relationships WHERE org_id = :org_id",
        "DELETE FROM follow_requests WHERE org_id = :org_id",
        "DELETE FROM invitations WHERE org_id = :org_id",
        "DELETE FROM notifications WHERE org_id = :org_id",
        "DELETE FROM org_delegate_profiles WHERE org_id = :org_id",
        "DELETE FROM org_memberships WHERE org_id = :org_id",
        "DELETE FROM pending_admin_actions WHERE org_id = :org_id",
        "DELETE FROM polis_xids WHERE org_id = :org_id",
        "DELETE FROM polises WHERE org_id = :org_id",
        "DELETE FROM proposal_revisions WHERE org_id = :org_id",
        "DELETE FROM sub_org_memberships WHERE sub_org_id = :org_id",
    ):
        result = db.execute(text(stmt), params)
        if result.rowcount > 0:
            print(f"  deleted {result.rowcount} rows: {stmt[:70]}")

    # ── 6b. Sub-org memberships of any child orgs whose role_id FK
    # points back at THIS org's roles. (sub_org_memberships.role_id
    # is the parent org's role; clearing them here lets the role
    # delete below proceed.)
    db.execute(
        text(
            "DELETE FROM sub_org_memberships WHERE sub_org_id IN ("
            "  SELECT id FROM organizations WHERE parent_org_id = :org_id"
            ")"
        ),
        params,
    )

    # ── 7. Roles cascade to role_permissions on delete.
    db.execute(text("DELETE FROM roles WHERE org_id = :org_id"), params)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 62 D1 — remove the orphan slug='demo' org (and its "
            "sub-orgs) in FK-dependency order."
        ),
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Apply. Without this flag the script dry-runs.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        root = (
            db.query(models.Organization)
            .filter_by(slug=ORPHAN_SLUG)
            .first()
        )
        if root is None:
            print(
                f"[phase62-d1] No Organization with slug={ORPHAN_SLUG!r} "
                f"found. Nothing to do. (idempotent)"
            )
            return 0

        sub_orgs = (
            db.query(models.Organization)
            .filter_by(parent_org_id=root.id)
            .all()
        )
        all_orgs = [root, *sub_orgs]

        for org in all_orgs:
            ok, why = _safe_to_delete(org)
            if not ok:
                print(f"[phase62-d1] ABORT: {why}")
                return 2

        print(
            f"[phase62-d1] Plan: delete root org {root.slug!r} "
            f"(id={root.id}) plus {len(sub_orgs)} sub-org(s):"
        )
        for so in sub_orgs:
            print(f"    sub-org: {so.slug!r} (id={so.id})")
        for org in all_orgs:
            counts = {
                "memberships": (
                    db.query(models.OrgMembership)
                    .filter_by(org_id=org.id).count()
                ),
                "proposals": (
                    db.query(models.Proposal)
                    .filter_by(org_id=org.id).count()
                ),
                "topics": (
                    db.query(models.Topic)
                    .filter_by(org_id=org.id).count()
                ),
                "delegations": (
                    db.query(models.Delegation)
                    .filter_by(org_id=org.id).count()
                ),
                "delegate_profiles": (
                    db.query(models.DelegateProfile)
                    .filter_by(org_id=org.id).count()
                ),
            }
            print(f"    {org.slug}: {counts}")

        if not args.confirm:
            print("\n[phase62-d1] DRY RUN. Pass --confirm to apply.")
            return 0

        print("[phase62-d1] --confirm given. Applying...")

        for org in all_orgs:
            log_audit_event(
                db,
                action="org.deleted",
                target_type="organization",
                target_id=org.id,
                actor_id=None,
                details={
                    "phase": "62-d1",
                    "reason": (
                        "Orphan legacy demo org cleanup; predates "
                        "Phase 23 three-bible system."
                    ),
                    "slug": org.slug,
                    "name": org.name,
                    "via": (
                        "backend/scripts/phase62_d1_remove_orphaned_demo_org.py"
                    ),
                },
            )

        # Root first so its sub_org_id-scoped topics/proposals are
        # cleared before we touch the sub-orgs themselves.
        _delete_org_tree(db, root.id)
        for so in sub_orgs:
            _delete_org_tree(db, so.id)
            db.execute(
                text("DELETE FROM organizations WHERE id = :oid"),
                {"oid": so.id},
            )
        db.execute(
            text("DELETE FROM organizations WHERE id = :oid"),
            {"oid": root.id},
        )
        db.commit()

        survivor = (
            db.query(models.Organization)
            .filter_by(slug=ORPHAN_SLUG)
            .first()
        )
        assert survivor is None, "root org survived the delete"
        print(
            f"[phase62-d1] DONE. Orphan {ORPHAN_SLUG!r} + "
            f"{len(sub_orgs)} sub-org(s) removed."
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
