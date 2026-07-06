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

def test_registry_has_26_entries():
    """Stage 1 shipped 23 keys; Stage 2 + Phase 12.5 + Phase 16 + Phase
    32.2 + Phase 47 brought it to 28; Phase 68b adds `proposal.archive`
    (29); Phase 77 adds `org_inbox.view` (30); Phase 88 adds
    `member.set_voting_weight` (31). Per-category breakdown:
    8+3+6+3+1+2+1+4+2+1 = 31."""
    assert len(PERMISSION_REGISTRY) == 31


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
    assert len(CATEGORIES) == 10
    seen_categories = {p.category for p in PERMISSION_REGISTRY}
    assert seen_categories == set(CATEGORIES)


def test_registry_per_category_counts_match_spec():
    """Per spec table totals + Stage 2 + Phase 12.5 + Phase 16 + Phase 32.2
    + Phase 47 + Phase 68b additions: 8+3+5+3+1+2+1+4+2 = 29. Phase 68b
    adds `proposal.archive` to the Proposals category, bumping that
    category from 7 to 8."""
    expected = {
        "Proposals": 8,
        "Topics": 3,
        # Phase 88 — added member.set_voting_weight (now 6 = the existing 5 +
        # member.set_voting_weight).
        "Members": 6,
        "Sub-organizations": 3,
        "Delegate applications": 1,
        "Polis (deliberation)": 2,
        "Comments": 1,
        # Phase 47 — added title.manage to Organization (now 4 = the
        # existing 3 + title.manage).
        "Organization": 4,
        "Audit and analytics": 2,
        # Phase 77 — Messages category (org_inbox.view).
        "Messages": 1,
    }
    actual: dict[str, int] = {}
    for p in PERMISSION_REGISTRY:
        actual[p.category] = actual.get(p.category, 0) + 1
    assert actual == expected


def test_proposal_delete_key_is_present_and_honestly_labeled():
    """Phase 72b (Section B-keep) — `proposal.delete` is a registered-but-
    vestigial key: the only proposal-deletion route is draft-only and gates
    on author / org.edit_proposal / platform-admin, never reading this key.
    We keep the key (removing it is a prod role_permissions data-migration
    for zero user-facing gain) but its description must NOT overpromise. The
    Phase 71c relabel made it honest; assert that here so a future edit can't
    silently re-introduce the overpromise, and confirm keeping it didn't
    change the registry count."""
    by_key = {p.key: p for p in PERMISSION_REGISTRY}
    assert "proposal.delete" in by_key
    desc = by_key["proposal.delete"].description.lower()
    # The description must disclose that the key currently does nothing.
    assert "no effect" in desc
    # And must NOT claim it actually gates deletion.
    assert "allow deleting" not in desc
    # Keeping (not removing) the key leaves the count at 31.
    assert len(PERMISSION_REGISTRY) == 31


# ---------------------------------------------------------------------------
# DEFAULT_GRANTS counts
# ---------------------------------------------------------------------------

def test_default_grants_steward_gets_all_26():
    """Phase 16 — steward holds every permission by default, including
    `role_permissions.edit` (Stage 2 meta), `proposal.set_thresholds`
    (Phase 12.5), and `proposal.set_durations` (Phase 16). The Steward
    column also has three lockout-protected cells per Stage 2 spec Q1,
    but those still appear in DEFAULT_GRANTS as TRUE — they're enforced
    as-locked at the PATCH endpoint, not via DEFAULT_GRANTS."""
    assert len(DEFAULT_GRANTS["steward"]) == 31
    assert DEFAULT_GRANTS["steward"] == ALL_PERMISSION_KEYS


def test_default_grants_admin_gets_all_26():
    """Phase 16 — admins also default to the full 26-key set, including
    `role_permissions.edit`, `proposal.set_thresholds`, and
    `proposal.set_durations`. The matrix UI is what permits orgs to scope
    these back if they want stricter Admin scopes."""
    assert len(DEFAULT_GRANTS["admin"]) == 31
    assert DEFAULT_GRANTS["admin"] == ALL_PERMISSION_KEYS


def test_default_grants_moderator_gets_11():
    """Phase 71a — moderators get the original logistics set PLUS
    `member.suspend` and `polis.manage`. These are NOT new powers: under
    the pre-71 coarse-tier gates a moderator could already suspend members
    and manage org-wide polises. Phase 71 makes the per-org config
    authoritative for those routes, so the starter config must seed them
    TRUE to keep current behavior (orgs can now revoke them and have it
    actually enforced). `proposal.set_durations` (Phase 16) stays granted;
    `proposal.set_thresholds` stays reserved for Steward/Admin."""
    assert len(DEFAULT_GRANTS["moderator"]) == 11
    expected = {
        "proposal.create",
        "proposal.advance_phase",
        "topic.create",
        "topic.edit",
        "member.approve_join",
        "member.invite",
        "polis.create",
        "comment.moderate",
        "proposal.set_durations",
        # Phase 71a additions (config-authoritative starter values).
        "member.suspend",
        "polis.manage",
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


def test_get_registry_returns_26_entries_with_correct_shape(client, test_db):
    """Phase 16 — endpoint returns the full 26-entry list (12.5's 25
    plus `proposal.set_durations`) with key/label/description/category on
    every row."""
    user = _make_user(test_db, "bob")
    test_db.commit()

    resp = client.get("/api/permissions/registry", headers=_auth(user))
    body = resp.json()

    assert "permissions" in body
    assert "categories" in body
    assert len(body["permissions"]) == 31
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
    assert len(body["categories"]) == 10


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
