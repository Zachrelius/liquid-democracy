"""Phase 77 — Org-scoped direct messaging.

Three messaging surfaces (delegate, org inbox, member DM) share one
Conversation + Message model, differentiated by ``conversation_type`` and
the gate that controls who can initiate. See
``phase77_org_scoped_messaging_2026-06-20.md`` for the full design.

Route convention note: the spec wrote ``/api/orgs/{org_id}/...`` but the
entire platform addresses org-scoped routes by ``{org_slug}`` (and the FE
builds URLs from slugs via ``urlFor``). This module follows the platform
convention — ``{org_slug}`` — for consistency; the org is resolved to its
id internally.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

import auth as auth_utils
import models
import schemas
import verification
from database import get_db
from notification_emit import emit_notification
from role_permissions import has_permission


log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/orgs", tags=["messages"])

CONVERSATION_TYPES = {"direct", "delegate", "org_inbox"}
RATE_LIMIT_PER_HOUR = 20
PREVIEW_LEN = 100


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_naive() -> datetime:
    """Naive UTC — matches how the DateTime columns store values (SQLAlchemy
    strips tz under SQLite/PG DateTime-without-tz)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _org_or_404(db: Session, org_slug: str) -> models.Organization:
    org = (
        db.query(models.Organization)
        .filter(models.Organization.slug == org_slug)
        .first()
    )
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


def _active_membership_or_404(
    db: Session, user_id: str, org_id: str
) -> models.OrgMembership:
    m = (
        db.query(models.OrgMembership)
        .filter(
            models.OrgMembership.user_id == user_id,
            models.OrgMembership.org_id == org_id,
            models.OrgMembership.status == "active",
        )
        .first()
    )
    if m is None:
        # Hide the org from non-members (matches the rest of the platform).
        raise HTTPException(status_code=404, detail="Organization not found")
    return m


def _is_active_member(db: Session, user_id: str, org_id: str) -> bool:
    return (
        db.query(models.OrgMembership)
        .filter(
            models.OrgMembership.user_id == user_id,
            models.OrgMembership.org_id == org_id,
            models.OrgMembership.status == "active",
        )
        .first()
        is not None
    )


def _conversation_or_404(
    db: Session, conv_id: str, org_id: str
) -> models.Conversation:
    c = db.get(models.Conversation, conv_id)
    if c is None or c.org_id != org_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return c


def _can_view_org_inbox(db: Session, user_id: str, org_id: str) -> bool:
    return has_permission(db, user_id, org_id, "org_inbox.view")


def _is_participant(
    db: Session, conv: models.Conversation, user_id: str
) -> bool:
    if user_id == conv.initiator_id or user_id == conv.recipient_id:
        return True
    if conv.conversation_type == "org_inbox" and _can_view_org_inbox(
        db, user_id, conv.org_id
    ):
        return True
    return False


def _has_block(db: Session, blocker_id: str, blocked_id: str, org_id: str) -> bool:
    return (
        db.query(models.MessageBlock)
        .filter(
            models.MessageBlock.blocker_id == blocker_id,
            models.MessageBlock.blocked_id == blocked_id,
            models.MessageBlock.org_id == org_id,
        )
        .first()
        is not None
    )


def _has_follow_either_direction(
    db: Session, a_id: str, b_id: str, org_id: str
) -> bool:
    return (
        db.query(models.FollowRelationship)
        .filter(
            models.FollowRelationship.org_id == org_id,
            or_(
                (models.FollowRelationship.follower_id == a_id)
                & (models.FollowRelationship.followed_id == b_id),
                (models.FollowRelationship.follower_id == b_id)
                & (models.FollowRelationship.followed_id == a_id),
            ),
        )
        .first()
        is not None
    )


def _delegate_messageable(
    db: Session, sender_id: str, recipient_id: str, org_id: str
) -> bool:
    """True iff the recipient has a delegate profile in this org whose
    visibility the sender can reach (access matrix §delegate)."""
    profiles = (
        db.query(models.DelegateProfile)
        .filter(
            models.DelegateProfile.user_id == recipient_id,
            or_(
                models.DelegateProfile.org_id == org_id,
                models.DelegateProfile.org_id.is_(None),
            ),
        )
        .all()
    )
    for p in profiles:
        if p.visibility in ("public", "public_accepting"):
            return True
        if p.visibility == "followers_only":
            # sender must follow recipient (one direction, per spec).
            follows = (
                db.query(models.FollowRelationship)
                .filter(
                    models.FollowRelationship.org_id == org_id,
                    models.FollowRelationship.follower_id == sender_id,
                    models.FollowRelationship.followed_id == recipient_id,
                )
                .first()
            )
            if follows is not None:
                return True
        # "private" → not messageable via this surface.
    return False


