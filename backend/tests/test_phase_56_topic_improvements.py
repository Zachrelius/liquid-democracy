"""Phase 56 — topic system improvements: color validator + purpose +
category + org topic_guidance + topic_categories_enabled toggle.

Side-effect assertions per CLAUDE.md (we don't just check 200; we read
the persisted state back). Mirrors the integration-style pattern used
by test_phase_55_explore.py: in-memory SQLite + TestClient + real ORM
rows (no shims) so the route + schema + model paths are exercised
end-to-end.

Test families:
  * Color validator (5): RGB / RRGGBB / case-insensitive accepted;
    var() rejected (the bug regression guard); '#zzz' rejected (the old
    hand-rolled validator wrongly accepted this).
  * Purpose (3): persists + surfaces; over-length rejected;
    legacy-shape topic (purpose NULL) round-trips cleanly.
  * Category (2): persists + surfaces; toggle-off-retains category data.
  * Over-length category rejected by Pydantic.
  * Org settings (3): topic_guidance persists + surfaces; over-length
    rejected; topic_categories_enabled toggle persists + surfaces.
  * topic_guidance must be a string (type validation).
  * topic_categories_enabled must be a bool (type validation).
"""
from __future__ import annotations

from typing import Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from auth import hash_password
from database import Base, get_db
from main import app
from role_seed import seed_default_roles_for_org


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def db_session():
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
def client(db_session):
    def _get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth(user_id: str) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user_id)}"}


def _make_user(db: Session, username: str) -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=hash_password("x"),
        email=f"{username}@test.example",
        email_verified=True,
    )
    db.add(u)
    db.flush()
    return u


def _make_org_with_steward(
    db: Session, slug: str = "test-org",
) -> tuple[models.Organization, models.User]:
    """Create an org + a steward member who can hit topic + settings endpoints."""
    org = models.Organization(
        name=slug.title(), slug=slug, description="", join_policy="open",
        settings={},
    )
    db.add(org)
    db.flush()
    roles = seed_default_roles_for_org(db, org.id)
    steward = _make_user(db, f"{slug}_steward")
    db.add(models.OrgMembership(
        user_id=steward.id, org_id=org.id,
        role_id=roles["steward"].id, status="active",
    ))
    db.commit()
    return org, steward


# ===========================================================================
# Color validator (5)
# ===========================================================================


