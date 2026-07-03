import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import case
from sqlalchemy.orm import Session

import auth as auth_utils
import models
import schemas
from audit_utils import log_audit_event
from database import get_db
from delegation_engine import (
    engine as delegation_engine,
    resolve_vote_pure,
    ApprovalTally,
    RCVTally,
    eligible_voter_ids_for_proposal,
)
from notification_emit import emit_notification, user_has_any_channel_enabled
from org_config import (
    get_default_proposal_durations,
    get_default_proposal_thresholds,
    get_org_config,
)
from eligibility import eligible_viewers_for_proposal as _eligible_viewers_for_proposal
from permissions import can_see_votes
from polis_engine import eligible_viewers_for_polis
from role_permissions import has_permission as _has_permission
from rate_limit_utils import content_limiter, PROPOSAL_CREATE_LIMIT, WRITEIN_OPTION_LIMIT


log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/proposals", tags=["proposals"])

STATUS_TRANSITIONS = {
    "draft": "deliberation",
    "deliberation": "voting",
    "voting": "passed",  # actual pass/fail determined at close; admin forces
}


def _strip_tz(dt: Optional[datetime]) -> Optional[datetime]:
    """Phase 75a — normalize an optional datetime to naive UTC (the platform's
    storage convention). NULL passes through."""
    if dt is not None and dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


def _compute_voting_end_at_advance(
    *,
    voting_start: datetime,
    body_voting_end: Optional[datetime],
    proposal: models.Proposal,
    org: Optional[models.Organization],
) -> datetime:
    """Phase 25 B1.1 — derive ``voting_end`` at the deliberation → voting
    transition.

    Precedence:
      1. ``body_voting_end`` — admin client explicitly setting a custom end.
         Logs a deprecation warning so stale callers surface in logs over
         time; future callers should PATCH ``voting_days`` instead.
      2. ``proposal.voting_days`` — Phase 16 per-proposal override stored
         on the row at create time.
      3. Org default ``default_voting_days`` via ``get_default_proposal_durations``.

    Raises ``HTTPException(400)`` if all three are unavailable or the
    resolved value is <= 0 (org configuration error — would create a
    proposal that closes immediately or never closes).

    Fractional days are honored: ``voting_days=0.05`` produces ~72 minutes
    via ``timedelta(days=0.05)``.
    """
    if body_voting_end is not None:
        log.warning(
            "advance_proposal: body.voting_end is deprecated; "
            "set proposal.voting_days at create or via PATCH instead "
            "(proposal_id=%s)",
            proposal.id,
        )
        if body_voting_end.tzinfo is not None:
            return body_voting_end.replace(tzinfo=None)
        return body_voting_end

    # Phase 75a — absolute voting end date takes priority over voting_days
    # (and the org default). When set and valid, it becomes voting_end
    # directly. The real staleness check is here at advance time (not at
    # create), mirroring how voting_days has no create-time "enough time?"
    # check — a proposal may sit in draft for days.
    end_date = getattr(proposal, "voting_end_date", None)
    if end_date is not None:
        if end_date.tzinfo is not None:
            end_date = end_date.replace(tzinfo=None)
        if end_date <= voting_start:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"The specified voting end date "
                    f"({end_date.strftime('%Y-%m-%d %H:%M')}) has already "
                    "passed or is before voting would start. Update it or "
                    "remove it to use the default voting duration."
                ),
            )
        derived_days = (end_date - voting_start).total_seconds() / 86400
        if derived_days < _VOTING_DAYS_FLOOR:
            raise HTTPException(
                status_code=400,
                detail=(
                    "The specified voting end date is too soon — the voting "
                    f"window would be {derived_days:.2f} days, below the "
                    f"minimum of {_VOTING_DAYS_FLOOR} days (~72 minutes)."
                ),
            )
        return end_date

    voting_days: Optional[float] = getattr(proposal, "voting_days", None)
    if voting_days is None:
        _, default_vote = get_default_proposal_durations(org)
        voting_days = default_vote

    if voting_days is None or voting_days <= 0:
        raise HTTPException(
            status_code=400,
            detail=(
                "Cannot advance to voting: proposal has no voting_days and "
                "the organization has no positive default_voting_days. "
                "Set proposal.voting_days or fix the org configuration."
            ),
        )

    return voting_start + timedelta(days=float(voting_days))


def _viewer_can_advance_permission(
    proposal: models.Proposal,
    db: Session,
    viewer_id: Optional[str],
    *,
    user: Optional[models.User] = None,
) -> bool:
    """Phase 70 — THE advance permission ladder (ignoring next-status).

    Single source of truth shared by ``advance_proposal`` (the endpoint
    gate) and ``_viewer_can_advance`` (which adds the next-status check
    to drive ``ProposalOut.can_advance``). Keeping the ladder in one
    place means the FE control and the endpoint can never diverge.

    True iff the viewer is:
      * the proposal author, OR
      * a platform admin, OR
      * a holder of ``proposal.advance_phase`` in the proposal's org.

    A moderator who is NOT the author is deliberately NOT in this set —
    they need ``proposal.advance_phase`` (mirrors the endpoint, which
    403s a moderator on someone else's proposal). ``user`` may be passed
    to avoid a redundant User load when the caller already has it.

    Phase 71a PF-2 — RUNG-LIMITED author branch. Platform admins and
    ``proposal.advance_phase`` holders may advance at ANY rung (including
    the ``voting→passed`` force-close). The proposal AUTHOR, by identity
    alone, may self-advance ONLY on the author-advanceable rungs
    (``draft→deliberation``, ``deliberation→voting``) — they may NOT
    force-close their own voting phase. Closing voting is governed by
    ``proposal.advance_phase`` (or platform-admin) even for the author.
    This closes the §69 PF-2 API-only bypass; the FE already hid the
    voting-rung advance via ``can_advance`` (``_viewer_can_advance``).
    """
    if viewer_id is None:
        return False
    # Admin + key holders advance at any rung (incl. voting→passed).
    u = user if user is not None else db.get(models.User, viewer_id)
    if u is not None and u.is_admin:
        return True
    if proposal.org_id is not None and _has_permission(
        db, viewer_id, proposal.org_id, "proposal.advance_phase",
    ):
        return True
    # Author identity suffices only on the author-advanceable rungs.
    if (
        proposal.author_id == viewer_id
        and proposal.status in _AUTHOR_ADVANCEABLE_STATUSES
    ):
        return True
    return False


# Phase 70 — statuses the proposal-detail "Advance" control may act on.
# Deliberately EXCLUDES "voting": ``STATUS_TRANSITIONS`` maps voting→passed
# for the endpoint's admin force-close path, but that's "close voting early"
# (an admin action surfaced in the admin view), NOT an author "advance to the
# next phase". The author control is only for draft→deliberation and
# deliberation→voting, so ``can_advance``/``next_status`` are gated to these.
_AUTHOR_ADVANCEABLE_STATUSES = ("draft", "deliberation")


def _author_next_status(proposal: models.Proposal) -> Optional[str]:
    """Phase 70 — the next status the author advance control would move to,
    or None when the proposal isn't at an author-advanceable rung."""
    if proposal.status in _AUTHOR_ADVANCEABLE_STATUSES:
        return STATUS_TRANSITIONS.get(proposal.status)
    return None


def _viewer_can_advance(
    proposal: models.Proposal,
    db: Session,
    viewer_id: Optional[str],
    *,
    user: Optional[models.User] = None,
) -> bool:
    """Phase 70 — full ``can_advance`` capability: the permission ladder
    AND an author-advanceable next status existing (True only for draft /
    deliberation; False for voting/passed/failed/withdrawn/unresolved).
    Drives the FE author advance control + ``ProposalOut.can_advance``.
    """
    return (
        _author_next_status(proposal) is not None
        and _viewer_can_advance_permission(proposal, db, viewer_id, user=user)
    )


def _proposal_or_404(proposal_id: str, db: Session) -> models.Proposal:
    p = db.get(models.Proposal, proposal_id)
    if not p:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return p


def _validate_linked_polis_ids(
    db: Session,
    ids: list[str],
    viewer_user_id: str,
    viewer_org_id: str,
) -> None:
    """Phase 9 Session 2: validate proposal->Polis links at create/update time.

    Each ID must:
      1. Exist in the `polises` table.
      2. Belong to the same parent org as the proposal (sub-org sub-scopes
         are handled at the route layer separately when sub_org_id is set
         on the proposal — for v1 we accept any same-org Polis the viewer
         can see, mirroring how URL-detection links work).
      3. Be `status='active'` (archived Polises cannot be newly linked;
         existing links stay because we only validate the diff on update).
      4. Have the viewer in `eligible_viewers_for_polis` (Decision 5/6/7).

    Raises HTTPException(400) on the FIRST failure encountered with a
    detail string the FE can render verbatim. We could batch all errors
    but a single-error-per-call shape is simpler and matches the topic-
    scope-validation pattern in routes/organizations.py.

    Lift of the helper from `tests/test_proposal_linked_polises.py` into
    the route module per Session 2 prerequisites.
    """
    for pid in ids:
        polis = db.query(models.Polis).filter(models.Polis.id == pid).first()
        if polis is None:
            raise HTTPException(
                status_code=400,
                detail=f"linked_polis_id {pid} does not exist",
            )
        if polis.org_id != viewer_org_id:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"linked_polis_id {pid} belongs to a different organization"
                ),
            )
        if polis.status != "active":
            raise HTTPException(
                status_code=400,
                detail=(
                    f"linked_polis_id {pid} is not active "
                    f"(status={polis.status})"
                ),
            )
        viewers = eligible_viewers_for_polis(db, polis)
        if viewer_user_id not in viewers:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"linked_polis_id {pid} is out of viewer scope; you "
                    "cannot link a Polis you cannot see."
                ),
            )


def _build_linked_polises(
    db: Session, proposal: models.Proposal,
) -> Optional[list[dict]]:
    """Resolve `linked_polis_ids` into rich objects for ProposalOut.

    Phase 9 spec (proposal detail GET): returns
    `[{id, title, prompt, status, participation_count}]` for each linked
    Polis. Uses fail-soft `polis_service.get_participation_stats` so a
    pol.is API outage doesn't 500 proposal detail.

    N+1 footnote: one stats fetch per linked Polis. v1 spec says "small
    number of linked Polises per proposal" — surfaced as a tech-debt
    note rather than over-engineered here.
    """
    ids = proposal.linked_polis_ids or []
    if not ids:
        return None
    out: list[dict] = []
    for pid in ids:
        p = db.query(models.Polis).filter(models.Polis.id == pid).first()
        if p is None:
            # Polis was deleted out from under the proposal. Render a
            # tombstone so the FE can show "Polis no longer available".
            out.append({
                "id": pid, "title": None, "prompt": None,
                "status": "missing", "participation_count": None,
            })
            continue
        participation: Optional[int]
        if p.polis_conversation_id:
            try:
                from polis_service import get_participation_stats
                stats = get_participation_stats(p.polis_conversation_id)
                participation = stats.get("participant_count")
            except Exception:
                participation = None
        else:
            participation = None
        out.append({
            "id": p.id,
            "title": p.title,
            "prompt": p.prompt,
            "status": p.status,
            "participation_count": participation,
        })
    return out


def _build_proposal_out(
    proposal: models.Proposal,
    db: Session,
    viewer_id: Optional[str] = None,
) -> schemas.ProposalOut:
    """Build the ProposalOut payload.

    `db` is required: the Phase 32.2 four-mode resolver reads
    `org.settings.{write_ins,pre_voting}.*_mode` to surface effective
    flag values, so it needs the org loaded by FK. (Phase 32.2 hotfix
    1: previously db was Optional and most call sites passed None,
    which silently fell back to platform defaults and broke
    `always_on` / `always_off` modes in the API surface.)
    `linked_polises` is also resolved via db when available; rich
    polis resolution is gated on db, but that path always had db
    in practice.

    Phase 32.2 — surfaces resolved-effective values + overridable
    flags for the four Phase 32 deliberation-engagement knobs. The
    frontend gates rendering (e.g., +Add option button, pre-vote panel,
    create-form toggle visibility) on these so it doesn't need to
    duplicate the resolver logic client-side.
    """
    from proposal_engagement_config import (
        resolve_allow_write_in_options_full,
        resolve_allow_write_ins_during_voting_full,
        resolve_allow_pre_voting_full,
        resolve_show_votes_during_deliberation_full,
        resolve_max_write_ins,
        resolve_edit_lockout_fraction,
    )
    _org = (
        db.get(models.Organization, proposal.org_id)
        if proposal.org_id is not None
        else None
    )
    _wi = resolve_allow_write_in_options_full(proposal, _org)
    _wi_dv = resolve_allow_write_ins_during_voting_full(proposal, _org)
    _pv = resolve_allow_pre_voting_full(proposal, _org)
    _svd = resolve_show_votes_during_deliberation_full(proposal, _org)

    # Phase 65 — delegation gating indicator. Same predicate the
    # resolution layer uses (DelegationService._build_context), so the
    # FE "direct vote only" indicator can never disagree with how the
    # tally actually resolves.
    from org_config import proposal_is_delegation_gated
    _gate_topic_ids = [pt.topic_id for pt in proposal.proposal_topics]
    _gate_topics = (
        db.query(models.Topic)
        .filter(models.Topic.id.in_(_gate_topic_ids))
        .all()
        if _gate_topic_ids else []
    )
    _delegation_gated = proposal_is_delegation_gated(
        proposal, _org, _gate_topics,
    )

    return schemas.ProposalOut(
        id=proposal.id,
        title=proposal.title,
        body=proposal.body,
        author_id=proposal.author_id,
        author=proposal.author,
        status=proposal.status,
        voting_method=proposal.voting_method,
        num_winners=proposal.num_winners,
        tie_resolution=proposal.tie_resolution,
        deliberation_start=proposal.deliberation_start,
        voting_start=proposal.voting_start,
        voting_end=proposal.voting_end,
        pass_threshold=proposal.pass_threshold,
        quorum_threshold=proposal.quorum_threshold,
        deliberation_days=getattr(proposal, "deliberation_days", None),
        voting_days=getattr(proposal, "voting_days", None),
        # Phase 75a — absolute voting deadline (NULL falls through to the
        # voting_days → org-default chain at advance time).
        voting_end_date=getattr(proposal, "voting_end_date", None),
        created_at=proposal.created_at,
        updated_at=proposal.updated_at,
        topics=proposal.proposal_topics,
        options=proposal.options,
        stable_result_required=proposal.stable_result_required,
        sub_org_id=getattr(proposal, "sub_org_id", None),
        linked_polis_ids=proposal.linked_polis_ids,
        linked_polises=_build_linked_polises(db, proposal),
        # Phase 32.1 followup hotfix: per-proposal override fields were
        # added to the SQLAlchemy model + the Pydantic schema in Phase 32
        # but this explicit-field response builder didn't surface them.
        # Result: every proposal API response had these as null in the
        # JSON body even when the row column was set. The trajectory
        # endpoint's resolver was reading the column directly (correct);
        # this builder was the lossy path.
        allow_write_in_options=getattr(proposal, "allow_write_in_options", None),
        allow_write_ins_during_voting=getattr(proposal, "allow_write_ins_during_voting", None),
        max_write_ins=getattr(proposal, "max_write_ins", None),
        allow_pre_voting=getattr(proposal, "allow_pre_voting", None),
        show_votes_during_deliberation=getattr(proposal, "show_votes_during_deliberation", None),
        edit_lockout_fraction=getattr(proposal, "edit_lockout_fraction", None),
        # Phase 32.2 — resolved-effective values via the 4-option resolver.
        effective_allow_write_in_options=_wi.effective,
        write_in_options_overridable=_wi.overridable,
        effective_allow_write_ins_during_voting=_wi_dv.effective,
        write_ins_during_voting_overridable=_wi_dv.overridable,
        effective_allow_pre_voting=_pv.effective,
        pre_voting_overridable=_pv.overridable,
        effective_show_votes_during_deliberation=_svd.effective,
        show_votes_during_deliberation_overridable=_svd.overridable,
        effective_max_write_ins=resolve_max_write_ins(proposal, _org),
        effective_edit_lockout_fraction=resolve_edit_lockout_fraction(proposal, _org),
        # Phase 46 — cosign-gated proposal surface (B3/B4). Always
        # safe to read: getattr-with-defaults on non-cosign-gated
        # proposals (the column is False/null). signature_count is a
        # cheap COUNT(*) — for non-gated proposals it returns 0.
        is_cosign_gated=bool(getattr(proposal, "is_cosign_gated", False)),
        cosign_threshold_snapshot=getattr(proposal, "cosign_threshold_snapshot", None),
        cosign_expires_at=getattr(proposal, "cosign_expires_at", None),
        cosign_signature_count=_cosign_signature_count(proposal, db),
        cosign_weight=_cosign_weight(proposal, db),
        viewer_has_cosigned=_viewer_has_cosigned(proposal, db, viewer_id),
        is_election=bool(getattr(proposal, "is_election", False)),
        election_title_id=getattr(proposal, "election_title_id", None),
        election_title_name=_election_title_name(proposal, db),
        election_candidates=_election_candidates(proposal, db),
        # Phase 52 Stage 1 — per-proposal verification gate. NULL =
        # ungated; non-null = floor required to cast direct vote.
        verification_floor=getattr(proposal, "verification_floor", None),
        verification_jurisdiction=getattr(proposal, "verification_jurisdiction", None),
        # Phase 65 — direct-vote-only indicator (org master switch off OR
        # any attached topic disallows delegation).
        delegation_gated=_delegation_gated,
        # Phase 66 — multi-winner approval config. NULL = legacy
        # single-winner (all pre-66 rows).
        approval_winner_config=getattr(
            proposal, "approval_winner_config", None,
        ),
        # Phase 73 — budget-voting config. NULL = not a budget proposal. The
        # FE branches its ballot + results UI on this, so it MUST surface.
        budget_config=getattr(proposal, "budget_config", None),
        # Phase 68b — viewer's archive capability (drives the FE "Archive"
        # action). False when no viewer context (list builds pass none).
        can_archive=_viewer_can_archive(proposal, db, viewer_id),
        # Phase 70 — viewer's advance capability + the next status, so the
        # FE can surface an "Advance to {next_status}" control without
        # re-deriving the gate or the transition map. Shares the endpoint's
        # permission ladder via _viewer_can_advance (single source of truth).
        can_advance=_viewer_can_advance(proposal, db, viewer_id),
        next_status=_author_next_status(proposal),
    )


def _election_title_name(proposal: models.Proposal, db: Session) -> Optional[str]:
    if not getattr(proposal, "is_election", False):
        return None
    tid = getattr(proposal, "election_title_id", None)
    if tid is None:
        return None
    title = db.get(models.OrgTitle, tid)
    return title.name if title else None


def _election_candidates(proposal: models.Proposal, db: Session) -> list[str]:
    if not getattr(proposal, "is_election", False):
        return []
    rows = db.query(models.ElectionCandidacy).filter(
        models.ElectionCandidacy.proposal_id == proposal.id,
        models.ElectionCandidacy.status == "declared",
    ).order_by(models.ElectionCandidacy.declared_at).all()
    return [r.user_id for r in rows]


def _cosign_weight(proposal: models.Proposal, db: Session) -> int:
    if not getattr(proposal, "is_cosign_gated", False):
        return 0
    from cosign import cosign_weight as _resolve_weight
    try:
        return _resolve_weight(db, proposal)
    except Exception:  # noqa: BLE001 — defensive; fall back to headcount.
        from cosign import signature_count
        return signature_count(db, proposal.id)


def _cosign_signature_count(proposal: models.Proposal, db: Session) -> int:
    if not getattr(proposal, "is_cosign_gated", False):
        return 0
    from cosign import signature_count
    return signature_count(db, proposal.id)


