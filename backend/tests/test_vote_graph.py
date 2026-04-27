"""
Phase 7B — Vote graph endpoint tests.

Covers method-aware extensions to GET /api/proposals/{id}/vote-graph and the
proposal-list "votes_cast" counter fix for ranked_choice. Suite map:

  01: Approval graph returns options list with correct approval_count.
  02: Approval graph populates ballot.approvals for both visible AND
      anonymous voters (ballot is part of the aggregate population view —
      Phase 7C.1 privacy boundary). Only label is gated on identity.
  03: RCV graph returns options list with correct first_pref_count.
  04: RCV graph populates ballot.ranking for visible voters in rank order.
  05: Tied RCV graph: clusters.rcv.winners has length > 1.
  06: Binary graph regression: legacy top-level yes/no/abstain populated and
      clusters.binary mirrors them.
  07: Privacy (Phase 7C.1): anonymous voters keep ballots populated but
      label is empty — identity hidden, ballot content visible.
  08: Privacy: voters who privately delegate to current user have visible ballots.
  09: Proposal-list votes_cast counter accurate for binary/approval/ranked_choice.
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
# Fixtures (mirroring the pattern used in test_ranked_choice_voting.py)
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


def _topic(db: Session) -> models.Topic:
    t = models.Topic(name=f"Topic-{models._uuid()[:8]}", description="", color="#abcabc")
    db.add(t)
    db.flush()
    return t


def _approval_proposal(db: Session, author: models.User, topic, labels=None,
                        status="voting") -> models.Proposal:
    p = models.Proposal(
        title="Approval Vote",
        body="",
        author_id=author.id,
        voting_method="approval",
        status=status,
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


def _rcv_proposal(db: Session, author: models.User, topic, labels=None,
                   num_winners=1, status="voting") -> models.Proposal:
    p = models.Proposal(
        title="RCV Vote",
        body="",
        author_id=author.id,
        voting_method="ranked_choice",
        num_winners=num_winners,
        status=status,
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


def _binary_proposal(db: Session, author: models.User, topic,
                      status="voting") -> models.Proposal:
    p = models.Proposal(
        title="Binary Vote",
        body="",
        author_id=author.id,
        voting_method="binary",
        status=status,
    )
    db.add(p)
    db.flush()
    db.add(models.ProposalTopic(proposal_id=p.id, topic_id=topic.id))
    db.flush()
    return p


def _option_ids(db: Session, proposal) -> list[str]:
    opts = db.query(models.ProposalOption).filter(
        models.ProposalOption.proposal_id == proposal.id,
    ).order_by(models.ProposalOption.display_order).all()
    return [o.id for o in opts]


def _cast_approval(db: Session, user, proposal, approvals: list[str]):
    db.add(models.Vote(
        proposal_id=proposal.id,
        user_id=user.id,
        vote_value=None,
        ballot={"approvals": approvals},
        is_direct=True,
        cast_by_id=user.id,
    ))
    db.flush()


def _cast_ranked(db: Session, user, proposal, ranking: list[str]):
    db.add(models.Vote(
        proposal_id=proposal.id,
        user_id=user.id,
        vote_value=None,
        ballot={"ranking": ranking},
        is_direct=True,
        cast_by_id=user.id,
    ))
    db.flush()


def _cast_binary(db: Session, user, proposal, value: str):
    db.add(models.Vote(
        proposal_id=proposal.id,
        user_id=user.id,
        vote_value=value,
        is_direct=True,
        cast_by_id=user.id,
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

def test_01_approval_graph_options_have_correct_approval_count(client, test_db):
    """Approval graph returns options list with approval_count per option."""
    topic = _topic(test_db)
    author = _user(test_db, "author")
    voter1 = _user(test_db, "v1")
    voter2 = _user(test_db, "v2")
    voter3 = _user(test_db, "v3")
    p = _approval_proposal(test_db, author, topic, labels=["A", "B", "C"])
    oids = _option_ids(test_db, p)
    # v1 approves A, B; v2 approves A; v3 approves B, C; author abstains (no vote)
    _cast_approval(test_db, voter1, p, [oids[0], oids[1]])
    _cast_approval(test_db, voter2, p, [oids[0]])
    _cast_approval(test_db, voter3, p, [oids[1], oids[2]])
    test_db.commit()

    resp = client.get(f"/api/proposals/{p.id}/vote-graph", headers=_auth(author))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["voting_method"] == "approval"
    options_by_id = {o["id"]: o for o in data["options"]}
    assert options_by_id[oids[0]]["approval_count"] == 2  # A
    assert options_by_id[oids[1]]["approval_count"] == 2  # B
    assert options_by_id[oids[2]]["approval_count"] == 1  # C
    # first_pref_count is 0 for approval method
    assert all(o["first_pref_count"] == 0 for o in data["options"])
    # clusters.approval populated; clusters.binary/rcv null
    assert data["clusters"]["voting_method"] == "approval"
    assert data["clusters"]["approval"]["option_counts"][oids[0]] == 2
    assert sorted(data["clusters"]["approval"]["winners"]) == sorted([oids[0], oids[1]])
    assert data["clusters"]["binary"] is None
    assert data["clusters"]["rcv"] is None


def test_02_approval_graph_visible_and_anonymous_voter_ballots(client, test_db):
    """Phase 7C.1: ballots populated for ALL voters; only label is identity-gated.

    Privacy boundary: identity (label) hidden for anonymous voters; ballot
    content remains visible because it's already part of the aggregate
    per-option counts that everyone sees.
    """
    topic = _topic(test_db)
    viewer = _user(test_db, "viewer")
    public_dlg = _user(test_db, "public_dlg")
    anon = _user(test_db, "anon_voter")
    # Public delegate profile makes public_dlg visible.
    test_db.add(models.DelegateProfile(
        user_id=public_dlg.id, topic_id=topic.id, bio="", is_active=True,
    ))
    p = _approval_proposal(test_db, viewer, topic, labels=["A", "B"])
    oids = _option_ids(test_db, p)
    _cast_approval(test_db, public_dlg, p, [oids[0], oids[1]])
    _cast_approval(test_db, anon, p, [oids[0]])
    test_db.commit()

    resp = client.get(f"/api/proposals/{p.id}/vote-graph", headers=_auth(viewer))
    assert resp.status_code == 200
    graph = resp.json()
    pub_node = _node(graph, public_dlg.id)
    anon_node = _node(graph, anon.id)
    # Public delegate is visible: ballot present with approvals list, label populated.
    assert pub_node["label"] != ""
    assert pub_node["ballot"] is not None
    assert sorted(pub_node["ballot"]["approvals"]) == sorted([oids[0], oids[1]])
    # Anonymous voter: identity hidden but ballot visible (Phase 7C.1).
    assert anon_node["label"] == ""
    assert anon_node["ballot"] is not None
    assert anon_node["ballot"]["approvals"] == [oids[0]]


def test_03_rcv_graph_options_have_correct_first_pref_count(client, test_db):
    """RCV graph options carry first_pref_count from each ballot's first rank."""
    topic = _topic(test_db)
    author = _user(test_db, "author")
    v1 = _user(test_db, "v1")
    v2 = _user(test_db, "v2")
    v3 = _user(test_db, "v3")
    p = _rcv_proposal(test_db, author, topic, labels=["A", "B", "C"])
    oids = _option_ids(test_db, p)
    _cast_ranked(test_db, v1, p, [oids[0], oids[1]])  # 1st: A
    _cast_ranked(test_db, v2, p, [oids[0], oids[2]])  # 1st: A
    _cast_ranked(test_db, v3, p, [oids[1]])           # 1st: B
    test_db.commit()

    resp = client.get(f"/api/proposals/{p.id}/vote-graph", headers=_auth(author))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["voting_method"] == "ranked_choice"
    options_by_id = {o["id"]: o for o in data["options"]}
    assert options_by_id[oids[0]]["first_pref_count"] == 2
    assert options_by_id[oids[1]]["first_pref_count"] == 1
    assert options_by_id[oids[2]]["first_pref_count"] == 0
    # approval_count is 0 for RCV
    assert all(o["approval_count"] == 0 for o in data["options"])
    # clusters.rcv populated
    assert data["clusters"]["rcv"] is not None
    assert data["clusters"]["rcv"]["total_rounds"] >= 1


