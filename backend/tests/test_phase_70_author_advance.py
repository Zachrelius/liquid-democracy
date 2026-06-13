"""Phase 70 — Author proposal advance: can_advance flag + single-source gate.

Coverage (spec: phase70_author_advance_and_admin_nav_2026-06-13.md):

1. `_viewer_can_advance` / `_viewer_can_advance_permission` unit coverage.
2. Single-source-of-truth agreement: for an author-advanceable status,
   can_advance==True ⟹ POST /advance does NOT 403; can_advance==False
   (a permission reason) ⟹ POST /advance DOES 403. The flag and the gate
   agree because both call _viewer_can_advance_permission.
3. ProposalOut.can_advance / next_status populate per status via the
   detail endpoint.
4. Config-error path: deliberation→voting with no voting_days + no positive
   org default → 400 with the config-error detail (Item 3 backend half).

Style mirrors test_phase_68b_proposal_archive.py.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from main import app
from role_seed import seed_default_roles_for_org
from tests.conftest import make_org_membership


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


@pytest.fixture(scope="function")
def test_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def client(test_db: Session):
    def _get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_user(db, username, *, is_admin=False) -> models.User:
    u = models.User(
        username=username, display_name=username, password_hash=_DUMMY_HASH,
        email=f"{username}@test.example", email_verified=True, is_admin=is_admin,
    )
    db.add(u)
    db.flush()
    return u


def _make_org(db, slug, *, settings=None) -> models.Organization:
    o = models.Organization(
        name=slug.title(), slug=slug, description="",
        settings=settings if settings is not None else {"default_voting_days": 7},
    )
    db.add(o)
    db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _make_proposal(db, author, org, *, status="draft", voting_days=7) -> models.Proposal:
    p = models.Proposal(
        title=f"P-{status}", body="", author_id=author.id, org_id=org.id,
        voting_method="binary", num_winners=1, status=status, voting_days=voting_days,
    )
    db.add(p)
    db.flush()
    return p


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


@pytest.fixture()
def setup(test_db):
    org = _make_org(test_db, "adv-org")
    author = _make_user(test_db, "author")
    other = _make_user(test_db, "other")
    steward = _make_user(test_db, "steward")  # holds proposal.advance_phase
    admin = _make_user(test_db, "platadmin", is_admin=True)
    make_org_membership(test_db, org_id=org.id, user_id=author.id, role="member")
    make_org_membership(test_db, org_id=org.id, user_id=other.id, role="member")
    make_org_membership(test_db, org_id=org.id, user_id=steward.id, role="steward")
    test_db.commit()
    return dict(org=org, author=author, other=other, steward=steward, admin=admin)


# ---------------------------------------------------------------------------
# 1. Unit coverage of the helpers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status,expected", [
    ("draft", True), ("deliberation", True),
    ("voting", False), ("passed", False), ("failed", False),
    ("withdrawn", False), ("unresolved", False),
])
def test_viewer_can_advance_author_by_status(test_db, setup, status, expected):
    from routes.proposals import _viewer_can_advance
    p = _make_proposal(test_db, setup["author"], setup["org"], status=status)
    test_db.commit()
    assert _viewer_can_advance(p, test_db, setup["author"].id) is expected


def test_viewer_can_advance_permission_ladder(test_db, setup):
    from routes.proposals import _viewer_can_advance_permission as perm
    p = _make_proposal(test_db, setup["author"], setup["org"], status="draft")
    test_db.commit()
    assert perm(p, test_db, setup["author"].id) is True       # author
    assert perm(p, test_db, setup["steward"].id) is True      # advance_phase holder
    assert perm(p, test_db, setup["admin"].id) is True        # platform admin
    assert perm(p, test_db, setup["other"].id) is False       # plain member
    assert perm(p, test_db, None) is False                    # no viewer


def test_viewer_can_advance_holder_and_admin_on_deliberation(test_db, setup):
    from routes.proposals import _viewer_can_advance
    p = _make_proposal(test_db, setup["author"], setup["org"], status="deliberation")
    test_db.commit()
    assert _viewer_can_advance(p, test_db, setup["steward"].id) is True
    assert _viewer_can_advance(p, test_db, setup["admin"].id) is True
    assert _viewer_can_advance(p, test_db, setup["other"].id) is False


# ---------------------------------------------------------------------------
# 2. Single-source-of-truth agreement: flag vs endpoint gate
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("viewer_key", ["author", "other", "steward", "admin"])
@pytest.mark.parametrize("status", ["draft", "deliberation"])
def test_flag_and_gate_agree(client, test_db, setup, viewer_key, status):
    """For an author-advanceable status: can_advance==True ⟹ POST /advance
    not 403; can_advance==False (permission reason) ⟹ POST 403."""
    p = _make_proposal(test_db, setup["author"], setup["org"], status=status)
    test_db.commit()
    viewer = setup[viewer_key]

    detail = client.get(f"/api/proposals/{p.id}", headers=_auth(viewer))
    assert detail.status_code == 200, detail.text
    can_advance = detail.json()["can_advance"]

    resp = client.post(f"/api/proposals/{p.id}/advance", headers=_auth(viewer), json={})
    if can_advance:
        assert resp.status_code != 403, (
            f"{viewer_key} on {status}: can_advance True but /advance 403'd: {resp.text}"
        )
    else:
        # For draft/deliberation, a False is always a permission reason
        # (a next status exists), so the gate MUST 403.
        assert resp.status_code == 403, (
            f"{viewer_key} on {status}: can_advance False but /advance "
            f"returned {resp.status_code}, expected 403"
        )


# ---------------------------------------------------------------------------
# 3. ProposalOut.can_advance / next_status via the detail endpoint
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status,exp_can,exp_next", [
    ("draft", True, "deliberation"),
    ("deliberation", True, "voting"),
    ("voting", False, None),
    ("passed", False, None),
    ("withdrawn", False, None),
])
def test_proposalout_fields(client, test_db, setup, status, exp_can, exp_next):
    p = _make_proposal(test_db, setup["author"], setup["org"], status=status)
    test_db.commit()
    body = client.get(f"/api/proposals/{p.id}", headers=_auth(setup["author"])).json()
    assert body["can_advance"] is exp_can
    assert body["next_status"] == exp_next


def test_non_author_member_sees_no_advance(client, test_db, setup):
    p = _make_proposal(test_db, setup["author"], setup["org"], status="draft")
    test_db.commit()
    body = client.get(f"/api/proposals/{p.id}", headers=_auth(setup["other"])).json()
    assert body["can_advance"] is False
    # next_status is informational (status-derived), independent of viewer.
    assert body["next_status"] == "deliberation"


# ---------------------------------------------------------------------------
# 4. Successful author advance through both rungs
# ---------------------------------------------------------------------------

def test_author_advances_draft_then_deliberation(client, test_db, setup):
    p = _make_proposal(test_db, setup["author"], setup["org"], status="draft")
    test_db.commit()

    r1 = client.post(f"/api/proposals/{p.id}/advance", headers=_auth(setup["author"]), json={})
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == "deliberation"
    assert r1.json()["can_advance"] is True
    assert r1.json()["next_status"] == "voting"

    r2 = client.post(f"/api/proposals/{p.id}/advance", headers=_auth(setup["author"]), json={})
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "voting"
    # Voting is not author-advanceable — control disappears.
    assert r2.json()["can_advance"] is False
    assert r2.json()["next_status"] is None


# ---------------------------------------------------------------------------
# 5. Config-error path (Item 3 backend half)
# ---------------------------------------------------------------------------

def test_advance_to_voting_config_error(client, test_db):
    org = _make_org(test_db, "no-vdays", settings={"default_voting_days": 0})
    author = _make_user(test_db, "cfg-author")
    make_org_membership(test_db, org_id=org.id, user_id=author.id, role="member")
    # No per-proposal voting_days + zero org default → advance-to-voting 400.
    p = _make_proposal(test_db, author, org, status="deliberation", voting_days=None)
    test_db.commit()

    resp = client.post(f"/api/proposals/{p.id}/advance", headers=_auth(author), json={})
    assert resp.status_code == 400, resp.text
    assert "voting_days" in resp.json()["detail"]
