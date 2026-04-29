from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

import auth as auth_utils
import models
import schemas
from database import get_db

router = APIRouter(prefix="/api/topics", tags=["topics"])


@router.get("", response_model=list[schemas.TopicOut])
def list_topics(
    org_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(auth_utils.get_optional_user),
):
    """List topics, filtered by viewer scope (Phase 8.6 — Decision 3 carry-forward).

    Sub-org-scoped topics (sub_org_id IS NOT NULL) are visible only to:
      - users who are active SubOrgMembership members of that sub-org, OR
      - parent-org admins/owners (Decision 6 implicit power)

    Parent-org-wide topics (sub_org_id IS NULL) are always visible.

    Mirrors the filter applied to ``/api/orgs/{slug}/topics`` and the proposal
    list (``routes.organizations.list_org_proposals``). The unscoped global
    ``/api/topics`` endpoint is hit by the personal Settings / Delegations
    pages when the user has no current-org context, but Decision 3 still
    requires that sub-org topics not leak to non-members.

    Anonymous callers (no auth header) see only parent-org-wide topics —
    strict default; never leak sub-org-scoped topics to a session that
    can't be resolved to a SubOrgMembership.
    """
    q = db.query(models.Topic)
    if org_id:
        q = q.filter(models.Topic.org_id == org_id)
    all_topics = q.order_by(models.Topic.name).all()

    if current_user is None:
        return [t for t in all_topics if t.sub_org_id is None]

    # Resolve the set of (org_id) for which the user is a parent-org admin.
    parent_admin_org_ids = {
        row.org_id for row in db.query(models.OrgMembership.org_id).filter(
            models.OrgMembership.user_id == current_user.id,
            models.OrgMembership.status == "active",
            models.OrgMembership.role.in_(("admin", "owner")),
        ).all()
    }

    # Resolve sub-orgs the current user belongs to (across all parents).
    visible_sub_org_ids = {
        row.sub_org_id for row in db.query(
            models.SubOrgMembership.sub_org_id
        ).filter(
            models.SubOrgMembership.user_id == current_user.id,
            models.SubOrgMembership.status == "active",
        ).all()
    }

    return [
        t for t in all_topics
        if t.sub_org_id is None
        or t.sub_org_id in visible_sub_org_ids
        or t.org_id in parent_admin_org_ids
    ]


@router.post("", response_model=schemas.TopicOut, status_code=status.HTTP_201_CREATED)
def create_topic(
    body: schemas.TopicCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_admin),
):
    if db.query(models.Topic).filter(models.Topic.name == body.name).first():
        raise HTTPException(status_code=400, detail="Topic name already exists")
    topic = models.Topic(**body.model_dump())
    db.add(topic)
    db.commit()
    db.refresh(topic)
    return topic