def test_color_validator_accepts_rrggbb(client, db_session):
    org, steward = _make_org_with_steward(db_session)
    r = client.post(
        f"/api/orgs/{org.slug}/topics",
        headers=_auth(steward.id),
        json={"name": "Topic A", "color": "#abcdef"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["color"] == "#abcdef"


def test_color_validator_accepts_rgb_short(client, db_session):
    org, steward = _make_org_with_steward(db_session)
    r = client.post(
        f"/api/orgs/{org.slug}/topics",
        headers=_auth(steward.id),
        json={"name": "Topic B", "color": "#abc"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["color"] == "#abc"


def test_color_validator_is_case_insensitive(client, db_session):
    org, steward = _make_org_with_steward(db_session)
    r = client.post(
        f"/api/orgs/{org.slug}/topics",
        headers=_auth(steward.id),
        json={"name": "Topic C", "color": "#AaBbCc"},
    )
    assert r.status_code == 201
    assert r.json()["color"] == "#AaBbCc"


def test_color_validator_rejects_var_string(client, db_session):
    """Regression guard for the Phase 56 bug: the FE was POSTing
    `var(--brand-primary)` from the two dropped preset swatches. The
    hand-rolled validator wrongly accepted them at the API layer too
    (`startswith('#')` was False so they 422'd, but no clear message);
    the converged regex now produces a clean rejection."""
    org, steward = _make_org_with_steward(db_session)
    r = client.post(
        f"/api/orgs/{org.slug}/topics",
        headers=_auth(steward.id),
        json={"name": "Topic D", "color": "var(--brand-primary)"},
    )
    assert r.status_code == 422
    body = r.json()
    detail_text = str(body)
    assert "#RRGGBB" in detail_text or "color" in detail_text.lower()


def test_color_validator_rejects_zzz_malformed(client, db_session):
    """The pre-Phase-56 hand-rolled validator wrongly accepted '#zzz' —
    it satisfied startswith('#') and length 4. The converged regex
    rejects it."""
    org, steward = _make_org_with_steward(db_session)
    r = client.post(
        f"/api/orgs/{org.slug}/topics",
        headers=_auth(steward.id),
        json={"name": "Topic E", "color": "#zzz"},
    )
    assert r.status_code == 422


# ===========================================================================
# Purpose (3)
# ===========================================================================


def test_purpose_persists_and_surfaces(client, db_session):
    org, steward = _make_org_with_steward(db_session)
    purpose = "Use this topic for budget-related proposals."
    r = client.post(
        f"/api/orgs/{org.slug}/topics",
        headers=_auth(steward.id),
        json={"name": "Budget", "color": "#abcdef", "purpose": purpose},
    )
    assert r.status_code == 201, r.text
    assert r.json()["purpose"] == purpose

    # Round-trip via the list endpoint to confirm purpose surfaces on
    # GET too (not just on the POST response).
    list_r = client.get(
        f"/api/orgs/{org.slug}/topics", headers=_auth(steward.id),
    )
    assert list_r.status_code == 200
    rows = list_r.json()
    assert len(rows) == 1
    assert rows[0]["purpose"] == purpose


def test_purpose_over_max_length_rejected(client, db_session):
    org, steward = _make_org_with_steward(db_session)
    r = client.post(
        f"/api/orgs/{org.slug}/topics",
        headers=_auth(steward.id),
        json={"name": "Big", "color": "#abcdef", "purpose": "x" * 501},
    )
    assert r.status_code == 422


def test_topic_without_purpose_surfaces_null(client, db_session):
    """No purpose on create → null on TopicOut. Graceful handling per
    spec B1 — what the FE relies on for the no-subtitle render."""
    org, steward = _make_org_with_steward(db_session)
    r = client.post(
        f"/api/orgs/{org.slug}/topics",
        headers=_auth(steward.id),
        json={"name": "Plain", "color": "#abcdef"},
    )
    assert r.status_code == 201
    assert r.json()["purpose"] is None
    assert r.json()["category"] is None


# ===========================================================================
# Category (2 + over-length)
# ===========================================================================


def test_category_persists_and_surfaces(client, db_session):
    org, steward = _make_org_with_steward(db_session)
    r = client.post(
        f"/api/orgs/{org.slug}/topics",
        headers=_auth(steward.id),
        json={
            "name": "Roads",
            "color": "#abcdef",
            "category": "Infrastructure",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["category"] == "Infrastructure"

    list_r = client.get(
        f"/api/orgs/{org.slug}/topics", headers=_auth(steward.id),
    )
    assert list_r.status_code == 200
    assert list_r.json()[0]["category"] == "Infrastructure"


def test_category_retained_when_toggle_disabled(client, db_session):
    """Spec D6: when `topic_categories_enabled` is False, grouping is
    hidden but category VALUES ARE RETAINED on the rows. Confirmed by:
    create topic with category → disable the toggle → category still
    present on the row (re-enabling restores grouping)."""
    org, steward = _make_org_with_steward(db_session)
    create_r = client.post(
        f"/api/orgs/{org.slug}/topics",
        headers=_auth(steward.id),
        json={
            "name": "Policy",
            "color": "#abcdef",
            "category": "Governance",
        },
    )
    assert create_r.status_code == 201
    topic_id = create_r.json()["id"]

    # Disable the toggle (it was never enabled; the test just confirms
    # the absence-of-deletion property by patching it OFF explicitly).
    toggle_off = client.patch(
        f"/api/orgs/{org.slug}",
        headers=_auth(steward.id),
        json={"settings": {"topic_categories_enabled": False}},
    )
    assert toggle_off.status_code == 200, toggle_off.text

    # Category value still on the topic row.
    list_r = client.get(
        f"/api/orgs/{org.slug}/topics", headers=_auth(steward.id),
    )
    rows = {t["id"]: t for t in list_r.json()}
    assert rows[topic_id]["category"] == "Governance", (
        "Disabling categories should NOT clear stored category values"
    )

    # Re-enable; still retained.
    toggle_on = client.patch(
        f"/api/orgs/{org.slug}",
        headers=_auth(steward.id),
        json={"settings": {"topic_categories_enabled": True}},
    )
    assert toggle_on.status_code == 200
    list_r2 = client.get(
        f"/api/orgs/{org.slug}/topics", headers=_auth(steward.id),
    )
    rows2 = {t["id"]: t for t in list_r2.json()}
    assert rows2[topic_id]["category"] == "Governance"


def test_category_over_max_length_rejected(client, db_session):
    org, steward = _make_org_with_steward(db_session)
    r = client.post(
        f"/api/orgs/{org.slug}/topics",
        headers=_auth(steward.id),
        json={"name": "Big", "color": "#abcdef", "category": "x" * 81},
    )
    assert r.status_code == 422


# ===========================================================================
# Topic purpose + category persist on PATCH too
# ===========================================================================


def test_purpose_and_category_persist_on_patch(client, db_session):
    org, steward = _make_org_with_steward(db_session)
    create_r = client.post(
        f"/api/orgs/{org.slug}/topics",
        headers=_auth(steward.id),
        json={"name": "Initial", "color": "#abcdef"},
    )
    assert create_r.status_code == 201
    topic_id = create_r.json()["id"]
    assert create_r.json()["purpose"] is None
    assert create_r.json()["category"] is None

    patch_r = client.patch(
        f"/api/orgs/{org.slug}/topics/{topic_id}",
        headers=_auth(steward.id),
        json={
            "name": "Initial",
            "color": "#abcdef",
            "purpose": "A clarifying note.",
            "category": "Misc",
        },
    )
    assert patch_r.status_code == 200, patch_r.text
    assert patch_r.json()["purpose"] == "A clarifying note."
    assert patch_r.json()["category"] == "Misc"


def test_purpose_and_category_clearable_on_patch(client, db_session):
    """PATCH with empty/None values clears the fields (sets NULL)."""
    org, steward = _make_org_with_steward(db_session)
    create_r = client.post(
        f"/api/orgs/{org.slug}/topics",
        headers=_auth(steward.id),
        json={
            "name": "WithExtras",
            "color": "#abcdef",
            "purpose": "to be cleared",
            "category": "to be cleared",
        },
    )
    topic_id = create_r.json()["id"]

    patch_r = client.patch(
        f"/api/orgs/{org.slug}/topics/{topic_id}",
        headers=_auth(steward.id),
        json={
            "name": "WithExtras", "color": "#abcdef",
            "purpose": "", "category": "",
        },
    )
    assert patch_r.status_code == 200
    assert patch_r.json()["purpose"] is None
    assert patch_r.json()["category"] is None


# ===========================================================================
# Org settings: topic_guidance + topic_categories_enabled (3 + 2 type checks)
# ===========================================================================


def test_topic_guidance_persists_and_surfaces(client, db_session):
    org, steward = _make_org_with_steward(db_session)
    guidance = (
        "# Topic conventions\n\n"
        "Use **broad** topics that group multiple proposals."
    )
    r = client.patch(
        f"/api/orgs/{org.slug}",
        headers=_auth(steward.id),
        json={"settings": {"topic_guidance": guidance}},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["settings"].get("topic_guidance") == guidance


def test_topic_categories_enabled_persists_and_surfaces(client, db_session):
    org, steward = _make_org_with_steward(db_session)
    r = client.patch(
        f"/api/orgs/{org.slug}",
        headers=_auth(steward.id),
        json={"settings": {"topic_categories_enabled": True}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["settings"]["topic_categories_enabled"] is True

    # Toggle back off.
    r2 = client.patch(
        f"/api/orgs/{org.slug}",
        headers=_auth(steward.id),
        json={"settings": {"topic_categories_enabled": False}},
    )
    assert r2.status_code == 200
    assert r2.json()["settings"]["topic_categories_enabled"] is False


def test_topic_guidance_over_max_length_rejected(client, db_session):
    org, steward = _make_org_with_steward(db_session)
    r = client.patch(
        f"/api/orgs/{org.slug}",
        headers=_auth(steward.id),
        json={"settings": {"topic_guidance": "x" * 5001}},
    )
    assert r.status_code == 400
    assert "5000" in r.text


def test_topic_guidance_wrong_type_rejected(client, db_session):
    org, steward = _make_org_with_steward(db_session)
    r = client.patch(
        f"/api/orgs/{org.slug}",
        headers=_auth(steward.id),
        json={"settings": {"topic_guidance": 12345}},
    )
    assert r.status_code == 400
    assert "string" in r.text.lower()


def test_topic_categories_enabled_wrong_type_rejected(client, db_session):
    org, steward = _make_org_with_steward(db_session)
    r = client.patch(
        f"/api/orgs/{org.slug}",
        headers=_auth(steward.id),
        json={"settings": {"topic_categories_enabled": "yes"}},
    )
    assert r.status_code == 400
    assert "bool" in r.text.lower()


# ===========================================================================
# Bonus: empty-string purpose normalizes to NULL (not "" literal)
# ===========================================================================


def test_empty_purpose_string_normalizes_to_null(client, db_session):
    """The route handler treats empty strings as NULL so the row is
    clean. This keeps the FE's `t.purpose &&` truthy-check correct
    (no need to also check for empty literals)."""
    org, steward = _make_org_with_steward(db_session)
    r = client.post(
        f"/api/orgs/{org.slug}/topics",
        headers=_auth(steward.id),
        json={"name": "Empty", "color": "#abcdef", "purpose": ""},
    )
    assert r.status_code == 201
    assert r.json()["purpose"] is None
