"""Phase 9.7 W5 — public invitation metadata endpoint.

Exposes a single read-only route used by the frontend ``InviteAccept`` page
to render the right state (registration form vs. sign-in form vs. accept
button) for an invited user, WITHOUT consuming the invitation.

The route is deliberately placed in its own module / router (under the
``/api/invitations`` prefix) rather than in ``routes/organizations.py``:

  * The existing organization invitation routes are scoped under
    ``/api/orgs/{org_slug}/invitations/...`` and require admin-membership
    auth. This endpoint is public and slug-less by design — the invited
    user, by definition, doesn't yet know (and shouldn't be told) the org
    slug until they have a valid token in hand.
  * Token enumeration risk warrants a tight rate limit (30 req/IP/min via
    slowapi, mirroring the existing ``forgot-password`` pattern in
    ``routes/auth.py``). Keeping the limited route in its own module makes
    the rate-limit wiring obvious to future readers.

The response intentionally does NOT include any organization-internal
identifiers, member lists, or proposal counts — just the human-readable
fields the InviteAccept page renders. 404 covers all "no metadata"
outcomes (token not found, expired, revoked, or already-accepted) so a
non-recipient can't tell the difference between "you typoed the token"
and "this token has already been used".
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db


router = APIRouter(prefix="/api/invitations", tags=["invitations"])

# Per-module Limiter, mirroring ``routes/auth.py``. The shared
# ``app.state.limiter`` registered in ``main.py`` is what enables the
# ``@limiter.limit(...)`` decorator to actually take effect — slowapi looks
# up the request's ``app.state.limiter`` to apply the rule.
limiter = Limiter(key_func=get_remote_address)


def _now() -> datetime:
    """Naive UTC datetime — see auth.py's _now for rationale."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.get("/{token}/meta", response_model=schemas.InvitationMetaOut)
@limiter.limit("30/minute")
def get_invitation_meta(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Return public-safe invitation metadata if the token is valid + pending.

    404 covers all four "metadata not available" outcomes (not found,
    expired, revoked, accepted) so this endpoint cannot be used to enumerate
    or distinguish invitation states.
    """
    inv = db.query(models.Invitation).filter(
        models.Invitation.token == token,
        models.Invitation.status == "pending",
    ).first()
    if not inv or inv.expires_at < _now():
        raise HTTPException(status_code=404, detail="Invitation not found")

    org = db.get(models.Organization, inv.org_id)
    if not org:
        # Defensive — if the FK target was deleted out from under the
        # invitation, treat it as missing.
        raise HTTPException(status_code=404, detail="Invitation not found")

    return schemas.InvitationMetaOut(
        org_name=org.name,
        org_slug=org.slug,
        invited_email=inv.email,
        role=inv.role,
        expires_at=inv.expires_at,
    )
