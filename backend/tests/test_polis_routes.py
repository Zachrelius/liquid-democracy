"""Phase 9 Session 2 — Integration tests for Polis routes + proposal-link
extensions + audit-event coverage.

Mirrors `test_sub_org_routes.py` style: in-memory SQLite, FastAPI TestClient,
function-scoped fixtures. HTTP boundaries to pol.is are mocked via
monkeypatching `polis_service`'s httpx call sites and (for the route-level
control flow) the `polis_service.create_conversation` /
`archive_conversation` / `fetch_export` entry points themselves.

Coverage:
  - Sub-org Polis CRUD round-trip (create -> get -> list -> patch-archive)
  - Two-path create: programmatic-with-token vs. manual-fallback-without-token
  - intended_seed_statements stored regardless of which path runs
  - Multi-persona scope visibility: alice/dave/carol/voter02/frank
  - Permission gating: parent-org admin can archive sub-org Polis (Decision 6);
    non-admin sub-org member cannot
  - xid endpoint: idempotent + per-org isolated
  - Proposal create with valid linked_polis_ids; rejected on
    nonexistent / archived / out-of-scope
  - require_polis_for_new_proposals enforcement (org-level + sub-org override)
  - Composite audit event coverage — all 6 new event types fire in sequence
  - Export endpoint admin/non-admin gating + deanonymization
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
import polis_service
from database import Base, get_db
from tests.conftest import make_org_membership
from main import app
from settings import settings as app_settings


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


@pytest.fixture(scope="function")
def db():
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
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _no_polis_token(monkeypatch):
    """Default: POLIS_AUTH_TOKEN unset. Tests that need the programmatic
    path opt in by monkeypatching back to a non-empty value."""
    monkeypatch.setattr(app_settings, "polis_auth_token", "")
    monkeypatch.setattr(app_settings, "polis_api_base_url", "https://pol.is")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user(db: Session, username: str) -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=True,
    )
    db.add(u); db.flush()
    return u


def _org(
    db: Session, slug: str = "parent", parent_org_id: str | None = None,
    settings: dict | None = None,
) -> models.Organization:
    org = models.Organization(
        name=slug.replace("-", " ").title(), slug=slug, description="",
        join_policy="open" if parent_org_id is None else "invite_only",
        settings=settings or {}, parent_org_id=parent_org_id,
    )
    db.add(org); db.flush()
    return org


def _membership(db, org, user, role="member", status="active"):
    return make_org_membership(
        db, user_id=user.id, org_id=org.id, role=role, status=status,
    )


def _sub_membership(db, sub_org, user, role="member", status="active"):
    from tests.conftest import make_sub_org_membership
    return make_sub_org_membership(
        db, sub_org_id=sub_org.id, user_id=user.id,
        role=role, status=status,
    )


def _polis_row(
    db, org, creator, *, sub_org=None, status="active",
    title="P", prompt="Q", conversation_id="manual-conv-id",
):
    p = models.Polis(
        org_id=org.id,
        sub_org_id=sub_org.id if sub_org else None,
        title=title, prompt=prompt,
        created_by=creator.id, status=status,
        polis_conversation_id=conversation_id,
    )
    db.add(p); db.flush()
    return p


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _audit(db, action: str | None = None) -> list[models.AuditLog]:
    q = db.query(models.AuditLog)
    if action:
        q = q.filter(models.AuditLog.action == action)
    return q.order_by(models.AuditLog.timestamp).all()


# ===========================================================================
# CRUD round-trip
# ===========================================================================

class TestPolisCRUD:
    def test_create_org_wide_polis_round_trip(self, db, client):
        admin = _user(db, "admin")
        parent = _org(db, "parent")
        _membership(db, parent, admin, role="admin")
        db.commit()

        resp = client.post(
            f"/api/orgs/{parent.slug}/polises",
            json={
                "title": "Org-wide Polis",
                "prompt": "What should we do?",
                "seed_statements": ["s1", "s2"],
                "polis_conversation_id": "manual-1",
            },
            headers=_auth(admin),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["programmatic_path"] is False
        assert body["manual_seed_statements_required"] is True
        assert body["polis"]["title"] == "Org-wide Polis"
        assert body["polis"]["polis_conversation_id"] == "manual-1"
        assert body["polis"]["intended_seed_statements"] == ["s1", "s2"]
        polis_id = body["polis"]["id"]

        # Get
        resp = client.get(
            f"/api/orgs/{parent.slug}/polises/{polis_id}",
            headers=_auth(admin),
        )
        assert resp.status_code == 200
        gbody = resp.json()
        assert gbody["id"] == polis_id
        assert "participation_stats" in gbody

        # List
        resp = client.get(
            f"/api/orgs/{parent.slug}/polises", headers=_auth(admin),
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        # Patch (archive)
        resp = client.patch(
            f"/api/orgs/{parent.slug}/polises/{polis_id}",
            json={"status": "archived"},
            headers=_auth(admin),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "archived"
        assert resp.json()["archived_at"] is not None

    def test_create_sub_org_polis_round_trip(self, db, client):
        admin = _user(db, "admin")
        dave = _user(db, "dave")
        parent = _org(db, "parent")
        sub = _org(db, "engineering", parent_org_id=parent.id)
        _membership(db, parent, admin, role="admin")
        _membership(db, parent, dave, role="member")
        _sub_membership(db, sub, dave, role="admin")
        db.commit()

        resp = client.post(
            f"/api/orgs/{parent.slug}/polises",
            json={
                "title": "Eng Tooling",
                "prompt": "What tools next?",
                "sub_org_id": sub.id,
                "seed_statements": ["a", "b"],
                "polis_conversation_id": "eng-1",
            },
            headers=_auth(dave),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["polis"]["sub_org_id"] == sub.id
        assert resp.json()["polis"]["intended_seed_statements"] == ["a", "b"]

    def test_manual_fallback_requires_conversation_id(self, db, client):
        admin = _user(db, "admin")
        parent = _org(db, "parent")
        _membership(db, parent, admin, role="admin")
        db.commit()

        resp = client.post(
            f"/api/orgs/{parent.slug}/polises",
            json={
                "title": "Missing", "prompt": "Q",
                "seed_statements": ["s"],
                # no polis_conversation_id
            },
            headers=_auth(admin),
        )
        assert resp.status_code == 400
        assert "polis_conversation_id" in resp.json()["detail"]

    def test_programmatic_path_when_token_set(self, db, client, monkeypatch):
        """With POLIS_AUTH_TOKEN set, route calls polis_service.create_conversation."""
        monkeypatch.setattr(app_settings, "polis_auth_token", "test-jwt")

        captured = {}

        def fake_create_conversation(title, prompt, seed_statements=None):
            captured["title"] = title
            captured["prompt"] = prompt
            captured["seed_statements"] = list(seed_statements or [])
            return {
                "conversation_id": "fake-conv-1",
                "embed_url": "https://pol.is/fake-conv-1",
                "manage_url": "https://pol.is/m/fake-conv-1",
                "seed_statement_results": [
                    {"text": s, "ok": True} for s in (seed_statements or [])
                ],
            }

        monkeypatch.setattr(
            polis_service, "create_conversation", fake_create_conversation,
        )

        admin = _user(db, "admin")
        parent = _org(db, "parent")
        _membership(db, parent, admin, role="admin")
        db.commit()

        resp = client.post(
            f"/api/orgs/{parent.slug}/polises",
            json={
                "title": "Auto",
                "prompt": "Programmatic prompt",
                "seed_statements": ["s1", "s2", "s3"],
                # operator-supplied conversation_id ignored when token set
                "polis_conversation_id": "should-be-ignored",
            },
            headers=_auth(admin),
        )
        assert resp.status_code == 201, resp.text
        b = resp.json()
        assert b["programmatic_path"] is True
        # Conversation_id comes from API, not from operator.
        assert b["polis"]["polis_conversation_id"] == "fake-conv-1"
        assert b["polis"]["intended_seed_statements"] == ["s1", "s2", "s3"]
        assert captured["title"] == "Auto"
        assert captured["seed_statements"] == ["s1", "s2", "s3"]
        assert b.get("manual_seed_statements_required") in (None, False)

    def test_programmatic_path_partial_seed_failure_surfaced(
        self, db, client, monkeypatch,
    ):
        monkeypatch.setattr(app_settings, "polis_auth_token", "test-jwt")

        def fake_create(title, prompt, seed_statements=None):
            results = []
            for s in seed_statements or []:
                results.append(
                    {"text": s, "ok": s != "bad", "error": None if s != "bad" else "x"}
                )
            return {
                "conversation_id": "c2",
                "embed_url": "https://pol.is/c2",
                "manage_url": "https://pol.is/m/c2",
                "seed_statement_results": results,
            }

        monkeypatch.setattr(polis_service, "create_conversation", fake_create)

        admin = _user(db, "admin")
        parent = _org(db, "parent")
        _membership(db, parent, admin, role="admin")
        db.commit()

        resp = client.post(
            f"/api/orgs/{parent.slug}/polises",
            json={
                "title": "Auto", "prompt": "P",
                "seed_statements": ["good", "bad", "good2"],
            },
            headers=_auth(admin),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["programmatic_path"] is True
        failures = body.get("partial_seed_failures") or []
        assert len(failures) == 1
        assert failures[0]["text"] == "bad"

    def test_programmatic_path_api_failure_no_orphan(
        self, db, client, monkeypatch,
    ):
        """If pol.is API call fails, NO platform-side row is created."""
        monkeypatch.setattr(app_settings, "polis_auth_token", "test-jwt")

        def fake_create(title, prompt, seed_statements=None):
            raise polis_service.PolisAPIError("simulated outage", status_code=502)

        monkeypatch.setattr(polis_service, "create_conversation", fake_create)

        admin = _user(db, "admin")
        parent = _org(db, "parent")
        _membership(db, parent, admin, role="admin")
        db.commit()

        resp = client.post(
            f"/api/orgs/{parent.slug}/polises",
            json={"title": "Auto", "prompt": "P", "seed_statements": ["s1"]},
            headers=_auth(admin),
        )
        assert resp.status_code == 502
        assert db.query(models.Polis).count() == 0


# ===========================================================================
# Permissions
# ===========================================================================

class TestPolisPermissions:
    def test_parent_org_admin_can_archive_sub_org_polis(self, db, client):
        """Decision 6 — parent-org admin implicit power."""
        alice = _user(db, "alice")  # parent admin
        dave = _user(db, "dave")    # sub-org member only
        parent = _org(db, "parent")
        sub = _org(db, "eng", parent_org_id=parent.id)
        _membership(db, parent, alice, role="admin")
        _membership(db, parent, dave, role="member")
        _sub_membership(db, sub, dave, role="admin")
        polis = _polis_row(db, parent, dave, sub_org=sub)
        db.commit()

        resp = client.patch(
            f"/api/orgs/{parent.slug}/polises/{polis.id}",
            json={"status": "archived"},
            headers=_auth(alice),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "archived"

    def test_non_admin_sub_org_member_cannot_archive(self, db, client):
        alice = _user(db, "alice")
        bob = _user(db, "bob")  # plain sub-org member
        parent = _org(db, "parent")
        sub = _org(db, "eng", parent_org_id=parent.id)
        _membership(db, parent, alice, role="admin")
        _membership(db, parent, bob, role="member")
        _sub_membership(db, sub, bob, role="member")
        polis = _polis_row(db, parent, alice, sub_org=sub)
        db.commit()

        resp = client.patch(
            f"/api/orgs/{parent.slug}/polises/{polis.id}",
            json={"status": "archived"},
            headers=_auth(bob),
        )
        assert resp.status_code == 403

    def test_org_wide_polis_creation_requires_moderator_plus(self, db, client):
        plain = _user(db, "plain")
        parent = _org(db, "parent")
        _membership(db, parent, plain, role="member")
        db.commit()

        resp = client.post(
            f"/api/orgs/{parent.slug}/polises",
            json={"title": "x", "prompt": "y", "polis_conversation_id": "c1"},
            headers=_auth(plain),
        )
        assert resp.status_code == 403


# ===========================================================================
# Phase 9 Session 4 — one-shot conversation_id connect (manual-fallback wire-up)
# ===========================================================================

class TestPolisConnectConversationId:
    """PATCH-with-polis_conversation_id: the success-panel "paste slug"
    flow's backend half. One-shot connect — only valid when current value
    is NULL; rejects empty/whitespace; emits `polis.connected`."""

    def test_allowed_when_null_emits_connected_audit(self, db, client):
        admin = _user(db, "admin")
        parent = _org(db, "parent")
        _membership(db, parent, admin, role="admin")
        # Create a Polis without a conversation_id (manual-fallback pre-paste).
        polis = _polis_row(db, parent, admin, conversation_id=None)
        db.commit()
        polis_id = polis.id

        resp = client.patch(
            f"/api/orgs/{parent.slug}/polises/{polis_id}",
            json={"polis_conversation_id": "manual-pasted-slug"},
            headers=_auth(admin),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["polis_conversation_id"] == "manual-pasted-slug"

        db.expire_all()
        refreshed = db.query(models.Polis).filter(
            models.Polis.id == polis_id,
        ).first()
        assert refreshed.polis_conversation_id == "manual-pasted-slug"

        events = _audit(db, action="polis.connected")
        assert len(events) == 1
        assert events[0].details["polis_id"] == polis_id
        assert events[0].details["polis_conversation_id"] == "manual-pasted-slug"

    def test_rejected_when_already_set(self, db, client):
        admin = _user(db, "admin")
        parent = _org(db, "parent")
        _membership(db, parent, admin, role="admin")
        polis = _polis_row(db, parent, admin, conversation_id="existing-conv-id")
        db.commit()

        resp = client.patch(
            f"/api/orgs/{parent.slug}/polises/{polis.id}",
            json={"polis_conversation_id": "different-id"},
            headers=_auth(admin),
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"].lower()
        assert "irreversible" in detail or "one-shot" in detail
        # No connected audit emitted.
        assert _audit(db, action="polis.connected") == []
        # Original conversation_id preserved.
        db.expire_all()
        refreshed = db.query(models.Polis).filter(
            models.Polis.id == polis.id,
        ).first()
        assert refreshed.polis_conversation_id == "existing-conv-id"

    def test_empty_or_whitespace_rejected(self, db, client):
        admin = _user(db, "admin")
        parent = _org(db, "parent")
        _membership(db, parent, admin, role="admin")
        polis = _polis_row(db, parent, admin, conversation_id=None)
        db.commit()

        for bad in ("", "   ", "\t\n "):
            resp = client.patch(
                f"/api/orgs/{parent.slug}/polises/{polis.id}",
                json={"polis_conversation_id": bad},
                headers=_auth(admin),
            )
            assert resp.status_code == 400, (bad, resp.text)
            assert "non-empty" in resp.json()["detail"].lower()
        # No connected audit ever emitted.
        assert _audit(db, action="polis.connected") == []
        # Polis still null.
        db.expire_all()
        refreshed = db.query(models.Polis).filter(
            models.Polis.id == polis.id,
        ).first()
        assert refreshed.polis_conversation_id is None


# ===========================================================================
# List scope visibility
# ===========================================================================

class TestPolisListScope:
    def _setup_personas(self, db):
        """Build alice (parent admin) / dave (sub-org admin) / bob (sub-org
        member) / frank (parent-only member) on an Engineering sub-org."""
        alice = _user(db, "alice")
        dave = _user(db, "dave")
        bob = _user(db, "bob")
        frank = _user(db, "frank")
        parent = _org(db, "parent")
        return alice, dave, bob, frank, parent

    def test_org_wide_polis_visible_to_all_parent_members(self, db, client):
        alice, dave, bob, frank, parent = self._setup_personas(db)
        _membership(db, parent, alice, role="admin")
        _membership(db, parent, frank, role="member")
        _polis_row(db, parent, alice, title="Org wide")
        db.commit()

        for actor in (alice, frank):
            resp = client.get(
                f"/api/orgs/{parent.slug}/polises",
                headers=_auth(actor),
            )
            assert resp.status_code == 200
            assert len(resp.json()) == 1

    def test_sub_org_polis_private_hidden_from_non_member(self, db, client):
        """Decision 7 — when sub-org settings.private=true, parent-only
        member doesn't see sub-org Polis."""
        alice, dave, bob, frank, parent = self._setup_personas(db)
        sub = _org(db, "eng", parent_org_id=parent.id, settings={"private": True})
        _membership(db, parent, alice, role="admin")
        _membership(db, parent, dave, role="member")
        _membership(db, parent, frank, role="member")
        _sub_membership(db, sub, dave, role="admin")
        _polis_row(db, parent, dave, sub_org=sub, title="Eng polis")
        db.commit()

        # Frank: parent-only, sub is private -> should NOT see Engineering Polis
        resp = client.get(
            f"/api/orgs/{parent.slug}/polises", headers=_auth(frank),
        )
        assert resp.status_code == 200
        titles = [p["title"] for p in resp.json()]
        assert "Eng polis" not in titles

        # Dave: sub-org member -> sees it
        resp = client.get(
            f"/api/orgs/{parent.slug}/polises", headers=_auth(dave),
        )
        assert "Eng polis" in [p["title"] for p in resp.json()]

        # Alice: parent admin -> sees it (Decision 6)
        resp = client.get(
            f"/api/orgs/{parent.slug}/polises", headers=_auth(alice),
        )
        assert "Eng polis" in [p["title"] for p in resp.json()]

    def test_sub_org_polis_default_visibility_to_parent_members(self, db, client):
        """Decision 7 default — sub-org NOT private => parent member sees it."""
        alice, dave, bob, frank, parent = self._setup_personas(db)
        sub = _org(db, "eng", parent_org_id=parent.id, settings={})  # not private
        _membership(db, parent, alice, role="admin")
        _membership(db, parent, dave, role="member")
        _membership(db, parent, frank, role="member")
        _sub_membership(db, sub, dave, role="admin")
        _polis_row(db, parent, dave, sub_org=sub, title="Eng polis open")
        db.commit()

        resp = client.get(
            f"/api/orgs/{parent.slug}/polises", headers=_auth(frank),
        )
        assert "Eng polis open" in [p["title"] for p in resp.json()]


