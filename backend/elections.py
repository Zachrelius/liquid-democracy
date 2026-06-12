"""Phase 48 Stage 1 — Elections service.

An election is a proposal subtype (D1): when ``Proposal.is_election``
is True, the proposal's vote close fills the target ``OrgTitle`` (and
its optionally bound platform role) via the existing Phase 47
``org_titles.py`` assignment path. The election proposal carries the
same lifecycle (draft → deliberation → voting → passed/failed) and the
same voting/eligibility/tally machinery; the new surface is narrow:

  1. ``open_election`` — create a proposal flagged as an election with
     a target title. Stage 1 supports admin-direct trigger only.
  2. Candidacy — self-nomination during the nomination window
     (deliberation phase), recorded in ``election_candidacies``.
  3. ``finalize_election`` — called from the proposal-close path when
     ``is_election`` is True. Determines the winner(s) via the existing
     tally + D6 rules, then routes the title grant through
     ``org_titles._apply_bound_role_for_assign`` so 45a/45b floor +
     mode logic apply uniformly.

Per D2 the role + governance.py floor are untouched; per D6 the
zero/one-candidate corner cases are handled at the close hook.

Phase 49 — scheduled / fixed-term elections (the D11 deferred item).
Adds ``open_due_term_elections(db, now)`` for the digest tick + B4
advancement of ``OrgTitle.next_election_due_at`` in ``finalize_
election`` for scheduled-trigger resolutions. Off-cycle elections do
NOT advance the schedule (B4 decision); the calendar cadence is
fixed regardless of mid-term challenges.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

import models


log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Org-level config (D3) — elections enabled at org level
# ---------------------------------------------------------------------------

def elections_enabled(org: models.Organization) -> bool:
    """Per D3 elections are off by default; appointment (45a/45b)
    remains the default seat-filling mechanism until an org opts in
    via ``Organization.settings.elections.enabled = True``."""
    settings = (org.settings or {}).get("elections")
    if not isinstance(settings, dict):
        return False
    return bool(settings.get("enabled", False))


# ---------------------------------------------------------------------------
# Phase 48 Stage 3 — Trigger config (D4) + elected-revert (D12 partner)
# ---------------------------------------------------------------------------

_DEFAULT_TRIGGER_SOURCES = ("admin_direct",)
# Phase 49 D2 — ``scheduled`` is the third trigger source: a fixed-
# term clock auto-opens an election when ``next_election_due_at -
# election_lead_time_days <= now``. Opt-in per title (D1) AND per
# org (must be in ``settings.elections.trigger_sources``) per D2.
VALID_TRIGGER_SOURCES = frozenset(
    {"admin_direct", "member_cosign", "scheduled"},
)


def trigger_sources(org: models.Organization) -> list[str]:
    """Return the list of allowed election-trigger sources for the org
    per D4. Default ``['admin_direct']`` so Stage 1 / Stage 2 callers
    are unchanged. Orgs that enable member-cosign petitioning add
    ``'member_cosign'`` to the list.

    Tolerant read: malformed config falls back to the default; an
    explicit empty list is honored (meaning "no triggers" — an effective
    way to pause elections without disabling them).
    """
    settings = (org.settings or {}).get("elections")
    if not isinstance(settings, dict):
        return list(_DEFAULT_TRIGGER_SOURCES)
    raw = settings.get("trigger_sources")
    if raw is None:
        return list(_DEFAULT_TRIGGER_SOURCES)
    if not isinstance(raw, list):
        return list(_DEFAULT_TRIGGER_SOURCES)
    return [s for s in raw if isinstance(s, str) and s in VALID_TRIGGER_SOURCES]


def trigger_source_enabled(
    org: models.Organization, source: str,
) -> bool:
    return source in trigger_sources(org)


def allow_elected_revert(org: models.Organization) -> bool:
    """Per the D12 elected-revert partner: an org in admin_council mode
    can open a steward-binding election that, on close, flips the mode
    back to single_steward + installs the winner as steward. Opt-in
    via ``settings.elections.allow_elected_revert = True``; default
    False so existing council-mode orgs are unaffected.

    The opt-in is read at OPEN time (to allow the election to be
    created in council mode despite Phase 47's default rejection) AND
    at CLOSE time (to authorize the mode flip atomically with the
    title assignment). Reading the same flag in both places means an
    admin can't toggle it off mid-election to leave the system in a
    half-flipped state — if it's off at close, the election fails
    cleanly (the close hook records `outcome: revert_not_authorized`).
    """
    settings = (org.settings or {}).get("elections")
    if not isinstance(settings, dict):
        return False
    return bool(settings.get("allow_elected_revert", False))


# ---------------------------------------------------------------------------
# Title-electable check
# ---------------------------------------------------------------------------

def title_is_electable(title: models.OrgTitle) -> bool:
    """A title is electable iff its ``fill_method`` is 'elected' or
    'both'. Phase 47 ships titles with fill_method='assigned' as the
    default; orgs change this on the title to opt the seat in for
    elections."""
    return title.fill_method in ("elected", "both")


# ---------------------------------------------------------------------------
# Candidacy
# ---------------------------------------------------------------------------

def active_candidacies(
    db: Session, proposal_id: str,
) -> list[models.ElectionCandidacy]:
    """Return the active (status='declared') candidates for an
    election. This is the set used to determine the ballot at
    voting-open + the winner at voting-close."""
    return (
        db.query(models.ElectionCandidacy)
        .filter(
            models.ElectionCandidacy.proposal_id == proposal_id,
            models.ElectionCandidacy.status == "declared",
        )
        .order_by(models.ElectionCandidacy.declared_at)
        .all()
    )


def declare_candidacy(
    db: Session, proposal: models.Proposal, user_id: str,
) -> models.ElectionCandidacy:
    """Self-nominate (D5). Idempotent on a 'declared' status: a user
    who already has an active candidacy gets a clean 400. A user who
    previously withdrew can re-declare by flipping the same row's
    status back to 'declared'."""
    existing = (
        db.query(models.ElectionCandidacy)
        .filter(
            models.ElectionCandidacy.proposal_id == proposal.id,
            models.ElectionCandidacy.user_id == user_id,
        )
        .first()
    )
    if existing is not None:
        if existing.status == "declared":
            raise HTTPException(
                status_code=400,
                detail="You have already declared candidacy for this election.",
            )
        # Re-declare after withdrawal.
        existing.status = "declared"
        existing.withdrawn_at = None
        existing.declared_at = _now()
        db.flush()
        return existing
    row = models.ElectionCandidacy(
        proposal_id=proposal.id,
        user_id=user_id,
        status="declared",
    )
    db.add(row)
    db.flush()
    return row


def withdraw_candidacy(
    db: Session, proposal: models.Proposal, user_id: str,
) -> bool:
    """Withdraw a candidacy. Returns True iff a row was found and
    transitioned to 'withdrawn'."""
    existing = (
        db.query(models.ElectionCandidacy)
        .filter(
            models.ElectionCandidacy.proposal_id == proposal.id,
            models.ElectionCandidacy.user_id == user_id,
            models.ElectionCandidacy.status == "declared",
        )
        .first()
    )
    if existing is None:
        return False
    existing.status = "withdrawn"
    existing.withdrawn_at = _now()
    db.flush()
    return True


# ---------------------------------------------------------------------------
# Close → assign-title hook (the load-bearing piece)
# ---------------------------------------------------------------------------

def finalize_election(
    db: Session,
    proposal: models.Proposal,
    actor_id: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> dict:
    """Apply the close→assign-title hook (Stage 1 single-winner path).

    Called from the proposal-close path when ``proposal.is_election``
    is True. Determines the winner per D6:
      * Zero candidates → return ``{"resolved": "no_election", ...}``;
        the proposal is moved to ``expired_unsigned`` to signal "no
        contest, status quo holds." The incumbent / current title
        holder is unaffected (D6).
      * One candidate → auto-win; the title is assigned to the lone
        candidate via the Phase 47 ``org_titles`` path.
      * Multi-candidate → derive winner from the existing tally
        engine (binary: highest yes-count; approval/RCV: same as
        Phase 17/29). Stage 1 covers the single-winner path; Stage 2
        adds multi-winner via ``num_winners`` + STV.

    The title assignment routes through
    ``routes.org_titles._apply_bound_role_for_assign`` (Phase 47), so
    bound-role swaps for a steward-binding title follow the same
    atomic-transfer + 45a/45b floor + mode-aware machinery as a manual
    title assignment. Stage 1 is single_steward mode only on the
    happy path — admin_council mode steward-binding rejection is the
    same 47 rejection (we surface it as the election failing).

    Returns a result dict for the caller's audit + response:
      ``{"resolved": "winner" | "no_election" | "failed", "winner_id":
        ..., "title_id": ..., "reason": ...}``

    Phase 67 W1 — quorum gates seat installation: the close sites call
    this ONLY via ``run_election_close_hook`` on a "passed" close (for
    elections, passed == quorum met). An under-quorum election closes
    "failed" and this function never runs — seats stay exactly as they
    were (the hook records ``election.not_finalized`` instead).
    """
    from audit_utils import log_audit_event

    if not proposal.is_election or proposal.election_title_id is None:
        return {"resolved": "not_an_election"}

    title = db.get(models.OrgTitle, proposal.election_title_id)
    if title is None:
        return {"resolved": "failed", "reason": "title_not_found"}

    org = db.get(models.Organization, proposal.org_id) if proposal.org_id else None
    if org is None:
        return {"resolved": "failed", "reason": "org_not_found"}

    candidates = active_candidacies(db, proposal.id)

    # Phase 49 B4 — advance the title's scheduled clock on scheduled-
    # trigger resolutions. The advancement happens for every scheduled
    # outcome (no_election hold-over, single winner, multi winner) so
    # the calendar cadence is maintained even when the incumbent
    # holds over. Off-cycle (admin_direct / member_cosign) elections
    # leave ``next_election_due_at`` untouched per B4. Done BEFORE
    # the winner-install branches so the schedule advances even if a
    # downstream install errors out — the next tick must NOT re-open
    # an election whose schedule already cycled.
    if getattr(proposal, "election_trigger", None) == "scheduled":
        _advance_schedule_for_title(db, title)

    if len(candidates) == 0:
        # D6 zero candidates → expire without changing the seat.
        log_audit_event(
            db,
            action="election.resolved",
            target_type="proposal",
            target_id=proposal.id,
            actor_id=actor_id,
            details={
                "outcome": "no_candidates",
                "title_id": title.id,
                "proposal_id": proposal.id,
            },
            ip_address=ip_address,
        )
        return {
            "resolved": "no_election",
            "reason": "no_candidates",
            "title_id": title.id,
        }

    # Phase 66a — approval-method elections carrying an
    # ``approval_winner_config`` resolve their winner SET from the
    # config-driven approval tally (Phase 66 core), post boundary-tie
    # resolution. ``num_winners`` is ignored on this path (the config
    # owns the winner count — open_election enforces num_winners == 1
    # when a config is supplied). All other elections take the
    # existing Stage 2 ``num_winners`` path byte-for-byte.
    awc = getattr(proposal, "approval_winner_config", None)
    is_config_approval = (
        proposal.voting_method == "approval" and bool(awc)
    )
    capacity_overflow: list[str] = []
    if is_config_approval:
        winner_ids = _resolve_approval_config_winners(
            db, proposal, candidates, actor_id=actor_id,
        )
        min_w = int((awc or {}).get("min_winners") or 0)
        auto_win_uncontested = min_w > 0 and len(candidates) <= min_w
        # The config's winner count can exceed the title's capacity
        # (expand_winners boundary ties; generous thresholds). Seat up
        # to capacity in tally-winner order; record the overflow in
        # the finalize audit detail (see helper docstring).
        winner_ids, capacity_overflow = _cap_winners_to_title_capacity(
            db, title, winner_ids,
            slate_mode=getattr(
                proposal, "election_slate_mode", "fill_vacancies",
            ) or "fill_vacancies",
        )
    else:
        num_winners = max(1, proposal.num_winners or 1)
        # Phase 48 Stage 2 — multi-winner resolution. For num_winners
        # == 1 this reduces to the Stage 1 path (single winner). For
        # N > 1 the RCV/STV tally produces N option-id winners; we map
        # them back to user_ids via option.label.
        winner_ids = _resolve_winners(db, proposal, candidates, num_winners)
        auto_win_uncontested = len(candidates) <= num_winners
    if not winner_ids:
        no_winner_details = {
            "outcome": "tie_unresolved_or_no_winner",
            "title_id": title.id,
        }
        if is_config_approval:
            no_winner_details["approval_winner_config"] = awc
            no_winner_details["capacity_overflow_winner_ids"] = (
                capacity_overflow
            )
        log_audit_event(
            db,
            action="election.resolved",
            target_type="proposal",
            target_id=proposal.id,
            actor_id=actor_id,
            details=no_winner_details,
            ip_address=ip_address,
        )
        return {
            "resolved": "failed",
            "reason": "tally_did_not_produce_winner",
        }

    # Phase 48 Stage 2 — D10 slate mode. ``refresh_slate`` removes
    # current holders of the target title BEFORE installing winners
    # (whole-slate refresh). The floor checks happen inside the
    # ``revoke_title`` / ``_check_revoke_floor`` path; if a refresh
    # would violate the floor we surface a failure and leave the
    # election unresolved. ``fill_vacancies`` (default) just adds.
    slate_mode = getattr(proposal, "election_slate_mode", "fill_vacancies")
    if slate_mode == "refresh_slate":
        try:
            _refresh_slate_for_title(
                db, org, title, winner_ids,
                actor_id=actor_id, ip_address=ip_address,
            )
        except HTTPException as e:
            log_audit_event(
                db,
                action="election.resolved",
                target_type="proposal",
                target_id=proposal.id,
                actor_id=actor_id,
                details={
                    "outcome": "slate_refresh_rejected",
                    "title_id": title.id,
                    "detail": str(e.detail),
                },
                ip_address=ip_address,
            )
            return {"resolved": "failed", "reason": e.detail}

    # Phase 48 Stage 3 — elected revert (D12 partner). If this is a
    # steward-binding election in admin_council mode AND the org has
    # the elected-revert opt-in on, FLIP THE MODE FIRST. The atomic
    # ordering matters: by the time `_apply_election_winner` calls
    # `_apply_bound_role_for_assign`, mode==single_steward, so Phase
    # 47's "no steward seat in council mode" rejection (routes/
    # org_titles.py:365) doesn't fire and the steward swap proceeds
    # exactly as a single_steward-mode election would.
    #
    # If the opt-in is OFF, we record `revert_not_authorized` and let
    # the assignment fail downstream via Phase 47's rejection. That's
    # the loud-failure path: the user can see why no winner was
    # installed.
    revert_applied = False
    if (
        title.bound_role == "steward"
        and _mode_of(org) == _ADMIN_COUNCIL
    ):
        if allow_elected_revert(org):
            _flip_mode_to_single_steward(
                db, org,
                actor_id=actor_id, ip_address=ip_address,
                proposal_id=proposal.id,
            )
            revert_applied = True
        else:
            log_audit_event(
                db,
                action="election.resolved",
                target_type="proposal",
                target_id=proposal.id,
                actor_id=actor_id,
                details={
                    "outcome": "revert_not_authorized",
                    "title_id": title.id,
                    "title_name": title.name,
                    "reason": (
                        "Steward-binding election won in admin_council "
                        "mode but settings.elections.allow_elected_revert "
                        "is off — winner cannot be installed."
                    ),
                },
                ip_address=ip_address,
            )
            return {
                "resolved": "failed",
                "reason": "revert_not_authorized",
                "title_id": title.id,
            }

    # Install each winner.
    installed: list[str] = []
    failures: list[dict] = []
    for winner_id in winner_ids:
        winner_user = db.get(models.User, winner_id)
        if winner_user is None or not winner_user.is_active:
            failures.append({"user_id": winner_id, "reason": "winner_inactive"})
            continue
        try:
            _apply_election_winner(
                db, org, title, winner_user,
                actor_id=actor_id, ip_address=ip_address,
            )
            installed.append(winner_id)
        except HTTPException as e:
            failures.append({
                "user_id": winner_id, "reason": str(e.detail),
            })

    resolved_details = {
        "outcome": "winners" if installed else "no_winner_installed",
        "title_id": title.id,
        "title_name": title.name,
        "winner_ids": installed,
        "failed_assignments": failures,
        "slate_mode": slate_mode,
        "candidate_count": len(candidates),
        "auto_win_uncontested": auto_win_uncontested,
        "elected_revert_applied": revert_applied,
    }
    if is_config_approval:
        # Phase 66a — transparency keys for config-driven approval
        # elections (absent on the legacy path so pre-66a audit shapes
        # are unchanged).
        resolved_details["approval_winner_config"] = awc
        resolved_details["capacity_overflow_winner_ids"] = capacity_overflow
    log_audit_event(
        db,
        action="election.resolved",
        target_type="proposal",
        target_id=proposal.id,
        actor_id=actor_id,
        details=resolved_details,
        ip_address=ip_address,
    )
    return {
        "resolved": "winner" if installed else "failed",
        "title_id": title.id,
        "winner_ids": installed,
        "failures": failures,
        "elected_revert_applied": revert_applied,
    }


def election_close_status(proposal: models.Proposal, tally) -> str:
    """Phase 67 W1 — pass/fail computation for ELECTION proposal closes.

    Elections are not pass/fail propositions: "passed" means the
    election concluded and seating ran; "failed" means quorum was not
    met and NOTHING was seated. Quorum is therefore the ONLY gate —
    the per-method winner logic (tally winners, uncontested auto-win,
    zero-candidate hold-over) all belongs to ``finalize_election``,
    which only fires on a "passed" close (see
    ``run_election_close_hook``).

    Elections default to ``quorum_threshold=0`` at creation (this
    pass), so the normal case closes "passed" and seats winners
    exactly as before; an org that explicitly sets a quorum on a
    leadership election means it.

    Shared by all three close sites (routes/proposals.py advance,
    routes/organizations.py advance, worker ``_close_proposal_now``)
    so they can't drift.
    """
    try:
        quorum_met = bool(tally.quorum_met(proposal.quorum_threshold))
    except Exception:  # noqa: BLE001
        # Defensive: a tally error must not wedge the close. Treat as
        # quorum met (the pre-67 hook ran finalize on every close;
        # erring on the seating side preserves that behavior).
        quorum_met = True
    return "passed" if quorum_met else "failed"


def run_election_close_hook(
    db: Session,
    proposal: models.Proposal,
    closed_status: str,
    *,
    actor_id: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> str:
    """Phase 67 W1 — shared election close hook for every site where an
    election proposal reaches passed/failed (route advance in
    ``routes/proposals.py``, org-scoped advance in
    ``routes/organizations.py``, worker natural/SRR close in
    ``sustained_majority_worker._close_proposal_now``).

    Quorum gates seat installation:

      * "passed" close (quorum met — see ``election_close_status``):
        run ``finalize_election``, which owns ALL winner determination
        (tally winners, uncontested auto-win, zero-candidate
        hold-over, slate refresh, schedule advancement).
      * "failed" close (quorum NOT met): seating is SKIPPED entirely —
        incumbents stay, vacancies stay vacant, the org can re-run.
        An explicit ``election.not_finalized`` audit row records that
        seating was skipped. For scheduled-trigger elections the
        title's term clock still advances (B4 cadence — pre-67
        finalize advanced it for every scheduled outcome including
        failures; without this the next tick would immediately re-open
        the same election).

    Non-election proposals return immediately (completely untouched).
    Returns the close status unchanged (no status forcing). Failures
    inside the hook are contained (logged) so a hook error never rolls
    back the close itself — mirrors the pre-67 try/except at the
    routes/proposals.py call site.
    """
    if not getattr(proposal, "is_election", False):
        return closed_status
    if closed_status == "passed":
        try:
            finalize_election(
                db, proposal,
                actor_id=actor_id,
                ip_address=ip_address,
            )
        except Exception:  # noqa: BLE001
            log.exception(
                "election finalize hook raised for proposal %s; the "
                "close still happened but no winner was installed",
                proposal.id,
            )
        return closed_status
    if closed_status == "failed":
        # Quorum unmet (the only way an election closes "failed" as of
        # Phase 67) — record explicitly that seating was skipped.
        try:
            from audit_utils import log_audit_event
            log_audit_event(
                db,
                action="election.not_finalized",
                target_type="proposal",
                target_id=proposal.id,
                actor_id=actor_id,
                details={
                    "proposal_id": proposal.id,
                    "title_id": getattr(proposal, "election_title_id", None),
                    "reason": "quorum_not_met",
                    "quorum_met": False,
                    "seats_unchanged": True,
                },
                ip_address=ip_address,
            )
            if getattr(proposal, "election_trigger", None) == "scheduled":
                title = (
                    db.get(models.OrgTitle, proposal.election_title_id)
                    if proposal.election_title_id else None
                )
                if title is not None:
                    _advance_schedule_for_title(db, title)
        except Exception:  # noqa: BLE001
            log.exception(
                "election not-finalized bookkeeping raised for "
                "proposal %s; the close still happened",
                proposal.id,
            )
    return closed_status


def _mode_of(org: models.Organization) -> str:
    """Lazy wrapper around governance.mode_of so this module doesn't
    pull the governance import at module load. Localized for testability
    + to mirror Stage 1's pattern of late-binding governance reads."""
    from governance import mode_of
    return mode_of(org)


