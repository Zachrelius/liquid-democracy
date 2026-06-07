"""Phase 59 Cluster A — draft-edit + type-change + hard-delete tests.

Side-effect asserts per CLAUDE.md (read persisted state back; not just
status codes).

Test families:
  * Draft PATCH (title, body, topics) — persists.
  * Type change (A4):
      - binary → approval/RCV is allowed in draft.
      - approval/RCV → binary in draft DISCARDS existing options.
      - approval ↔ ranked_choice in draft preserves options.
      - Leaving RCV resets num_winners to 1 (unless explicit).
      - Type change REJECTED on non-draft status (the load-bearing guard).
      - num_winners-only change REJECTED on non-draft status.
  * Hard delete (A5):
      - DELETE draft cascades + removes row.
      - DELETE rejected with 400 on non-draft status (THE load-bearing
        invariant — protects the audit trail).
      - DELETE rejected with 403 for non-author / no permission.
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
    db: Session, slug: str = "draft-test-org",
) -> models.Organization:
    o = models.Organization(
        name=slug.title(), slug=slug, description="",
        join_policy="open", settings={
            # Allow all three methods so type-change tests aren't blocked
            # by the allowed-methods gate.
            "allowed_voting_methods": ["binary", "approval", "ranked_choice"],
        },
    )
    db.add(o)
    db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _add_member(
    db: Session, org: models.Organization, user: models.User,
    role: str = "steward",
) -> None:
    role_row = (
        db.query(models.Role)
        .filter_by(org_id=org.id, system_key=role)
        .first()
    )
    db.add(models.OrgMembership(
        user_id=user.id, org_id=org.id,
        role_id=role_row.id, status="active",
    ))
    db.flush()


def _make_proposal(
    db: Session, org: models.Organization, author: models.User, *,
    status: str = "draft",
    voting_method: str = "binary",
    options: Optional[list[str]] = None,
    num_winners: int = 1,
) -> models.Proposal:
    p = models.Proposal(
        title="Draft Test", body="body", author_id=author.id,
        voting_method=voting_method, status=status,
        org_id=org.id, num_winners=num_winners,
    )
    if status != "draft":
        # Add timestamps so downstream gates don't choke.
        p.voting_start = datetime.utcnow() - timedelta(days=1)
        p.voting_end = datetime.utcnow() + timedelta(days=1)
    db.add(p)
    db.flush()
    if options:
        for i, label in enumerate(options):
            db.add(models.ProposalOption(
                proposal_id=p.id, label=label, display_order=i,
            ))
        db.flush()
    return p


# ===========================================================================
# Draft PATCH — title/body persistence
# ===========================================================================


def test_draft_patch_title_and_body_persists(client, db_session):
    org = _make_org(db_session)
    steward = _make_user(db_session, "stew")
    _add_member(db_session, org, steward)
    p = _make_proposal(db_session, org, steward, status="draft")
    db_session.commit()

    r = client.patch(
        f"/api/proposals/{p.id}",
        headers=_auth(steward.id),
        json={"title": "Updated title", "body": "Updated body"},
    )
    assert r.status_code == 200, r.text
    db_session.refresh(p)
    assert p.title == "Updated title"
    assert p.body == "Updated body"


# ===========================================================================
# Type change (A4)
# ===========================================================================


def test_type_change_binary_to_approval_in_draft(client, db_session):
    org = _make_org(db_session)
    steward = _make_user(db_session, "stew")
    _add_member(db_session, org, steward)
    p = _make_proposal(db_session, org, steward, voting_method="binary")
    db_session.commit()

    r = client.patch(
        f"/api/proposals/{p.id}",
        headers=_auth(steward.id),
        json={"voting_method": "approval"},
    )
    assert r.status_code == 200, r.text
    db_session.refresh(p)
    assert p.voting_method == "approval"


def test_type_change_approval_to_binary_discards_options(client, db_session):
    """Spec A4: switching to binary from an options-method discards
    the ProposalOption rows. The FE confirms with the user before
    submitting; the backend just performs the discard."""
    org = _make_org(db_session)
    steward = _make_user(db_session, "stew")
    _add_member(db_session, org, steward)
    p = _make_proposal(
        db_session, org, steward,
        voting_method="approval",
        options=["Opt A", "Opt B", "Opt C"],
    )
    db_session.commit()
    assert len(p.options) == 3

    r = client.patch(
        f"/api/proposals/{p.id}",
        headers=_auth(steward.id),
        json={"voting_method": "binary"},
    )
    assert r.status_code == 200, r.text
    db_session.refresh(p)
    assert p.voting_method == "binary"
    # Options are gone (cascade via explicit db.delete in handler).
    remaining = db_session.query(models.ProposalOption).filter_by(
        proposal_id=p.id,
    ).all()
    assert remaining == [], (
        f"Expected zero options after binary switch, got {len(remaining)}"
    )


def test_type_change_approval_to_rcv_preserves_options(client, db_session):
    """Switching between two options-methods preserves the options."""
    org = _make_org(db_session)
    steward = _make_user(db_session, "stew")
    _add_member(db_session, org, steward)
    p = _make_proposal(
        db_session, org, steward,
        voting_method="approval",
        options=["X", "Y"],
    )
    db_session.commit()

    r = client.patch(
        f"/api/proposals/{p.id}",
        headers=_auth(steward.id),
        json={"voting_method": "ranked_choice", "num_winners": 1},
    )
    assert r.status_code == 200, r.text
    db_session.refresh(p)
    assert p.voting_method == "ranked_choice"
    remaining = sorted(o.label for o in p.options)
    assert remaining == ["X", "Y"]


def test_leaving_rcv_resets_num_winners(client, db_session):
    org = _make_org(db_session)
    steward = _make_user(db_session, "stew")
    _add_member(db_session, org, steward)
    p = _make_proposal(
        db_session, org, steward,
        voting_method="ranked_choice",
        options=["A", "B", "C"],
        num_winners=3,
    )
    db_session.commit()

    r = client.patch(
        f"/api/proposals/{p.id}",
        headers=_auth(steward.id),
        json={"voting_method": "approval"},
    )
    assert r.status_code == 200, r.text
    db_session.refresh(p)
    assert p.voting_method == "approval"
    assert p.num_winners == 1, (
        f"Leaving RCV should snap num_winners to 1; got {p.num_winners}"
    )


def test_type_change_rejected_on_non_draft(client, db_session):
    """LOAD-BEARING: type changes outside draft are 400."""
    org = _make_org(db_session)
    steward = _make_user(db_session, "stew")
    _add_member(db_session, org, steward)
    p = _make_proposal(
        db_session, org, steward,
        status="deliberation", voting_method="binary",
    )
    db_session.commit()

    r = client.patch(
        f"/api/proposals/{p.id}",
        headers=_auth(steward.id),
        json={"voting_method": "approval"},
    )
    assert r.status_code == 400, r.text
    assert "draft" in r.text.lower()
    db_session.refresh(p)
    assert p.voting_method == "binary"  # unchanged


def test_num_winners_change_rejected_on_non_draft(client, db_session):
    org = _make_org(db_session)
    steward = _make_user(db_session, "stew")
    _add_member(db_session, org, steward)
    p = _make_proposal(
        db_session, org, steward,
        status="voting", voting_method="ranked_choice",
        options=["A", "B"], num_winners=1,
    )
    db_session.commit()

    r = client.patch(
        f"/api/proposals/{p.id}",
        headers=_auth(steward.id),
        json={"num_winners": 2},
    )
    assert r.status_code == 400, r.text
    db_session.refresh(p)
    assert p.num_winners == 1  # unchanged


# ===========================================================================
# Hard delete (A5)
# ===========================================================================


def test_delete_draft_removes_proposal(client, db_session):
    org = _make_org(db_session)
    steward = _make_user(db_session, "stew")
    _add_member(db_session, org, steward)
    p = _make_proposal(
        db_session, org, steward,
        voting_method="approval",
        options=["A", "B"],
    )
    db_session.commit()
    pid = p.id

    r = client.delete(
        f"/api/proposals/{pid}",
        headers=_auth(steward.id),
    )
    assert r.status_code == 204, r.text
    # Proposal row gone.
    survivors = db_session.query(models.Proposal).filter_by(id=pid).all()
    assert survivors == []
    # Option rows cascaded.
    options = db_session.query(models.ProposalOption).filter_by(
        proposal_id=pid,
    ).all()
    assert options == []


def test_delete_proposal_rejected_on_non_draft_status(client, db_session):
    """LOAD-BEARING: only drafts can be hard-deleted. Proposals that
    have entered deliberation/voting are withdrawn (preserving audit),
    not deleted. This protects the audit trail."""
    org = _make_org(db_session)
    steward = _make_user(db_session, "stew")
    _add_member(db_session, org, steward)
    p_delib = _make_proposal(
        db_session, org, steward, status="deliberation",
    )
    p_voting = _make_proposal(
        db_session, org, steward, status="voting",
    )
    p_passed = _make_proposal(
        db_session, org, steward, status="passed",
    )
    db_session.commit()

    for p, label in (
        (p_delib, "deliberation"),
        (p_voting, "voting"),
        (p_passed, "passed"),
    ):
        r = client.delete(
            f"/api/proposals/{p.id}",
            headers=_auth(steward.id),
        )
        assert r.status_code == 400, (label, r.text)
        # Proposal row survived.
        db_session.refresh(p)
        assert p.id == p.id  # still present (refresh would have errored otherwise)


def test_delete_proposal_rejected_for_non_author_without_permission(
    client, db_session,
):
    """Author OR org.edit_proposal OR platform admin can delete. A
    plain member can't."""
    org = _make_org(db_session)
    author = _make_user(db_session, "author")
    member = _make_user(db_session, "rando")
    _add_member(db_session, org, author, role="member")
    _add_member(db_session, org, member, role="member")
    p = _make_proposal(db_session, org, author)
    db_session.commit()

    r = client.delete(
        f"/api/proposals/{p.id}",
        headers=_auth(member.id),
    )
    assert r.status_code == 403, r.text
    # Proposal still exists.
    assert db_session.query(models.Proposal).filter_by(id=p.id).first() is not None


def test_delete_proposal_allowed_for_author(client, db_session):
    org = _make_org(db_session)
    author = _make_user(db_session, "author")
    _add_member(db_session, org, author, role="member")
    p = _make_proposal(db_session, org, author)
    db_session.commit()

    r = client.delete(
        f"/api/proposals/{p.id}",
        headers=_auth(author.id),
    )
    assert r.status_code == 204, r.text