def test_04_rcv_graph_visible_voter_ballot_ranking_in_order(client, test_db):
    """Visible voter's ballot.ranking matches the cast rank order exactly."""
    topic = _topic(test_db)
    viewer = _user(test_db, "viewer")
    public_dlg = _user(test_db, "public_dlg")
    test_db.add(models.DelegateProfile(
        user_id=public_dlg.id, topic_id=topic.id, bio="", is_active=True,
    ))
    p = _rcv_proposal(test_db, viewer, topic, labels=["A", "B", "C"])
    oids = _option_ids(test_db, p)
    ordered = [oids[2], oids[0], oids[1]]  # C > A > B
    _cast_ranked(test_db, public_dlg, p, ordered)
    test_db.commit()

    resp = client.get(f"/api/proposals/{p.id}/vote-graph", headers=_auth(viewer))
    assert resp.status_code == 200
    graph = resp.json()
    pub_node = _node(graph, public_dlg.id)
    assert pub_node["ballot"] is not None
    assert pub_node["ballot"]["ranking"] == ordered  # order preserved


def test_05_tied_rcv_graph_winners_len_gt_one(client, test_db):
    """Final-round tie surfaces in clusters.rcv.winners with len > 1."""
    topic = _topic(test_db)
    author = _user(test_db, "author")
    v1 = _user(test_db, "v1")
    v2 = _user(test_db, "v2")
    p = _rcv_proposal(test_db, author, topic, labels=["A", "B"])
    oids = _option_ids(test_db, p)
    # 1 vote each — exact tie in IRV
    _cast_ranked(test_db, v1, p, [oids[0]])
    _cast_ranked(test_db, v2, p, [oids[1]])
    test_db.commit()

    resp = client.get(f"/api/proposals/{p.id}/vote-graph", headers=_auth(author))
    assert resp.status_code == 200
    data = resp.json()
    assert data["clusters"]["rcv"] is not None
    assert len(data["clusters"]["rcv"]["winners"]) > 1