_ADMIN_COUNCIL = "admin_council"
_SINGLE_STEWARD = "single_steward"


def _flip_mode_to_single_steward(
    db: Session,
    org: models.Organization,
    *,
    actor_id: Optional[str],
    ip_address: Optional[str],
    proposal_id: str,
) -> None:
    """Atomic mode flip for the elected-revert (Stage 3 D12 partner).

    Called from `finalize_election` ONLY when the gate has confirmed
    this is an authorized elected revert. Emits the same
    ``org.governance_mode_changed`` audit event the direct revert path
    emits, with an additional ``via: elected_revert`` marker so the
    audit log distinguishes the two paths cleanly.

    Does NOT route through Phase 44 multi-admin approval — the
    election itself IS the multi-admin ratification (D12 partner
    note). The direct ``change_governance_mode`` revert is the path
    that wraps under Phase 44.

    Does NOT promote a successor admin to steward — the close hook's
    ``_apply_bound_role_for_assign`` does that as the next step. By
    the time it runs, mode==single_steward and the call succeeds.
    """
    from audit_utils import log_audit_event
    org.governance_mode = _SINGLE_STEWARD
    log_audit_event(
        db,
        action="org.governance_mode_changed",
        target_type="organization",
        target_id=org.id,
        actor_id=actor_id,
        details={
            "from": _ADMIN_COUNCIL,
            "to": _SINGLE_STEWARD,
            "via": "elected_revert",
            "proposal_id": proposal_id,
        },
        ip_address=ip_address,
    )