# ===========================================================================
# xid endpoint
# ===========================================================================

class TestPolisXid:
    def test_xid_idempotent_on_repeat(self, db, client):
        alice = _user(db, "alice")
        parent = _org(db, "parent")
        _membership(db, parent, alice, role="member")
        polis = _polis_row(db, parent, alice)
        db.commit()

        resp1 = client.post(
            f"/api/orgs/{parent.slug}/polises/{polis.id}/xid",
            json={}, headers=_auth(alice),
        )
        assert resp1.status_code == 200
        x1 = resp1.json()["polis_xid"]

        resp2 = client.post(
            f"/api/orgs/{parent.slug}/polises/{polis.id}/xid",
            json={}, headers=_auth(alice),
        )
        assert resp2.json()["polis_xid"] == x1

    def test_xid_per_org_isolated(self, db, client):
        alice = _user(db, "alice")
        org_a = _org(db, "org-a")
        org_b = _org(db, "org-b")
        _membership(db, org_a, alice, role="member")
        _membership(db, org_b, alice, role="member")
        polis_a = _polis_row(db, org_a, alice)
        polis_b = _polis_row(db, org_b, alice)
        db.commit()

        r_a = client.post(
            f"/api/orgs/{org_a.slug}/polises/{polis_a.id}/xid",
            json={}, headers=_auth(alice),
        )
        r_b = client.post(
            f"/api/orgs/{org_b.slug}/polises/{polis_b.id}/xid",
            json={}, headers=_auth(alice),
        )
        assert r_a.json()["polis_xid"] != r_b.json()["polis_xid"]