def _resolve_display_name(db: Session, user_id: str, org: models.Organization) -> str:
    user = db.get(models.User, user_id)
    if user is None:
        return ""
    membership = (
        db.query(models.OrgMembership)
        .filter(
            models.OrgMembership.user_id == user_id,
            models.OrgMembership.org_id == org.id,
        )
        .first()
    )
    return verification.display_name_for(user, org, membership=membership)


def _unread_count(db: Session, conv_id: str, viewer_id: str) -> int:
    read = (
        db.query(models.ConversationRead)
        .filter(
            models.ConversationRead.user_id == viewer_id,
            models.ConversationRead.conversation_id == conv_id,
        )
        .first()
    )
    q = db.query(models.Message).filter(
        models.Message.conversation_id == conv_id,
        models.Message.sender_id != viewer_id,
    )
    if read is not None:
        q = q.filter(models.Message.created_at > read.last_read_at)
    return q.count()


def _last_message(db: Session, conv_id: str) -> Optional[models.Message]:
    return (
        db.query(models.Message)
        .filter(models.Message.conversation_id == conv_id)
        .order_by(models.Message.created_at.desc())
        .first()
    )


def _build_conversation_out(
    db: Session,
    conv: models.Conversation,
    viewer_id: str,
    org: models.Organization,
) -> schemas.ConversationOut:
    # Resolve the "other party" from the viewer's perspective.
    other_id: Optional[str]
    other_name: str
    if conv.conversation_type == "org_inbox" and viewer_id == conv.initiator_id:
        # Member side of the org inbox — the counterpart is the org itself.
        other_id = None
        other_name = "Org Inbox"
    else:
        other_id = (
            conv.recipient_id if viewer_id == conv.initiator_id else conv.initiator_id
        )
        other_name = _resolve_display_name(db, other_id, org) if other_id else "Org Inbox"

    last = _last_message(db, conv.id)
    preview = None
    if last is not None and last.body:
        preview = last.body[:PREVIEW_LEN]

    return schemas.ConversationOut(
        id=conv.id,
        org_id=conv.org_id,
        conversation_type=conv.conversation_type,
        initiator_id=conv.initiator_id,
        recipient_id=conv.recipient_id,
        subject=conv.subject,
        context_proposal_id=conv.context_proposal_id,
        status=conv.status,
        last_message_at=conv.last_message_at,
        created_at=conv.created_at,
        other_party_display_name=other_name,
        other_party_id=other_id,
        unread_count=_unread_count(db, conv.id, viewer_id),
        last_message_preview=preview,
    )


def _build_message_out(
    db: Session, msg: models.Message, org: models.Organization
) -> schemas.MessageOut:
    return schemas.MessageOut(
        id=msg.id,
        conversation_id=msg.conversation_id,
        sender_id=msg.sender_id,
        sender_display_name=_resolve_display_name(db, msg.sender_id, org),
        body=msg.body,
        is_system=msg.is_system,
        created_at=msg.created_at,
    )


def _enforce_rate_limit(db: Session, user_id: str, org_id: str) -> None:
    """20 messages/hour/user/org (D11). DB-count based (per-user-per-org,
    which the IP-keyed slowapi limiter can't express)."""
    cutoff = _now_naive() - timedelta(hours=1)
    count = (
        db.query(models.Message)
        .join(models.Conversation, models.Message.conversation_id == models.Conversation.id)
        .filter(
            models.Conversation.org_id == org_id,
            models.Message.sender_id == user_id,
            models.Message.created_at >= cutoff,
        )
        .count()
    )
    if count >= RATE_LIMIT_PER_HOUR:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Message rate limit reached. Please try again later.",
        )


def _proposal_summary(db: Session, proposal_id: Optional[str]) -> Optional[dict]:
    if not proposal_id:
        return None
    p = db.get(models.Proposal, proposal_id)
    if p is None:
        return None
    return {"id": p.id, "title": p.title, "status": p.status}


# ---------------------------------------------------------------------------
# Message send + notification (shared by create + send-message)
# ---------------------------------------------------------------------------