def _viewer_has_cosigned(
    proposal: models.Proposal, db: Session, viewer_id: Optional[str],
) -> Optional[bool]:
    if viewer_id is None or not getattr(proposal, "is_cosign_gated", False):
        return None
    row = db.query(models.ProposalCosignature).filter(
        models.ProposalCosignature.proposal_id == proposal.id,
        models.ProposalCosignature.user_id == viewer_id,
    ).first()
    return row is not None


def _emit_polis_link_diff_audits(
    db: Session,
    proposal: models.Proposal,
    old_ids: list[str],
    new_ids: list[str],
    actor_id: str,
    ip_address: Optional[str] = None,
) -> None:
    """Emit `polis.linked_to_proposal` / `polis.unlinked_from_proposal`
    one event per added / removed Polis.

    Pure diff against the old set. Idempotent: re-saving the same set
    emits zero events.
    """
    old_set, new_set = set(old_ids or []), set(new_ids or [])
    for pid in new_set - old_set:
        log_audit_event(
            db,
            action="polis.linked_to_proposal",
            target_type="polis",
            target_id=pid,
            actor_id=actor_id,
            details={
                "proposal_id": proposal.id,
                "polis_id": pid,
                "by_actor": actor_id,
            },
            ip_address=ip_address,
        )
    for pid in old_set - new_set:
        log_audit_event(
            db,
            action="polis.unlinked_from_proposal",
            target_type="polis",
            target_id=pid,
            actor_id=actor_id,
            details={
                "proposal_id": proposal.id,
                "polis_id": pid,
                "by_actor": actor_id,
            },
            ip_address=ip_address,
        )


def _enforce_threshold_permission(
    db: Session,
    user_id: str,
    org: Optional[models.Organization],
    requested_pass: Optional[float],
    requested_quorum: Optional[float],
) -> None:
    """Phase 12.5 — gate threshold overrides on `proposal.set_thresholds`.

    The check is "differs from defaults," NOT "is present" (spec line 133):
    a Member who explicitly passes `pass_threshold=0.50` (matching the org
    default) succeeds; only a Member trying `pass_threshold=0.10` fails.

    Args:
      requested_pass: the value from the request body, or None for "use
        whatever the route would otherwise default to". Falsy/None values
        are treated as "not setting this threshold" — the route uses the
        org default in that case.
      requested_quorum: same shape as requested_pass.

    For global (non-org) proposals — org is None — falls through to the
    platform-wide defaults (0.50 / 0.40) via the helper. There is no
    permission check possible without an org context, so global proposals
    use the existing free-form behavior. Org-scoped routes always pass org.

    Raises HTTPException(400) on permission denial with the spec's exact
    error message (line 130).
    """
    default_pass, default_quorum = get_default_proposal_thresholds(org)

    pass_diverges = (
        requested_pass is not None and requested_pass != default_pass
    )
    quorum_diverges = (
        requested_quorum is not None and requested_quorum != default_quorum
    )
    if not (pass_diverges or quorum_diverges):
        return

    # Only enforce the permission gate when there's an org context. Global
    # proposals (no org_id) keep their pre-12.5 behavior.
    if org is None:
        return

    if not _has_permission(db, user_id, org.id, "proposal.set_thresholds"):
        raise HTTPException(
            status_code=400,
            detail=(
                "You do not have permission to override the organization's "
                "default thresholds. Submit the proposal with default values "
                "or ask an Admin or Steward to set custom thresholds."
            ),
        )


# Phase 16 — floors for per-proposal duration overrides.
# Voting must be >= 0.05 days (72 minutes) — prevents pathological
# 1-second windows while still permitting live-poll use cases.
# Deliberation must be >= 0 days (zero is a valid choice for time-pressure
# decisions: proposal created -> straight to voting).
_VOTING_DAYS_FLOOR: float = 0.05
_DELIBERATION_DAYS_FLOOR: float = 0.0


def _validate_duration_floors(
    requested_delib: Optional[float], requested_vote: Optional[float],
) -> None:
    """Phase 16 — floor checks independent of the permission gate.

    Raises HTTPException(400) with the spec's exact error messages when
    a below-floor value is requested. Skips when the field is omitted.
    """
    if requested_vote is not None and requested_vote < _VOTING_DAYS_FLOOR:
        raise HTTPException(
            status_code=400,
            detail="Voting duration must be at least 0.05 days (72 minutes).",
        )
    if requested_delib is not None and requested_delib < _DELIBERATION_DAYS_FLOOR:
        raise HTTPException(
            status_code=400,
            detail="Deliberation duration cannot be negative.",
        )


def _enforce_duration_permission(
    db: Session,
    user_id: str,
    org: Optional[models.Organization],
    requested_delib: Optional[float],
    requested_vote: Optional[float],
) -> None:
    """Phase 16 — gate duration overrides on `proposal.set_durations`.

    Same shape as ``_enforce_threshold_permission``: the check is
    "differs from defaults," NOT "is present" (spec line 169). A user
    without the permission who explicitly passes values matching the
    org's defaults succeeds; only differing values trigger the gate.

    Args:
      requested_delib: deliberation_days from the request body, or None
        when the field was omitted (caller intends to use the org default).
      requested_vote: voting_days, same convention.

    For global (non-org) proposals — org is None — falls through to the
    platform-wide defaults via the helper. There is no permission check
    possible without an org context, so global proposals use the
    existing free-form behavior. Org-scoped routes always pass org.

    Raises HTTPException(400) on permission denial with the spec's exact
    error message (line 162).
    """
    default_delib, default_vote = get_default_proposal_durations(org)

    delib_diverges = (
        requested_delib is not None and float(requested_delib) != default_delib
    )
    vote_diverges = (
        requested_vote is not None and float(requested_vote) != default_vote
    )
    if not (delib_diverges or vote_diverges):
        return

    # Only enforce the permission gate when there's an org context. Global
    # proposals (no org_id) keep their pre-Phase-16 behavior.
    if org is None:
        return

    if not _has_permission(db, user_id, org.id, "proposal.set_durations"):
        raise HTTPException(
            status_code=400,
            detail=(
                "You do not have permission to override the organization's "
                "default durations. Submit the proposal with default values "
                "or ask a Moderator/Admin/Steward to set custom durations."
            ),
        )


def _collect_proposal_creation_errors(
    body: schemas.ProposalCreate,
    org: Optional[models.Organization] = None,
) -> list[tuple[str, int, str]]:
    """Phase 68a — collect ``(field, status_code, message)`` for every
    proposal-creation rule violation, rather than raising on the first.

    Single source of truth for the create-time validation rules + their
    exact messages. ``_validate_proposal_creation`` raises
    ``HTTPException`` for the first tuple (live create path, fail-fast);
    the import-preview path (``POST .../proposals/import-preview``)
    groups them field-keyed so the create form can surface every error
    at once instead of one-at-a-time round trips.
    """
    errors: list[tuple[str, int, str]] = []
    # Check org allowed_voting_methods. Ranked-choice in particular is
    # opt-in per org — surface as 403 (not 400) when the method is not
    # enabled, matching the Phase 7 spec.
    # Phase 8.5: walk the parent chain via get_org_config so a sub-org can
    # enable a voting method its parent doesn't, or vice-versa (Decision 9).
    if org is not None:
        from routes.organizations import DEFAULT_ORG_SETTINGS
        allowed = get_org_config(
            org,
            "allowed_voting_methods",
            DEFAULT_ORG_SETTINGS["allowed_voting_methods"],
        )
        if body.voting_method not in allowed:
            status_code = 403 if body.voting_method == "ranked_choice" else 400
            errors.append((
                "voting_method", status_code,
                f"Voting method '{body.voting_method}' is not allowed by this organization",
            ))
    # Phase 66 — approval_winner_config is approval-method-only. Shape
    # validation already happened at the Pydantic layer (422); this is
    # the method-compatibility gate (400).
    if (
        getattr(body, "approval_winner_config", None) is not None
        and body.voting_method != "approval"
    ):
        errors.append((
            "approval_winner_config", 400,
            (
                "approval_winner_config is only supported on approval "
                f"proposals (voting_method is '{body.voting_method}')."
            ),
        ))
    # Phase 73/74 — budget_config method/mode coherence (shape already
    # validated at the Pydantic layer). budget_config belongs only on a budget
    # method; a budget method requires it; the config mode must match the
    # method (allocation↔budget_allocation, project↔budget_project).
    _budget_methods = {"budget_allocation", "budget_project"}
    _budget_cfg = getattr(body, "budget_config", None)
    if _budget_cfg is not None and body.voting_method not in _budget_methods:
        errors.append((
            "budget_config", 400,
            (
                "budget_config is only supported on budget proposals "
                f"(voting_method is '{body.voting_method}')."
            ),
        ))
    if body.voting_method in _budget_methods and _budget_cfg is None:
        errors.append((
            "budget_config", 400,
            f"{body.voting_method} proposals require a budget_config.",
        ))
    if _budget_cfg is not None and body.voting_method in _budget_methods:
        _expected_mode = (
            "allocation" if body.voting_method == "budget_allocation" else "project"
        )
        if _budget_cfg.get("mode") != _expected_mode:
            errors.append((
                "budget_config", 400,
                (
                    f"budget_config.mode must be '{_expected_mode}' for "
                    f"{body.voting_method} proposals."
                ),
            ))
    # Phase 73 §4 — stable-result is not supported for budget proposals.
    if (
        body.voting_method in _budget_methods
        and getattr(body, "stable_result_required", None) is True
    ):
        errors.append((
            "stable_result_required", 400,
            "Stable-result is not yet supported for budget proposals.",
        ))
    if body.voting_method == "binary":
        if body.options:
            errors.append((
                "options", 400, "Binary proposals must not have options",
            ))
        if body.num_winners != 1:
            errors.append((
                "num_winners", 400,
                "num_winners must be 1 for binary proposals",
            ))
    elif body.voting_method == "approval":
        if len(body.options) < 2:
            errors.append((
                "options", 400,
                "Approval proposals require at least 2 options",
            ))
        if len(body.options) > 20:
            errors.append((
                "options", 400,
                "Approval proposals may have at most 20 options",
            ))
        seen_labels: set[str] = set()
        for opt in body.options:
            lower = opt.label.strip().lower()
            if lower in seen_labels:
                errors.append((
                    "options", 400, f"Duplicate option label: {opt.label}",
                ))
                break
            seen_labels.add(lower)
        if body.num_winners != 1:
            errors.append((
                "num_winners", 400,
                "num_winners must be 1 for approval proposals",
            ))
    elif body.voting_method == "ranked_choice":
        if len(body.options) < 2:
            errors.append((
                "options", 400,
                "Ranked-choice proposals require at least 2 options",
            ))
        if len(body.options) > 20:
            errors.append((
                "options", 400,
                "Ranked-choice proposals may have at most 20 options",
            ))
        seen_labels: set[str] = set()
        for opt in body.options:
            lower = opt.label.strip().lower()
            if lower in seen_labels:
                errors.append((
                    "options", 400, f"Duplicate option label: {opt.label}",
                ))
                break
            seen_labels.add(lower)
        if body.num_winners < 1 or body.num_winners > len(body.options):
            errors.append((
                "num_winners", 400,
                "num_winners must be between 1 and the number of options",
            ))
    elif body.voting_method == "budget_allocation":
        # Phase 73 — each option is a continuously-fundable bucket.
        if len(body.options) < 2:
            errors.append((
                "options", 400,
                "Budget proposals require at least 2 buckets",
            ))
        if len(body.options) > 20:
            errors.append((
                "options", 400,
                "Budget proposals may have at most 20 buckets",
            ))
        seen_labels: set[str] = set()
        for opt in body.options:
            lower = opt.label.strip().lower()
            if lower in seen_labels:
                errors.append((
                    "options", 400, f"Duplicate option label: {opt.label}",
                ))
                break
            seen_labels.add(lower)
        if body.num_winners != 1:
            errors.append((
                "num_winners", 400,
                "num_winners must be 1 for budget proposals",
            ))
    elif body.voting_method == "budget_project":
        # Phase 74 core + 74a — each option is a discrete fundable item OR a
        # Mode C "continuous-as-discrete" item (funded at its ceiling/floor,
        # all-or-$0). Cost tiers (tier_parent) are 74b — still rejected here.
        if len(body.options) < 2:
            errors.append((
                "options", 400,
                "Project budget proposals require at least 2 items",
            ))
        if len(body.options) > 20:
            errors.append((
                "options", 400,
                "Project budget proposals may have at most 20 items",
            ))
        seen_labels: set[str] = set()
        for opt in body.options:
            lower = opt.label.strip().lower()
            if lower in seen_labels:
                errors.append((
                    "options", 400, f"Duplicate option label: {opt.label}",
                ))
                break
            seen_labels.add(lower)
        for opt in body.options:
            kind = getattr(opt, "budget_kind", None) or "discrete"
            # Tier children are created server-side from a parent's nested
            # `tiers` (74b); a top-level option must not carry a parent link.
            if getattr(opt, "budget_tier_parent_id", None):
                errors.append((
                    "options", 400,
                    (
                        f"Item '{opt.label}' must not set budget_tier_parent_id "
                        "directly — add tiers nested under a tier_parent item."
                    ),
                ))
                break
            if kind not in ("discrete", "continuous-as-discrete", "tier_parent"):
                errors.append((
                    "options", 400,
                    (
                        f"Project budget item '{opt.label}' has unsupported "
                        f"budget_kind '{kind}'."
                    ),
                ))
                break
            floor = getattr(opt, "budget_floor_amount", None)
            if kind == "tier_parent":
                # 74b — a tier parent has >=1 nested tier and NO cost of its own.
                tiers = getattr(opt, "tiers", None) or []
                if len(tiers) < 1:
                    errors.append((
                        "options", 400,
                        f"Tier item '{opt.label}' requires at least one tier variant.",
                    ))
                    break
                if floor is not None or getattr(opt, "budget_max_amount", None) is not None:
                    errors.append((
                        "options", 400,
                        (
                            f"Tier item '{opt.label}' must not carry its own cost; "
                            "the cost lives on each tier variant."
                        ),
                    ))
                    break
                # Each tier's positive cost is enforced at the schema layer
                # (TierOptionCreate.budget_floor_amount gt=0).
            elif kind == "continuous-as-discrete":
                # Mode C funds at its ceiling if set, else its floor; either
                # must resolve to a positive cost.
                max_a = getattr(opt, "budget_max_amount", None)
                resolved = max_a if max_a is not None else floor
                if resolved is None or resolved <= 0:
                    errors.append((
                        "options", 400,
                        (
                            f"Continuous item '{opt.label}' requires a positive "
                            "budget_max_amount or budget_floor_amount (its "
                            "all-or-nothing cost)."
                        ),
                    ))
                    break
            else:  # discrete
                if floor is None or floor <= 0:
                    errors.append((
                        "options", 400,
                        (
                            f"Project budget item '{opt.label}' requires a "
                            "positive budget_floor_amount (its cost when funded)."
                        ),
                    ))
                    break
        if body.num_winners != 1:
            errors.append((
                "num_winners", 400,
                "num_winners must be 1 for budget proposals",
            ))
    return errors


def _validate_proposal_creation(body: schemas.ProposalCreate, org: Optional[models.Organization] = None):
    """Validate voting_method and options for proposal creation.

    Thin fail-fast wrapper over ``_collect_proposal_creation_errors``
    (Phase 68a) — raises ``HTTPException`` for the first rule violation,
    preserving the historical first-error-wins behavior + status codes.
    """
    for _field, status_code, message in _collect_proposal_creation_errors(body, org):
        raise HTTPException(status_code=status_code, detail=message)


def _create_proposal_options(db: Session, proposal_id: str, options: list[schemas.OptionCreate]):
    """Create ProposalOption rows for a multi-option proposal.

    Phase 74b — a tier-parent option (``budget_kind == 'tier_parent'``) carries
    nested ``tiers``; we create the parent row (no cost) then expand each tier
    into a child option row (``budget_kind='discrete'``,
    ``budget_tier_parent_id=parent.id``, ``budget_floor_amount=<tier cost>``).
    Children sort right after their parent; display_order is contiguous.
    """
    order = 0
    for opt in options:
        is_tier_parent = getattr(opt, "budget_kind", None) == "tier_parent"
        parent = models.ProposalOption(
            proposal_id=proposal_id,
            label=opt.label.strip(),
            description=opt.description,
            display_order=order,
            # Phase 73 — bucket ceiling (NULL on non-budget options).
            budget_max_amount=getattr(opt, "budget_max_amount", None),
            # Phase 74 — discrete project-item cost metadata (NULL otherwise).
            # A tier parent carries NO cost of its own.
            budget_floor_amount=(None if is_tier_parent else getattr(opt, "budget_floor_amount", None)),
            budget_kind=getattr(opt, "budget_kind", None),
            budget_tier_parent_id=getattr(opt, "budget_tier_parent_id", None),
            tier_allow_fallback=getattr(opt, "tier_allow_fallback", None),
        )
        db.add(parent)
        order += 1
        if is_tier_parent and getattr(opt, "tiers", None):
            db.flush()  # assign parent.id before linking children
            for tier in opt.tiers:
                db.add(models.ProposalOption(
                    proposal_id=proposal_id,
                    label=tier.label.strip(),
                    description=tier.description,
                    display_order=order,
                    budget_kind="discrete",
                    budget_floor_amount=tier.budget_floor_amount,
                    budget_tier_parent_id=parent.id,
                ))
                order += 1
    db.flush()


def _validate_and_update_options(
    db: Session,
    proposal: models.Proposal,
    options: list[schemas.OptionCreate],
):
    """Replace options on a multi-option proposal (draft/deliberation only)."""
    if proposal.status in ("voting", "passed", "failed", "withdrawn"):
        raise HTTPException(
            status_code=409,
            detail="Options cannot be edited after voting has started",
        )
    label_method = {
        "approval": "Approval",
        "budget_allocation": "Budget",
        "budget_project": "Project budget",
    }.get(proposal.voting_method, "Ranked-choice")
    if len(options) < 2:
        raise HTTPException(status_code=400, detail=f"{label_method} proposals require at least 2 options")
    if len(options) > 20:
        raise HTTPException(status_code=400, detail=f"{label_method} proposals may have at most 20 options")
    if proposal.voting_method == "ranked_choice":
        # num_winners is immutable after creation, but if options shrink below
        # num_winners, the proposal becomes inconsistent — reject.
        if proposal.num_winners > len(options):
            raise HTTPException(
                status_code=400,
                detail="Cannot reduce options below num_winners",
            )
    seen_labels: set[str] = set()
    for opt in options:
        lower = opt.label.strip().lower()
        if lower in seen_labels:
            raise HTTPException(status_code=400, detail=f"Duplicate option label: {opt.label}")
        seen_labels.add(lower)
    # Delete existing options
    for existing_opt in list(proposal.options):
        db.delete(existing_opt)
    db.flush()
    _create_proposal_options(db, proposal.id, options)


