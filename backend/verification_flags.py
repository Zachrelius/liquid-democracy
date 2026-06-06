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
# Phase 52h Stage 1 H2 — low-confidence is now also configurable, with
# the SAME action semantics + the same ``pending_approval`` default.
# Pre-52h it was hardcoded review_only.
SETTING_LOW_CONF_FLAG_ACTION = "verification_low_confidence_flag_action"
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


def low_confidence_flag_action(org) -> str:
    """Phase 52h Stage 1 H2 — low-confidence is now configurable,
    with the same ``pending_approval`` default as high-confidence.
    Pre-52h this tier was hardcoded review-only; the locked-decision
    pivot is that within a real org, false positives on the low-
    confidence flag are rare enough that routing to admin review
    beats letting a possible duplicate through silently. Org admin
    can flip to ``review_only`` if they want the pre-52h behavior."""
    settings = getattr(org, "settings", None) or {}
    if not isinstance(settings, dict):
        return ACTION_PENDING_APPROVAL
    val = settings.get(SETTING_LOW_CONF_FLAG_ACTION)
    if val == ACTION_REVIEW_ONLY:
        return ACTION_REVIEW_ONLY
    return ACTION_PENDING_APPROVAL


def flag_action_for_confidence(org, confidence: str) -> str:
    """Single dispatch helper — callers pass the confidence tier and
    get back the configured action. Used by the join paths so the
    routing logic doesn't have to branch on tier."""
    if confidence == CONFIDENCE_HIGH:
        return high_confidence_flag_action(org)
    if confidence == CONFIDENCE_LOW:
        return low_confidence_flag_action(org)
    # Unknown tier — fail-safe to the safer action.
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


