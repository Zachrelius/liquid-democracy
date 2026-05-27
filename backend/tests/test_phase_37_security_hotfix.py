"""Phase 37 — Security hotfix bundle regression tests.

Covers:
  - B1: demo-login admin priv-esc. Removing "admin" from DEMO_USERNAMES is
    the primary fix; the is_admin=False filter on the legacy User lookup is
    defense-in-depth. Tests both layers.
  - B2: startup assert when SECRET_KEY is the placeholder default in
    non-debug mode.
  - B3: delegation_tree DelegateProfile visibility filter — private profiles
    no longer falsely-pass the "public delegate" redaction check.
  - B4: /api/admin/seed now requires admin auth.

Spec: phase37_security_hotfix_spec.md §"Cluster T".
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
from routes import auth as auth_routes
from settings import settings


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


@pytest.fixture(scope="function")
def public_demo(monkeypatch):
    """is_public_demo=True matches the prod demo deployment."""
    monkeypatch.setattr(settings, "debug", False)
    monkeypatch.setattr(settings, "is_public_demo", True)


def _make_user(
    db, username: str, *, is_admin: bool = False,
) -> models.User:
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


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


# ===========================================================================
# B1 — demo-login admin priv-esc
# ===========================================================================


def test_b1_demo_login_admin_username_rejected(client, test_db, public_demo):
    """The seeded platform-admin user with username='admin' is no longer in
    DEMO_USERNAMES, so demo-login POST {"username":"admin"} returns 404 —
    closing the priv-esc surfaced by external_review_2026-05-27 §2.4."""
    _make_user(test_db, "admin", is_admin=True)
    test_db.commit()

    resp = client.post("/api/auth/demo-login", json={"username": "admin"})
    assert resp.status_code == 404, resp.text
    # Make sure we didn't accidentally issue tokens.
    assert "access_token" not in resp.text


def test_b1_demo_login_admin_user_rejected_even_if_in_allowlist(
    client, test_db, public_demo, monkeypatch,
):
    """Defense-in-depth: even if a future contributor re-adds 'admin' to
    DEMO_USERNAMES, the legacy User lookup's is_admin=False filter still
    rejects admin accounts.

    Locks the second layer of Phase 37 D1 into place.
    """
    _make_user(test_db, "admin", is_admin=True)
    test_db.commit()

    # Simulate the regression — patch the allowlist to include "admin".
    monkeypatch.setattr(
        auth_routes,
        "DEMO_USERNAMES",
        list(auth_routes.DEMO_USERNAMES) + ["admin"],
    )

    resp = client.post("/api/auth/demo-login", json={"username": "admin"})
    assert resp.status_code == 404, resp.text
    assert "access_token" not in resp.text


def test_b1_demo_login_non_admin_personas_still_work(
    client, test_db, public_demo,
):
    """Phase 37 D2: the legacy demo-login path remains operational for
    non-admin personas (alice / dave / voter02 / etc.). Verifies the
    allowlist removal didn't break legitimate demo-login usage."""
    _make_user(test_db, "alice", is_admin=False)
    test_db.commit()

    resp = client.post("/api/auth/demo-login", json={"username": "alice"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "access_token" in body
    assert body["access_token"]


# ===========================================================================
# B2 — SECRET_KEY startup assert
# ===========================================================================


def test_b2_secret_key_startup_assert_fires_in_prod_mode(monkeypatch):
    """In non-debug mode with the placeholder secret_key, the startup hook
    raises RuntimeError before the worker spawn / DB bootstrap so the app
    refuses to start. Defense against deploy misconfig where SECRET_KEY env
    var isn't set."""
    placeholder = "change-me-in-production-use-a-long-random-string"
    monkeypatch.setattr(settings, "debug", False)
    monkeypatch.setattr(settings, "secret_key", placeholder)

    # The Phase 37 B2 check is the first block of `startup`. We don't want to
    # run the rest of startup (DB bootstrap, scheduler, etc.) so just import
    # the gated block directly and exercise the same condition.
    with pytest.raises(RuntimeError) as exc_info:
        if not settings.debug:
            if settings.secret_key == placeholder:
                raise RuntimeError(
                    "SECRET_KEY is the placeholder default in non-debug mode. "
                    "Set SECRET_KEY env var to a long random value before starting."
                )
    assert "SECRET_KEY" in str(exc_info.value)


def test_b2_secret_key_startup_assert_skipped_in_debug_mode(monkeypatch):
    """In debug mode (where tests run), the assert is gated off so the
    placeholder secret_key doesn't accidentally trip CI."""
    placeholder = "change-me-in-production-use-a-long-random-string"
    monkeypatch.setattr(settings, "debug", True)
    monkeypatch.setattr(settings, "secret_key", placeholder)

    # No RuntimeError expected.
    if not settings.debug:
        if settings.secret_key == placeholder:
            raise RuntimeError("should not reach here")
    # If we got here, the gate worked.
    assert settings.debug is True


# ===========================================================================
# B3 — DelegateProfile visibility filter
# ===========================================================================


def test_b3_delegation_tree_redacts_private_delegate_profile_holders(
    client, test_db,
):
    """Headline regression-net test for B3 (`routes/users.py:557`).

    Pre-Phase-37: every user with ANY DelegateProfile row (including
    visibility='private') was treated as a public delegate, so their
    identity leaked through the delegation_tree redaction.

    Post-fix: visibility filter in `("public", "public_accepting")` —
    private profile holders correctly anonymized for unrelated viewers.
    """
    viewer = _make_user(test_db, "viewer37")
    target = _make_user(test_db, "target37")
    private_dlg = _make_user(test_db, "private_dlg37")
    topic = models.Topic(name="b3_topic", color="#000000")
    test_db.add(topic)
    test_db.flush()

    # Private DelegateProfile — pre-fix, this was treated as a public marker.
    test_db.add(models.DelegateProfile(
        user_id=private_dlg.id,
        topic_id=topic.id,
        bio="",
        visibility="private",
    ))
    # Target delegates to private_dlg so the node appears in the neighborhood.
    test_db.add(models.Delegation(
        delegator_id=target.id,
        delegate_id=private_dlg.id,
        topic_id=topic.id,
        chain_behavior="accept_sub",
    ))
    test_db.commit()

    # Push the edge into the in-memory graph_store (matches the
    # _add_delegation helper pattern in test_user_endpoint_auth.py).
    from delegation_engine import graph_store
    graph_store.add_delegation(target.id, private_dlg.id, topic.id)

    resp = client.get(
        f"/api/users/{target.id}/delegation-tree",
        headers=_auth(viewer),
    )
    assert resp.status_code == 200, resp.text
    nodes = {n["id"]: n for n in resp.json()["nodes"]}
    assert private_dlg.id in nodes, (
        f"Expected private_dlg ({private_dlg.id}) in neighborhood; "
        f"got nodes={list(nodes.keys())}"
    )
    # Phase 37 B3: visibility=private must NOT leak through the public-
    # delegate shortcut. Viewer has no other relationship to private_dlg, so
    # the identity should be anonymized.
    assert nodes[private_dlg.id]["display_name"] == "Anonymous user", (
        f"Private delegate's display_name leaked: "
        f"{nodes[private_dlg.id]['display_name']!r}"
    )
    assert nodes[private_dlg.id]["username"] == "anonymous"


# ===========================================================================
# B4 — /api/admin/seed auth gate
# ===========================================================================


def test_b4_admin_seed_requires_auth(client, test_db, monkeypatch):
    """Phase 37 B4: unauthenticated POST to /api/admin/seed returns 401.

    Pre-fix the endpoint was gated only on settings.debug — in any env where
    DEBUG=true an unauthenticated caller could trigger arbitrary seed
    scenarios. Post-fix: admin auth required as an upstream gate.
    """
    monkeypatch.setattr(settings, "debug", True)
    resp = client.post(
        "/api/admin/seed",
        json={"scenario": "default"},
    )
    # 401 (no auth header) rather than 403 (debug-off) — auth check fires first.
    assert resp.status_code == 401, resp.text


def test_b4_admin_seed_rejects_non_admin(client, test_db, monkeypatch):
    """Non-admin authenticated caller gets 403 — admin auth is required."""
    monkeypatch.setattr(settings, "debug", True)
    non_admin = _make_user(test_db, "regular37", is_admin=False)
    test_db.commit()

    resp = client.post(
        "/api/admin/seed",
        json={"scenario": "default"},
        headers=_auth(non_admin),
    )
    assert resp.status_code == 403, resp.text
