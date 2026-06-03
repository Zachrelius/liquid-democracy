import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

import auth as auth_utils
import models
import schemas
from audit_utils import log_audit_event
from database import get_db
from delegation_engine import engine as delegation_engine, eligible_voter_ids_for_proposal
from notification_emit import emit_notification, should_emit_with_dedup
from permissions import can_view_vote_rationale
from websocket import manager as ws_manager


log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/proposals", tags=["votes"])

# Phase 19 (B6) — vote rationale CRUD lives on a separate APIRouter so the
# URL prefix can be ``/api/votes/{vote_id}/rationale`` (the spec's chosen
# shape) without colliding with the proposal-prefixed routes above.
rationale_router = APIRouter(prefix="/api/votes", tags=["vote-rationale"])


def _proposal_or_404(proposal_id: str, db: Session) -> models.Proposal:
    p = db.get(models.Proposal, proposal_id)
    if not p:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return p


def _require_voting_open(
    proposal: models.Proposal, db: Optional["Session"] = None,
) -> None:
    """Phase 32 P1 — accept ``deliberation`` status too when the proposal
    has pre-voting enabled (org default OR per-proposal override).

    Default behavior unchanged for proposals with ``allow_pre_voting``
    null/False: vote-casting still requires status="voting".
    """
    if proposal.status == "voting":
        return
    if proposal.status == "deliberation":
        from proposal_engagement_config import resolve_allow_pre_voting
        org = None
        if db is not None and proposal.org_id is not None:
            org = db.get(models.Organization, proposal.org_id)
        if resolve_allow_pre_voting(proposal, org):
            return
        raise HTTPException(
            status_code=400,
            detail=(
                "Voting is not open yet — pre-voting during deliberation "
                "is not enabled for this proposal"
            ),
        )
    raise HTTPException(
        status_code=400, detail="Proposal is not in voting phase",
    )


def _delegators_for_proposal(
    db: Session, proposal: models.Proposal, delegate_user_id: str,
) -> set[str]:
    """Phase 21 — return the set of delegator user IDs whose delegation to
    ``delegate_user_id`` covers this ``proposal``.

    Codebase has no ``Proposal.primary_topic_id`` — proposals carry many
    topics via ``ProposalTopic`` (M2M). The spec's "primary topic" wording
    maps to "any of the proposal's topics." A ``Delegation`` row with
    ``topic_id IS NULL`` is an org-wide global delegation and also
    qualifies.

    Org-scoping uses ``proposal.org_id`` per Phase 18 retrofit. Excludes
    ``delegate_user_id`` itself per D14 (never self-notify).
    """
    topic_ids = [pt.topic_id for pt in proposal.proposal_topics]
    q = db.query(models.Delegation).filter(
        models.Delegation.delegate_id == delegate_user_id,
        models.Delegation.org_id == proposal.org_id,
    )
    if topic_ids:
        q = q.filter(
            or_(
                models.Delegation.topic_id.is_(None),
                models.Delegation.topic_id.in_(topic_ids),
            )
        )
    else:
        # Proposal has no topics; only org-wide global delegations
        # (topic_id IS NULL) qualify.
        q = q.filter(models.Delegation.topic_id.is_(None))
    delegations = q.all()
    return {d.delegator_id for d in delegations if d.delegator_id != delegate_user_id}


def _format_vote_value_for_payload(
    vote_value: object, ballot: object, voting_method: str,
):
    """Phase 21 — produce the payload's ``vote_value`` per D12.

    Binary: string ("yes"/"no"/"abstain"). Approval: list of option_ids.
    RCV: ordered list of option_ids.
    """
    if voting_method == "binary":
        return vote_value
    if voting_method == "approval":
        if isinstance(ballot, dict):
            return list(ballot.get("approvals") or [])
        return []
    if voting_method == "ranked_choice":
        if isinstance(ballot, dict):
            return list(ballot.get("ranking") or [])
        return []
    return vote_value