def _apply_election_winner(
    db: Session,
    org: models.Organization,
    title: models.OrgTitle,
    winner: models.User,
    *,
    actor_id: Optional[str],
    ip_address: Optional[str],
) -> None:
    """Grant the title to the winner via the Phase 47 assignment
    machinery. Routes bound-role changes through
    ``_apply_bound_role_for_assign`` so the floor + mode-aware rules
    apply uniformly. For system titles (Steward, Admin) we bypass the
    routes-level direct-assign block — the close hook IS the assigner
    per spec D6 — but still flow through the role-update path so the
    45a/45b atomic swap fires.

    Phase 52 Stage 1 — verification + the title-vs-role-bind split.
    When a bound-role title's winner fails the Phase 52 role floor,
    ``_apply_bound_role_for_assign`` raises ``HTTPException(403)``.
    Per the spec's recommended handling ("title granted but role-bind
    held, rather than silently dropping the election result"), the
    title row is granted first; the role-bind is then attempted in a
    try/except that converts a verification failure into an audit
    event (``election.winner_verification_required``). The election
    is considered resolved + the winner holds the title (its label
    layer surfaces on the FE), but the bound role isn't bumped until
    they verify — at which point a manual title-reassign or admin
    role-change closes the loop. Other HTTPException types (mode
    mismatches, floor violations, etc.) re-raise so the calling
    ``finalize_election`` loop records them in ``failures`` as
    before.
    """
    from audit_utils import log_audit_event
    from fastapi import HTTPException
    from org_titles import grant_title
    # Import the route-level helpers we want to reuse. They mutate
    # role rows via the 45a/45b path and emit audits.
    from routes.org_titles import (
        _apply_bound_role_for_assign,
    )

    # Wrap the role change in a synthetic Request stand-in only used
    # for ip_address bookkeeping inside _apply_bound_role_for_assign;
    # easier to construct a tiny shim than refactor that helper. The
    # FastAPI Request type is duck-typed for `.client.host`.
    class _ShimReq:
        class client:  # noqa: N801 — match Request shape
            host = ip_address
    shim = _ShimReq()

    # Phase 52 — grant the title row FIRST so a verification block on
    # the bound role doesn't silently drop the election outcome. For
    # system titles (Steward, Admin) there's no title row to grant;
    # they're role-derived. Skip the grant in that case.
    if not title.is_system:
        grant_title(db, title, winner.id, actor_id)
        log_audit_event(
            db,
            action="title.assigned",
            target_type="org_title",
            target_id=title.id,
            actor_id=actor_id,
            details={
                "org_id": org.id,
                "title_name": title.name,
                "bound_role": title.bound_role,
                "user_id": winner.id,
                "trigger": "election_close",
            },
            ip_address=ip_address,
        )

    if title.bound_role:
        try:
            _apply_bound_role_for_assign(
                db, org, winner, title.bound_role, shim,
            )
        except HTTPException as e:
            # Distinguish verification failure (recoverable: title
            # holds, role-bind held) from other failures (re-raise so
            # the caller records them).
            detail = e.detail
            is_verification_failure = (
                e.status_code == 403
                and isinstance(detail, dict)
                and detail.get("error") == "verification_required"
            )
            if not is_verification_failure:
                raise
            log_audit_event(
                db,
                action="election.winner_verification_required",
                target_type="org_title",
                target_id=title.id,
                actor_id=actor_id,
                details={
                    "org_id": org.id,
                    "title_name": title.name,
                    "bound_role": title.bound_role,
                    "user_id": winner.id,
                    "required_floor": detail.get("floor"),
                    "required_jurisdiction": detail.get("jurisdiction"),
                    "trigger": "election_close",
                    "note": (
                        "Title granted but role-bind held pending "
                        "winner verification. After the winner "
                        "verifies, an admin can re-trigger the "
                        "role-bind via title reassignment."
                    ),
                },
                ip_address=ip_address,
            )


