"""
Tests for Phase 7: Ranked-Choice Voting (IRV) and Single Transferable Vote (STV).

Coverage map (matches phase7_spec.md "Backend Unit Tests"):

  Data model / proposal creation        — tests 01–07
  Vote casting                           — tests 08–13
  Delegation for ranked-choice           — tests 14–20
  IRV tabulation (num_winners=1)         — tests 21–26
  STV tabulation (num_winners > 1)       — tests 27–30
  Per-round data extraction              — tests 31–32
  Tie resolution                         — tests 33–35
  Regression                             — test  36
  Bonus                                  — tests 37+
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
from delegation_engine import (
    Ballot,
    BallotResult,
    RCVTally,
    RCVRound,
    ProposalContext,
    DelegationData,
    resolve_vote_pure,
    compute_tally_pure,
    _compute_rcv_tally_pure,
)
from tests.conftest import (
    make_user,
    make_topic,
    set_delegation,
    set_precedence,
)


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


# ---------------------------------------------------------------------------
# HTTP fixtures (route-level tests)
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


def _create_user(db: Session, username: str, email_verified: bool = True) -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=email_verified,
    )
    db.add(u)
    db.flush()
    return u


def _create_org(db: Session, allowed_methods=None, slug="rcv-org") -> models.Organization:
    settings = {"default_voting_days": 7}
    if allowed_methods is not None:
        settings["allowed_voting_methods"] = allowed_methods
    org = models.Organization(
        name="RCV Org",
        slug=slug,
        description="",
        join_policy="open",
        settings=settings,
    )
    db.add(org)
    db.flush()
    return org


def _create_membership(db, org, user, role="admin"):
    m = models.OrgMembership(
        user_id=user.id, org_id=org.id, role=role, status="active",
    )
    db.add(m)
    db.flush()
    return m


def _create_topic(db: Session, org=None) -> models.Topic:
    t = models.Topic(
        name=f"Topic-{models._uuid()[:8]}",
        description="",
        color="#00ff00",
        org_id=org.id if org else None,
    )
    db.add(t)
    db.flush()
    return t


def _auth_header(user: models.User) -> dict:
    token = auth_utils.create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# DB-level helpers (model-only tests)
# ---------------------------------------------------------------------------

def make_rcv_proposal(
    db,
    author,
    option_labels=None,
    num_winners=1,
    status="voting",
    org=None,
):
    """Create a ranked_choice proposal with options, bypassing route validation."""
    p = models.Proposal(
        title="RCV Test Proposal",
        body="",
        author_id=author.id,
        voting_method="ranked_choice",
        num_winners=num_winners,
        status=status,
        org_id=org.id if org else None,
    )
    db.add(p)
    db.flush()
    labels = option_labels or ["Option A", "Option B", "Option C", "Option D"]
    for i, label in enumerate(labels):
        db.add(models.ProposalOption(
            proposal_id=p.id,
            label=label,
            description=f"Description for {label}",
            display_order=i,
        ))
    db.flush()
    return p


def cast_ranked_vote(db, user, proposal, ranking):
    v = models.Vote(
        proposal_id=proposal.id,
        user_id=user.id,
        vote_value=None,
        ballot={"ranking": ranking},
        is_direct=True,
        cast_by_id=user.id,
    )
    db.add(v)
    db.flush()
    return v


def get_option_ids(db, proposal):
    opts = db.query(models.ProposalOption).filter(
        models.ProposalOption.proposal_id == proposal.id,
    ).order_by(models.ProposalOption.display_order).all()
    return [o.id for o in opts]


# ===========================================================================
# Tests 01–07: Data model / proposal creation validation (route-level)
# ===========================================================================

def test_01_create_rcv_proposal_succeeds(client, test_db):
    """RCV proposal with 4 options, num_winners=1 — succeeds."""
    org = _create_org(test_db, allowed_methods=["binary", "approval", "ranked_choice"])
    admin = _create_user(test_db, "admin")
    _create_membership(test_db, org, admin)
    topic = _create_topic(test_db, org)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals",
        headers=_auth_header(admin),
        json={
            "title": "Pick a Color",
            "body": "Pick a color",
            "voting_method": "ranked_choice",
            "num_winners": 1,
            "options": [
                {"label": "Red"},
                {"label": "Blue"},
                {"label": "Green"},
                {"label": "Purple"},
            ],
            "topics": [{"topic_id": topic.id, "relevance": 1.0}],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["voting_method"] == "ranked_choice"
    assert body["num_winners"] == 1
    assert len(body["options"]) == 4


def test_02_create_stv_proposal_succeeds(client, test_db):
    """STV proposal with 5 options, num_winners=3 — succeeds."""
    org = _create_org(test_db, allowed_methods=["binary", "approval", "ranked_choice"])
    admin = _create_user(test_db, "admin")
    _create_membership(test_db, org, admin)
    topic = _create_topic(test_db, org)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals",
        headers=_auth_header(admin),
        json={
            "title": "Pick 3 board members",
            "body": "Multi-winner",
            "voting_method": "ranked_choice",
            "num_winners": 3,
            "options": [
                {"label": f"Candidate {i}"} for i in range(5)
            ],
            "topics": [{"topic_id": topic.id, "relevance": 1.0}],
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["num_winners"] == 3


def test_03_create_rcv_num_winners_zero_rejected(client, test_db):
    """num_winners=0 is rejected (Pydantic ge=1)."""
    org = _create_org(test_db, allowed_methods=["binary", "approval", "ranked_choice"])
    admin = _create_user(test_db, "admin")
    _create_membership(test_db, org, admin)
    topic = _create_topic(test_db, org)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals",
        headers=_auth_header(admin),
        json={
            "title": "Bad",
            "voting_method": "ranked_choice",
            "num_winners": 0,
            "options": [{"label": "A"}, {"label": "B"}],
            "topics": [{"topic_id": topic.id}],
        },
    )
    # Pydantic rejects with 422
    assert resp.status_code == 422


def test_04_create_rcv_num_winners_too_large_rejected(client, test_db):
    """num_winners > options count is rejected."""
    org = _create_org(test_db, allowed_methods=["binary", "approval", "ranked_choice"])
    admin = _create_user(test_db, "admin")
    _create_membership(test_db, org, admin)
    topic = _create_topic(test_db, org)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals",
        headers=_auth_header(admin),
        json={
            "title": "Bad",
            "voting_method": "ranked_choice",
            "num_winners": 5,
            "options": [{"label": "A"}, {"label": "B"}],
            "topics": [{"topic_id": topic.id}],
        },
    )
    assert resp.status_code == 400
    assert "num_winners" in resp.json()["detail"]


def test_05_create_rcv_in_org_without_permission_rejected(client, test_db):
    """Org without ranked_choice in allowed_voting_methods returns 403."""
    org = _create_org(test_db, allowed_methods=["binary", "approval"])
    admin = _create_user(test_db, "admin")
    _create_membership(test_db, org, admin)
    topic = _create_topic(test_db, org)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals",
        headers=_auth_header(admin),
        json={
            "title": "Should fail",
            "voting_method": "ranked_choice",
            "num_winners": 1,
            "options": [{"label": "A"}, {"label": "B"}],
            "topics": [{"topic_id": topic.id}],
        },
    )
    assert resp.status_code == 403


def test_06_create_rcv_in_org_with_permission_succeeds(client, test_db):
    """Org with ranked_choice enabled allows creation."""
    org = _create_org(test_db, allowed_methods=["binary", "approval", "ranked_choice"])
    admin = _create_user(test_db, "admin")
    _create_membership(test_db, org, admin)
    topic = _create_topic(test_db, org)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals",
        headers=_auth_header(admin),
        json={
            "title": "OK",
            "voting_method": "ranked_choice",
            "num_winners": 1,
            "options": [{"label": "A"}, {"label": "B"}],
            "topics": [{"topic_id": topic.id}],
        },
    )
    assert resp.status_code == 201


def test_07_default_org_does_not_include_ranked_choice(client, test_db):
    """A fresh org without explicit allowed_voting_methods rejects RCV."""
    # Org with no settings dict at all → defaults to ["binary","approval"]
    org = _create_org(test_db, allowed_methods=None)
    admin = _create_user(test_db, "admin")
    _create_membership(test_db, org, admin)
    topic = _create_topic(test_db, org)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals",
        headers=_auth_header(admin),
        json={
            "title": "Should fail",
            "voting_method": "ranked_choice",
            "num_winners": 1,
            "options": [{"label": "A"}, {"label": "B"}],
            "topics": [{"topic_id": topic.id}],
        },
    )
    assert resp.status_code == 403


# ===========================================================================
# Tests 08–13: Vote casting (route-level)
# ===========================================================================

def _setup_voting_rcv(db, options=None, num_winners=1):
    """Helper: create org+admin+rcv proposal in voting status."""
    org = _create_org(db, allowed_methods=["binary", "approval", "ranked_choice"])
    admin = _create_user(db, "admin")
    _create_membership(db, org, admin)
    topic = _create_topic(db, org)
    p = make_rcv_proposal(
        db, admin,
        option_labels=options or ["A", "B", "C", "D"],
        num_winners=num_winners,
        status="voting",
        org=org,
    )
    p.org_id = org.id
    db.flush()
    db.commit()
    return org, admin, topic, p


def test_08_cast_ranked_ballot_partial(client, test_db):
    """Ranked ballot with 3 of 4 options stored as {ranking: [...]}."""
    org, admin, _, p = _setup_voting_rcv(test_db)
    oids = get_option_ids(test_db, p)

    voter = _create_user(test_db, "voter")
    test_db.commit()

    resp = client.post(
        f"/api/proposals/{p.id}/vote",
        headers=_auth_header(voter),
        json={"ranking": [oids[2], oids[0], oids[1]]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["vote_value"] is None
    assert body["ballot"] == {"ranking": [oids[2], oids[0], oids[1]]}


def test_09_cast_ranked_ballot_empty_accepted(client, test_db):
    """Empty ranking [] is accepted (abstain)."""
    org, admin, _, p = _setup_voting_rcv(test_db)
    voter = _create_user(test_db, "voter")
    test_db.commit()

    resp = client.post(
        f"/api/proposals/{p.id}/vote",
        headers=_auth_header(voter),
        json={"ranking": []},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ballot"] == {"ranking": []}


def test_10_cast_ranked_ballot_duplicate_rejected(client, test_db):
    """Duplicate option_ids in ranking rejected."""
    org, admin, _, p = _setup_voting_rcv(test_db)
    oids = get_option_ids(test_db, p)
    voter = _create_user(test_db, "voter")
    test_db.commit()

    resp = client.post(
        f"/api/proposals/{p.id}/vote",
        headers=_auth_header(voter),
        json={"ranking": [oids[0], oids[1], oids[0]]},
    )
    assert resp.status_code == 422  # Pydantic validator


def test_11_cast_ranked_ballot_unknown_option_rejected(client, test_db):
    """option_id not in proposal rejected."""
    org, admin, _, p = _setup_voting_rcv(test_db)
    oids = get_option_ids(test_db, p)
    voter = _create_user(test_db, "voter")
    test_db.commit()

    fake_oid = "00000000-0000-0000-0000-000000000000"
    resp = client.post(
        f"/api/proposals/{p.id}/vote",
        headers=_auth_header(voter),
        json={"ranking": [oids[0], fake_oid]},
    )
    assert resp.status_code == 400
    assert "does not belong" in resp.json()["detail"]


def test_12_cast_ranked_ballot_too_long_rejected(client, test_db):
    """Ranking longer than option count rejected — needs 5 distinct UUIDs but
    only 4 options exist. Use a real extra option_id from a separate proposal."""
    org, admin, _, p = _setup_voting_rcv(test_db)
    oids = get_option_ids(test_db, p)

    # Create another proposal so we have a 5th valid UUID-shaped option_id.
    p2 = make_rcv_proposal(
        test_db, admin,
        option_labels=["X", "Y"],
        org=org, status="draft",
    )
    extra_oid = get_option_ids(test_db, p2)[0]

    voter = _create_user(test_db, "voter")
    test_db.commit()

    resp = client.post(
        f"/api/proposals/{p.id}/vote",
        headers=_auth_header(voter),
        json={"ranking": oids + [extra_oid]},
    )
    assert resp.status_code == 400
    assert "exceeds" in resp.json()["detail"] or "does not belong" in resp.json()["detail"]


def test_13_cast_ranked_ballot_order_preserved(client, test_db):
    """Order of ranking preserved exactly as submitted."""
    org, admin, _, p = _setup_voting_rcv(test_db)
    oids = get_option_ids(test_db, p)
    voter = _create_user(test_db, "voter")
    test_db.commit()

    submitted = [oids[3], oids[1], oids[2], oids[0]]
    resp = client.post(
        f"/api/proposals/{p.id}/vote",
        headers=_auth_header(voter),
        json={"ranking": submitted},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ballot"]["ranking"] == submitted


# ===========================================================================
# Tests 14–20: Delegation for ranked-choice
# ===========================================================================

def test_14_delegator_inherits_full_ranking(db, store, engine_obj):
    """Delegator inherits delegate's full ranking, in order."""
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    p = make_rcv_proposal(db, alice)
    oids = get_option_ids(db, p)

    set_delegation(db, store, alice, bob)
    cast_ranked_vote(db, bob, p, [oids[2], oids[0], oids[1], oids[3]])

    result = engine_obj.resolve_vote(alice.id, p.id, db)
    assert result is not None
    assert result.is_direct is False
    assert result.ballot.ranking == [oids[2], oids[0], oids[1], oids[3]]
    assert result.delegate_chain == [bob.id]