@router.post("/{proposal_id}/vote", response_model=schemas.VoteOut, status_code=status.HTTP_200_OK)
async def cast_vote(
    proposal_id: str,
    body: schemas.VoteCast,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    proposal = _proposal_or_404(proposal_id, db)
    _require_voting_open(proposal, db)

    if not current_user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email before voting.",
        )

    # Phase 52 Stage 1 — verification per-vote floor gate. If the
    # proposal carries ``verification_floor``, the caller must
    # satisfy it to cast a *direct* vote. Runs BEFORE the org-
    # membership eligibility check so an org-member who fails
    # verification gets the structured "verification_required"
    # detail rather than the generic "not eligible" string (the
    # eligibility helper also narrows by verification floor for
    # gated proposals — Cluster C4 — so they'd be filtered out of
    # the eligible set too; this check ensures the FE renders the
    # right CTA). No-op when the proposal has no gate.
    from verification import check_vote_floor_for_proposal
    check_vote_floor_for_proposal(current_user, proposal)

    # Phase 10.1: eligibility check. Pre-fix, parent-org members could vote on
    # sub-org proposals they weren't members of, and cross-org users could
    # vote on any proposal whose ID they knew. The new gate uses the same
    # eligible_voter_ids_for_proposal helper that compute_tally and
    # get_vote_graph use, so the three call sites stay in lockstep.
    eligible_ids = eligible_voter_ids_for_proposal(db, proposal)
    if current_user.id not in eligible_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not eligible to vote on this proposal.",
        )

    # -- Method-specific validation --
    if proposal.voting_method == "binary":
        if body.approvals is not None or body.ranking is not None:
            raise HTTPException(status_code=400, detail="Use vote_value for binary proposals")
        if body.vote_value is None:
            raise HTTPException(status_code=400, detail="vote_value is required for binary proposals")
        vote_value = body.vote_value
        ballot = None
    elif proposal.voting_method == "approval":
        if body.vote_value is not None or body.ranking is not None:
            raise HTTPException(status_code=400, detail="Use approvals for approval proposals")
        if body.approvals is None:
            raise HTTPException(status_code=400, detail="approvals is required for approval proposals")
        # Validate option IDs belong to this proposal
        valid_option_ids = {opt.id for opt in proposal.options}
        for oid in body.approvals:
            if oid not in valid_option_ids:
                raise HTTPException(status_code=400, detail=f"Option {oid} does not belong to this proposal")
        vote_value = None
        ballot = {"approvals": body.approvals}
    elif proposal.voting_method == "ranked_choice":
        if body.vote_value is not None or body.approvals is not None:
            raise HTTPException(status_code=400, detail="Use ranking for ranked-choice proposals")
        if body.ranking is None:
            raise HTTPException(status_code=400, detail="ranking is required for ranked-choice proposals")
        valid_option_ids = {opt.id for opt in proposal.options}
        if len(body.ranking) > len(valid_option_ids):
            raise HTTPException(
                status_code=400,
                detail="Ranking length exceeds proposal option count",
            )
        for oid in body.ranking:
            if oid not in valid_option_ids:
                raise HTTPException(status_code=400, detail=f"Option {oid} does not belong to this proposal")
        vote_value = None
        ballot = {"ranking": body.ranking}
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported voting method: {proposal.voting_method}")

    existing = (
        db.query(models.Vote)
        .filter(
            models.Vote.proposal_id == proposal_id,
            models.Vote.user_id == current_user.id,
        )
        .first()
    )

    ip = request.client.host if request.client else None

    # Phase 21 — capture pre-update state for delegate.vote_changed payload.
    is_change = existing is not None
    pre_update_vote_value = existing.vote_value if existing else None
    pre_update_ballot = existing.ballot if existing else None

    if existing:
        previous_value = existing.vote_value
        previous_ballot = existing.ballot
        existing.vote_value = vote_value
        existing.ballot = ballot
        existing.is_direct = True
        existing.delegate_chain = None
        existing.cast_by_id = current_user.id
        db.flush()
        log_audit_event(
            db,
            action="vote.cast",
            target_type="vote",
            target_id=existing.id,
            actor_id=current_user.id,
            details={
                "proposal_id": proposal_id,
                "vote_value": vote_value,
                "ballot": ballot,
                "is_direct": True,
                "previous_value": previous_value,
                "delegate_chain": None,
            },
            ip_address=ip,
        )
        db.commit()
        db.refresh(existing)
        vote = existing
    else:
        vote = models.Vote(
            proposal_id=proposal_id,
            user_id=current_user.id,
            vote_value=vote_value,
            ballot=ballot,
            is_direct=True,
            delegate_chain=None,
            cast_by_id=current_user.id,
        )
        db.add(vote)
        db.flush()
        log_audit_event(
            db,
            action="vote.cast",
            target_type="vote",
            target_id=vote.id,
            actor_id=current_user.id,
            details={
                "proposal_id": proposal_id,
                "vote_value": vote_value,
                "ballot": ballot,
                "is_direct": True,
                "previous_value": None,
                "delegate_chain": None,
            },
            ip_address=ip,
        )
        db.commit()
        db.refresh(vote)

    # Broadcast updated tally via WebSocket
    tally = delegation_engine.compute_tally(proposal, db)
    await ws_manager.broadcast_tally(proposal_id, tally)

    # Phase 21 (D2/D3/D14/D15) — fire delegate.voted (initial cast) or
    # delegate.vote_changed (subsequent updates) to the delegators of
    # ``current_user`` on this proposal. Dedup via should_emit_with_dedup
    # so a flurry of vote changes within 1h produces at most one
    # notification per delegator. Wrapped in try/except per D15 so a
    # notification failure never rolls back the vote write.
    try:
        delegator_ids = _delegators_for_proposal(db, proposal, current_user.id)
        if delegator_ids:
            actor_display = current_user.display_name or current_user.username
            now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
            cast_at_iso = (vote.cast_at or now_naive).isoformat() if hasattr(vote, "cast_at") else now_naive.isoformat()
            updated_at_iso = (vote.updated_at or now_naive).isoformat() if hasattr(vote, "updated_at") else now_naive.isoformat()
            vote_value_payload = _format_vote_value_for_payload(
                vote.vote_value, vote.ballot, proposal.voting_method,
            )
            if is_change:
                event_type = "delegate.vote_changed"
                previous_value_payload = _format_vote_value_for_payload(
                    pre_update_vote_value, pre_update_ballot, proposal.voting_method,
                )
                payload_base = {
                    "proposal_id": proposal.id,
                    "proposal_title": proposal.title,
                    "delegate_user_id": current_user.id,
                    "delegate_display_name": actor_display,
                    "vote_value": vote_value_payload,
                    "previous_vote_value": previous_value_payload,
                    "cast_at": cast_at_iso,
                    "changed_at": updated_at_iso,
                }
            else:
                event_type = "delegate.voted"
                payload_base = {
                    "proposal_id": proposal.id,
                    "proposal_title": proposal.title,
                    "delegate_user_id": current_user.id,
                    "delegate_display_name": actor_display,
                    "vote_value": vote_value_payload,
                    "cast_at": cast_at_iso,
                }

            emitted_any = False
            for delegator_id in delegator_ids:
                if not should_emit_with_dedup(db, delegator_id, event_type, proposal.id):
                    continue
                emit_notification(
                    db,
                    background_tasks,
                    event_type=event_type,
                    user_id=delegator_id,
                    org_id=proposal.org_id,
                    actor_id=current_user.id,
                    target_type="proposal",
                    target_id=proposal.id,
                    payload=dict(payload_base),
                )
                emitted_any = True
            if emitted_any:
                db.commit()
    except Exception as e:  # noqa: BLE001 — D15: vote write must not roll back
        log.warning(
            "vote notification emit failed (event=%s proposal=%s actor=%s): %s: %s",
            "delegate.vote_changed" if is_change else "delegate.voted",
            proposal_id, current_user.id, type(e).__name__, e,
        )
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass

    return vote