@router.get("", response_model=list[schemas.ProposalOut])
def list_proposals(
    status_filter: Optional[str] = Query(None, alias="status"),
    topic_id: Optional[str] = Query(None),
    org_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Phase 38 B1 — unscoped list endpoint now requires auth and filters
    each candidate proposal through ``_eligible_viewers_for_proposal``.
    Platform admins bypass the filter (D4). The Phase 14 public-org
    landing surface uses ``/api/orgs/{slug}/proposals`` instead, so
    requiring auth here doesn't break anonymous browsing of public-org
    splash pages.
    """
    q = db.query(models.Proposal)
    if org_id:
        q = q.filter(models.Proposal.org_id == org_id)
    if status_filter:
        q = q.filter(models.Proposal.status == status_filter)
    if topic_id:
        q = q.join(models.ProposalTopic).filter(models.ProposalTopic.topic_id == topic_id)
    proposals = q.order_by(*_proposal_list_ordering()).all()

    if not current_user.is_admin:
        proposals = [
            p for p in proposals
            if current_user.id in _eligible_viewers_for_proposal(db, p)
        ]

    return [_build_proposal_out(p, db) for p in proposals]


def _proposal_list_ordering():
    """Phase 31 F1 — three-tier status ordering for proposal lists.

    Returns a tuple of ORDER BY expressions for use with ``.order_by(*...)``.

    Primary: status group — voting (0) → deliberation (1) → closed (2) →
    draft (3). 'closed' covers passed / failed / withdrawn / unresolved.

    Secondary (within each group):
      - voting: ``voting_end`` ASC (closing soonest first).
      - deliberation: ``created_at`` DESC (newest first).
      - closed: ``updated_at`` DESC (most-recently-changed first; serves
        as the closed-at proxy since the schema has no dedicated
        ``closed_at`` column — the close action is typically the last
        write that touches the row).
      - draft: ``created_at`` DESC (fallback).

    Tertiary: ``created_at`` DESC as a stable tie-breaker.
    """
    status_group = case(
        (models.Proposal.status == "voting", 0),
        (models.Proposal.status == "deliberation", 1),
        (models.Proposal.status.in_(
            ["passed", "failed", "withdrawn", "unresolved"]
        ), 2),
        else_=3,  # draft and anything unexpected
    )
    voting_secondary = case(
        (models.Proposal.status == "voting", models.Proposal.voting_end),
        else_=None,
    )
    delib_secondary = case(
        (models.Proposal.status == "deliberation", models.Proposal.created_at),
        else_=None,
    )
    closed_secondary = case(
        (
            models.Proposal.status.in_(
                ["passed", "failed", "withdrawn", "unresolved"]
            ),
            models.Proposal.updated_at,
        ),
        else_=None,
    )
    return (
        status_group.asc(),
        voting_secondary.asc(),
        delib_secondary.desc(),
        closed_secondary.desc(),
        models.Proposal.created_at.desc(),
    )


@router.post("", response_model=schemas.ProposalOut, status_code=status.HTTP_201_CREATED)
@content_limiter.limit(PROPOSAL_CREATE_LIMIT)
def create_proposal(
    body: schemas.ProposalCreate,
    request: Request,
    db: Session = Depends(get_db),
    # Phase 86 (B-9) — proposal creation requires a verified email.
    current_user: models.User = Depends(auth_utils.require_verified_email),
):
    _validate_proposal_creation(body)

    # Phase 12.5 — global (non-org) proposals have no org context for the
    # threshold-permission gate, so the helper short-circuits and the
    # caller-supplied values are honored. Kept as a single call site for
    # symmetry with org-scoped POST (organizations.py::create_org_proposal).
    _enforce_threshold_permission(
        db, current_user.id, None,
        body.pass_threshold if "pass_threshold" in body.model_fields_set else None,
        body.quorum_threshold if "quorum_threshold" in body.model_fields_set else None,
    )

    # Phase 16 — duration floors + permission gate. Floors are enforced
    # regardless of org context (global proposals also can't have
    # below-floor values); the permission gate short-circuits for the
    # global path (no org context).
    requested_delib = (
        body.deliberation_days
        if "deliberation_days" in body.model_fields_set else None
    )
    requested_vote = (
        body.voting_days
        if "voting_days" in body.model_fields_set else None
    )
    _validate_duration_floors(requested_delib, requested_vote)
    _enforce_duration_permission(
        db, current_user.id, None, requested_delib, requested_vote,
    )
    # Phase 16 — record effective duration values on the proposal so the
    # row reflects what was decided at create time (spec line 109: existing
    # proposals keep whatever durations they were created with). Global
    # proposals fall back to platform defaults (org=None branch of helper).
    default_delib_days, default_vote_days = get_default_proposal_durations(None)
    effective_delib_days = (
        requested_delib if requested_delib is not None else default_delib_days
    )
    effective_vote_days = (
        requested_vote if requested_vote is not None else default_vote_days
    )

    # Phase 8 / Phase 20 — global (non-org) proposals: per-proposal
    # "Stable Result Required" override is always ignored at create time
    # because there is no org config to honor it against. Store as null.
    stable_result_required = None

    for t in body.topics:
        if not db.get(models.Topic, t.topic_id):
            raise HTTPException(status_code=400, detail=f"Topic {t.topic_id} not found")

    # Phase 9 — global (non-org) proposals don't have an org_id, so linked
    # Polis validation is skipped here (Polises always live under an org).
    # The org-scoped create endpoint in routes/organizations.py runs the
    # full validation. Reject linked_polis_ids on global proposals to
    # avoid silent acceptance.
    if body.linked_polis_ids:
        raise HTTPException(
            status_code=400,
            detail=(
                "linked_polis_ids is only supported on org-scoped proposals; "
                "create the proposal under /api/orgs/{slug}/proposals."
            ),
        )

    # Phase 25 B2 — 0-day deliberation skip. Mirrors the org-scoped path
    # in routes/organizations.py::create_org_proposal. When the effective
    # deliberation duration is zero, the proposal is created directly in
    # 'voting' status with a single audit event.
    skip_deliberation = (
        effective_delib_days is not None and float(effective_delib_days) == 0.0
    )
    now_at_create = (
        datetime.now(timezone.utc).replace(tzinfo=None) if skip_deliberation else None
    )

    proposal = models.Proposal(
        title=body.title,
        body=body.body,
        author_id=current_user.id,
        voting_method=body.voting_method,
        num_winners=body.num_winners,
        status="voting" if skip_deliberation else "draft",
        deliberation_start=now_at_create,
        voting_start=now_at_create,
        voting_end=(
            now_at_create + timedelta(days=float(effective_vote_days))
            if skip_deliberation else None
        ),
        pass_threshold=body.pass_threshold,
        quorum_threshold=body.quorum_threshold,
        deliberation_days=effective_delib_days,
        voting_days=effective_vote_days,
        # Phase 75a — absolute voting deadline (tz stripped to naive UTC).
        voting_end_date=_strip_tz(getattr(body, "voting_end_date", None)),
        stable_result_required=stable_result_required,
        # Phase 32 — per-proposal overrides; null = inherit org default
        # at read time (resolved by ``proposal_engagement_config``).
        allow_write_in_options=body.allow_write_in_options,
        allow_write_ins_during_voting=body.allow_write_ins_during_voting,
        max_write_ins=body.max_write_ins,
        allow_pre_voting=body.allow_pre_voting,
        show_votes_during_deliberation=body.show_votes_during_deliberation,
        edit_lockout_fraction=body.edit_lockout_fraction,
        # Phase 66 — multi-winner approval config. Validated for shape
        # at the Pydantic layer + method-compatibility in
        # _validate_proposal_creation above. NULL = legacy single-winner.
        approval_winner_config=body.approval_winner_config,
        # Phase 73 — budget config (allocation mode). Validated for shape at
        # the Pydantic layer + method/mode coherence in
        # _validate_proposal_creation above. NULL = not a budget proposal.
        budget_config=getattr(body, "budget_config", None),
    )
    db.add(proposal)
    db.flush()

    if skip_deliberation:
        log_audit_event(
            db,
            action="proposal.status_changed",
            target_type="proposal",
            target_id=proposal.id,
            actor_id=current_user.id,
            details={
                "proposal_id": proposal.id,
                "old_status": "draft",
                "new_status": "voting",
                "trigger": "zero_day_deliberation_skip",
            },
            ip_address=request.client.host if request.client else None,
        )

    for t in body.topics:
        db.add(models.ProposalTopic(
            proposal_id=proposal.id, topic_id=t.topic_id, relevance=t.relevance
        ))
    db.flush()

    if body.voting_method in ("approval", "ranked_choice", "budget_allocation", "budget_project") and body.options:
        _create_proposal_options(db, proposal.id, body.options)

    log_audit_event(
        db,
        action="proposal.created",
        target_type="proposal",
        target_id=proposal.id,
        actor_id=current_user.id,
        details={"title": proposal.title, "topic_ids": [t.topic_id for t in body.topics]},
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    db.refresh(proposal)
    return _build_proposal_out(proposal, db)


@router.get("/{proposal_id}", response_model=schemas.ProposalOut)
def get_proposal(
    proposal_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Phase 38 B1 — requires auth and eligibility. 404 on eligibility
    failure so the endpoint reveals nothing about non-eligible proposals
    (matches the Phase 19 / Phase 22 trajectory-endpoint posture)."""
    proposal = _proposal_or_404(proposal_id, db)
    if not current_user.is_admin:
        if current_user.id not in _eligible_viewers_for_proposal(db, proposal):
            raise HTTPException(status_code=404, detail="Proposal not found")
    # Phase 46 — thread viewer_id so viewer_has_cosigned populates on
    # detail GET (used by the Sign/Withdraw UI gate).
    return _build_proposal_out(proposal, db, viewer_id=current_user.id)


@router.patch("/{proposal_id}", response_model=schemas.ProposalOut)
def update_proposal(
    proposal_id: str,
    body: schemas.ProposalUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    proposal = _proposal_or_404(proposal_id, db)

    if proposal.status not in ("draft", "deliberation"):
        raise HTTPException(status_code=400, detail="Only draft or deliberation proposals can be edited")
    # Phase 32.2 B2 — author OR caller has `org.edit_proposal` permission
    # (Phase 32 D14 spec, now actually wired). Phase 32 shipped checking
    # `is_admin` only; Phase 32.1 hotfix #4 tightened the FE to match. With
    # the permission key now registered + seeded to admin/steward by
    # default, restore the spec'd gate. Platform admin still bypasses
    # because `has_permission` short-circuits on `User.is_admin`.
    if not (
        proposal.author_id == current_user.id
        or current_user.is_admin
        or (
            proposal.org_id is not None
            and _has_permission(
                db, current_user.id, proposal.org_id, "org.edit_proposal",
            )
        )
    ):
        raise HTTPException(
            status_code=403,
            detail="Not authorized to edit this proposal",
        )

    # Phase 32 E3 — edit lockout enforcement. Applies only during the
    # deliberation phase; draft proposals are unaffected (the author is
    # still composing). Fraction is resolved per-proposal-override-or-
    # org-default. Edge case (D17 operational watch-out): if the PATCH
    # also extends ``deliberation_days``, the lockout check runs against
    # the ORIGINAL deliberation_end — author can't dodge lockout by
    # extending then editing in one call. We achieve this by reading
    # ``proposal.deliberation_days`` here BEFORE applying the body's
    # updated value.
    from proposal_engagement_config import resolve_edit_lockout_fraction
    if proposal.status == "deliberation":
        org_for_lockout = (
            db.get(models.Organization, proposal.org_id)
            if proposal.org_id else None
        )
        lockout = resolve_edit_lockout_fraction(proposal, org_for_lockout)
        delib_start = proposal.deliberation_start
        if delib_start is not None and proposal.deliberation_days is not None:
            delib_end = delib_start + timedelta(
                days=float(proposal.deliberation_days)
            )
            duration = (delib_end - delib_start).total_seconds()
            if duration > 0:
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                elapsed = (now - delib_start).total_seconds()
                if elapsed / duration >= lockout:
                    raise HTTPException(
                        status_code=403,
                        detail=(
                            f"Editing is locked for the final "
                            f"{int(round((1 - lockout) * 100))}% of "
                            f"deliberation"
                        ),
                    )

    # Phase 32 E1/E2 — capture snapshot_before for the revision log. We
    # take this BEFORE any mutation so the diff captures what the field
    # values were at the moment the author submitted the edit. The set
    # of tracked fields mirrors D15's editable-during-deliberation list
    # plus the Phase 32 per-proposal override fields.
    snapshot_before = _snapshot_revisable_fields(proposal)

    # Phase 12.5 — threshold-override gate. Resolved BEFORE the field
    # writes below so a permission-denied PATCH leaves the proposal
    # untouched. Org context comes from the existing proposal (per spec
    # B3 step 1: "from existing proposal for PATCH").
    if "pass_threshold" in body.model_fields_set or "quorum_threshold" in body.model_fields_set:
        org_for_thresh = (
            db.get(models.Organization, proposal.org_id)
            if proposal.org_id else None
        )
        _enforce_threshold_permission(
            db, current_user.id, org_for_thresh,
            body.pass_threshold if "pass_threshold" in body.model_fields_set else None,
            body.quorum_threshold if "quorum_threshold" in body.model_fields_set else None,
        )
        if "pass_threshold" in body.model_fields_set and body.pass_threshold is not None:
            proposal.pass_threshold = body.pass_threshold
        if "quorum_threshold" in body.model_fields_set and body.quorum_threshold is not None:
            proposal.quorum_threshold = body.quorum_threshold

    # Phase 16 — duration-override gate (mirrors the threshold block
    # immediately above). Same atomicity property: floor + permission
    # checks fire BEFORE field writes so a 400 leaves the row untouched.
    if (
        "deliberation_days" in body.model_fields_set
        or "voting_days" in body.model_fields_set
    ):
        org_for_dur = (
            db.get(models.Organization, proposal.org_id)
            if proposal.org_id else None
        )
        requested_delib = (
            body.deliberation_days
            if "deliberation_days" in body.model_fields_set else None
        )
        requested_vote = (
            body.voting_days
            if "voting_days" in body.model_fields_set else None
        )
        _validate_duration_floors(requested_delib, requested_vote)
        _enforce_duration_permission(
            db, current_user.id, org_for_dur, requested_delib, requested_vote,
        )
        if (
            "deliberation_days" in body.model_fields_set
            and body.deliberation_days is not None
        ):
            proposal.deliberation_days = body.deliberation_days
        if (
            "voting_days" in body.model_fields_set
            and body.voting_days is not None
        ):
            proposal.voting_days = body.voting_days

    # Phase 75a — absolute voting deadline edit. Setting it (incl. to null to
    # clear) is handled independently of voting_days. The implied duration is
    # folded into the divergence gate so an absolute deadline can't bypass
    # proposal.set_durations. Floor/staleness are re-checked at advance.
    if "voting_end_date" in body.model_fields_set:
        org_for_end = (
            db.get(models.Organization, proposal.org_id)
            if proposal.org_id else None
        )
        if body.voting_end_date is not None:
            _end = _strip_tz(body.voting_end_date)
            _now = datetime.now(timezone.utc).replace(tzinfo=None)
            _implied = (_end - _now).total_seconds() / 86400
            _enforce_duration_permission(
                db, current_user.id, org_for_end, None, _implied,
            )
            proposal.voting_end_date = _end
        else:
            proposal.voting_end_date = None

    # Phase 62 A2 — per-proposal verification gate edit (draft-only).
    # Mirrors the create-path normalization block: validate against
    # VALID_STATES, enforce jurisdiction-presence consistency, drop a
    # misleading jurisdiction on a non-jurisdiction floor, normalize
    # email_only → NULL (= ungated). Gated on status='draft' because
    # tightening or relaxing the floor after voters have begun casting
    # would re-eligible/de-eligible them mid-vote.
    #
    # Semantics: client must send `verification_floor` to change the
    # gate at all. `verification_floor: null` clears the gate (and
    # any jurisdiction). Sending only `verification_jurisdiction`
    # without `verification_floor` is a no-op (matches the create
    # path which only acts when floor is non-null).
    if "verification_floor" in body.model_fields_set:
        if proposal.status != "draft":
            raise HTTPException(
                status_code=400,
                detail=(
                    "verification_floor / verification_jurisdiction can "
                    "only be changed while the proposal is in draft status."
                ),
            )
        if body.verification_floor is not None:
            from verification import (
                VALID_STATES,
                ORDER,
                jurisdiction_required_for,
                EMAIL_ONLY,
            )
            if body.verification_floor not in VALID_STATES:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Unknown verification_floor "
                        f"{body.verification_floor!r}. "
                        f"Allowed: {list(ORDER)}."
                    ),
                )
            _jur = body.verification_jurisdiction
            _jur = _jur.strip() if isinstance(_jur, str) else None
            if _jur == "":
                _jur = None
            if jurisdiction_required_for(body.verification_floor) and not _jur:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"verification_floor {body.verification_floor!r} "
                        "requires a non-empty verification_jurisdiction."
                    ),
                )
            if (
                not jurisdiction_required_for(body.verification_floor)
                and _jur
            ):
                body.verification_jurisdiction = None
            else:
                body.verification_jurisdiction = _jur
            if body.verification_floor == EMAIL_ONLY:
                body.verification_floor = None
                body.verification_jurisdiction = None
            proposal.verification_floor = body.verification_floor
            proposal.verification_jurisdiction = body.verification_jurisdiction
        else:
            # Explicit NULL → clear the gate. Jurisdiction is cleared
            # alongside so the column pair stays consistent.
            proposal.verification_floor = None
            proposal.verification_jurisdiction = None

    if body.title is not None:
        proposal.title = body.title
    if body.body is not None:
        proposal.body = body.body
    if body.topics is not None:
        for pt in list(proposal.proposal_topics):
            db.delete(pt)
        db.flush()
        for t in body.topics:
            if not db.get(models.Topic, t.topic_id):
                raise HTTPException(status_code=400, detail=f"Topic {t.topic_id} not found")
            db.add(models.ProposalTopic(
                proposal_id=proposal.id, topic_id=t.topic_id, relevance=t.relevance
            ))

    # Phase 59 A4 — voting_method + num_winners change while in draft.
    # Reject post-draft (the proposal has an audience by then; switching
    # method invalidates any cast intent). Option reshape: when leaving
    # an options-method, discard the existing ProposalOption rows
    # (cascade-via-ORM); the FE confirms the destructive intent with the
    # user before submitting. When entering RCV, num_winners defaults
    # to 1 unless supplied. When leaving RCV, num_winners snaps to 1.
    method_changed = (
        "voting_method" in body.model_fields_set
        and body.voting_method is not None
        and body.voting_method != proposal.voting_method
    )
    if method_changed:
        if proposal.status != "draft":
            raise HTTPException(
                status_code=400,
                detail=(
                    "voting_method can only be changed while the proposal "
                    "is in draft status."
                ),
            )
        new_method = body.voting_method
        # Validate against org's allowed_voting_methods (mirrors the
        # _validate_voting_method check on create).
        from routes.organizations import DEFAULT_ORG_SETTINGS
        org_for_method = (
            db.get(models.Organization, proposal.org_id)
            if proposal.org_id else None
        )
        if org_for_method is not None:
            allowed = (org_for_method.settings or {}).get(
                "allowed_voting_methods",
                DEFAULT_ORG_SETTINGS["allowed_voting_methods"],
            )
            if new_method not in allowed:
                raise HTTPException(
                    status_code=(
                        403 if new_method == "ranked_choice" else 400
                    ),
                    detail=(
                        f"Voting method '{new_method}' is not allowed by "
                        f"this organization"
                    ),
                )
        old_method = proposal.voting_method
        # When the new method is binary, drop any existing options.
        if new_method == "binary":
            for opt in list(proposal.options or []):
                db.delete(opt)
            db.flush()
        # When leaving RCV, snap num_winners back to 1 (unless the body
        # explicitly sets it).
        if old_method == "ranked_choice" and "num_winners" not in body.model_fields_set:
            proposal.num_winners = 1
        # Phase 66 — leaving the approval method clears any multi-winner
        # config (it's approval-only; mirrors the num_winners snap).
        if (
            old_method == "approval"
            and new_method != "approval"
            and getattr(proposal, "approval_winner_config", None) is not None
        ):
            proposal.approval_winner_config = None
        proposal.voting_method = new_method
    # num_winners change (independent of method change — RCV proposals
    # can adjust num_winners while in draft).
    if "num_winners" in body.model_fields_set and body.num_winners is not None:
        if proposal.status != "draft":
            raise HTTPException(
                status_code=400,
                detail=(
                    "num_winners can only be changed while the proposal "
                    "is in draft status."
                ),
            )
        proposal.num_winners = body.num_winners

    # Phase 66 — approval_winner_config change (draft-only, approval
    # method only). Shape was validated at the Pydantic layer; explicit
    # null clears the config (back to legacy single-winner). Runs AFTER
    # the voting_method block so a single PATCH that switches to
    # approval AND sets the config works.
    #
    # Phase 66a — approval-method ELECTIONS may now carry the config
    # (set at open-election time via _OpenElectionBody; editable here
    # only in the artificial draft-status case since real elections
    # open straight into deliberation). Non-approval elections still
    # reject it: num_winners owns RCV/STV winner counts.
    if "approval_winner_config" in body.model_fields_set:
        if (
            getattr(proposal, "is_election", False)
            and proposal.voting_method != "approval"
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "approval_winner_config is only supported on "
                    "approval-method elections (num_winners governs "
                    f"'{proposal.voting_method}' elections)."
                ),
            )
        if proposal.status != "draft":
            raise HTTPException(
                status_code=400,
                detail=(
                    "approval_winner_config can only be changed while "
                    "the proposal is in draft status."
                ),
            )
        if (
            body.approval_winner_config is not None
            and proposal.voting_method != "approval"
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "approval_winner_config is only supported on approval "
                    f"proposals (voting_method is "
                    f"'{proposal.voting_method}')."
                ),
            )
        proposal.approval_winner_config = body.approval_winner_config

    # Phase 73 — budget_config change (draft-only, budget method only). Shape
    # validated at the Pydantic layer; explicit null clears it. Mirrors the
    # approval_winner_config gate.
    if "budget_config" in body.model_fields_set:
        if proposal.status != "draft":
            raise HTTPException(
                status_code=400,
                detail=(
                    "budget_config can only be changed while the proposal is "
                    "in draft status."
                ),
            )
        if (
            body.budget_config is not None
            and proposal.voting_method not in ("budget_allocation", "budget_project")
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "budget_config is only supported on budget proposals "
                    f"(voting_method is '{proposal.voting_method}')."
                ),
            )
        proposal.budget_config = body.budget_config

    if body.options is not None:
        if proposal.voting_method not in ("approval", "ranked_choice", "budget_allocation", "budget_project"):
            raise HTTPException(
                status_code=400,
                detail="Options can only be set on approval, ranked-choice, or budget proposals",
            )
        _validate_and_update_options(db, proposal, body.options)

    # Phase 8 / Phase 20 — Stable Result Required per-proposal override.
    # Validate against the org's ``stable_result_per_proposal_override``
    # setting; only persist when the value actually changes so we don't emit
    # spurious audit events on no-op patches.
    if "stable_result_required" in body.model_fields_set:
        org = (
            db.get(models.Organization, proposal.org_id)
            if proposal.org_id else None
        )
        from sustained_majority_service import validate_per_proposal_override
        validate_per_proposal_override(body.stable_result_required, org)
        old_value = proposal.stable_result_required
        if old_value != body.stable_result_required:
            proposal.stable_result_required = body.stable_result_required
            log_audit_event(
                db,
                action=(
                    "proposal.stable_result_required_enabled"
                    if body.stable_result_required is True
                    else "proposal.stable_result_required_disabled"
                ),
                target_type="proposal",
                target_id=proposal.id,
                actor_id=current_user.id,
                details={
                    "old_value": old_value,
                    "new_value": body.stable_result_required,
                },
            )

    # Phase 32 — per-proposal override fields. Authors can flip these
    # during deliberation; they're not subject to a separate permission
    # gate beyond the existing author-or-admin check at the top of the
    # endpoint. Only persist when the field is in the payload AND the
    # value actually changes (matches the SRR pattern above).
    for _phase32_field in (
        "allow_write_in_options",
        "allow_write_ins_during_voting",
        "max_write_ins",
        "allow_pre_voting",
        "show_votes_during_deliberation",
        "edit_lockout_fraction",
    ):
        if _phase32_field in body.model_fields_set:
            new_val = getattr(body, _phase32_field)
            old_val = getattr(proposal, _phase32_field)
            if old_val != new_val:
                setattr(proposal, _phase32_field, new_val)

    # Phase 9 — linked Polises diff. Only run when the field is present in
    # the payload (omitted = leave existing links alone). For org-scoped
    # proposals, validate against scope rules (existence + viewer scope +
    # active status). Global proposals reject linked_polis_ids hard since
    # Polises live under an org.
    if "linked_polis_ids" in body.model_fields_set and body.linked_polis_ids is not None:
        if proposal.org_id is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "linked_polis_ids is only supported on org-scoped "
                    "proposals."
                ),
            )
        old_ids = list(proposal.linked_polis_ids or [])
        new_ids = list(body.linked_polis_ids)
        # Only validate the *new* additions (existing links could now be
        # archived; we don't want to forcibly re-validate them on every
        # PATCH). Removed IDs need no validation.
        added = [pid for pid in new_ids if pid not in old_ids]
        if added:
            _validate_linked_polis_ids(
                db, added, current_user.id, proposal.org_id,
            )
        proposal.linked_polis_ids = new_ids if new_ids else None
        _emit_polis_link_diff_audits(
            db, proposal, old_ids, new_ids,
            actor_id=current_user.id,
        )

    # Phase 32 E1/E2 — diff snapshot_before vs current state; if anything
    # changed AND the proposal is in deliberation (drafts don't generate
    # revisions — author is still composing), write a ProposalRevision
    # row + fire the ``proposal.edited`` notification to engaged members.
    # Drafts are intentionally excluded: revisions are visible to all
    # org members per D17, and surfacing the author's draft iteration
    # would be noise.
    db.flush()  # ensure topic/option changes are visible to snapshot_after
    snapshot_after = _snapshot_revisable_fields(proposal)
    changed_fields = _diff_revisable_snapshots(
        snapshot_before, snapshot_after,
    )
    if changed_fields and proposal.status == "deliberation":
        revision = models.ProposalRevision(
            proposal_id=proposal.id,
            org_id=proposal.org_id,
            edited_by_user_id=current_user.id,
            snapshot_before=snapshot_before,
            snapshot_after=snapshot_after,
            changed_fields=changed_fields,
        )
        db.add(revision)
        db.flush()

        log_audit_event(
            db,
            action="proposal.edited",
            target_type="proposal",
            target_id=proposal.id,
            actor_id=current_user.id,
            details={
                "changed_fields": changed_fields,
                "revision_id": revision.id,
            },
        )

        # E5 — fire ``proposal.edited`` notification to engaged members.
        # Phase 32.1 B2: engaged set is voters ∪ commenters ∪
        # delegators-on-the-proposal's-topic. A user who has delegated on
        # any of the proposal's topics is materially affected by the
        # edit even if they haven't voted or commented directly —
        # whichever delegate actually casts will do so on the post-edit
        # version of the proposal. Conservative inclusion: any active
        # delegation matching org+topic counts, regardless of whether
        # the user's strategy would actually route through this delegate
        # (resolving the graph for every edit is too expensive and
        # narrow-by-strategy noise isn't worth the audience trim). User-
        # side notification toggles are the safety valve if the audience
        # is too broad for any one user's taste.
        engaged_voter_ids = {
            row[0] for row in (
                db.query(models.Vote.user_id)
                .filter(models.Vote.proposal_id == proposal.id)
                .all()
            )
        }
        engaged_commenter_ids = {
            row[0] for row in (
                db.query(models.Comment.author_id)
                .filter(models.Comment.proposal_id == proposal.id)
                .all()
            )
        }
        engaged_delegator_ids: set[str] = set()
        topic_ids_for_proposal = [
            pt.topic_id for pt in proposal.proposal_topics
        ]
        if topic_ids_for_proposal and proposal.org_id is not None:
            delegations_q = db.query(models.Delegation.delegator_id).filter(
                models.Delegation.org_id == proposal.org_id,
                models.Delegation.topic_id.in_(topic_ids_for_proposal),
            )
            engaged_delegator_ids = {row[0] for row in delegations_q.all()}
        engaged = (
            engaged_voter_ids
            | engaged_commenter_ids
            | engaged_delegator_ids
        )
        engaged.discard(current_user.id)
        for uid in engaged:
            emit_notification(
                db,
                background_tasks,
                event_type="proposal.edited",
                user_id=uid,
                org_id=proposal.org_id,
                actor_id=current_user.id,
                target_type="proposal",
                target_id=proposal.id,
                payload={
                    "proposal_id": proposal.id,
                    "proposal_title": proposal.title,
                    "changed_fields": changed_fields,
                    "editor_username": current_user.username,
                },
            )

    db.commit()
    db.refresh(proposal)
    return _build_proposal_out(proposal, db)