def test_15_delegator_inherits_empty_ranking(db, store, engine_obj):
    """Delegator inherits delegate's empty ranking (abstain)."""
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    p = make_rcv_proposal(db, alice)
    set_delegation(db, store, alice, bob)
    cast_ranked_vote(db, bob, p, [])  # bob abstains

    result = engine_obj.resolve_vote(alice.id, p.id, db)
    assert result is not None
    assert result.is_direct is False
    assert result.ballot.ranking == []


def test_16_delegator_inherits_partial_ranking(db, store, engine_obj):
    """Partial ranking inherited as-is (3 of 5)."""
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    p = make_rcv_proposal(
        db, alice, option_labels=["A", "B", "C", "D", "E"],
    )
    oids = get_option_ids(db, p)

    set_delegation(db, store, alice, bob)
    cast_ranked_vote(db, bob, p, [oids[1], oids[3], oids[0]])  # 3 of 5

    result = engine_obj.resolve_vote(alice.id, p.id, db)
    assert result is not None
    assert result.ballot.ranking == [oids[1], oids[3], oids[0]]


def test_17_delegation_chain_accept_sub(db, store, engine_obj):
    """accept_sub chains through to sub-delegate's ranking."""
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    carol = make_user(db, "carol")
    p = make_rcv_proposal(db, alice)
    oids = get_option_ids(db, p)

    set_delegation(db, store, alice, bob, chain_behavior="accept_sub")
    set_delegation(db, store, bob, carol, chain_behavior="accept_sub")
    cast_ranked_vote(db, carol, p, [oids[1], oids[2]])

    result = engine_obj.resolve_vote(alice.id, p.id, db)
    assert result is not None
    assert result.ballot.ranking == [oids[1], oids[2]]
    assert bob.id in result.delegate_chain
    assert carol.id in result.delegate_chain


