#!/usr/bin/env python3
"""Phase 102b — privacy-minimized Didit integrity audit/remediation.

Dry-run is the default. Raw provider responses are classified only in memory
and are never printed or persisted. Apply mode targets exactly one explicitly
identified user/session and uses compare-and-set preconditions under row locks.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import models  # noqa: E402
import verification  # noqa: E402
import verification_provider  # noqa: E402
from audit_utils import log_audit_event  # noqa: E402
from database import SessionLocal  # noqa: E402


CLASSIFICATIONS = (
    "confirmed_valid",
    "confirmed_false_positive",
    "needs_review_provider_unavailable",
    "needs_review_history_mismatch",
    "not_applicable",
)
APPROVAL_SESSION_STATUSES = {
    "approved", "approved_purged", "approved_purge_failed",
}
CONFIRMED_TERMINAL_FAILURE_STATUSES = {"abandoned", "declined"}
DERIVED_USER_FIELDS = (
    "verification_jurisdiction",
    "verification_country",
    "verification_attestation_id",
    "legal_first_name",
    "legal_last_name",
    "legal_full_name",
    "verification_age_bands",
    "verification_age_promotes_at",
    "verification_locality_hash",
    "name_dob_address_hash",
    "name_dob_hash",
    "uniqueness_strength",
)


def _short(value: str) -> str:
    """Opaque operator label; never expose a full provider/user identifier."""
    return str(value)[:8]


def classify_record(
    *,
    provenance: str,
    verification_state: str,
    session_status: str,
    has_completion_audit: bool,
    has_consumption: bool,
    provider_result: verification_provider.ProviderDecisionResult,
) -> str:
    """Classify one correlated record without handling provider I/O."""
    if provenance != verification.PROV_DIDIT:
        return "not_applicable"
    if verification_state == verification.EMAIL_ONLY:
        return "needs_review_history_mismatch"
    if not has_completion_audit or not has_consumption:
        return "needs_review_history_mismatch"
    if provider_result.approved:
        if session_status not in APPROVAL_SESSION_STATUSES:
            return "needs_review_history_mismatch"
        return "confirmed_valid"
    # Only an authoritative terminal provider failure supports automated
    # correction. Transient, malformed, contradictory, or unknown outcomes
    # remain review-only even though the webhook correctly fails them closed.
    if provider_result.normalized_status in CONFIRMED_TERMINAL_FAILURE_STATUSES:
        return "confirmed_false_positive"
    return "needs_review_history_mismatch"


def _correlation_flags(db, user_id: str, provider_session_id: str) -> tuple[bool, bool]:
    has_completion = db.query(models.AuditLog.id).filter(
        models.AuditLog.target_id == user_id,
        models.AuditLog.action == "verification.completed",
    ).first() is not None
    has_consumption = db.query(models.VerificationConsumption.id).filter(
        models.VerificationConsumption.user_id == user_id,
        models.VerificationConsumption.provider_session_id == provider_session_id,
    ).first() is not None
    return has_completion, has_consumption


def _provider_result(provider_session_id: str):
    payload = verification_provider.retrieve_session_decision(provider_session_id)
    return verification_provider.classify_retrieved_session_decision(payload)


def audit_cohort() -> int:
    counts = Counter({name: 0 for name in CLASSIFICATIONS})
    review_labels: list[str] = []
    provider_errors = 0
    with SessionLocal() as db:
        # One row per user, using the newest local Didit session. Non-Didit
        # provenance is included only when a session exists so the explicit
        # not_applicable category remains observable without scanning all users.
        rows = db.query(models.VerificationSession).order_by(
            models.VerificationSession.user_id,
            models.VerificationSession.created_at.desc(),
        ).all()
        newest = {}
        for row in rows:
            newest.setdefault(row.user_id, row)

        for user_id, session in newest.items():
            user = db.get(models.User, user_id)
            if user is None:
                counts["needs_review_history_mismatch"] += 1
                review_labels.append(f"u:{_short(user_id)} s:{_short(session.id)}")
                continue
            if user.verification_provenance != verification.PROV_DIDIT:
                counts["not_applicable"] += 1
                continue
            try:
                result = _provider_result(session.provider_session_id)
            except (httpx.HTTPError, RuntimeError, ValueError):
                counts["needs_review_provider_unavailable"] += 1
                provider_errors += 1
                review_labels.append(f"u:{_short(user.id)} s:{_short(session.id)}")
                continue
            has_completion, has_consumption = _correlation_flags(
                db, user.id, session.provider_session_id,
            )
            classification = classify_record(
                provenance=user.verification_provenance,
                verification_state=user.verification_state,
                session_status=session.status,
                has_completion_audit=has_completion,
                has_consumption=has_consumption,
                provider_result=result,
            )
            counts[classification] += 1
            if classification.startswith("needs_review") or classification == "confirmed_false_positive":
                review_labels.append(f"u:{_short(user.id)} s:{_short(session.id)}")

    print("phase102b_didit_integrity_audit mode=dry_run")
    print("cohort_counts " + " ".join(f"{key}={counts[key]}" for key in CLASSIFICATIONS))
    if review_labels:
        print("operator_labels " + " ".join(review_labels))
    if provider_errors:
        print(f"result=needs_review provider_errors={provider_errors}")
        return 3
    print("result=complete_no_provider_errors")
    return 0


def _membership_fails_after_reset(user, org) -> bool:
    requirements = verification.membership_verification_requirements(org)
    floor = requirements["floor"]
    if floor != verification.EMAIL_ONLY and not verification.user_satisfies_floor(
        user, floor, requirements.get("jurisdiction"),
    ):
        return True
    min_age = requirements.get("min_age")
    if min_age and not verification.user_meets_age(user, min_age):
        return True
    if requirements.get("requires_residency") and not verification.user_satisfies_residency_scope(user, org):
        return True
    return False


def _reset_user_view(user):
    """Read-only user shape representing the post-remediation identity state."""
    return SimpleNamespace(
        verification_state=verification.EMAIL_ONLY,
        verification_jurisdiction=None,
        verification_country=None,
        verification_age_bands=None,
        verification_age_promotes_at=None,
        verification_locality_hash=None,
    )


def audit_exact(args) -> int:
    with SessionLocal() as db:
        user = db.get(models.User, args.user_id)
        session = db.query(models.VerificationSession).filter(
            models.VerificationSession.provider_session_id == args.provider_session_id,
        ).first()
        if user is None or session is None or session.user_id != args.user_id:
            print("result=refused reason=exact_target_not_found")
            return 2
        if user.verification_state == verification.EMAIL_ONLY and user.verification_provenance == verification.PROV_NONE and session.status == "remediated_false_positive":
            print("result=already_remediated user_rows=1 session_rows=1 mutations=0")
            return 0
        try:
            result = _provider_result(args.provider_session_id)
        except (httpx.HTTPError, RuntimeError, ValueError):
            print("result=needs_review reason=provider_unavailable")
            return 3
        has_completion, has_consumption = _correlation_flags(
            db, user.id, session.provider_session_id,
        )
        classification = classify_record(
            provenance=user.verification_provenance,
            verification_state=user.verification_state,
            session_status=session.status,
            has_completion_audit=has_completion,
            has_consumption=has_consumption,
            provider_result=result,
        )
        active_memberships = db.query(models.OrgMembership).filter(
            models.OrgMembership.user_id == user.id,
            models.OrgMembership.status == "active",
        ).all()
        suspension_count = sum(
            1 for membership in active_memberships
            if _membership_fails_after_reset(
                _reset_user_view(user), membership.organization,
            )
        )
        vote_count = db.query(models.Vote).filter(models.Vote.user_id == user.id).count()
        consumption_count = db.query(models.VerificationConsumption).filter(
            models.VerificationConsumption.user_id == user.id,
        ).count()
        print(
            "preview "
            f"classification={classification} provider_status={result.normalized_status} "
            f"user_rows=1 session_rows=1 memberships_to_suspend={suspension_count} "
            f"votes_preserved={vote_count} audits_to_add={1 + suspension_count} "
            f"consumption_rows_preserved={consumption_count}"
        )
        if not args.confirm_remediation:
            print("result=dry_run no_mutation=true")
            return 0 if classification == "confirmed_false_positive" else 2

    # Fresh transaction and locked compare-and-set immediately before apply.
    with SessionLocal() as db:
        user = db.query(models.User).filter(models.User.id == args.user_id).with_for_update().one_or_none()
        session = db.query(models.VerificationSession).filter(
            models.VerificationSession.provider_session_id == args.provider_session_id,
            models.VerificationSession.user_id == args.user_id,
        ).with_for_update().one_or_none()
        if user is None or session is None:
            print("result=refused reason=compare_and_set_target_changed")
            return 2
        if user.verification_state == verification.EMAIL_ONLY and user.verification_provenance == verification.PROV_NONE and session.status == "remediated_false_positive":
            print("result=already_remediated user_rows=1 session_rows=1 mutations=0")
            return 0
        if (
            user.verification_state != args.expected_verification_state
            or user.verification_provenance != args.expected_provenance
            or session.status != args.expected_session_status
        ):
            db.rollback()
            print("result=refused reason=database_precondition_changed")
            return 2
        try:
            fresh_result = _provider_result(args.provider_session_id)
        except (httpx.HTTPError, RuntimeError, ValueError):
            db.rollback()
            print("result=refused reason=fresh_provider_read_failed")
            return 3
        if fresh_result.normalized_status != args.expected_provider_status:
            db.rollback()
            print("result=refused reason=provider_precondition_changed")
            return 2
        has_completion, has_consumption = _correlation_flags(
            db, user.id, session.provider_session_id,
        )
        if classify_record(
            provenance=user.verification_provenance,
            verification_state=user.verification_state,
            session_status=session.status,
            has_completion_audit=has_completion,
            has_consumption=has_consumption,
            provider_result=fresh_result,
        ) != "confirmed_false_positive":
            db.rollback()
            print("result=refused reason=not_confirmed_false_positive")
            return 2

        old_state = user.verification_state
        user.verification_state = verification.EMAIL_ONLY
        user.verification_provenance = verification.PROV_NONE
        for field in DERIVED_USER_FIELDS:
            setattr(user, field, None)
        user.verification_updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.status = "remediated_false_positive"

        memberships = db.query(models.OrgMembership).filter(
            models.OrgMembership.user_id == user.id,
            models.OrgMembership.status == "active",
        ).with_for_update().all()
        suspended = []
        for membership in memberships:
            if not _membership_fails_after_reset(user, membership.organization):
                continue
            membership.status = "suspended"
            suspended.append(membership)
            log_audit_event(
                db,
                action="org.membership_suspended_verification_remediation",
                target_type="org_membership",
                target_id=membership.id,
                details={"org_id": membership.org_id, "reason": "verification_false_positive_remediated"},
            )
        log_audit_event(
            db,
            action="verification.remediated_false_positive",
            target_type="user",
            target_id=user.id,
            details={
                "provider": "didit",
                "provider_outcome": fresh_result.normalized_status,
                "old_state": old_state,
                "new_state": verification.EMAIL_ONLY,
            },
        )
        db.commit()
        print(
            "result=remediated user_rows=1 session_rows=1 "
            f"memberships_suspended={len(suspended)} votes_mutated=0 "
            "consumption_rows_mutated=0"
        )
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id")
    parser.add_argument("--provider-session-id")
    parser.add_argument("--expected-verification-state")
    parser.add_argument("--expected-provenance")
    parser.add_argument("--expected-session-status")
    parser.add_argument("--expected-provider-status")
    parser.add_argument("--confirm-remediation", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    exact = bool(args.user_id or args.provider_session_id)
    if exact and not (args.user_id and args.provider_session_id):
        print("result=refused reason=user_and_session_ids_required_together")
        return 2
    if args.confirm_remediation:
        required = (
            args.user_id, args.provider_session_id,
            args.expected_verification_state, args.expected_provenance,
            args.expected_session_status, args.expected_provider_status,
        )
        if not all(required):
            print("result=refused reason=all_compare_and_set_arguments_required")
            return 2
    return audit_exact(args) if exact else audit_cohort()


if __name__ == "__main__":
    raise SystemExit(main())