def _emit_message_notifications(
    db: Session,
    background_tasks: BackgroundTasks,
    conv: models.Conversation,
    sender_id: str,
    org: models.Organization,
    preview: str,
) -> None:
    """Notification emission rules (spec §Notification emission). Wrapped by
    the caller's try/except is not needed — each emit is itself guarded."""
    sender_name = _resolve_display_name(db, sender_id, org)
    base_payload = {
        "conversation_id": conv.id,
        "sender_display_name": sender_name,
        "preview": preview,
        "org_id": org.id,
        "org_slug": org.slug,
        "org_name": org.name,
    }

    def _safe_emit(user_id: str, event_type: str, extra: Optional[dict] = None):
        if user_id == sender_id:
            return
        try:
            payload = dict(base_payload)
            if extra:
                payload.update(extra)
            emit_notification(
                db,
                background_tasks,
                event_type=event_type,
                user_id=user_id,
                org_id=org.id,
                actor_id=sender_id,
                target_type="conversation",
                target_id=conv.id,
                payload=payload,
            )
        except Exception:  # pragma: no cover - defensive
            log.exception(
                "message notification emit failed user=%s event=%s",
                user_id, event_type,
            )

    if conv.conversation_type == "org_inbox":
        if sender_id == conv.initiator_id:
            # Member → org: notify every org_inbox.view holder.
            members = (
                db.query(models.OrgMembership)
                .filter(
                    models.OrgMembership.org_id == org.id,
                    models.OrgMembership.status == "active",
                )
                .all()
            )
            for m in members:
                if _can_view_org_inbox(db, m.user_id, org.id):
                    _safe_emit(m.user_id, "message.org_inbox")
        else:
            # Admin reply → notify the initiator only.
            _safe_emit(
                conv.initiator_id,
                "message.received",
                {"conversation_type": "org_inbox",
                 "context_proposal_id": conv.context_proposal_id},
            )
        return

    # direct / delegate: notify the other participant.
    other_id = (
        conv.recipient_id if sender_id == conv.initiator_id else conv.initiator_id
    )
    if other_id:
        _safe_emit(
            other_id,
            "message.received",
            {"conversation_type": conv.conversation_type,
             "context_proposal_id": conv.context_proposal_id},
        )


def _send_message(
    db: Session,
    background_tasks: BackgroundTasks,
    conv: models.Conversation,
    sender_id: str,
    org: models.Organization,
    body: str,
    *,
    enforce_block: bool = True,
) -> models.Message:
    """Insert a message, update denorm fields, reopen, mark sender read, and
    emit notifications. Caller has already verified participation + body."""
    # Block check: the OTHER participant must not have blocked the sender.
    # (Org-inbox: no block enforcement — it's an org surface, D-matrix.)
    if enforce_block and conv.conversation_type != "org_inbox":
        other_id = (
            conv.recipient_id if sender_id == conv.initiator_id else conv.initiator_id
        )
        if other_id and _has_block(db, other_id, sender_id, org.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "unable_to_send"},
            )

    _enforce_rate_limit(db, sender_id, org.id)

    cleaned = body.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Message body cannot be empty.")

    msg = models.Message(
        conversation_id=conv.id,
        sender_id=sender_id,
        body=cleaned,
        is_system=False,
    )
    db.add(msg)
    conv.last_message_at = _now_naive()
    if conv.status == "closed":
        conv.status = "active"  # reopen on new message (D5 / send rules)
    db.flush()

    # Sender has implicitly read their own message.
    _mark_read(db, conv.id, sender_id)

    db.commit()
    db.refresh(msg)
    db.refresh(conv)

    _emit_message_notifications(
        db, background_tasks, conv, sender_id, org, cleaned[:PREVIEW_LEN],
    )
    db.commit()
    return msg


def _mark_read(db: Session, conv_id: str, user_id: str) -> None:
    read = (
        db.query(models.ConversationRead)
        .filter(
            models.ConversationRead.user_id == user_id,
            models.ConversationRead.conversation_id == conv_id,
        )
        .first()
    )
    if read is None:
        read = models.ConversationRead(
            user_id=user_id,
            conversation_id=conv_id,
            last_read_at=_now_naive(),
        )
        db.add(read)
    else:
        read.last_read_at = _now_naive()


# ---------------------------------------------------------------------------
# Conversation list + create
# ---------------------------------------------------------------------------