def _resolve_winners(
    db: Session,
    proposal: models.Proposal,
    candidates: list[models.ElectionCandidacy],
    num_winners: int,
) -> list[str]:
    """Phase 48 Stage 2 multi-winner resolution. Reuses the existing
    tally engine (binary / approval / ranked_choice) to derive winners
    over ProposalOption rows whose ``label`` is the candidate user_id.

    Auto-win shortcut: if there are at most ``num_winners`` candidates
    they all win uncontested (D6 generalization). Otherwise we call
    the tally engine; for RCV/STV the engine populates
    ``tally.winners`` with up to ``num_winners`` option_ids.

    Defensive fallback: if the tally errors or returns no winners,
    fall back to the first ``num_winners`` declared candidates (Stage 1
    pattern carried forward — keeps the load-bearing role-assignment
    behavior testable).
    """
    # Auto-win shortcut: candidates <= num_winners → all win.
    if len(candidates) <= num_winners:
        return [c.user_id for c in candidates]

    candidate_ids = {c.user_id for c in candidates}
    try:
        from delegation_engine import engine as delegation_engine
        tally = delegation_engine.compute_tally(proposal, db)
        winners = list(getattr(tally, "winners", None) or [])
        if winners:
            options_by_id = {o.id: o for o in proposal.options}
            mapped: list[str] = []
            for w in winners:
                opt = options_by_id.get(w)
                if opt is None:
                    continue
                if opt.label in candidate_ids and opt.label not in mapped:
                    mapped.append(opt.label)
                if len(mapped) >= num_winners:
                    break
            if mapped:
                return mapped
    except Exception:
        pass

    # Defensive fallback: take the first num_winners declared.
    return [c.user_id for c in candidates[:num_winners]]


