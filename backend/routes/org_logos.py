"""Phase 12.7 B1+B2 — org logo upload + branding settings endpoints.

Three endpoints, all gated by ``has_permission(user, org, "org.edit_branding")``:

  POST   /api/orgs/{slug}/logo       — multipart logo upload
  DELETE /api/orgs/{slug}/logo       — remove logo (idempotent)
  PATCH  /api/orgs/{slug}/branding   — set primary/accent colors

Storage scheme (Phase 12.7 D1):
  Logos: ``LOGOS_BASE_DIR / {org_id} / {large|small}.{ext}``
    - large: max 400x160 bounding box
    - small: max 200x80 bounding box
    - extension preserved from input (jpg/png/webp) so transparency in
      PNG/WEBP isn't lost (avatars store as JPEG; logos are different
      because non-rectangular logos are common).

Storage URL: ``/uploads/logos/{org_id}/large.{ext}`` (the StaticFiles
mount in main.py serves the file regardless of extension; the canonical
URL stored on Organization.settings.branding.logo_url is the large
path).

Branding state lives on ``Organization.settings.branding`` as a JSON
sub-dict (no schema migration required). Shape:

    {
      "logo_url": "/uploads/logos/{org_id}/large.png" | null,
      "primary_color": "#RRGGBB" | null,
      "accent_color": "#RRGGBB" | null,
      "accent_auto_derived": true | false
    }

The ``branding`` object is also surfaced on /api/orgs/{slug} responses
via the ``_org_to_out`` helper (Phase 12.7 B4).
"""
from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from PIL import Image
from sqlalchemy.orm import Session

import auth as auth_utils
import models
import schemas
from audit_utils import log_audit_event
from database import get_db
from role_permissions import has_permission
from routes import avatars as avatars_module


log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/orgs", tags=["org-branding"])


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Mirror the avatar route's content-type whitelist + size cap so the two
# upload surfaces have a consistent posture from the user's perspective.
ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset({
    "image/jpeg",
    "image/png",
    "image/webp",
})

# Map content-type → file extension. The output format follows the
# input format so PNG/WEBP transparency is preserved for non-rectangular
# logos.
_EXT_BY_CONTENT_TYPE: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}

# Map content-type → Pillow save format string.
_PIL_FORMAT_BY_CONTENT_TYPE: dict[str, str] = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}

# Set of every extension we might have written for a logo, used by the
# replace + delete paths to find the previous file regardless of
# whichever format was uploaded last.
_ALL_LOGO_EXTS: tuple[str, ...] = ("jpg", "jpeg", "png", "webp")

MAX_UPLOAD_BYTES: int = 6 * 1024 * 1024  # 6 MB pre-resize, mirrors avatars.

# Bounding-box size pairs. (width_max, height_max) per spec D5.
SIZE_LARGE: tuple[int, int] = (400, 160)
SIZE_SMALL: tuple[int, int] = (200, 80)
SIZES_BY_NAME: dict[str, tuple[int, int]] = {
    "large": SIZE_LARGE,
    "small": SIZE_SMALL,
}


# ---------------------------------------------------------------------------
# Path / URL helpers
# ---------------------------------------------------------------------------

def _logo_dir(org_id: str) -> Path:
    """Per-org directory under LOGOS_BASE_DIR.

    Reads through ``avatars_module.LOGOS_BASE_DIR`` (rather than caching a
    local reference) so monkeypatched test paths flow through correctly.
    """
    return avatars_module.LOGOS_BASE_DIR / org_id


def _logo_path(org_id: str, size_name: str, ext: str) -> Path:
    return _logo_dir(org_id) / f"{size_name}.{ext}"


def _logo_url(org_id: str, size_name: str, ext: str) -> str:
    """Canonical public URL — must match the StaticFiles mount in main.py."""
    return f"/uploads/logos/{org_id}/{size_name}.{ext}"


def _remove_existing_logo_files(org_id: str) -> None:
    """Remove any existing large.* / small.* files in the org's logo dir.

    Iterates the extensions whitelist rather than relying on the current
    branding.logo_url so we handle the format-change-on-replace case
    cleanly (e.g., user uploaded a PNG, now uploads a JPEG; both files
    should be replaced, leaving no stale PNGs behind).
    """
    org_dir = _logo_dir(org_id)
    if not org_dir.exists():
        return
    for size_name in SIZES_BY_NAME:
        for ext in _ALL_LOGO_EXTS:
            p = _logo_path(org_id, size_name, ext)
            if p.exists():
                try:
                    p.unlink()
                except OSError as exc:
                    log.warning(
                        "failed to remove old logo file %s: %s", p, exc
                    )


# ---------------------------------------------------------------------------
# Permission helpers
# ---------------------------------------------------------------------------

