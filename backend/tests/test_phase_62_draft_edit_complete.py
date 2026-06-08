"""Phase 62 A4 — full-field draft-edit PATCH tests.

Builds on Phase 59's draft-edit tests. Phase 62 extends the PATCH
endpoint to accept ``verification_floor`` + ``verification_jurisdiction``
while ``status='draft'``, reusing the create-path normalization +
validation block.

The other field groups (thresholds, durations, topics, stable_result,
engagement overrides) were already accepted by PATCH pre-Phase-62;
they're spot-checked here as part of the "full-field round-trip" test
to lock in the contract the FE now relies on.

Side-effect asserts per CLAUDE.md — read persisted state back rather
than relying on the response payload alone.
"""
from __future__ import annotations

from datetime import datetime, timedelta
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
    db: Session, slug: str = "p62-test-org",
) -> models.Organization:
    o = models.Organization(
        name=slug.title(),
        slug=slug,
        description="",
        join_policy="open",
        settings={
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
        title="P62 Draft",
        body="body",
        author_id=author.id,
        voting_method=voting_method,
        status=status,
        org_id=org.id,
        num_winners=num_winners,
    )
    if status != "draft":
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
# Verification floor — new in Phase 62 A2
# ===========================================================================


def test_verification_floor_set_in_draft_persists(client, db_session):
    """Setting a valid floor + jurisdiction on a draft persists both."""
    org = _make_org(db_session)
    steward = _make_user(db_session, "stew")
    _add_member(db_session, org, steward)
    p = _make_proposal(db_session, org, steward, status="draft")
    assert p.verification_floor is None
    db_session.commit()

    r = client.patch(
        f"/api/proposals/{p.id}",
        headers=_auth(steward.id),
        json={
            "verification_floor": "address_on_id",
            "verification_jurisdiction": "US-CA",
        },
    )
    assert r.status_code == 200, r.text
    db_session.refresh(p)
    assert p.verification_floor == "address_on_id"
    assert p.verification_jurisdiction == "US-CA"


def test_verification_floor_clear_in_draft_via_explicit_null(client, db_session):
    """Sending verification_floor=null clears a previously-set gate
    (jurisdiction is cleared alongside)."""
    org = _make_org(db_session)
    steward = _make_user(db_session, "stew")
    _add_member(db_session, org, steward)
    p = _make_proposal(db_session, org, steward, status="draft")
    p.verification_floor = "address_on_id"
    p.verification_jurisdiction = "US-CA"
    db_session.commit()

    r = client.patch(
        f"/api/proposals/{p.id}",
        headers=_auth(steward.id),
        json={
            "verification_floor": None,
            "verification_jurisdiction": None,
        },
    )
    assert r.status_code == 200, r.text
    db_session.refresh(p)
    assert p.verification_floor is None
    assert p.verification_jurisdiction is None


def test_verification_floor_email_only_normalized_to_null(client, db_session):
    """email_only is a no-op gate (predicate returns True for everyone).
    The create path normalizes it to NULL; the PATCH path must too."""
    org = _make_org(db_session)
    steward = _make_user(db_session, "stew")
    _add_member(db_session, org, steward)
    p = _make_proposal(db_session, org, steward, status="draft")
    db_session.commit()

    r = client.patch(
        f"/api/proposals/{p.id}",
        headers=_auth(steward.id),
        json={"verification_floor": "email_only"},
    )
    assert r.status_code == 200, r.text
    db_session.refresh(p)
    assert p.verification_floor is None
    assert p.verification_jurisdiction is None


def test_verification_floor_unknown_value_rejected_400(client, db_session):
    """An unknown floor value 400s with a "Unknown verification_floor"
    detail — same as create."""
    org = _make_org(db_session)
    steward = _make_user(db_session, "stew")
    _add_member(db_session, org, steward)
    p = _make_proposal(db_session, org, steward, status="draft")
    db_session.commit()

    r = client.patch(
        f"/api/proposals/{p.id}",
        headers=_auth(steward.id),
        json={"verification_floor": "definitely_not_a_state"},
    )
    assert r.status_code == 400, r.text
    assert "Unknown verification_floor" in r.json()["detail"]


def test_verification_floor_state_id_without_jurisdiction_rejected(client, db_session):
    """state_id (and any jurisdiction-required floor) requires a
    non-empty jurisdiction. Mirrors the create-path validator."""
    org = _make_org(db_session)
    steward = _make_user(db_session, "stew")
    _add_member(db_session, org, steward)
    p = _make_proposal(db_session, org, steward, status="draft")
    db_session.commit()

    r = client.patch(
        f"/api/proposals/{p.id}",
        headers=_auth(steward.id),
        json={"verification_floor": "address_on_id"},  # no jurisdiction
    )
    assert r.status_code == 400, r.text
    assert "verification_jurisdiction" in r.json()["detail"]


def test_verification_floor_non_jurisdiction_drops_jurisdiction(client, db_session):
    """Lower-tier floors (e.g. 'country' which doesn't require
    jurisdiction) drop a stray jurisdiction so the column pair stays
    consistent. Mirrors the create-path normalization."""
    org = _make_org(db_session)
    steward = _make_user(db_session, "stew")
    _add_member(db_session, org, steward)
    p = _make_proposal(db_session, org, steward, status="draft")
    db_session.commit()

    r = client.patch(
        f"/api/proposals/{p.id}",
        headers=_auth(steward.id),
        json={
            # identity_unique doesn't require a jurisdiction; sending one
            # is the misleading-input case the normalization block drops.
            "verification_floor": "identity_unique",
            "verification_jurisdiction": "US",  # would be dropped
        },
    )
    assert r.status_code == 200, r.text
    db_session.refresh(p)
    assert p.verification_floor == "identity_unique"
    assert p.verification_jurisdiction is None


def test_verification_floor_change_on_non_draft_rejected_400(client, db_session):
    """Phase 62 A2 load-bearing invariant: verification floor edits are
    draft-only. Changing the gate on a deliberating/voting proposal
    would re-eligible/de-eligible voters mid-cycle."""
    org = _make_org(db_session)
    steward = _make_user(db_session, "stew")
    _add_member(db_session, org, steward)
    p = _make_proposal(db_session, org, steward, status="deliberation")
    p.deliberation_start = datetime.utcnow() - timedelta(hours=1)
    p.deliberation_days = 7
    db_session.commit()

    r = client.patch(
        f"/api/proposals/{p.id}",
        headers=_auth(steward.id),
        json={
            "verification_floor": "address_on_id",
            "verification_jurisdiction": "US-CA",
        },
    )
    assert r.status_code == 400, r.text
    assert "draft" in r.json()["detail"].lower()
    # Side-effect assert: nothing persisted.
    db_session.refresh(p)
    assert p.verification_floor is None
    assert p.verification_jurisdiction is None


def test_jurisdiction_only_no_floor_is_noop(client, db_session):
    """Sending verification_jurisdiction without verification_floor is
    a no-op (matches the create-path semantics where the normalization
    block only fires when floor is non-null)."""
    org = _make_org(db_session)
    steward = _make_user(db_session, "stew")
    _add_member(db_session, org, steward)
    p = _make_proposal(db_session, org, steward, status="draft")
    p.verification_floor = "address_on_id"
    p.verification_jurisdiction = "US-CA"
    db_session.commit()

    r = client.patch(
        f"/api/proposals/{p.id}",
        headers=_auth(steward.id),
        json={"verification_jurisdiction": "US-NY"},  # no floor
    )
    assert r.status_code == 200, r.text
    db_session.refresh(p)
    # Floor + jurisdiction unchanged (jurisdiction-alone is a no-op).
    assert p.verification_floor == "address_on_id"
    assert p.verification_jurisdiction == "US-CA"


# ===========================================================================
# Full-field round-trip — the "everything at once" smoke test
# ===========================================================================


def test_full_field_round_trip_in_draft(client, db_session):
    """Submitting the full editable field set in a single PATCH (the
    A1 frontend's normal save flow) persists each field group."""
    org = _make_org(db_session)
    steward = _make_user(db_session, "stew")
    _add_member(db_session, org, steward)
    p = _make_proposal(db_session, org, steward, status="draft", voting_method="binary")
    # Pre-create a topic so the topics-replace test path has something
    # to set.
    topic = models.Topic(
        org_id=org.id, name="Phase 62 topic", color="#3b82f6",
    )
    db_session.add(topic)
    db_session.flush()
    db_session.commit()

    payload = {
        "title": "Round-trip title",
        "body": "Round-trip body",
        "voting_method": "approval",
        "options": [
            {"label": "Opt A", "description": ""},
            {"label": "Opt B", "description": ""},
        ],
        "topics": [{"topic_id": topic.id, "relevance": 0.75}],
        "pass_threshold": 0.60,
        "quorum_threshold": 0.30,
        "deliberation_days": 5,
        "voting_days": 2.5,
        "stable_result_required": True,
        "allow_pre_voting": True,
        "edit_lockout_fraction": 0.80,
        "verification_floor": "address_on_id",
        "verification_jurisdiction": "US-CA",
    }
    r = client.patch(
        f"/api/proposals/{p.id}",
        headers=_auth(steward.id),
        json=payload,
    )
    assert r.status_code == 200, r.text
    db_session.refresh(p)

    # Field-by-field side-effect asserts.
    assert p.title == "Round-trip title"
    assert p.body == "Round-trip body"
    assert p.voting_method == "approval"
    assert {o.label for o in p.options} == {"Opt A", "Opt B"}
    assert p.pass_threshold == 0.60
    assert p.quorum_threshold == 0.30
    assert p.deliberation_days == 5
    assert p.voting_days == 2.5
    assert p.stable_result_required is True
    assert p.allow_pre_voting is True
    assert p.edit_lockout_fraction == 0.80
    assert p.verification_floor == "address_on_id"
    assert p.verification_jurisdiction == "US-CA"

    # Topics replaced wholesale.
    pt_rows = (
        db_session.query(models.ProposalTopic)
        .filter_by(proposal_id=p.id)
        .all()
    )
    assert len(pt_rows) == 1
    assert pt_rows[0].topic_id == topic.id
    assert pt_rows[0].relevance == 0.75


def test_topics_replace_is_wholesale(client, db_session):
    """PATCH topics replaces the ProposalTopic set wholesale — existing
    rows are deleted, the new set is inserted, all within the request
    transaction."""
    org = _make_org(db_session)
    steward = _make_user(db_session, "stew")
    _add_member(db_session, org, steward)
    p = _make_proposal(db_session, org, steward, status="draft")

    # Two topics to start with.
    topic_a = models.Topic(org_id=org.id, name="topic-a", color="#a00000")
    topic_b = models.Topic(org_id=org.id, name="topic-b", color="#00a000")
    db_session.add_all([topic_a, topic_b])
    db_session.flush()
    db_session.add_all([
        models.ProposalTopic(proposal_id=p.id, topic_id=topic_a.id, relevance=1.0),
        models.ProposalTopic(proposal_id=p.id, topic_id=topic_b.id, relevance=0.5),
    ])
    db_session.commit()

    # Replace with just topic_a at a new relevance.
    r = client.patch(
        f"/api/proposals/{p.id}",
        headers=_auth(steward.id),
        json={"topics": [{"topic_id": topic_a.id, "relevance": 0.9}]},
    )
    assert r.status_code == 200, r.text

    pt_rows = (
        db_session.query(models.ProposalTopic)
        .filter_by(proposal_id=p.id)
        .all()
    )
    assert len(pt_rows) == 1
    assert pt_rows[0].topic_id == topic_a.id
    assert pt_rows[0].relevance == 0.9
