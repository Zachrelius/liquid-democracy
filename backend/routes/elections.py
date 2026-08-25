"""Phase 48 Stage 1 — Election HTTP routes.

Admin-direct open (D4 Stage 1 only — cosign triggers land in Stage 3).
Self-nominate + withdraw + list-candidates per D5.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

import auth as auth_utils
import models
import schemas
from audit_utils import log_audit_event
from database import get_db
from org_middleware import (
    get_org_context, require_org_admin, require_org_membership,
)


router = APIRouter(prefix="/api/orgs", tags=["elections"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class _OpenElectionBody(BaseModel):
    title_id: str
    body: str = ""
    deliberation_days: float = 3.0  # Nomination window
    voting_days: float = 7.0
    # Phase 48 Stage 2 — multi-winner + slate config (D9 + D10).
    # voting_method defaults to 'ranked_choice' so the existing
    # RCV/STV engine produces winners over per-candidate options.
    # num_winners defaults to 1 (single-holder election); the FE
    # picks higher values when the target title is multi-holder.
    voting_method: str = "ranked_choice"
    num_winners: int = 1
    slate_mode: str = "fill_vacancies"  # or 'refresh_slate'
    # Phase 48 Stage 3 — trigger source (D4). Default 'admin_direct'
    # so Stage 1+2 callers + tests are unchanged. 'member_cosign'
    # creates the election proposal in cosign-gathering state; it
    # advances to voting when the cosign threshold is met (Phase 46
    # path, unchanged).
    trigger: str = "admin_direct"
    # Phase 66a — multi-winner approval selection config for
    # approval-method elections. Same generalized shape as ordinary
    # proposals ({min_winners, max_winners, approval_threshold});
    # shape-validated by the shared Phase 66 validator below (422).
    # Approval-method only — the route 400s when combined with
    # ranked_choice/binary (num_winners owns those). NULL = legacy
    # single-winner election behavior, byte-for-byte.
    approval_winner_config: Optional[dict] = None
    # Phase 67 W1 — elections default to quorum 0 (plurality of those
    # who vote is the norm). An org that explicitly sets a quorum on a
    # leadership election means it: an under-quorum close fails and
    # seats NOTHING (incumbents stay, vacancies stay vacant). None →
    # the route applies the 0.0 default; 0..1 enforced (422 outside).
    quorum_threshold: Optional[float] = Field(None, ge=0.0, le=1.0)

    @field_validator("approval_winner_config")
    @classmethod
    def validate_approval_winner_config(
        cls, v: Optional[dict],
    ) -> Optional[dict]:
        return schemas._validate_approval_winner_config(v)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _proposal_or_404(
    db: Session, proposal_id: str, org_id: Optional[str] = None,
) -> models.Proposal:
    p = db.get(models.Proposal, proposal_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    # Phase 63 (security): bind the proposal to the org resolved from the
    # URL slug. Without this, a member of any org could act on another
    # org's election proposal (declare/withdraw candidacy, list the
    # candidate roster) because require_org_membership only validates
    # membership in the *slug's* org. 404 (not 403) to avoid confirming
    # the proposal exists, mirroring duplicate_flags.resolve_flag.
    if org_id is not None and p.org_id != org_id:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return p


def _require_election(proposal: models.Proposal) -> None:
    if not proposal.is_election:
        raise HTTPException(
            status_code=400,
            detail="Proposal is not an election.",
        )


def _require_nomination_window(proposal: models.Proposal) -> None:
    """Self-nominations are accepted during the nomination/gathering
    window — equivalent to the proposal's deliberation phase. Once
    voting opens, the candidate set is locked."""
    if proposal.status not in ("draft", "deliberation"):
        raise HTTPException(
            status_code=400,
            detail=(
                "Candidacy can only be declared/withdrawn during the "
                f"nomination window (status='{proposal.status}')."
            ),
        )


# ---------------------------------------------------------------------------
# Open an election (admin-direct trigger only this stage)
# ---------------------------------------------------------------------------

@router.post(
    "/{org_slug}/elections",
    response_model=schemas.ProposalOut,
    status_code=status.HTTP_201_CREATED,
)
def open_election(
    org_slug: str,
    body: _OpenElectionBody,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """Open an election for a specific title.

    Two trigger sources per D4 (controlled by
    ``settings.elections.trigger_sources``):
      * ``admin_direct`` — admin/steward direct trigger (Stage 1+2).
        Requires the caller to hold the admin role. Proposal enters
        ``deliberation`` (nomination window) immediately.
      * ``member_cosign`` (Stage 3) — any member opens a petition.
        Proposal enters cosign-gathering state; advances to nomination
        + voting when the cosign threshold is met (reuses Phase 46).

    Validates per D3 (elections enabled), D4 (title electable), D12
    partner (steward-binding council-mode allowed iff
    ``allow_elected_revert`` is on), and per-trigger source allowed.
    """
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug,
    ).first()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    from elections import (
        elections_enabled, title_is_electable,
        trigger_source_enabled, allow_elected_revert,
    )

    if not elections_enabled(org):
        raise HTTPException(
            status_code=400,
            detail=(
                "Elections are not enabled for this organization. "
                "Set settings.elections.enabled = true to opt in."
            ),
        )

    # Phase 48 Stage 3 + Phase 49 — validate trigger source per D4 /
    # Phase 49 D2. 'scheduled' is internal-only — the tick's
    # ``open_due_term_elections`` calls ``open_election_via_service``
    # (the in-process entry point) rather than this HTTP route, so an
    # external client can't open a scheduled election by passing
    # trigger='scheduled' through the API.
    if body.trigger not in ("admin_direct", "member_cosign"):
        raise HTTPException(
            status_code=400,
            detail=(
                "trigger must be 'admin_direct' or 'member_cosign'"
            ),
        )
    if not trigger_source_enabled(org, body.trigger):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Trigger source '{body.trigger}' is not enabled for "
                "this organization. Update "
                "settings.elections.trigger_sources to allow it."
            ),
        )
    # admin_direct trigger requires admin or steward role; member_cosign
    # is open to any active member (membership dep above).
    if body.trigger == "admin_direct":
        actor_role = None
        if membership.role_id is not None:
            role = db.get(models.Role, membership.role_id)
            actor_role = role.system_key if role is not None else None
        if actor_role not in ("admin", "steward"):
            raise HTTPException(
                status_code=403,
                detail=(
                    "Admin or steward role required to open an "
                    "admin-direct election."
                ),
            )

    title = db.get(models.OrgTitle, body.title_id)
    if title is None or title.org_id != org.id:
        raise HTTPException(status_code=404, detail="Title not found")
    if not title_is_electable(title):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Title '{title.name}' is not electable "
                f"(fill_method='{title.fill_method}'). Set the title's "
                "fill_method to 'elected' or 'both' first."
            ),
        )

    # Phase 47 council-mode rejection — loosened in Stage 3 for the
    # elected-revert path (D12 partner). The rejection still fires
    # UNLESS the org has explicitly opted in to elected revert via
    # ``settings.elections.allow_elected_revert``. When the opt-in is
    # on, the close→assign hook flips the mode atomically before
    # calling _apply_bound_role_for_assign, so Phase 47's check passes
    # at assignment time.
    from governance import mode_of, ADMIN_COUNCIL
    if title.bound_role == "steward" and mode_of(org) == ADMIN_COUNCIL:
        if not allow_elected_revert(org):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Cannot open an election for a steward-binding title "
                    "in admin_council mode unless "
                    "settings.elections.allow_elected_revert is enabled. "
                    "Enable the elected-revert opt-in or switch "
                    "governance mode first."
                ),
            )

    # Validate Stage 2 inputs.
    if body.voting_method not in ("binary", "approval", "ranked_choice"):
        raise HTTPException(
            status_code=400,
            detail="voting_method must be 'binary', 'approval', or 'ranked_choice'",
        )
    if body.num_winners < 1:
        raise HTTPException(
            status_code=400,
            detail="num_winners must be >= 1",
        )
    if body.slate_mode not in ("fill_vacancies", "refresh_slate"):
        raise HTTPException(
            status_code=400,
            detail="slate_mode must be 'fill_vacancies' or 'refresh_slate'",
        )
    # Multi-winner is only meaningful for multi-holder titles.
    if body.num_winners > 1 and title.cardinality_mode == "single":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Title '{title.name}' is single-holder; num_winners "
                "must be 1."
            ),
        )
    # Phase 66a — approval_winner_config wiring for approval-method
    # elections. The config owns the winner count for approval
    # elections; num_winners stays at its default (1) and is ignored
    # by the close hook on this path.
    if body.approval_winner_config is not None:
        if body.voting_method != "approval":
            raise HTTPException(
                status_code=400,
                detail=(
                    "approval_winner_config is only supported on "
                    "approval-method elections (num_winners governs "
                    f"'{body.voting_method}' elections)."
                ),
            )
        if body.num_winners != 1:
            raise HTTPException(
                status_code=400,
                detail=(
                    "num_winners must be 1 (the default) when "
                    "approval_winner_config is set — the config owns "
                    "the winner count for approval elections."
                ),
            )
        # Mirror the num_winners single-holder check: a config that can
        # seat more than one winner is incoherent on a single-holder
        # title.
        if title.cardinality_mode == "single" and (
            body.approval_winner_config.get("max_winners") != 1
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Title '{title.name}' is single-holder; "
                    "approval_winner_config.max_winners must be 1."
                ),
            )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    proposal = models.Proposal(
        title=f"Election: {title.name}",
        body=body.body or (
            f"Nominations open for the '{title.name}' title. "
            "Members may self-nominate during the nomination window."
        ),
        author_id=current_user.id,
        org_id=org.id,
        voting_method=body.voting_method,
        num_winners=body.num_winners,
        status="deliberation",
        deliberation_start=now,
        deliberation_end=now + timedelta(days=float(body.deliberation_days)),
        deliberation_days=body.deliberation_days,
        voting_days=body.voting_days,
        pass_threshold=org.settings.get("default_pass_threshold", 0.50) if org.settings else 0.50,
        # Phase 67 W1 — elections default to quorum 0, NOT the org's
        # proposal default. Quorum now gates seat installation; the
        # plurality-of-those-who-vote norm requires 0 unless the
        # opener explicitly sets one.
        quorum_threshold=(
            body.quorum_threshold
            if body.quorum_threshold is not None else 0.0
        ),
        is_election=True,
        election_title_id=title.id,
        election_slate_mode=body.slate_mode,
        election_trigger=body.trigger,
        # Phase 66a — NULL for non-approval methods (enforced above);
        # NULL = legacy single-winner election behavior.
        approval_winner_config=body.approval_winner_config,
    )
    db.add(proposal)
    db.flush()

    # Phase 48 Stage 3 — cosign-trigger: stamp cosign markers + insert
    # the author's implicit first signature. Threshold-met advances
    # this proposal to voting via the existing Phase 46 worker (no
    # changes to the worker needed — election proposals look like any
    # other cosign-gated proposal from the worker's POV).
    if body.trigger == "member_cosign":
        from cosign import init_cosign_gated_proposal
        init_cosign_gated_proposal(db, proposal, org)

    log_audit_event(
        db,
        action="election.opened",
        target_type="proposal",
        target_id=proposal.id,
        actor_id=current_user.id,
        details={
            "org_id": org.id,
            "title_id": title.id,
            "title_name": title.name,
            "bound_role": title.bound_role,
            "trigger": body.trigger,
            "deliberation_days": body.deliberation_days,
            "voting_days": body.voting_days,
            "cosign_gated": body.trigger == "member_cosign",
        },
        ip_address=request.client.host if request.client else None,
    )
    log_audit_event(
        db,
        action="proposal.created",
        target_type="proposal",
        target_id=proposal.id,
        actor_id=current_user.id,
        details={
            "title": proposal.title,
            "org_id": org.id,
            "voting_method": body.voting_method,
            "is_election": True,
            "is_cosign_gated": body.trigger == "member_cosign",
        },
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(proposal)

    from routes.proposals import _build_proposal_out
    return _build_proposal_out(proposal, db, viewer_id=current_user.id)


# ---------------------------------------------------------------------------
# Candidacy endpoints (D5)
# ---------------------------------------------------------------------------

@router.get("/{org_slug}/elections/{proposal_id}/candidacies")
def list_candidacies(
    org_slug: str,
    proposal_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    proposal = _proposal_or_404(db, proposal_id, org_id=membership.org_id)
    _require_election(proposal)
    from elections import active_candidacies
    rows = active_candidacies(db, proposal.id)
    out = []
    for r in rows:
        user = db.get(models.User, r.user_id)
        out.append({
            "user_id": r.user_id,
            "display_name": user.display_name if user else None,
            "username": user.username if user else None,
            "declared_at": r.declared_at.isoformat(),
        })
    return out


@router.post(
    "/{org_slug}/elections/{proposal_id}/candidacies",
    status_code=status.HTTP_201_CREATED,
)
def declare_my_candidacy(
    org_slug: str,
    proposal_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """Self-nominate per D5. Only the caller can declare for themselves
    — there is no draft-nomination of others. Must be in the
    nomination window (proposal.status in 'draft'/'deliberation')."""
    proposal = _proposal_or_404(db, proposal_id, org_id=membership.org_id)
    _require_election(proposal)
    _require_nomination_window(proposal)

    from elections import declare_candidacy
    row = declare_candidacy(db, proposal, current_user.id)
    log_audit_event(
        db,
        action="election.candidate_declared",
        target_type="proposal",
        target_id=proposal.id,
        actor_id=current_user.id,
        details={
            "proposal_id": proposal.id,
            "user_id": current_user.id,
            "title_id": proposal.election_title_id,
        },
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {"status": "declared", "user_id": current_user.id}


@router.delete(
    "/{org_slug}/elections/{proposal_id}/candidacies",
    status_code=status.HTTP_204_NO_CONTENT,
)
def withdraw_my_candidacy(
    org_slug: str,
    proposal_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    proposal = _proposal_or_404(db, proposal_id, org_id=membership.org_id)
    _require_election(proposal)
    _require_nomination_window(proposal)

    from elections import withdraw_candidacy
    removed = withdraw_candidacy(db, proposal, current_user.id)
    if not removed:
        raise HTTPException(
            status_code=404, detail="No active candidacy to withdraw.",
        )
    log_audit_event(
        db,
        action="election.candidate_withdrawn",
        target_type="proposal",
        target_id=proposal.id,
        actor_id=current_user.id,
        details={
            "proposal_id": proposal.id,
            "user_id": current_user.id,
        },
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
