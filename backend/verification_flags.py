"""Phase 52e Stage 2 — org-scoped duplicate-flag detection + the
derived ``is_org_verified`` predicate.

Two responsibilities (kept in this module so the rest of the codebase
talks to one seam):

  1. **Flag detection** at participation points. Given a candidate
     user joining or promoting in an org, walk the user's hashes and
     the org's current member hashes and create
     ``OrgDuplicateFlag`` rows for any matches. Cross-org matches
     are computed-but-ignored — harm is org-scoped.

  2. **Derived predicate.** ``is_org_verified(user, org, db)`` is
     True iff the user satisfies the org's membership floor AND the
     user is not currently the ``user_b_id`` of any open high-
     confidence flag in this org. Computed on read — never stored,
     so seed-time / existing-row drift is impossible (see Phase 32.2
     B3 hindsight for why this matters).

Phase 52e settings keys (live on ``Organization.settings`` JSON):

  * ``verification_high_confidence_flag_action`` — what to do with a
    high-confidence (``name_dob_address_hash``) match at join time.
    Values: ``"pending_approval"`` (default — block-pending-appeal,
    routes the membership to the existing approval queue) or
    ``"review_only"`` (flag is created + admin notified, but the
    membership status is unchanged). Low-confidence flags are ALWAYS
    review-only regardless of this setting.

  * ``verification_required_for_public_delegate`` — bool. When True,
    ``submit_public_accepting`` requires ``is_org_verified``.

  * ``verification_membership_floor`` — string (Phase 52 Stage 1)
    Re-read here through the existing helper.

This module does NOT decide whether to BLOCK membership — that's the
join route's call after consulting the flag rows + the setting. We
just produce the flag rows + provide the read predicate.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import models
import verification
from audit_utils import log_audit_event


# Settings keys
SETTING_HIGH_CONF_FLAG_ACTION = "verification_high_confidence_flag_action"
SETTING_VERIFY_PUBLIC_DELEGATE = "verification_required_for_public_delegate"

# Confidence tier labels (mirror the hash field naming, minus "_hash")
CONFIDENCE_HIGH = "name_dob_address"
CONFIDENCE_LOW = "name_dob"

# Action values for the high-confidence default-action setting
ACTION_PENDING_APPROVAL = "pending_approval"
ACTION_REVIEW_ONLY = "review_only"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _ordered_pair(a_id: str, b_id: str) -> tuple[str, str]:
    """Order user ids so (a, b) and (b, a) collapse to the same key
    for uniqueness. The convention is alphabetic; pure ordering, no
    semantic claim about which is the incumbent."""
    if a_id < b_id:
        return a_id, b_id
    return b_id, a_id


# ---------------------------------------------------------------------------
# Settings reads (defaults-if-absent)
# ---------------------------------------------------------------------------


def high_confidence_flag_action(org) -> str:
    """Returns ``"pending_approval"`` (default — high-confidence
    matches default to block-pending-appeal) or ``"review_only"``.
    Org admin can flip this in OrgSettings; the v1 default is the
    safer one (route to admin review)."""
    settings = getattr(org, "settings", None) or {}
    if not isinstance(settings, dict):
        return ACTION_PENDING_APPROVAL
    val = settings.get(SETTING_HIGH_CONF_FLAG_ACTION)
    if val == ACTION_REVIEW_ONLY:
        return ACTION_REVIEW_ONLY
    return ACTION_PENDING_APPROVAL


def verification_required_for_public_delegate(org) -> bool:
    """True iff the org has opted in to requiring ``is_org_verified``
    for the ``public_accepting`` promotion. Defaults False — preserves
    the additive-layer invariant for orgs that haven't touched the
    setting."""
    settings = getattr(org, "settings", None) or {}
    if not isinstance(settings, dict):
        return False
    return bool(settings.get(SETTING_VERIFY_PUBLIC_DELEGATE, False))


# ---------------------------------------------------------------------------
# Flag detection (write side)
# ---------------------------------------------------------------------------


def _existing_member_hashes(
    db: Session, org_id: str, exclude_user_id: str,
) -> list[models.User]:
    """Return the User rows for active members of ``org_id`` (other
    than ``exclude_user_id``) who carry at least one name-based hash.
    Used to walk the org's current population for matches."""
    rows = db.execute(
        select(models.User).join(
            models.OrgMembership,
            models.OrgMembership.user_id == models.User.id,
        ).where(
            models.OrgMembership.org_id == org_id,
            models.OrgMembership.status == "active",
            models.User.id != exclude_user_id,
            (
                (models.User.name_dob_address_hash.isnot(None))
                | (models.User.name_dob_hash.isnot(None))
            ),
        ),
    ).scalars().all()
    return list(rows)


