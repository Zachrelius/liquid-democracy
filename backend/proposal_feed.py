"""Phase 103 compact, keyset-paginated proposal feed.

The module deliberately owns the shared query/order/cursor and viewer-state
projection used by member, public, and platform/global endpoints.  Aggregate
tallies are not computed here.
"""
from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

from fastapi import HTTPException
from sqlalchemy import and_, case, false, func, or_, true
from sqlalchemy.orm import Session, joinedload, selectinload

import models
import schemas
from delegation_engine import (
    Ballot,
    DelegationData,
    ProposalContext,
    resolve_vote_pure,
)
from org_config import proposal_is_delegation_gated


VALID_STATUSES = frozenset({
    "all", "deliberation", "voting", "unvoted", "passed", "failed", "archived",
})
CURSOR_VERSION = 1
_FUTURE = datetime(9999, 12, 31, 23, 59, 59)
_EPOCH = datetime(1970, 1, 1)


def validate_status(value: str) -> str:
    if value not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_feed_status", "allowed": sorted(VALID_STATUSES)},
        )
    return value


def _expressions():
    p = models.Proposal
    group = case(
        (p.status == "voting", 0),
        (p.status == "deliberation", 1),
        (p.status.in_(("passed", "failed", "withdrawn", "unresolved", "expired_unsigned")), 2),
        else_=3,
    )
    asc_key = case(
        (p.status == "voting", func.coalesce(p.voting_end, _FUTURE)),
        else_=_FUTURE,
    )
    desc_key = case(
        (p.status == "deliberation", p.created_at),
        (p.status.in_(("passed", "failed", "withdrawn", "unresolved", "expired_unsigned")),
         func.coalesce(p.updated_at, p.created_at)),
        else_=p.created_at,
    )
    return group, asc_key, desc_key


def _row_key(proposal: models.Proposal) -> tuple[int, datetime, datetime, datetime, str]:
    status = proposal.status
    group = 0 if status == "voting" else 1 if status == "deliberation" else (
        2 if status in {"passed", "failed", "withdrawn", "unresolved", "expired_unsigned"} else 3
    )
    asc_key = (proposal.voting_end or _FUTURE) if group == 0 else _FUTURE
    desc_key = (
        proposal.created_at if group in {1, 3}
        else (proposal.updated_at or proposal.created_at) if group == 2
        else proposal.created_at
    )
    return group, asc_key, desc_key, proposal.created_at, proposal.id


def encode_cursor(proposal: models.Proposal) -> str:
    group, asc_key, desc_key, created_at, proposal_id = _row_key(proposal)
    raw = json.dumps({
        "v": CURSOR_VERSION, "g": group, "a": asc_key.isoformat(),
        "d": desc_key.isoformat(), "c": created_at.isoformat(), "i": proposal_id,
    }, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(value: str) -> tuple[int, datetime, datetime, datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        data = json.loads(raw)
        if data.get("v") != CURSOR_VERSION or not isinstance(data.get("i"), str):
            raise ValueError
        group = int(data["g"])
        if group not in range(4):
            raise ValueError
        return (
            group, datetime.fromisoformat(data["a"]), datetime.fromisoformat(data["d"]),
            datetime.fromisoformat(data["c"]), data["i"],
        )
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, binascii.Error, UnicodeDecodeError):
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_feed_cursor", "message": "Malformed proposal feed cursor"},
        ) from None


def _after_cursor(cursor: tuple[int, datetime, datetime, datetime, str]):
    group, asc_key, desc_key, created_at, proposal_id = cursor
    g, a, d = _expressions()
    return or_(
        g > group,
        and_(g == group, a > asc_key),
        and_(g == group, a == asc_key, d < desc_key),
        and_(g == group, a == asc_key, d == desc_key, models.Proposal.created_at < created_at),
        and_(g == group, a == asc_key, d == desc_key,
             models.Proposal.created_at == created_at, models.Proposal.id > proposal_id),
    )


