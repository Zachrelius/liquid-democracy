"""Phase 28 — delegation table consolidation tests.

Covers backend clusters B1 (auto-precedence on PUT upsert), B2
(auto-cleanup on revoke), B3 (backfill migration), and an end-to-end
delegate+reorder integration scenario.

Uses TestClient + the existing get_db override pattern from prior
phase test files.
"""
from __future__ import annotations

import pytest
import uuid as _uuid
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
import schemas  # noqa: F401
from database import Base, get_db
from main import app
from tests.conftest import make_org_membership


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def api_db():
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


def _make_client(db: Session) -> TestClient:
    def _override_db():
        try:
            yield db
        finally:
            pass
    app.dependency_overrides[get_db] = _override_db
    return TestClient(app)


def _user(db: Session, username: str, *, email_verified: bool = True) -> models.User:
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


def _org(db: Session, slug: str) -> models.Organization:
    o = models.Organization(
        name=f"Org {slug}",
        slug=slug,
        description="",
        join_policy="open",
        settings={},
    )
    db.add(o)
    db.flush()
    return o


def _topic(db: Session, name: str, org: models.Organization) -> models.Topic:
    t = models.Topic(name=name, description="", color="#000", org_id=org.id)
    db.add(t)
    db.flush()
    return t


def _follow(db: Session, follower: models.User, followed: models.User, org: models.Organization, perm: str = "delegation_allowed"):
    fr = models.FollowRelationship(
        follower_id=follower.id,
        followed_id=followed.id,
        org_id=org.id,
        permission_level=perm,
    )
    db.add(fr)
    db.flush()
    return fr


def _login(user: models.User) -> str:
    return auth_utils.create_access_token(user.id)


# ===========================================================================
# B1 — PUT upsert auto-precedence
# ===========================================================================

