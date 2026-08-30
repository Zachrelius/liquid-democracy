"""Phase 104 compact proposal-management feed and eligibility rules."""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy import and_, false, func, or_
from sqlalchemy.orm import Session, load_only

import models
import schemas
from proposal_pagination import (
    decode_proposal_cursor,
    encode_proposal_cursor,
    proposal_after_cursor,
    proposal_ordering,
)


STORED_STATUSES = frozenset({
    "draft",
    "deliberation",
    "voting",
    "passed",
    "failed",
    "withdrawn",
    "unresolved",
    "expired_unsigned",
})
VALID_MANAGEMENT_STATUSES = STORED_STATUSES | {"all"}
ELIGIBLE_OPERATIONS = (
    "draft_to_deliberation",
    "deliberation_to_voting",
    "schedule_start",
    "set_end",
)


def is_structurally_eligible(proposal: models.Proposal, operation: str) -> bool:
    if operation == "draft_to_deliberation":
        return proposal.status == "draft"
    if operation in {"deliberation_to_voting", "schedule_start"}:
        return proposal.status == "deliberation" and not proposal.is_cosign_gated
    if operation == "set_end":
        return proposal.status in {"deliberation", "voting"}
    raise ValueError(f"Unknown management operation: {operation}")


def structural_eligibility_predicate(operation: str):
    p = models.Proposal
    if operation == "draft_to_deliberation":
        return p.status == "draft"
    if operation in {"deliberation_to_voting", "schedule_start"}:
        return and_(p.status == "deliberation", p.is_cosign_gated.is_(False))
    if operation == "set_end":
        return p.status.in_(("deliberation", "voting"))
    raise HTTPException(
        status_code=422,
        detail={
            "code": "invalid_management_operation",
            "allowed": list(ELIGIBLE_OPERATIONS),
        },
    )


def eligible_operations(proposal: models.Proposal) -> list[str]:
    return [
        operation
        for operation in ELIGIBLE_OPERATIONS
        if is_structurally_eligible(proposal, operation)
    ]


def management_visibility(
    db: Session,
    parent: models.Organization,
    viewer: models.User,
    *,
    is_admin: bool,
):
    """Parent management visibility applied before every filter and limit."""
    p = models.Proposal
    if is_admin:
        return p.org_id == parent.id
    visible_sub_orgs = db.query(models.SubOrgMembership.sub_org_id).filter(
        models.SubOrgMembership.user_id == viewer.id,
        models.SubOrgMembership.status == "active",
    )
    non_private_sub_orgs = db.query(models.Organization.id).filter(
        models.Organization.parent_org_id == parent.id,
        func.coalesce(
            models.Organization.settings["private"].as_boolean(), false(),
        ).is_(False),
    )
    return and_(
        p.org_id == parent.id,
        or_(
            p.sub_org_id.is_(None),
            p.sub_org_id.in_(visible_sub_orgs),
            p.sub_org_id.in_(non_private_sub_orgs),
        ),
    )


def _literal_title_pattern(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def build_management_feed(
    db: Session,
    *,
    visibility,
    status: str = "all",
    sub_org_id: Optional[str] = None,
    parent_only: bool = False,
    title_query: Optional[str] = None,
    eligible_for: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: int = 50,
) -> schemas.ProposalManagementFeedOut:
    if status not in VALID_MANAGEMENT_STATUSES:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_management_status",
                "allowed": sorted(VALID_MANAGEMENT_STATUSES),
            },
        )
    if sub_org_id and parent_only:
        raise HTTPException(
            status_code=422,
            detail={"code": "mutually_exclusive_management_scope"},
        )
    if eligible_for is not None and eligible_for not in ELIGIBLE_OPERATIONS:
        structural_eligibility_predicate(eligible_for)

    query = db.query(models.Proposal).options(load_only(
        models.Proposal.id,
        models.Proposal.title,
        models.Proposal.status,
        models.Proposal.voting_method,
        models.Proposal.num_winners,
        models.Proposal.created_at,
        models.Proposal.updated_at,
        models.Proposal.sub_org_id,
        models.Proposal.deliberation_end,
        models.Proposal.voting_end_date,
        models.Proposal.voting_end,
        models.Proposal.is_cosign_gated,
    )).filter(visibility)
    if status != "all":
        query = query.filter(models.Proposal.status == status)
    if sub_org_id:
        query = query.filter(models.Proposal.sub_org_id == sub_org_id)
    elif parent_only:
        query = query.filter(models.Proposal.sub_org_id.is_(None))
    normalized_query = (title_query or "").strip()
    if normalized_query:
        pattern = f"%{_literal_title_pattern(normalized_query.lower())}%"
        query = query.filter(
            func.lower(models.Proposal.title).like(pattern, escape="\\")
        )
    if eligible_for:
        query = query.filter(structural_eligibility_predicate(eligible_for))
    if cursor:
        decoded = decode_proposal_cursor(
            cursor,
            error_code="invalid_management_cursor",
            error_message="Malformed proposal management cursor",
        )
        query = query.filter(proposal_after_cursor(decoded))

    rows = query.order_by(*proposal_ordering()).limit(limit + 1).all()
    has_more = len(rows) > limit
    page = rows[:limit]
    return schemas.ProposalManagementFeedOut(
        items=[
            schemas.ProposalManagementItemOut(
                id=proposal.id,
                title=proposal.title,
                status=proposal.status,
                voting_method=proposal.voting_method or "binary",
                num_winners=proposal.num_winners,
                created_at=proposal.created_at,
                sub_org_id=proposal.sub_org_id,
                deliberation_end=proposal.deliberation_end,
                voting_end_date=proposal.voting_end_date,
                voting_end=proposal.voting_end,
                is_cosign_gated=bool(proposal.is_cosign_gated),
                eligible_operations=eligible_operations(proposal),
            )
            for proposal in page
        ],
        next_cursor=(
            encode_proposal_cursor(page[-1]) if has_more and page else None
        ),
        has_more=has_more,
    )