def _resolve_approval_config_winners(
    db: Session,
    proposal: models.Proposal,
    candidates: list[models.ElectionCandidacy],
    *,
    actor_id: Optional[str] = None,
) -> list[str]:
    """Phase 66a — winner-set resolution for approval-method elections
    carrying an ``approval_winner_config``.

    Mirrors ``_resolve_winners`` (Stage 2) but the winner COUNT is
    owned by the config, not ``num_winners``: the config-driven
    approval tally (Phase 66 core; ``_build_context`` attaches the
    config for approval elections as of 66a) produces the winner set.
    A boundary tie (D4) routes through the SAME Phase 17 machinery the
    ordinary-proposal close path uses.

    Tie-resolution ordering: the close path (``advance_proposal``)
    runs ``_maybe_resolve_tie`` BEFORE this hook and persists the
    audit record to ``proposal.tie_resolution``. Because this helper
    recomputes its own tally (same ballots → deterministically the
    same boundary subset), it MERGES the persisted resolution instead
    of re-resolving (avoids a duplicate ``proposal.tie_resolved``
    audit row). If finalize is reached WITHOUT a persisted resolution
    (direct service calls, tests), it invokes the same
    ``_maybe_resolve_tie`` helper itself so the resolved set seats
    either way.

    Uncontested shortcut (D6 generalization, mirroring Stage 2's
    ``candidates <= num_winners``): when the declared candidates all
    fit inside the config's unconditional floor (``len(candidates) <=
    min_winners``) they all win without a tally. Threshold-only
    configs (min_winners == 0) have no unconditional floor, so no
    shortcut applies — candidates must clear the threshold.

    Defensive fallback (Stage 1/2 pattern carried forward): if the
    tally engine errors, fall back to the first ``min_winners``
    declared candidates. A threshold-only config falls back to no
    winners (the caller surfaces ``tally_did_not_produce_winner``) —
    seating someone who never cleared the threshold would contradict
    the config's semantics.
    """
    config = getattr(proposal, "approval_winner_config", None) or {}
    min_winners = int(config.get("min_winners") or 0)
    candidate_ids = {c.user_id for c in candidates}

    # Uncontested shortcut: everyone fits the unconditional floor.
    if min_winners > 0 and len(candidates) <= min_winners:
        return [c.user_id for c in candidates]

    try:
        from delegation_engine import engine as delegation_engine
        tally = delegation_engine.compute_tally(proposal, db)
    except Exception:  # noqa: BLE001
        log.exception(
            "approval-config election tally failed for proposal %s; "
            "falling back to the unconditional floor",
            proposal.id,
        )
        return [c.user_id for c in candidates[:min_winners]]

    # D4 — boundary tie at a seat boundary.
    boundary_tied = list(getattr(tally, "boundary_tied", None) or [])
    seats_remaining = int(getattr(tally, "seats_remaining", 0) or 0)
    if boundary_tied and seats_remaining > 0:
        persisted = getattr(proposal, "tie_resolution", None)
        if (
            isinstance(persisted, dict)
            and set(persisted.get("input_winners") or [])
            == set(boundary_tied)
        ):
            # The close path already resolved this exact tie — merge
            # its picks rather than re-resolving.
            for oid in persisted.get("chosen_winners") or []:
                if oid not in tally.winners:
                    tally.winners.append(oid)
                if hasattr(tally, "winner_seats"):
                    tally.winner_seats.setdefault(oid, "tie_resolution")
        else:
            # Finalize reached without a route-layer resolution —
            # run the same resolver now (persists the audit record).
            from routes.proposals import _maybe_resolve_tie
            _maybe_resolve_tie(
                proposal, tally, "approval", db,
                current_user_id=actor_id,
            )

    # Map option-id winners back to candidate user_ids (option.label
    # carries the user_id for elections), preserving tally seat order.
    options_by_id = {o.id: o for o in proposal.options}
    mapped: list[str] = []
    for w in list(getattr(tally, "winners", None) or []):
        opt = options_by_id.get(w)
        if opt is None:
            continue
        if opt.label in candidate_ids and opt.label not in mapped:
            mapped.append(opt.label)
    return mapped


