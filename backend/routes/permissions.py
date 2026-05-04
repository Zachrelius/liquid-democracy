"""Phase 12 Stage 1 — Permission registry endpoint (Cluster H, H4).

Exposes the full permission vocabulary as a static read-only endpoint
that Stage 2's admin matrix UI consumes to render its rows + grouping.

Auth: any authenticated user. No role gate beyond authentication —
the registry is metadata, not configuration. Per-org permission
configuration lives behind separate Stage 2 endpoints.

Static endpoint — no DB query, no per-org branching. Cache headers
can be aggressive (the registry only changes when the codebase ships
a new permission key).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

import auth as auth_utils
import models
from permission_registry import CATEGORIES, PERMISSION_REGISTRY


router = APIRouter(prefix="/api/permissions", tags=["permissions"])


@router.get("/registry")
def get_permission_registry(
    current_user: models.User = Depends(auth_utils.get_current_user),
) -> dict:
    """Return the full permission registry plus the canonical category list.

    Response shape (consumed by Stage 2's matrix UI):
        {
          "permissions": [
            {"key": "...", "label": "...", "description": "...", "category": "..."},
            ...23 entries...
          ],
          "categories": ["Proposals", "Topics", ...9 entries...]
        }
    """
    return {
        "permissions": [
            {
                "key": entry.key,
                "label": entry.label,
                "description": entry.description,
                "category": entry.category,
            }
            for entry in PERMISSION_REGISTRY
        ],
        "categories": list(CATEGORIES),
    }