def test_06_binary_graph_preserves_legacy_structure(client, test_db):
    """Binary graph keeps top-level yes/no/abstain dicts and mirrors them in clusters.binary."""
    topic = _topic(test_db)
    author = _user(test_db, "author")
    v_yes = _user(test_db, "v_yes")
    v_no = _user(test_db, "v_no")
    v_abs = _user(test_db, "v_abs")
    p = _binary_proposal(test_db, author, topic)
    _cast_binary(test_db, v_yes, p, "yes")
    _cast_binary(test_db, v_no, p, "no")
    _cast_binary(test_db, v_abs, p, "abstain")
    test_db.commit()

    resp = client.get(f"/api/proposals/{p.id}/vote-graph", headers=_auth(author))
    assert resp.status_code == 200
    data = resp.json()
    assert data["voting_method"] == "binary"
    # Legacy top-level fields populated
    c = data["clusters"]
    assert c["yes"]["count"] == 1
    assert c["no"]["count"] == 1
    assert c["abstain"]["count"] == 1
    # Author has no vote → counted as not_cast
    assert c["not_cast"]["count"] == 1
    # New nested binary block mirrors the legacy fields
    assert c["binary"] is not None
    assert c["binary"]["yes"]["count"] == 1
    assert c["binary"]["no"]["count"] == 1
    assert c["binary"]["abstain"]["count"] == 1
    # Other method blocks null; options list empty
    assert c["approval"] is None
    assert c["rcv"] is None
    assert data["options"] == []
    # Per-node ballot for binary uses vote_value
    yes_node = _node(data, v_yes.id)
    # Author is the current_user → visible
    author_node = _node(data, author.id)
    assert author_node["ballot"] is None  # author has no vote
    # v_yes is anonymous to author. Phase 7C.1: identity hidden, ballot visible.
    assert yes_node["label"] == ""
    assert yes_node["ballot"] is not None
    assert yes_node["ballot"]["vote_value"] == "yes"


