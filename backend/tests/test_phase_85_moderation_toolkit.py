"""Phase 85 — Steward moderation toolkit P1.

Cluster 1 (B-1): attributed moderator comment removal.
Cluster 2 (B-8): org-scoped rejoin ban.

Side-effect assertions (not just status codes): the resulting comment row /
org_bans row / audit rows / notification row are asserted directly, and every
blocked join path is verified to create NO membership row.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from main import app
from tests.conftest import make_org_membership, make_sub_org_membership


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


@pytest.fixture(scope="function")
def test_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
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

def _user(db, username, *, is_admin=False, email_verified=True):
    u = models.User(
        username=username, display_name=username.title(), password_hash=_DUMMY_HASH,
        email=f"{username}@test.example", email_verified=email_verified, is_admin=is_admin,
    )
    db.add(u); db.flush(); return u


def _org(db, slug="acme", *, join_policy="open", parent_org_id=None, **kw):
    o = models.Organization(
        name=slug.title(), slug=slug, description="", join_policy=join_policy,
        parent_org_id=parent_org_id, settings={"default_voting_days": 7}, **kw,
    )
    db.add(o); db.flush(); return o


def _member(db, org, user, role="member", status="active"):
    return make_org_membership(db, user_id=user.id, org_id=org.id, role=role, status=status)


def _proposal(db, author, *, org=None, sub_org=None, status="voting"):
    p = models.Proposal(
        title="Test Proposal", body="", author_id=author.id,
        org_id=org.id if org else None,
        sub_org_id=sub_org.id if sub_org else None, status=status,
    )
    db.add(p); db.flush(); return p


def _auth(user):
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _set_perm(db, org_id, system_key, key, enabled):
    role = db.query(models.Role).filter_by(org_id=org_id, system_key=system_key).first()
    row = db.query(models.RolePermission).filter_by(role_id=role.id, permission_key=key).first()
    if row is None:
        db.add(models.RolePermission(role_id=role.id, permission_key=key, enabled=enabled))
    else:
        row.enabled = enabled
    db.commit()
    db.info.pop("_permission_cache", None)


def _post_comment(client, user, proposal_id, body="hello"):
    return client.post(
        f"/api/proposals/{proposal_id}/comments", json={"body": body}, headers=_auth(user),
    )


def _enable_in_app(db, user_id, event_type):
    db.add(models.NotificationPreference(
        user_id=user_id, event_type=event_type, channel="in_app", enabled=True,
    ))
    db.commit()


# ===========================================================================
# Cluster 1 — comment.moderate enforcement (B-1)
# ===========================================================================

class TestCommentModeration:
    def _setup(self, db):
        org = _org(db)
        author = _user(db, "author")
        mod = _user(db, "mod")
        _member(db, org, author, role="member")
        _member(db, org, mod, role="moderator")  # holds comment.moderate by default
        proposal = _proposal(db, author, org=org)
        db.commit()
        return org, author, mod, proposal

    def test_moderator_removes_others_comment(self, client, test_db):
        org, author, mod, proposal = self._setup(test_db)
        cid = _post_comment(client, author, proposal.id).json()["id"]
        _enable_in_app(test_db, author.id, "comment.moderated")

        r = client.delete(f"/api/comments/{cid}", headers=_auth(mod))
        assert r.status_code == 204, r.text

        test_db.expire_all()
        c = test_db.get(models.Comment, cid)
        assert c.deleted_at is not None
        assert c.body == ""
        assert c.removed_by_id == mod.id

        # Audit: comment.moderated with author_id, no body content.
        ev = test_db.query(models.AuditLog).filter_by(action="comment.moderated").first()
        assert ev is not None
        assert ev.details.get("author_id") == author.id
        assert "body" not in ev.details

        # Notification to the author.
        notif = test_db.query(models.Notification).filter_by(
            user_id=author.id, event_type="comment.moderated",
        ).first()
        assert notif is not None
        assert notif.actor_id == mod.id

    def test_author_self_delete_unchanged(self, client, test_db):
        org, author, mod, proposal = self._setup(test_db)
        cid = _post_comment(client, author, proposal.id).json()["id"]

        r = client.delete(f"/api/comments/{cid}", headers=_auth(author))
        assert r.status_code == 204, r.text

        test_db.expire_all()
        c = test_db.get(models.Comment, cid)
        assert c.deleted_at is not None
        assert c.removed_by_id is None  # self-delete stays NULL
        assert test_db.query(models.AuditLog).filter_by(action="comment.deleted").first() is not None
        assert test_db.query(models.AuditLog).filter_by(action="comment.moderated").first() is None

    def test_serializer_surfaces_moderator_removed(self, client, test_db):
        org, author, mod, proposal = self._setup(test_db)
        cid = _post_comment(client, author, proposal.id).json()["id"]
        client.delete(f"/api/comments/{cid}", headers=_auth(mod))

        rows = client.get(
            f"/api/proposals/{proposal.id}/comments", headers=_auth(mod),
        ).json()
        row = next(c for c in rows if c["id"] == cid)
        assert row["moderator_removed"] is True
        assert row["body_deleted"] is True
        assert row["body"] == ""

        # Self-delete side: a different comment self-deleted reads False.
        cid2 = _post_comment(client, author, proposal.id, body="two").json()["id"]
        client.delete(f"/api/comments/{cid2}", headers=_auth(author))
        rows2 = client.get(
            f"/api/proposals/{proposal.id}/comments", headers=_auth(mod),
        ).json()
        row2 = next(c for c in rows2 if c["id"] == cid2)
        assert row2["moderator_removed"] is False
        assert row2["body_deleted"] is True

    def test_moderator_without_permission_403(self, client, test_db):
        org, author, mod, proposal = self._setup(test_db)
        cid = _post_comment(client, author, proposal.id).json()["id"]
        _set_perm(test_db, org.id, "moderator", "comment.moderate", False)

        r = client.delete(f"/api/comments/{cid}", headers=_auth(mod))
        assert r.status_code == 403, r.text
        test_db.expire_all()
        c = test_db.get(models.Comment, cid)
        assert c.deleted_at is None  # no mutation
        assert c.removed_by_id is None

    def test_plain_member_non_author_403(self, client, test_db):
        org, author, mod, proposal = self._setup(test_db)
        other = _user(test_db, "other"); _member(test_db, org, other, role="member")
        test_db.commit()
        cid = _post_comment(client, author, proposal.id).json()["id"]

        r = client.delete(f"/api/comments/{cid}", headers=_auth(other))
        assert r.status_code == 403, r.text
        test_db.expire_all()
        assert test_db.get(models.Comment, cid).deleted_at is None

    def test_moderator_on_already_self_deleted_is_noop(self, client, test_db):
        org, author, mod, proposal = self._setup(test_db)
        cid = _post_comment(client, author, proposal.id).json()["id"]
        client.delete(f"/api/comments/{cid}", headers=_auth(author))  # self-delete first

        r = client.delete(f"/api/comments/{cid}", headers=_auth(mod))
        assert r.status_code == 204, r.text
        test_db.expire_all()
        c = test_db.get(models.Comment, cid)
        # Must NOT retroactively re-attribute the self-delete as moderation.
        assert c.removed_by_id is None
        assert test_db.query(models.AuditLog).filter_by(action="comment.moderated").first() is None

    def test_sub_org_scoped_moderation_resolves_via_sub_org(self, client, test_db):
        parent = _org(test_db, "parent")
        author = _user(test_db, "sauthor")
        padmin = _user(test_db, "padmin")
        _member(test_db, parent, author, role="member")
        _member(test_db, parent, padmin, role="admin")  # parent admin => sub-org power
        sub = _org(test_db, "sub", parent_org_id=parent.id)
        make_sub_org_membership(test_db, sub_org_id=sub.id, user_id=author.id, role="member")
        proposal = _proposal(test_db, author, org=parent, sub_org=sub)
        test_db.commit()
        cid = _post_comment(client, author, proposal.id).json()["id"]

        r = client.delete(f"/api/comments/{cid}", headers=_auth(padmin))
        assert r.status_code == 204, r.text
        test_db.expire_all()
        assert test_db.get(models.Comment, cid).removed_by_id == padmin.id


# ===========================================================================
# Cluster 2 — rejoin ban (B-8)
# ===========================================================================

class TestRejoinBan:
    def test_remove_with_ban_creates_ban_row(self, client, test_db):
        org = _org(test_db)
        admin = _user(test_db, "admin"); _member(test_db, org, admin, role="admin")
        target = _user(test_db, "target"); _member(test_db, org, target, role="member")
        test_db.commit()

        r = client.request(
            "DELETE", f"/api/orgs/acme/members/{target.id}",
            headers=_auth(admin), json={"ban": True},
        )
        assert r.status_code == 204, r.text
        test_db.expire_all()
        # Membership gone.
        assert test_db.query(models.OrgMembership).filter_by(
            org_id=org.id, user_id=target.id).first() is None
        # Active ban row present.
        ban = test_db.query(models.OrgBan).filter_by(org_id=org.id, user_id=target.id).first()
        assert ban is not None and ban.revoked_at is None
        assert ban.banned_by_id == admin.id
        assert test_db.query(models.AuditLog).filter_by(action="member.banned").first() is not None

    def test_remove_without_ban_no_ban_row_and_can_rejoin(self, client, test_db):
        org = _org(test_db, join_policy="open")
        admin = _user(test_db, "admin"); _member(test_db, org, admin, role="admin")
        target = _user(test_db, "target"); _member(test_db, org, target, role="member")
        test_db.commit()

        client.delete(f"/api/orgs/acme/members/{target.id}", headers=_auth(admin))
        test_db.expire_all()
        assert test_db.query(models.OrgBan).filter_by(org_id=org.id, user_id=target.id).first() is None

        # Rejoin the open org succeeds (removal without ban is toothless — the
        # very gap B-8 closes; here we prove the default remains permissive).
        r = client.post("/api/orgs/acme/join-request", headers=_auth(target))
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "active"

    def _ban(self, db, org, user, by):
        from org_bans import create_ban
        create_ban(db, org_id=org.id, user_id=user.id, banned_by_id=by.id)
        db.commit()

    def test_banned_blocked_open_join(self, client, test_db):
        org = _org(test_db, join_policy="open")
        admin = _user(test_db, "admin"); _member(test_db, org, admin, role="admin")
        banned = _user(test_db, "banned")
        self._ban(test_db, org, banned, admin)

        r = client.post("/api/orgs/acme/join-request", headers=_auth(banned))
        assert r.status_code == 403, r.text
        assert test_db.query(models.OrgMembership).filter_by(
            org_id=org.id, user_id=banned.id).first() is None

    def test_banned_blocked_approval_join(self, client, test_db):
        org = _org(test_db, join_policy="approval")
        admin = _user(test_db, "admin"); _member(test_db, org, admin, role="admin")
        banned = _user(test_db, "banned")
        self._ban(test_db, org, banned, admin)

        r = client.post("/api/orgs/acme/join-request", headers=_auth(banned))
        assert r.status_code == 403, r.text
        # No pending row created either.
        assert test_db.query(models.OrgMembership).filter_by(
            org_id=org.id, user_id=banned.id).first() is None

    def test_banned_blocked_legacy_join(self, client, test_db):
        org = _org(test_db, join_policy="open")
        admin = _user(test_db, "admin"); _member(test_db, org, admin, role="admin")
        banned = _user(test_db, "banned")
        self._ban(test_db, org, banned, admin)

        r = client.post("/api/orgs/acme/join", headers=_auth(banned))
        assert r.status_code == 403, r.text
        assert test_db.query(models.OrgMembership).filter_by(
            org_id=org.id, user_id=banned.id).first() is None

    def test_banned_blocked_invitation_accept(self, client, test_db):
        org = _org(test_db, join_policy="approval")
        admin = _user(test_db, "admin"); _member(test_db, org, admin, role="admin")
        banned = _user(test_db, "banned")
        self._ban(test_db, org, banned, admin)
        # Create a pending invitation targeting the banned user.
        from datetime import datetime, timedelta, timezone
        inv = models.Invitation(
            org_id=org.id, email=banned.email, invited_by=admin.id, role="member",
            token="tok-banned", status="pending",
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7),
        )
        test_db.add(inv); test_db.commit()

        r = client.post("/api/orgs/join/tok-banned", headers=_auth(banned))
        assert r.status_code == 403, r.text
        assert test_db.query(models.OrgMembership).filter_by(
            org_id=org.id, user_id=banned.id).first() is None

    def test_consume_invitation_helper_blocks_banned(self, test_db):
        """The register/login invite-consume path (auth._consume_invitation)
        is a distinct entry point — assert its ban gate directly."""
        from routes.auth import _consume_invitation
        from fastapi import HTTPException
        from datetime import datetime, timedelta, timezone
        org = _org(test_db, join_policy="open")
        admin = _user(test_db, "admin"); _member(test_db, org, admin, role="admin")
        banned = _user(test_db, "banned")
        from org_bans import create_ban
        create_ban(test_db, org_id=org.id, user_id=banned.id, banned_by_id=admin.id)
        inv = models.Invitation(
            org_id=org.id, email=banned.email, invited_by=admin.id, role="member",
            token="tok2", status="pending",
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7),
        )
        test_db.add(inv); test_db.commit()

        class _Req:
            client = None
        with pytest.raises(HTTPException) as ei:
            _consume_invitation(
                test_db, invitation_token="tok2", user=banned,
                request_email=banned.email, via="login", request=_Req(),
            )
        assert ei.value.status_code == 403
        assert test_db.query(models.OrgMembership).filter_by(
            org_id=org.id, user_id=banned.id).first() is None

    def test_unban_allows_rejoin(self, client, test_db):
        org = _org(test_db, join_policy="open")
        admin = _user(test_db, "admin"); _member(test_db, org, admin, role="admin")
        banned = _user(test_db, "banned")
        self._ban(test_db, org, banned, admin)
        ban = test_db.query(models.OrgBan).filter_by(user_id=banned.id).first()

        r = client.post(f"/api/orgs/acme/bans/{ban.id}/revoke", headers=_auth(admin))
        assert r.status_code == 200, r.text
        test_db.expire_all()
        ban = test_db.get(models.OrgBan, ban.id)
        assert ban.revoked_at is not None
        assert ban.revoked_by_id == admin.id
        assert test_db.query(models.AuditLog).filter_by(action="member.ban_revoked").first() is not None

        # Now the previously-banned user can join.
        r2 = client.post("/api/orgs/acme/join-request", headers=_auth(banned))
        assert r2.status_code == 200, r2.text
        assert r2.json()["status"] == "active"

    def test_reban_after_unban_ok(self, client, test_db):
        """Partial unique index only constrains ACTIVE bans — a revoked ban
        does not block a fresh ban of the same pair."""
        org = _org(test_db)
        admin = _user(test_db, "admin"); _member(test_db, org, admin, role="admin")
        banned = _user(test_db, "banned")
        from org_bans import create_ban, revoke_ban
        b1 = create_ban(test_db, org_id=org.id, user_id=banned.id, banned_by_id=admin.id)
        revoke_ban(test_db, ban=b1, revoked_by_id=admin.id)
        test_db.commit()
        b2 = create_ban(test_db, org_id=org.id, user_id=banned.id, banned_by_id=admin.id)
        test_db.commit()
        assert b2.id != b1.id
        active = test_db.query(models.OrgBan).filter_by(
            org_id=org.id, user_id=banned.id, revoked_at=None).all()
        assert len(active) == 1

    def test_ban_list_endpoint_and_gate(self, client, test_db):
        org = _org(test_db)
        admin = _user(test_db, "admin"); _member(test_db, org, admin, role="admin")
        plain = _user(test_db, "plain"); _member(test_db, org, plain, role="member")
        banned = _user(test_db, "banned")
        self._ban(test_db, org, banned, admin)

        r = client.get("/api/orgs/acme/bans", headers=_auth(admin))
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body) == 1
        assert body[0]["user_id"] == banned.id
        assert body[0]["banned_by_display_name"] == admin.display_name

        # Plain member cannot read bans (require_org_admin floor).
        r2 = client.get("/api/orgs/acme/bans", headers=_auth(plain))
        assert r2.status_code == 403

    def test_last_governor_removal_still_guarded_no_ban(self, client, test_db):
        """Governance floor: removing the sole steward is refused, and no ban
        is written for the blocked removal."""
        org = _org(test_db, join_policy="single_steward" and "open")
        steward = _user(test_db, "steward"); _member(test_db, org, steward, role="steward")
        test_db.commit()

        r = client.request(
            "DELETE", f"/api/orgs/acme/members/{steward.id}",
            headers=_auth(steward), json={"ban": True},
        )
        assert r.status_code == 400, r.text
        assert test_db.query(models.OrgBan).filter_by(user_id=steward.id).first() is None