# ===========================================================================
# Proposal linked_polis_ids validation
# ===========================================================================

class TestProposalLinkedPolises:
    def _setup(self, db):
        alice = _user(db, "alice")
        parent = _org(db, "parent")
        _membership(db, parent, alice, role="moderator")
        return alice, parent

    def test_create_with_valid_link(self, db, client):
        alice, parent = self._setup(db)
        polis = _polis_row(db, parent, alice)
        db.commit()

        resp = client.post(
            f"/api/orgs/{parent.slug}/proposals",
            json={
                "title": "P", "body": "",
                "voting_method": "binary",
                "linked_polis_ids": [polis.id],
            },
            headers=_auth(alice),
        )
        assert resp.status_code == 201, resp.text
        prop = resp.json()
        assert prop["linked_polis_ids"] == [polis.id]

    def test_create_rejects_nonexistent_link(self, db, client):
        alice, parent = self._setup(db)
        db.commit()

        resp = client.post(
            f"/api/orgs/{parent.slug}/proposals",
            json={
                "title": "P", "body": "",
                "voting_method": "binary",
                "linked_polis_ids": ["does-not-exist"],
            },
            headers=_auth(alice),
        )
        assert resp.status_code == 400
        assert "does not exist" in resp.json()["detail"]

    def test_create_rejects_archived_polis(self, db, client):
        alice, parent = self._setup(db)
        polis = _polis_row(db, parent, alice, status="archived")
        db.commit()

        resp = client.post(
            f"/api/orgs/{parent.slug}/proposals",
            json={
                "title": "P", "body": "",
                "voting_method": "binary",
                "linked_polis_ids": [polis.id],
            },
            headers=_auth(alice),
        )
        assert resp.status_code == 400
        assert "not active" in resp.json()["detail"]

    def test_create_rejects_out_of_scope_polis(self, db, client):
        alice = _user(db, "alice")
        bob = _user(db, "bob")
        parent_a = _org(db, "org-a")
        parent_b = _org(db, "org-b")
        _membership(db, parent_a, alice, role="moderator")
        _membership(db, parent_b, bob, role="moderator")
        polis_b = _polis_row(db, parent_b, bob)
        db.commit()

        # Alice tries to link a Polis from org-b in an org-a proposal.
        resp = client.post(
            f"/api/orgs/{parent_a.slug}/proposals",
            json={
                "title": "P", "body": "",
                "voting_method": "binary",
                "linked_polis_ids": [polis_b.id],
            },
            headers=_auth(alice),
        )
        assert resp.status_code == 400
        assert "different organization" in resp.json()["detail"]


