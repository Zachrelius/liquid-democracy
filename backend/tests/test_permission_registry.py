"""Phase 12 Stage 1 — Permission registry tests (Cluster H, H3 + H4).

Exercises the static module data in ``backend/permission_registry.py``
plus the read-only ``GET /api/permissions/registry`` endpoint.

Coverage:
  * Registry shape: 23 entries, 9 categories, no key collisions.
  * DEFAULT_GRANTS counts per role match the spec (steward=23, admin=23,
    moderator=8, member=0).
  * Every key referenced in DEFAULT_GRANTS exists in the registry
    (catches typos in the seed table).
  * Endpoint returns 200 for an authenticated user with the correct
    payload shape; 401 when no auth token is presented.
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
from permission_registry import (
    ALL_PERMISSION_KEYS,
    CATEGORIES,
    DEFAULT_GRANTS,
    PERMISSION_REGISTRY,
)


_DUMMY_HASH = auth_utils.hash_password("demo1234")


# ---------------------------------------------------------------------------
# Module-level data tests (no DB required)
# ---------------------------------------------------------------------------

def test_registry_has_23_entries():
    """Per spec §'Permission registry' — 4+3+5+3+1+2+1+2+2 = 23 keys."""
    assert len(PERMISSION_REGISTRY) == 23


def test_registry_keys_are_unique():
    """No two permission entries share a key — uniqueness is load-bearing
    for DEFAULT_GRANTS lookups and the role_permissions UniqueConstraint."""
    keys = [p.key for p in PERMISSION_REGISTRY]
    assert len(set(keys)) == len(keys)


def test_registry_uses_nine_canonical_categories():
    """Per spec — categories drive Stage 2's matrix UI grouping. Nine
    categories: Proposals, Topics, Members, Sub-organizations, Delegate
    applications, Polis (deliberation), Comments, Organization, Audit
    and analytics."""
    assert len(CATEGORIES) == 9
    seen_categories = {p.category for p in PERMISSION_REGISTRY}
    assert seen_categories == set(CATEGORIES)


def test_registry_per_category_counts_match_spec():
    """Per spec table totals: 4+3+5+3+1+2+1+2+2 = 23."""
    expected = {
        "Proposals": 4,
        "Topics": 3,
        "Members": 5,
        "Sub-organizations": 3,
        "Delegate applications": 1,
        "Polis (deliberation)": 2,
        "Comments": 1,
        "Organization": 2,
        "Audit and analytics": 2,
    }
    actual: dict[str, int] = {}
    for p in PERMISSION_REGISTRY:
        actual[p.category] = actual.get(p.category, 0) + 1
    assert actual == expected


# ---------------------------------------------------------------------------
# DEFAULT_GRANTS counts
# ---------------------------------------------------------------------------

def test_default_grants_steward_gets_all_23():
    """Steward holds every permission by default — they're the org owner
    and Stage 1 doesn't restrict them in any UI-configurable way."""
    assert len(DEFAULT_GRANTS["steward"]) == 23
    assert DEFAULT_GRANTS["steward"] == ALL_PERMISSION_KEYS


def test_default_grants_admin_gets_all_23():
    """Admin appears in every Default: line in the spec table — admins
    get the full 23 permissions on a freshly-seeded org. Stage 2's UI
    is what permits orgs to scope this back."""
    assert len(DEFAULT_GRANTS["admin"]) == 23
    assert DEFAULT_GRANTS["admin"] == ALL_PERMISSION_KEYS


def test_default_grants_moderator_gets_8():
    """Per spec — moderators get the eight 'moderator, admin, steward'
    rows. Counted by hand from spec lines 105-144."""
    assert len(DEFAULT_GRANTS["moderator"]) == 8
    expected = {
        "proposal.create",
        "proposal.advance_phase",
        "topic.create",
        "topic.edit",
        "member.approve_join",
        "member.invite",
        "polis.create",
        "comment.moderate",
    }
    assert DEFAULT_GRANTS["moderator"] == expected


def test_default_grants_member_gets_zero():
    """Per spec — members hold no admin-tier permissions. Voting,
    delegating, posting comments, etc. are gated by membership status,
    not by entries in role_permissions."""
    assert DEFAULT_GRANTS["member"] == set()


def test_default_grants_keys_all_exist_in_registry():
    """Catches typos in DEFAULT_GRANTS — every key it references must
    be a known permission key from the registry."""
    for role, keys in DEFAULT_GRANTS.items():
        for key in keys:
            assert key in ALL_PERMISSION_KEYS, (
                f"DEFAULT_GRANTS[{role!r}] references unknown key {key!r}"
            )


def test_default_grants_covers_all_four_preset_roles():
    """The seed helper iterates DEFAULT_GRANTS to populate role_permissions
    for the four preset roles. Missing a role would silently leave it
    with zero rows."""
    assert set(DEFAULT_GRANTS.keys()) == {"steward", "admin", "moderator", "member"}


# ---------------------------------------------------------------------------
# Endpoint tests
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


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def test_get_registry_returns_200_for_authenticated_user(client, test_db):
    """Any authenticated user can read the registry — it's metadata."""
    user = _make_user(test_db, "alice")
    test_db.commit()

    resp = client.get("/api/permissions/registry", headers=_auth(user))
    assert resp.status_code == 200, resp.text


def test_get_registry_returns_23_entries_with_correct_shape(client, test_db):
    """Endpoint returns the full 23-entry list with key/label/description/
    category on every row."""
    user = _make_user(test_db, "bob")
    test_db.commit()

    resp = client.get("/api/permissions/registry", headers=_auth(user))
    body = resp.json()

    assert "permissions" in body
    assert "categories" in body
    assert len(body["permissions"]) == 23
    for entry in body["permissions"]:
        assert set(entry.keys()) == {"key", "label", "description", "category"}
        assert isinstance(entry["key"], str) and entry["key"]
        assert isinstance(entry["label"], str) and entry["label"]
        assert isinstance(entry["description"], str) and entry["description"]
        assert entry["category"] in CATEGORIES


def test_get_registry_returns_nine_categories(client, test_db):
    """Endpoint returns the canonical CATEGORIES list — Stage 2 uses this
    to render the matrix UI's row groups in a stable order."""
    user = _make_user(test_db, "carol")
    test_db.commit()

    resp = client.get("/api/permissions/registry", headers=_auth(user))
    body = resp.json()

    assert body["categories"] == list(CATEGORIES)
    assert len(body["categories"]) == 9


def test_get_registry_includes_known_keys(client, test_db):
    """Spot-check a representative key from each category appears in
    the response — guards against accidental key removal during refactor."""
    user = _make_user(test_db, "dave")
    test_db.commit()

    resp = client.get("/api/permissions/registry", headers=_auth(user))
    keys = {p["key"] for p in resp.json()["permissions"]}

    # One representative key per category.
    expected_subset = {
        "proposal.create",
        "topic.create",
        "member.approve_join",
        "sub_org.create",
        "delegate_application.approve",
        "polis.create",
        "comment.moderate",
        "org.edit_settings",
        "audit.view_org",
    }
    assert expected_subset.issubset(keys)


def test_get_registry_unauthenticated_returns_401(client):
    """No bearer token — endpoint requires auth, even though it's
    metadata. Anonymous reads are not permitted."""
    resp = client.get("/api/permissions/registry")
    assert resp.status_code == 401, resp.text