def member_visibility(db: Session, org: models.Organization, viewer: models.User, *, is_admin: bool):
    """SQL predicate applied before pagination for parent/sub-org visibility."""
    p = models.Proposal
    if org.parent_org_id is not None:
        scope = and_(p.org_id == org.parent_org_id, p.sub_org_id == org.id)
        if is_admin or not bool((org.settings or {}).get("private", False)):
            return scope
        is_sub_member = db.query(models.SubOrgMembership.id).filter(
            models.SubOrgMembership.sub_org_id == org.id,
            models.SubOrgMembership.user_id == viewer.id,
            models.SubOrgMembership.status == "active",
        ).exists()
        return and_(scope, is_sub_member)
    if is_admin:
        return p.org_id == org.id
    visible_sub_orgs = db.query(models.SubOrgMembership.sub_org_id).filter(
        models.SubOrgMembership.user_id == viewer.id,
        models.SubOrgMembership.status == "active",
    )
    non_private_sub_orgs = db.query(models.Organization.id).filter(
        models.Organization.parent_org_id == org.id,
        func.coalesce(models.Organization.settings["private"].as_boolean(), false()).is_(False),
    )
    return and_(
        p.org_id == org.id,
        or_(p.sub_org_id.is_(None), p.sub_org_id.in_(visible_sub_orgs), p.sub_org_id.in_(non_private_sub_orgs)),
    )


def global_visibility(db: Session, viewer: models.User):
    p = models.Proposal
    if viewer.is_admin:
        return true()
    parent_orgs = db.query(models.OrgMembership.org_id).filter(
        models.OrgMembership.user_id == viewer.id,
        models.OrgMembership.status == "active",
    )
    sub_orgs = db.query(models.SubOrgMembership.sub_org_id).filter(
        models.SubOrgMembership.user_id == viewer.id,
        models.SubOrgMembership.status == "active",
    )
    # Public/non-private sub-org proposals are viewable by every active parent
    # member. Private sub-org proposals additionally require sub membership.
    non_private_sub_orgs = db.query(models.Organization.id).filter(
        models.Organization.parent_org_id.in_(parent_orgs),
        func.coalesce(models.Organization.settings["private"].as_boolean(), false()).is_(False),
    )
    return or_(
        p.org_id.is_(None),
        and_(p.org_id.in_(parent_orgs), p.sub_org_id.is_(None)),
        p.sub_org_id.in_(sub_orgs),
        p.sub_org_id.in_(non_private_sub_orgs),
    )


def _apply_filters(query, *, status: str, topic_id: Optional[str]):
    p = models.Proposal
    if status == "all":
        query = query.filter(p.status != "withdrawn")
    elif status == "archived":
        query = query.filter(p.status == "withdrawn")
    elif status != "unvoted":
        query = query.filter(p.status == status)
    else:
        query = query.filter(p.status == "voting")
    if topic_id:
        query = query.filter(p.proposal_topics.any(models.ProposalTopic.topic_id == topic_id))
    return query


def _base_query(db: Session):
    return db.query(models.Proposal).options(
        joinedload(models.Proposal.organization),
        joinedload(models.Proposal.author).selectinload(models.User.org_memberships),
        selectinload(models.Proposal.proposal_topics).joinedload(models.ProposalTopic.topic),
        selectinload(models.Proposal.options),
    )