# ===========================================================================
# require_polis_for_new_proposals
# ===========================================================================

class TestRequirePolis:
    def test_org_setting_blocks_proposal_without_link(self, db, client):
        alice = _user(db, "alice")
        parent = _org(db, "parent", settings={"require_polis_for_new_proposals": True})
        _membership(db, parent, alice, role="moderator")
        db.commit()

        resp = client.post(
            f"/api/orgs/{parent.slug}/proposals",
            json={"title": "P", "body": "", "voting_method": "binary"},
            headers=_auth(alice),
        )
        assert resp.status_code == 400
        assert "require_polis_for_new_proposals" in resp.json()["detail"]

    def test_org_setting_allows_with_link(self, db, client):
        alice = _user(db, "alice")
        parent = _org(db, "parent", settings={"require_polis_for_new_proposals": True})
        _membership(db, parent, alice, role="moderator")
        polis = _polis_row(db, parent, alice)
        db.commit()

        resp = client.post(
            f"/api/orgs/{parent.slug}/proposals",
            json={
                "title": "P", "body": "",
                "voting_method": "binary",
                "linked_polis_ids": [polis.id],
            },
            headers=_auth(alice),
        )
        assert resp.status_code == 201

    def test_sub_org_overrides_parent_setting(self, db, client):
        """Sub-org sets require_polis_for_new_proposals=False; parent has True.
        get_org_config sees the sub-org's local setting first => allow."""
        alice = _user(db, "alice")
        parent = _org(db, "parent", settings={"require_polis_for_new_proposals": True})
        sub = _org(
            db, "sub", parent_org_id=parent.id,
            settings={"require_polis_for_new_proposals": False},
        )
        _membership(db, parent, alice, role="admin")
        _sub_membership(db, sub, alice, role="admin")
        # Wire parent_org relationship (it's lazy-loaded by ORM, but in a
        # SQLite memory engine we need an explicit refresh for the FK
        # relationship to populate before the route reads it).
        db.commit()
        db.refresh(sub)

        resp = client.post(
            f"/api/orgs/{parent.slug}/proposals",
            json={
                "title": "P", "body": "",
                "voting_method": "binary",
                "sub_org_id": sub.id,
                # No linked_polis_ids — sub-org override should let it through
            },
            headers=_auth(alice),
        )
        assert resp.status_code == 201, resp.text


