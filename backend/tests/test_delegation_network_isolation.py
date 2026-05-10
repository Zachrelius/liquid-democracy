"""Phase 10.2 W-FIX-A — /api/orgs/{slug}/delegations/network cross-user
isolation.

Per docs/test_depth_audit_2026-05.md (Class B, Delegation):
  * test_network_endpoint_returns_only_callers_ego_graph — two users with
    DISJOINT delegations; each caller sees only their own ego graph and
    NEVER the other user's nodes/edges.

Phase 18 update (D3): the endpoint moved from ``/api/delegations/network``
to ``/api/orgs/{org_slug}/delegations/network``. Delegations now carry
``org_id`` so the test sets up an org context, populates real
``OrgMembership`` rows so the route's ``require_org_membership``
dependency resolves, and constructs Delegation rows with ``org_id``.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from main import app
from role_seed import seed_default_roles_for_org
from tests.conftest import make_org_membership


_DUMMY_HASH = auth_utils.hash_password("demo1234")


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


def _make_user(db, username: str) -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=True,
    )
    db.add(u)
    db.flush()
    return u


def _make_org(db, slug: str) -> models.Organization:
    o = models.Organization(name=slug.title(), slug=slug, description="", settings={})
    db.add(o)
    db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _add_delegation(db, delegator, delegate, *, org_id):
    d = models.Delegation(
        delegator_id=delegator.id,
        delegate_id=delegate.id,
        org_id=org_id,
        topic_id=None,
        chain_behavior="accept_sub",
    )
    db.add(d)
    db.flush()
    return d


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def test_network_endpoint_returns_only_callers_ego_graph(client, test_db):
    """Phase 10.2 audit: Class B, GET /api/orgs/{slug}/delegations/network
    — third-party isolation guarantee. Two callers with disjoint
    delegation networks must each see only their own ego graph (within
    the same org).

    Phase 18 (D3): the URL is org-scoped now. The two callers + their
    delegation neighborhoods are placed in the SAME org so the
    isolation test exercises the user-isolation guarantee, not the
    org-isolation guarantee (that's tested separately in
    test_phase_18_delegation_org_scoping.py).
    """
    org = _make_org(test_db, "testorg")
    # Caller A and their delegations.
    a = _make_user(test_db, "alpha_caller")
    a_delegate = _make_user(test_db, "alpha_target")
    a_follower = _make_user(test_db, "alpha_follower")
    # Caller B and their delegations — completely disjoint.
    b = _make_user(test_db, "bravo_caller")
    b_delegate = _make_user(test_db, "bravo_target")
    b_follower = _make_user(test_db, "bravo_follower")
    for u in (a, a_delegate, a_follower, b, b_delegate, b_follower):
        make_org_membership(
            test_db, org_id=org.id, user_id=u.id, role="member",
        )
    _add_delegation(test_db, a, a_delegate, org_id=org.id)
    _add_delegation(test_db, a_follower, a, org_id=org.id)
    _add_delegation(test_db, b, b_delegate, org_id=org.id)
    _add_delegation(test_db, b_follower, b, org_id=org.id)
    test_db.commit()

    # A's view: should see a_delegate + a_follower; should NOT see b's
    # cluster.
    resp_a = client.get(
        f"/api/orgs/{org.slug}/delegations/network", headers=_auth(a),
    )
    assert resp_a.status_code == 200, resp_a.text
    a_ids = {n["id"] for n in resp_a.json()["nodes"]}
    assert a_delegate.id in a_ids
    assert a_follower.id in a_ids
    assert b.id not in a_ids
    assert b_delegate.id not in a_ids
    assert b_follower.id not in a_ids

    # B's view: symmetric.
    resp_b = client.get(
        f"/api/orgs/{org.slug}/delegations/network", headers=_auth(b),
    )
    assert resp_b.status_code == 200, resp_b.text
    b_ids = {n["id"] for n in resp_b.json()["nodes"]}
    assert b_delegate.id in b_ids
    assert b_follower.id in b_ids
    assert a.id not in b_ids
    assert a_delegate.id not in b_ids
    assert a_follower.id not in b_ids