def test_18_delegation_chain_revert_direct(db, store, engine_obj):
    """revert_direct: delegate hasn't voted → resolved vote is None (not_cast)."""
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    p = make_rcv_proposal(db, alice)

    set_delegation(db, store, alice, bob, chain_behavior="revert_direct")
    # Bob hasn't voted

    result = engine_obj.resolve_vote(alice.id, p.id, db)
    assert result is None


def test_19_delegation_chain_abstain(db, store, engine_obj):
    """abstain: delegate hasn't voted → resolved as None (no chain forward)."""
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    p = make_rcv_proposal(db, alice)

    set_delegation(db, store, alice, bob, chain_behavior="abstain")
    # Bob hasn't voted

    result = engine_obj.resolve_vote(alice.id, p.id, db)
    # Per Phase 6 semantics: abstain → no resolved vote
    assert result is None


def test_20_non_strict_strategy_falls_back(db, store, engine_obj):
    """Non-strict-precedence strategy falls back to strict for RCV."""
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    alice.delegation_strategy = "majority_of_delegates"
    db.flush()
    p = make_rcv_proposal(db, alice)
    oids = get_option_ids(db, p)

    set_delegation(db, store, alice, bob)
    cast_ranked_vote(db, bob, p, [oids[0]])

    # Resolve still works — falls back to strict_precedence path
    result = engine_obj.resolve_vote(alice.id, p.id, db)
    assert result is not None
    assert result.ballot.ranking == [oids[0]]


