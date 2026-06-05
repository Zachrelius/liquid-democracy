"""Phase 55 — public org discovery (/api/orgs/explore) test coverage.

Spec: ``phase55_public_org_discovery_spec_2026-06-05.md`` §B3.

Asserts SIDE EFFECTS / actual response content (per CLAUDE.md testing
strategy) — not just 200. Covers four categories:

  * Filtering (8 tests): the three public join policies appear,
    invite_only_secret is hidden, demo orgs are hidden, sub-orgs are
    hidden, anon + authed callers get identical results.
  * Search (5 tests): name substring, description substring, no-match
    exclusion, empty query returns all, case-insensitive.
  * Sort (3 tests): members ordering, activity ordering with
    zero-proposal orgs last, default == activity.
  * Projection safety (2 tests): response card omits settings /
    user_permissions / governance_mode; member_count equals active
    membership count and excludes pending/inactive memberships.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
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


def _make_org(
    db: Session,
    slug: str,
    *,
    name: Optional[str] = None,
    description: str = "",
    join_policy: str = "open",
    parent_org_id: Optional[str] = None,
    is_demo: bool = False,
    governance_type: Optional[str] = None,
    settings: Optional[dict] = None,
) -> models.Organization:
    o = models.Organization(
        name=name or slug.replace("-", " ").title(),
        slug=slug,
        description=description,
        join_policy=join_policy,
        parent_org_id=parent_org_id,
        is_demo=is_demo,
        governance_type=governance_type,
        settings=settings or {},
    )
    db.add(o)
    db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _add_member(
    db: Session,
    org: models.Organization,
    user: models.User,
    *,
    role_key: str = "member",
    status: str = "active",
) -> models.OrgMembership:
    role = (
        db.query(models.Role)
        .filter_by(org_id=org.id, system_key=role_key)
        .first()
    )
    m = models.OrgMembership(
        user_id=user.id,
        org_id=org.id,
        role_id=role.id,
        status=status,
    )
    db.add(m)
    db.flush()
    return m


def _add_proposal(
    db: Session,
    org: models.Organization,
    author: models.User,
    *,
    created_at: Optional[datetime] = None,
    title: str = "P",
) -> models.Proposal:
    p = models.Proposal(
        title=title,
        body="",
        author_id=author.id,
        voting_method="binary",
        status="voting",
        org_id=org.id,
    )
    if created_at is not None:
        # SQLite Vote/Proposal tables store naive UTC; align here.
        p.created_at = created_at.replace(tzinfo=None) if created_at.tzinfo else created_at
    db.add(p)
    db.flush()
    return p


def _slugs(payload: dict) -> set[str]:
    return {card["slug"] for card in payload["orgs"]}


# ===========================================================================
# Cluster 1: Filtering
# ===========================================================================


def test_open_org_appears(client, db_session):
    """Spec B3 #1: open-policy org appears in /explore results."""
    _make_org(db_session, "open-org", join_policy="open")
    db_session.commit()

    r = client.get("/api/orgs/explore")
    assert r.status_code == 200
    assert "open-org" in _slugs(r.json())


def test_approval_required_org_appears(client, db_session):
    """Spec B3 #2: approval_required org appears."""
    _make_org(db_session, "approval-org", join_policy="approval_required")
    db_session.commit()

    r = client.get("/api/orgs/explore")
    assert r.status_code == 200
    assert "approval-org" in _slugs(r.json())


def test_invite_only_public_org_appears(client, db_session):
    """Spec B3 #3: invite_only_public org appears (opted into public
    visibility; the splash explains the invite requirement)."""
    _make_org(db_session, "iop-org", join_policy="invite_only_public")
    db_session.commit()

    r = client.get("/api/orgs/explore")
    assert r.status_code == 200
    assert "iop-org" in _slugs(r.json())


def test_invite_only_secret_org_absent(client, db_session):
    """Spec B3 #4: invite_only_secret org is NOT listed — mirrors
    Phase 14's 404-for-secret posture."""
    _make_org(db_session, "secret-org", join_policy="invite_only_secret")
    _make_org(db_session, "visible-org", join_policy="open")
    db_session.commit()

    r = client.get("/api/orgs/explore")
    payload = r.json()
    slugs = _slugs(payload)
    assert "secret-org" not in slugs
    assert "visible-org" in slugs


