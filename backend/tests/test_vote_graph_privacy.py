"""
Phase 7C.1 — Vote-graph privacy boundary tests.

These tests pin the new identity-vs-ballot privacy semantics introduced in
Phase 7C.1. Previously the API redacted both `label` AND `ballot` for any
voter the current user couldn't see by identity. The new semantics decouple
those two boundaries:

  - Identity (label): redacted when the viewer doesn't have a follow / public-
    delegate / private-delegation-to-me relationship with the voter.
  - Ballot content: returned for every voter who cast one. The aggregate
    population view (per-option counts, cluster shape) is visible to all
    viewers anyway; per-node ballot data is just the projection of that.

Suite map:

  01: Anonymous voter — ballot visible (approvals list populated), label empty.
  02: Anonymous voter — ranked-choice ballot visible, label empty.
  03: Followed voter — full visibility (label + ballot both populated).
  04: Anonymous node has no other identity-leaking fields beyond what the
      schema explicitly returns.
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

_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def test_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False)
    session = TestingSessionLocal()
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user(db: Session, username: str, display_name: str | None = None) -> models.User:
    u = models.User(
        username=username,
        display_name=display_name or username.title(),
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=True,
    )
    db.add(u)
    db.flush()
    return u


def _topic(db: Session) -> models.Topic:
    t = models.Topic(name=f"Topic-{models._uuid()[:8]}", description="", color="#abcabc")
    db.add(t)
    db.flush()
    return t


def _approval_proposal(db: Session, author: models.User, topic, labels=None):
    p = models.Proposal(
        title="Approval", body="", author_id=author.id,
        voting_method="approval", status="voting",
    )
    db.add(p)
    db.flush()
    db.add(models.ProposalTopic(proposal_id=p.id, topic_id=topic.id))
    for i, label in enumerate(labels or ["A", "B", "C"]):
        db.add(models.ProposalOption(
            proposal_id=p.id, label=label, description="", display_order=i,
        ))
    db.flush()
    return p


def _rcv_proposal(db: Session, author: models.User, topic, labels=None):
    p = models.Proposal(
        title="RCV", body="", author_id=author.id,
        voting_method="ranked_choice", num_winners=1, status="voting",
    )
    db.add(p)
    db.flush()
    db.add(models.ProposalTopic(proposal_id=p.id, topic_id=topic.id))
    for i, label in enumerate(labels or ["A", "B", "C"]):
        db.add(models.ProposalOption(
            proposal_id=p.id, label=label, description="", display_order=i,
        ))
    db.flush()
    return p


def _option_ids(db: Session, proposal) -> list[str]:
    opts = db.query(models.ProposalOption).filter(
        models.ProposalOption.proposal_id == proposal.id,
    ).order_by(models.ProposalOption.display_order).all()
    return [o.id for o in opts]


def _cast_approval(db: Session, user, proposal, approvals: list[str]):
    db.add(models.Vote(
        proposal_id=proposal.id, user_id=user.id,
        vote_value=None, ballot={"approvals": approvals},
        is_direct=True, cast_by_id=user.id,
    ))
    db.flush()


def _cast_ranked(db: Session, user, proposal, ranking: list[str]):
    db.add(models.Vote(
        proposal_id=proposal.id, user_id=user.id,
        vote_value=None, ballot={"ranking": ranking},
        is_direct=True, cast_by_id=user.id,
    ))
    db.flush()


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _node(graph: dict, user_id: str) -> dict:
    for n in graph["nodes"]:
        if n["id"] == user_id:
            return n
    raise AssertionError(f"Node {user_id} not found in graph")


# ===========================================================================
# Tests
# ===========================================================================

def test_anonymous_voter_ballot_visible_but_label_redacted(client, test_db):
    """Several voters, viewer doesn't follow them — labels empty, ballots populated."""
    topic = _topic(test_db)
    viewer = _user(test_db, "viewer", "Viewer Person")
    voter_a = _user(test_db, "voter_a", "Aiyana A.")
    voter_b = _user(test_db, "voter_b", "Bo B.")
    voter_c = _user(test_db, "voter_c", "Carmen C.")
    p = _approval_proposal(test_db, viewer, topic, labels=["X", "Y", "Z"])
    oids = _option_ids(test_db, p)
    _cast_approval(test_db, voter_a, p, [oids[0], oids[1]])
    _cast_approval(test_db, voter_b, p, [oids[1]])
    _cast_approval(test_db, voter_c, p, [oids[0], oids[2]])
    test_db.commit()

    resp = client.get(f"/api/proposals/{p.id}/vote-graph", headers=_auth(viewer))
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # All three are anonymous to viewer — labels blank, ballots populated.
    for voter, expected_approvals in (
        (voter_a, [oids[0], oids[1]]),
        (voter_b, [oids[1]]),
        (voter_c, [oids[0], oids[2]]),
    ):
        n = _node(data, voter.id)
        assert n["label"] == "", f"{voter.username} label should be redacted"
        assert n["ballot"] is not None, f"{voter.username} ballot should be visible"
        assert sorted(n["ballot"]["approvals"]) == sorted(expected_approvals), (
            f"{voter.username} ballot mismatch"
        )


