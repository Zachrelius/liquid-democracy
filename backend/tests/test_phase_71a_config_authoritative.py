"""Phase 71a — per-org permission config becomes authoritative.

Covers the three 71a conversions + the escalation-safety + no-behavior-
change invariants that make the staged rollout safe:

  * ``member.suspend`` (PF-1) — moderator+ tier FLOOR + config-authoritative.
  * ``analytics.view`` (PF-3 representative) — admin tier FLOOR + config.
  * ``proposal.advance_phase`` (PF-2) — author may NOT force-close their own
    ``voting→passed`` rung; that rung needs the key (or platform-admin).

House rule: assert SIDE EFFECTS (the member row actually changes /
doesn't), not just status codes.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from database import Base, get_db
import models
import auth as auth_utils
from main import app
from tests.conftest import make_org_membership


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


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


def _user(db: Session, username: str, *, is_admin: bool = False) -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=True,
        is_admin=is_admin,
    )
    db.add(u)
    db.flush()
    return u


def _org(db: Session, slug: str = "test-org") -> models.Organization:
    org = models.Organization(
        name=slug.title(),
        slug=slug,
        description="",
        join_policy="approval_required",
        settings={"default_voting_days": 7},
    )
    db.add(org)
    db.flush()
    return org


def _member(db, org, user, role="member", status="active"):
    return make_org_membership(
        db, user_id=user.id, org_id=org.id, role=role, status=status,
    )


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _set_perm(db, org_id, system_key, key, enabled):
    """Flip a (role, key) cell in the org's config, then clear the per-
    request permission cache (tests reuse one session across requests)."""
    role = db.query(models.Role).filter_by(
        org_id=org_id, system_key=system_key,
    ).first()
    row = db.query(models.RolePermission).filter_by(
        role_id=role.id, permission_key=key,
    ).first()
    if row is None:
        db.add(models.RolePermission(
            role_id=role.id, permission_key=key, enabled=enabled,
        ))
    else:
        row.enabled = enabled
    db.commit()
    db.info.pop("_permission_cache", None)


def _membership_status(db, org, user) -> str:
    m = db.query(models.OrgMembership).filter_by(
        org_id=org.id, user_id=user.id,
    ).first()
    return m.status if m else "<none>"


# ===========================================================================
# member.suspend (PF-1) — config-authoritative, tier as floor
# ===========================================================================

class TestMemberSuspend:
    def test_moderator_with_config_can_suspend_side_effect(self, client, test_db):
        """Default starter config grants moderators member.suspend (matches
        pre-71 behavior). Suspend succeeds AND the target row flips."""
        org = _org(test_db)
        mod = _user(test_db, "mod")
        _member(test_db, org, mod, role="moderator")
        target = _user(test_db, "target")
        _member(test_db, org, target, role="member")
        test_db.commit()

        resp = client.post(
            f"/api/orgs/test-org/members/{target.id}/suspend",
            headers=_auth(mod),
        )
        assert resp.status_code == 200, resp.text
        assert _membership_status(test_db, org, target) == "suspended"

    def test_moderator_with_cell_revoked_cannot_suspend(self, client, test_db):
        """Revoke member.suspend from moderator in the config → 403 AND the
        target row is unchanged (the config is now actually enforced)."""
        org = _org(test_db)
        mod = _user(test_db, "mod")
        _member(test_db, org, mod, role="moderator")
        target = _user(test_db, "target")
        _member(test_db, org, target, role="member")
        test_db.commit()
        _set_perm(test_db, org.id, "moderator", "member.suspend", False)

        resp = client.post(
            f"/api/orgs/test-org/members/{target.id}/suspend",
            headers=_auth(mod),
        )
        assert resp.status_code == 403, resp.text
        assert _membership_status(test_db, org, target) == "active"

    def test_floor_invariant_member_with_cell_still_403(self, client, test_db):
        """ESCALATION SAFETY: a plain member GRANTED member.suspend by config
        still 403s — the tier floor (moderator+) holds; config can't grant
        below the floor."""
        org = _org(test_db)
        member = _user(test_db, "plain")
        _member(test_db, org, member, role="member")
        target = _user(test_db, "target")
        _member(test_db, org, target, role="member")
        test_db.commit()
        _set_perm(test_db, org.id, "member", "member.suspend", True)

        resp = client.post(
            f"/api/orgs/test-org/members/{target.id}/suspend",
            headers=_auth(member),
        )
        assert resp.status_code == 403, resp.text
        assert _membership_status(test_db, org, target) == "active"

    def test_admin_unchanged(self, client, test_db):
        """No-behavior-change: admin (holds every key) still suspends."""
        org = _org(test_db)
        admin = _user(test_db, "admin")
        _member(test_db, org, admin, role="admin")
        target = _user(test_db, "target")
        _member(test_db, org, target, role="member")
        test_db.commit()

        resp = client.post(
            f"/api/orgs/test-org/members/{target.id}/suspend",
            headers=_auth(admin),
        )
        assert resp.status_code == 200, resp.text
        assert _membership_status(test_db, org, target) == "suspended"


# ===========================================================================
# analytics.view (PF-3 representative) — config-authoritative, admin floor
# ===========================================================================

class TestAnalyticsView:
    def test_admin_with_config_can_view(self, client, test_db):
        org = _org(test_db)
        admin = _user(test_db, "admin")
        _member(test_db, org, admin, role="admin")
        test_db.commit()

        resp = client.get("/api/orgs/test-org/analytics", headers=_auth(admin))
        assert resp.status_code == 200, resp.text

    def test_admin_with_cell_revoked_cannot_view(self, client, test_db):
        org = _org(test_db)
        admin = _user(test_db, "admin")
        _member(test_db, org, admin, role="admin")
        test_db.commit()
        _set_perm(test_db, org.id, "admin", "analytics.view", False)

        resp = client.get("/api/orgs/test-org/analytics", headers=_auth(admin))
        assert resp.status_code == 403, resp.text

    def test_floor_invariant_member_with_cell_still_403(self, client, test_db):
        """A member granted analytics.view by config still 403s (admin floor)."""
        org = _org(test_db)
        member = _user(test_db, "plain")
        _member(test_db, org, member, role="member")
        test_db.commit()
        _set_perm(test_db, org.id, "member", "analytics.view", True)

        resp = client.get("/api/orgs/test-org/analytics", headers=_auth(member))
        assert resp.status_code == 403, resp.text


# ===========================================================================
# PF-2 — author cannot force-close their own voting→passed rung
# ===========================================================================

def _draft_proposal(db, author, org) -> models.Proposal:
    p = models.Proposal(
        title="P", body="", author_id=author.id, org_id=org.id,
        voting_method="binary", num_winners=1, status="draft", voting_days=7,
        pass_threshold=0.5, quorum_threshold=0.4,
    )
    db.add(p)
    db.flush()
    return p


def _voting_proposal_authored_by(client, test_db, org, admin, author):
    """Create a well-formed proposal via the API as admin (draft→voting),
    then reassign authorship to ``author`` so we can exercise the author
    branch on a voting-status proposal."""
    topic = models.Topic(name="T", color="#00ff00", org_id=org.id)
    test_db.add(topic)
    test_db.flush()
    test_db.commit()
    r = client.post(
        "/api/orgs/test-org/proposals", headers=_auth(admin), json={
            "title": "Lifecycle", "body": "b",
            "topics": [{"topic_id": topic.id, "relevance": 1.0}],
            "pass_threshold": 0.5, "quorum_threshold": 0.4,
        },
    )
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    client.post(f"/api/orgs/test-org/proposals/{pid}/advance",
                headers=_auth(admin), json={})  # → deliberation
    r3 = client.post(f"/api/orgs/test-org/proposals/{pid}/advance",
                     headers=_auth(admin), json={"voting_end": "2030-01-01T00:00:00Z"})
    assert r3.json()["status"] == "voting", r3.text
    p = test_db.get(models.Proposal, pid)
    p.author_id = author.id
    test_db.commit()
    test_db.info.pop("_permission_cache", None)
    return pid


class TestAdvancePhaseVotingRung:
    def test_author_cannot_force_close_own_voting(self, client, test_db):
        org = _org(test_db)
        admin = _user(test_db, "admin")
        _member(test_db, org, admin, role="admin")
        member = _user(test_db, "author")
        _member(test_db, org, member, role="member")
        test_db.commit()
        pid = _voting_proposal_authored_by(client, test_db, org, admin, member)

        resp = client.post(f"/api/proposals/{pid}/advance",
                           headers=_auth(member), json={})
        assert resp.status_code == 403, resp.text
        # Side effect: status is still voting (not force-closed).
        assert test_db.get(models.Proposal, pid).status == "voting"

    def test_key_holder_can_close_voting(self, client, test_db):
        org = _org(test_db)
        admin = _user(test_db, "admin")
        _member(test_db, org, admin, role="admin")
        member = _user(test_db, "author")
        _member(test_db, org, member, role="member")
        test_db.commit()
        pid = _voting_proposal_authored_by(client, test_db, org, admin, member)

        # Admin holds proposal.advance_phase → may close voting at any rung.
        resp = client.post(f"/api/proposals/{pid}/advance",
                           headers=_auth(admin), json={})
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] in ("passed", "failed")

    def test_author_can_still_self_advance_draft(self, client, test_db):
        """Unchanged: author self-advances draft→deliberation without the key."""
        org = _org(test_db)
        member = _user(test_db, "author")
        _member(test_db, org, member, role="member")
        test_db.commit()
        p = _draft_proposal(test_db, member, org)
        test_db.commit()

        resp = client.post(f"/api/proposals/{p.id}/advance",
                           headers=_auth(member), json={})
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "deliberation"

    def test_flag_and_gate_agree_on_voting_rung(self, client, test_db):
        """can_advance == False (author on voting) AND /advance 403 — the
        Phase 70 flag↔gate agreement now covers the voting rung."""
        org = _org(test_db)
        admin = _user(test_db, "admin")
        _member(test_db, org, admin, role="admin")
        member = _user(test_db, "author")
        _member(test_db, org, member, role="member")
        test_db.commit()
        pid = _voting_proposal_authored_by(client, test_db, org, admin, member)

        body = client.get(f"/api/proposals/{pid}", headers=_auth(member)).json()
        assert body["can_advance"] is False
        resp = client.post(f"/api/proposals/{pid}/advance",
                           headers=_auth(member), json={})
        assert resp.status_code == 403, resp.text