@router.delete("/{proposal_id}/vote", status_code=status.HTTP_204_NO_CONTENT)
async def retract_vote(
    proposal_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    proposal = _proposal_or_404(proposal_id, db)
    _require_voting_open(proposal, db)

    # Phase 10.1: same eligibility gate as cast_vote — a non-eligible user
    # shouldn't be able to retract a vote they shouldn't have been able to
    # cast. See cast_vote for the bug history.
    eligible_ids = eligible_voter_ids_for_proposal(db, proposal)
    if current_user.id not in eligible_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not eligible to vote on this proposal.",
        )

    vote = (
        db.query(models.Vote)
        .filter(
            models.Vote.proposal_id == proposal_id,
            models.Vote.user_id == current_user.id,
            models.Vote.is_direct.is_(True),
        )
        .first()
    )
    if not vote:
        raise HTTPException(status_code=404, detail="No direct vote to retract")

    previous_value = vote.vote_value
    vote_id = vote.id

    log_audit_event(
        db,
        action="vote.retracted",
        target_type="vote",
        target_id=vote_id,
        actor_id=current_user.id,
        details={"proposal_id": proposal_id, "previous_value": previous_value},
        ip_address=request.client.host if request.client else None,
    )
    db.delete(vote)
    db.commit()

    tally = delegation_engine.compute_tally(proposal, db)
    await ws_manager.broadcast_tally(proposal_id, tally)