def test_anonymous_voter_rcv_ballot_visible_label_redacted(client, test_db):
    """RCV: anonymous voter's ranking is returned in cast order; label hidden."""
    topic = _topic(test_db)
    viewer = _user(test_db, "viewer")
    stranger = _user(test_db, "stranger", "Devika D.")
    p = _rcv_proposal(test_db, viewer, topic, labels=["A", "B", "C"])
    oids = _option_ids(test_db, p)
    ordered = [oids[2], oids[0], oids[1]]  # C > A > B
    _cast_ranked(test_db, stranger, p, ordered)
    test_db.commit()

    resp = client.get(f"/api/proposals/{p.id}/vote-graph", headers=_auth(viewer))
    assert resp.status_code == 200
    data = resp.json()
    n = _node(data, stranger.id)
    assert n["label"] == ""
    assert n["ballot"] is not None
    assert n["ballot"]["ranking"] == ordered


def test_followed_voter_full_visibility(client, test_db):
    """A voter the viewer follows has both label and ballot populated."""
    topic = _topic(test_db)
    viewer = _user(test_db, "viewer", "Viewer Person")
    followed = _user(test_db, "friend", "Hiroshi H.")
    # viewer follows `followed`
    test_db.add(models.FollowRelationship(
        follower_id=viewer.id,
        followed_id=followed.id,
        permission_level="view_only",
    ))
    p = _approval_proposal(test_db, viewer, topic, labels=["A", "B"])
    oids = _option_ids(test_db, p)
    _cast_approval(test_db, followed, p, [oids[0], oids[1]])
    test_db.commit()

    resp = client.get(f"/api/proposals/{p.id}/vote-graph", headers=_auth(viewer))
    assert resp.status_code == 200
    data = resp.json()
    n = _node(data, followed.id)
    # Both label and ballot are populated.
    assert n["label"] == "Hiroshi H."
    assert n["ballot"] is not None
    assert sorted(n["ballot"]["approvals"]) == sorted([oids[0], oids[1]])


def test_anonymous_node_has_no_other_identity_leaks(client, test_db):
    """Anonymous voter node has no field that reveals identity beyond what the
    schema documents.

    The VoteFlowNode schema fields that could in principle leak identity are
    `label` (the only one explicitly meant to carry display name). Confirm
    label is empty AND no other field accidentally carries username, email,
    or display_name for an anonymous voter.
    """
    topic = _topic(test_db)
    viewer = _user(test_db, "viewer", "Viewer Person")
    secret_user = _user(test_db, "secret_username", "Imani I.")
    # Make sure secret_user has a distinctive email and display_name we can grep for.
    secret_user.email = "secret_email@example.test"
    test_db.flush()
    p = _approval_proposal(test_db, viewer, topic, labels=["A", "B"])
    oids = _option_ids(test_db, p)
    _cast_approval(test_db, secret_user, p, [oids[0]])
    test_db.commit()

    resp = client.get(f"/api/proposals/{p.id}/vote-graph", headers=_auth(viewer))
    assert resp.status_code == 200
    data = resp.json()
    n = _node(data, secret_user.id)
    assert n["label"] == ""
    # Serialise the full node dict and confirm none of the identity strings appear.
    import json
    blob = json.dumps(n)
    assert "secret_username" not in blob, "username leaked into anonymous node"
    assert "secret_email" not in blob, "email leaked into anonymous node"
    assert "Imani" not in blob, "display_name leaked into anonymous node"
    # Ballot still populated (the whole point of the new boundary).
    assert n["ballot"] is not None
    assert n["ballot"]["approvals"] == [oids[0]]
