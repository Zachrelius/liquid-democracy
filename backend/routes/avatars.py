"""Phase 9.8 W A1 — avatar upload, resize, and serve endpoints.

POST /api/users/me/avatar
    Multipart upload. Whitelisted content types: image/jpeg, image/png,
    image/webp. Max 6 MB pre-resize (relaxed from 2 MB in Phase 9.9 W2 to
    accommodate typical phone-photo sizes when client-side resize is
    bypassed; real uploads from a modern browser arrive at ~30 KB after
    canvas downsample). Pillow resizes to 128x128 and 48x48, saved as JPEG
    quality 85 to ``backend/uploads/avatars/{user_id}/{128|48}.jpg``.
    Updates ``users.avatar_url`` to the canonical 128 path. Audited as
    ``user.avatar_uploaded`` with input size info. Replacing an existing
    avatar removes the old files first.

DELETE /api/users/me/avatar
    Removes both files and nulls ``users.avatar_url``. Audited as
    ``user.avatar_removed``. Returns 204 even if no avatar was set
    (idempotent — easier to reason about than 404 here).

The static-files mount that serves the resulting URLs lives in main.py.
The path constant ``AVATARS_BASE_DIR`` is module-level so tests can monkey-
patch it to a tmp_path and exercise the full resize pipeline without
polluting the real ``backend/uploads/`` tree.
"""
from __future__ import annotations

import io
import logging
import os
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from PIL import Image
# Phase 40 B2 D4 (2026-05-27) — defense against decompression bombs. Pillow's
# default MAX_IMAGE_PIXELS (~178 MP) allows a small JPEG to decode to GB of
# RAM. 25 MP is generous for a phone camera (~6000×4000) and tight enough to
# make decompression bombs unprofitable. Combines with the existing 6 MB
# pre-resize byte cap below.
Image.MAX_IMAGE_PIXELS = 25_000_000
from sqlalchemy.orm import Session

import auth as auth_utils
import models
from audit_utils import log_audit_event
from database import get_db


log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/users/me/avatar", tags=["avatars"])


# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

# Module-level so tests can monkeypatch to a tmp_path. The corresponding
# StaticFiles mount in main.py reads the same constant so they stay in sync.
_BACKEND_DIR = Path(__file__).resolve().parent.parent


def _resolve_uploads_base() -> Path:
    """Phase 25 B3 (revised after first-deploy 502) — env-driven uploads
    base directory with a writability fallback.

    Resolution order:
      1. ``UPLOAD_DIR`` (Phase 25 canonical name) — overrides everything.
         Tests set this to a pytest ``tmp_path`` so each test run uses
         an isolated tmpdir.
      2. ``UPLOADS_BASE_DIR`` (Phase 12.7 legacy name) — backward-compat
         alias.
      3. ``/data/uploads`` if the Railway Volume mount is writable from
         the app process. The Phase 25 initial deploy hard-defaulted to
         this path without a fallback and crashed startup with
         PermissionError because the volume mount was owned by root and
         appuser couldn't mkdir inside it. The writability probe below
         restores the Phase 12.7 fallback so an unwritable mount
         degrades to ephemeral storage with a startup warning rather
         than a 502.
      4. Fallback to in-image ``backend/uploads`` (ephemeral on Railway).
         The main.py startup hook logs a warning when the resolved
         path isn't under ``/data/`` so the operator sees the state.

    Volume mount ownership is the real ops fix (Dockerfile runs as
    appuser; Railway mounts /data/uploads as root). Tracked as deferred
    work; until then this fallback keeps deploys safe.
    """
    explicit = os.environ.get("UPLOAD_DIR") or os.environ.get("UPLOADS_BASE_DIR")
    if explicit:
        return Path(explicit)
    railway_volume = Path("/data/uploads")
    try:
        # Probe parent writability first — mkdir(.., parents=True,
        # exist_ok=True) creates /data/uploads if absent then the
        # avatars/logos subdirs inside it. Need write access to /data.
        if railway_volume.parent.exists() and os.access(
            railway_volume.parent, os.W_OK,
        ):
            return railway_volume
        # /data/uploads itself may exist (mounted) even when /data
        # isn't writable. Test it directly.
        if railway_volume.exists() and os.access(railway_volume, os.W_OK):
            return railway_volume
    except OSError:
        pass
    return _BACKEND_DIR / "uploads"


UPLOADS_BASE_DIR: Path = _resolve_uploads_base()
AVATARS_BASE_DIR: Path = UPLOADS_BASE_DIR / "avatars"
# Phase 12.7 B1 — org logos live alongside avatars on the same Volume.
# Path scheme: LOGOS_BASE_DIR / {org_id} / {large|small}.{ext}
LOGOS_BASE_DIR: Path = UPLOADS_BASE_DIR / "logos"

ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset({
    "image/jpeg",
    "image/png",
    "image/webp",
})