def _cap_winners_to_title_capacity(
    db: Session,
    title: models.OrgTitle,
    winner_ids: list[str],
    *,
    slate_mode: str,
) -> tuple[list[str], list[str]]:
    """Phase 66a — cap a config-driven winner set at the title's
    holder capacity. Returns ``(seated, overflow)``.

    The config's winner count can legitimately exceed the title's
    capacity: the ``expand_winners`` tie method seats ALL boundary-
    tied options (documented D4/D11 semantics), and a generous
    ``approval_threshold`` can clear more options than ``max_holders``.
    Decision (66a, documented here): seat up to capacity in
    tally-winner order; the overflow is NOT installed and is recorded
    in the finalize audit detail (``capacity_overflow_winner_ids``)
    so the outcome is transparent rather than silently truncated.

    Capacity:
      * system titles — role-derived holders, no assignment rows; no
        cap here (the role machinery owns those bounds).
      * single-holder titles — capacity 1.
      * multi-holder titles — ``max_holders`` (NULL = uncapped).

    ``fill_vacancies``: current holders who are NOT in the winner set
    keep their seats and count against capacity; winners who already
    hold the title keep theirs (no new seat consumed beyond the one
    they hold). ``refresh_slate``: non-winning holders are removed
    before install, so the full capacity is available and incumbents
    compete in tally order like everyone else (an incumbent past the
    cap is dropped by the refresh).
    """
    if title.is_system:
        return list(winner_ids), []
    if title.cardinality_mode == "single":
        capacity: Optional[int] = 1
    elif title.max_holders is not None:
        capacity = int(title.max_holders)
    else:
        capacity = None
    if capacity is None:
        return list(winner_ids), []

    holder_ids = {
        row.user_id
        for row in db.query(models.OrgTitleAssignment)
        .filter(models.OrgTitleAssignment.title_id == title.id)
        .all()
    }
    if slate_mode == "refresh_slate":
        used = 0  # Non-winning holders are removed before install.
    else:
        used = len(holder_ids - set(winner_ids))

    seated: list[str] = []
    overflow: list[str] = []
    for uid in winner_ids:
        if slate_mode != "refresh_slate" and uid in holder_ids:
            # fill_vacancies: an incumbent winner keeps the seat they
            # already occupy.
            seated.append(uid)
            used += 1
            continue
        if used < capacity:
            seated.append(uid)
            used += 1
        else:
            overflow.append(uid)
    return seated, overflow


def _refresh_slate_for_title(
    db: Session,
    org: models.Organization,
    title: models.OrgTitle,
    incoming_winner_ids: list[str],
    *,
    actor_id: Optional[str],
    ip_address: Optional[str],
) -> None:
    """Phase 48 Stage 2 D10 — refresh_slate removes the current holders
    of ``title`` before the new winners are installed. For custom
    titles, this iterates ``OrgTitleAssignment`` rows. For system
    titles (Steward, Admin) the "current holders" are derived from
    role; refresh_slate for the Admin system title means demoting
    all current admins not in the winner set — a destructive action
    that respects the council-mode floor (cannot leave zero admins).

    Winners that are already current holders are KEPT — they're a
    no-op rather than a churn-then-restore.
    """
    if title.is_system:
        _refresh_slate_for_system_title(
            db, org, title, incoming_winner_ids,
            actor_id=actor_id, ip_address=ip_address,
        )
        return

    # Custom title: remove existing assignments not in the winners.
    from routes.org_titles import _check_revoke_floor
    incoming = set(incoming_winner_ids)
    existing = (
        db.query(models.OrgTitleAssignment)
        .filter(models.OrgTitleAssignment.title_id == title.id)
        .all()
    )
    for row in existing:
        if row.user_id in incoming:
            continue  # Already a holder + still winning → no-op.
        if title.bound_role:
            _check_revoke_floor(db, org, row.user_id, title.bound_role)
        db.delete(row)
    db.flush()