# ---------------------------------------------------------------------------
# Phase 19 (B6) — Vote rationale CRUD
# ---------------------------------------------------------------------------
#
# All three endpoints operate on the optional one-to-one
# ``DelegateVoteRationale`` row attached to a ``Vote``. The vote-owner
# bypass for visibility lives in ``can_view_vote_rationale`` (centralized
# in ``permissions.py`` per spec line 326). Write endpoints are vote-
# owner-only and validate non-empty content via the schema.


def _vote_or_404(db: Session, vote_id: str) -> models.Vote:
    vote = db.get(models.Vote, vote_id)
    if vote is None:
        raise HTTPException(status_code=404, detail="Vote not found")
    return vote


@rationale_router.get(
    "/{vote_id}/rationale",
    response_model=schemas.DelegateVoteRationaleOut,
)
def get_vote_rationale(
    vote_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Return the rationale for ``vote_id`` if the caller has visibility.

    Visibility is gated by ``can_view_vote_rationale`` — vote owner
    always; others only when (a) the proposal's primary topic is in
    non-private state for the vote owner AND (b) viewer has access to
    the org. 404 (not 403) when visibility is denied to avoid leaking
    rationale existence to unauthorized callers.
    """
    vote = _vote_or_404(db, vote_id)
    if not can_view_vote_rationale(current_user, vote, db):
        raise HTTPException(status_code=404, detail="Rationale not found")

    rationale = (
        db.query(models.DelegateVoteRationale)
        .filter(models.DelegateVoteRationale.vote_id == vote_id)
        .first()
    )
    if rationale is None:
        raise HTTPException(status_code=404, detail="Rationale not found")
    return rationale


@rationale_router.put(
    "/{vote_id}/rationale",
    response_model=schemas.DelegateVoteRationaleOut,
)
def upsert_vote_rationale(
    vote_id: str,
    body: schemas.DelegateVoteRationaleUpsert,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Vote-owner-only — create or update the rationale on this vote.
    Markdown sanitization happens at render time (matches comment
    behavior per spec §B6) — content stored verbatim.
    """
    vote = _vote_or_404(db, vote_id)
    if vote.user_id != current_user.id:
        # 404 not 403: treat the rationale as if it doesn't exist for
        # non-owners so the surface doesn't leak which votes have
        # rationale via 403-vs-404 timing differences.
        raise HTTPException(status_code=404, detail="Vote not found")

    rationale = (
        db.query(models.DelegateVoteRationale)
        .filter(models.DelegateVoteRationale.vote_id == vote_id)
        .first()
    )
    ip = request.client.host if request.client else None
    is_create = rationale is None

    if rationale is None:
        rationale = models.DelegateVoteRationale(
            vote_id=vote_id,
            content=body.content,
        )
        db.add(rationale)
        db.flush()
        log_audit_event(
            db,
            action="delegate_vote_rationale.created",
            target_type="delegate_vote_rationale",
            target_id=rationale.id,
            actor_id=current_user.id,
            details={
                "vote_id": vote_id,
                "proposal_id": vote.proposal_id,
            },
            ip_address=ip,
        )
    else:
        rationale.content = body.content
        db.flush()
        log_audit_event(
            db,
            action="delegate_vote_rationale.updated",
            target_type="delegate_vote_rationale",
            target_id=rationale.id,
            actor_id=current_user.id,
            details={
                "vote_id": vote_id,
                "proposal_id": vote.proposal_id,
            },
            ip_address=ip,
        )

    db.commit()
    db.refresh(rationale)

    # Phase 21 (D4) — emit ``delegate.posted_rationale`` to delegators when
    # the rationale is freshly created AND the vote-owner has at least one
    # DelegateProfile (matching one of the proposal's topics + the
    # proposal's org) in ``public`` or ``public_accepting`` visibility.
    # No emission on update (per spec — initial post is the load-bearing
    # signal). Wrapped in try/except per D15.
    if is_create:
        try:
            proposal = db.get(models.Proposal, vote.proposal_id)
            if proposal is not None:
                topic_ids = [pt.topic_id for pt in proposal.proposal_topics]
                qualifying_profile = None
                if topic_ids:
                    qualifying_profile = (
                        db.query(models.DelegateProfile)
                        .filter(
                            models.DelegateProfile.user_id == current_user.id,
                            models.DelegateProfile.topic_id.in_(topic_ids),
                            models.DelegateProfile.org_id == proposal.org_id,
                            models.DelegateProfile.visibility.in_(
                                ("public", "public_accepting")
                            ),
                        )
                        .first()
                    )
                if qualifying_profile is not None:
                    delegator_ids = _delegators_for_proposal(
                        db, proposal, current_user.id,
                    )
                    if delegator_ids:
                        actor_display = current_user.display_name or current_user.username
                        excerpt = (body.content or "")[:150]
                        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
                        posted_at_iso = (
                            rationale.created_at.isoformat()
                            if getattr(rationale, "created_at", None)
                            else now_naive.isoformat()
                        )
                        payload_base = {
                            "proposal_id": proposal.id,
                            "proposal_title": proposal.title,
                            "delegate_user_id": current_user.id,
                            "delegate_display_name": actor_display,
                            "rationale_excerpt": excerpt,
                            "posted_at": posted_at_iso,
                        }
                        emitted_any = False
                        for delegator_id in delegator_ids:
                            if not should_emit_with_dedup(
                                db, delegator_id, "delegate.posted_rationale",
                                proposal.id,
                            ):
                                continue
                            emit_notification(
                                db,
                                background_tasks,
                                event_type="delegate.posted_rationale",
                                user_id=delegator_id,
                                org_id=proposal.org_id,
                                actor_id=current_user.id,
                                target_type="proposal",
                                target_id=proposal.id,
                                payload=dict(payload_base),
                            )
                            emitted_any = True
                        if emitted_any:
                            db.commit()
        except Exception as e:  # noqa: BLE001 — D15: rationale write must not roll back
            log.warning(
                "rationale notification emit failed (vote=%s actor=%s): %s: %s",
                vote_id, current_user.id, type(e).__name__, e,
            )
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass

    return rationale


@rationale_router.delete(
    "/{vote_id}/rationale",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_vote_rationale(
    vote_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Vote-owner-only — remove the rationale row on this vote. Returns
    explicit ``Response(status_code=204)`` per Phase 18.5 lesson (FastAPI
    implicit-None-on-204 quirk causes Cloudflare 503).
    """
    vote = _vote_or_404(db, vote_id)
    if vote.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Vote not found")

    rationale = (
        db.query(models.DelegateVoteRationale)
        .filter(models.DelegateVoteRationale.vote_id == vote_id)
        .first()
    )
    if rationale is None:
        raise HTTPException(status_code=404, detail="Rationale not found")

    rationale_id = rationale.id
    log_audit_event(
        db,
        action="delegate_vote_rationale.deleted",
        target_type="delegate_vote_rationale",
        target_id=rationale_id,
        actor_id=current_user.id,
        details={
            "vote_id": vote_id,
            "proposal_id": vote.proposal_id,
        },
        ip_address=request.client.host if request.client else None,
    )
    db.delete(rationale)
    db.commit()
    # Phase 18.5 B2 — explicit Response so the 204 doesn't carry a
    # ``content-type: application/json`` header that Cloudflare/Railway's
    # edge proxy rejects with a 503.
    return Response(status_code=204)