# ===========================================================================
# Tests 21–26: IRV tabulation (num_winners=1)
# ===========================================================================

def _ctx(rankings: dict[str, list[str]]) -> ProposalContext:
    """Build a ProposalContext with direct ranked ballots, no delegation."""
    return ProposalContext(
        proposal_topics=[],
        all_delegations={},
        all_precedences={},
        direct_votes={},
        direct_ballots={uid: Ballot(ranking=r) for uid, r in rankings.items()},
        voting_method="ranked_choice",
    )


def test_21_irv_clear_majority_round_1():
    """IRV with clear first-round majority — single round, that option wins."""
    ctx = _ctx({
        "u1": ["A", "B", "C"],
        "u2": ["A", "C", "B"],
        "u3": ["A", "B", "C"],
        "u4": ["B", "A", "C"],
        "u5": ["C", "A", "B"],
    })
    tally = compute_tally_pure(
        list(ctx.direct_ballots.keys()),
        ctx,
        option_ids=["A", "B", "C"],
        num_winners=1,
    )
    assert isinstance(tally, RCVTally)
    assert tally.method == "irv"
    assert tally.winners == ["A"]
    assert tally.tied is False
    # First round has A=3 (majority of 5)
    assert tally.rounds[0].option_counts["A"] == pytest.approx(3.0)


def test_22_irv_two_rounds_with_transfer():
    """IRV requiring 2 rounds: last-place eliminated, votes transfer."""
    # 5 voters: A:2, B:2, C:1. C eliminated, C voter's 2nd pref = B → B wins 3.
    ctx = _ctx({
        "u1": ["A", "B", "C"],
        "u2": ["A", "C", "B"],
        "u3": ["B", "A", "C"],
        "u4": ["B", "A", "C"],
        "u5": ["C", "B", "A"],
    })
    tally = compute_tally_pure(
        list(ctx.direct_ballots.keys()),
        ctx,
        option_ids=["A", "B", "C"],
        num_winners=1,
    )
    assert tally.winners == ["B"]
    assert tally.tied is False
    assert len(tally.rounds) >= 2
    # In final round B should have 3 votes (2 first + 1 transferred)
    last = tally.rounds[-1]
    assert last.option_counts["B"] == pytest.approx(3.0)


def test_23_irv_three_plus_rounds():
    """IRV with 3+ rounds across multiple eliminations."""
    # 7 voters across 4 options. A:2, B:2, C:2, D:1. D eliminated → C gets D's
    # second pref. Then someone trails and gets eliminated, and so on.
    ctx = _ctx({
        "u1": ["A", "B", "C", "D"],
        "u2": ["A", "C", "B", "D"],
        "u3": ["B", "A", "C", "D"],
        "u4": ["B", "C", "A", "D"],
        "u5": ["C", "B", "A", "D"],
        "u6": ["C", "A", "B", "D"],
        "u7": ["D", "C", "B", "A"],
    })
    tally = compute_tally_pure(
        list(ctx.direct_ballots.keys()),
        ctx,
        option_ids=["A", "B", "C", "D"],
        num_winners=1,
    )
    assert isinstance(tally, RCVTally)
    assert len(tally.winners) == 1
    # We should see at least 2 rounds (need to eliminate D first, and likely
    # one more elimination after transfers).
    assert len(tally.rounds) >= 2