def evaluate_duplicate_flags_for_user_orgs(
    db: Session, *,
    user: models.User,
    actor_id: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> dict[str, list[models.OrgDuplicateFlag]]:
    """Phase 52h Stage 1 H1 — verify-time trigger. Iterate the user's
    active ``OrgMembership`` rows and run
    ``evaluate_duplicate_flags_for_org`` against each. Returns a
    mapping ``{org_id: [new_flag, …]}`` for any orgs where new flags
    were created.

    Why this exists: pre-52h, detection ran only at join / promote.
    Join-then-verify gaps existed — a user could join an org while
    unverified, then verify later, and never get checked against the
    org's existing population. This wraps the same comparison logic
    used at join time, just iterated over the user's own orgs.

    Cross-org stays ignored — only the user's OWN orgs are walked;
    never a global walk over all orgs in the platform. Consistent
    with the locked org-scoped-harm principle.

    Important behavioral asymmetry from join-time detection (H1
    locked Z decision): the CALLER is responsible for the next-step
    action. At verify-time, an active member who newly matches an
    existing org member must NOT be flipped back to
    ``pending_approval`` — that would suspend a sitting member with
    no warning. The webhook caller in ``routes/verification.
    _apply_decision`` therefore only RECORDS the flag (so
    ``is_org_verified`` flips to False per H3); it does NOT touch
    membership status.

    Performance: a user in N orgs triggers N evaluations. At current
    volumes (the typical user is in 1-3 orgs) this is trivial; no
    pre-optimization.
    """
    actor = actor_id or user.id
    membership_rows = db.execute(
        select(models.OrgMembership).where(
            models.OrgMembership.user_id == user.id,
            models.OrgMembership.status == "active",
        ),
    ).scalars().all()
    out: dict[str, list[models.OrgDuplicateFlag]] = {}
    for m in membership_rows:
        org = db.get(models.Organization, m.org_id)
        if org is None:
            continue
        new_flags = evaluate_duplicate_flags_for_org(
            db, candidate_user=user, org=org,
            actor_id=actor, ip_address=ip_address,
        )
        if new_flags:
            out[org.id] = new_flags
    return out


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


def has_open_flag(
    db: Session, *, user_id: str, org_id: str,
) -> bool:
    """Phase 52h Stage 1 H3 — True iff there's an open flag of EITHER
    tier (high-confidence or low-confidence) involving this user in
    this org. The pre-52h ``has_open_high_confidence_flag`` only
    keyed on the high tier because low-confidence was review-only;
    with H2's low-confidence-now-routes-to-pending change, both tiers
    are real signals and both invalidate ``is_org_verified``.
    """
    row = db.execute(
        select(models.OrgDuplicateFlag.id).where(
            models.OrgDuplicateFlag.org_id == org_id,
            models.OrgDuplicateFlag.status == "open",
            (
                (models.OrgDuplicateFlag.user_a_id == user_id)
                | (models.OrgDuplicateFlag.user_b_id == user_id)
            ),
        ),
    ).scalars().first()
    return row is not None


def is_demoted_in_resolved_same(
    db: Session, *, user_id: str, org_id: str,
) -> bool:
    """Phase 52h Stage 1 H4 — True iff the user is the durable demoted
    side of any ``resolved_same`` flag in this org. ``resolve_same``
    captures ``demoted_user_id = newer-of-pair`` so the predicate
    keys on this column rather than re-checking ``open`` status
    (which would silently re-verify the duplicate the moment the
    admin resolved the flag — the backward outcome the pre-52h
    behavior produced).
    """
    row = db.execute(
        select(models.OrgDuplicateFlag.id).where(
            models.OrgDuplicateFlag.org_id == org_id,
            models.OrgDuplicateFlag.status == "resolved_same",
            models.OrgDuplicateFlag.demoted_user_id == user_id,
        ),
    ).scalars().first()
    return row is not None


def is_org_verified(
    user: models.User, org: models.Organization, db: Session,
) -> bool:
    """Phase 52e Stage 2 E3 + Phase 52h Stage 1 H3/H4 — derived
    per-org verified-member status.

    True iff:
      1. The user satisfies the org's membership verification floor
         (``user_satisfies_floor`` against ``get_org_verification_
         floor("membership")``). When the floor is unset / email_only,
         this rung is satisfied trivially — additive-layer parity for
         orgs that haven't enabled verification.
      2. The user is NOT currently the subject of an open duplicate
         flag of EITHER tier in this org (H3 — was high-only).
      3. The user is NOT the durable demoted side of any
         ``resolved_same`` flag in this org (H4 — durable per-org
         demotion that survives admin resolution).

    NEVER stored. Computed at read time so a state change (membership
    floor change, flag raised, flag resolved + demote) is reflected
    immediately everywhere this predicate is read. The Members-list
    "Verified" badge, the public_accepting gate, the proposal-vote
    eligibility helpers all funnel through this.
    """
    floor, jurisdiction = verification.get_org_verification_floor(
        org, "membership",
    )
    if not verification.user_satisfies_floor(user, floor, jurisdiction):
        return False
    if has_open_flag(db, user_id=user.id, org_id=org.id):
        return False
    if is_demoted_in_resolved_same(db, user_id=user.id, org_id=org.id):
        return False
    return True


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
    ``resolved_same`` (admin says these ARE the same person; Phase
    52h Stage 1 H4 auto-demotes the NEWER of the two accounts).

    Phase 52h Stage 1 H4 — ``resolved_same`` now durably demotes:
    the newer-of-pair (by ``User.created_at``) is recorded in
    ``demoted_user_id`` and the ``is_org_verified`` predicate stays
    False for that account in this org. The admin can manually
    adjust afterward if the newer account is actually the real
    person (the locked Z policy: auto-pick the more-likely
    duplicate, leave the manual override to the admin in the rare
    inverted case).

    Fully removing / kicking the duplicate account stays a
    SEPARATE manual admin action — ``resolved_same`` only demotes
    verified-status-in-this-org; it does not deny membership,
    strip roles, or delete the account. The Phase 52 Stage 1
    cardinality-floor invariant holds: a seated role on the
    demoted account is NOT auto-stripped (the role_id row is
    untouched), preserving the "removing power requires process"
    rule.

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

    demoted_user_id: Optional[str] = None
    if resolution == "resolved_same":
        # Pick the NEWER of the two accounts by created_at. If one
        # side is missing (deleted user, FK SET NULL) fall back to
        # the other side; if both are missing demote neither.
        user_a = db.get(models.User, flag.user_a_id)
        user_b = db.get(models.User, flag.user_b_id)
        if user_a and user_b:
            demoted_user_id = (
                user_b.id if user_b.created_at >= user_a.created_at
                else user_a.id
            )
        elif user_a:
            demoted_user_id = user_a.id
        elif user_b:
            demoted_user_id = user_b.id
        flag.demoted_user_id = demoted_user_id

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
            "demoted_user_id": demoted_user_id,
        },
        ip_address=ip_address,
    )
    return flag