def _resolve_org_or_404(db: Session, slug: str) -> models.Organization:
    org = db.query(models.Organization).filter(
        models.Organization.slug == slug
    ).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


def _require_branding_permission(
    db: Session, user_id: str, org: models.Organization,
) -> None:
    """Gate every branding endpoint on ``org.edit_branding``.

    Returns None on success; raises HTTPException(403) otherwise. The
    same gate fires whether the caller is a non-member, a member without
    the permission, or has it disabled in the matrix — the underlying
    ``has_permission`` returns False uniformly.
    """
    if not has_permission(db, user_id, org.id, "org.edit_branding"):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to edit organization branding.",
        )


# ---------------------------------------------------------------------------
# Logo: upload (B1)
# ---------------------------------------------------------------------------

@router.post("/{org_slug}/logo", status_code=status.HTTP_200_OK)
async def upload_org_logo(
    org_slug: str,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Upload + resize an organization's logo.

    Validates content-type + size, decodes via Pillow, resizes
    proportionally to fit within both bounding boxes (large: 400x160,
    small: 200x80), writes both files, removes any prior logo files
    (across all extensions), updates ``Organization.settings.branding.logo_url``,
    and emits an ``org.logo_uploaded`` audit event.

    Returns ``{logo_url, logo_url_small, content_type, ext, sizes}``
    where the URLs are the public ``/uploads/...`` paths. The large URL
    matches what's persisted to settings.
    """
    org = _resolve_org_or_404(db, org_slug)
    _require_branding_permission(db, current_user.id, org)

    # Content-type whitelist — reject before reading the body.
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Unsupported image type {file.content_type!r}. "
                "Allowed: image/jpeg, image/png, image/webp."
            ),
        )

    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Logo exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB "
                "pre-resize limit."
            ),
        )

    if not raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty file upload.",
        )

    # Decode + validate via Pillow. Catch broadly because corrupt bytes
    # should hit a 400, not a 500.
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not decode image: {exc}",
        )

    ext = _EXT_BY_CONTENT_TYPE[file.content_type]
    pil_format = _PIL_FORMAT_BY_CONTENT_TYPE[file.content_type]

    # JPEG can't carry alpha; if the input is RGBA-mode under a JPEG
    # content-type (rare but possible), flatten to RGB. PNG/WEBP keep
    # their alpha.
    if pil_format == "JPEG" and img.mode in ("RGBA", "LA", "P"):
        # Composite onto white so transparent pixels don't go black.
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        background.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
        img = background
    elif pil_format == "JPEG" and img.mode != "RGB":
        img = img.convert("RGB")

    # Replace-existing semantics: clear out any prior files (across all
    # extensions) before writing new ones, so a format change leaves
    # nothing stale behind.
    _remove_existing_logo_files(org.id)
    org_dir = _logo_dir(org.id)
    org_dir.mkdir(parents=True, exist_ok=True)

    # Resize proportionally to fit each bounding box. PIL.thumbnail()
    # mutates in place and preserves aspect ratio — use a copy so the
    # second resize starts from the original full-resolution image, not
    # the small one.
    written_paths: dict[str, Path] = {}
    for size_name, max_dims in SIZES_BY_NAME.items():
        resized = img.copy()
        resized.thumbnail(max_dims, Image.LANCZOS)
        out_path = _logo_path(org.id, size_name, ext)
        save_kwargs: dict = {}
        if pil_format == "JPEG":
            save_kwargs["quality"] = 90
        elif pil_format == "WEBP":
            save_kwargs["quality"] = 90
            save_kwargs["method"] = 4
        resized.save(out_path, format=pil_format, **save_kwargs)
        written_paths[size_name] = out_path

    new_url_large = _logo_url(org.id, "large", ext)
    new_url_small = _logo_url(org.id, "small", ext)

    # Persist the canonical large URL into settings.branding.logo_url.
    # Use the spread-merge pattern (explicitly assigning a new dict
    # rather than mutating in place) so SQLAlchemy's change detection
    # picks it up — this is the same pattern enforced by the org_settings
    # tests after the Phase 4c JSON-mutation bug.
    current_settings = dict(org.settings or {})
    branding = dict(current_settings.get("branding") or {})
    branding["logo_url"] = new_url_large
    current_settings["branding"] = branding
    org.settings = current_settings

    log_audit_event(
        db,
        action="org.logo_uploaded",
        target_type="organization",
        target_id=org.id,
        actor_id=current_user.id,
        details={
            "content_type": file.content_type,
            "input_bytes": len(raw),
            "ext": ext,
            "logo_url": new_url_large,
        },
        ip_address=request.client.host if request.client else None,
    )
    db.commit()

    return {
        "logo_url": new_url_large,
        "logo_url_small": new_url_small,
        "content_type": file.content_type,
        "ext": ext,
        "sizes": list(SIZES_BY_NAME.keys()),
    }


# ---------------------------------------------------------------------------
# Logo: delete (B1)
# ---------------------------------------------------------------------------

@router.delete("/{org_slug}/logo", status_code=status.HTTP_204_NO_CONTENT)
def delete_org_logo(
    org_slug: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Remove an organization's logo files and clear branding.logo_url.

    Idempotent — returns 204 whether or not a logo existed. Audit event
    only fires when there was actually a logo to remove (matches the
    avatar-delete pattern, keeps the audit log noise-free).
    """
    org = _resolve_org_or_404(db, org_slug)
    _require_branding_permission(db, current_user.id, org)

    branding_dict = (org.settings or {}).get("branding") or {}
    had_logo = bool(branding_dict.get("logo_url"))

    # Always remove files on disk regardless of settings state — this
    # also cleans up any orphan files (e.g., from a prior partial write).
    _remove_existing_logo_files(org.id)

    if had_logo:
        current_settings = dict(org.settings or {})
        branding = dict(current_settings.get("branding") or {})
        branding["logo_url"] = None
        current_settings["branding"] = branding
        org.settings = current_settings

        log_audit_event(
            db,
            action="org.logo_removed",
            target_type="organization",
            target_id=org.id,
            actor_id=current_user.id,
            details={},
            ip_address=request.client.host if request.client else None,
        )
        db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Branding: PATCH colors (B2)
# ---------------------------------------------------------------------------

@router.patch("/{org_slug}/branding", response_model=schemas.OrgOut)
def update_org_branding(
    org_slug: str,
    body: schemas.BrandingUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Set primary/accent colors + accent_auto_derived on an org's branding.

    Partial-update semantics:
      - Keys absent from the request body are left unchanged.
      - Keys present with ``null`` clear the value (frontend will then
        use platform defaults for that color).
      - ``accent_auto_derived`` is a flag the frontend uses to decide
        whether to recompute the accent on primary changes; backend
        just stores what it's told.

    Returns the updated org via the standard OrgOut shape (same as
    PATCH /api/orgs/{slug}) so the client can update its cached state
    without a separate GET. Audit event ``org.branding_updated`` fires
    with the diff when at least one field actually changed.

    Permission: ``org.edit_branding``. The logo_url is NOT settable via
    this endpoint — it's managed via POST/DELETE /logo.
    """
    org = _resolve_org_or_404(db, org_slug)
    _require_branding_permission(db, current_user.id, org)

    # exclude_unset=True distinguishes "key absent in request body"
    # (leave unchanged) from "key present with null" (clear). Both have
    # the same Python value (None) but only the latter shows up here.
    requested = body.model_dump(exclude_unset=True)
    if not requested:
        # Empty PATCH — return current state without touching settings
        # or audit log. Trivially valid; frontend may submit an empty
        # body during a save with no edits.
        from routes.organizations import _org_to_out
        return _org_to_out(org, db, current_user.id)

    current_settings = dict(org.settings or {})
    branding = dict(current_settings.get("branding") or {})

    # Phase 14 B4 — intro_text lives at the top level of settings (not
    # nested under settings.branding) since it's conceptually independent
    # of color/logo branding even though it ships through the same PATCH
    # endpoint. Pop it out of the branding-key loop so it doesn't get
    # written into settings.branding.intro_text by mistake.
    intro_text_change: Optional[dict] = None
    if "intro_text" in requested:
        new_intro = requested.pop("intro_text")
        old_intro = current_settings.get("intro_text")
        if old_intro != new_intro:
            intro_text_change = {"old": old_intro, "new": new_intro}
        current_settings["intro_text"] = new_intro

    # Diff against current state to build the audit event payload. Only
    # actually-changed fields end up in the diff so the audit log isn't
    # littered with no-op rows.
    diff: dict[str, dict] = {}
    for key, new_val in requested.items():
        old_val = branding.get(key)
        if old_val != new_val:
            diff[key] = {"old": old_val, "new": new_val}
        branding[key] = new_val

    if intro_text_change is not None:
        diff["intro_text"] = intro_text_change

    current_settings["branding"] = branding
    org.settings = current_settings

    if diff:
        log_audit_event(
            db,
            action="org.branding_updated",
            target_type="organization",
            target_id=org.id,
            actor_id=current_user.id,
            details={"changes": diff},
            ip_address=request.client.host if request.client else None,
        )

    db.commit()
    db.refresh(org)

    # Reuse the canonical org serializer so the response shape exactly
    # matches GET /api/orgs/{slug} (including the branding object,
    # member_count, user_role, user_permissions). Late import avoids the
    # circular dependency at module-import time.
    from routes.organizations import _org_to_out
    return _org_to_out(org, db, current_user.id)