class TestUpsertCreatesPrecedenceRow:
    def test_new_topic_delegation_creates_precedence(self, api_db):
        alice = _user(api_db, "alice")
        bob = _user(api_db, "bob")
        org = _org(api_db, "o-b1a")
        topic = _topic(api_db, "Topic A", org)
        make_org_membership(api_db, org_id=org.id, user_id=alice.id, role="member", status="active")
        make_org_membership(api_db, org_id=org.id, user_id=bob.id, role="member", status="active")
        _follow(api_db, alice, bob, org)
        api_db.commit()

        client = _make_client(api_db)
        token = _login(alice)
        try:
            resp = client.put(
                f"/api/orgs/{org.slug}/delegations",
                json={
                    "delegate_id": bob.id,
                    "topic_id": topic.id,
                    "chain_behavior": "accept_sub",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200, resp.text
            prec = api_db.query(models.TopicPrecedence).filter(
                models.TopicPrecedence.user_id == alice.id,
                models.TopicPrecedence.topic_id == topic.id,
            ).first()
            assert prec is not None
            assert prec.priority == 0
        finally:
            app.dependency_overrides.pop(get_db, None)


class TestUpsertUpdateDoesNotChangePrecedence:
    def test_chain_behavior_update_leaves_priority_alone(self, api_db):
        alice = _user(api_db, "alice")
        bob = _user(api_db, "bob")
        carol = _user(api_db, "carol")
        org = _org(api_db, "o-b1b")
        topic = _topic(api_db, "Topic A", org)
        make_org_membership(api_db, org_id=org.id, user_id=alice.id, role="member", status="active")
        make_org_membership(api_db, org_id=org.id, user_id=bob.id, role="member", status="active")
        make_org_membership(api_db, org_id=org.id, user_id=carol.id, role="member", status="active")
        _follow(api_db, alice, bob, org)
        _follow(api_db, alice, carol, org)
        api_db.commit()

        client = _make_client(api_db)
        token = _login(alice)
        try:
            # Initial create — precedence row at 0.
            client.put(
                f"/api/orgs/{org.slug}/delegations",
                json={"delegate_id": bob.id, "topic_id": topic.id, "chain_behavior": "accept_sub"},
                headers={"Authorization": f"Bearer {token}"},
            )
            # Manually bump the precedence to priority 5 (simulating prior reorder).
            prec = api_db.query(models.TopicPrecedence).filter(
                models.TopicPrecedence.user_id == alice.id,
                models.TopicPrecedence.topic_id == topic.id,
            ).first()
            prec.priority = 5
            api_db.commit()

            # Update — change delegate. Precedence priority MUST stay at 5.
            resp = client.put(
                f"/api/orgs/{org.slug}/delegations",
                json={"delegate_id": carol.id, "topic_id": topic.id, "chain_behavior": "revert_direct"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200, resp.text
            api_db.refresh(prec)
            assert prec.priority == 5
            # Still exactly one row.
            count = api_db.query(models.TopicPrecedence).filter(
                models.TopicPrecedence.user_id == alice.id,
            ).count()
            assert count == 1
        finally:
            app.dependency_overrides.pop(get_db, None)


class TestUpsertGlobalDoesNotCreatePrecedence:
    def test_global_delegation_creates_no_precedence(self, api_db):
        alice = _user(api_db, "alice")
        bob = _user(api_db, "bob")
        org = _org(api_db, "o-b1c")
        make_org_membership(api_db, org_id=org.id, user_id=alice.id, role="member", status="active")
        make_org_membership(api_db, org_id=org.id, user_id=bob.id, role="member", status="active")
        _follow(api_db, alice, bob, org)
        api_db.commit()

        client = _make_client(api_db)
        token = _login(alice)
        try:
            resp = client.put(
                f"/api/orgs/{org.slug}/delegations",
                json={"delegate_id": bob.id, "topic_id": None, "chain_behavior": "accept_sub"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200, resp.text
            count = api_db.query(models.TopicPrecedence).filter(
                models.TopicPrecedence.user_id == alice.id,
            ).count()
            assert count == 0
        finally:
            app.dependency_overrides.pop(get_db, None)


# ===========================================================================
# B2 — revoke cleans up TopicPrecedence
# ===========================================================================

class TestRevokeDeletesPrecedenceRow:
    def test_revoke_topic_delegation_removes_precedence(self, api_db):
        alice = _user(api_db, "alice")
        bob = _user(api_db, "bob")
        org = _org(api_db, "o-b2a")
        topic = _topic(api_db, "Topic A", org)
        make_org_membership(api_db, org_id=org.id, user_id=alice.id, role="member", status="active")
        make_org_membership(api_db, org_id=org.id, user_id=bob.id, role="member", status="active")
        _follow(api_db, alice, bob, org)
        api_db.commit()

        client = _make_client(api_db)
        token = _login(alice)
        try:
            client.put(
                f"/api/orgs/{org.slug}/delegations",
                json={"delegate_id": bob.id, "topic_id": topic.id, "chain_behavior": "accept_sub"},
                headers={"Authorization": f"Bearer {token}"},
            )
            # Precedence row exists.
            assert api_db.query(models.TopicPrecedence).filter(
                models.TopicPrecedence.user_id == alice.id,
            ).count() == 1
            # Revoke.
            resp = client.delete(
                f"/api/orgs/{org.slug}/delegations/{topic.id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 204, resp.text
            # Precedence row gone.
            assert api_db.query(models.TopicPrecedence).filter(
                models.TopicPrecedence.user_id == alice.id,
            ).count() == 0
        finally:
            app.dependency_overrides.pop(get_db, None)


class TestRevokeGlobalIsNoOp:
    def test_revoke_global_does_not_break(self, api_db):
        alice = _user(api_db, "alice")
        bob = _user(api_db, "bob")
        org = _org(api_db, "o-b2b")
        topic = _topic(api_db, "Topic A", org)
        make_org_membership(api_db, org_id=org.id, user_id=alice.id, role="member", status="active")
        make_org_membership(api_db, org_id=org.id, user_id=bob.id, role="member", status="active")
        _follow(api_db, alice, bob, org)
        api_db.commit()

        client = _make_client(api_db)
        token = _login(alice)
        try:
            # Create a global delegation and a topic delegation.
            client.put(
                f"/api/orgs/{org.slug}/delegations",
                json={"delegate_id": bob.id, "topic_id": None, "chain_behavior": "accept_sub"},
                headers={"Authorization": f"Bearer {token}"},
            )
            client.put(
                f"/api/orgs/{org.slug}/delegations",
                json={"delegate_id": bob.id, "topic_id": topic.id, "chain_behavior": "accept_sub"},
                headers={"Authorization": f"Bearer {token}"},
            )
            # Should have 1 precedence row (from the topic delegation only).
            assert api_db.query(models.TopicPrecedence).filter(
                models.TopicPrecedence.user_id == alice.id,
            ).count() == 1

            # Revoke the global delegation. Precedence row should stay.
            resp = client.delete(
                f"/api/orgs/{org.slug}/delegations/global",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 204, resp.text
            assert api_db.query(models.TopicPrecedence).filter(
                models.TopicPrecedence.user_id == alice.id,
            ).count() == 1
        finally:
            app.dependency_overrides.pop(get_db, None)


# ===========================================================================
# B3 — backfill migration (Python-loop body, tested directly)
# ===========================================================================

def _run_backfill_inline(db: Session) -> None:
    """Inline copy of the migration body so the test exercises the same
    SQL/loop logic against the same SQLite engine. Mirrors
    migrations/versions/f3a8b25e90c7_phase_28_backfill_missing_topic_precedences.py."""
    from itertools import groupby
    bind = db.connection()

    missing_rows = bind.execute(text("""
        SELECT d.delegator_id, d.topic_id, d.created_at
        FROM delegations d
        WHERE d.topic_id IS NOT NULL
        AND NOT EXISTS (
            SELECT 1 FROM topic_precedences tp
            WHERE tp.user_id = d.delegator_id
            AND tp.topic_id = d.topic_id
        )
        ORDER BY d.delegator_id, d.created_at
    """)).fetchall()
    if not missing_rows:
        return

    for user_id, group in groupby(missing_rows, key=lambda r: r[0]):
        rows = list(group)
        max_prio = bind.execute(text(
            "SELECT COALESCE(MAX(priority), -1) FROM topic_precedences "
            "WHERE user_id = :uid"
        ), {"uid": user_id}).scalar()
        next_prio = (max_prio if max_prio is not None else -1) + 1
        for row in rows:
            bind.execute(text("""
                INSERT INTO topic_precedences (id, user_id, topic_id, priority)
                VALUES (:id, :uid, :tid, :prio)
            """), {
                "id": str(_uuid.uuid4()),
                "uid": user_id,
                "tid": row[1],
                "prio": next_prio,
            })
            next_prio += 1
    db.commit()


def _seed_legacy_delegation(
    db: Session,
    delegator: models.User,
    delegate: models.User,
    topic: models.Topic,
    org: models.Organization,
) -> models.Delegation:
    """Create a Delegation row WITHOUT the Phase 27 auto-precedence side
    effect — bypasses the route. Matches the legacy pre-Phase-27 shape
    that the backfill targets."""
    d = models.Delegation(
        delegator_id=delegator.id,
        delegate_id=delegate.id,
        org_id=org.id,
        topic_id=topic.id,
        chain_behavior="accept_sub",
    )
    db.add(d)
    db.flush()
    return d


class TestBackfillCreatesMissingPrecedences:
    def test_backfill_inserts_rows_for_legacy_delegations(self, api_db):
        alice = _user(api_db, "alice")
        bob = _user(api_db, "bob")
        org = _org(api_db, "o-b3a")
        t1 = _topic(api_db, "T1", org)
        t2 = _topic(api_db, "T2", org)
        _seed_legacy_delegation(api_db, alice, bob, t1, org)
        _seed_legacy_delegation(api_db, alice, bob, t2, org)
        api_db.commit()
        assert api_db.query(models.TopicPrecedence).count() == 0

        _run_backfill_inline(api_db)

        rows = api_db.query(models.TopicPrecedence).filter(
            models.TopicPrecedence.user_id == alice.id,
        ).order_by(models.TopicPrecedence.priority).all()
        assert len(rows) == 2
        assert rows[0].priority == 0
        assert rows[1].priority == 1
        topic_ids = {r.topic_id for r in rows}
        assert topic_ids == {t1.id, t2.id}


class TestBackfillIdempotent:
    def test_running_backfill_twice_doesnt_duplicate(self, api_db):
        alice = _user(api_db, "alice")
        bob = _user(api_db, "bob")
        org = _org(api_db, "o-b3b")
        t1 = _topic(api_db, "T1", org)
        _seed_legacy_delegation(api_db, alice, bob, t1, org)
        api_db.commit()

        _run_backfill_inline(api_db)
        _run_backfill_inline(api_db)

        count = api_db.query(models.TopicPrecedence).filter(
            models.TopicPrecedence.user_id == alice.id,
        ).count()
        assert count == 1


class TestBackfillPreservesExistingPriorities:
    def test_existing_precedence_unchanged_missing_inserted_at_max_plus_one(self, api_db):
        alice = _user(api_db, "alice")
        bob = _user(api_db, "bob")
        org = _org(api_db, "o-b3c")
        t1 = _topic(api_db, "T1", org)
        t2 = _topic(api_db, "T2", org)
        # Existing delegation + precedence at priority 5 for t1.
        _seed_legacy_delegation(api_db, alice, bob, t1, org)
        api_db.add(models.TopicPrecedence(
            user_id=alice.id, topic_id=t1.id, priority=5,
        ))
        # Legacy delegation on t2 with NO precedence row.
        _seed_legacy_delegation(api_db, alice, bob, t2, org)
        api_db.commit()

        _run_backfill_inline(api_db)

        t1_prec = api_db.query(models.TopicPrecedence).filter(
            models.TopicPrecedence.user_id == alice.id,
            models.TopicPrecedence.topic_id == t1.id,
        ).first()
        t2_prec = api_db.query(models.TopicPrecedence).filter(
            models.TopicPrecedence.user_id == alice.id,
            models.TopicPrecedence.topic_id == t2.id,
        ).first()
        assert t1_prec.priority == 5
        assert t2_prec.priority == 6


# ===========================================================================
# E2E integration
# ===========================================================================

class TestE2EBackfillThenReorder:
    def test_backfilled_user_can_reorder_via_put_precedence(self, api_db):
        alice = _user(api_db, "alice")
        bob = _user(api_db, "bob")
        org = _org(api_db, "o-e2e")
        t1 = _topic(api_db, "T1", org)
        t2 = _topic(api_db, "T2", org)
        t3 = _topic(api_db, "T3", org)
        make_org_membership(api_db, org_id=org.id, user_id=alice.id, role="member", status="active")
        make_org_membership(api_db, org_id=org.id, user_id=bob.id, role="member", status="active")
        _follow(api_db, alice, bob, org)
        _seed_legacy_delegation(api_db, alice, bob, t1, org)
        _seed_legacy_delegation(api_db, alice, bob, t2, org)
        _seed_legacy_delegation(api_db, alice, bob, t3, org)
        api_db.commit()

        _run_backfill_inline(api_db)
        # After backfill: t1, t2, t3 at priorities 0, 1, 2.
        api_db.expire_all()
        rows = api_db.query(models.TopicPrecedence).filter(
            models.TopicPrecedence.user_id == alice.id,
        ).order_by(models.TopicPrecedence.priority).all()
        assert [r.topic_id for r in rows] == [t1.id, t2.id, t3.id]

        # Now reorder via PUT /precedence: put t3 first, then t1, then t2.
        client = _make_client(api_db)
        token = _login(alice)
        try:
            resp = client.put(
                f"/api/orgs/{org.slug}/delegations/precedence",
                json={"ordered_topic_ids": [t3.id, t1.id, t2.id]},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200, resp.text
            api_db.expire_all()
            rows = api_db.query(models.TopicPrecedence).filter(
                models.TopicPrecedence.user_id == alice.id,
            ).order_by(models.TopicPrecedence.priority).all()
            assert [r.topic_id for r in rows] == [t3.id, t1.id, t2.id]
            assert [r.priority for r in rows] == [0, 1, 2]
        finally:
            app.dependency_overrides.pop(get_db, None)
