"""Phase 40 B5 — shared slowapi key_func with controlled bypass.

`bypass_or_remote_address` is the canonical key_func for every `Limiter`
in this codebase (three call sites: main.py, routes/auth.py,
routes/invitations.py). It defers to `slowapi.util.get_remote_address`
in normal operation, but returns a unique-per-request UUID when the
bypass conditions are met — effectively disabling the limiter for the
caller without monkey-patching slowapi or per-route opt-outs.

Bypass conditions:
  - `settings.debug == True` (local dev / test); OR
  - `settings.rate_limit_bypass == True` AND `settings.is_public_demo
    == False` (ops/QA on a controlled non-public env)

Compound gate prevents the bypass from silently activating on the
public-demo prod env even if `RATE_LIMIT_BYPASS=true` is set in
Railway by mistake. A startup assert in main.py also fails-fast at
boot if both `IS_PUBLIC_DEMO=true` and `RATE_LIMIT_BYPASS=true` are
set — belt-and-suspenders.

See SECURITY_REVIEW.md for the operator-facing documentation.
"""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import Request
from limits import parse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from slowapi.wrappers import Limit

from settings import settings


def _bypass_active() -> bool:
    return settings.debug or (
        settings.rate_limit_bypass and not settings.is_public_demo
    )


def bypass_or_remote_address(request: Request) -> str:
    """Return a unique-per-request key when bypass is active; the real
    client IP otherwise.
    """
    if _bypass_active():
        return f"bypass-{uuid.uuid4()}"
    return get_remote_address(request)


def user_or_remote_address(request: Request) -> str:
    """Phase 86 (B-7) — key content-creation limits by the authenticated
    user id when resolvable, else the client IP.

    IP-keying is the wrong unit for logged-in abuse (one troll can rotate
    IPs, and shared-NAT users would collide). We resolve the bearer token to
    a user id without a DB hit (the id is the JWT subject). Falls back to the
    client IP for unauthenticated callers. Honors the same bypass gate as
    ``bypass_or_remote_address`` so debug/QA env is unaffected and the
    IS_PUBLIC_DEMO fail-fast assert in main.py is untouched.
    """
    if _bypass_active():
        return f"bypass-{uuid.uuid4()}"
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        try:
            import auth as auth_utils
            payload = auth_utils.jwt.decode(
                token, settings.secret_key, algorithms=[auth_utils.ALGORITHM],
            )
            sub = payload.get("sub")
            if sub:
                return f"user:{sub}"
        except Exception:  # noqa: BLE001 — fall back to IP on any decode failure
            pass
    return get_remote_address(request)


# ---------------------------------------------------------------------------
# Phase 86 (B-7) — content-creation limiter + limits.
#
# One module-level home for every content limit so tuning is a one-line
# change. Defaults are generous: sized to never bother a legitimate pilot
# org, only to cap runaway automated abuse from a single account. Not
# per-org configurable (deliberately out of scope this pass).
# ---------------------------------------------------------------------------
content_limiter = Limiter(key_func=user_or_remote_address)

COMMENT_CREATE_LIMIT = "30/hour"       # comment posting
PROPOSAL_CREATE_LIMIT = "10/day"       # proposal + cosign-petition creation
# Phase 101 — trusted organization maintainers get a distinct bounded bucket.
# This is deliberately not configurable per org and never replaces any
# proposal-create permission or validation gate.
HIGH_VOLUME_PROPOSAL_CREATE_LIMIT = "10000/day"
WRITEIN_OPTION_LIMIT = "20/day"        # write-in option adds
FOLLOW_REQUEST_LIMIT = "30/day"        # follow requests
JOIN_REQUEST_LIMIT = "20/day"          # open join + join requests + invite accept
REPORT_CREATE_LIMIT = "20/day"         # content reports (belt-and-suspenders)
ORG_CREATE_LIMIT = "5/day"             # org creation (3-org cap is the real gate)
# Invitation send is already permission-gated (member.invite, moderator+); this
# is a per-request (not per-email) ceiling so batch onboarding still works. The
# key change vs. pre-86 is user-keying instead of the pre-auth meta GET's IP key.
INVITATION_CREATE_LIMIT = "30/day"
# Phase 90b — member-to-member share transfers. Modest per-user ceiling; the
# balance check is the real gate.
SHARE_TRANSFER_LIMIT = "10/hour"


