"""Phase 86 — anti-abuse pass.

C1 content reports (B-4), C2 content-creation rate limits (B-7),
C3 uniform verified-email gate (B-9).

Side-effect assertions throughout: report create asserts the row + audit +
notification; duplicate asserts NO second row; resolve asserts the mutation;
rate-limit tests assert the 429 AND that no row was written; verified-email
gate tests assert rejection writes nothing.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
import rate_limit_utils
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

def _user(db, username, *, email_verified=True):
    u = models.User(
        username=username, display_name=username.title(), password_hash=_DUMMY_HASH,
        email=f"{username}@test.example", email_verified=email_verified,
    )
    db.add(u); db.flush(); return u


def _org(db, slug="acme", *, join_policy="open", is_demo=False, **kw):
    o = models.Organization(
        name=slug.title(), slug=slug, description="", join_policy=join_policy,
        is_demo=is_demo, settings={"default_voting_days": 7}, **kw,
    )
    db.add(o); db.flush(); return o


def _member(db, org, user, role="member"):
    return make_org_membership(db, user_id=user.id, org_id=org.id, role=role, status="active")


def _proposal(db, author, *, org=None, status="voting"):
    p = models.Proposal(
        title="Test Proposal", body="", author_id=author.id,
        org_id=org.id if org else None, status=status,
    )
    db.add(p); db.flush(); return p


def _comment(db, author, proposal, body="hello"):
    c = models.Comment(proposal_id=proposal.id, author_id=author.id, body=body)
    db.add(c); db.flush(); return c


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


def _enable_in_app(db, user_id, event_type):
    db.add(models.NotificationPreference(
        user_id=user_id, event_type=event_type, channel="in_app", enabled=True,
    ))
    db.commit()


# ===========================================================================
# Cluster 1 — content reports (B-4)
# ===========================================================================

class TestContentReports:
    def _setup(self, db):
        org = _org(db)
        author = _user(db, "author"); _member(db, org, author, role="member")
        reporter = _user(db, "reporter"); _member(db, org, reporter, role="member")
        mod = _user(db, "mod"); _member(db, org, mod, role="moderator")  # comment.moderate
        proposal = _proposal(db, author, org=org)
        comment = _comment(db, author, proposal)
        db.commit()
        return org, author, reporter, mod, proposal, comment

    def test_report_comment_creates_row_audit_notification(self, client, test_db):
        org, author, reporter, mod, proposal, comment = self._setup(test_db)
        _enable_in_app(test_db, mod.id, "report_created")

        r = client.post("/api/reports", headers=_auth(reporter), json={
            "target_type": "comment", "target_id": comment.id,
            "reason": "harassment", "note": "over the line",
        })
        assert r.status_code == 201, r.text
        assert r.json()["already_open"] is False

        test_db.expire_all()
        row = test_db.query(models.ContentReport).filter_by(
            target_type="comment", target_id=comment.id).first()
        assert row is not None
        assert row.status == "open"
        assert row.org_id == org.id
        assert row.reporter_id == reporter.id
        assert row.reason == "harassment"

        ev = test_db.query(models.AuditLog).filter_by(action="report.created").first()
        assert ev is not None
        assert ev.details.get("note_present") is True
        assert "note" not in ev.details  # note body never in audit

        notif = test_db.query(models.Notification).filter_by(
            user_id=mod.id, event_type="report_created").first()
        assert notif is not None

    def test_duplicate_open_report_is_noop(self, client, test_db):
        org, author, reporter, mod, proposal, comment = self._setup(test_db)
        body = {"target_type": "comment", "target_id": comment.id, "reason": "spam"}
        r1 = client.post("/api/reports", headers=_auth(reporter), json=body)
        assert r1.status_code == 201
        r2 = client.post("/api/reports", headers=_auth(reporter), json=body)
        assert r2.status_code == 201
        assert r2.json()["already_open"] is True
        assert test_db.query(models.ContentReport).filter_by(
            reporter_id=reporter.id, target_id=comment.id).count() == 1

    def test_report_own_content_400(self, client, test_db):
        org, author, reporter, mod, proposal, comment = self._setup(test_db)
        r = client.post("/api/reports", headers=_auth(author), json={
            "target_type": "comment", "target_id": comment.id, "reason": "spam"})
        assert r.status_code == 400, r.text
        assert test_db.query(models.ContentReport).count() == 0

    def test_report_by_non_member_403(self, client, test_db):
        org, author, reporter, mod, proposal, comment = self._setup(test_db)
        outsider = _user(test_db, "outsider"); test_db.commit()
        r = client.post("/api/reports", headers=_auth(outsider), json={
            "target_type": "comment", "target_id": comment.id, "reason": "spam"})
        assert r.status_code == 403, r.text
        assert test_db.query(models.ContentReport).count() == 0

    def test_report_already_removed_comment_400(self, client, test_db):
        org, author, reporter, mod, proposal, comment = self._setup(test_db)
        comment.deleted_at = __import__("datetime").datetime.utcnow()
        test_db.commit()
        r = client.post("/api/reports", headers=_auth(reporter), json={
            "target_type": "comment", "target_id": comment.id, "reason": "spam"})
        assert r.status_code == 400, r.text
        assert test_db.query(models.ContentReport).count() == 0

    def test_report_proposal_target(self, client, test_db):
        org, author, reporter, mod, proposal, comment = self._setup(test_db)
        r = client.post("/api/reports", headers=_auth(reporter), json={
            "target_type": "proposal", "target_id": proposal.id, "reason": "misleading"})
        assert r.status_code == 201, r.text
        assert test_db.query(models.ContentReport).filter_by(
            target_type="proposal", target_id=proposal.id).count() == 1

    def test_queue_gated_on_comment_moderate(self, client, test_db):
        org, author, reporter, mod, proposal, comment = self._setup(test_db)
        client.post("/api/reports", headers=_auth(reporter), json={
            "target_type": "comment", "target_id": comment.id, "reason": "spam"})

        # Moderator (holds comment.moderate) can view.
        r = client.get("/api/orgs/acme/reports", headers=_auth(mod))
        assert r.status_code == 200, r.text
        groups = r.json()
        assert len(groups) == 1
        assert groups[0]["open_count"] == 1
        assert groups[0]["reports"][0]["reporter_id"] == reporter.id  # identity visible to mod

        # Plain member cannot.
        r2 = client.get("/api/orgs/acme/reports", headers=_auth(reporter))
        assert r2.status_code == 403

        # Moderator with the cell toggled OFF cannot.
        _set_perm(test_db, org.id, "moderator", "comment.moderate", False)
        r3 = client.get("/api/orgs/acme/reports", headers=_auth(mod))
        assert r3.status_code == 403

    def test_resolve_report(self, client, test_db):
        org, author, reporter, mod, proposal, comment = self._setup(test_db)
        client.post("/api/reports", headers=_auth(reporter), json={
            "target_type": "comment", "target_id": comment.id, "reason": "spam"})
        report = test_db.query(models.ContentReport).first()

        r = client.patch(f"/api/reports/{report.id}", headers=_auth(mod),
                         json={"status": "actioned"})
        assert r.status_code == 200, r.text
        test_db.expire_all()
        report = test_db.get(models.ContentReport, report.id)
        assert report.status == "actioned"
        assert report.resolved_by_id == mod.id
        assert report.resolved_at is not None
        ev = test_db.query(models.AuditLog).filter_by(action="report.resolved").first()
        assert ev is not None
        assert ev.details.get("disposition") == "actioned"

    def test_resolve_gated_on_comment_moderate(self, client, test_db):
        org, author, reporter, mod, proposal, comment = self._setup(test_db)
        client.post("/api/reports", headers=_auth(reporter), json={
            "target_type": "comment", "target_id": comment.id, "reason": "spam"})
        report = test_db.query(models.ContentReport).first()
        r = client.patch(f"/api/reports/{report.id}", headers=_auth(reporter),
                         json={"status": "dismissed"})
        assert r.status_code == 403, r.text
        test_db.expire_all()
        assert test_db.get(models.ContentReport, report.id).status == "open"


# ===========================================================================
# Cluster 2 — content-creation rate limits (B-7)
# ===========================================================================

class TestRateLimits:
    def test_user_or_remote_address_keying(self):
        """Unit: authenticated → user:{id}; token resolved without a DB hit."""
        from starlette.requests import Request
        u = "abc-123"
        token = auth_utils.create_access_token(u)

        class _FakeReq:
            def __init__(self, headers):
                self.headers = headers
                self.client = type("C", (), {"host": "1.2.3.4"})()

        key = rate_limit_utils.user_or_remote_address(
            _FakeReq({"authorization": f"Bearer {token}"}))
        assert key == f"user:{u}"
        # No token → IP fallback.
        key2 = rate_limit_utils.user_or_remote_address(_FakeReq({}))
        assert key2 == "1.2.3.4"

    def test_bypass_returns_unique_key(self, monkeypatch):
        """When bypass is active the key is unique per request → limiter never
        trips (debug / QA env unaffected)."""
        monkeypatch.setattr(rate_limit_utils, "_bypass_active", lambda: True)

        class _FakeReq:
            headers = {}
            client = type("C", (), {"host": "9.9.9.9"})()

        k1 = rate_limit_utils.user_or_remote_address(_FakeReq())
        k2 = rate_limit_utils.user_or_remote_address(_FakeReq())
        assert k1 != k2 and k1.startswith("bypass-")

    def test_comment_rate_limit_429_writes_nothing(self, client, test_db):
        """30/hour comment limit: the 31st request is 429 and creates no row."""
        # Isolate this user's bucket from any prior test state.
        rate_limit_utils.content_limiter.reset()
        org = _org(test_db)
        u = _user(test_db, "spammer"); _member(test_db, org, u, role="member")
        p = _proposal(test_db, u, org=org)
        test_db.commit()

        ok = 0
        for i in range(30):
            r = client.post(f"/api/proposals/{p.id}/comments",
                            headers=_auth(u), json={"body": f"c{i}"})
            assert r.status_code == 201, (i, r.text)
            ok += 1
        assert ok == 30
        # 31st trips the limiter.
        r = client.post(f"/api/proposals/{p.id}/comments",
                        headers=_auth(u), json={"body": "over"})
        assert r.status_code == 429, r.text
        # No 31st row written.
        assert test_db.query(models.Comment).filter_by(author_id=u.id).count() == 30
        rate_limit_utils.content_limiter.reset()

    def test_bypass_disables_limiter(self, client, test_db, monkeypatch):
        """With bypass active, >limit posts all succeed (no 429)."""
        rate_limit_utils.content_limiter.reset()
        monkeypatch.setattr(rate_limit_utils, "_bypass_active", lambda: True)
        org = _org(test_db)
        u = _user(test_db, "heavy"); _member(test_db, org, u, role="member")
        p = _proposal(test_db, u, org=org)
        test_db.commit()
        for i in range(35):
            r = client.post(f"/api/proposals/{p.id}/comments",
                            headers=_auth(u), json={"body": f"c{i}"})
            assert r.status_code == 201, (i, r.text)
        rate_limit_utils.content_limiter.reset()


# ===========================================================================
# Cluster 3 — uniform verified-email gate (B-9)
# ===========================================================================

class TestVerifiedEmailGate:
    def _org_author_unverified(self, db):
        org = _org(db)
        author = _user(db, "author"); _member(db, org, author, role="member")
        unv = _user(db, "unv", email_verified=False); _member(db, org, unv, role="member")
        proposal = _proposal(db, author, org=org)
        comment = _comment(db, author, proposal)
        db.commit()
        return org, author, unv, proposal, comment

    def test_unverified_cannot_comment(self, client, test_db):
        org, author, unv, proposal, comment = self._org_author_unverified(test_db)
        r = client.post(f"/api/proposals/{proposal.id}/comments",
                        headers=_auth(unv), json={"body": "hi"})
        assert r.status_code == 403, r.text
        assert test_db.query(models.Comment).filter_by(author_id=unv.id).count() == 0

    def test_unverified_cannot_report(self, client, test_db):
        org, author, unv, proposal, comment = self._org_author_unverified(test_db)
        r = client.post("/api/reports", headers=_auth(unv), json={
            "target_type": "comment", "target_id": comment.id, "reason": "spam"})
        assert r.status_code == 403, r.text
        assert test_db.query(models.ContentReport).count() == 0

    def test_unverified_cannot_join(self, client, test_db):
        org = _org(test_db, join_policy="open")
        owner = _user(test_db, "owner"); _member(test_db, org, owner, role="steward")
        unv = _user(test_db, "unv", email_verified=False)
        test_db.commit()
        r = client.post("/api/orgs/acme/join-request", headers=_auth(unv))
        assert r.status_code == 403, r.text
        assert test_db.query(models.OrgMembership).filter_by(
            org_id=org.id, user_id=unv.id).first() is None

    def test_verified_can_comment(self, client, test_db):
        org, author, unv, proposal, comment = self._org_author_unverified(test_db)
        r = client.post(f"/api/proposals/{proposal.id}/comments",
                        headers=_auth(author), json={"body": "ok"})
        assert r.status_code == 201, r.text


# ===========================================================================
# Demo reset — content_reports scoped to demo orgs are wiped
# ===========================================================================

def test_demo_reset_wipes_content_reports(test_db):
    from demo_reset_job import _wipe_demo_orgs
    demo = _org(test_db, slug="demo-org", is_demo=True)
    author = _user(test_db, "dauthor"); _member(test_db, demo, author, role="member")
    reporter = _user(test_db, "dreporter"); _member(test_db, demo, reporter, role="member")
    proposal = _proposal(test_db, author, org=demo)
    comment = _comment(test_db, author, proposal)
    test_db.add(models.ContentReport(
        org_id=demo.id, reporter_id=reporter.id, target_type="comment",
        target_id=comment.id, reason="spam", status="open",
    ))
    test_db.commit()
    assert test_db.query(models.ContentReport).count() == 1

    _wipe_demo_orgs(test_db, [demo])
    test_db.commit()
    assert test_db.query(models.ContentReport).filter_by(org_id=demo.id).count() == 0
