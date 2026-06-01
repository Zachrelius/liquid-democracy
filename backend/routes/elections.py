"""Phase 48 Stage 1 — Election HTTP routes.

Admin-direct open (D4 Stage 1 only — cosign triggers land in Stage 3).
Self-nominate + withdraw + list-candidates per D5.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _proposal_or_404(db: Session, proposal_id: str) -> models.Proposal:
    p = db.get(models.Proposal, proposal_id)
    if p is None:
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
    admin_membership: models.OrgMembership = Depends(require_org_admin),
):
    """Open an election for a specific title (D4 admin-direct trigger).

    Validates per D3: elections must be opted in at the org level.
    Validates per D4: the target title must have `fill_method` in
    'elected' or 'both'. Validates per D7/D8: incumbent (current
    title holder, if any) is NOT automatically nominated — they must
    self-declare during the nomination window.

    Creates a proposal flagged as an election + linked to the title.
    The proposal enters 'deliberation' status (the nomination window);
    voting opens via the existing /advance endpoint when the admin
    moves the proposal to 'voting'.

    Stage 1 uses 'binary' voting method for single-winner elections;
    Stage 2 generalizes to ranked_choice + num_winners > 1.
    """
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug,
    ).first()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    from elections import elections_enabled, title_is_electable

    if not elections_enabled(org):
        raise HTTPException(
            status_code=400,
            detail=(
                "Elections are not enabled for this organization. "
                "Set settings.elections.enabled = true to opt in."
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

    # Per D3 + 47-council-mode-rejection (mirrored here so the failure
    # surfaces at open time rather than at close time): a steward-
    # binding title cannot be elected in admin_council mode.
    from governance import mode_of, ADMIN_COUNCIL
    if title.bound_role == "steward" and mode_of(org) == ADMIN_COUNCIL:
        raise HTTPException(
            status_code=400,
            detail=(
                "Cannot open an election for a steward-binding title "
                "in admin_council mode — the org has no steward seat. "
                "Switch governance mode first."
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
        deliberation_days=body.deliberation_days,
        voting_days=body.voting_days,
        pass_threshold=org.settings.get("default_pass_threshold", 0.50) if org.settings else 0.50,
        quorum_threshold=org.settings.get("default_quorum_threshold", 0.40) if org.settings else 0.40,
        is_election=True,
        election_title_id=title.id,
        election_slate_mode=body.slate_mode,
    )
    db.add(proposal)
    db.flush()
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
            "trigger": "admin_direct",
            "deliberation_days": body.deliberation_days,
            "voting_days": body.voting_days,
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
            "voting_method": "binary",
            "is_election": True,
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
    proposal = _proposal_or_404(db, proposal_id)
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
    proposal = _proposal_or_404(db, proposal_id)
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
    proposal = _proposal_or_404(db, proposal_id)
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