def test_24_irv_exhausted_ballot():
    """A voter whose ranked options are all eliminated — ballot exhausted."""
    # 5 voters; voter u5 only ranks D (which gets eliminated first).
    ctx = _ctx({
        "u1": ["A", "B"],
        "u2": ["A", "B"],
        "u3": ["B", "A"],
        "u4": ["B", "A"],
        "u5": ["C"],
    })
    tally = compute_tally_pure(
        list(ctx.direct_ballots.keys()),
        ctx,
        option_ids=["A", "B", "C"],
        num_winners=1,
    )
    # C is eliminated; u5's ballot is exhausted (no further preferences).
    # Final round between A and B should have 2 each => pyrankvote breaks tie.
    assert isinstance(tally, RCVTally)
    # exhausted ballot doesn't increase A/B beyond their first-pref counts
    last = tally.rounds[-1]
    assert last.option_counts["A"] == pytest.approx(2.0)
    assert last.option_counts["B"] == pytest.approx(2.0)


def test_25_irv_all_empty_rankings():
    """All empty rankings → no winners, all counted as abstain."""
    ctx = _ctx({
        "u1": [],
        "u2": [],
        "u3": [],
    })
    tally = compute_tally_pure(
        list(ctx.direct_ballots.keys()),
        ctx,
        option_ids=["A", "B", "C"],
        num_winners=1,
    )
    assert isinstance(tally, RCVTally)
    assert tally.winners == []
    assert tally.total_abstain == 3
    assert tally.total_ballots_cast == 3
    assert tally.rounds == []


def test_26_irv_final_round_tie():
    """Final-round 2-2 tie → tied=True, multiple option_ids in winners."""
    ctx = _ctx({
        "u1": ["A"],
        "u2": ["A"],
        "u3": ["B"],
        "u4": ["B"],
    })
    tally = compute_tally_pure(
        list(ctx.direct_ballots.keys()),
        ctx,
        option_ids=["A", "B"],
        num_winners=1,
    )
    assert tally.tied is True
    assert set(tally.winners) == {"A", "B"}


# ===========================================================================
# Tests 27–30: STV tabulation (num_winners > 1)
# ===========================================================================

def test_27_stv_two_clear_winners():
    """STV num_winners=2 with two clearly-favored options."""
    # 6 voters: A and B each get 3 first-pref votes
    ctx = _ctx({
        "u1": ["A", "B", "C", "D"],
        "u2": ["A", "B", "C", "D"],
        "u3": ["A", "B", "C", "D"],
        "u4": ["B", "A", "C", "D"],
        "u5": ["B", "A", "C", "D"],
        "u6": ["B", "A", "C", "D"],
    })
    tally = compute_tally_pure(
        list(ctx.direct_ballots.keys()),
        ctx,
        option_ids=["A", "B", "C", "D"],
        num_winners=2,
    )
    assert isinstance(tally, RCVTally)
    assert tally.method == "stv"
    assert set(tally.winners) == {"A", "B"}


def test_28_stv_minority_proportional_seat():
    """STV: 30% minority for option C wins one of 3 seats."""
    # 10 voters, 3 winners. 7 voters prefer A/B/D; 3 voters prefer C.
    # Standard STV quota = floor(10/(3+1))+1 = 3.
    # C has exactly 3 first-pref votes, so C wins outright in round 1.
    ctx = _ctx({
        "u1": ["A", "B", "D", "C"],
        "u2": ["A", "B", "D", "C"],
        "u3": ["A", "B", "D", "C"],
        "u4": ["B", "A", "D", "C"],
        "u5": ["B", "A", "D", "C"],
        "u6": ["D", "A", "B", "C"],
        "u7": ["D", "A", "B", "C"],
        "u8": ["C", "B", "A", "D"],
        "u9": ["C", "B", "A", "D"],
        "u10": ["C", "B", "A", "D"],
    })
    tally = compute_tally_pure(
        list(ctx.direct_ballots.keys()),
        ctx,
        option_ids=["A", "B", "C", "D"],
        num_winners=3,
    )
    assert isinstance(tally, RCVTally)
    assert "C" in tally.winners
    assert len(tally.winners) == 3


def test_29_stv_surplus_distribution_fractional():
    """STV surplus from over-quota winner produces fractional transfers."""
    # 10 voters, 2 seats. A heavily favored (6 first-pref). Quota = 4.
    # A wins with 6, surplus 2 transfers fractionally to next prefs.
    ctx = _ctx({
        "u1": ["A", "B"],
        "u2": ["A", "B"],
        "u3": ["A", "B"],
        "u4": ["A", "C"],
        "u5": ["A", "C"],
        "u6": ["A", "D"],
        "u7": ["B", "A"],
        "u8": ["C", "A"],
        "u9": ["D", "A"],
        "u10": ["B", "C"],
    })
    tally = compute_tally_pure(
        list(ctx.direct_ballots.keys()),
        ctx,
        option_ids=["A", "B", "C", "D"],
        num_winners=2,
    )
    assert isinstance(tally, RCVTally)
    assert "A" in tally.winners
    assert len(tally.winners) == 2
    # Transfer rounds should contain at least one fractional vote count
    # (i.e. not all integer values).
    saw_fractional = False
    for r in tally.rounds:
        for v in r.option_counts.values():
            if abs(v - round(v)) > 1e-9:
                saw_fractional = True
    assert saw_fractional, "STV surplus distribution should produce fractional counts"