@router.get("/{org_slug}/conversations", response_model=list[schemas.ConversationOut])
def list_conversations(
    org_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    org = _org_or_404(db, org_slug)
    _active_membership_or_404(db, current_user.id, org.id)

    clauses = [
        models.Conversation.initiator_id == current_user.id,
        models.Conversation.recipient_id == current_user.id,
    ]
    if _can_view_org_inbox(db, current_user.id, org.id):
        clauses.append(models.Conversation.conversation_type == "org_inbox")

    convs = (
        db.query(models.Conversation)
        .filter(
            models.Conversation.org_id == org.id,
            or_(*clauses),
        )
        .order_by(models.Conversation.last_message_at.desc().nullslast(),
                  models.Conversation.created_at.desc())
        .all()
    )
    return [_build_conversation_out(db, c, current_user.id, org) for c in convs]


@router.post(
    "/{org_slug}/conversations",
    response_model=schemas.ConversationOut,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation(
    org_slug: str,
    body: schemas.ConversationCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    org = _org_or_404(db, org_slug)
    _active_membership_or_404(db, current_user.id, org.id)

    ctype = body.conversation_type
    if ctype not in CONVERSATION_TYPES:
        raise HTTPException(status_code=400, detail="Unknown conversation type.")

    cleaned = body.body.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Message body cannot be empty.")

    # Optional context proposal must belong to this org.
    context_proposal_id = None
    if body.context_proposal_id:
        p = db.get(models.Proposal, body.context_proposal_id)
        if p is None or p.org_id != org.id:
            raise HTTPException(status_code=400, detail="Linked proposal not found in this organization.")
        context_proposal_id = p.id

    sender_id = current_user.id

    # ---- org_inbox ----
    if ctype == "org_inbox":
        existing = (
            db.query(models.Conversation)
            .filter(
                models.Conversation.org_id == org.id,
                models.Conversation.conversation_type == "org_inbox",
                models.Conversation.initiator_id == sender_id,
            )
            .first()
        )
        if existing is not None:
            if existing.status == "closed":
                existing.status = "active"
            db.flush()
            _send_message(db, background_tasks, existing, sender_id, org, cleaned, enforce_block=False)
            return _build_conversation_out(db, existing, sender_id, org)
        conv = models.Conversation(
            org_id=org.id,
            conversation_type="org_inbox",
            initiator_id=sender_id,
            recipient_id=None,
            subject=body.subject,
            context_proposal_id=context_proposal_id,
            status="active",
        )
        db.add(conv)
        db.flush()
        _send_message(db, background_tasks, conv, sender_id, org, cleaned, enforce_block=False)
        return _build_conversation_out(db, conv, sender_id, org)

    # direct + delegate share: recipient required, must be a distinct active member.
    recipient_id = body.recipient_id
    if not recipient_id:
        raise HTTPException(status_code=400, detail="recipient_id is required.")
    if recipient_id == sender_id:
        raise HTTPException(status_code=400, detail="You can't message yourself.")
    if not _is_active_member(db, recipient_id, org.id):
        raise HTTPException(status_code=400, detail="Recipient is not an active member of this organization.")

    # Dedup FIRST (D5: an existing conversation is always writable by both
    # parties, subject only to a block). Only the block gate applies on the
    # existing-conversation path; the creation gates apply only to genuinely
    # new conversations.
    existing = (
        db.query(models.Conversation)
        .filter(
            models.Conversation.org_id == org.id,
            models.Conversation.conversation_type == ctype,
            or_(
                (models.Conversation.initiator_id == sender_id)
                & (models.Conversation.recipient_id == recipient_id),
                (models.Conversation.initiator_id == recipient_id)
                & (models.Conversation.recipient_id == sender_id),
            ),
        )
        .first()
    )
    if existing is not None:
        _send_message(db, background_tasks, existing, sender_id, org, cleaned)
        return _build_conversation_out(db, existing, sender_id, org)

    # ---- creation gates for a NEW conversation ----
    if ctype == "delegate":
        if not _delegate_messageable(db, sender_id, recipient_id, org.id):
            raise HTTPException(status_code=403, detail={"error": "unable_to_send"})
        # dm_disabled NOT checked for delegate messages (public profile = consent).
        if _has_block(db, recipient_id, sender_id, org.id):
            raise HTTPException(status_code=403, detail={"error": "unable_to_send"})
    else:  # direct
        policy = (org.settings or {}).get("member_dm_policy", "follow_only")
        if policy == "disabled":
            raise HTTPException(status_code=403, detail={"error": "dm_policy_disabled"})
        if policy == "follow_only" and not _has_follow_either_direction(db, sender_id, recipient_id, org.id):
            raise HTTPException(status_code=403, detail={"error": "follow_required"})
        if _has_block(db, recipient_id, sender_id, org.id):
            raise HTTPException(status_code=403, detail={"error": "unable_to_send"})
        recipient = db.get(models.User, recipient_id)
        if recipient is not None and recipient.dm_disabled:
            raise HTTPException(status_code=403, detail={"error": "recipient_unavailable"})

    conv = models.Conversation(
        org_id=org.id,
        conversation_type=ctype,
        initiator_id=sender_id,
        recipient_id=recipient_id,
        subject=body.subject,
        context_proposal_id=context_proposal_id,
        status="active",
    )
    db.add(conv)
    db.flush()
    _send_message(db, background_tasks, conv, sender_id, org, cleaned)
    return _build_conversation_out(db, conv, sender_id, org)


# ---------------------------------------------------------------------------
# Conversation detail + messages
# ---------------------------------------------------------------------------

@router.get(
    "/{org_slug}/conversations/{conversation_id}",
    response_model=schemas.ConversationDetailOut,
)
def get_conversation(
    org_slug: str,
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    org = _org_or_404(db, org_slug)
    _active_membership_or_404(db, current_user.id, org.id)
    conv = _conversation_or_404(db, conversation_id, org.id)
    if not _is_participant(db, conv, current_user.id):
        raise HTTPException(status_code=403, detail="Not a participant in this conversation.")

    messages = (
        db.query(models.Message)
        .filter(models.Message.conversation_id == conv.id)
        .order_by(models.Message.created_at.asc())
        .all()
    )
    # Viewing marks the conversation read.
    _mark_read(db, conv.id, current_user.id)
    db.commit()

    return schemas.ConversationDetailOut(
        conversation=_build_conversation_out(db, conv, current_user.id, org),
        messages=[_build_message_out(db, m, org) for m in messages],
        context_proposal=_proposal_summary(db, conv.context_proposal_id),
    )


@router.post(
    "/{org_slug}/conversations/{conversation_id}/messages",
    response_model=schemas.MessageOut,
    status_code=status.HTTP_201_CREATED,
)
def send_message(
    org_slug: str,
    conversation_id: str,
    body: schemas.MessageCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    org = _org_or_404(db, org_slug)
    _active_membership_or_404(db, current_user.id, org.id)
    conv = _conversation_or_404(db, conversation_id, org.id)
    if not _is_participant(db, conv, current_user.id):
        raise HTTPException(status_code=403, detail="Not a participant in this conversation.")
    msg = _send_message(db, background_tasks, conv, current_user.id, org, body.body)
    return _build_message_out(db, msg, org)


@router.post("/{org_slug}/conversations/{conversation_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_conversation_read(
    org_slug: str,
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    org = _org_or_404(db, org_slug)
    _active_membership_or_404(db, current_user.id, org.id)
    conv = _conversation_or_404(db, conversation_id, org.id)
    if not _is_participant(db, conv, current_user.id):
        raise HTTPException(status_code=403, detail="Not a participant in this conversation.")
    _mark_read(db, conv.id, current_user.id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{org_slug}/conversations/{conversation_id}/close",
    response_model=schemas.ConversationOut,
)
def close_conversation(
    org_slug: str,
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    org = _org_or_404(db, org_slug)
    _active_membership_or_404(db, current_user.id, org.id)
    conv = _conversation_or_404(db, conversation_id, org.id)

    if conv.conversation_type == "org_inbox":
        if not _can_view_org_inbox(db, current_user.id, org.id):
            raise HTTPException(status_code=403, detail="Not allowed to close this conversation.")
    else:
        if current_user.id not in (conv.initiator_id, conv.recipient_id):
            raise HTTPException(status_code=403, detail="Not a participant in this conversation.")

    if conv.status != "closed":
        conv.status = "closed"
        closer_name = _resolve_display_name(db, current_user.id, org)
        sys_msg = models.Message(
            conversation_id=conv.id,
            sender_id=current_user.id,
            body=f"Conversation closed by {closer_name}.",
            is_system=True,
        )
        db.add(sys_msg)
        conv.last_message_at = _now_naive()
        db.commit()
        db.refresh(conv)

    return _build_conversation_out(db, conv, current_user.id, org)


# ---------------------------------------------------------------------------
# Org inbox
# ---------------------------------------------------------------------------

@router.get("/{org_slug}/org-inbox", response_model=list[schemas.ConversationOut])
def list_org_inbox(
    org_slug: str,
    status_filter: str = "active",
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    org = _org_or_404(db, org_slug)
    _active_membership_or_404(db, current_user.id, org.id)
    if not _can_view_org_inbox(db, current_user.id, org.id):
        raise HTTPException(status_code=403, detail="Not allowed to view the org inbox.")

    q = db.query(models.Conversation).filter(
        models.Conversation.org_id == org.id,
        models.Conversation.conversation_type == "org_inbox",
    )
    if status_filter in ("active", "closed"):
        q = q.filter(models.Conversation.status == status_filter)
    convs = q.order_by(
        models.Conversation.last_message_at.desc().nullslast(),
        models.Conversation.created_at.desc(),
    ).all()
    return [_build_conversation_out(db, c, current_user.id, org) for c in convs]


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------

def _build_block_out(db: Session, blk: models.MessageBlock, org: models.Organization) -> schemas.MessageBlockOut:
    return schemas.MessageBlockOut(
        id=blk.id,
        blocked_id=blk.blocked_id,
        blocked_display_name=_resolve_display_name(db, blk.blocked_id, org),
        org_id=blk.org_id,
        created_at=blk.created_at,
    )


@router.get("/{org_slug}/message-blocks", response_model=list[schemas.MessageBlockOut])
def list_blocks(
    org_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    org = _org_or_404(db, org_slug)
    _active_membership_or_404(db, current_user.id, org.id)
    blocks = (
        db.query(models.MessageBlock)
        .filter(
            models.MessageBlock.blocker_id == current_user.id,
            models.MessageBlock.org_id == org.id,
        )
        .order_by(models.MessageBlock.created_at.desc())
        .all()
    )
    return [_build_block_out(db, b, org) for b in blocks]


@router.post(
    "/{org_slug}/message-blocks",
    response_model=schemas.MessageBlockOut,
    status_code=status.HTTP_201_CREATED,
)
def create_block(
    org_slug: str,
    body: schemas.MessageBlockCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    org = _org_or_404(db, org_slug)
    _active_membership_or_404(db, current_user.id, org.id)
    if body.blocked_id == current_user.id:
        raise HTTPException(status_code=400, detail="You can't block yourself.")
    if not _is_active_member(db, body.blocked_id, org.id):
        raise HTTPException(status_code=400, detail="That user is not a member of this organization.")
    existing = (
        db.query(models.MessageBlock)
        .filter(
            models.MessageBlock.blocker_id == current_user.id,
            models.MessageBlock.blocked_id == body.blocked_id,
            models.MessageBlock.org_id == org.id,
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="User already blocked.")
    blk = models.MessageBlock(
        blocker_id=current_user.id,
        blocked_id=body.blocked_id,
        org_id=org.id,
    )
    db.add(blk)
    db.commit()
    db.refresh(blk)
    return _build_block_out(db, blk, org)


@router.delete(
    "/{org_slug}/message-blocks/{blocked_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_block(
    org_slug: str,
    blocked_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    org = _org_or_404(db, org_slug)
    _active_membership_or_404(db, current_user.id, org.id)
    blk = (
        db.query(models.MessageBlock)
        .filter(
            models.MessageBlock.blocker_id == current_user.id,
            models.MessageBlock.blocked_id == blocked_id,
            models.MessageBlock.org_id == org.id,
        )
        .first()
    )
    if blk is None:
        raise HTTPException(status_code=404, detail="Block not found.")
    db.delete(blk)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Unread count (nav badge)
# ---------------------------------------------------------------------------

@router.get("/{org_slug}/messages/unread-count")
def unread_count(
    org_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    org = _org_or_404(db, org_slug)
    _active_membership_or_404(db, current_user.id, org.id)

    clauses = [
        models.Conversation.initiator_id == current_user.id,
        models.Conversation.recipient_id == current_user.id,
    ]
    if _can_view_org_inbox(db, current_user.id, org.id):
        clauses.append(models.Conversation.conversation_type == "org_inbox")
    convs = (
        db.query(models.Conversation)
        .filter(models.Conversation.org_id == org.id, or_(*clauses))
        .all()
    )
    total = sum(_unread_count(db, c.id, current_user.id) for c in convs)
    return {"unread_count": total}