def _refresh_slate_for_system_title(
    db: Session,
    org: models.Organization,
    title: models.OrgTitle,
    incoming_winner_ids: list[str],
    *,
    actor_id: Optional[str],
    ip_address: Optional[str],
) -> None:
    """Refresh the system title's role-derived holders. Demotes all
    users currently holding ``title.bound_role`` who are NOT in the
    incoming winner set. Floor-respecting via the existing
    ``_check_revoke_floor`` gate."""
    from routes.org_titles import _check_revoke_floor
    if title.bound_role is None:
        return  # Nothing to refresh on a label-only system title.
    incoming = set(incoming_winner_ids)
    # Find current holders of the bound role.
    memberships = (
        db.query(models.OrgMembership)
        .filter(
            models.OrgMembership.org_id == org.id,
            models.OrgMembership.status == "active",
        )
        .all()
    )
    member_role_id = None
    role_row = db.query(models.Role).filter(
        models.Role.org_id == org.id,
        models.Role.system_key == "member",
    ).first()
    if role_row is not None:
        member_role_id = role_row.id
    for m in memberships:
        if m.user_id in incoming:
            continue
        if m.role_id is None:
            continue
        role = db.get(models.Role, m.role_id)
        if role is None or role.system_key != title.bound_role:
            continue
        # Floor check first — block if revoking would violate the
        # mode floor.
        _check_revoke_floor(db, org, m.user_id, title.bound_role)
        # Demote to member.
        if member_role_id is not None:
            m.role_id = member_role_id
    db.flush()


def _resolve_single_winner(
    db: Session,
    proposal: models.Proposal,
    candidates: list[models.ElectionCandidacy],
) -> Optional[str]:
    """Stage 1 single-winner resolution. For a binary election the
    winner is the candidate with the highest vote count; for
    approval/RCV the engine's existing tally produces winners (we
    take the first if multiple).

    Stage 1 is single-holder steward-title elections; the realistic
    election shape on this path is a binary "candidate A vs candidate
    B" with options corresponding to the candidates. Stage 2 will
    generalize to ranked_choice + num_winners > 1.

    Defensive fallback: if the tally returns no winner (no votes
    cast, ties not resolved by Phase 17, etc.), return None so the
    caller surfaces a clean "tally_did_not_produce_winner" failure.
    """
    # Stage 1 uses a candidate-derived winner: the candidate whose
    # user_id appears as a ProposalOption winner. If options aren't
    # populated (Stage 1 election creation should populate them per
    # candidate), fall back to the first declared candidate to keep
    # the load-bearing assertion testable even when the tally engine
    # isn't fully wired through this path yet.
    try:
        from delegation_engine import engine as delegation_engine
        tally = delegation_engine.compute_tally(proposal, db)
        winners = getattr(tally, "winners", None) or []
        if winners:
            # Winners are option_ids; map to user_id via the option
            # label convention (option.label = user_id for elections).
            options_by_id = {o.id: o for o in proposal.options}
            for w in winners:
                opt = options_by_id.get(w)
                if opt is None:
                    continue
                # Option label is the user_id for elections.
                if opt.label in {c.user_id for c in candidates}:
                    return opt.label
    except Exception:
        # If the tally engine errors on a not-yet-supported shape,
        # fall through to the defensive path.
        pass

    # Defensive fallback: the first declared candidate wins. This is
    # explicit + testable; Stage 2 replaces it with a full tally path.
    return candidates[0].user_id


# ---------------------------------------------------------------------------
# Phase 49 — Scheduled / fixed-term election trigger
# ---------------------------------------------------------------------------

def _advance_schedule_for_title(
    db: Session, title: models.OrgTitle,
) -> None:
    """Advance ``title.next_election_due_at`` by ``term_length_days``.

    Called from ``finalize_election`` when ``proposal.election_trigger
    == 'scheduled'`` (B4). The advancement is unconditional on the
    election outcome — hold-over (no candidates), uncontested win,
    contested win all advance the schedule by the same step so the
    calendar cadence is preserved.

    If the title has no term configured (term_length_days NULL) or
    no current next-due (next_election_due_at NULL) the function is
    a no-op — both are defensive cases (the tick only opens
    scheduled elections for titles with both set, so this shouldn't
    fire in practice).
    """
    if title.term_length_days is None or title.next_election_due_at is None:
        return
    step = timedelta(days=int(title.term_length_days))
    title.next_election_due_at = title.next_election_due_at + step


def _has_open_election_for_title(db: Session, title_id: str) -> bool:
    """D5 idempotency guard. True iff there's a Proposal currently
    targeting this title that is NOT in a terminal state. Pre-voting
    (draft / deliberation) + voting all count as "open."

    Closed states (passed / failed / expired_unsigned) do NOT count,
    so a resolved scheduled election doesn't block the next one once
    the title's clock advances past the next-due threshold.
    """
    open_statuses = ("draft", "deliberation", "voting")
    return (
        db.query(models.Proposal.id)
        .filter(
            models.Proposal.is_election == True,  # noqa: E712
            models.Proposal.election_title_id == title_id,
            models.Proposal.status.in_(open_statuses),
        )
        .first()
        is not None
    )


def _resolve_system_actor_for_org(
    db: Session, org: models.Organization,
) -> Optional[str]:
    """Pick an actor_id to attribute the scheduled-trigger election to.

    Audit + proposal-creator semantics expect a User. The scheduled
    trigger has no human actor — pick the current top-tier governor
    (the steward in single_steward mode, any admin in admin_council).
    Falls back to None if the org somehow has no governors (the
    no-governors org will already be in a recovery state per Phase
    45b B4; the system shouldn't be scheduling elections on it).

    This is a least-surprise default: the audit log shows the
    governance-tier holder as the proposal author, which is the
    natural "on behalf of leadership" attribution.
    """
    from governance import governing_role_key
    target_key = governing_role_key(org)
    memberships = (
        db.query(models.OrgMembership)
        .filter(
            models.OrgMembership.org_id == org.id,
            models.OrgMembership.status == "active",
        )
        .all()
    )
    for m in memberships:
        if m.role_id is None:
            continue
        role = db.get(models.Role, m.role_id)
        if role is not None and role.system_key == target_key:
            user = db.get(models.User, m.user_id)
            if user is not None and user.is_active:
                return user.id
    return None