# ===========================================================================
# Composite audit-event coverage
# ===========================================================================

class TestAuditEventCoverage:
    def test_all_polis_audit_events_fire(self, db, client, monkeypatch):
        """Single sequence exercising every Polis-side audit event:
          1. polis.created (manual fallback)
          2. polis.connected (Session 4 — manual-fallback paste-slug Save)
          3. polis.linked_to_proposal (via proposal create)
          4. polis.unlinked_from_proposal (via proposal patch)
          5. polis.config_changed (title edit)
          6. polis.archived
          7. polis.export_requested

        polis.xid_generated is exercised in TestPolisXid; the helper-level
        tests already cover the audit shape (Session 1 unit tests).
        """
        alice = _user(db, "alice")
        parent = _org(db, "parent")
        _membership(db, parent, alice, role="admin")
        db.commit()

        # 1. polis.created — create the Polis WITHOUT a conversation_id so we
        # can test polis.connected on the same row in step 2. The manual-
        # fallback path normally requires polis_conversation_id at create
        # time; bypass that by inserting the row directly via a SQL upsert
        # would couple to internals — instead we create with a placeholder
        # then null it out, which mirrors a future "create-then-paste-later"
        # FE flow. (Spec Session 4: success-panel paste-slug uses this exact
        # sequence: create endpoint returns a row whose conversation_id is
        # operator-supplied; the connect-via-PATCH path is reached only when
        # an admin needs to LATER set/swap, hence the null pre-state.)
        unconnected = models.Polis(
            org_id=parent.id,
            title="Audit-T",
            prompt="Q",
            created_by=alice.id,
            status="active",
            polis_conversation_id=None,
            intended_seed_statements=["s1"],
        )
        db.add(unconnected); db.flush()
        # Emit the polis.created audit event manually to mirror what the
        # POST route does (we sidestepped the route to land in the null-
        # conversation_id pre-state).
        from audit_utils import log_audit_event as _log
        _log(
            db,
            action="polis.created",
            target_type="polis",
            target_id=unconnected.id,
            actor_id=alice.id,
            details={
                "polis_id": unconnected.id,
                "org_id": parent.id,
                "sub_org_id": None,
                "title": "Audit-T",
                "programmatic_path": False,
                "polis_conversation_id": None,
            },
        )
        db.commit()
        polis_id = unconnected.id

        # 2. polis.connected — paste-slug Save flow (Session 4).
        connect_resp = client.patch(
            f"/api/orgs/{parent.slug}/polises/{polis_id}",
            json={"polis_conversation_id": "audit-conv-1"},
            headers=_auth(alice),
        )
        assert connect_resp.status_code == 200, connect_resp.text

        # Create another Polis to enable a swap-link scenario.
        resp2 = client.post(
            f"/api/orgs/{parent.slug}/polises",
            json={
                "title": "Other",
                "prompt": "Q2",
                "polis_conversation_id": "audit-conv-2",
            },
            headers=_auth(alice),
        )
        polis2_id = resp2.json()["polis"]["id"]

        # 2. polis.linked_to_proposal — via proposal create with linked_polis_ids
        prop_resp = client.post(
            f"/api/orgs/{parent.slug}/proposals",
            json={
                "title": "Prop",
                "body": "",
                "voting_method": "binary",
                "linked_polis_ids": [polis_id],
            },
            headers=_auth(alice),
        )
        assert prop_resp.status_code == 201, prop_resp.text
        prop_id = prop_resp.json()["id"]

        # 3. polis.unlinked_from_proposal — patch removes polis_id, adds polis2_id
        # via the global /api/proposals route (PATCH there triggers the
        # link-diff helper).
        patch_resp = client.patch(
            f"/api/proposals/{prop_id}",
            json={"linked_polis_ids": [polis2_id]},
            headers=_auth(alice),
        )
        assert patch_resp.status_code == 200, patch_resp.text

        # 4. polis.config_changed — title edit
        title_resp = client.patch(
            f"/api/orgs/{parent.slug}/polises/{polis_id}",
            json={"title": "Audit-T (renamed)"},
            headers=_auth(alice),
        )
        assert title_resp.status_code == 200

        # 5. polis.archived
        arc_resp = client.patch(
            f"/api/orgs/{parent.slug}/polises/{polis_id}",
            json={"status": "archived"},
            headers=_auth(alice),
        )
        assert arc_resp.status_code == 200

        # 6. polis.export_requested — needs token configured + fetch_export
        # mocked to return raw bytes so the route doesn't 503.
        monkeypatch.setattr(app_settings, "polis_auth_token", "test-jwt")
        monkeypatch.setattr(
            polis_service, "fetch_export", lambda cid: b"votes,xid\n1,abc",
        )
        # Use polis2 because polis_id is archived (export still allowed,
        # but we want to test on a live-conversation_id polis with
        # an active row).
        exp_resp = client.get(
            f"/api/orgs/{parent.slug}/polises/{polis2_id}/export",
            headers=_auth(alice),
        )
        assert exp_resp.status_code == 200

        # Assert all seven event types present (8th is polis.xid_generated,
        # exercised in TestPolisXid + Session 1 unit tests).
        events = {e.action for e in _audit(db)}
        for action in (
            "polis.created",
            "polis.connected",
            "polis.linked_to_proposal",
            "polis.unlinked_from_proposal",
            "polis.config_changed",
            "polis.archived",
            "polis.export_requested",
        ):
            assert action in events, f"missing audit event: {action}"

        # Verify polis.connected payload shape (aggregate-only per Phase 7.5).
        conn_event = next(e for e in _audit(db) if e.action == "polis.connected")
        assert conn_event.details["polis_id"] == polis_id
        assert conn_event.details["polis_conversation_id"] == "audit-conv-1"

        # Verify polis.archived payload includes polis_api_call_result
        arc_event = next(e for e in _audit(db) if e.action == "polis.archived")
        assert "polis_api_call_result" in arc_event.details
        assert arc_event.details["polis_api_call_result"] in (
            "success", "failed", "no_token",
        )

        # Verify polis.config_changed payload uses the diff shape
        cc_event = next(e for e in _audit(db) if e.action == "polis.config_changed")
        assert "changes" in cc_event.details
        assert cc_event.details["changes"]["title"]["old"] == "Audit-T"
        assert cc_event.details["changes"]["title"]["new"] == "Audit-T (renamed)"

        # Verify export_requested NOT in event details (Phase 7.5 redaction)
        ex_event = next(e for e in _audit(db) if e.action == "polis.export_requested")
        assert "deanonymized" in ex_event.details
        # No raw bytes, no contents.
        assert "content" not in ex_event.details
        assert "csv" not in ex_event.details