def test_demo_org_absent(client, db_session):
    """Spec B3 #5: is_demo=True org does NOT appear on /explore (demo
    orgs live at /demo)."""
    _make_org(
        db_session, "demo-foo", join_policy="open", is_demo=True,
    )
    _make_org(db_session, "real-foo", join_policy="open")
    db_session.commit()

    r = client.get("/api/orgs/explore")
    slugs = _slugs(r.json())
    assert "demo-foo" not in slugs
    assert "real-foo" in slugs


def test_sub_org_absent(client, db_session):
    """Spec B3 #6: a sub-org (parent_org_id IS NOT NULL) is hidden
    even if its join_policy is open."""
    parent = _make_org(db_session, "parent-org", join_policy="open")
    _make_org(
        db_session, "child-org",
        join_policy="open", parent_org_id=parent.id,
    )
    db_session.commit()

    r = client.get("/api/orgs/explore")
    slugs = _slugs(r.json())
    assert "parent-org" in slugs
    assert "child-org" not in slugs


def test_anonymous_caller_gets_200_with_results(client, db_session):
    """Spec B3 #7: anonymous (no auth header) caller gets 200 with
    the discoverable set."""
    _make_org(db_session, "open-org", join_policy="open")
    db_session.commit()

    # No Authorization header at all.
    r = client.get("/api/orgs/explore")
    assert r.status_code == 200
    assert r.json()["count"] >= 1
    assert "open-org" in _slugs(r.json())


def test_authed_caller_sees_same_result_set(client, db_session):
    """Spec B3 #8: logged-in caller gets the identical result set
    (the endpoint is auth-agnostic — same response either way)."""
    user = _make_user(db_session, "alice")
    _make_org(db_session, "open-org", join_policy="open")
    _make_org(db_session, "iop-org", join_policy="invite_only_public")
    db_session.commit()

    r_anon = client.get("/api/orgs/explore")
    r_auth = client.get("/api/orgs/explore", headers=_auth(user.id))
    assert r_anon.status_code == r_auth.status_code == 200
    assert _slugs(r_anon.json()) == _slugs(r_auth.json())
    assert r_anon.json()["count"] == r_auth.json()["count"]


# ===========================================================================
# Cluster 2: Search
# ===========================================================================


def test_search_matches_name_substring(client, db_session):
    """Spec B3 #9: q matching a substring of name includes the org."""
    _make_org(
        db_session, "reform-table",
        name="The Reform Table", description="A space for civic debate.",
    )
    _make_org(db_session, "other-org", name="Hobby Polling",
              description="Low-stakes polls.")
    db_session.commit()

    r = client.get("/api/orgs/explore", params={"q": "reform"})
    slugs = _slugs(r.json())
    assert "reform-table" in slugs
    assert "other-org" not in slugs


def test_search_matches_description_substring(client, db_session):
    """Spec B3 #10: q matching a substring of description includes
    the org (even when the name doesn't match)."""
    _make_org(
        db_session, "alpha",
        name="Alpha", description="Civic deliberation org for tax policy.",
    )
    _make_org(db_session, "beta", name="Beta", description="Hobby polls only.")
    db_session.commit()

    r = client.get("/api/orgs/explore", params={"q": "tax policy"})
    slugs = _slugs(r.json())
    assert "alpha" in slugs
    assert "beta" not in slugs


def test_search_no_match_excludes_org(client, db_session):
    """Spec B3 #11: q matching neither name nor description excludes
    the org (returns empty result set when nothing matches)."""
    _make_org(db_session, "alpha", name="Alpha", description="One.")
    _make_org(db_session, "beta", name="Beta", description="Two.")
    db_session.commit()

    r = client.get("/api/orgs/explore", params={"q": "zzzzzzz-no-match"})
    assert r.status_code == 200
    payload = r.json()
    assert payload["count"] == 0
    assert payload["orgs"] == []


