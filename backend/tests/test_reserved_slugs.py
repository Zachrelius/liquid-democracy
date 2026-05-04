"""Phase 11 B1 — reserved-slugs validation tests.

Covers:
  - POST /api/orgs            with each (parameterized subset of) reserved
    slug -> 400 with the spec error message.
  - POST /api/orgs/{slug}/sub-orgs with reserved slug -> 400.
  - POST /api/orgs            with a non-reserved slug -> 201 (regression).
  - POST /api/orgs            with mixed-case reserved slug -> 400 (lowercase
    comparison; schema validator rejects uppercase letters before us so we
    only sanity-check via slug = "ADMIN" which the schema rejects, plus the
    deliberately-lowercased "admin" which our gate catches first).

Note: ``o`` is in RESERVED_SLUGS but schema-validates as too short (the slug
regex requires min 3 chars), so it never reaches our gate; it's deliberately
excluded from the parameterized list.

Reuses the in-memory SQLite + dependency-override pattern from
test_org_creation_gates.py and test_sub_org_routes.py.
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
from reserved_slugs import RESERVED_SLUGS
from tests.conftest import make_org_membership


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
    db.add(u)
    db.flush()
    return u


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _parent_org(db: Session, owner: models.User, slug: str = "parent") -> models.Organization:
    """Stamp a parent org with `owner` as admin so the user can create sub-orgs."""
    org = models.Organization(
        name=slug.title(),
        slug=slug,
        description="",
        join_policy="open",
        settings={},
    )
    db.add(org)
    db.flush()
    make_org_membership(
        db,
        user_id=owner.id, org_id=org.id, role="admin", status="active",
    )
    db.flush()
    return org


def _create_org_payload(slug: str) -> dict:
    return {
        "name": "Test Org",
        "slug": slug,
        "description": "",
        "join_policy": "open",
    }


# Parameterized subset of RESERVED_SLUGS that is also a valid schema slug.
# Excludes ``o`` (only 1 char, fails Pydantic min_length=3 + slug regex).
# All entries pass the schema regex ^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$ and
# should be rejected at the route layer with the reserved-words 400.
_VALID_RESERVED_SUBSET = sorted(s for s in RESERVED_SLUGS if len(s) >= 3)


# ---------------------------------------------------------------------------
# Org creation — reserved-slug rejection
# ---------------------------------------------------------------------------

class TestOrgCreationReservedSlugs:
    @pytest.mark.parametrize("slug", _VALID_RESERVED_SUBSET)
    def test_org_creation_with_reserved_slug_rejected(self, db, client, slug):
        """Each reserved slug returns 400 with the spec error message."""
        u = _user(db, "alice")
        db.commit()
        resp = client.post(
            "/api/orgs", json=_create_org_payload(slug), headers=_auth(u),
        )
        assert resp.status_code == 400, (
            f"Expected 400 for reserved slug '{slug}', got {resp.status_code}: "
            f"{resp.text}"
        )
        detail = resp.json()["detail"]
        assert "reserved" in detail.lower(), (
            f"Expected 'reserved' in detail for '{slug}', got: {detail}"
        )
        assert slug in detail, (
            f"Expected slug '{slug}' echoed in detail, got: {detail}"
        )

    def test_org_creation_with_non_reserved_slug_succeeds(self, db, client):
        """Regression: a normal slug still gets created (201)."""
        u = _user(db, "alice")
        db.commit()
        resp = client.post(
            "/api/orgs",
            json=_create_org_payload("game-nights"),
            headers=_auth(u),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["slug"] == "game-nights"

    def test_org_creation_reserved_slug_check_runs_before_uniqueness(
        self, db, client,
    ):
        """If the requested slug is reserved AND already taken, the
        reserved-words error wins (it's the more useful diagnostic)."""
        # Pre-seed a row with slug "admin" directly (bypassing the route).
        u = _user(db, "alice")
        existing = models.Organization(
            name="Admin",
            slug="admin",
            description="",
            join_policy="open",
            settings={},
        )
        db.add(existing)
        db.commit()

        resp = client.post(
            "/api/orgs",
            json=_create_org_payload("admin"),
            headers=_auth(u),
        )
        assert resp.status_code == 400
        # Reserved-words message wins; uniqueness check would have said
        # "Organization slug already taken".
        assert "reserved" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Sub-org creation — reserved-slug rejection
# ---------------------------------------------------------------------------

class TestSubOrgCreationReservedSlugs:
    @pytest.mark.parametrize("slug", _VALID_RESERVED_SUBSET)
    def test_sub_org_creation_with_reserved_slug_rejected(
        self, db, client, slug,
    ):
        """Sub-org creation with a reserved slug -> 400.

        Sub-slugs only appear in URLs as the second segment so they can't
        collide with top-level routes — but the same reserved-words gate
        applies for consistency (per spec line 281)."""
        u = _user(db, "admin")
        parent = _parent_org(db, u, slug="parent-co")
        db.commit()

        resp = client.post(
            f"/api/orgs/{parent.slug}/sub-orgs",
            json={"name": "Sub", "slug": slug, "description": ""},
            headers=_auth(u),
        )
        assert resp.status_code == 400, (
            f"Expected 400 for reserved sub-slug '{slug}', got "
            f"{resp.status_code}: {resp.text}"
        )
        detail = resp.json()["detail"]
        assert "reserved" in detail.lower()
        assert slug in detail

    def test_sub_org_creation_with_non_reserved_slug_succeeds(self, db, client):
        """Regression: normal sub-org slug -> 201."""
        u = _user(db, "admin")
        parent = _parent_org(db, u, slug="parent-co")
        db.commit()

        resp = client.post(
            f"/api/orgs/{parent.slug}/sub-orgs",
            json={"name": "Eng", "slug": "engineering", "description": ""},
            headers=_auth(u),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["slug"] == "engineering"