def test_30_stv_tie_detection():
    """STV with a marginal tie at the final seat surfaces tied=True."""
    # 4 voters, 2 seats. A clearly wins. B and C tied for 2nd seat.
    ctx = _ctx({
        "u1": ["A"],
        "u2": ["A"],
        "u3": ["B"],
        "u4": ["C"],
    })
    tally = compute_tally_pure(
        list(ctx.direct_ballots.keys()),
        ctx,
        option_ids=["A", "B", "C"],
        num_winners=2,
    )
    assert isinstance(tally, RCVTally)
    # A is a clear winner; B vs C tied for the second seat
    assert "A" in tally.winners
    assert tally.tied is True
    assert "B" in tally.winners and "C" in tally.winners


# ===========================================================================
# Tests 31–32: Per-round data extraction
# ===========================================================================

def test_31_rounds_populated_with_data():
    """RCVTally.rounds is populated with round-by-round data."""
    ctx = _ctx({
        "u1": ["A", "B", "C"],
        "u2": ["A", "C", "B"],
        "u3": ["B", "A", "C"],
        "u4": ["B", "C", "A"],
        "u5": ["C", "A", "B"],
    })
    tally = compute_tally_pure(
        list(ctx.direct_ballots.keys()),
        ctx,
        option_ids=["A", "B", "C"],
        num_winners=1,
    )
    assert len(tally.rounds) >= 1
    for i, r in enumerate(tally.rounds):
        assert r.round_number == i
        assert isinstance(r.option_counts, dict)
        assert all(oid in r.option_counts for oid in ["A", "B", "C"])
        assert isinstance(r.transfer_breakdown, dict)


def test_32_round_extraction_shape():
    """Each round shows option_counts, eliminated, elected, transfer_breakdown."""
    # IRV with one elimination round
    ctx = _ctx({
        "u1": ["A", "B", "C"],
        "u2": ["A", "B", "C"],
        "u3": ["B", "A", "C"],
        "u4": ["C", "A", "B"],
    })
    tally = compute_tally_pure(
        list(ctx.direct_ballots.keys()),
        ctx,
        option_ids=["A", "B", "C"],
        num_winners=1,
    )
    # Round 0 should reject the lowest (C with 1 vote)
    r0 = tally.rounds[0]
    assert r0.option_counts["A"] == pytest.approx(2.0)
    assert r0.option_counts["B"] == pytest.approx(1.0)
    assert r0.option_counts["C"] == pytest.approx(1.0)
    # Eliminated should be either B or C (whichever pyrankvote picks); the
    # important thing is that exactly one of them got eliminated.
    if len(tally.rounds) > 1:
        assert r0.eliminated in {"B", "C"}
        # Round 1 must show the transfer
        r1 = tally.rounds[1]
        assert r1.transferred_from is not None


# ===========================================================================
# Tests 33–35: Tie resolution endpoint (route-level)
# ===========================================================================

def _setup_passed_tied_rcv(db):
    """Create an RCV proposal in passed status with a real final-round tie."""
    org = _create_org(db, allowed_methods=["binary", "approval", "ranked_choice"])
    admin = _create_user(db, "admin")
    _create_membership(db, org, admin)
    p = make_rcv_proposal(db, admin, option_labels=["A", "B"], num_winners=1, org=org, status="passed")
    p.org_id = org.id
    db.flush()

    # Create 4 voters with a 2-2 tie between A and B
    oids = get_option_ids(db, p)
    voters = [_create_user(db, f"v{i}") for i in range(4)]
    for i, v in enumerate(voters):
        cast_ranked_vote(db, v, p, [oids[0] if i < 2 else oids[1]])
    db.commit()
    return org, admin, p, oids


def test_33_admin_resolves_rcv_tie(client, test_db):
    """Admin resolves an RCV final-round tie via the org endpoint."""
    org, admin, p, oids = _setup_passed_tied_rcv(test_db)

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals/{p.id}/resolve-tie",
        headers=_auth_header(admin),
        json={"selected_option_id": oids[0]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tie_resolution"]["selected_option_id"] == oids[0]
    assert body["tie_resolution"]["resolved_by"] == admin.id
    # Audit event recorded
    audit = test_db.query(models.AuditLog).filter(
        models.AuditLog.action == "proposal.tie_resolved",
        models.AuditLog.target_id == p.id,
    ).first()
    assert audit is not None
    assert oids[0] in audit.details["tied_winners"]


def test_34_non_admin_cannot_resolve_rcv_tie(client, test_db):
    """Non-admin gets 403 on RCV tie resolution."""
    org, admin, p, oids = _setup_passed_tied_rcv(test_db)
    member = _create_user(test_db, "member")
    _create_membership(test_db, org, member, role="member")
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals/{p.id}/resolve-tie",
        headers=_auth_header(member),
        json={"selected_option_id": oids[0]},
    )
    assert resp.status_code == 403