def _record_flag(
    db: Session, *,
    org_id: str,
    candidate_user_id: str,
    incumbent_user_id: str,
    confidence: str,
    actor_id: str,
    ip_address: Optional[str] = None,
) -> Optional[models.OrgDuplicateFlag]:
    """Create an ``OrgDuplicateFlag`` for this pair if one doesn't
    already exist with status ``open`` or ``resolved_distinct``.
    A previously-resolved-distinct pair is NOT re-flagged (the
    suppression rule)."""
    a_id, b_id = _ordered_pair(incumbent_user_id, candidate_user_id)
    existing = db.execute(
        select(models.OrgDuplicateFlag).where(
            models.OrgDuplicateFlag.org_id == org_id,
            models.OrgDuplicateFlag.user_a_id == a_id,
            models.OrgDuplicateFlag.user_b_id == b_id,
            models.OrgDuplicateFlag.confidence == confidence,
        ),
    ).scalars().first()
    if existing is not None:
        return existing  # don't dupe; caller can decide what to do
    flag = models.OrgDuplicateFlag(
        org_id=org_id,
        user_a_id=a_id,
        user_b_id=b_id,
        confidence=confidence,
        status="open",
    )
    db.add(flag)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return None
    log_audit_event(
        db,
        action="org.duplicate_flag_raised",
        target_type="organization",
        target_id=org_id,
        actor_id=actor_id,
        details={
            "org_id": org_id,
            "user_a_id": a_id,
            "user_b_id": b_id,
            "confidence": confidence,
            "candidate_user_id": candidate_user_id,
            "incumbent_user_id": incumbent_user_id,
        },
        ip_address=ip_address,
    )
    return flag