@router.delete(
    "/{proposal_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_proposal(
    proposal_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Phase 59 A5 — hard-delete a draft proposal.

    Restricted to ``status='draft'`` ONLY. Proposals that have entered
    deliberation/voting (or any later status) preserve the audit trail
    via withdrawal, NOT deletion. This is a load-bearing invariant —
    asserted in tests — and deliberately the only `proposal` row
    deletion path in the codebase.

    Permission ladder: author OR ``org.edit_proposal`` permission OR
    platform admin. Mirrors the PATCH /api/proposals/{id} permission
    check.

    NOTE (Phase 72b): the ``proposal.delete`` permission key is
    intentionally NOT consulted here. Draft deletion is gated by the
    author / ``org.edit_proposal`` / platform-admin ladder above; there
    is no other proposal-deletion path. ``proposal.delete`` remains a
    registered-but-vestigial key (see permission_registry.py) — its
    description states it has no effect. Do not "fix" this by adding a
    ``proposal.delete`` check: deletion is deliberately org.edit_proposal-
    gated, and proposals past draft are archived (withdrawn), never
    deleted.

    Cascade: ORM `cascade='all, delete-orphan'` on Proposal's
    `options`, `proposal_topics`, and the rest of the relationship
    set handles dependent rows. No vote / delegation / comment rows
    can exist on a draft (those require deliberation/voting), so the
    cascade scope is bounded.
    """
    proposal = _proposal_or_404(proposal_id, db)
    if proposal.status != "draft":
        raise HTTPException(
            status_code=400,
            detail=(
                "Only draft proposals can be hard-deleted. "
                "Proposals that have entered deliberation or voting are "
                "withdrawn (preserving the audit trail), not deleted."
            ),
        )
    if not (
        proposal.author_id == current_user.id
        or current_user.is_admin
        or (
            proposal.org_id is not None
            and _has_permission(
                db, current_user.id, proposal.org_id, "org.edit_proposal",
            )
        )
    ):
        raise HTTPException(
            status_code=403,
            detail="Not authorized to delete this proposal",
        )

    log_audit_event(
        db,
        action="proposal.deleted",
        target_type="proposal",
        target_id=proposal.id,
        actor_id=current_user.id,
        details={"slug_org_id": proposal.org_id, "title": proposal.title},
    )
    db.delete(proposal)
    db.commit()
    from fastapi import Response
    return Response(status_code=204)


# ===========================================================================
# Phase 68b — archive a proposal (surfaces the existing `withdrawn` status
# as a user-facing "Archive" action). No new status: `withdrawn` already
# sits in the closed sort bucket and is excluded from the active flow, so
# it behaves exactly as "archive" should. Votes are preserved; nothing is
# deleted. There is no proposal-level `withdrawn` write-path before this
# (the only prior `status='withdrawn'` write is on ElectionCandidacy), so
# this is a brand-new endpoint per the spec's pre-flight branch.
# ===========================================================================


def _viewer_can_archive(
    proposal: models.Proposal, db: Session, viewer_id: Optional[str],
) -> bool:
    """Phase 68b — whether ``viewer_id`` may archive ``proposal`` right now.

    Mirrors the archive endpoint's permission ladder so the FE "Archive"
    affordance can never disagree with what the endpoint will allow:
      * platform admin → any phase
      * ``proposal.archive`` holder → any phase
      * author → own proposal while ``draft`` or ``deliberation``
    Already-archived (``withdrawn``) proposals return False (idempotency —
    the endpoint 409s, so there's nothing to offer).
    """
    if viewer_id is None or proposal.status == "withdrawn":
        return False
    user = db.get(models.User, viewer_id)
    if user is not None and user.is_admin:
        return True
    if proposal.org_id is not None and _has_permission(
        db, viewer_id, proposal.org_id, "proposal.archive",
    ):
        return True
    if (
        proposal.author_id == viewer_id
        and proposal.status in ("draft", "deliberation")
    ):
        return True
    return False


@router.post("/{proposal_id}/archive", response_model=schemas.ProposalOut)
def archive_proposal(
    proposal_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Phase 68b — archive a proposal by moving it to the ``withdrawn``
    status (user-facing label: "Archive").

    Permission ladder:
      * platform admin → any phase
      * ``proposal.archive`` holder → any phase (draft / deliberation /
        voting / passed / failed)
      * author → own proposal while ``draft`` or ``deliberation``

    Archiving a ``voting`` proposal is allowed (product-owner-confirmed):
    votes are PRESERVED on the row, no result is computed, and the audit
    event records who archived it and from which phase. Nothing is deleted.
    There is no "unarchive" in this pass (forward-only).
    """
    proposal = _proposal_or_404(proposal_id, db)

    # Idempotency guard: already-archived → 409 (nothing to do).
    if proposal.status == "withdrawn":
        raise HTTPException(
            status_code=409, detail="Proposal is already archived",
        )

    allowed = False
    if current_user.is_admin:
        allowed = True
    elif proposal.org_id is not None and _has_permission(
        db, current_user.id, proposal.org_id, "proposal.archive",
    ):
        allowed = True
    elif (
        proposal.author_id == current_user.id
        and proposal.status in ("draft", "deliberation")
    ):
        allowed = True

    if not allowed:
        raise HTTPException(
            status_code=403,
            detail=(
                "Not authorized to archive this proposal. Authors can "
                "archive their own draft or deliberation proposals; "
                "archiving at other phases requires the 'Archive proposals' "
                "permission."
            ),
        )

    from_status = proposal.status
    proposal.status = "withdrawn"
    # Touch updated_at so it sorts correctly in the closed bucket (which
    # orders by updated_at desc). onupdate would fire on the status change
    # too, but set it explicitly so the "most-recently-archived" ordering
    # is unambiguous. Votes / options / tally are deliberately untouched.
    proposal.updated_at = datetime.now(timezone.utc)

    log_audit_event(
        db,
        action="proposal.archived",
        target_type="proposal",
        target_id=proposal.id,
        actor_id=current_user.id,
        details={
            "proposal_id": proposal.id,
            "from_status": from_status,
            "by_actor": current_user.id,
            "title": proposal.title,
        },
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(proposal)
    return _build_proposal_out(proposal, db, viewer_id=current_user.id)


# ===========================================================================
# Phase 32 E — revision capture helpers + endpoints
# ===========================================================================


def _snapshot_revisable_fields(proposal: models.Proposal) -> dict:
    """Phase 32 E1 — serialize the editable-during-deliberation fields
    into a JSON-safe dict.

    Tracks: title, body, deliberation_days (proxy for deliberation_end
    which is derived), topics (list of {topic_id, relevance}), options
    (list of {id, label, description, display_order, is_write_in}),
    and the six Phase 32 per-proposal override flags.
    """
    return {
        "title": proposal.title,
        "body": proposal.body,
        "deliberation_days": proposal.deliberation_days,
        "voting_days": proposal.voting_days,
        "pass_threshold": proposal.pass_threshold,
        "quorum_threshold": proposal.quorum_threshold,
        "topics": sorted(
            [
                {"topic_id": pt.topic_id, "relevance": pt.relevance}
                for pt in proposal.proposal_topics
            ],
            key=lambda d: d["topic_id"],
        ),
        "options": sorted(
            [
                {
                    "id": o.id,
                    "label": o.label,
                    "description": o.description,
                    "display_order": o.display_order,
                    "is_write_in": bool(o.is_write_in),
                }
                for o in proposal.options
            ],
            key=lambda d: d["display_order"],
        ),
        "allow_write_in_options": proposal.allow_write_in_options,
        "allow_write_ins_during_voting": proposal.allow_write_ins_during_voting,
        "max_write_ins": proposal.max_write_ins,
        "allow_pre_voting": proposal.allow_pre_voting,
        "show_votes_during_deliberation": proposal.show_votes_during_deliberation,
        "edit_lockout_fraction": proposal.edit_lockout_fraction,
    }


def _diff_revisable_snapshots(before: dict, after: dict) -> list[str]:
    """Return the list of top-level keys whose values differ between the
    two snapshots. Empty list = no meaningful change (the PATCH was a
    no-op for revision purposes)."""
    return sorted(
        k for k in set(before) | set(after)
        if before.get(k) != after.get(k)
    )


@router.get(
    "/{proposal_id}/revisions",
    response_model=list[schemas.ProposalRevisionOut],
)
def get_proposal_revisions(
    proposal_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Phase 32 E4 — chronological list of every author-edit revision.

    Visible to any org member (D17 transparency-first). Platform admins
    bypass the membership check. Global (non-org) proposals are visible
    to any authenticated user since there's no org-membership concept.
    """
    proposal = _proposal_or_404(proposal_id, db)

    if proposal.org_id is not None and not current_user.is_admin:
        membership = (
            db.query(models.OrgMembership)
            .filter(
                models.OrgMembership.user_id == current_user.id,
                models.OrgMembership.org_id == proposal.org_id,
                models.OrgMembership.status == "active",
            )
            .first()
        )
        if membership is None:
            raise HTTPException(
                status_code=403,
                detail="Not a member of this proposal's organization",
            )

    revisions = (
        db.query(models.ProposalRevision)
        .filter(models.ProposalRevision.proposal_id == proposal.id)
        .order_by(models.ProposalRevision.edited_at.asc())
        .all()
    )
    return [
        schemas.ProposalRevisionOut.model_validate(r) for r in revisions
    ]


# ===========================================================================
# Phase 32 W — write-in options
# ===========================================================================


@router.post(
    "/{proposal_id}/options",
    response_model=schemas.OptionOut,
    status_code=status.HTTP_201_CREATED,
)
@content_limiter.limit(WRITEIN_OPTION_LIMIT)
def add_write_in_option(
    proposal_id: str,
    body: schemas.WriteInOptionCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    # Phase 86 (B-9) — write-in creation requires a verified email.
    current_user: models.User = Depends(auth_utils.require_verified_email),
):
    """Phase 32 W2 — add a write-in option to a multi-option proposal.

    Permission ladder:
      - Authenticated org member.
      - Proposal must have ``allow_write_in_options`` resolved True
        (per-proposal override OR org default).
      - Proposal must be multi-option (approval / ranked_choice).
      - Proposal must be in deliberation, OR in voting with
        ``allow_write_ins_during_voting`` resolved True.
      - Per-proposal cap (W4): existing write-in count < resolved
        ``max_write_ins`` (default 10).

    Side effect: fires ``proposal.option_added`` notification (W7) to
    every member who has cast a vote on this proposal, EXCLUDING the
    adder.
    """
    from proposal_engagement_config import (
        resolve_allow_write_in_options,
        resolve_allow_write_ins_during_voting,
        resolve_max_write_ins,
    )

    proposal = _proposal_or_404(proposal_id, db)
    org = (
        db.get(models.Organization, proposal.org_id)
        if proposal.org_id else None
    )

    # Org membership gate (org-scoped proposals only — globals are
    # platform-wide and write-ins aren't supported on them).
    if proposal.org_id is None:
        raise HTTPException(
            status_code=400,
            detail="Write-in options are only supported on org-scoped proposals",
        )
    if not current_user.is_admin:
        membership = (
            db.query(models.OrgMembership)
            .filter(
                models.OrgMembership.user_id == current_user.id,
                models.OrgMembership.org_id == proposal.org_id,
                models.OrgMembership.status == "active",
            )
            .first()
        )
        if membership is None:
            raise HTTPException(
                status_code=403,
                detail="Not a member of this proposal's organization",
            )

    if proposal.voting_method not in ("approval", "ranked_choice"):
        raise HTTPException(
            status_code=400,
            detail="Write-in options are only allowed on multi-option proposals",
        )

    if not resolve_allow_write_in_options(proposal, org):
        raise HTTPException(
            status_code=403,
            detail="Write-in options are not enabled for this proposal",
        )

    if proposal.status == "deliberation":
        pass  # OK
    elif proposal.status == "voting":
        if not resolve_allow_write_ins_during_voting(proposal, org):
            raise HTTPException(
                status_code=403,
                detail=(
                    "Write-in options are not allowed during voting "
                    "for this proposal"
                ),
            )
    else:
        raise HTTPException(
            status_code=400,
            detail=(
                "Write-in options can only be added during deliberation "
                "or voting"
            ),
        )

    # Cap check (W4) — count existing write-ins.
    write_in_count = (
        db.query(models.ProposalOption)
        .filter(
            models.ProposalOption.proposal_id == proposal.id,
            models.ProposalOption.is_write_in == True,  # noqa: E712
        )
        .count()
    )
    cap = resolve_max_write_ins(proposal, org)
    if write_in_count >= cap:
        raise HTTPException(
            status_code=400,
            detail=(
                f"This proposal has reached the maximum of {cap} "
                f"write-in options"
            ),
        )

    # Duplicate-label check (case-insensitive) against existing options.
    requested_label = body.label.strip()
    if not requested_label:
        raise HTTPException(status_code=400, detail="Label is required")
    lowered = requested_label.lower()
    for existing in proposal.options:
        if existing.label.strip().lower() == lowered:
            raise HTTPException(
                status_code=400,
                detail=f"An option with the label '{existing.label}' already exists",
            )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    next_order = (
        max((o.display_order for o in proposal.options), default=-1) + 1
    )
    option = models.ProposalOption(
        proposal_id=proposal.id,
        label=requested_label,
        description=body.description,
        display_order=next_order,
        added_by_user_id=current_user.id,
        added_at=now,
        is_write_in=True,
    )
    db.add(option)
    db.flush()

    log_audit_event(
        db,
        action="proposal.option_added",
        target_type="proposal_option",
        target_id=option.id,
        actor_id=current_user.id,
        details={
            "proposal_id": proposal.id,
            "label": option.label,
            "is_write_in": True,
        },
    )

    # W7 — fire notifications to existing voters (excluding the adder).
    voter_ids = {
        row[0] for row in (
            db.query(models.Vote.user_id)
            .filter(models.Vote.proposal_id == proposal.id)
            .all()
        )
    }
    voter_ids.discard(current_user.id)
    notification_payload = {
        "proposal_id": proposal.id,
        "proposal_title": proposal.title,
        "option_label": option.label,
        "added_by_username": current_user.username,
    }
    for voter_id in voter_ids:
        emit_notification(
            db,
            background_tasks,
            event_type="proposal.option_added",
            user_id=voter_id,
            org_id=proposal.org_id,
            actor_id=current_user.id,
            target_type="proposal",
            target_id=proposal.id,
            payload=notification_payload,
        )

    db.commit()
    db.refresh(option)
    return schemas.OptionOut.model_validate(option)


@router.delete(
    "/{proposal_id}/options/{option_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_write_in_option(
    proposal_id: str,
    option_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Phase 32 W3 — remove a write-in option.

    Permission ladder:
      - Option must be a write-in (originals can't be removed via this
        endpoint).
      - Caller must be the adder OR have ``org.edit_proposal``
        permission (admin / steward).
      - Existing approval / RCV ballots that reference this option drop
        the reference (approval: remove from approvals; RCV: remove
        from ranking and shift remaining ranks up).

    Hard delete chosen over soft delete: the audit-log entry below
    captures who-deleted-what-and-when; the per-vote ballot adjustment
    is reversible only by re-vote, which is the existing user surface.
    Document choice in closeout.
    """
    proposal = _proposal_or_404(proposal_id, db)
    option = db.get(models.ProposalOption, option_id)
    if option is None or option.proposal_id != proposal.id:
        raise HTTPException(status_code=404, detail="Option not found")

    if not option.is_write_in:
        raise HTTPException(
            status_code=400,
            detail=(
                "Only write-in options can be removed via this endpoint; "
                "original options are edited via the proposal PATCH."
            ),
        )

    is_adder = option.added_by_user_id == current_user.id
    is_admin = current_user.is_admin
    has_edit_perm = False
    if proposal.org_id is not None and not (is_adder or is_admin):
        has_edit_perm = _has_permission(
            db, current_user.id, proposal.org_id, "org.edit_proposal",
        )
    if not (is_adder or is_admin or has_edit_perm):
        raise HTTPException(
            status_code=403,
            detail="Not allowed to remove this write-in option",
        )

    # Strip the option from existing ballots before deleting the row.
    votes = (
        db.query(models.Vote)
        .filter(models.Vote.proposal_id == proposal.id)
        .all()
    )
    for v in votes:
        ballot = v.ballot
        if not isinstance(ballot, dict):
            continue
        changed = False
        if "approvals" in ballot and isinstance(ballot["approvals"], list):
            if option_id in ballot["approvals"]:
                ballot["approvals"] = [
                    oid for oid in ballot["approvals"] if oid != option_id
                ]
                changed = True
        if "ranking" in ballot and isinstance(ballot["ranking"], list):
            if option_id in ballot["ranking"]:
                ballot["ranking"] = [
                    oid for oid in ballot["ranking"] if oid != option_id
                ]
                changed = True
        if changed:
            # Reassign so SQLAlchemy notices the JSON mutation.
            v.ballot = dict(ballot)

    log_audit_event(
        db,
        action="proposal.option_removed",
        target_type="proposal_option",
        target_id=option.id,
        actor_id=current_user.id,
        details={
            "proposal_id": proposal.id,
            "label": option.label,
            "added_by_user_id": option.added_by_user_id,
        },
    )

    db.delete(option)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _assert_not_edit_locked(db: Session, proposal: models.Proposal) -> None:
    """Phase 76b — raise 403 if the proposal is in the locked tail of
    deliberation. Mirrors the lockout block inside ``update_proposal`` so
    in-place option edits respect the same window as title/body edits.
    No-op in draft (the author is still composing)."""
    if proposal.status != "deliberation":
        return
    from proposal_engagement_config import resolve_edit_lockout_fraction
    org_for_lockout = (
        db.get(models.Organization, proposal.org_id)
        if proposal.org_id else None
    )
    lockout = resolve_edit_lockout_fraction(proposal, org_for_lockout)
    delib_start = proposal.deliberation_start
    if delib_start is not None and proposal.deliberation_days is not None:
        delib_end = delib_start + timedelta(days=float(proposal.deliberation_days))
        duration = (delib_end - delib_start).total_seconds()
        if duration > 0:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            elapsed = (now - delib_start).total_seconds()
            if elapsed / duration >= lockout:
                raise HTTPException(
                    status_code=403,
                    detail=(
                        f"Editing is locked for the final "
                        f"{int(round((1 - lockout) * 100))}% of deliberation"
                    ),
                )


@router.patch(
    "/{proposal_id}/options/{option_id}",
    response_model=schemas.ProposalOut,
)
def update_option_text(
    proposal_id: str,
    option_id: str,
    body: schemas.OptionTextUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Phase 76b — in-place edit of an option's label / description.

    Editing original options used to require the proposal PATCH ``options``
    full-replace, which deletes + recreates every option row. That's safe in
    draft but lossy during deliberation: it changes option ids (orphaning any
    pre-votes cast while ``allow_pre_voting`` is on), drops write-in
    attribution, and would need budget tier structure reconstructed. This
    endpoint edits the row in place, so ids + ballots + budget metadata all
    survive.

    Permission ladder mirrors ``update_proposal``: author OR ``org.edit_proposal``
    (platform admin bypasses via ``has_permission``). Allowed in draft /
    deliberation only; the deliberation edit-lockout window applies.
    """
    proposal = _proposal_or_404(proposal_id, db)
    option = db.get(models.ProposalOption, option_id)
    if option is None or option.proposal_id != proposal.id:
        raise HTTPException(status_code=404, detail="Option not found")

    if proposal.status not in ("draft", "deliberation"):
        raise HTTPException(
            status_code=409,
            detail="Options cannot be edited after voting has started",
        )
    # Election candidate options store the candidate's user-id as the label and
    # the display name as the description; editing that text here would corrupt
    # the engine's stable keys. Election candidates are managed elsewhere.
    if getattr(proposal, "is_election", False):
        raise HTTPException(
            status_code=400,
            detail="Election candidate options can't be edited here",
        )

    if not (
        proposal.author_id == current_user.id
        or current_user.is_admin
        or (
            proposal.org_id is not None
            and _has_permission(
                db, current_user.id, proposal.org_id, "org.edit_proposal",
            )
        )
    ):
        raise HTTPException(
            status_code=403,
            detail="Not authorized to edit this proposal",
        )

    _assert_not_edit_locked(db, proposal)

    fields = body.model_fields_set
    if not ({"label", "description"} & fields):
        raise HTTPException(
            status_code=400,
            detail="Provide a label and/or description to update",
        )

    changed = {}
    if "label" in fields:
        new_label = (body.label or "").strip()
        if not new_label:
            raise HTTPException(status_code=400, detail="Option label cannot be empty")
        lower = new_label.lower()
        for sibling in proposal.options:
            if sibling.id != option.id and sibling.label.strip().lower() == lower:
                raise HTTPException(
                    status_code=400,
                    detail=f"Duplicate option label: {new_label}",
                )
        if new_label != option.label:
            changed["label"] = {"old": option.label, "new": new_label}
            option.label = new_label
    if "description" in fields:
        new_desc = body.description or ""
        if new_desc != (option.description or ""):
            changed["description"] = True
            option.description = new_desc

    if changed:
        log_audit_event(
            db,
            action="proposal.option_edited",
            target_type="proposal_option",
            target_id=option.id,
            actor_id=current_user.id,
            details={"proposal_id": proposal.id, "changed": list(changed.keys())},
        )

    db.commit()
    db.refresh(proposal)
    return _build_proposal_out(proposal, db)


def _is_delegate_target_for_proposal(
    db: Session, user_id: str, proposal: models.Proposal,
) -> bool:
    """Phase 13.3 — is anyone delegating to ``user_id`` on ANY of this
    proposal's topics?

    Counts a row in ``delegations`` where ``delegate_id == user_id`` and
    ``topic_id`` is one of the proposal's topics (or ``topic_id IS NULL``
    for global delegations). Returns False for topicless proposals
    (delegated_to_you doesn't fire when there's no topic to scope on).

    Phase 18 (B2.2): adds ``org_id == proposal.org_id`` filter so a
    delegation made in org X doesn't surface ``delegated_to_you``
    notifications for a proposal in org Y. The defensive fallback for
    legacy proposals with no ``org_id`` keeps the pre-fix behavior.
    """
    topic_ids = [pt.topic_id for pt in proposal.proposal_topics]
    if not topic_ids:
        return False
    proposal_org_id = getattr(proposal, "org_id", None)
    q = db.query(models.Delegation.id).filter(
        models.Delegation.delegate_id == user_id,
        models.Delegation.topic_id.in_(topic_ids),
    )
    if proposal_org_id is not None:
        q = q.filter(models.Delegation.org_id == proposal_org_id)
    return db.query(q.exists()).scalar() or False


def _has_delegated_away_for_proposal(
    db: Session, user_id: str, proposal: models.Proposal,
) -> bool:
    """Phase 13.3 — has ``user_id`` delegated their vote on ANY of this
    proposal's topics?

    Counts a row in ``delegations`` where ``delegator_id == user_id`` and
    ``topic_id`` is one of the proposal's topics. Topicless proposals
    treat all recipients as not-delegated (you_vote candidates).

    Phase 18 (B2.2): adds ``org_id == proposal.org_id`` filter so a
    delegation in org X doesn't suppress ``you_vote`` notifications for
    a proposal in org Y. The defensive fallback for legacy proposals with
    no ``org_id`` keeps the pre-fix behavior.
    """
    topic_ids = [pt.topic_id for pt in proposal.proposal_topics]
    if not topic_ids:
        return False
    proposal_org_id = getattr(proposal, "org_id", None)
    q = db.query(models.Delegation.id).filter(
        models.Delegation.delegator_id == user_id,
        models.Delegation.topic_id.in_(topic_ids),
    )
    if proposal_org_id is not None:
        q = q.filter(models.Delegation.org_id == proposal_org_id)
    return db.query(q.exists()).scalar() or False


def _resolve_voting_event_for_recipient(
    db: Session, user_id: str, proposal: models.Proposal,
) -> Optional[str]:
    """Phase 13.3 §B3 — pick the highest-priority voting-opened event
    the recipient has at least one channel enabled for.

    Priority order (highest first):
      1. ``proposal.entered_voting.delegated_to_you`` (if recipient is a
         delegate-target on one of the proposal's topics)
      2. ``proposal.entered_voting.you_vote`` (if recipient has not
         delegated their vote on any of the proposal's topics)
      3. ``proposal.entered_voting`` (generic fallback)

    Returns the chosen event_type or ``None`` if the recipient is opted
    into none of the candidates.
    """
    is_target = _is_delegate_target_for_proposal(db, user_id, proposal)
    has_delegated = _has_delegated_away_for_proposal(db, user_id, proposal)

    candidates: list[str] = []
    if is_target:
        candidates.append("proposal.entered_voting.delegated_to_you")
    if not has_delegated:
        candidates.append("proposal.entered_voting.you_vote")
    candidates.append("proposal.entered_voting")  # generic fallback last

    for candidate in candidates:
        if user_has_any_channel_enabled(db, user_id, candidate):
            return candidate
    return None


def _emit_proposal_status_notifications(
    db,
    background_tasks: BackgroundTasks,
    proposal: models.Proposal,
    old_status: str,
    new_status: str,
    actor_id: Optional[str],
) -> None:
    """Phase 13 B-emit / 13.3 §B3 — fire proposal.entered_voting (with
    priority-resolved variants) and proposal.closed.

    Always wrapped by the caller in try/except so a notification failure
    never sinks the originating advance/close request.

    Routing:
      - old != "voting" -> "voting": for each eligible voter, resolve to
        the highest-priority voting-opened event they're opted into and
        emit ONE notification (single-notification-per-recipient
        invariant, spec §B3).
      - "voting" -> "passed"/"failed": proposal.closed -> author + every
        user who voted (deduplicated).

    Author-self-vote dedup: a single user_id appears at most once per
    event regardless of how many roles (author, voter) they hold.
    """
    payload_base = {
        "proposal_id": proposal.id,
        "proposal_title": proposal.title,
        "org_id": proposal.org_id,
        "old_status": old_status,
        "new_status": new_status,
    }

    if old_status != "voting" and new_status == "voting":
        try:
            voter_ids = eligible_voter_ids_for_proposal(db, proposal)
        except Exception as e:  # noqa: BLE001
            log.warning(
                "proposal.entered_voting eligible-voters lookup failed: %s",
                e,
            )
            return
        for uid in voter_ids:
            chosen = _resolve_voting_event_for_recipient(db, uid, proposal)
            if chosen is None:
                # Recipient is opted into none of the three voting-opened
                # events — emit nothing for them. Single-notification-per-
                # recipient invariant: this is the "zero" case.
                continue
            emit_notification(
                db,
                background_tasks,
                event_type=chosen,
                user_id=uid,
                org_id=proposal.org_id,
                actor_id=actor_id,
                target_type="proposal",
                target_id=proposal.id,
                payload=payload_base,
            )

    if old_status == "voting" and new_status in ("passed", "failed"):
        recipients: set[str] = set()
        if proposal.author_id:
            recipients.add(proposal.author_id)
        # Everyone who cast a direct vote on this proposal.
        vote_rows = (
            db.query(models.Vote.user_id)
            .filter(models.Vote.proposal_id == proposal.id)
            .all()
        )
        for r in vote_rows:
            recipients.add(r.user_id)
        for uid in recipients:
            emit_notification(
                db,
                background_tasks,
                event_type="proposal.closed",
                user_id=uid,
                org_id=proposal.org_id,
                actor_id=actor_id,
                target_type="proposal",
                target_id=proposal.id,
                payload={
                    **payload_base,
                    "outcome": new_status,
                },
            )


def _maybe_resolve_tie(
    proposal: models.Proposal,
    tally,
    voting_method: str,
    db: Session,
    *,
    current_user_id: Optional[str],
) -> None:
    """Phase 17 — auto-resolve a tie at advance-to-passed time.

    Called from both ``advance_proposal`` (global) and
    ``advance_org_proposal`` (org-scoped) when a tally returns
    ``tied=True AND len(winners) > 1``. Loads the org's configured
    tie-resolution method, runs the resolver, persists the audit record
    to ``proposal.tie_resolution`` JSON, mutates ``tally.winners`` in
    place so downstream consumers (results page, ProposalResults schema)
    see the post-resolution set, and writes the
    ``proposal.tie_resolved`` audit log row.

    ``tally.winners`` is mutated by the route after auto-resolution; the
    pure tally functions in ``delegation_engine`` remain method-agnostic
    and return the un-resolved tied set (per spec line 433). ``tally.tied``
    intentionally stays ``True`` after resolution (D9) — the F2 results-
    page banner reads both fields to surface "this proposal had a tie,
    resolved via X."

    Defensive (B4.1, spec lines 270-272): if ``random_seed`` is selected
    and ``proposal.voting_end is None``, the resolver raises
    ``RuntimeError`` — that signals the route reached the passed branch
    without going through the voting branch (a bug elsewhere). We bubble
    that up as HTTP 500 so the failure is visible.
    """
    # Local imports: keep the tie-resolution module out of the proposals.py
    # import graph for callers that never hit a tie path, and avoid any
    # cycle if tie_resolution / org_config later need anything from here.
    from tie_resolution import resolve_tie
    from org_config import get_org_tie_resolution_method

    # Phase 66 (D4) — multi-winner boundary tie. When the pure layer
    # detected an equal-count group that only partially fits the
    # remaining seats, it seated the unambiguous set into
    # ``tally.winners`` and exposed the tied subset + seat count here.
    # Both fields are always empty for NULL-config proposals, so the
    # legacy branch below is byte-for-byte unchanged.
    boundary_tied = list(getattr(tally, "boundary_tied", None) or [])
    seats_remaining = int(getattr(tally, "seats_remaining", 0) or 0)
    is_boundary_tie = bool(boundary_tied) and seats_remaining > 0

    if not is_boundary_tie and not (
        getattr(tally, "tied", False)
        and len(getattr(tally, "winners", []) or []) > 1
    ):
        return

    org = db.get(models.Organization, proposal.org_id) if proposal.org_id else None
    method = get_org_tie_resolution_method(org, voting_method)

    try:
        if is_boundary_tie:
            # Route the boundary-tied subset through the org's resolver
            # for the remaining seat(s). ``expand_winners`` seats ALL
            # tied options in one call — documented existing semantics
            # (D11 precedent): the result may exceed max_winners. The
            # single-pick methods (random_seed / earliest_decisive_vote
            # / broader_approval_base) are invoked once per remaining
            # seat over the not-yet-chosen subset.
            chosen: list[str] = []
            seed: Optional[str] = None
            rounds_meta: list = []
            if method == "expand_winners":
                result = resolve_tie(
                    method, list(boundary_tied), proposal, tally, db,
                )
                chosen = list(result.chosen_winners)
                seed = result.seed
                rounds_meta.append(result.metadata)
            else:
                remaining = sorted(boundary_tied)
                for _seat in range(seats_remaining):
                    if not remaining:
                        break
                    result = resolve_tie(
                        method, list(remaining), proposal, tally, db,
                    )
                    picks = [
                        oid for oid in result.chosen_winners
                        if oid in remaining
                    ]
                    chosen.extend(picks)
                    remaining = [
                        oid for oid in remaining if oid not in picks
                    ]
                    seed = result.seed or seed
                    rounds_meta.append(result.metadata)
        else:
            result = resolve_tie(
                method, list(tally.winners), proposal, tally, db,
            )
    except RuntimeError as exc:
        # B4.1 — random_seed requires voting_end. None at resolution time
        # means the advance path didn't pass through the "voting" branch
        # that sets voting_end; surface as 500 rather than silently picking
        # something else.
        log.error(
            "tie resolution failed for proposal id=%s method=%s: %s",
            proposal.id, method, exc,
        )
        raise HTTPException(
            status_code=500,
            detail=(
                "Tie resolution invariant violated: "
                f"{exc}"
            ),
        ) from exc

    if is_boundary_tie:
        proposal.tie_resolution = {
            "method": method,
            "input_winners": list(boundary_tied),
            "chosen_winners": list(chosen),
            "seed": seed,
            "metadata": {
                "boundary_tie": True,
                "seats_remaining": seats_remaining,
                "rounds": rounds_meta,
            },
            "applied_at": datetime.now(timezone.utc).isoformat(),
        }
        # Merge the resolver's picks into the seated set (tally.tied
        # stays True for transparency — D9) and attribute their seats.
        tally.winners = list(tally.winners) + [
            oid for oid in chosen if oid not in tally.winners
        ]
        if hasattr(tally, "winner_seats"):
            for oid in chosen:
                tally.winner_seats.setdefault(oid, "tie_resolution")

        log_audit_event(
            db,
            action="proposal.tie_resolved",
            target_type="proposal",
            target_id=proposal.id,
            actor_id=current_user_id,
            details={
                "method": method,
                "input_winners": list(boundary_tied),
                "chosen_winners": list(chosen),
                "boundary_tie": True,
                "seats_remaining": seats_remaining,
            },
        )
        return

    proposal.tie_resolution = {
        "method": result.method,
        "input_winners": result.input_winners,
        "chosen_winners": result.chosen_winners,
        "seed": result.seed,
        "metadata": result.metadata,
        "applied_at": datetime.now(timezone.utc).isoformat(),
    }
    # Mutate tally.winners in place so downstream consumers see the
    # resolved winners (tally.tied stays True for transparency — D9).
    tally.winners = result.chosen_winners

    log_audit_event(
        db,
        action="proposal.tie_resolved",
        target_type="proposal",
        target_id=proposal.id,
        actor_id=current_user_id,
        details={
            "method": result.method,
            "input_winners": result.input_winners,
            "chosen_winners": result.chosen_winners,
        },
    )


@router.post("/{proposal_id}/advance", response_model=schemas.ProposalOut)
def advance_proposal(
    proposal_id: str,
    body: schemas.AdvanceProposalRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    # Permissions: platform admin, org admin/owner (proposal.advance_phase),
    # proposal author, or org moderator (own proposals only). Moderators get
    # 403 on others' proposals.
    #
    # Phase 70 — the allow decision is centralized in
    # _viewer_can_advance_permission (the single source of truth shared with
    # ProposalOut.can_advance, so the FE control + this gate never diverge).
    # The moderator-of-someone-else's-proposal case keeps its specific 403
    # message (asserted by test_proposal_lifecycle).
    proposal = _proposal_or_404(proposal_id, db)

    if not _viewer_can_advance_permission(
        proposal, db, current_user.id, user=current_user,
    ):
        if proposal.org_id and proposal.author_id != current_user.id:
            from org_middleware import membership_role_system_key as _sk
            membership = db.query(models.OrgMembership).filter(
                models.OrgMembership.org_id == proposal.org_id,
                models.OrgMembership.user_id == current_user.id,
                models.OrgMembership.status == "active",
            ).first()
            if membership and _sk(membership) == "moderator":
                raise HTTPException(
                    status_code=403,
                    detail="Moderators can only advance proposals they created",
                )
        raise HTTPException(status_code=403, detail="Not the proposal author or admin")

    next_status = STATUS_TRANSITIONS.get(proposal.status)
    if next_status is None:
        raise HTTPException(status_code=400, detail=f"Cannot advance from status '{proposal.status}'")

    old_status = proposal.status
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    if next_status == "deliberation":
        proposal.deliberation_start = now
    elif next_status == "voting":
        proposal.voting_start = now
        # Phase 25 B1.1 — derive voting_end from proposal.voting_days (or
        # org default) when the body doesn't supply one. body.voting_end is
        # honored if present but logs a deprecation warning.
        org_for_advance = (
            db.get(models.Organization, proposal.org_id)
            if proposal.org_id else None
        )
        proposal.voting_end = _compute_voting_end_at_advance(
            voting_start=now,
            body_voting_end=body.voting_end,
            proposal=proposal,
            org=org_for_advance,
        )
        _lock_election_candidate_options(db, proposal)
    elif next_status == "passed":
        tally = delegation_engine.compute_tally(proposal, db)
        if getattr(proposal, "is_election", False):
            # Phase 67 W1 — elections: quorum is the ONLY pass/fail
            # gate. Winner determination (tally winners, uncontested
            # auto-win, zero-candidate hold-over) belongs to
            # finalize_election, which fires on the "passed" close via
            # run_election_close_hook below. An under-quorum election
            # closes "failed" and seats NOTHING.
            from elections import election_close_status
            next_status = election_close_status(proposal, tally)
        elif proposal.voting_method == "approval":
            # Approval proposals pass if quorum met and at least one option
            # has votes. Phase 66: a multi-winner boundary tie can leave
            # ``winners`` empty with the whole contested set in
            # ``boundary_tied`` (e.g. Top 1 with two options tied at the
            # top) — that's resolvable, not a failure, so it counts as
            # "has votes" here. For NULL-config proposals boundary_tied
            # is always empty (legacy condition unchanged).
            if (
                isinstance(tally, ApprovalTally)
                and tally.quorum_met(proposal.quorum_threshold)
                and (tally.winners or tally.boundary_tied)
            ):
                _maybe_resolve_tie(
                    proposal, tally, "approval", db,
                    current_user_id=current_user.id,
                )
                next_status = "passed"
            else:
                next_status = "failed"
        elif proposal.voting_method == "ranked_choice":
            # RCV/STV passes if quorum met and at least one winner emerged
            if isinstance(tally, RCVTally) and tally.quorum_met(proposal.quorum_threshold) and tally.winners:
                _maybe_resolve_tie(
                    proposal, tally, "ranked_choice", db,
                    current_user_id=current_user.id,
                )
                next_status = "passed"
            else:
                next_status = "failed"
        elif proposal.voting_method in ("budget_allocation", "budget_project"):
            # Phase 73/74 — budget proposals pass on quorum alone (no yes/no, so
            # pass_threshold is not consulted), INCLUDING the degenerate "fund
            # nothing" case. Budget tallies have no winner set, so they never
            # route through tie resolution.
            from budget_tally import AllocationTally, ProjectTally
            if (
                isinstance(tally, (AllocationTally, ProjectTally))
                and tally.quorum_met(proposal.quorum_threshold)
            ):
                next_status = "passed"
            else:
                next_status = "failed"
        else:
            if tally.threshold_met(proposal.pass_threshold) and tally.quorum_met(proposal.quorum_threshold):
                next_status = "passed"
            else:
                next_status = "failed"

    proposal.status = next_status
    db.flush()

    # Phase 48 Stage 1 — close→assign-title hook. Phase 67 W1: quorum
    # gates seat installation — finalize_election (winner seating) only
    # fires on a "passed" close; a "failed" (quorum unmet) close skips
    # seating entirely and records election.not_finalized instead.
    # Failure containment is inside the helper: a hook error is logged
    # and never rolls back the proposal status transition.
    if getattr(proposal, "is_election", False) and next_status in ("passed", "failed"):
        from elections import run_election_close_hook
        next_status = run_election_close_hook(
            db, proposal, next_status,
            actor_id=current_user.id,
            ip_address=request.client.host if request.client else None,
        )

    log_audit_event(
        db,
        action="proposal.status_changed",
        target_type="proposal",
        target_id=proposal.id,
        actor_id=current_user.id,
        details={"proposal_id": proposal.id, "old_status": old_status, "new_status": next_status},
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    db.refresh(proposal)

    # Phase 13 B-emit — proposal.entered_voting / proposal.closed.
    try:
        _emit_proposal_status_notifications(
            db, background_tasks, proposal, old_status, next_status,
            actor_id=current_user.id,
        )
        db.commit()
    except Exception as e:  # noqa: BLE001
        log.warning(
            "proposal status emit failed (%s -> %s): %s: %s",
            old_status, next_status, type(e).__name__, e,
        )
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass

    # Phase 70 — pass viewer_id so the response's can_advance/can_archive
    # reflect the actor's capability on the NEW status (the FE re-labels or
    # hides the advance control from this same response).
    return _build_proposal_out(proposal, db, viewer_id=current_user.id)


# ---------------------------------------------------------------------------
# Phase 46 — Cosign endpoints
# ---------------------------------------------------------------------------

def _lock_election_candidate_options(
    db: Session, proposal: models.Proposal,
) -> None:
    """Phase 48 Stage 2 + Stage 3 — lock the candidate set into
    ProposalOption rows so the existing tally engine (RCV / approval)
    can resolve winners over candidate-keyed options.

    ``option.label`` carries the candidate's user_id so
    ``finalize_election`` maps tally winners back to users.

    Idempotent — only fires if no options exist yet (avoids
    duplicating if advance is somehow retried). Called from both the
    admin-direct advance path (``advance_proposal``) and the
    cosign-threshold-met auto-advance path
    (``_advance_cosign_to_voting``) so cosign-triggered elections (D4
    member_cosign trigger) lock options too.
    """
    if not getattr(proposal, "is_election", False):
        return
    if proposal.options:
        return
    from elections import active_candidacies
    candidates = active_candidacies(db, proposal.id)
    for i, c in enumerate(candidates):
        user = db.get(models.User, c.user_id)
        display = user.display_name if user else c.user_id
        db.add(models.ProposalOption(
            proposal_id=proposal.id,
            label=c.user_id,
            description=display,
            display_order=i,
        ))
    db.flush()


def _advance_cosign_to_voting(
    db: Session,
    proposal: models.Proposal,
    background_tasks: Optional[BackgroundTasks],
    actor_id: Optional[str],
    ip_address: Optional[str],
) -> None:
    """Run the deliberation → voting transition triggered by the cosign
    window-end gate (Phase 46a Item 2 — formerly fired inline by the
    sign endpoint in Phase 46; now only fired by the worker).

    Reuses the existing advance machinery so downstream behavior is
    indistinguishable from a manual advance: voting_end computed via
    ``_compute_voting_end_at_advance``, ``proposal.entered_voting``
    notifications fired (best-effort), ``proposal.status_changed`` audit
    emitted.

    Phase 46a — ``background_tasks`` is Optional because the worker
    calls this without a FastAPI request scope. ``_emit_proposal_status_
    notifications`` already wraps individual emits in try/except so
    passing ``None`` is safe — the notifications use background_tasks
    only for the in-app push delivery; missing background_tasks
    degrades to no async push (audit + DB notification rows are still
    written). ``actor_id=None`` is accepted for the same worker-context
    reason; the audit entry just records a system-level actor.
    """
    if proposal.status != "deliberation":
        return  # Defensive: already advanced or in a terminal state.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    org_for_advance = (
        db.get(models.Organization, proposal.org_id)
        if proposal.org_id else None
    )
    proposal.voting_start = now
    proposal.voting_end = _compute_voting_end_at_advance(
        voting_start=now,
        body_voting_end=None,
        proposal=proposal,
        org=org_for_advance,
    )
    old_status = proposal.status
    proposal.status = "voting"
    # Phase 48 Stage 3 — cosign-triggered elections: lock candidate
    # options before voting opens (same as the admin-direct path).
    _lock_election_candidate_options(db, proposal)
    log_audit_event(
        db,
        action="proposal.status_changed",
        target_type="proposal",
        target_id=proposal.id,
        actor_id=actor_id,
        details={
            "proposal_id": proposal.id,
            "old_status": old_status,
            "new_status": "voting",
            "trigger": "cosign_threshold_met",
        },
        ip_address=ip_address,
    )
    log_audit_event(
        db,
        action="proposal.cosign_threshold_met",
        target_type="proposal",
        target_id=proposal.id,
        actor_id=actor_id,
        details={
            "proposal_id": proposal.id,
            "threshold": proposal.cosign_threshold_snapshot,
            "voting_start": now.isoformat(),
            "voting_end": proposal.voting_end.isoformat(),
        },
        ip_address=ip_address,
    )
    try:
        _emit_proposal_status_notifications(
            db, background_tasks, proposal,
            old_status=old_status, new_status="voting",
            actor_id=actor_id,
        )
    except Exception:  # noqa: BLE001
        log.exception(
            "cosign auto-advance: emit_proposal_status_notifications failed "
            "for proposal %s; continuing (notification failure must not "
            "sink the advance).",
            proposal.id,
        )


def _require_cosign_gathering(proposal: models.Proposal) -> None:
    """Raise 400 unless the proposal is currently in cosign gathering
    (cosign-gated AND status=='deliberation')."""
    if not getattr(proposal, "is_cosign_gated", False):
        raise HTTPException(
            status_code=400,
            detail="This proposal is not cosign-gated.",
        )
    if proposal.status != "deliberation":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Proposal is no longer gathering signatures "
                f"(status='{proposal.status}')."
            ),
        )


def _require_active_org_member(
    db: Session, user_id: str, proposal: models.Proposal,
) -> None:
    """Raise 403 unless the user has an active OrgMembership on the
    proposal's org (cosigning is org-scoped per D4)."""
    if proposal.org_id is None:
        raise HTTPException(
            status_code=400,
            detail="Cosign is only supported on org-scoped proposals.",
        )
    membership = db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == proposal.org_id,
        models.OrgMembership.user_id == user_id,
        models.OrgMembership.status == "active",
    ).first()
    if membership is None:
        raise HTTPException(
            status_code=403,
            detail="You must be an active member of this organization to cosign.",
        )


@router.post("/{proposal_id}/cosign", response_model=schemas.ProposalOut)
def cosign_proposal(
    proposal_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Phase 46 B4 + 46a Item 2 — sign a cosign-gated proposal.

    Idempotent: re-signing is a no-op (returns 200 with the unchanged
    count). Signing only accrues weight; it does NOT advance the
    proposal mid-window. The deliberation window is the gathering
    cadence; the worker performs the unified window-end gate
    (advance-if-met / expire-if-unmet) at ``cosign_expires_at``.
    """
    proposal = _proposal_or_404(proposal_id, db)
    _require_cosign_gathering(proposal)
    _require_active_org_member(db, current_user.id, proposal)

    from cosign import add_signature

    added, new_count = add_signature(db, proposal, current_user.id)
    ip = request.client.host if request.client else None

    if added:
        log_audit_event(
            db,
            action="proposal.cosigned",
            target_type="proposal",
            target_id=proposal.id,
            actor_id=current_user.id,
            details={
                "proposal_id": proposal.id,
                "new_count": new_count,
                "threshold": proposal.cosign_threshold_snapshot,
            },
            ip_address=ip,
        )

    db.commit()
    db.refresh(proposal)
    return _build_proposal_out(proposal, db, viewer_id=current_user.id)


@router.delete("/{proposal_id}/cosign", response_model=schemas.ProposalOut)
def withdraw_cosign(
    proposal_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Phase 46 B4 — withdraw your signature from a cosign-gated proposal.

    The author cannot withdraw their implicit first signature (D4); they
    must withdraw the proposal itself (the existing /advance or PATCH
    status route). Other members may withdraw freely while the proposal
    is still gathering; the count decrements, which can drop it below
    threshold.
    """
    proposal = _proposal_or_404(proposal_id, db)
    _require_cosign_gathering(proposal)
    _require_active_org_member(db, current_user.id, proposal)

    if current_user.id == proposal.author_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "The author cannot withdraw their implicit signature; "
                "withdraw the proposal instead."
            ),
        )

    from cosign import remove_signature

    removed, new_count = remove_signature(db, proposal, current_user.id)
    ip = request.client.host if request.client else None

    if removed:
        log_audit_event(
            db,
            action="proposal.cosign_withdrawn",
            target_type="proposal",
            target_id=proposal.id,
            actor_id=current_user.id,
            details={
                "proposal_id": proposal.id,
                "new_count": new_count,
                "threshold": proposal.cosign_threshold_snapshot,
            },
            ip_address=ip,
        )

    db.commit()
    db.refresh(proposal)
    return _build_proposal_out(proposal, db, viewer_id=current_user.id)


def _approval_winner_seats(
    tally: ApprovalTally, proposal: models.Proposal,
) -> dict[str, str]:
    """Phase 66 — per-winner seat attribution for the results surface.

    Starts from the pure layer's ``winner_seats`` ("floor" /
    "threshold") and layers in "tie_resolution" for any boundary-tied
    option the persisted ``Proposal.tie_resolution`` record chose at
    close time. The live tally is recomputed on every results read, so
    close-time resolver picks only exist in the persisted record — this
    merge keeps the results page's attribution complete for closed
    proposals while remaining honest (an unresolved live boundary tie
    surfaces via ``boundary_tied`` / ``seats_remaining`` instead).
    """
    seats = dict(getattr(tally, "winner_seats", None) or {})
    record = getattr(proposal, "tie_resolution", None)
    boundary = set(getattr(tally, "boundary_tied", None) or [])
    if record and boundary:
        for oid in record.get("chosen_winners", []) or []:
            if oid in boundary and oid not in seats:
                seats[oid] = "tie_resolution"
    return seats


@router.get("/{proposal_id}/results", response_model=schemas.ProposalResults)
def get_results(
    proposal_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Phase 38 B1 — requires auth and eligibility. 404 on eligibility
    failure to avoid leaking live-tally state for in-progress votes in
    private sub-orgs."""
    proposal = _proposal_or_404(proposal_id, db)
    if not current_user.is_admin:
        if current_user.id not in _eligible_viewers_for_proposal(db, proposal):
            raise HTTPException(status_code=404, detail="Proposal not found")
    tally = delegation_engine.compute_tally(proposal, db)
    org = (
        db.get(models.Organization, proposal.org_id)
        if proposal.org_id else None
    )
    from sustained_majority_service import build_status as _sm_build_status
    sm_status = _sm_build_status(db, proposal, org)

    snapshots = (
        db.query(models.VoteSnapshot)
        .filter(models.VoteSnapshot.proposal_id == proposal_id)
        .order_by(models.VoteSnapshot.simulated_time)
        .all()
    )
    time_series = [
        schemas.SnapshotPoint(
            simulated_time=s.simulated_time,
            yes=s.yes_count,
            no=s.no_count,
            abstain=s.abstain_count,
            not_cast=s.not_cast_count,
            total_eligible=s.total_eligible,
        )
        for s in snapshots
    ]

    if proposal.voting_method == "approval" and isinstance(tally, ApprovalTally):
        # Build option label map
        option_labels = {opt.id: opt.label for opt in proposal.options}
        return schemas.ProposalResults(
            proposal_id=proposal_id,
            voting_method="approval",
            not_cast=tally.not_cast,
            total_eligible=tally.total_eligible,
            votes_cast=tally.total_ballots_cast,
            quorum_met=tally.quorum_met(proposal.quorum_threshold),
            option_approvals=tally.option_approvals,
            option_labels=option_labels,
            total_ballots_cast=tally.total_ballots_cast,
            total_abstain=tally.total_abstain,
            winners=tally.winners,
            tied=tally.tied,
            tie_resolution=proposal.tie_resolution,
            # Phase 66 — multi-winner attribution + boundary-tie surface.
            winner_seats=_approval_winner_seats(tally, proposal),
            boundary_tied=list(tally.boundary_tied or []),
            seats_remaining=tally.seats_remaining,
            approval_winner_config=getattr(
                proposal, "approval_winner_config", None,
            ),
            time_series=time_series,
            sustained_majority=sm_status,
        )

    if proposal.voting_method == "ranked_choice" and isinstance(tally, RCVTally):
        option_labels = {opt.id: opt.label for opt in proposal.options}
        rounds_out = [
            schemas.RCVRoundOut(
                round_number=r.round_number,
                option_counts=r.option_counts,
                eliminated=r.eliminated,
                elected=r.elected,
                transferred_from=r.transferred_from,
                transfer_breakdown=r.transfer_breakdown,
            )
            for r in tally.rounds
        ]
        return schemas.ProposalResults(
            proposal_id=proposal_id,
            voting_method="ranked_choice",
            not_cast=tally.not_cast,
            total_eligible=tally.total_eligible,
            votes_cast=tally.total_ballots_cast,
            quorum_met=tally.quorum_met(proposal.quorum_threshold),
            option_labels=option_labels,
            total_ballots_cast=tally.total_ballots_cast,
            total_abstain=tally.total_abstain,
            winners=tally.winners,
            tied=tally.tied,
            tie_resolution=proposal.tie_resolution,
            rounds=rounds_out,
            method=tally.method,
            num_winners=tally.num_winners,
            time_series=time_series,
            sustained_majority=sm_status,
        )

    from budget_tally import AllocationTally, ProjectTally
    if (
        proposal.voting_method == "budget_allocation"
        and isinstance(tally, AllocationTally)
    ):
        option_labels = {opt.id: opt.label for opt in proposal.options}
        cfg = getattr(proposal, "budget_config", None) or {}
        return schemas.ProposalResults(
            proposal_id=proposal_id,
            voting_method="budget_allocation",
            not_cast=tally.not_cast,
            total_eligible=tally.total_eligible,
            votes_cast=tally.total_ballots_cast,
            quorum_met=tally.quorum_met(proposal.quorum_threshold),
            option_labels=option_labels,
            total_ballots_cast=tally.total_ballots_cast,
            budget_amounts=tally.amounts,
            budget_total_allocated=tally.total_allocated,
            budget_unallocated_remainder=tally.unallocated_remainder,
            budget_degenerate_no_support=tally.degenerate_no_support,
            budget_envelope=cfg.get("envelope"),
            budget_currency=cfg.get("currency", "USD"),
            budget_aggregation=tally.aggregation,
            time_series=time_series,
            sustained_majority=sm_status,
        )

    if (
        proposal.voting_method == "budget_project"
        and isinstance(tally, ProjectTally)
    ):
        option_labels = {opt.id: opt.label for opt in proposal.options}
        cfg = getattr(proposal, "budget_config", None) or {}
        return schemas.ProposalResults(
            proposal_id=proposal_id,
            voting_method="budget_project",
            not_cast=tally.not_cast,
            total_eligible=tally.total_eligible,
            votes_cast=tally.total_ballots_cast,
            quorum_met=tally.quorum_met(proposal.quorum_threshold),
            option_labels=option_labels,
            total_ballots_cast=tally.total_ballots_cast,
            project_funded=tally.funded,
            project_unfunded=tally.unfunded,
            project_priority_order=tally.priority_order,
            project_total_committed=tally.total_committed,
            project_stop_point=tally.stop_point,
            project_group_desired_total=tally.group_desired_total,
            project_halt_reason=tally.halt_reason,
            project_min_spend=cfg.get("min_spend"),
            project_max_spend=cfg.get("max_spend"),
            budget_envelope=cfg.get("envelope"),
            budget_currency=cfg.get("currency", "USD"),
            time_series=time_series,
            sustained_majority=sm_status,
        )

    return schemas.ProposalResults(
        proposal_id=proposal_id,
        voting_method="binary",
        yes=tally.yes,
        no=tally.no,
        abstain=tally.abstain,
        not_cast=tally.not_cast,
        total_eligible=tally.total_eligible,
        votes_cast=tally.votes_cast,
        yes_pct=round(tally.yes_pct, 4),
        no_pct=round(tally.no_pct, 4),
        abstain_pct=round(tally.abstain_pct, 4),
        quorum_met=tally.quorum_met(proposal.quorum_threshold),
        threshold_met=tally.threshold_met(proposal.pass_threshold),
        time_series=time_series,
        sustained_majority=sm_status,
    )


@router.get("/{proposal_id}/verification-weight")
def my_verification_weight(
    proposal_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Phase 52 Stage 1 — transparency surface for the caller's
    delegated weight on a verification-gated proposal.

    Surfaces the difference between:
      * ``headline_delegated_count`` — total active org-scoped
        delegations TO the caller for this proposal's org (the
        "headline" weight a delegate would normally see).
      * ``effective_delegated_count`` — the subset of those
        delegators who are in the eligible-voter set for this
        specific proposal (i.e. who satisfy the verification floor
        when one applies AND the org's delegation-carries-weight
        setting is False; equal to ``headline`` when the proposal
        isn't gated OR the org opted into Yes).
      * ``gated_out_count`` — the principals whose weight didn't
        carry because they don't satisfy the floor.

    Honest-by-construction transparency: without this surface the
    weight evaporation reads as a bug in QA. The FE renders
    "Effective weight here: 12 of 40 — 28 of your delegators aren't
    verified for this vote" from these counts.

    Returns a 404 for an unknown proposal. ``proposal_is_gated`` and
    ``delegation_carries_unverified_weight`` are also exposed so
    the FE can decide which copy to render (no client-side guess at
    the gating state).
    """
    proposal = _proposal_or_404(proposal_id, db)
    org_id = getattr(proposal, "org_id", None)
    floor = getattr(proposal, "verification_floor", None)
    jurisdiction = getattr(proposal, "verification_jurisdiction", None)
    org = db.get(models.Organization, org_id) if org_id else None
    from verification import (
        delegation_carries_unverified_weight, user_satisfies_floor,
    )
    org_carries = (
        delegation_carries_unverified_weight(org) if org is not None else False
    )

    # Delegators TO the caller scoped to this proposal's org. Topic
    # scoping (org-wide vs topic-specific) is honored by the
    # ``Delegation.topic_id`` join: a delegation with topic_id IN
    # this proposal's topics OR NULL (org-wide) counts.
    if org_id is None:
        # Pre-multi-tenancy / unit-test rows — no org-scoped
        # delegation, return zeros.
        return {
            "headline_delegated_count": 0,
            "effective_delegated_count": 0,
            "gated_out_count": 0,
            "proposal_is_gated": False,
            "delegation_carries_unverified_weight": False,
            "floor": None,
            "jurisdiction": None,
        }

    proposal_topic_ids = [
        pt.topic_id for pt in db.query(models.ProposalTopic).filter(
            models.ProposalTopic.proposal_id == proposal.id,
        ).all()
    ]
    from sqlalchemy import or_ as _or_
    q = db.query(models.Delegation).filter(
        models.Delegation.org_id == org_id,
        models.Delegation.delegate_id == current_user.id,
    )
    if proposal_topic_ids:
        q = q.filter(
            _or_(
                models.Delegation.topic_id.is_(None),
                models.Delegation.topic_id.in_(proposal_topic_ids),
            )
        )
    else:
        q = q.filter(models.Delegation.topic_id.is_(None))
    delegations = q.all()
    delegator_ids = {d.delegator_id for d in delegations}

    headline = len(delegator_ids)
    if not floor or org_carries or not delegator_ids:
        effective = headline
        gated_out = 0
    else:
        users = db.query(models.User).filter(
            models.User.id.in_(delegator_ids),
        ).all()
        passing = {
            u.id for u in users
            if user_satisfies_floor(u, floor, jurisdiction)
        }
        effective = len(passing)
        gated_out = headline - effective

    return {
        "headline_delegated_count": headline,
        "effective_delegated_count": effective,
        "gated_out_count": gated_out,
        "proposal_is_gated": bool(floor),
        "delegation_carries_unverified_weight": bool(org_carries),
        "floor": floor,
        "jurisdiction": jurisdiction,
    }


@router.get("/{proposal_id}/my-vote", response_model=schemas.MyVoteStatus)
def my_vote_status(
    proposal_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    proposal = _proposal_or_404(proposal_id, db)

    # Phase 73/74 — budget proposals are direct-vote only; never resolve
    # through delegation. Return the caller's own direct ballot (or "not
    # cast"). This keeps my-vote consistent with the direct-only tally.
    if proposal.voting_method in ("budget_allocation", "budget_project"):
        own = (
            db.query(models.Vote)
            .filter(
                models.Vote.proposal_id == proposal.id,
                models.Vote.user_id == current_user.id,
                models.Vote.is_direct.is_(True),
            )
            .first()
        )
        if proposal.voting_method == "budget_allocation":
            if own is None or not own.ballot:
                return schemas.MyVoteStatus(
                    allocations=None, is_direct=None, delegate_chain=None,
                    cast_by=None,
                    message="You have not allocated a budget on this proposal.",
                )
            allocations = (own.ballot or {}).get("allocations", {})
            return schemas.MyVoteStatus(
                allocations=allocations, is_direct=True, delegate_chain=None,
                cast_by=db.get(models.User, current_user.id),
                message=f"You allocated across {len(allocations)} bucket(s).",
            )
        # budget_project
        if own is None or not own.ballot:
            return schemas.MyVoteStatus(
                ranked=None, is_direct=None, delegate_chain=None, cast_by=None,
                message="You have not ranked this project budget.",
            )
        ranked = (own.ballot or {}).get("ranked", [])
        return schemas.MyVoteStatus(
            ranked=ranked, is_direct=True, delegate_chain=None,
            cast_by=db.get(models.User, current_user.id),
            message=f"You ranked {len(ranked)} item(s).",
        )

    result = delegation_engine.resolve_vote(current_user.id, proposal.id, db)

    # Multi-option proposals only support strict_precedence delegation today.
    # Other strategies fall back; surface that to the frontend so it can
    # render the explanatory note.
    fallback = (
        proposal.voting_method in ("approval", "ranked_choice")
        and (current_user.delegation_strategy or "strict_precedence") != "strict_precedence"
    )

    if result is None:
        delegate_result = delegation_engine.find_delegate(current_user.id, proposal.id, db)
        if delegate_result:
            _, delegation = delegate_result
            delegate = db.get(models.User, delegation.delegate_id)
            msg = (
                f"Your delegate {delegate.display_name} has not voted. "
                f"Chain behavior: {delegation.chain_behavior}."
            )
        else:
            msg = "You have not voted and have no delegation covering this proposal."
        return schemas.MyVoteStatus(
            vote_value=None,
            is_direct=None,
            delegate_chain=None,
            cast_by=None,
            message=msg,
            delegation_strategy_fallback=fallback or None,
        )

    cast_by_user = db.get(models.User, result.cast_by_id)
    approvals = None
    ranking = None
    if proposal.voting_method == "approval":
        approvals = result.ballot.approvals if result.ballot.approvals else []
        n_approved = len(approvals)
        if result.is_direct:
            msg = f"You approved {n_approved} option(s) directly."
        else:
            chain_names = []
            for uid in result.delegate_chain:
                u = db.get(models.User, uid)
                chain_names.append(u.display_name if u else uid)
            msg = f"Your ballot ({n_approved} option(s) approved) via {' -> '.join(chain_names)}."
    elif proposal.voting_method == "ranked_choice":
        ranking = result.ballot.ranking if result.ballot.ranking else []
        n_ranked = len(ranking)
        if result.is_direct:
            msg = f"You ranked {n_ranked} option(s) directly."
        else:
            chain_names = []
            for uid in result.delegate_chain:
                u = db.get(models.User, uid)
                chain_names.append(u.display_name if u else uid)
            msg = f"Your ballot ({n_ranked} option(s) ranked) via {' -> '.join(chain_names)}."
    elif result.is_direct:
        msg = f"You voted {result.vote_value.upper()} directly."
    else:
        chain_names = []
        for uid in result.delegate_chain:
            u = db.get(models.User, uid)
            chain_names.append(u.display_name if u else uid)
        msg = f"Your vote is {result.vote_value.upper()} via {' -> '.join(chain_names)}."

    return schemas.MyVoteStatus(
        vote_value=result.vote_value,
        approvals=approvals,
        ranking=ranking,
        is_direct=result.is_direct,
        delegate_chain=result.delegate_chain,
        cast_by=cast_by_user,
        message=msg,
        delegation_strategy_fallback=fallback or None,
    )


@router.get("/{proposal_id}/vote-graph", response_model=schemas.VoteFlowGraph)
def get_vote_graph(
    proposal_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """
    Returns the delegation network for a specific proposal showing how every
    vote was cast or delegated, with privacy-aware node labelling.

    Phase 7B: extends the response with method-aware data (options list,
    per-voter ballot, method-specific cluster aggregates) so the frontend can
    render the option-attractor visualization for approval and RCV.
    """
    proposal = _proposal_or_404(proposal_id, db)
    # Phase 63 (security): same viewer-eligibility gate as get_proposal /
    # get_results / get_trajectory. Pre-fix this endpoint required only
    # authentication, so any logged-in user — including non-members of a
    # private org — could pull the full per-voter ballot list. 404 (not
    # 403) to avoid confirming the proposal exists.
    if not current_user.is_admin:
        if current_user.id not in _eligible_viewers_for_proposal(db, proposal):
            raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.status not in ("voting", "passed", "failed"):
        raise HTTPException(status_code=400, detail="Vote graph only available for voting/passed/failed proposals")

    voting_method = proposal.voting_method or "binary"

    # Build context for vote resolution.
    # Phase 10.1 (cross-scope vote leak fix): scope the user set to the
    # proposal's eligible voters. Pre-fix, all_users iterated every user in
    # the platform, which leaked cross-org and cross-sub-org votes into the
    # graph and inflated total_eligible.
    eligible_ids = eligible_voter_ids_for_proposal(db, proposal)
    ctx = delegation_engine._build_context(proposal, db, eligible_ids=eligible_ids)
    all_users = db.query(models.User).filter(models.User.id.in_(eligible_ids)).all()
    user_map = {u.id: u for u in all_users}
    proposal_topic_ids = [pt.topic_id for pt in proposal.proposal_topics]

    # Identify public delegates for this proposal's topics.
    # Phase 41 (2026-05-28): use canonical eligibility.public_delegate_user_ids
    # helper. Original Phase 37 B3 fix added the visibility filter inline
    # here + at routes/users.py::delegation_tree; Phase 41 followup
    # consolidates the predicate.
    from eligibility import public_delegate_user_ids
    pub_delegate_ids: set[str] = set()
    for pt in proposal.proposal_topics:
        pub_delegate_ids.update(
            public_delegate_user_ids(db, topic_id=pt.topic_id)
        )

    # Follow relationships of the current user (for visibility)
    following_ids: set[str] = set()
    for rel in db.query(models.FollowRelationship).filter(
        models.FollowRelationship.follower_id == current_user.id,
    ).all():
        following_ids.add(rel.followed_id)

    # Users who privately delegate TO the current user via a follow relationship
    # (not through a public delegate profile — those stay anonymous)
    private_follow_ids: set[str] = set()
    for rel in db.query(models.FollowRelationship).filter(
        models.FollowRelationship.followed_id == current_user.id,
        models.FollowRelationship.permission_level == "delegation_allowed",
    ).all():
        private_follow_ids.add(rel.follower_id)

    # Phase 18 (B2.2): scope delegators_to_me to the proposal's org so
    # the per-proposal vote-graph privacy resolution doesn't leak
    # cross-org delegators' identities into the rendered graph. The
    # defensive fallback for legacy proposals with no ``org_id`` keeps the
    # pre-fix behavior.
    delegators_to_me: set[str] = set()
    delegators_q = db.query(models.Delegation).filter(
        models.Delegation.delegate_id == current_user.id,
    )
    proposal_org_id = getattr(proposal, "org_id", None)
    if proposal_org_id is not None:
        delegators_q = delegators_q.filter(
            models.Delegation.org_id == proposal_org_id
        )
    for d in delegators_q.all():
        # Only reveal name if they delegate via a private follow relationship
        if d.delegator_id in private_follow_ids:
            delegators_to_me.add(d.delegator_id)

    # Resolve every user's vote
    vote_results: dict[str, Optional[object]] = {}
    for uid in user_map:
        vote_results[uid] = resolve_vote_pure(uid, ctx)

    # ------------------------------------------------------------------
    # Phase 63 (security): identity-redacted nodes must NOT expose the
    # voter's real user_id. The members endpoint maps user_id ->
    # display_name (+ email) for any co-member, so a real id on a
    # redacted node is a stable join key that de-anonymizes every
    # ballot. Redacted nodes get a per-request opaque id instead —
    # stable within this response only (nodes and edges are wired
    # through the same mapping), unlinkable across requests.
    # ------------------------------------------------------------------
    _graph_salt = secrets.token_hex(16)

    def _viewer_can_see_identity(uid: str) -> bool:
        return (
            uid == current_user.id
            or uid in pub_delegate_ids
            or uid in following_ids
            or uid in delegators_to_me
        )

    def _node_id(uid: str) -> str:
        if _viewer_can_see_identity(uid):
            return uid
        digest = hashlib.sha256(f"{_graph_salt}:{uid}".encode()).hexdigest()
        return f"anon_{digest[:16]}"

    # Build delegation edges: for each user who delegates, find their delegate
    edges: list[schemas.VoteFlowEdge] = []
    delegator_counts: dict[str, int] = {}  # delegate_id -> count of delegators

    # Topic map for edge colours
    topic_map: dict[str, models.Topic] = {}
    for t in db.query(models.Topic).all():
        topic_map[t.id] = t

    for uid, result in vote_results.items():
        if result and not result.is_direct and result.delegate_chain:
            # This user's vote comes via delegation
            direct_delegate_id = result.delegate_chain[0]

            # Determine which topic matched this delegation
            user_delegations = ctx.all_delegations.get(uid, {})
            user_precedences = ctx.all_precedences.get(uid, {})
            from delegation_engine import find_delegate_pure
            matched_delegation = find_delegate_pure(uid, proposal_topic_ids, user_precedences, user_delegations)
            matched_topic_id = matched_delegation.topic_id if matched_delegation else None

            topic_name = None
            topic_color = "#95a5a6"
            if matched_topic_id and matched_topic_id in topic_map:
                topic_name = topic_map[matched_topic_id].name
                topic_color = topic_map[matched_topic_id].color
            elif matched_topic_id is None:
                topic_name = "Global"
                topic_color = "#95a5a6"

            # Privacy: only show edge if current user is involved, or delegate is public
            can_see_edge = (
                uid == current_user.id
                or direct_delegate_id == current_user.id
                or direct_delegate_id in pub_delegate_ids
            )
            if can_see_edge:
                edges.append(schemas.VoteFlowEdge(
                    source=_node_id(uid),
                    target=_node_id(direct_delegate_id),
                    topic=topic_name,
                    topic_color=topic_color,
                    is_active=True,
                ))

            delegator_counts[direct_delegate_id] = delegator_counts.get(direct_delegate_id, 0) + 1

            # Chain edges (A->B->C)
            if len(result.delegate_chain) > 1:
                for i in range(len(result.delegate_chain) - 1):
                    chain_src = result.delegate_chain[i]
                    chain_tgt = result.delegate_chain[i + 1]
                    can_see_chain = (
                        chain_src == current_user.id
                        or chain_tgt == current_user.id
                        or chain_tgt in pub_delegate_ids
                    )
                    if can_see_chain:
                        edges.append(schemas.VoteFlowEdge(
                            source=_node_id(chain_src),
                            target=_node_id(chain_tgt),
                            topic=topic_name,
                            topic_color=topic_color,
                            is_active=True,
                        ))

    # ------------------------------------------------------------------
    # Build options list (approval / ranked_choice) and option-level
    # aggregates that feed both per-node ballots and the clusters block.
    # ------------------------------------------------------------------
    proposal_options = list(proposal.options) if voting_method in ("approval", "ranked_choice") else []
    proposal_options.sort(key=lambda o: o.display_order)
    option_id_set = {opt.id for opt in proposal_options}

    approval_counts: dict[str, int] = {opt.id: 0 for opt in proposal_options}
    first_pref_counts: dict[str, int] = {opt.id: 0 for opt in proposal_options}

    if voting_method == "approval":
        for uid, result in vote_results.items():
            if result is None or result.ballot is None:
                continue
            for oid in (result.ballot.approvals or []):
                if oid in approval_counts:
                    approval_counts[oid] += 1
    elif voting_method == "ranked_choice":
        for uid, result in vote_results.items():
            if result is None or result.ballot is None:
                continue
            ranking = result.ballot.ranking or []
            if ranking and ranking[0] in first_pref_counts:
                first_pref_counts[ranking[0]] += 1

    options_out: list[schemas.VoteFlowOption] = [
        schemas.VoteFlowOption(
            id=opt.id,
            label=opt.label,
            display_order=opt.display_order,
            approval_count=approval_counts.get(opt.id, 0) if voting_method == "approval" else 0,
            first_pref_count=first_pref_counts.get(opt.id, 0) if voting_method == "ranked_choice" else 0,
        )
        for opt in proposal_options
    ]

    # ------------------------------------------------------------------
    # Build nodes — method-aware ballot is returned for every voter who
    # has a ballot (regardless of identity visibility). Only identity
    # (label) is gated by `can_see_identity`. This separates the two
    # privacy boundaries: ballot content is aggregate-visible, identity
    # is per-relationship.
    # ------------------------------------------------------------------
    nodes: list[schemas.VoteFlowNode] = []

    for uid, result in vote_results.items():
        user = user_map.get(uid)
        if not user:
            continue

        is_self = uid == current_user.id
        is_pub = uid in pub_delegate_ids
        is_followed = uid in following_ids
        is_delegator_to_me = uid in delegators_to_me

        # Privacy: show real name if self, public delegate, followed, or they privately delegate to you
        # (must stay consistent with _viewer_can_see_identity above, which
        # drives the opaque node-id mapping)
        can_see_identity = is_self or is_pub or is_followed or is_delegator_to_me
        label = user.display_name if can_see_identity else ""

        if result is None:
            node_type = "non_voter"
            vote = None
            vote_source = None
            weight = 0
        elif result.is_direct:
            node_type = "direct_voter"
            vote = result.vote_value
            vote_source = "direct"
            weight = 1 + delegator_counts.get(uid, 0)
        else:
            node_type = "delegator"
            vote = result.vote_value
            vote_source = "delegation"
            weight = 1

        # Method-aware ballot — populated for every voter who has a ballot.
        # Identity gating (label) is independent: ballot content is part of
        # the aggregate population view; only identity stays redacted.
        ballot_obj: Optional[schemas.VoteFlowBallot] = None
        if result is not None and result.ballot is not None:
            if voting_method == "binary":
                ballot_obj = schemas.VoteFlowBallot(vote_value=result.ballot.vote_value)
            elif voting_method == "approval":
                ballot_obj = schemas.VoteFlowBallot(
                    approvals=list(result.ballot.approvals or [])
                )
            elif voting_method == "ranked_choice":
                ballot_obj = schemas.VoteFlowBallot(
                    ranking=list(result.ballot.ranking or [])
                )

        nodes.append(schemas.VoteFlowNode(
            # Phase 63 (security): real user_id only when the viewer may see
            # this voter's identity; otherwise a per-request opaque id.
            id=_node_id(uid),
            label=label,
            type=node_type,
            vote=vote,
            vote_source=vote_source,
            is_public_delegate=is_pub,
            is_current_user=is_self,
            delegator_count=delegator_counts.get(uid, 0),
            total_vote_weight=weight,
            ballot=ballot_obj,
            # Phase 9.8 — only surface the avatar when the viewer can see
            # the identity (label). For redacted nodes, return None so the
            # frontend renders the anonymous-circle treatment.
            avatar_url=user.avatar_url if can_see_identity else None,
        ))

    # ------------------------------------------------------------------
    # Build clusters — back-compat top-level binary fields plus method-
    # specific nested blocks. Aggregates are derived from vote_results.
    # ------------------------------------------------------------------
    legacy = {
        "yes": {"count": 0, "direct": 0, "delegated": 0},
        "no": {"count": 0, "direct": 0, "delegated": 0},
        "abstain": {"count": 0, "direct": 0, "delegated": 0},
        "not_cast": {"count": 0},
    }
    total_cast = 0
    total_abstain = 0
    binary_block: Optional[schemas.BinaryClusters] = None
    approval_block: Optional[schemas.ApprovalClusters] = None
    rcv_block: Optional[schemas.RCVClusters] = None

    if voting_method == "binary":
        for uid, result in vote_results.items():
            if result is None:
                legacy["not_cast"]["count"] += 1
            else:
                bucket = legacy.get(result.vote_value or "abstain", legacy["abstain"])
                bucket["count"] += 1
                if result.is_direct:
                    bucket["direct"] += 1
                else:
                    bucket["delegated"] += 1
                total_cast += 1
        total_abstain = legacy["abstain"]["count"]
        binary_block = schemas.BinaryClusters(**legacy)
    else:
        # Approval / RCV: count cast vs not_cast and empty-ballot abstains.
        for uid, result in vote_results.items():
            if result is None:
                continue
            total_cast += 1
            if voting_method == "approval":
                if not (result.ballot and result.ballot.approvals):
                    total_abstain += 1
            else:  # ranked_choice
                if not (result.ballot and result.ballot.ranking):
                    total_abstain += 1
        if voting_method == "approval":
            # Winners = options with the max approval count (ties allowed).
            non_zero = {oid: c for oid, c in approval_counts.items() if c > 0}
            winners: list[str] = []
            if non_zero:
                top = max(non_zero.values())
                winners = [oid for oid, c in non_zero.items() if c == top]
            approval_block = schemas.ApprovalClusters(
                option_counts=dict(approval_counts),
                winners=winners,
            )
        elif voting_method == "ranked_choice":
            # Reuse the existing tally service for IRV/STV winners + rounds.
            tally = delegation_engine.compute_tally(proposal, db)
            from delegation_engine import RCVTally as _RCVTally
            if isinstance(tally, _RCVTally):
                rcv_block = schemas.RCVClusters(
                    winners=list(tally.winners),
                    total_rounds=len(tally.rounds),
                )
            else:
                rcv_block = schemas.RCVClusters(winners=[], total_rounds=0)

    clusters = schemas.VoteFlowClusters(
        yes=legacy["yes"],
        no=legacy["no"],
        abstain=legacy["abstain"],
        not_cast=legacy["not_cast"],
        voting_method=voting_method,
        total_eligible=len(eligible_ids),
        total_cast=total_cast,
        total_abstain=total_abstain,
        binary=binary_block,
        approval=approval_block,
        rcv=rcv_block,
    )

    return schemas.VoteFlowGraph(
        proposal_id=proposal.id,
        proposal_title=proposal.title,
        voting_method=voting_method,
        total_eligible=len(eligible_ids),
        nodes=nodes,
        edges=edges,
        options=options_out,
        clusters=clusters,
    )


# ---------------------------------------------------------------------------
# Phase 22 — Support trajectory chart endpoint
# ---------------------------------------------------------------------------
#
# Surfaces the VoteSnapshot rows captured by the sustained_majority_worker
# (Phase 22 D1: now universal — every voting proposal gets snapshots, not
# just SRR-active ones) in a chart-ready shape. The frontend chart component
# fetches this on-expand and renders a support-over-time line / per-option
# trajectory + SRR annotation overlay.
#
# Response shape: per D3 of phase22_support_trajectory_chart_spec.md.
# Org-scoped (D4): only members of the proposal's org can fetch.
# Downsampling (D7): >500 snapshots are bucketed by time and reduced to
# the latest snapshot per bucket; client receives ≤500 points.

TRAJECTORY_MAX_POINTS = 500


class TrajectorySnapshotOut(BaseModel):
    """One snapshot point in the trajectory response.

    Binary fields (``support_fraction``) and multi-option fields
    (``winners`` + ``option_totals``) are mutually exclusive per snapshot.
    The frontend chart picks the right rendering path based on
    ``voting_method`` at the top level.

    ``option_totals`` can legitimately be ``None`` for old-shape snapshots
    captured before Phase 22's payload extension landed. The chart degrades
    gracefully (winner bar still renders from ``winners``).
    """
    captured_at: datetime
    votes_cast: int
    # Binary-only:
    support_fraction: Optional[float] = None
    # Multi-option only:
    winners: Optional[list[str]] = None
    option_totals: Optional[dict[str, float]] = None


class TrajectoryExtensionOut(BaseModel):
    fired_at: datetime
    reason: Optional[str] = None
    new_voting_end: Optional[datetime] = None


class TrajectoryDestabilizationOut(BaseModel):
    fired_at: datetime
    reason: Optional[str] = None


class TrajectorySRRAnnotations(BaseModel):
    stable_window_starts_at: Optional[datetime] = None
    stable_window_fraction: float
    extensions: list[TrajectoryExtensionOut] = []
    destabilization_events: list[TrajectoryDestabilizationOut] = []
    close_trigger: Optional[str] = None


class TrajectoryResponse(BaseModel):
    proposal_id: str
    voting_method: str
    voting_start: Optional[datetime] = None
    voting_end: Optional[datetime] = None
    snapshots: list[TrajectorySnapshotOut]
    srr_annotations: Optional[TrajectorySRRAnnotations] = None
    # Phase 32 P3 — deliberation_start surfaces when pre-voting visibility
    # is on so the frontend chart can extend its x-axis to span the
    # deliberation phase as well. NULL when visibility is off (frontend
    # uses voting_start as the x-axis lower bound, matching current
    # behavior).
    deliberation_start: Optional[datetime] = None
    show_votes_during_deliberation: bool = False


def _binary_support_fraction(snap: models.VoteSnapshot) -> float:
    """Phase 22 binary support_fraction: yes / (yes + no + abstain).

    Matches the Phase 20 binary stability semantics in
    ``sustained_majority.evaluate_original_window_stability``: support is
    measured against the cast pool, NOT against total_eligible. (A snapshot
    with 3 yes / 2 no and 5 not-cast = 60% support, not 30%.) Returns 0.0
    when no votes have been cast.
    """
    cast = (snap.yes_count or 0) + (snap.no_count or 0) + (snap.abstain_count or 0)
    if cast == 0:
        return 0.0
    return float(snap.yes_count or 0) / float(cast)


def _binary_votes_cast(snap: models.VoteSnapshot) -> int:
    return (
        (snap.yes_count or 0)
        + (snap.no_count or 0)
        + (snap.abstain_count or 0)
    )


def _downsample_snapshots(
    rows: list[models.VoteSnapshot],
    proposal: models.Proposal,
    max_points: int = TRAJECTORY_MAX_POINTS,
) -> list[models.VoteSnapshot]:
    """Uniform time-bucket downsampling per D7.

    Bucket size = (voting_end - voting_start).total_seconds() / max_points.
    For each bucket, keep the LATEST snapshot whose simulated_time falls in
    that bucket. Snapshots are already chronologically ordered on input.

    Falls back to a row-count-bucketing path when voting_start / voting_end
    are missing (e.g. a draft proposal that somehow accumulated snapshots);
    this keeps the endpoint defensively non-crashing on edge data.
    """
    if len(rows) <= max_points:
        return rows

    vs = proposal.voting_start
    ve = proposal.voting_end
    if vs is not None and ve is not None and ve > vs:
        total_seconds = (ve - vs).total_seconds()
        bucket_size = total_seconds / max_points
        if bucket_size > 0:
            # Group by bucket index; keep only the row with the latest
            # simulated_time in each bucket.
            buckets: dict[int, models.VoteSnapshot] = {}
            for r in rows:
                if r.simulated_time is None:
                    continue
                offset = (r.simulated_time - vs).total_seconds()
                idx = int(offset // bucket_size)
                if idx < 0:
                    idx = 0
                if idx >= max_points:
                    idx = max_points - 1
                existing = buckets.get(idx)
                if existing is None or (
                    existing.simulated_time is not None
                    and r.simulated_time >= existing.simulated_time
                ):
                    buckets[idx] = r
            return [
                buckets[k] for k in sorted(buckets.keys())
            ]

    # Fallback: row-count buckets (proposal lacks voting window timestamps).
    step = max(1, len(rows) // max_points)
    out: list[models.VoteSnapshot] = []
    for i in range(0, len(rows), step):
        chunk = rows[i:i + step]
        if chunk:
            # Latest in the chunk.
            out.append(chunk[-1])
        if len(out) >= max_points:
            break
    return out


def _build_snapshot_out(
    snap: models.VoteSnapshot,
    *,
    voting_method: str,
) -> TrajectorySnapshotOut:
    """Translate one VoteSnapshot row into the API response shape."""
    if voting_method == "binary":
        return TrajectorySnapshotOut(
            captured_at=snap.simulated_time,
            votes_cast=_binary_votes_cast(snap),
            support_fraction=_binary_support_fraction(snap),
        )
    # Multi-option (approval / ranked_choice).
    payload: dict[str, Any] = snap.multi_option_winners or {}
    winners = list(payload.get("winners") or [])
    total_cast = int(payload.get("total_ballots_cast") or 0)
    # option_totals may be absent on pre-Phase-22 snapshots (D12 / D2):
    # surface as None so the chart can degrade gracefully.
    raw_totals = payload.get("option_totals")
    option_totals: Optional[dict[str, float]]
    if raw_totals is None:
        option_totals = None
    else:
        option_totals = {
            str(k): float(v) for k, v in raw_totals.items()
        }
    return TrajectorySnapshotOut(
        captured_at=snap.simulated_time,
        votes_cast=total_cast,
        winners=winners,
        option_totals=option_totals,
    )


def _build_srr_annotations(
    db: Session,
    proposal: models.Proposal,
) -> Optional[TrajectorySRRAnnotations]:
    """Build srr_annotations from audit log + org config. Returns None when
    SRR is not active for this proposal (caller omits the field entirely).
    """
    if proposal.org_id is None:
        return None
    org = db.get(models.Organization, proposal.org_id)
    if org is None:
        return None
    from sustained_majority import (
        get_stable_result_config as _cfg,
        is_proposal_stable_result_active as _active,
    )
    config = _cfg(org)
    if not _active(proposal.stable_result_required, config.enabled_default):
        return None

    # Stable-window-starts-at, derived from the ORIGINAL voting duration
    # (so the chart annotation matches Phase 20's stability math even
    # for proposals that have already been extended).
    from sustained_majority_service import (
        reconstruct_original_voting_duration as _orig_dur,
    )
    stable_window_starts_at: Optional[datetime] = None
    if proposal.voting_start is not None:
        orig_dur = _orig_dur(db, proposal)
        if orig_dur is not None and orig_dur.total_seconds() > 0:
            stable_window_starts_at = (
                proposal.voting_start
                + orig_dur * (1.0 - config.stable_window_fraction)
            )

    # Walk audit log for extensions (worker-fired only — actor_id IS NULL).
    extension_rows = (
        db.query(models.AuditLog)
        .filter(
            models.AuditLog.action == "proposal.window_extended",
            models.AuditLog.target_id == proposal.id,
            models.AuditLog.actor_id.is_(None),
        )
        .order_by(models.AuditLog.timestamp.asc())
        .all()
    )
    extensions: list[TrajectoryExtensionOut] = []
    for row in extension_rows:
        details = row.details or {}
        new_end_raw = details.get("new_voting_end") if isinstance(details, dict) else None
        new_end: Optional[datetime] = None
        if isinstance(new_end_raw, str):
            try:
                new_end = datetime.fromisoformat(new_end_raw)
            except ValueError:
                new_end = None
        extensions.append(TrajectoryExtensionOut(
            fired_at=row.timestamp,
            reason=details.get("reason") if isinstance(details, dict) else None,
            new_voting_end=new_end,
        ))

    # Walk audit log for destabilization-at-max events.
    destab_rows = (
        db.query(models.AuditLog)
        .filter(
            models.AuditLog.action == "proposal.destabilization_at_max_extensions",
            models.AuditLog.target_id == proposal.id,
        )
        .order_by(models.AuditLog.timestamp.asc())
        .all()
    )
    destabilization_events: list[TrajectoryDestabilizationOut] = []
    for row in destab_rows:
        details = row.details or {}
        destabilization_events.append(TrajectoryDestabilizationOut(
            fired_at=row.timestamp,
            reason=details.get("reason") if isinstance(details, dict) else None,
        ))

    # close_trigger from the most-recent proposal.status_changed audit row.
    close_row = (
        db.query(models.AuditLog)
        .filter(
            models.AuditLog.action == "proposal.status_changed",
            models.AuditLog.target_id == proposal.id,
        )
        .order_by(models.AuditLog.timestamp.desc())
        .first()
    )
    close_trigger: Optional[str] = None
    if close_row is not None and isinstance(close_row.details, dict):
        trig = close_row.details.get("trigger")
        if isinstance(trig, str) and trig:
            close_trigger = trig

    return TrajectorySRRAnnotations(
        stable_window_starts_at=stable_window_starts_at,
        stable_window_fraction=config.stable_window_fraction,
        extensions=extensions,
        destabilization_events=destabilization_events,
        close_trigger=close_trigger,
    )


@router.get("/{proposal_id}/trajectory", response_model=TrajectoryResponse)
def get_trajectory(
    proposal_id: str,
    response: Response,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Phase 22 D3 — support-trajectory data for the chart panel.

    Returns chronologically-ordered VoteSnapshot rows shaped for the chart,
    with SRR annotation overlay metadata when the proposal has Stable Result
    Required active. Org-scoped (D4) — only members of the proposal's org
    can fetch.

    Performance: downsampled to ≤500 points (D7) for long voting windows.
    Caching: Cache-Control max-age varies by status — closed proposals are
    immutable so cache aggressively; voting proposals get a short max-age
    (the trajectory monotonically extends as the worker writes more rows).
    """
    proposal = _proposal_or_404(proposal_id, db)

    # D4 — org-scoped access. Platform admins bypass; org members of the
    # proposal's org pass; everyone else gets 403.
    if not current_user.is_admin:
        if proposal.org_id is None:
            raise HTTPException(
                status_code=403,
                detail="Trajectory requires an org-scoped proposal.",
            )
        membership = (
            db.query(models.OrgMembership)
            .filter(
                models.OrgMembership.org_id == proposal.org_id,
                models.OrgMembership.user_id == current_user.id,
                models.OrgMembership.status == "active",
            )
            .first()
        )
        if membership is None:
            raise HTTPException(
                status_code=403,
                detail="Not a member of this proposal's organization.",
            )

    # Snapshot rows, chronological.
    rows = (
        db.query(models.VoteSnapshot)
        .filter(models.VoteSnapshot.proposal_id == proposal.id)
        .order_by(models.VoteSnapshot.simulated_time.asc())
        .all()
    )

    # Phase 32 P2/P3 — when pre-voting visibility is off, hide
    # deliberation-phase snapshots from the chart. Snapshots are still
    # captured server-side; this only filters the GET response so the
    # chart's x-axis stays at voting_start (current behavior). When
    # ``show_votes_during_deliberation`` is on, all snapshots surface,
    # and the chart extends back to deliberation_start.
    from proposal_engagement_config import (
        resolve_show_votes_during_deliberation,
    )
    org_for_vis = (
        db.get(models.Organization, proposal.org_id)
        if proposal.org_id else None
    )
    show_delib = resolve_show_votes_during_deliberation(proposal, org_for_vis)
    if not show_delib and proposal.voting_start is not None:
        rows = [
            r for r in rows
            if r.simulated_time is not None
            and r.simulated_time >= proposal.voting_start
        ]

    # Downsample if needed.
    rows = _downsample_snapshots(rows, proposal)

    snapshots_out = [
        _build_snapshot_out(r, voting_method=proposal.voting_method)
        for r in rows
    ]

    srr_annotations = _build_srr_annotations(db, proposal)

    # Cache headers: closed proposals are immutable; voting proposals get
    # a short max-age since new snapshots accumulate every ~5min.
    if proposal.status in ("passed", "failed", "withdrawn", "unresolved"):
        response.headers["Cache-Control"] = "max-age=86400"
    else:
        response.headers["Cache-Control"] = "max-age=30"

    return TrajectoryResponse(
        proposal_id=proposal.id,
        voting_method=proposal.voting_method,
        voting_start=proposal.voting_start,
        voting_end=proposal.voting_end,
        snapshots=snapshots_out,
        srr_annotations=srr_annotations,
        # Phase 32 P3 — surface deliberation_start + visibility flag so
        # the frontend chart knows whether to extend its x-axis.
        deliberation_start=(
            proposal.deliberation_start if show_delib else None
        ),
        show_votes_during_deliberation=show_delib,
    )