@dataclass
class BatchViewerResolver:
    db: Session
    proposals: list[models.Proposal]
    viewer: models.User

    def resolve(self) -> dict[str, object]:
        if not self.proposals:
            return {}
        proposal_ids = [p.id for p in self.proposals]
        org_ids = {p.org_id for p in self.proposals if p.org_id}
        sub_ids = {p.sub_org_id for p in self.proposals if p.sub_org_id}
        organizations = {
            row.id: row for row in self.db.query(models.Organization).filter(
                models.Organization.id.in_(org_ids | sub_ids)
            ).all()
        }
        parent_members: dict[str, set[str]] = {oid: set() for oid in org_ids}
        if org_ids:
            for oid, uid in self.db.query(models.OrgMembership.org_id, models.OrgMembership.user_id).filter(
                models.OrgMembership.org_id.in_(org_ids), models.OrgMembership.status == "active"
            ).all():
                parent_members.setdefault(oid, set()).add(uid)
        sub_members: dict[str, set[str]] = {sid: set() for sid in sub_ids}
        if sub_ids:
            for sid, uid in self.db.query(models.SubOrgMembership.sub_org_id, models.SubOrgMembership.user_id).filter(
                models.SubOrgMembership.sub_org_id.in_(sub_ids), models.SubOrgMembership.status == "active"
            ).all():
                sub_members.setdefault(sid, set()).add(uid)
        eligible_union = set().union(*parent_members.values(), *sub_members.values(), {self.viewer.id})
        users = {
            u.id: u for u in self.db.query(models.User).filter(models.User.id.in_(eligible_union)).all()
        } if eligible_union else {self.viewer.id: self.viewer}

        delegations: dict[str, dict[str, dict[Optional[str], DelegationData]]] = {}
        if org_ids:
            for row in self.db.query(models.Delegation).filter(models.Delegation.org_id.in_(org_ids)).all():
                delegations.setdefault(row.org_id, {}).setdefault(row.delegator_id, {})[row.topic_id] = DelegationData(
                    row.delegator_id, row.delegate_id, row.topic_id, row.chain_behavior,
                )
        precedences: dict[str, dict[str, int]] = {}
        if eligible_union:
            for uid, tid, priority in self.db.query(
                models.TopicPrecedence.user_id, models.TopicPrecedence.topic_id, models.TopicPrecedence.priority,
            ).filter(models.TopicPrecedence.user_id.in_(eligible_union)).all():
                precedences.setdefault(uid, {})[tid] = priority
        votes_by_proposal: dict[str, list[models.Vote]] = {}
        for vote in self.db.query(models.Vote).filter(
            models.Vote.proposal_id.in_(proposal_ids), models.Vote.is_direct.is_(True),
        ).all():
            votes_by_proposal.setdefault(vote.proposal_id, []).append(vote)

        results: dict[str, object] = {}
        from verification import effective_proposal_floor, user_satisfies_floor
        for proposal in self.proposals:
            eligible = set(sub_members.get(proposal.sub_org_id, ())) if proposal.sub_org_id else set(
                parent_members.get(proposal.org_id, ())
            )
            org = organizations.get(proposal.org_id)
            floor, jurisdiction = effective_proposal_floor(proposal, org)
            if floor:
                from verification import delegation_carries_unverified_weight
                if not (org and delegation_carries_unverified_weight(org)):
                    eligible = {uid for uid in eligible if uid in users and user_satisfies_floor(users[uid], floor, jurisdiction)}
            if self.viewer.id not in eligible:
                results[proposal.id] = None
                continue
            topic_ids = [pt.topic_id for pt in proposal.proposal_topics]
            topic_models = [pt.topic for pt in proposal.proposal_topics]
            gated = proposal_is_delegation_gated(proposal, org, topic_models)
            direct_votes: dict[str, str] = {}
            direct_ballots: dict[str, Ballot] = {}
            for row in votes_by_proposal.get(proposal.id, ()):
                if row.user_id not in eligible:
                    continue
                ballot = row.ballot or {}
                if proposal.voting_method == "approval":
                    direct_ballots[row.user_id] = Ballot(approvals=ballot.get("approvals", []))
                elif proposal.voting_method == "ranked_choice":
                    direct_ballots[row.user_id] = Ballot(ranking=ballot.get("ranking", []))
                elif proposal.voting_method == "budget_allocation":
                    direct_ballots[row.user_id] = Ballot(allocations=ballot.get("allocations", {}))
                elif proposal.voting_method == "budget_project":
                    direct_ballots[row.user_id] = Ballot(project_ranked=[
                        (item.get("option_id"), item.get("tier_id"))
                        for item in (ballot.get("ranked") or [])
                        if isinstance(item, dict) and item.get("option_id")
                    ])
                elif row.vote_value is not None:
                    direct_votes[row.user_id] = row.vote_value
            ctx = ProposalContext(
                proposal_topics=topic_ids,
                all_delegations={} if gated else delegations.get(proposal.org_id, {}),
                all_precedences={} if gated else precedences,
                direct_votes=direct_votes,
                direct_ballots=direct_ballots,
                voting_method=proposal.voting_method or "binary",
                proposal_topic_relevances={pt.topic_id: float(pt.relevance or 1.0) for pt in proposal.proposal_topics},
                user_strategies={uid: (u.delegation_strategy or "strict_precedence") for uid, u in users.items()},
            )
            results[proposal.id] = resolve_vote_pure(self.viewer.id, ctx)
        return results