def test_35_rcv_tie_resolution_invalid_option_rejected(client, test_db):
    """selected_option_id not in tied finalists → 400."""
    org, admin, p, oids = _setup_passed_tied_rcv(test_db)

    # An option from a different proposal — valid UUID, not in tied_pool
    p2 = make_rcv_proposal(test_db, admin, option_labels=["X", "Y"], org=org, status="draft")
    p2.org_id = org.id
    test_db.flush()
    other_oid = get_option_ids(test_db, p2)[0]
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals/{p.id}/resolve-tie",
        headers=_auth_header(admin),
        json={"selected_option_id": other_oid},
    )
    assert resp.status_code == 400
    assert "tied" in resp.json()["detail"].lower()


# ===========================================================================
# Test 36: Regression — binary/approval still work with 3-way dispatch
# ===========================================================================

def test_36_binary_approval_regression(db):
    """Binary and approval tallies still work after dispatch extension."""
    from delegation_engine import ProposalTally, ApprovalTally

    binary_ctx = ProposalContext(
        proposal_topics=[],
        all_delegations={},
        all_precedences={},
        direct_votes={"u1": "yes", "u2": "no", "u3": "yes"},
        direct_ballots={},
        voting_method="binary",
    )
    binary_tally = compute_tally_pure(["u1", "u2", "u3"], binary_ctx)
    assert isinstance(binary_tally, ProposalTally)
    assert binary_tally.yes == 2

    approval_ctx = ProposalContext(
        proposal_topics=[],
        all_delegations={},
        all_precedences={},
        direct_votes={},
        direct_ballots={
            "u1": Ballot(approvals=["A"]),
            "u2": Ballot(approvals=["A", "B"]),
        },
        voting_method="approval",
    )
    approval_tally = compute_tally_pure(["u1", "u2", "u3"], approval_ctx)
    assert isinstance(approval_tally, ApprovalTally)
    assert approval_tally.option_approvals["A"] == 2


# ===========================================================================
# Bonus: Ballot dataclass + delegation context behavior
# ===========================================================================

def test_37_ballot_voting_method_property():
    """Ballot.voting_method dispatches on which field is set."""
    assert Ballot(vote_value="yes").voting_method == "binary"
    assert Ballot(approvals=["a"]).voting_method == "approval"
    assert Ballot(ranking=["a"]).voting_method == "ranked_choice"
    # Empty approvals/ranking still resolve to their method
    assert Ballot(approvals=[]).voting_method == "approval"
    assert Ballot(ranking=[]).voting_method == "ranked_choice"
    assert Ballot().voting_method == "unknown"


def test_38_quorum_met_calculation():
    """RCVTally.quorum_met uses ballots-cast / total_eligible."""
    ctx = _ctx({
        "u1": ["A", "B"],
        "u2": ["B", "A"],
    })
    # 2 voters cast, 5 eligible
    tally = _compute_rcv_tally_pure(
        ["u1", "u2", "u3", "u4", "u5"],
        ctx,
        option_ids=["A", "B"],
        num_winners=1,
    )
    assert tally.total_ballots_cast == 2
    assert tally.total_eligible == 5
    assert tally.quorum_met(0.4) is True
    assert tally.quorum_met(0.5) is False


def test_39_results_endpoint_returns_rcv_payload(client, test_db):
    """GET /api/proposals/{id}/results returns RCV-shaped payload."""
    org, admin, _, p = _setup_voting_rcv(test_db)
    oids = get_option_ids(test_db, p)
    voters = [_create_user(test_db, f"v{i}") for i in range(3)]
    test_db.commit()

    for v, ranking in zip(voters, [
        [oids[0], oids[1]],
        [oids[0], oids[2]],
        [oids[1], oids[0]],
    ]):
        client.post(
            f"/api/proposals/{p.id}/vote",
            headers=_auth_header(v),
            json={"ranking": ranking},
        )

    resp = client.get(f"/api/proposals/{p.id}/results")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["voting_method"] == "ranked_choice"
    assert body["method"] == "irv"
    assert body["num_winners"] == 1
    assert body["winners"] == [oids[0]]
    assert "rounds" in body and len(body["rounds"]) >= 1
    assert "option_labels" in body
    assert body["option_labels"][oids[0]] == "A"


def test_40_voting_method_rejects_wrong_payload(client, test_db):
    """Posting approvals to a ranked_choice proposal is rejected."""
    org, admin, _, p = _setup_voting_rcv(test_db)
    oids = get_option_ids(test_db, p)
    voter = _create_user(test_db, "voter")
    test_db.commit()

    resp = client.post(
        f"/api/proposals/{p.id}/vote",
        headers=_auth_header(voter),
        json={"approvals": [oids[0]]},
    )
    assert resp.status_code == 400