# ---------------------------------------------------------------------------
# Phase 101 — organization-scoped proposal-create rate tier.
# ---------------------------------------------------------------------------

ProposalCreateRateTier = Literal["ordinary", "high_volume"]


def resolve_proposal_create_rate_tier(
    db,
    user_id: str,
    target_org,
) -> ProposalCreateRateTier:
    """Resolve the organization proposal-create rate tier from server state.

    The trusted tier requires an active, verified user; a real effective role
    on the target scope (not a platform-admin-only fallback); and BOTH
    ``proposal.create`` and ``proposal.high_volume_create``.  Returning the
    ordinary tier is intentionally fail-closed: the caller still passes
    through the route's existing authorization and validation gates.
    """
    import models
    from role_permissions import effective_role_on_sub_org, has_permission

    user = db.get(models.User, user_id)
    if (
        user is None
        or not bool(user.is_active)
        or not bool(user.email_verified)
        or target_org is None
    ):
        return "ordinary"

    if target_org.parent_org_id is None:
        membership = db.query(models.OrgMembership).filter(
            models.OrgMembership.user_id == user_id,
            models.OrgMembership.org_id == target_org.id,
            models.OrgMembership.status == "active",
        ).first()
        if membership is None:
            return "ordinary"
    else:
        role, via_platform_admin = effective_role_on_sub_org(
            db, user_id, target_org,
        )
        if role is None or via_platform_admin:
            return "ordinary"

    if not has_permission(db, user_id, target_org.id, "proposal.create"):
        return "ordinary"
    if not has_permission(
        db, user_id, target_org.id, "proposal.high_volume_create",
    ):
        return "ordinary"
    return "high_volume"


def _slowapi_limit_wrapper(item, key: str, scope: str) -> Limit:
    """Build the wrapper SlowAPI's public 429 handler expects."""
    return Limit(
        item,
        key_func=lambda: key,
        scope=scope,
        per_method=False,
        methods=None,
        error_message=None,
        exempt_when=None,
        cost=1,
        override_defaults=True,
    )


def enforce_proposal_create_rate_limit(
    request: Request,
    user_id: str,
    tier: ProposalCreateRateTier,
    *,
    ordinary_limit: str = PROPOSAL_CREATE_LIMIT,
    high_volume_limit: str = HIGH_VOLUME_PROPOSAL_CREATE_LIMIT,
) -> None:
    """Charge exactly one mutually-exclusive fixed-window proposal bucket.

    The helper runs after FastAPI auth/membership dependencies and proposal
    validation resolve, avoiding an ordering assumption in SlowAPI's route
    decorator.  The optional limits are for isolated safety-fuse tests; the
    production call uses the module constants.
    """
    if _bypass_active():
        return

    if tier == "high_volume":
        limit_text = high_volume_limit
        scope = "org-proposal-create:high-volume"
    else:
        limit_text = ordinary_limit
        scope = "org-proposal-create:ordinary"

    item = parse(limit_text)
    key = f"user:{user_id}"
    identifiers = [key, scope]
    request.state.view_rate_limit = (item, identifiers)
    if not content_limiter._limiter.hit(item, *identifiers, cost=1):
        raise RateLimitExceeded(_slowapi_limit_wrapper(item, key, scope))


__all__ = [
    "bypass_or_remote_address",
    "user_or_remote_address",
    "content_limiter",
    "COMMENT_CREATE_LIMIT",
    "PROPOSAL_CREATE_LIMIT",
    "HIGH_VOLUME_PROPOSAL_CREATE_LIMIT",
    "ProposalCreateRateTier",
    "resolve_proposal_create_rate_tier",
    "enforce_proposal_create_rate_limit",
    "WRITEIN_OPTION_LIMIT",
    "FOLLOW_REQUEST_LIMIT",
    "JOIN_REQUEST_LIMIT",
    "REPORT_CREATE_LIMIT",
    "ORG_CREATE_LIMIT",
    "INVITATION_CREATE_LIMIT",
    "SHARE_TRANSFER_LIMIT",
]
