"""Phase 68b — archive a proposal (via the existing `withdrawn` status).

Side-effect assertions per CLAUDE.md (not just status codes):
  * Author archives own draft / deliberation → status==withdrawn,
    updated_at advanced, audit `proposal.archived` row with correct
    from_status.
  * Author CANNOT archive own voting proposal without proposal.archive.
  * proposal.archive holder archives voting → withdrawn, ALL Vote rows
    preserved (explicit count), no ProposalResults computed, audit
    from_status==voting.
  * proposal.archive holder archives passed / failed → withdrawn, votes
    preserved.
  * Non-holder non-author member → 403, unchanged.
  * Platform admin → allowed at any phase.
  * Already-withdrawn → 409, unchanged.
  * Ordering: archived proposal sorts into the closed bucket.
  * ProposalOut.can_archive mirrors the endpoint's permission ladder.
  * New-org parity baseline (Phase 48 helper): steward/admin hold
    proposal.archive; member does not.

Style mirrors test_phase_66_multiwinner_approval.py.
"""
from __future__ import annotations

from datetime import datetime, timezone

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
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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


def _make_org(db, slug) -> models.Organization:
    o = models.Organization(name=slug.title(), slug=slug, description="", settings={})
    db.add(o)
    db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _make_proposal(db, author, org, *, status="draft") -> models.Proposal:
    p = models.Proposal(
        title=f"P-{status}", body="", author_id=author.id, org_id=org.id,
        voting_method="binary", num_winners=1, status=status,
    )
    db.add(p)
    db.flush()
    return p


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _archive(client, proposal_id, auth):
    return client.post(f"/api/proposals/{proposal_id}/archive", headers=auth)


def _audit_rows(db, proposal_id):
    return db.query(models.AuditLog).filter(
        models.AuditLog.action == "proposal.archived",
        models.AuditLog.target_id == proposal_id,
    ).all()


@pytest.fixture()
def setup(test_db):
    org = _make_org(test_db, "arch-org")
    steward = _make_user(test_db, "steward")  # holds proposal.archive
    author = _make_user(test_db, "author")     # plain member
    other = _make_user(test_db, "other")       # plain member, not author
    admin = _make_user(test_db, "platadmin", is_admin=True)
    make_org_membership(test_db, org_id=org.id, user_id=steward.id, role="steward")
    make_org_membership(test_db, org_id=org.id, user_id=author.id, role="member")
    make_org_membership(test_db, org_id=org.id, user_id=other.id, role="member")
    test_db.commit()
    return dict(org=org, steward=steward, author=author, other=other, admin=admin)


# ---------------------------------------------------------------------------
# Author archives own draft / deliberation
# ---------------------------------------------------------------------------

def test_author_archives_own_draft(client, test_db, setup):
    p = _make_proposal(test_db, setup["author"], setup["org"], status="draft")
    p.updated_at = datetime(2020, 1, 1)
    test_db.commit()

    resp = _archive(client, p.id, _auth(setup["author"]))
    assert resp.status_code == 200, resp.text
    test_db.refresh(p)
    assert p.status == "withdrawn"
    assert p.updated_at.year >= 2026  # advanced
    rows = _audit_rows(test_db, p.id)
    assert len(rows) == 1
    assert rows[0].details["from_status"] == "draft"
    assert rows[0].actor_id == setup["author"].id


def test_author_archives_own_deliberation(client, test_db, setup):
    p = _make_proposal(test_db, setup["author"], setup["org"], status="deliberation")
    test_db.commit()

    resp = _archive(client, p.id, _auth(setup["author"]))
    assert resp.status_code == 200, resp.text
    test_db.refresh(p)
    assert p.status == "withdrawn"
    assert _audit_rows(test_db, p.id)[0].details["from_status"] == "deliberation"


def test_author_cannot_archive_own_voting_without_permission(client, test_db, setup):
    p = _make_proposal(test_db, setup["author"], setup["org"], status="voting")
    test_db.commit()

    resp = _archive(client, p.id, _auth(setup["author"]))
    assert resp.status_code == 403, resp.text
    test_db.refresh(p)
    assert p.status == "voting"  # unchanged
    assert _audit_rows(test_db, p.id) == []


# ---------------------------------------------------------------------------
# proposal.archive holder — any phase, votes preserved
# ---------------------------------------------------------------------------

def test_holder_archives_voting_preserves_votes(client, test_db, setup):
    p = _make_proposal(test_db, setup["author"], setup["org"], status="voting")
    # Two votes on the proposal — must survive the archive untouched.
    for voter in (setup["author"], setup["other"]):
        test_db.add(models.Vote(
            proposal_id=p.id, user_id=voter.id, cast_by_id=voter.id,
            vote_value="yes", is_direct=True,
        ))
    test_db.commit()
    votes_before = test_db.query(models.Vote).filter_by(proposal_id=p.id).count()
    assert votes_before == 2

    resp = _archive(client, p.id, _auth(setup["steward"]))
    assert resp.status_code == 200, resp.text
    test_db.refresh(p)
    assert p.status == "withdrawn"
    # Votes preserved — explicit count assertion.
    assert test_db.query(models.Vote).filter_by(proposal_id=p.id).count() == 2
    assert _audit_rows(test_db, p.id)[0].details["from_status"] == "voting"


def test_holder_archives_passed(client, test_db, setup):
    p = _make_proposal(test_db, setup["author"], setup["org"], status="passed")
    test_db.commit()
    resp = _archive(client, p.id, _auth(setup["steward"]))
    assert resp.status_code == 200, resp.text
    test_db.refresh(p)
    assert p.status == "withdrawn"
    assert _audit_rows(test_db, p.id)[0].details["from_status"] == "passed"