def test_07_privacy_anonymous_voters_keep_ballots_label_redacted(client, test_db):
    """Phase 7C.1: anonymous voters keep ballot populated; only label is hidden.

    Identity (label) and ballot content are now two separate privacy boundaries.
    Ballot content stays visible because it's already part of the aggregate
    per-option counts that all viewers see; only the *who* is redacted.
    """
    topic = _topic(test_db)
    viewer = _user(test_db, "viewer")
    stranger = _user(test_db, "stranger")  # no follow / public-delegate / delegation
    p = _approval_proposal(test_db, viewer, topic, labels=["A", "B"])
    oids = _option_ids(test_db, p)
    _cast_approval(test_db, stranger, p, [oids[0]])
    test_db.commit()

    resp = client.get(f"/api/proposals/{p.id}/vote-graph", headers=_auth(viewer))
    assert resp.status_code == 200
    data = resp.json()
    stranger_node = _node(data, stranger.id)
    assert stranger_node["label"] == ""                 # identity hidden
    assert stranger_node["ballot"] is not None           # ballot remains visible
    assert stranger_node["ballot"]["approvals"] == [oids[0]]


def test_08_privacy_private_delegator_to_me_has_visible_ballot(client, test_db):
    """Voters who privately delegate to current user have visible ballots."""
    topic = _topic(test_db)
    viewer = _user(test_db, "viewer")  # current user
    follower = _user(test_db, "follower")  # privately delegates to viewer
    # Follower follows viewer with delegation_allowed permission.
    test_db.add(models.FollowRelationship(
        follower_id=follower.id,
        followed_id=viewer.id,
        permission_level="delegation_allowed",
    ))
    # And actually delegates to viewer (private delegation, no public profile).
    test_db.add(models.Delegation(
        delegator_id=follower.id,
        delegate_id=viewer.id,
        topic_id=None,
        chain_behavior="accept_sub",
    ))
    p = _approval_proposal(test_db, viewer, topic, labels=["A", "B"])
    oids = _option_ids(test_db, p)
    # Follower casts an approval ballot directly so we have a ballot to inspect.
    _cast_approval(test_db, follower, p, [oids[1]])
    test_db.commit()

    resp = client.get(f"/api/proposals/{p.id}/vote-graph", headers=_auth(viewer))
    assert resp.status_code == 200
    data = resp.json()
    follower_node = _node(data, follower.id)
    # Identity is revealed because they privately delegate to current user.
    assert follower_node["label"] == follower.display_name
    assert follower_node["ballot"] is not None
    assert follower_node["ballot"]["approvals"] == [oids[1]]


def test_09_proposal_results_votes_cast_correct_for_all_methods(client, test_db):
    """ProposalResults.votes_cast is populated for binary/approval/ranked_choice.

    Regression: phase 7 left this field as 0 for approval/RCV which made the
    proposal-list "0 of N votes cast" counter wrong.
    """
    topic = _topic(test_db)
    author = _user(test_db, "author")
    v1 = _user(test_db, "v1")
    v2 = _user(test_db, "v2")

    # Binary
    bp = _binary_proposal(test_db, author, topic)
    _cast_binary(test_db, v1, bp, "yes")
    _cast_binary(test_db, v2, bp, "no")
    # Approval
    ap = _approval_proposal(test_db, author, topic, labels=["A", "B"])
    aoids = _option_ids(test_db, ap)
    _cast_approval(test_db, v1, ap, [aoids[0]])
    _cast_approval(test_db, v2, ap, [aoids[1]])
    # RCV
    rp = _rcv_proposal(test_db, author, topic, labels=["A", "B"])
    roids = _option_ids(test_db, rp)
    _cast_ranked(test_db, v1, rp, [roids[0], roids[1]])
    _cast_ranked(test_db, v2, rp, [roids[1]])
    test_db.commit()

    for prop in (bp, ap, rp):
        resp = client.get(f"/api/proposals/{prop.id}/results", headers=_auth(author))
        assert resp.status_code == 200, f"{prop.voting_method}: {resp.text}"
        body = resp.json()
        assert body["votes_cast"] == 2, (
            f"votes_cast wrong for {prop.voting_method}: {body['votes_cast']} != 2"
        )
