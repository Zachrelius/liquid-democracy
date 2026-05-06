import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
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
from org_config import get_default_proposal_thresholds, get_org_config
from permissions import can_see_votes
from polis_engine import eligible_viewers_for_polis
from role_permissions import has_permission as _has_permission


log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/proposals", tags=["proposals"])

STATUS_TRANSITIONS = {
    "draft": "deliberation",
    "deliberation": "voting",
    "voting": "passed",  # actual pass/fail determined at close; admin forces
}


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
    proposal: models.Proposal, db: Optional[Session] = None,
) -> schemas.ProposalOut:
    """Build the ProposalOut payload.

    `db` is optional; when provided, `linked_polises` is resolved with
    title/prompt/participation. When absent (existing call sites that
    pre-date Phase 9 don't pass it), `linked_polis_ids` is still
    returned as the raw list and `linked_polises` is None — frontend
    can choose to do its own resolution or treat absent as "didn't ask
    for the rich resolution".
    """
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
        created_at=proposal.created_at,
        updated_at=proposal.updated_at,
        topics=proposal.proposal_topics,
        options=proposal.options,
        sustained_majority_enabled=proposal.sustained_majority_enabled,
        sub_org_id=getattr(proposal, "sub_org_id", None),
        linked_polis_ids=proposal.linked_polis_ids,
        linked_polises=_build_linked_polises(db, proposal) if db is not None else None,
    )


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


def _validate_proposal_creation(body: schemas.ProposalCreate, org: Optional[models.Organization] = None):
    """Validate voting_method and options for proposal creation."""
    # Check org allowed_voting_methods. Ranked-choice in particular is
    # opt-in per org — return 403 (not 400) when the method is not enabled,
    # matching the Phase 7 spec.
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
            raise HTTPException(
                status_code=status_code,
                detail=f"Voting method '{body.voting_method}' is not allowed by this organization",
            )
    if body.voting_method == "binary":
        if body.options:
            raise HTTPException(
                status_code=400,
                detail="Binary proposals must not have options",
            )
        if body.num_winners != 1:
            raise HTTPException(
                status_code=400,
                detail="num_winners must be 1 for binary proposals",
            )
    elif body.voting_method == "approval":
        if len(body.options) < 2:
            raise HTTPException(
                status_code=400,
                detail="Approval proposals require at least 2 options",
            )
        if len(body.options) > 20:
            raise HTTPException(
                status_code=400,
                detail="Approval proposals may have at most 20 options",
            )
        seen_labels: set[str] = set()
        for opt in body.options:
            lower = opt.label.strip().lower()
            if lower in seen_labels:
                raise HTTPException(
                    status_code=400,
                    detail=f"Duplicate option label: {opt.label}",
                )
            seen_labels.add(lower)
        if body.num_winners != 1:
            raise HTTPException(
                status_code=400,
                detail="num_winners must be 1 for approval proposals",
            )
    elif body.voting_method == "ranked_choice":
        if len(body.options) < 2:
            raise HTTPException(
                status_code=400,
                detail="Ranked-choice proposals require at least 2 options",
            )
        if len(body.options) > 20:
            raise HTTPException(
                status_code=400,
                detail="Ranked-choice proposals may have at most 20 options",
            )
        seen_labels: set[str] = set()
        for opt in body.options:
            lower = opt.label.strip().lower()
            if lower in seen_labels:
                raise HTTPException(
                    status_code=400,
                    detail=f"Duplicate option label: {opt.label}",
                )
            seen_labels.add(lower)
        if body.num_winners < 1 or body.num_winners > len(body.options):
            raise HTTPException(
                status_code=400,
                detail="num_winners must be between 1 and the number of options",
            )


def _create_proposal_options(db: Session, proposal_id: str, options: list[schemas.OptionCreate]):
    """Create ProposalOption rows for an approval proposal."""
    for i, opt in enumerate(options):
        db.add(models.ProposalOption(
            proposal_id=proposal_id,
            label=opt.label.strip(),
            description=opt.description,
            display_order=i,
        ))
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
    label_method = "Approval" if proposal.voting_method == "approval" else "Ranked-choice"
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
):
    q = db.query(models.Proposal)
    if org_id:
        q = q.filter(models.Proposal.org_id == org_id)
    if status_filter:
        q = q.filter(models.Proposal.status == status_filter)
    if topic_id:
        q = q.join(models.ProposalTopic).filter(models.ProposalTopic.topic_id == topic_id)
    proposals = q.order_by(models.Proposal.created_at.desc()).all()
    return [_build_proposal_out(p) for p in proposals]