# ===========================================================================
# Export endpoint
# ===========================================================================

class TestPolisExport:
    def test_export_admin_succeeds(self, db, client, monkeypatch):
        monkeypatch.setattr(app_settings, "polis_auth_token", "test-jwt")
        monkeypatch.setattr(
            polis_service, "fetch_export", lambda cid: b"raw,csv,here",
        )
        admin = _user(db, "admin")
        parent = _org(db, "parent")
        _membership(db, parent, admin, role="admin")
        polis = _polis_row(db, parent, admin)
        db.commit()

        resp = client.get(
            f"/api/orgs/{parent.slug}/polises/{polis.id}/export",
            headers=_auth(admin),
        )
        assert resp.status_code == 200
        assert resp.content == b"raw,csv,here"

    def test_export_non_admin_blocked(self, db, client, monkeypatch):
        monkeypatch.setattr(app_settings, "polis_auth_token", "test-jwt")
        admin = _user(db, "admin")
        plain = _user(db, "plain")
        parent = _org(db, "parent")
        _membership(db, parent, admin, role="admin")
        _membership(db, parent, plain, role="member")
        polis = _polis_row(db, parent, admin)
        db.commit()

        resp = client.get(
            f"/api/orgs/{parent.slug}/polises/{polis.id}/export",
            headers=_auth(plain),
        )
        assert resp.status_code == 403

    def test_export_503_when_token_missing(self, db, client):
        admin = _user(db, "admin")
        parent = _org(db, "parent")
        _membership(db, parent, admin, role="admin")
        polis = _polis_row(db, parent, admin)
        db.commit()

        resp = client.get(
            f"/api/orgs/{parent.slug}/polises/{polis.id}/export",
            headers=_auth(admin),
        )
        assert resp.status_code == 503
        assert "manual export" in resp.json()["detail"].lower()

    def test_export_deanonymized_includes_user_mapping(
        self, db, client, monkeypatch,
    ):
        """?deanonymize=true prepends an xid -> user mapping section."""
        monkeypatch.setattr(app_settings, "polis_auth_token", "test-jwt")
        monkeypatch.setattr(
            polis_service, "fetch_export", lambda cid: b"votes,xid\n1,abc",
        )
        admin = _user(db, "admin")
        parent = _org(db, "parent")
        _membership(db, parent, admin, role="admin")
        polis = _polis_row(db, parent, admin)
        # Pre-create an xid row so the mapping isn't empty.
        xid_row = models.PolisXid(
            user_id=admin.id, org_id=parent.id, polis_xid="testxid123",
        )
        db.add(xid_row)
        db.commit()

        resp = client.get(
            f"/api/orgs/{parent.slug}/polises/{polis.id}/export?deanonymize=true",
            headers=_auth(admin),
        )
        assert resp.status_code == 200
        assert resp.headers.get("X-Polis-Deanonymized") == "true"
        body = resp.content
        assert b"testxid123" in body
        assert b"--- POLIS EXPORT ---" in body
        # Original export bytes preserved AFTER the separator.
        assert body.endswith(b"votes,xid\n1,abc")