MAX_UPLOAD_BYTES: int = 6 * 1024 * 1024  # 6 MB pre-resize (Phase 9.9 W2)

JPEG_QUALITY: int = 85
SIZES: tuple[int, ...] = (128, 48)


def _avatar_dir(user_id: str) -> Path:
    """Per-user directory holding the two resized JPEGs."""
    return AVATARS_BASE_DIR / user_id


def _avatar_path(user_id: str, size: int) -> Path:
    return _avatar_dir(user_id) / f"{size}.jpg"


def _avatar_url(user_id: str, size: int) -> str:
    """Canonical URL — must match the StaticFiles mount in main.py."""
    return f"/uploads/avatars/{user_id}/{size}.jpg"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", status_code=status.HTTP_200_OK)
async def upload_avatar(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Upload + resize the calling user's avatar.

    Pre-resize body limit is 6 MB (Phase 9.9 W2). The frontend now does a
    client-side canvas downsample before POSTing, so real-world bodies
    arrive at ~30 KB; the 6 MB ceiling is defense-in-depth for the case
    where the client-side resize is bypassed (very old browser, JS error,
    direct API call) without forcing real users to compress phone photos
    themselves.

    Returns ``{avatar_url, avatar_url_small}``. The 128 URL is what gets
    stored on ``User.avatar_url`` and surfaced in user-shape responses; the
    48 URL is computed deterministically by callers but returned here for
    clients that want both sizes immediately.
    """
    # Content-type whitelist — reject before reading the body.
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Unsupported image type {file.content_type!r}. "
                "Allowed: image/jpeg, image/png, image/webp."
            ),
        )

    # Read up to MAX_UPLOAD_BYTES + 1 so we can distinguish "right at the
    # limit" from "over". Spool back into BytesIO for Pillow.
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Avatar exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB "
                "pre-resize limit."
            ),
        )

    if not raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty file upload.",
        )

    # Decode + resize via Pillow. Catch broad exceptions because corrupt
    # uploads should hit a 400, not a 500.
    # Phase 40 B2 (2026-05-27) — explicit pre-load size check. Pillow's
    # MAX_IMAGE_PIXELS only triggers DecompressionBombError at 2× the
    # configured value; an explicit width*height check before .load() makes
    # the user-facing 25 MP message accurate at the actual threshold and
    # avoids loading any pixels into memory when the image is over the cap.
    try:
        img = Image.open(io.BytesIO(raw))
        if img.size[0] * img.size[1] > 25_000_000:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Image dimensions exceed the supported limit "
                    "(25 megapixels). Resize before uploading."
                ),
            )
        img.load()
    except HTTPException:
        raise
    except Image.DecompressionBombError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Image dimensions exceed the supported limit "
                "(25 megapixels). Resize before uploading."
            ),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not decode image: {exc}",
        )

    # Convert any mode to RGB so JPEG encode works regardless of input
    # (PNG with alpha, WebP, palette images, etc.).
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    elif img.mode == "L":
        img = img.convert("RGB")

    # Replace-existing semantics: clean the user's directory first so any
    # old files that don't match the new size set get removed, then write
    # both sizes fresh.
    user_dir = _avatar_dir(current_user.id)
    if user_dir.exists():
        shutil.rmtree(user_dir, ignore_errors=True)
    user_dir.mkdir(parents=True, exist_ok=True)

    for size in SIZES:
        # LANCZOS gives the cleanest down-sample for photos at small sizes.
        resized = img.resize((size, size), Image.LANCZOS)
        resized.save(_avatar_path(current_user.id, size), format="JPEG", quality=JPEG_QUALITY)

    new_url = _avatar_url(current_user.id, 128)
    new_url_small = _avatar_url(current_user.id, 48)

    current_user.avatar_url = new_url
    log_audit_event(
        db,
        action="user.avatar_uploaded",
        target_type="user",
        target_id=current_user.id,
        actor_id=current_user.id,
        details={
            "content_type": file.content_type,
            "input_bytes": len(raw),
            "sizes": list(SIZES),
        },
    )
    db.commit()

    return {"avatar_url": new_url, "avatar_url_small": new_url_small}


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_avatar(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Remove both avatar files and null ``avatar_url``.

    Idempotent: returns 204 whether or not an avatar existed. We always
    audit when the column was non-null at entry; calls against a NULL column
    skip the audit so we don't fill the log with no-ops.
    """
    had_avatar = current_user.avatar_url is not None

    user_dir = _avatar_dir(current_user.id)
    if user_dir.exists():
        shutil.rmtree(user_dir, ignore_errors=True)

    if had_avatar:
        current_user.avatar_url = None
        log_audit_event(
            db,
            action="user.avatar_removed",
            target_type="user",
            target_id=current_user.id,
            actor_id=current_user.id,
            details={},
        )
        db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