def test_empty_q_returns_full_set(client, db_session):
    """Spec B3 #12: empty/absent q returns the full discoverable set."""
    _make_org(db_session, "alpha", join_policy="open")
    _make_org(db_session, "beta", join_policy="approval_required")
    _make_org(
        db_session, "gamma-secret", join_policy="invite_only_secret",
    )
    db_session.commit()

    r_no_param = client.get("/api/orgs/explore")
    r_empty = client.get("/api/orgs/explore", params={"q": ""})
    # Both behave the same: full discoverable set, secret excluded.
    for r in (r_no_param, r_empty):
        slugs = _slugs(r.json())
        assert slugs == {"alpha", "beta"}
        assert r.json()["count"] == 2


def test_search_is_case_insensitive(client, db_session):
    """Spec B3 #13: search treats query as case-insensitive."""
    _make_org(
        db_session, "reform-table",
        name="The Reform Table", description="Civic stuff.",
    )
    db_session.commit()

    # Mixed-case and upper-case both match.
    for q in ["REFORM", "Reform", "reform", "ReFoRm"]:
        r = client.get("/api/orgs/explore", params={"q": q})
        assert "reform-table" in _slugs(r.json()), f"failed for q={q!r}"


# ===========================================================================
# Cluster 3: Sort
# ===========================================================================


def test_sort_members_orders_by_descending_member_count(client, db_session):
    """Spec B3 #14: sort=members orders DESC by member_count.

    Builds three orgs with distinct active member counts and asserts
    the response ordering matches the descending count.
    """
    a = _make_org(db_session, "small", join_policy="open")
    b = _make_org(db_session, "medium", join_policy="open")
    c = _make_org(db_session, "large", join_policy="open")

    # 1 / 3 / 5 active members respectively.
    for i in range(1):
        _add_member(db_session, a, _make_user(db_session, f"a_user_{i}"))
    for i in range(3):
        _add_member(db_session, b, _make_user(db_session, f"b_user_{i}"))
    for i in range(5):
        _add_member(db_session, c, _make_user(db_session, f"c_user_{i}"))
    db_session.commit()

    r = client.get("/api/orgs/explore", params={"sort": "members"})
    ordered = [card["slug"] for card in r.json()["orgs"]]
    assert ordered == ["large", "medium", "small"]
    # Counts surface correctly too.
    counts = {card["slug"]: card["member_count"] for card in r.json()["orgs"]}
    assert counts == {"small": 1, "medium": 3, "large": 5}


def test_sort_activity_orders_by_recency_with_zero_proposal_orgs_last(
    client, db_session,
):
    """Spec B3 #15: sort=activity orders DESC by most-recent-proposal
    created_at; orgs with zero proposals sort last."""
    older = _make_org(db_session, "older", join_policy="open")
    newer = _make_org(db_session, "newer", join_policy="open")
    silent = _make_org(db_session, "silent", join_policy="open")

    author = _make_user(db_session, "author")
    _add_member(db_session, older, author)
    _add_member(db_session, newer, author)
    _add_member(db_session, silent, author)

    base = datetime(2026, 1, 1, 12, 0, 0)
    _add_proposal(db_session, older, author, created_at=base)
    _add_proposal(
        db_session, newer, author, created_at=base + timedelta(days=10),
    )
    # `silent` has no proposal at all.
    db_session.commit()

    r = client.get("/api/orgs/explore", params={"sort": "activity"})
    ordered = [card["slug"] for card in r.json()["orgs"]]
    assert ordered == ["newer", "older", "silent"]


def test_default_sort_is_activity(client, db_session):
    """Spec B3 #16: omitted sort param == sort=activity."""
    older = _make_org(db_session, "older", join_policy="open")
    newer = _make_org(db_session, "newer", join_policy="open")
    author = _make_user(db_session, "author")
    _add_member(db_session, older, author)
    _add_member(db_session, newer, author)

    base = datetime(2026, 1, 1, 12, 0, 0)
    _add_proposal(db_session, older, author, created_at=base)
    _add_proposal(
        db_session, newer, author, created_at=base + timedelta(days=5),
    )
    db_session.commit()

    r_default = client.get("/api/orgs/explore")
    r_explicit = client.get("/api/orgs/explore", params={"sort": "activity"})
    assert (
        [c["slug"] for c in r_default.json()["orgs"]]
        == [c["slug"] for c in r_explicit.json()["orgs"]]
        == ["newer", "older"]
    )