# ===========================================================================
# Phase 81 — link-existing simplification: topic/description optional,
# conversation_id required, seed field retained for back-compat, topic
# clearable via PATCH. (autouse _no_polis_token keeps the token unset =
# prod state.)
# ===========================================================================

class TestPhase81LinkExisting:
    def test_create_with_no_topic_or_description(self, db, client):
        # VM #1 — empty topic/description + conversation_id persists "".
        admin = _user(db, "admin")
        parent = _org(db, "parent")
        _membership(db, parent, admin, role="admin")
        db.commit()

        resp = client.post(
            f"/api/orgs/{parent.slug}/polises",
            json={"polis_conversation_id": "3jrhnuhnjs"},
            headers=_auth(admin),
        )
        assert resp.status_code == 201, resp.text
        pid = resp.json()["polis"]["id"]
        row = db.get(models.Polis, pid)
        assert row.title == ""
        assert row.prompt == ""
        assert row.polis_conversation_id == "3jrhnuhnjs"
        assert row.intended_seed_statements is None

    def test_create_with_topic_and_description(self, db, client):
        # VM #2 — trimmed values persist.
        admin = _user(db, "admin")
        parent = _org(db, "parent")
        _membership(db, parent, admin, role="admin")
        db.commit()

        resp = client.post(
            f"/api/orgs/{parent.slug}/polises",
            json={
                "polis_conversation_id": "abc123",
                "title": "  Budget priorities  ",
                "prompt": "  What should we fund?  ",
            },
            headers=_auth(admin),
        )
        assert resp.status_code == 201, resp.text
        row = db.get(models.Polis, resp.json()["polis"]["id"])
        assert row.title == "Budget priorities"
        assert row.prompt == "What should we fund?"

    def test_create_whitespace_topic_collapses_to_empty(self, db, client):
        # VM #3 — _blank_to_empty validator.
        admin = _user(db, "admin")
        parent = _org(db, "parent")
        _membership(db, parent, admin, role="admin")
        db.commit()

        resp = client.post(
            f"/api/orgs/{parent.slug}/polises",
            json={"polis_conversation_id": "ws1", "title": "   ", "prompt": "  "},
            headers=_auth(admin),
        )
        assert resp.status_code == 201, resp.text
        row = db.get(models.Polis, resp.json()["polis"]["id"])
        assert row.title == ""
        assert row.prompt == ""

    def test_create_without_conversation_id_400_no_fallback_term(self, db, client):
        # VM #4 — required conversation_id; reworded detail (no "manual-fallback").
        admin = _user(db, "admin")
        parent = _org(db, "parent")
        _membership(db, parent, admin, role="admin")
        db.commit()

        resp = client.post(
            f"/api/orgs/{parent.slug}/polises",
            json={"title": "No conv id"},
            headers=_auth(admin),
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "polis_conversation_id" in detail
        assert "manual-fallback" not in detail.lower()

    def test_create_still_accepts_seed_statements_backcompat(self, db, client):
        # VM #5 — retained field / Phase 69 path: seeds still stored.
        admin = _user(db, "admin")
        parent = _org(db, "parent")
        _membership(db, parent, admin, role="admin")
        db.commit()

        resp = client.post(
            f"/api/orgs/{parent.slug}/polises",
            json={
                "polis_conversation_id": "bc1",
                "seed_statements": ["one", "two"],
            },
            headers=_auth(admin),
        )
        assert resp.status_code == 201, resp.text
        row = db.get(models.Polis, resp.json()["polis"]["id"])
        assert row.intended_seed_statements == ["one", "two"]

    def test_patch_title_to_empty_clears_topic(self, db, client):
        # VM #6 — min_length drop lets the discussion topic be cleared.
        admin = _user(db, "admin")
        parent = _org(db, "parent")
        _membership(db, parent, admin, role="admin")
        polis = _polis_row(db, parent, admin, title="Has a topic")
        db.commit()

        resp = client.patch(
            f"/api/orgs/{parent.slug}/polises/{polis.id}",
            json={"title": ""},
            headers=_auth(admin),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["title"] == ""
        db.refresh(polis)
        assert polis.title == ""

    def test_polisout_serializes_empty_title(self, db, client):
        # VM #7 — a title="" row serializes fine on GET.
        admin = _user(db, "admin")
        parent = _org(db, "parent")
        _membership(db, parent, admin, role="admin")
        polis = _polis_row(db, parent, admin, title="", prompt="")
        db.commit()

        resp = client.get(
            f"/api/orgs/{parent.slug}/polises/{polis.id}",
            headers=_auth(admin),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["title"] == ""
        assert resp.json()["prompt"] == ""


# ===========================================================================
# Phase 82 C1 — seed-statement generator (module + route) and C2 access.
# ===========================================================================

import polis_seed_generator  # noqa: E402


class TestPhase82SeedGeneratorModule:
    def test_parses_trims_dedupes(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        called = {}

        def fake(*, system, user, api_key, model):
            called["yes"] = True
            return '["  A  ", "B", "B", "", "C"]'

        monkeypatch.setattr(polis_seed_generator, "_call_anthropic", fake)
        out, warn = polis_seed_generator.generate_statements(topic="Housing")
        assert warn is None
        assert out == ["A", "B", "C"]  # trimmed, deduped, empties dropped
        assert called.get("yes") is True

    def test_empty_input_does_not_call_api(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        called = {}

        def fake(**kwargs):
            called["yes"] = True
            return "[]"

        monkeypatch.setattr(polis_seed_generator, "_call_anthropic", fake)
        out, warn = polis_seed_generator.generate_statements(
            topic="", description="", steer="",
        )
        assert out == []
        assert warn is not None
        assert "yes" not in called  # API was NOT invoked

    def test_api_failure_degrades_no_raise(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        def boom(**kwargs):
            raise RuntimeError("transport down")

        monkeypatch.setattr(polis_seed_generator, "_call_anthropic", boom)
        out, warn = polis_seed_generator.generate_statements(topic="Housing")
        assert out == []
        assert warn

    def test_unparseable_output_degrades(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setattr(
            polis_seed_generator, "_call_anthropic",
            lambda **k: "here are some statements: nope",
        )
        out, warn = polis_seed_generator.generate_statements(topic="Housing")
        assert out == []
        assert warn


class TestPhase82SeedGeneratorRoute:
    def test_503_when_unconfigured(self, db, client, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        admin = _user(db, "admin")
        parent = _org(db, "parent")
        _membership(db, parent, admin, role="admin")
        db.commit()
        r = client.post(
            f"/api/orgs/{parent.slug}/polises/seed-statements/generate",
            json={"topic": "Housing"},
            headers=_auth(admin),
        )
        assert r.status_code == 503

    def test_member_without_perm_forbidden(self, db, client, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        admin = _user(db, "admin")
        member = _user(db, "member")
        parent = _org(db, "parent")
        _membership(db, parent, admin, role="admin")
        _membership(db, parent, member, role="member")
        db.commit()
        r = client.post(
            f"/api/orgs/{parent.slug}/polises/seed-statements/generate",
            json={"topic": "Housing"},
            headers=_auth(member),
        )
        assert r.status_code == 403

    def test_org_description_only_sent_when_opted_in(self, db, client, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        captured = {}

        def fake(*, system, user, api_key, model):
            captured["user"] = user
            return '["A statement"]'

        monkeypatch.setattr(polis_seed_generator, "_call_anthropic", fake)
        admin = _user(db, "admin")
        parent = _org(db, "parent")
        parent.description = "We are the Maple Street tenants union."
        _membership(db, parent, admin, role="admin")
        db.commit()

        # Opted in → org description reaches the user message.
        r = client.post(
            f"/api/orgs/{parent.slug}/polises/seed-statements/generate",
            json={"topic": "Repairs", "include_org_description": True},
            headers=_auth(admin),
        )
        assert r.status_code == 200, r.text
        assert "Maple Street tenants union" in captured["user"]

        # Opted out → absent.
        captured.clear()
        r = client.post(
            f"/api/orgs/{parent.slug}/polises/seed-statements/generate",
            json={"topic": "Repairs", "include_org_description": False},
            headers=_auth(admin),
        )
        assert r.status_code == 200, r.text
        assert "Maple Street tenants union" not in captured["user"]

    def test_audit_does_not_log_statement_text(self, db, client, monkeypatch):
        import json as _json
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        monkeypatch.setattr(
            polis_seed_generator, "_call_anthropic",
            lambda **k: '["Secret confidential statement"]',
        )
        admin = _user(db, "admin")
        parent = _org(db, "parent")
        _membership(db, parent, admin, role="admin")
        db.commit()
        r = client.post(
            f"/api/orgs/{parent.slug}/polises/seed-statements/generate",
            json={"topic": "Housing"},
            headers=_auth(admin),
        )
        assert r.status_code == 200, r.text
        assert r.json()["statements"] == ["Secret confidential statement"]
        audits = _audit(db, "polis.seed_statements_generated")
        assert len(audits) >= 1
        details = audits[-1].details
        if not isinstance(details, dict):
            details = _json.loads(details)
        assert details.get("count") == 1
        assert "Secret confidential statement" not in _json.dumps(details)


class TestPhase82MemberAccess:
    def test_private_suborg_polis_hidden_from_non_member(self, db, client):
        # VM #13 — eligibility filter (load-bearing).
        admin = _user(db, "admin")
        outsider = _user(db, "outsider")
        parent = _org(db, "parent")
        sub = _org(db, "engineering", parent_org_id=parent.id,
                   settings={"private": True})
        _membership(db, parent, admin, role="admin")
        _membership(db, parent, outsider, role="member")  # parent member, NOT in sub
        polis = _polis_row(db, parent, admin, sub_org=sub, conversation_id="c1")
        db.commit()

        # list as outsider → the private sub-org polis must NOT appear.
        r = client.get(
            f"/api/orgs/{parent.slug}/polises", headers=_auth(outsider),
        )
        assert r.status_code == 200, r.text
        assert polis.id not in [p["id"] for p in r.json()]

        # has-visible → False (no org-wide polis, sub is private).
        r2 = client.get(
            f"/api/orgs/{parent.slug}/polises/has-visible",
            headers=_auth(outsider),
        )
        assert r2.json()["has_visible"] is False

    def test_org_wide_polis_visible_and_has_visible_true(self, db, client):
        admin = _user(db, "admin")
        member = _user(db, "member")
        parent = _org(db, "parent")
        _membership(db, parent, admin, role="admin")
        _membership(db, parent, member, role="member")
        polis = _polis_row(db, parent, admin, conversation_id="c2")
        db.commit()

        r = client.get(
            f"/api/orgs/{parent.slug}/polises", headers=_auth(member),
        )
        assert r.status_code == 200
        assert polis.id in [p["id"] for p in r.json()]

        r2 = client.get(
            f"/api/orgs/{parent.slug}/polises/has-visible",
            headers=_auth(member),
        )
        assert r2.json()["has_visible"] is True