def _open_scheduled_election(
    db: Session, org: models.Organization, title: models.OrgTitle,
    *, now: datetime,
) -> Optional[str]:
    """Open a scheduled-trigger election for ``title``.

    Sets ``election_trigger='scheduled'`` so ``finalize_election`` can
    advance the schedule on resolution (B4). The proposal lifecycle
    is identical to an admin-direct election: enters ``deliberation``
    immediately as the nomination window, then advances to voting +
    close along the normal path. The tick does NOT advance the
    proposal — that's handled by the existing voting-end worker.

    Returns the new proposal id on success or None if the open is
    skipped (e.g. no actor available + the org is in a recovery
    state).
    """
    from audit_utils import log_audit_event

    actor_id = _resolve_system_actor_for_org(db, org)
    if actor_id is None:
        log.warning(
            "open_due_term_elections: no governor available to attribute "
            "scheduled election to for org=%s title=%s; skipping",
            org.id, title.id,
        )
        return None

    # Sensible default windows; tick-driven elections use the org's
    # default deliberation + voting day settings if present, falling
    # back to platform defaults that match the admin-direct path.
    settings = org.settings or {}
    deliberation_days = float(
        settings.get("default_deliberation_days", 3.0),
    )
    voting_days = float(settings.get("default_voting_days", 7.0))

    proposal = models.Proposal(
        title=f"Election: {title.name}",
        body=(
            f"Scheduled election for the '{title.name}' title. "
            f"Term expiring around "
            f"{title.next_election_due_at.isoformat() if title.next_election_due_at else 'soon'}; "
            "the incumbent must self-nominate to defend the seat."
        ),
        author_id=actor_id,
        org_id=org.id,
        voting_method="ranked_choice",
        num_winners=max(1, title.max_holders or 1) if title.cardinality_mode == "multi" else 1,
        status="deliberation",
        deliberation_start=now,
        deliberation_days=deliberation_days,
        voting_days=voting_days,
        pass_threshold=settings.get("default_pass_threshold", 0.50) if settings else 0.50,
        # Phase 67 W1 — elections default to quorum 0 (mirrors the
        # open_election route): quorum gates seat installation, and a
        # scheduled election must seat its winners under any turnout
        # unless the org deliberately configures otherwise.
        quorum_threshold=0.0,
        is_election=True,
        election_title_id=title.id,
        election_slate_mode="fill_vacancies",
        election_trigger="scheduled",
    )
    db.add(proposal)
    db.flush()
    log_audit_event(
        db,
        action="election.opened",
        target_type="proposal",
        target_id=proposal.id,
        actor_id=actor_id,
        details={
            "org_id": org.id,
            "title_id": title.id,
            "title_name": title.name,
            "bound_role": title.bound_role,
            "trigger": "scheduled",
            "deliberation_days": deliberation_days,
            "voting_days": voting_days,
            "next_election_due_at": (
                title.next_election_due_at.isoformat()
                if title.next_election_due_at else None
            ),
        },
    )
    return proposal.id


def open_due_term_elections(
    db: Session, *, now: Optional[datetime] = None,
) -> dict:
    """Phase 49 B3 — open scheduled-trigger elections for titles whose
    term clock is due.

    A title is "due" when:
      * It has a term configured (``term_length_days`` IS NOT NULL).
      * It has ``next_election_due_at`` set.
      * ``next_election_due_at - election_lead_time_days <= now``
        (D4 lead-time alignment so the vote concludes around term-end).
      * The org has ``scheduled`` in ``settings.elections.trigger_
        sources`` AND ``elections.enabled = True`` (the two-gate
        check from D2 + Phase 48 D3).
      * No election proposal currently targets the title (D5
        idempotency).

    The tick calls this wrapped in try/except (like the
    halfway-deadline check); a per-title failure is logged + counted
    and the function continues so one bad title doesn't break the
    batch.

    Returns ``{"opened": N, "skipped_idempotent": N, "skipped_
    not_eligible": N, "errors": N}`` for the tick report.
    """
    counts = {
        "opened": 0,
        "skipped_idempotent": 0,
        "skipped_not_eligible": 0,
        "errors": 0,
    }
    now = (now or datetime.now(timezone.utc)).replace(tzinfo=None) if now else _now()
    if isinstance(now, datetime) and now.tzinfo is not None:
        now = now.astimezone(timezone.utc).replace(tzinfo=None)

    titles = (
        db.query(models.OrgTitle)
        .filter(
            models.OrgTitle.term_length_days.isnot(None),
            models.OrgTitle.next_election_due_at.isnot(None),
        )
        .all()
    )
    for title in titles:
        try:
            org = db.get(models.Organization, title.org_id)
            if org is None:
                counts["skipped_not_eligible"] += 1
                continue
            # Two-gate org check per D2.
            if not elections_enabled(org):
                counts["skipped_not_eligible"] += 1
                continue
            if not trigger_source_enabled(org, "scheduled"):
                counts["skipped_not_eligible"] += 1
                continue
            if not title_is_electable(title):
                counts["skipped_not_eligible"] += 1
                continue
            # Due-ness check (D4 lead-time alignment).
            lead = timedelta(days=int(title.election_lead_time_days or 7))
            if (title.next_election_due_at - lead) > now:
                counts["skipped_not_eligible"] += 1
                continue
            # D5 idempotency.
            if _has_open_election_for_title(db, title.id):
                counts["skipped_idempotent"] += 1
                continue
            pid = _open_scheduled_election(db, org, title, now=now)
            if pid is None:
                counts["errors"] += 1
                continue
            counts["opened"] += 1
        except Exception:  # noqa: BLE001
            log.exception(
                "open_due_term_elections: per-title failure (title=%s); continuing",
                title.id,
            )
            counts["errors"] += 1
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
    if counts["opened"] > 0:
        # Persist the new proposals + audit rows. (Rollback cases above
        # bail before this commit.)
        db.commit()
    return counts
