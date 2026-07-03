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

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

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
WRITEIN_OPTION_LIMIT = "20/day"        # write-in option adds
FOLLOW_REQUEST_LIMIT = "30/day"        # follow requests
JOIN_REQUEST_LIMIT = "20/day"          # open join + join requests + invite accept
REPORT_CREATE_LIMIT = "20/day"         # content reports (belt-and-suspenders)
ORG_CREATE_LIMIT = "5/day"             # org creation (3-org cap is the real gate)
# Invitation send is already permission-gated (member.invite, moderator+); this
# is a per-request (not per-email) ceiling so batch onboarding still works. The
# key change vs. pre-86 is user-keying instead of the pre-auth meta GET's IP key.
INVITATION_CREATE_LIMIT = "30/day"


__all__ = [
    "bypass_or_remote_address",
    "user_or_remote_address",
    "content_limiter",
    "COMMENT_CREATE_LIMIT",
    "PROPOSAL_CREATE_LIMIT",
    "WRITEIN_OPTION_LIMIT",
    "FOLLOW_REQUEST_LIMIT",
    "JOIN_REQUEST_LIMIT",
    "REPORT_CREATE_LIMIT",
    "ORG_CREATE_LIMIT",
    "INVITATION_CREATE_LIMIT",
]
