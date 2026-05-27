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
from slowapi.util import get_remote_address

from settings import settings


def bypass_or_remote_address(request: Request) -> str:
    """Return a unique-per-request key when bypass is active; the real
    client IP otherwise.
    """
    if settings.debug or (
        settings.rate_limit_bypass and not settings.is_public_demo
    ):
        return f"bypass-{uuid.uuid4()}"
    return get_remote_address(request)


__all__ = ["bypass_or_remote_address"]