@router.post("", response_model=schemas.ProposalOut, status_code=status.HTTP_201_CREATED)
def create_proposal(
    body: schemas.ProposalCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
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

    # Phase 8 — global (non-org) proposals: per-proposal override is always
    # ignored at create time because there is no org config to honor it
    # against. Store as null.
    sustained_majority_enabled = None

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

    proposal = models.Proposal(
        title=body.title,
        body=body.body,
        author_id=current_user.id,
        voting_method=body.voting_method,
        num_winners=body.num_winners,
        pass_threshold=body.pass_threshold,
        quorum_threshold=body.quorum_threshold,
        sustained_majority_enabled=sustained_majority_enabled,
    )
    db.add(proposal)
    db.flush()

    for t in body.topics:
        db.add(models.ProposalTopic(
            proposal_id=proposal.id, topic_id=t.topic_id, relevance=t.relevance
        ))
    db.flush()

    if body.voting_method in ("approval", "ranked_choice") and body.options:
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
    return _build_proposal_out(proposal)


@router.get("/{proposal_id}", response_model=schemas.ProposalOut)
def get_proposal(proposal_id: str, db: Session = Depends(get_db)):
    return _build_proposal_out(_proposal_or_404(proposal_id, db))


@router.patch("/{proposal_id}", response_model=schemas.ProposalOut)
def update_proposal(
    proposal_id: str,
    body: schemas.ProposalUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    proposal = _proposal_or_404(proposal_id, db)

    if proposal.status not in ("draft", "deliberation"):
        raise HTTPException(status_code=400, detail="Only draft or deliberation proposals can be edited")
    if proposal.author_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Not the proposal author")

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

    if body.options is not None:
        if proposal.voting_method not in ("approval", "ranked_choice"):
            raise HTTPException(
                status_code=400,
                detail="Options can only be set on approval or ranked-choice proposals",
            )
        _validate_and_update_options(db, proposal, body.options)

    # Phase 8 — sustained-majority per-proposal override.
    # Validate against the org's `sustained_majority_per_proposal_override`
    # setting; only persist when the value actually changes so we don't emit
    # spurious audit events on no-op patches.
    if "sustained_majority_enabled" in body.model_fields_set:
        org = (
            db.get(models.Organization, proposal.org_id)
            if proposal.org_id else None
        )
        from sustained_majority_service import validate_per_proposal_override
        validate_per_proposal_override(body.sustained_majority_enabled, org)
        old_value = proposal.sustained_majority_enabled
        if old_value != body.sustained_majority_enabled:
            proposal.sustained_majority_enabled = body.sustained_majority_enabled
            log_audit_event(
                db,
                action=(
                    "proposal.sustained_majority_enabled"
                    if body.sustained_majority_enabled is True
                    else "proposal.sustained_majority_disabled"
                ),
                target_type="proposal",
                target_id=proposal.id,
                actor_id=current_user.id,
                details={
                    "old_value": old_value,
                    "new_value": body.sustained_majority_enabled,
                },
            )

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
    """
    topic_ids = [pt.topic_id for pt in proposal.proposal_topics]
    if not topic_ids:
        return False
    q = db.query(models.Delegation.id).filter(
        models.Delegation.delegate_id == user_id,
        models.Delegation.topic_id.in_(topic_ids),
    )
    return db.query(q.exists()).scalar() or False


def _has_delegated_away_for_proposal(
    db: Session, user_id: str, proposal: models.Proposal,
) -> bool:
    """Phase 13.3 — has ``user_id`` delegated their vote on ANY of this
    proposal's topics?

    Counts a row in ``delegations`` where ``delegator_id == user_id`` and
    ``topic_id`` is one of the proposal's topics. Topicless proposals
    treat all recipients as not-delegated (you_vote candidates).
    """
    topic_ids = [pt.topic_id for pt in proposal.proposal_topics]
    if not topic_ids:
        return False
    q = db.query(models.Delegation.id).filter(
        models.Delegation.delegator_id == user_id,
        models.Delegation.topic_id.in_(topic_ids),
    )
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


@router.post("/{proposal_id}/advance", response_model=schemas.ProposalOut)
def advance_proposal(
    proposal_id: str,
    body: schemas.AdvanceProposalRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    # Permissions: platform admin, org admin/owner, proposal author, or org
    # moderator (own proposals only). Moderators get 403 on others' proposals.
    proposal = _proposal_or_404(proposal_id, db)

    is_author = proposal.author_id == current_user.id
    is_platform_admin = current_user.is_admin
    is_org_admin_or_owner = False
    is_org_moderator = False
    if proposal.org_id:
        membership = db.query(models.OrgMembership).filter(
            models.OrgMembership.org_id == proposal.org_id,
            models.OrgMembership.user_id == current_user.id,
            models.OrgMembership.status == "active",
        ).first()
        if membership:
            # Phase 12 — admin/Steward via has_permission(...)
            # 'proposal.advance_phase' is the canonical gate; Steward retains
            # the bypass via D4 + the standard grant table (admin gets it).
            from role_permissions import has_permission as _has_permission
            from org_middleware import membership_role_system_key as _sk
            if _has_permission(
                db, current_user.id, proposal.org_id, "proposal.advance_phase"
            ):
                is_org_admin_or_owner = True
            elif _sk(membership) == "moderator":
                is_org_moderator = True

    if is_org_moderator and not is_author:
        raise HTTPException(status_code=403, detail="Moderators can only advance proposals they created")
    if not (is_author or is_platform_admin or is_org_admin_or_owner or is_org_moderator):
        raise HTTPException(status_code=403, detail="Not the proposal author or admin")

    next_status = STATUS_TRANSITIONS.get(proposal.status)
    if next_status is None:
        raise HTTPException(status_code=400, detail=f"Cannot advance from status '{proposal.status}'")

    old_status = proposal.status
    now = datetime.now(timezone.utc)

    if next_status == "deliberation":
        proposal.deliberation_start = now
    elif next_status == "voting":
        proposal.voting_start = now
        if body.voting_end:
            proposal.voting_end = body.voting_end
    elif next_status == "passed":
        tally = delegation_engine.compute_tally(proposal, db)
        if proposal.voting_method == "approval":
            # Approval proposals pass if quorum met and at least one option has votes
            if isinstance(tally, ApprovalTally) and tally.quorum_met(proposal.quorum_threshold) and tally.winners:
                next_status = "passed"
            else:
                next_status = "failed"
        elif proposal.voting_method == "ranked_choice":
            # RCV/STV passes if quorum met and at least one winner emerged
            if isinstance(tally, RCVTally) and tally.quorum_met(proposal.quorum_threshold) and tally.winners:
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

    return _build_proposal_out(proposal)


@router.get("/{proposal_id}/results", response_model=schemas.ProposalResults)
def get_results(proposal_id: str, db: Session = Depends(get_db)):
    proposal = _proposal_or_404(proposal_id, db)
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


@router.get("/{proposal_id}/my-vote", response_model=schemas.MyVoteStatus)
def my_vote_status(
    proposal_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    proposal = _proposal_or_404(proposal_id, db)
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

    # Identify public delegates for this proposal's topics
    pub_delegate_ids: set[str] = set()
    for pt in proposal.proposal_topics:
        profiles = db.query(models.DelegateProfile).filter(
            models.DelegateProfile.topic_id == pt.topic_id,
            models.DelegateProfile.is_active.is_(True),
        ).all()
        for p in profiles:
            pub_delegate_ids.add(p.user_id)

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

    delegators_to_me: set[str] = set()
    for d in db.query(models.Delegation).filter(
        models.Delegation.delegate_id == current_user.id,
    ).all():
        # Only reveal name if they delegate via a private follow relationship
        if d.delegator_id in private_follow_ids:
            delegators_to_me.add(d.delegator_id)

    # Resolve every user's vote
    vote_results: dict[str, Optional[object]] = {}
    for uid in user_map:
        vote_results[uid] = resolve_vote_pure(uid, ctx)

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
                    source=uid,
                    target=direct_delegate_id,
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
                            source=chain_src,
                            target=chain_tgt,
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
            id=uid,
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
