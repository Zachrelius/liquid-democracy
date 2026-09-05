"""Phase 41 (2026-05-28) — eligibility predicates for proposals.

Promoted from `routes/comments.py` where the canonical proposal-viewer
eligibility predicate was originally inlined (Phase 10 first proposal-
scoped viewer set). Phase 38 expanded the predicate's consumers to
include the list / get / results routes in `routes/proposals.py` plus
the WebSocket handler in `main.py`; the cross-route import shape
(routes/proposals.py importing from routes/comments.py) was structurally
backwards and made the dependency graph harder to reason about.

This module is the canonical home. `routes/comments.py` re-exports the
function name for back-compat with any external tooling that may have
grepped the routes/comments source — but new callers should import from
`eligibility` directly.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

import models


_ADMIN_TIER_SYSTEM_KEYS = ("admin", "steward")


def eligible_viewers_for_proposal(
    db: Session, proposal: models.Proposal, *, user_id: str | None = None,
) -> set[str]:
    """Return the set of user IDs who can VIEW a proposal (and its comments).

    Optional ``user_id`` narrows SQL to one viewer without duplicating policy.

    Mirrors ``polis_engine.eligible_viewers_for_polis`` for the Proposal
    artifact. Phase 8.5 Decisions 3, 6, 7 apply identically:

      * Org-wide proposal (``sub_org_id`` IS NULL with non-null ``org_id``):
        all active OrgMembership members of ``proposal.org_id``.
      * Sub-org-scoped proposal (``sub_org_id`` IS NOT NULL):
        - active SubOrgMembership of ``proposal.sub_org_id``;
        - PLUS active OrgMembership admins/owners of the parent org
          (Decision 6 — implicit power);
        - PLUS, when the sub-org's ``settings.private`` is False, all active
          parent-org members (Decision 7 — default visibility).
      * No org context (``org_id`` IS NULL): defensive fallback to "all
        users" so legacy / unit-test fixtures with no org keep working —
        same shape as ``delegation_engine.eligible_voter_ids_for_proposal``.
    """
    sub_org_id = getattr(proposal, "sub_org_id", None)
    org_id = getattr(proposal, "org_id", None)

    if sub_org_id is None and org_id is None:
        # Defensive: pre-multi-tenancy / unit-test fixture path.
        rows = db.query(models.User.id).filter(
            models.User.id == user_id if user_id is not None else True,
        ).all()
        return {r.id for r in rows}

    if sub_org_id is None:
        # Org-wide proposal — all active parent-org members.
        rows = db.query(models.OrgMembership.user_id).filter(
            models.OrgMembership.org_id == org_id,
            models.OrgMembership.status == "active",
            models.OrgMembership.user_id == user_id if user_id is not None else True,
        ).all()
        return {r.user_id for r in rows}

    # Sub-org-scoped.
    visible: set[str] = set()

    sub_rows = db.query(models.SubOrgMembership.user_id).filter(
        models.SubOrgMembership.sub_org_id == sub_org_id,
        models.SubOrgMembership.status == "active",
        models.SubOrgMembership.user_id == user_id if user_id is not None else True,
    ).all()
    visible.update(r.user_id for r in sub_rows)

    if org_id is not None:
        # Phase 12 — join through the Role table to get parent-org admin/
        # Steward members; the legacy string column is gone.
        parent_admins = (
            db.query(models.OrgMembership.user_id)
            .join(models.Role, models.Role.id == models.OrgMembership.role_id)
            .filter(
                models.OrgMembership.org_id == org_id,
                models.OrgMembership.status == "active",
                models.OrgMembership.user_id == user_id if user_id is not None else True,
                models.Role.system_key.in_(_ADMIN_TIER_SYSTEM_KEYS),
            )
            .all()
        )
        visible.update(r.user_id for r in parent_admins)

    sub_org = db.get(models.Organization, sub_org_id)
    is_private = False
    if sub_org is not None:
        settings = sub_org.settings or {}
        is_private = bool(settings.get("private", False))
    if not is_private and org_id is not None:
        parent_members = db.query(models.OrgMembership.user_id).filter(
            models.OrgMembership.org_id == org_id,
            models.OrgMembership.status == "active",
            models.OrgMembership.user_id == user_id if user_id is not None else True,
        ).all()
        visible.update(r.user_id for r in parent_members)

    return visible


def public_delegate_user_ids(
    db: Session, *, topic_id: str | None = None,
) -> set[str]:
    """Return the set of user IDs that count as 'public delegates' for
    identity-redaction purposes.

    A user is a public delegate iff they have AT LEAST ONE DelegateProfile
    row with ``visibility IN ('public', 'public_accepting')`` —
    optionally scoped to a single topic when ``topic_id`` is provided.

    Phase 41 (2026-05-28) — extracted from two inline reimplementations:
    ``routes/users.py::delegation_tree`` (Phase 37 B3 site, no topic
    filter) and ``routes/proposals.py::get_vote_graph`` (Phase 37 B3
    sibling, per-topic loop). The Phase 37 closeout flagged the inline
    duplication as Tier-3 followup. Single canonical predicate avoids
    drift if the public-tier visibility values change.
    """
    q = db.query(models.DelegateProfile.user_id).filter(
        models.DelegateProfile.visibility.in_(("public", "public_accepting")),
    )
    if topic_id is not None:
        q = q.filter(models.DelegateProfile.topic_id == topic_id)
    rows = q.all()
    return {r.user_id for r in rows}


__all__ = ["eligible_viewers_for_proposal", "public_delegate_user_ids"]