def _viewer_out(result, users: dict[str, models.User], proposal: models.Proposal) -> schemas.ProposalFeedViewerVoteOut:
    if result is None:
        return schemas.ProposalFeedViewerVoteOut(has_effective_vote=False)
    selection_count = None
    ballot = result.ballot
    if ballot.approvals is not None:
        selection_count = len(ballot.approvals)
    elif ballot.ranking is not None:
        selection_count = len(ballot.ranking)
    elif ballot.allocations is not None:
        selection_count = len(ballot.allocations)
    elif ballot.project_ranked is not None:
        selection_count = len(ballot.project_ranked)
    cast_by = users.get(result.cast_by_id)
    from verification import display_name_for
    return schemas.ProposalFeedViewerVoteOut(
        has_effective_vote=True,
        is_direct=result.is_direct,
        binary_value=result.vote_value,
        selection_count=selection_count,
        cast_by_display_name=(display_name_for(cast_by, proposal.organization) if cast_by else None),
    )


def _serialize(proposal: models.Proposal, viewer_result, users: dict[str, models.User], *, public: bool):
    from verification import display_name_for
    return schemas.ProposalFeedItemOut(
        proposal=schemas.ProposalFeedProposalOut(
            id=proposal.id,
            title=proposal.title,
            author=schemas.ProposalFeedAuthorOut(
                id=proposal.author.id,
                display_name=display_name_for(proposal.author, proposal.organization),
            ),
            status=proposal.status,
            voting_method=proposal.voting_method or "binary",
            count_mode=proposal.count_mode,
            stable_result_required=proposal.stable_result_required,
            sub_org_id=proposal.sub_org_id,
            topics=[schemas.ProposalTopicOut.model_validate(pt) for pt in proposal.proposal_topics],
            created_at=proposal.created_at,
            voting_start=proposal.voting_start,
            voting_end=proposal.voting_end,
            is_election=bool(proposal.is_election),
            option_count=len(proposal.options),
        ),
        viewer_vote=None if public else _viewer_out(viewer_result, users, proposal),
    )


def build_feed(
    db: Session, *, visibility, status: str = "all", topic_id: Optional[str] = None,
    cursor: Optional[str] = None, limit: int = 25, viewer: Optional[models.User] = None,
    public: bool = False,
) -> schemas.ProposalFeedOut:
    status = validate_status(status)
    if public and status == "unvoted":
        raise HTTPException(status_code=422, detail={"code": "viewer_filter_not_public"})
    query = _apply_filters(_base_query(db).filter(visibility), status=status, topic_id=topic_id)

    # Unvoted is an effective-ballot filter, so resolve the bounded eligible
    # voting set before applying page boundaries.  No per-proposal route or DB
    # context builder is called; the batch resolver issues fixed-set queries.
    precomputed = None
    if status == "unvoted":
        candidates = query.order_by(*_ordering()).all()
        precomputed = BatchViewerResolver(db, candidates, viewer).resolve()
        unvoted_ids = [p.id for p in candidates if precomputed.get(p.id) is None]
        if not unvoted_ids:
            return schemas.ProposalFeedOut(items=[], next_cursor=None, has_more=False)
        query = _apply_filters(_base_query(db).filter(visibility), status="voting", topic_id=topic_id).filter(
            models.Proposal.id.in_(unvoted_ids)
        )

    if cursor:
        query = query.filter(_after_cursor(decode_cursor(cursor)))
    rows = query.order_by(*_ordering()).limit(limit + 1).all()
    has_more = len(rows) > limit
    page = rows[:limit]
    if viewer is not None:
        page_results = BatchViewerResolver(db, page, viewer).resolve()
    else:
        page_results = {}
    user_ids = {r.cast_by_id for r in page_results.values() if r is not None}
    users = {
        u.id: u for u in db.query(models.User).options(
            selectinload(models.User.org_memberships)
        ).filter(models.User.id.in_(user_ids)).all()
    } if user_ids else {}
    return schemas.ProposalFeedOut(
        items=[_serialize(p, page_results.get(p.id), users, public=public) for p in page],
        next_cursor=encode_cursor(page[-1]) if has_more and page else None,
        has_more=has_more,
    )


def _ordering():
    group, asc_key, desc_key = _expressions()
    return (
        group.asc(), asc_key.asc(), desc_key.desc(),
        models.Proposal.created_at.desc(), models.Proposal.id.asc(),
    )