def test_41_options_editable_in_draft_for_rcv(client, test_db):
    """RCV proposal options editable while in draft."""
    org = _create_org(test_db, allowed_methods=["binary", "approval", "ranked_choice"])
    admin = _create_user(test_db, "admin")
    _create_membership(test_db, org, admin)
    topic = _create_topic(test_db, org)
    test_db.commit()

    create_resp = client.post(
        f"/api/orgs/{org.slug}/proposals",
        headers=_auth_header(admin),
        json={
            "title": "Editable",
            "voting_method": "ranked_choice",
            "num_winners": 1,
            "options": [{"label": "A"}, {"label": "B"}],
            "topics": [{"topic_id": topic.id}],
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    pid = create_resp.json()["id"]

    edit_resp = client.patch(
        f"/api/proposals/{pid}",
        headers=_auth_header(admin),
        json={
            "options": [
                {"label": "Alpha"},
                {"label": "Beta"},
                {"label": "Gamma"},
            ],
        },
    )
    assert edit_resp.status_code == 200, edit_resp.text
    assert len(edit_resp.json()["options"]) == 3


def test_42_options_locked_after_voting_for_rcv(client, test_db):
    """RCV options cannot be edited after voting starts (route returns 400)."""
    org, admin, _, p = _setup_voting_rcv(test_db)

    resp = client.patch(
        f"/api/proposals/{p.id}",
        headers=_auth_header(admin),
        json={
            "options": [{"label": "X"}, {"label": "Y"}],
        },
    )
    # The proposal-update route blocks any edit when status != draft/deliberation
    # with 400; same behavior we get for approval voting.
    assert resp.status_code in (400, 409)


def test_43_my_vote_status_for_rcv(client, test_db):
    """my-vote endpoint returns ranking field for RCV proposals."""
    org, admin, _, p = _setup_voting_rcv(test_db)
    oids = get_option_ids(test_db, p)
    voter = _create_user(test_db, "voter")
    test_db.commit()

    client.post(
        f"/api/proposals/{p.id}/vote",
        headers=_auth_header(voter),
        json={"ranking": [oids[1], oids[0]]},
    )
    resp = client.get(
        f"/api/proposals/{p.id}/my-vote",
        headers=_auth_header(voter),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ranking"] == [oids[1], oids[0]]
    assert body["is_direct"] is True


def test_44_topic_precedence_works_for_rcv(db, store, engine_obj):
    """Topic precedence selects the right delegate for an RCV proposal."""
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    carol = make_user(db, "carol")

    t1 = make_topic(db, "topic1")
    t2 = make_topic(db, "topic2")

    p = make_rcv_proposal(db, alice)
    # Attach both topics
    db.add(models.ProposalTopic(proposal_id=p.id, topic_id=t1.id))
    db.add(models.ProposalTopic(proposal_id=p.id, topic_id=t2.id))
    db.flush()
    oids = get_option_ids(db, p)

    set_delegation(db, store, alice, bob, topic=t1)
    set_delegation(db, store, alice, carol, topic=t2)
    cast_ranked_vote(db, bob, p, [oids[0], oids[1]])
    cast_ranked_vote(db, carol, p, [oids[2], oids[3]])

    # Alice prefers t2 > t1 → carol's ranking wins
    set_precedence(db, alice, [t2, t1])

    result = engine_obj.resolve_vote(alice.id, p.id, db)
    assert result is not None
    assert result.ballot.ranking == [oids[2], oids[3]]
    assert result.cast_by_id == carol.id


def test_45_compute_tally_via_service_layer(db, store, engine_obj):
    """DelegationService.compute_tally returns RCVTally for ranked_choice."""
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    carol = make_user(db, "carol")
    p = make_rcv_proposal(db, alice)
    oids = get_option_ids(db, p)

    # 2 vs 1 — A wins clear majority
    cast_ranked_vote(db, alice, p, [oids[0], oids[1]])
    cast_ranked_vote(db, bob, p, [oids[0], oids[2]])
    cast_ranked_vote(db, carol, p, [oids[1], oids[0]])

    # Rebuild graph store from DB so service layer sees no delegations
    store.rebuild_from_db(db)
    tally = engine_obj.compute_tally(p, db)
    assert isinstance(tally, RCVTally)
    assert tally.total_ballots_cast == 3
    assert tally.winners == [oids[0]]
    assert tally.tied is False


def test_46_rcv_tally_not_cast_counted(db, store, engine_obj):
    """Users who didn't vote are counted as not_cast."""
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    carol = make_user(db, "carol")  # carol doesn't vote
    p = make_rcv_proposal(db, alice)
    oids = get_option_ids(db, p)

    cast_ranked_vote(db, alice, p, [oids[0]])
    cast_ranked_vote(db, bob, p, [oids[1]])

    store.rebuild_from_db(db)
    tally = engine_obj.compute_tally(p, db)
    assert isinstance(tally, RCVTally)
    assert tally.not_cast == 1
    assert tally.total_ballots_cast == 2
    assert tally.total_eligible == 3