def evaluate_duplicate_flags_for_org(
    db: Session, *,
    candidate_user: models.User,
    org: models.Organization,
    actor_id: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> list[models.OrgDuplicateFlag]:
    """Walk the org's active members and flag any name-hash matches
    with ``candidate_user``. Returns the list of NEW flags created
    (idempotent re-flagging — already-open flags are not re-created
    and not returned).

    Same-org only. Cross-org matches are computed-but-ignored at the
    call layer because the call layer never invokes this for orgs the
    candidate isn't joining / promoting in.
    """
    actor = actor_id or candidate_user.id
    members = _existing_member_hashes(db, org.id, candidate_user.id)
    new_flags: list[models.OrgDuplicateFlag] = []

    cand_nda = candidate_user.name_dob_address_hash
    cand_nd = candidate_user.name_dob_hash

    for m in members:
        # High-confidence match — name + DOB + address.
        if (
            cand_nda is not None
            and m.name_dob_address_hash is not None
            and cand_nda == m.name_dob_address_hash
        ):
            existing = db.execute(
                select(models.OrgDuplicateFlag).where(
                    models.OrgDuplicateFlag.org_id == org.id,
                    models.OrgDuplicateFlag.user_a_id == _ordered_pair(m.id, candidate_user.id)[0],
                    models.OrgDuplicateFlag.user_b_id == _ordered_pair(m.id, candidate_user.id)[1],
                    models.OrgDuplicateFlag.confidence == CONFIDENCE_HIGH,
                ),
            ).scalars().first()
            if existing is None:
                flag = _record_flag(
                    db, org_id=org.id,
                    candidate_user_id=candidate_user.id,
                    incumbent_user_id=m.id,
                    confidence=CONFIDENCE_HIGH,
                    actor_id=actor, ip_address=ip_address,
                )
                if flag is not None:
                    new_flags.append(flag)

        # Low-confidence match — name + DOB only. ONLY raised when
        # high-confidence didn't already match (the high flag carries
        # everything the low one would).
        elif (
            cand_nd is not None
            and m.name_dob_hash is not None
            and cand_nd == m.name_dob_hash
        ):
            existing = db.execute(
                select(models.OrgDuplicateFlag).where(
                    models.OrgDuplicateFlag.org_id == org.id,
                    models.OrgDuplicateFlag.user_a_id == _ordered_pair(m.id, candidate_user.id)[0],
                    models.OrgDuplicateFlag.user_b_id == _ordered_pair(m.id, candidate_user.id)[1],
                    models.OrgDuplicateFlag.confidence == CONFIDENCE_LOW,
                ),
            ).scalars().first()
            if existing is None:
                flag = _record_flag(
                    db, org_id=org.id,
                    candidate_user_id=candidate_user.id,
                    incumbent_user_id=m.id,
                    confidence=CONFIDENCE_LOW,
                    actor_id=actor, ip_address=ip_address,
                )
                if flag is not None:
                    new_flags.append(flag)
    return new_flags


# ---------------------------------------------------------------------------
# Read predicates
# ---------------------------------------------------------------------------


def has_open_high_confidence_flag(
    db: Session, *, user_id: str, org_id: str,
) -> bool:
    """True iff there's an open high-confidence flag involving this
    user in this org. Used by ``is_org_verified`` to invalidate the
    derived verified status when a duplicate is suspected."""
    row = db.execute(
        select(models.OrgDuplicateFlag.id).where(
            models.OrgDuplicateFlag.org_id == org_id,
            models.OrgDuplicateFlag.confidence == CONFIDENCE_HIGH,
            models.OrgDuplicateFlag.status == "open",
            (
                (models.OrgDuplicateFlag.user_a_id == user_id)
                | (models.OrgDuplicateFlag.user_b_id == user_id)
            ),
        ),
    ).scalars().first()
    return row is not None


def is_org_verified(
    user: models.User, org: models.Organization, db: Session,
) -> bool:
    """Phase 52e Stage 2 E3 — derived per-org verified-member status.

    True iff:
      1. The user satisfies the org's membership verification floor
         (``user_satisfies_floor`` against ``get_org_verification_
         floor("membership")``). When the floor is unset / email_only,
         this rung is satisfied trivially — additive-layer parity for
         orgs that haven't enabled verification.
      2. The user is NOT currently the subject of an open high-
         confidence duplicate flag in this org. Low-confidence flags
         do NOT invalidate verified status — they route to admin
         review only and the birthday-paradox math means a low-
         confidence false positive would otherwise wall innocents.

    NEVER stored. Computed at read time so a state change (membership
    floor change, flag raised, flag resolved) is reflected immediately
    everywhere this predicate is read. The Members-list "Verified"
    badge, the public_accepting gate, the proposal-vote eligibility
    helpers all funnel through this.
    """
    floor, jurisdiction = verification.get_org_verification_floor(
        org, "membership",
    )
    if not verification.user_satisfies_floor(user, floor, jurisdiction):
        return False
    return not has_open_high_confidence_flag(
        db, user_id=user.id, org_id=org.id,
    )


# ---------------------------------------------------------------------------
# Admin adjudication state machine
# ---------------------------------------------------------------------------


def resolve_flag(
    db: Session, *,
    flag: models.OrgDuplicateFlag,
    resolution: str,
    actor: models.User,
    ip_address: Optional[str] = None,
) -> models.OrgDuplicateFlag:
    """Set the flag to ``resolved_distinct`` (admin says these ARE
    two different real people; suppresses re-flagging) or
    ``resolved_same`` (admin says these ARE the same person; v1
    records only, enforcement is manual / future).

    Raises ValueError on an invalid resolution string.
    """
    if resolution not in ("resolved_distinct", "resolved_same"):
        raise ValueError(
            f"Invalid resolution {resolution!r}; expected "
            "'resolved_distinct' or 'resolved_same'."
        )
    if flag.status != "open":
        return flag  # idempotent — second resolve is a no-op

    flag.status = resolution
    flag.resolved_by_id = actor.id
    flag.resolved_at = _now()
    log_audit_event(
        db,
        action="org.duplicate_flag_resolved",
        target_type="organization",
        target_id=flag.org_id,
        actor_id=actor.id,
        details={
            "flag_id": flag.id,
            "user_a_id": flag.user_a_id,
            "user_b_id": flag.user_b_id,
            "confidence": flag.confidence,
            "resolution": resolution,
        },
        ip_address=ip_address,
    )
    return flag