# ===========================================================================
# Cluster 4: Projection safety
# ===========================================================================


_FORBIDDEN_KEYS = {
    "settings",
    "user_permissions",
    "governance_mode",
    "id",
    "user_role",
    "created_at",
    "parent_org_id",
}


def test_response_card_omits_internal_fields(client, db_session):
    """Spec B3 #17: explore cards must NOT include internal fields
    (settings, user_permissions, governance_mode, etc.). This is the
    public-safety guard — the endpoint is unauthenticated and the
    projection is deliberately minimal."""
    _make_org(
        db_session, "alpha", join_policy="open",
        settings={"branding": {"primary_color": "#1B3A5C"}},
    )
    db_session.commit()

    r = client.get("/api/orgs/explore")
    cards = r.json()["orgs"]
    assert len(cards) == 1
    card = cards[0]
    leaked = _FORBIDDEN_KEYS & card.keys()
    assert not leaked, f"explore card leaked internal fields: {leaked}"

    expected = {
        "slug", "name", "description", "governance_type",
        "join_policy", "member_count", "logo_url", "branding",
    }
    assert set(card.keys()) == expected


def test_member_count_excludes_pending_and_inactive(client, db_session):
    """Spec B3 #18: card.member_count equals the active-membership
    count — pending and inactive memberships are excluded."""
    org = _make_org(db_session, "alpha", join_policy="approval_required")
    active_a = _make_user(db_session, "active_a")
    active_b = _make_user(db_session, "active_b")
    pending_u = _make_user(db_session, "pending_u")
    inactive_u = _make_user(db_session, "inactive_u")

    _add_member(db_session, org, active_a, status="active")
    _add_member(db_session, org, active_b, status="active")
    _add_member(db_session, org, pending_u, status="pending_approval")
    _add_member(db_session, org, inactive_u, status="inactive")
    db_session.commit()

    r = client.get("/api/orgs/explore")
    cards = r.json()["orgs"]
    assert len(cards) == 1
    assert cards[0]["member_count"] == 2


# ===========================================================================
# Bonus: branding + governance_type surface correctly on the card
# ===========================================================================


def test_card_surfaces_branding_and_governance_type(client, db_session):
    """Branding (primary/accent color + logo_url) and governance_type
    surface on the card so the FE can render the visual treatment.
    Branding reads from settings.branding directly (no parent walk
    needed — /explore is top-level orgs only)."""
    _make_org(
        db_session, "branded-org",
        join_policy="open",
        governance_type="Civic Advocacy Group",
        settings={
            "branding": {
                "primary_color": "#1B3A5C",
                "accent_color": "#2E75B6",
                "logo_url": "/uploads/logos/branded/large.png",
            },
        },
    )
    db_session.commit()

    r = client.get("/api/orgs/explore")
    cards = r.json()["orgs"]
    assert len(cards) == 1
    card = cards[0]
    assert card["governance_type"] == "Civic Advocacy Group"
    assert card["logo_url"] == "/uploads/logos/branded/large.png"
    assert card["branding"] == {
        "primary_color": "#1B3A5C",
        "accent_color": "#2E75B6",
    }


def test_card_omits_branding_keys_when_unset(client, db_session):
    """When an org has no branding configured, the card surfaces
    nulls (explicit nulls, not key-missing) so the FE doesn't need
    to handle "key missing" vs "value None" separately."""
    _make_org(db_session, "plain", join_policy="open")
    db_session.commit()

    r = client.get("/api/orgs/explore")
    card = r.json()["orgs"][0]
    assert card["logo_url"] is None
    assert card["branding"] == {
        "primary_color": None,
        "accent_color": None,
    }
    assert card["governance_type"] is None
