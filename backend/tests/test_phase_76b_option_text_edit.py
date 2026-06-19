"""Phase 76b — in-place option label / description editing during deliberation.

PATCH /api/proposals/{id}/options/{option_id} edits an option's display text
without the delete+recreate the proposal PATCH `options` full-replace does, so
the option row (and its id) survives — preserving any pre-votes, write-in
attribution, and budget metadata.

Coverage:
  1. Author edits label + description in deliberation → 200, persisted, id kept.
  2. Edit rejected once voting has started → 409.
  3. Non-author without `org.edit_proposal` → 403; admin allowed.
  4. Duplicate / empty label → 400.
  5. In-place edit preserves a vote that references the option id.
  6. Election candidate options rejected → 400.
  7. Deliberation edit-lockout window blocks the edit → 403.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

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


def _user(db, username, *, is_admin=False):
    u = models.User(
        username=username, display_name=username, password_hash=_DUMMY_HASH,
        email=f"{username}@t.ex", email_verified=True, is_admin=is_admin,
    )
    db.add(u)
    db.flush()
    return u


def _org(db, slug):
    o = models.Organization(
        name=slug.title(), slug=slug, description="",
        settings={"default_voting_days": 7,
                  "allowed_voting_methods": ["binary", "approval"]},
    )
    db.add(o)
    db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _auth(user):
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _approval_proposal(db, author, org, *, status="deliberation",
                       labels=("Alpha", "Beta"), is_election=False,
                       deliberation_start=None, deliberation_days=None):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    p = models.Proposal(
        title="P", body="orig body", author_id=author.id, org_id=org.id,
        voting_method="approval", num_winners=1, status=status,
        is_election=is_election,
        deliberation_start=(
            deliberation_start if deliberation_start is not None
            else (now if status == "deliberation" else None)
        ),
        deliberation_days=deliberation_days,
        voting_start=now if status == "voting" else None,
        voting_end=(now + timedelta(days=7)) if status == "voting" else None,
    )
    db.add(p)
    db.flush()
    opts = []
    for i, label in enumerate(labels):
        o = models.ProposalOption(
            proposal_id=p.id, label=label, description="", display_order=i,
        )
        db.add(o)
        opts.append(o)
    db.flush()
    return p, opts


def _setup(db):
    org = _org(db, "opt-edit-org")
    author = _user(db, "author")
    member = _user(db, "member")
    make_org_membership(db, org_id=org.id, user_id=author.id, role="member")
    make_org_membership(db, org_id=org.id, user_id=member.id, role="member")
    db.commit()
    return org, author, member


def test_author_edits_option_text_in_deliberation(client, test_db):
    org, author, _member = _setup(test_db)
    p, opts = _approval_proposal(test_db, author, org)
    test_db.commit()
    oid = opts[0].id

    r = client.patch(
        f"/api/proposals/{p.id}/options/{oid}",
        headers=_auth(author),
        json={"label": "Alpha (revised)", "description": "a clearer take"},
    )
    assert r.status_code == 200, r.text
    out = {o["id"]: o for o in r.json()["options"]}
    assert out[oid]["label"] == "Alpha (revised)"
    assert out[oid]["description"] == "a clearer take"
    # id is unchanged — the row was edited in place, not recreated.
    test_db.expire_all()
    row = test_db.get(models.ProposalOption, oid)
    assert row is not None and row.label == "Alpha (revised)"


def test_description_only_edit(client, test_db):
    org, author, _member = _setup(test_db)
    p, opts = _approval_proposal(test_db, author, org)
    test_db.commit()
    oid = opts[1].id
    r = client.patch(
        f"/api/proposals/{p.id}/options/{oid}",
        headers=_auth(author), json={"description": "just the desc"},
    )
    assert r.status_code == 200, r.text
    out = {o["id"]: o for o in r.json()["options"]}
    assert out[oid]["description"] == "just the desc"
    assert out[oid]["label"] == "Beta"  # untouched


def test_edit_rejected_after_voting(client, test_db):
    org, author, _member = _setup(test_db)
    p, opts = _approval_proposal(test_db, author, org, status="voting")
    test_db.commit()
    r = client.patch(
        f"/api/proposals/{p.id}/options/{opts[0].id}",
        headers=_auth(author), json={"label": "nope"},
    )
    assert r.status_code == 409, r.text


def test_non_author_without_permission_forbidden(client, test_db):
    org, author, member = _setup(test_db)
    p, opts = _approval_proposal(test_db, author, org)
    test_db.commit()
    r = client.patch(
        f"/api/proposals/{p.id}/options/{opts[0].id}",
        headers=_auth(member), json={"label": "hijack"},
    )
    assert r.status_code == 403, r.text


def test_platform_admin_allowed(client, test_db):
    org, author, _member = _setup(test_db)
    admin = _user(test_db, "admin", is_admin=True)
    p, opts = _approval_proposal(test_db, author, org)
    test_db.commit()
    r = client.patch(
        f"/api/proposals/{p.id}/options/{opts[0].id}",
        headers=_auth(admin), json={"label": "admin edit"},
    )
    assert r.status_code == 200, r.text


def test_duplicate_label_rejected(client, test_db):
    org, author, _member = _setup(test_db)
    p, opts = _approval_proposal(test_db, author, org)
    test_db.commit()
    # rename Beta to "alpha" (case-insensitive clash with Alpha)
    r = client.patch(
        f"/api/proposals/{p.id}/options/{opts[1].id}",
        headers=_auth(author), json={"label": "  alpha "},
    )
    assert r.status_code == 400, r.text
    assert "duplicate" in r.json()["detail"].lower()


def test_empty_label_rejected(client, test_db):
    org, author, _member = _setup(test_db)
    p, opts = _approval_proposal(test_db, author, org)
    test_db.commit()
    r = client.patch(
        f"/api/proposals/{p.id}/options/{opts[0].id}",
        headers=_auth(author), json={"label": "   "},
    )
    assert r.status_code == 400, r.text


def test_no_fields_rejected(client, test_db):
    org, author, _member = _setup(test_db)
    p, opts = _approval_proposal(test_db, author, org)
    test_db.commit()
    r = client.patch(
        f"/api/proposals/{p.id}/options/{opts[0].id}",
        headers=_auth(author), json={},
    )
    assert r.status_code == 400, r.text


def test_in_place_edit_preserves_existing_vote(client, test_db):
    """A vote referencing the option id (e.g. a pre-vote during deliberation)
    is untouched by a text edit, because the option keeps its id."""
    org, author, member = _setup(test_db)
    p, opts = _approval_proposal(test_db, author, org)
    oid = opts[0].id
    vote = models.Vote(
        proposal_id=p.id, user_id=member.id, cast_by_id=member.id,
        is_direct=True, ballot={"approvals": [oid]},
    )
    test_db.add(vote)
    test_db.commit()
    vote_id = vote.id

    r = client.patch(
        f"/api/proposals/{p.id}/options/{oid}",
        headers=_auth(author), json={"label": "Renamed", "description": "x"},
    )
    assert r.status_code == 200, r.text

    test_db.expire_all()
    v = test_db.get(models.Vote, vote_id)
    assert v is not None
    assert v.ballot == {"approvals": [oid]}  # still references the same id
    assert test_db.get(models.ProposalOption, oid).label == "Renamed"


def test_election_option_rejected(client, test_db):
    org, author, _member = _setup(test_db)
    p, opts = _approval_proposal(
        test_db, author, org, is_election=True,
        labels=("candidate-uuid-1", "candidate-uuid-2"),
    )
    test_db.commit()
    r = client.patch(
        f"/api/proposals/{p.id}/options/{opts[0].id}",
        headers=_auth(author), json={"description": "Real Name"},
    )
    assert r.status_code == 400, r.text
    assert "election" in r.json()["detail"].lower()


def test_edit_lockout_blocks_edit(client, test_db):
    """Past the lockout fraction of the deliberation window, edits are 403 —
    same gate as title/body edits in update_proposal."""
    org, author, _member = _setup(test_db)
    # deliberation started 10 days ago with a 1-day window → well past lockout.
    start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=10)
    p, opts = _approval_proposal(
        test_db, author, org,
        deliberation_start=start, deliberation_days=1,
    )
    test_db.commit()
    r = client.patch(
        f"/api/proposals/{p.id}/options/{opts[0].id}",
        headers=_auth(author), json={"label": "too late"},
    )
    assert r.status_code == 403, r.text
    assert "locked" in r.json()["detail"].lower()


def test_option_not_found(client, test_db):
    org, author, _member = _setup(test_db)
    p, _opts = _approval_proposal(test_db, author, org)
    test_db.commit()
    r = client.patch(
        f"/api/proposals/{p.id}/options/does-not-exist",
        headers=_auth(author), json={"label": "x"},
    )
    assert r.status_code == 404, r.text
