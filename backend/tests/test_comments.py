"""Phase 10 W1 — comment CRUD tests.

Covers:

  Lifecycle
    * create top-level comment
    * create reply to top-level
    * reject reply-to-reply (one-level threading)
    * reject reply-to-other-proposal (cross-proposal parent)
    * GET returns chronological order with replies grouped under parents
    * edit within window succeeds
    * edit after window expired -> 403 with the documented message
    * edit by non-author -> 403
    * soft-delete blanks body and preserves the row
    * soft-delete preserves reply visibility (replies still render under
      the deleted parent)

  Permissions
    * POST requires email_verified
    * POST requires active org membership
    * POST on sub-org-scoped proposal requires sub-org eligibility
    * GET respects proposal visibility (parent-only members locked out
      when sub-org is private)

  Sanitization (LOAD-BEARING)
    * `<script>alert(1)</script>some text` -> response body has no
      `<script>` / `alert(1)` substrings, but legitimate trailing text
      "some text" is preserved.

  Audit
    * lifecycle (create + edit + delete) emits the three documented
      `comment.*` events; details NEVER include body content.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from main import app


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def test_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def client(test_db):
    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(
    db: Session, username: str, *, email_verified: bool = True,
) -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=email_verified,
    )
    db.add(u)
    db.flush()
    return u


def _make_org(
    db: Session, name: str = "Acme", slug: str = "acme", *,
    parent_org_id: str | None = None, settings: dict | None = None,
) -> models.Organization:
    o = models.Organization(
        name=name, slug=slug, parent_org_id=parent_org_id,
        settings=settings or {},
    )
    db.add(o)
    db.flush()
    return o


def _add_org_membership(
    db: Session, user: models.User, org: models.Organization,
    *, role: str = "member", status: str = "active",
) -> models.OrgMembership:
    m = models.OrgMembership(
        user_id=user.id, org_id=org.id, role=role, status=status,
    )
    db.add(m)
    db.flush()
    return m


def _add_sub_org_membership(
    db: Session, user: models.User, sub_org: models.Organization,
    *, role: str = "member", status: str = "active",
) -> models.SubOrgMembership:
    m = models.SubOrgMembership(
        user_id=user.id, sub_org_id=sub_org.id, role=role, status=status,
    )
    db.add(m)
    db.flush()
    return m


def _make_proposal(
    db: Session, author: models.User, *,
    org: models.Organization | None = None,
    sub_org: models.Organization | None = None,
    status: str = "voting",
) -> models.Proposal:
    p = models.Proposal(
        title="Test Proposal",
        body="",
        author_id=author.id,
        org_id=org.id if org else None,
        sub_org_id=sub_org.id if sub_org else None,
        status=status,
    )
    db.add(p)
    db.flush()
    return p


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _post_comment(
    client: TestClient, user: models.User, proposal_id: str,
    body: str = "Hello world", parent_comment_id: str | None = None,
):
    payload: dict = {"body": body}
    if parent_comment_id is not None:
        payload["parent_comment_id"] = parent_comment_id
    return client.post(
        f"/api/proposals/{proposal_id}/comments",
        json=payload,
        headers=_auth(user),
    )


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def test_create_top_level_comment(client, test_db):
    org = _make_org(test_db)
    alice = _make_user(test_db, "alice")
    _add_org_membership(test_db, alice, org)
    proposal = _make_proposal(test_db, alice, org=org)
    test_db.commit()

    r = _post_comment(client, alice, proposal.id, body="Top-level comment")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["body"] == "Top-level comment"
    assert body["body_deleted"] is False
    assert body["parent_comment_id"] is None
    assert body["author"]["username"] == "alice"
    assert body["proposal_id"] == proposal.id


def test_create_reply_to_top_level(client, test_db):
    org = _make_org(test_db)
    alice = _make_user(test_db, "alice")
    bob = _make_user(test_db, "bob")
    _add_org_membership(test_db, alice, org)
    _add_org_membership(test_db, bob, org)
    proposal = _make_proposal(test_db, alice, org=org)
    test_db.commit()

    r1 = _post_comment(client, alice, proposal.id, body="Top")
    assert r1.status_code == 201
    top_id = r1.json()["id"]

    r2 = _post_comment(
        client, bob, proposal.id, body="Reply", parent_comment_id=top_id,
    )
    assert r2.status_code == 201, r2.text
    assert r2.json()["parent_comment_id"] == top_id


def test_create_reply_to_reply_rejected_400(client, test_db):
    org = _make_org(test_db)
    alice = _make_user(test_db, "alice")
    bob = _make_user(test_db, "bob")
    carol = _make_user(test_db, "carol")
    for u in (alice, bob, carol):
        _add_org_membership(test_db, u, org)
    proposal = _make_proposal(test_db, alice, org=org)
    test_db.commit()

    top = _post_comment(client, alice, proposal.id, body="Top").json()
    reply = _post_comment(
        client, bob, proposal.id, body="Reply", parent_comment_id=top["id"],
    ).json()

    r = _post_comment(
        client, carol, proposal.id, body="Reply to reply",
        parent_comment_id=reply["id"],
    )
    assert r.status_code == 400, r.text
    assert "one level" in r.json()["detail"].lower()


def test_create_reply_to_other_proposal_rejected_400(client, test_db):
    org = _make_org(test_db)
    alice = _make_user(test_db, "alice")
    _add_org_membership(test_db, alice, org)
    p1 = _make_proposal(test_db, alice, org=org)
    p2 = _make_proposal(test_db, alice, org=org)
    test_db.commit()

    top_p1 = _post_comment(client, alice, p1.id, body="On P1").json()

    r = _post_comment(
        client, alice, p2.id, body="Wrong parent",
        parent_comment_id=top_p1["id"],
    )
    assert r.status_code == 400, r.text
    assert "different proposal" in r.json()["detail"].lower()


def test_list_returns_chronological_with_replies_grouped(client, test_db):
    """GET returns ALL comments in created_at-ascending order. Replies are
    rendered immediately after their parent in the API order because
    creation order naturally interleaves them; the frontend can re-group
    by parent_comment_id, but the route itself is ordered chronologically
    so the client has a deterministic baseline."""
    org = _make_org(test_db)
    alice = _make_user(test_db, "alice")
    _add_org_membership(test_db, alice, org)
    proposal = _make_proposal(test_db, alice, org=org)
    test_db.commit()

    top1 = _post_comment(client, alice, proposal.id, body="A").json()
    top2 = _post_comment(client, alice, proposal.id, body="B").json()
    reply1a = _post_comment(
        client, alice, proposal.id, body="A-reply",
        parent_comment_id=top1["id"],
    ).json()
    top3 = _post_comment(client, alice, proposal.id, body="C").json()

    r = client.get(
        f"/api/proposals/{proposal.id}/comments", headers=_auth(alice),
    )
    assert r.status_code == 200, r.text
    items = r.json()
    assert [c["body"] for c in items] == ["A", "B", "A-reply", "C"]
    # Each item has the right parent linkage so the frontend can group.
    by_id = {c["id"]: c for c in items}
    assert by_id[reply1a["id"]]["parent_comment_id"] == top1["id"]
    assert by_id[top2["id"]]["parent_comment_id"] is None


def test_edit_within_window_succeeds(client, test_db):
    org = _make_org(test_db)
    alice = _make_user(test_db, "alice")
    _add_org_membership(test_db, alice, org)
    proposal = _make_proposal(test_db, alice, org=org)
    test_db.commit()

    create = _post_comment(client, alice, proposal.id, body="Original")
    cid = create.json()["id"]

    # Comment is fresh — well within 15-min window.
    r = client.patch(
        f"/api/comments/{cid}",
        json={"body": "Edited"},
        headers=_auth(alice),
    )
    assert r.status_code == 200, r.text
    assert r.json()["body"] == "Edited"

    # GET reflects the edit.
    listed = client.get(
        f"/api/proposals/{proposal.id}/comments", headers=_auth(alice),
    ).json()
    assert listed[0]["body"] == "Edited"


def test_edit_after_window_expired_403(client, test_db):
    org = _make_org(test_db)
    alice = _make_user(test_db, "alice")
    _add_org_membership(test_db, alice, org)
    proposal = _make_proposal(test_db, alice, org=org)
    test_db.commit()

    cid = _post_comment(client, alice, proposal.id, body="Original").json()["id"]

    # Manually backdate created_at to >15 min ago so the edit-window check
    # fires. Naive UTC matches the column's storage convention.
    long_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=20)
    comment = test_db.get(models.Comment, cid)
    comment.created_at = long_ago
    test_db.commit()

    r = client.patch(
        f"/api/comments/{cid}",
        json={"body": "Late edit"},
        headers=_auth(alice),
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "Edit window has expired"


def test_edit_by_non_author_403(client, test_db):
    org = _make_org(test_db)
    alice = _make_user(test_db, "alice")
    bob = _make_user(test_db, "bob")
    _add_org_membership(test_db, alice, org)
    _add_org_membership(test_db, bob, org)
    proposal = _make_proposal(test_db, alice, org=org)
    test_db.commit()

    cid = _post_comment(client, alice, proposal.id, body="Mine").json()["id"]

    r = client.patch(
        f"/api/comments/{cid}",
        json={"body": "Bob's edit"},
        headers=_auth(bob),
    )
    assert r.status_code == 403, r.text


def test_soft_delete_blanks_body_preserves_row(client, test_db):
    org = _make_org(test_db)
    alice = _make_user(test_db, "alice")
    _add_org_membership(test_db, alice, org)
    proposal = _make_proposal(test_db, alice, org=org)
    test_db.commit()

    cid = _post_comment(client, alice, proposal.id, body="Hello").json()["id"]

    r = client.delete(f"/api/comments/{cid}", headers=_auth(alice))
    assert r.status_code == 204, r.text

    # Row still exists; body blanked; deleted_at set.
    comment = test_db.get(models.Comment, cid)
    assert comment is not None
    assert comment.body == ""
    assert comment.deleted_at is not None

    # GET response signals the deletion.
    listed = client.get(
        f"/api/proposals/{proposal.id}/comments", headers=_auth(alice),
    ).json()
    assert len(listed) == 1
    assert listed[0]["body"] == ""
    assert listed[0]["body_deleted"] is True
    assert listed[0]["deleted_at"] is not None


def test_soft_delete_preserves_replies_visibility(client, test_db):
    org = _make_org(test_db)
    alice = _make_user(test_db, "alice")
    bob = _make_user(test_db, "bob")
    _add_org_membership(test_db, alice, org)
    _add_org_membership(test_db, bob, org)
    proposal = _make_proposal(test_db, alice, org=org)
    test_db.commit()

    top = _post_comment(client, alice, proposal.id, body="Parent").json()
    reply = _post_comment(
        client, bob, proposal.id, body="Reply", parent_comment_id=top["id"],
    ).json()

    # Author soft-deletes the parent.
    r = client.delete(f"/api/comments/{top['id']}", headers=_auth(alice))
    assert r.status_code == 204

    listed = client.get(
        f"/api/proposals/{proposal.id}/comments", headers=_auth(alice),
    ).json()
    assert len(listed) == 2  # row preserved
    by_id = {c["id"]: c for c in listed}
    assert by_id[top["id"]]["body_deleted"] is True
    # Reply still renders with its content + parent linkage intact.
    assert by_id[reply["id"]]["body"] == "Reply"
    assert by_id[reply["id"]]["body_deleted"] is False
    assert by_id[reply["id"]]["parent_comment_id"] == top["id"]


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------

def test_post_requires_email_verified(client, test_db):
    org = _make_org(test_db)
    alice = _make_user(test_db, "alice", email_verified=False)
    _add_org_membership(test_db, alice, org)
    proposal = _make_proposal(test_db, alice, org=org)
    test_db.commit()

    r = _post_comment(client, alice, proposal.id, body="Try")
    assert r.status_code == 403, r.text
    assert "verify" in r.json()["detail"].lower()


def test_post_requires_org_membership(client, test_db):
    org = _make_org(test_db)
    alice = _make_user(test_db, "alice")
    bob = _make_user(test_db, "bob")  # NOT a member of org
    _add_org_membership(test_db, alice, org)
    proposal = _make_proposal(test_db, alice, org=org)
    test_db.commit()

    r = _post_comment(client, bob, proposal.id, body="Outsider")
    assert r.status_code == 403, r.text
    assert "active member" in r.json()["detail"].lower()


def test_post_on_sub_org_proposal_requires_sub_org_eligibility(client, test_db):
    """A sub-org-scoped proposal where the sub-org is private excludes
    parent-org-only members from posting."""
    parent = _make_org(test_db, name="Parent", slug="parent")
    sub = _make_org(
        test_db, name="Eng", slug="parent-eng",
        parent_org_id=parent.id, settings={"private": True},
    )

    alice = _make_user(test_db, "alice")     # sub-org member
    bob = _make_user(test_db, "bob")         # parent-org-only
    _add_org_membership(test_db, alice, parent)
    _add_org_membership(test_db, bob, parent)
    _add_sub_org_membership(test_db, alice, sub)

    proposal = _make_proposal(test_db, alice, org=parent, sub_org=sub)
    test_db.commit()

    # Sub-org member can post.
    r_alice = _post_comment(client, alice, proposal.id, body="Inside")
    assert r_alice.status_code == 201, r_alice.text

    # Parent-only member is locked out (sub-org is private).
    r_bob = _post_comment(client, bob, proposal.id, body="Outside")
    assert r_bob.status_code == 403, r_bob.text


def test_get_respects_proposal_visibility(client, test_db):
    """GET on a private sub-org proposal: sub-org members can list,
    parent-only members get 403."""
    parent = _make_org(test_db, name="Parent", slug="parent")
    sub = _make_org(
        test_db, name="Eng", slug="parent-eng",
        parent_org_id=parent.id, settings={"private": True},
    )

    alice = _make_user(test_db, "alice")
    bob = _make_user(test_db, "bob")
    _add_org_membership(test_db, alice, parent)
    _add_org_membership(test_db, bob, parent)
    _add_sub_org_membership(test_db, alice, sub)

    proposal = _make_proposal(test_db, alice, org=parent, sub_org=sub)
    test_db.commit()

    _post_comment(client, alice, proposal.id, body="Hi")

    r_alice = client.get(
        f"/api/proposals/{proposal.id}/comments", headers=_auth(alice),
    )
    assert r_alice.status_code == 200, r_alice.text
    assert len(r_alice.json()) == 1

    r_bob = client.get(
        f"/api/proposals/{proposal.id}/comments", headers=_auth(bob),
    )
    assert r_bob.status_code == 403, r_bob.text


# ---------------------------------------------------------------------------
# Sanitization (LOAD-BEARING)
# ---------------------------------------------------------------------------

def test_xss_payload_sanitized_via_nh3(client, test_db):
    """LOAD-BEARING: posting `<script>alert(1)</script>some text` yields a
    response/list whose body content has neither `<script>` nor
    `alert(1)` substrings. The legitimate trailing text "some text" is
    preserved so users can still write content around HTML they
    intended to escape.

    Asserts the SIDE EFFECT of `_sanitize_markdown` (nh3.clean) — not just
    that the route returned 201. This is the difference between "the API
    accepted the comment" and "the comment is actually safe to render."
    """
    org = _make_org(test_db)
    alice = _make_user(test_db, "alice")
    _add_org_membership(test_db, alice, org)
    proposal = _make_proposal(test_db, alice, org=org)
    test_db.commit()

    payload_body = "<script>alert(1)</script>some text"

    create = _post_comment(client, alice, proposal.id, body=payload_body)
    assert create.status_code == 201, create.text

    # The create response itself reflects the sanitized body.
    created_body = create.json()["body"]
    assert "<script>" not in created_body
    assert "alert(1)" not in created_body
    assert "some text" in created_body

    # GET verifies the same sanitization end-to-end (no accidental rehydration
    # of raw script tags from the DB).
    listed = client.get(
        f"/api/proposals/{proposal.id}/comments", headers=_auth(alice),
    ).json()
    assert len(listed) == 1
    listed_body = listed[0]["body"]
    assert "<script>" not in listed_body
    assert "alert(1)" not in listed_body
    assert "some text" in listed_body

    # Defense-in-depth: the row in the DB is also clean (sanitization
    # happens at write time, so there's nothing dangerous on disk).
    row = test_db.query(models.Comment).filter(
        models.Comment.proposal_id == proposal.id,
    ).one()
    assert "<script>" not in row.body
    assert "alert(1)" not in row.body


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

def test_audit_events_emitted_on_lifecycle(client, test_db):
    """POST + PATCH + DELETE each fire their respective `comment.*` event
    with the documented detail shape AND no body content present in any
    event's `details`."""
    org = _make_org(test_db)
    alice = _make_user(test_db, "alice")
    _add_org_membership(test_db, alice, org)
    proposal = _make_proposal(test_db, alice, org=org)
    test_db.commit()

    body_str = "Confidential body that should not leak into audit"

    create = _post_comment(client, alice, proposal.id, body=body_str)
    assert create.status_code == 201
    cid = create.json()["id"]

    edited_body = "Equally confidential edited content"
    edit = client.patch(
        f"/api/comments/{cid}",
        json={"body": edited_body},
        headers=_auth(alice),
    )
    assert edit.status_code == 200

    delete = client.delete(f"/api/comments/{cid}", headers=_auth(alice))
    assert delete.status_code == 204

    # Pull all comment.* audit rows for the lifecycle.
    rows = (
        test_db.query(models.AuditLog)
        .filter(models.AuditLog.action.in_([
            "comment.created", "comment.edited", "comment.deleted",
        ]))
        .order_by(models.AuditLog.timestamp.asc())
        .all()
    )
    actions = [r.action for r in rows]
    assert actions == ["comment.created", "comment.edited", "comment.deleted"]

    created_event = rows[0]
    assert created_event.actor_id == alice.id
    assert created_event.target_id == cid
    assert created_event.target_type == "comment"
    assert created_event.details["comment_id"] == cid
    assert created_event.details["proposal_id"] == proposal.id
    assert created_event.details["parent_comment_id"] is None
    assert created_event.details["body_length"] == len(body_str)

    edited_event = rows[1]
    assert edited_event.details["comment_id"] == cid
    assert edited_event.details["proposal_id"] == proposal.id
    assert edited_event.details["body_length"] == len(edited_body)

    deleted_event = rows[2]
    assert deleted_event.details["comment_id"] == cid
    assert deleted_event.details["proposal_id"] == proposal.id

    # LOAD-BEARING: assert body content is NOT present in any details payload.
    for r in rows:
        details_serialized = repr(r.details)
        assert body_str not in details_serialized, (
            f"raw create-body leaked into audit details for {r.action}"
        )
        assert edited_body not in details_serialized, (
            f"raw edit-body leaked into audit details for {r.action}"
        )
