"""Phase 72c — unmatched topic is warn-and-drop, not a blocking error.

Section A (backend): in `_resolve_import_topics`, topic-not-found (both
`topic_name` and `topic_id`) is downgraded from a blocking error to a
warning — the unmatched topic is dropped and the proposal imports with
whatever topics DID match. Structural topic errors ('topics' not a list,
entry missing both id+name, non-dict entry) stay blocking.

The load-bearing regression test is `test_housing_file_yields_three_valid`:
Z's real `import_housing_proposals.json` (3 proposals tagging a "Housing"
topic the org lacks) must yield 3 VALID warned items, not 3 invalid ones.

Style mirrors test_phase_72_multi_proposal_import.py.
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


def _make_user(db, username) -> models.User:
    u = models.User(
        username=username, display_name=username, password_hash=_DUMMY_HASH,
        email=f"{username}@test.example", email_verified=True,
    )
    db.add(u)
    db.flush()
    return u


def _make_org(db, slug) -> models.Organization:
    o = models.Organization(
        name=slug.title(), slug=slug, description="",
        settings={"allowed_voting_methods": ["binary", "approval", "ranked_choice"]},
    )
    db.add(o)
    db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _make_topic(db, org, name) -> models.Topic:
    t = models.Topic(name=name, org_id=org.id)
    db.add(t)
    db.flush()
    return t


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _preview(client, slug, payload, auth):
    return client.post(f"/api/orgs/{slug}/proposals/import-preview", json=payload, headers=auth)


@pytest.fixture()
def setup(test_db):
    org = _make_org(test_db, "rt72c")
    steward = _make_user(test_db, "steward")
    make_org_membership(test_db, org_id=org.id, user_id=steward.id, role="steward")
    test_db.commit()
    return dict(org=org, steward=steward)


# ---------------------------------------------------------------------------
# Single-object: unmatched topic_name → warn-and-drop (no error)
# ---------------------------------------------------------------------------

def test_unmatched_topic_name_warns_not_errors(client, test_db, setup):
    _make_topic(test_db, setup["org"], "Budget")
    test_db.commit()
    resp = _preview(client, setup["org"].slug, {
        "title": "P", "voting_method": "binary",
        "topics": [{"topic_name": "Housing"}],
    }, _auth(setup["steward"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "errors" not in body  # single-object success shape (no 422)
    assert body["proposal"]["topics"] == []
    assert body["resolved_topics"] == []
    assert any("Housing" in w and "isn't in this organization" in w for w in body["warnings"])


def test_partial_match_keeps_matched_drops_unmatched(client, test_db, setup):
    budget = _make_topic(test_db, setup["org"], "Budget")
    test_db.commit()
    resp = _preview(client, setup["org"].slug, {
        "title": "P", "voting_method": "binary",
        "topics": [
            {"topic_name": "Budget", "relevance": 0.9},
            {"topic_name": "Housing"},
        ],
    }, _auth(setup["steward"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Matched kept, unmatched dropped.
    assert body["proposal"]["topics"] == [{"topic_id": budget.id, "relevance": 0.9}]
    assert [t["topic_id"] for t in body["resolved_topics"]] == [budget.id]
    assert any("Housing" in w for w in body["warnings"])


def test_all_topics_unmatched_imports_topicless(client, test_db, setup):
    _make_topic(test_db, setup["org"], "Budget")
    test_db.commit()
    resp = _preview(client, setup["org"].slug, {
        "title": "P", "voting_method": "binary",
        "topics": [{"topic_name": "Housing"}, {"topic_name": "Climate"}],
    }, _auth(setup["steward"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["proposal"]["topics"] == []
    assert sum("isn't in this organization" in w for w in body["warnings"]) == 2


def test_unmatched_topic_id_warns_not_errors(client, test_db, setup):
    # Both bare-string id and dict-id forms downgrade to warnings.
    resp = _preview(client, setup["org"].slug, {
        "title": "P", "voting_method": "binary",
        "topics": ["00000000-0000-0000-0000-000000000000",
                   {"topic_id": "11111111-1111-1111-1111-111111111111"}],
    }, _auth(setup["steward"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "errors" not in body
    assert body["proposal"]["topics"] == []
    assert sum("isn't in this organization" in w for w in body["warnings"]) == 2


# ---------------------------------------------------------------------------
# Structural topic errors STAY blocking (regression guard)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("topics_val,expect_msg", [
    ("not-a-list", "must be a list"),
    ([{"relevance": 0.5}], "needs a 'topic_id' or 'topic_name'"),
    ([123], "Invalid topic entry"),
])
def test_structural_topic_errors_still_block(client, test_db, setup, topics_val, expect_msg):
    resp = _preview(client, setup["org"].slug, {
        "title": "P", "voting_method": "binary", "topics": topics_val,
    }, _auth(setup["steward"]))
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert "topics" in body["errors"]
    assert any(expect_msg in m for m in body["errors"]["topics"])


# ---------------------------------------------------------------------------
# Z's real housing file — the regression this pass exists for
# ---------------------------------------------------------------------------

# Faithful compact form of import_housing_proposals.json: 3 proposals (2 RCV
# + 1 binary), each tagging "Housing" (absent here) + a topic that IS present.
_HOUSING_FILE = [
    {
        "title": "Homelessness — What Should the US Approach Be?",
        "body": "...", "voting_method": "ranked_choice", "num_winners": 1,
        "options": [
            {"label": "Housing first"}, {"label": "Treatment first"},
            {"label": "Permanent supportive housing"}, {"label": "Clear encampments"},
            {"label": "Prevention"},
        ],
        "topics": [{"topic_name": "Housing", "relevance": 1},
                   {"topic_name": "Healthcare", "relevance": 0.8}],
    },
    {
        "title": "Should the Federal Government Override Local Zoning?",
        "body": "...", "voting_method": "binary",
        "topics": [{"topic_name": "Housing", "relevance": 1},
                   {"topic_name": "Democracy & Elections", "relevance": 0.8}],
    },
    {
        "title": "Homeownership Policy — Subsidize Owning Over Renting?",
        "body": "...", "voting_method": "ranked_choice", "num_winners": 1,
        "options": [
            {"label": "Maintain subsidies"}, {"label": "Target first-time buyers"},
            {"label": "Tenure-neutral"}, {"label": "Phase out"},
            {"label": "Public/social housing"},
        ],
        "topics": [{"topic_name": "Housing", "relevance": 1},
                   {"topic_name": "Economy & Taxes", "relevance": 0.8}],
    },
]


def test_housing_file_yields_three_valid_warned(client, test_db, setup):
    # The org has the sibling topics but NOT "Housing".
    healthcare = _make_topic(test_db, setup["org"], "Healthcare")
    democracy = _make_topic(test_db, setup["org"], "Democracy & Elections")
    economy = _make_topic(test_db, setup["org"], "Economy & Taxes")
    test_db.commit()

    resp = _preview(client, setup["org"].slug, _HOUSING_FILE, _auth(setup["steward"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["summary"] == {"total": 3, "valid": 3, "invalid": 0}
    expected_sibling = [healthcare.id, democracy.id, economy.id]
    for i, item in enumerate(body["items"]):
        assert item["proposal"] is not None, item
        assert item["errors"] == {}
        # Housing dropped + warned; the sibling topic retained.
        assert any("Housing" in w for w in item["warnings"])
        topic_ids = [t["topic_id"] for t in item["proposal"]["topics"]]
        assert topic_ids == [expected_sibling[i]]
    # No-write at preview.
    assert test_db.query(models.Proposal).count() == 0


def test_create_through_attaches_matched_drops_unmatched(client, test_db, setup):
    healthcare = _make_topic(test_db, setup["org"], "Healthcare")
    test_db.commit()

    body = _preview(client, setup["org"].slug, [_HOUSING_FILE[0]], _auth(setup["steward"])).json()
    payload = body["items"][0]["proposal"]
    assert [t["topic_id"] for t in payload["topics"]] == [healthcare.id]

    create = client.post(
        f"/api/orgs/{setup['org'].slug}/proposals", json=payload, headers=_auth(setup["steward"]),
    )
    assert create.status_code == 201, create.text
    pid = create.json()["id"]
    # Side-effect: the created draft has Healthcare attached, no Housing.
    rows = test_db.query(models.ProposalTopic).filter_by(proposal_id=pid).all()
    assert [r.topic_id for r in rows] == [healthcare.id]