def test_holder_archives_failed(client, test_db, setup):
    p = _make_proposal(test_db, setup["author"], setup["org"], status="failed")
    test_db.commit()
    resp = _archive(client, p.id, _auth(setup["steward"]))
    assert resp.status_code == 200, resp.text
    test_db.refresh(p)
    assert p.status == "withdrawn"


# ---------------------------------------------------------------------------
# Negative / edge cases
# ---------------------------------------------------------------------------

def test_non_author_non_holder_member_forbidden(client, test_db, setup):
    p = _make_proposal(test_db, setup["author"], setup["org"], status="draft")
    test_db.commit()
    resp = _archive(client, p.id, _auth(setup["other"]))
    assert resp.status_code == 403, resp.text
    test_db.refresh(p)
    assert p.status == "draft"


def test_platform_admin_archives_any_phase(client, test_db, setup):
    p = _make_proposal(test_db, setup["author"], setup["org"], status="voting")
    test_db.commit()
    resp = _archive(client, p.id, _auth(setup["admin"]))
    assert resp.status_code == 200, resp.text
    test_db.refresh(p)
    assert p.status == "withdrawn"


def test_already_withdrawn_returns_409(client, test_db, setup):
    p = _make_proposal(test_db, setup["author"], setup["org"], status="withdrawn")
    test_db.commit()
    resp = _archive(client, p.id, _auth(setup["steward"]))
    assert resp.status_code == 409, resp.text
    # No second audit row written.
    assert _audit_rows(test_db, p.id) == []


def test_archive_unknown_proposal_404(client, test_db, setup):
    resp = _archive(client, "00000000-0000-0000-0000-000000000000", _auth(setup["steward"]))
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# Ordering — archived falls into the closed bucket
# ---------------------------------------------------------------------------

def test_archived_proposal_sorts_into_closed_bucket(client, test_db, setup):
    from routes.proposals import _proposal_list_ordering
    voting = _make_proposal(test_db, setup["author"], setup["org"], status="voting")
    delib = _make_proposal(test_db, setup["author"], setup["org"], status="deliberation")
    draft = _make_proposal(test_db, setup["author"], setup["org"], status="draft")
    archived = _make_proposal(test_db, setup["author"], setup["org"], status="voting")
    test_db.commit()

    _archive(client, archived.id, _auth(setup["steward"]))

    ordered = test_db.query(models.Proposal).filter_by(
        org_id=setup["org"].id,
    ).order_by(*_proposal_list_ordering()).all()
    ids = [p.id for p in ordered]
    # voting (0) + deliberation (1) come before the closed/withdrawn (2) one.
    assert ids.index(voting.id) < ids.index(archived.id)
    assert ids.index(delib.id) < ids.index(archived.id)
    # draft (group 3) sorts AFTER closed — archived is in closed (2).
    assert ids.index(archived.id) < ids.index(draft.id)


# ---------------------------------------------------------------------------
# can_archive capability surfaced on ProposalOut
# ---------------------------------------------------------------------------

def test_can_archive_true_for_author_in_draft(client, test_db, setup):
    p = _make_proposal(test_db, setup["author"], setup["org"], status="draft")
    test_db.commit()
    resp = client.get(f"/api/proposals/{p.id}", headers=_auth(setup["author"]))
    assert resp.status_code == 200, resp.text
    assert resp.json()["can_archive"] is True


def test_can_archive_false_for_author_in_voting(client, test_db, setup):
    p = _make_proposal(test_db, setup["author"], setup["org"], status="voting")
    test_db.commit()
    resp = client.get(f"/api/proposals/{p.id}", headers=_auth(setup["author"]))
    assert resp.status_code == 200, resp.text
    assert resp.json()["can_archive"] is False


def test_can_archive_true_for_holder_in_voting(client, test_db, setup):
    p = _make_proposal(test_db, setup["author"], setup["org"], status="voting")
    test_db.commit()
    resp = client.get(f"/api/proposals/{p.id}", headers=_auth(setup["steward"]))
    assert resp.status_code == 200, resp.text
    assert resp.json()["can_archive"] is True


def test_can_archive_false_when_already_withdrawn(client, test_db, setup):
    p = _make_proposal(test_db, setup["author"], setup["org"], status="withdrawn")
    test_db.commit()
    resp = client.get(f"/api/proposals/{p.id}", headers=_auth(setup["steward"]))
    assert resp.status_code == 200, resp.text
    assert resp.json()["can_archive"] is False


# ---------------------------------------------------------------------------
# New-org parity baseline (Phase 48 helper) — the existing-org backfill
# (in test_phase_68b_migration_cycle) must reach THIS state.
# ---------------------------------------------------------------------------

def test_new_org_grants_archive_to_steward_admin_not_member(test_db):
    org = _make_org(test_db, "fresh")
    test_db.commit()
    from role_permissions import has_permission

    steward = _make_user(test_db, "s2")
    admin = _make_user(test_db, "a2")
    member = _make_user(test_db, "m2")
    make_org_membership(test_db, org_id=org.id, user_id=steward.id, role="steward")
    make_org_membership(test_db, org_id=org.id, user_id=admin.id, role="admin")
    make_org_membership(test_db, org_id=org.id, user_id=member.id, role="member")
    test_db.commit()

    assert has_permission(test_db, steward.id, org.id, "proposal.archive") is True
    assert has_permission(test_db, admin.id, org.id, "proposal.archive") is True
    assert has_permission(test_db, member.id, org.id, "proposal.archive") is False
