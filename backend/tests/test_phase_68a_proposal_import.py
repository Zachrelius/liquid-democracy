"""Phase 68a — import a proposal from a JSON file (parse + validate, no write).

Coverage map (spec: phase68_proposal_import_and_archive_dispatch_2026-06-13.md,
Section 68a → Tests):

1. Well-formed file per voting method (binary, approval, RCV) → correct
   ProposalCreate-shaped payload, no errors.
2. Topic-by-name resolution: matched name → topic_id in payload + warning;
   unmatched name → field error listing available topic names.
3. Unknown top-level keys (future export's id/status) → ignored, warning
   emitted, no error. (forward-compat assertion that protects export.)
4. Validation parity: an import violating create rules returns the SAME
   error the create path raises, field-keyed, and returns ALL such errors
   at once.
5. Malformed JSON → single _file error, 422.
6. Oversize upload → rejected (413).
7. Auth: member lacking proposal.create → 403; endpoint writes nothing in
   all cases (no Proposal rows — side-effect assertion).

Style mirrors test_phase_66_multiwinner_approval.py: in-memory SQLite,
explicit fixtures, side-effect assertions per CLAUDE.md.
"""
from __future__ import annotations

import json

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(db: Session, username: str) -> models.User:
    u = models.User(
        username=username,
        display_name=username,
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=True,
    )
    db.add(u)
    db.flush()
    return u


def _make_org(db: Session, slug: str, *, settings: dict | None = None) -> models.Organization:
    o = models.Organization(
        name=slug.title(), slug=slug, description="",
        settings=settings if settings is not None else {},
    )
    db.add(o)
    db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _make_topic(db: Session, org: models.Organization, name: str) -> models.Topic:
    t = models.Topic(name=name, org_id=org.id)
    db.add(t)
    db.flush()
    return t


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _preview(client, slug, payload, auth):
    """POST a raw-JSON import-preview."""
    return client.post(
        f"/api/orgs/{slug}/proposals/import-preview",
        json=payload,
        headers=auth,
    )


@pytest.fixture()
def org_and_author(test_db):
    """An org (binary+approval+RCV enabled) + a steward who can create."""
    org = _make_org(
        test_db, "import-org",
        settings={"allowed_voting_methods": ["binary", "approval", "ranked_choice"]},
    )
    author = _make_user(test_db, "author")
    make_org_membership(test_db, org_id=org.id, user_id=author.id, role="steward")
    test_db.commit()
    return org, author


# ---------------------------------------------------------------------------
# 1. Well-formed per voting method
# ---------------------------------------------------------------------------

def test_import_binary_wellformed(client, test_db, org_and_author):
    org, author = org_and_author
    resp = _preview(client, org.slug, {
        "title": "Binary proposal",
        "body": "Shall we?",
        "voting_method": "binary",
    }, _auth(author))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["proposal"]["title"] == "Binary proposal"
    assert body["proposal"]["voting_method"] == "binary"
    assert body["proposal"]["num_winners"] == 1
    assert body["proposal"]["options"] == []
    assert body["warnings"] == []
    # Side-effect: nothing persisted.
    assert test_db.query(models.Proposal).count() == 0


def test_import_approval_wellformed(client, test_db, org_and_author):
    org, author = org_and_author
    resp = _preview(client, org.slug, {
        "title": "Approval proposal",
        "voting_method": "approval",
        "options": [
            {"label": "Alpha", "description": "first"},
            {"label": "Beta"},
            {"label": "Gamma"},
        ],
    }, _auth(author))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["proposal"]["voting_method"] == "approval"
    assert [o["label"] for o in body["proposal"]["options"]] == ["Alpha", "Beta", "Gamma"]
    assert test_db.query(models.Proposal).count() == 0


def test_import_rcv_wellformed(client, test_db, org_and_author):
    org, author = org_and_author
    resp = _preview(client, org.slug, {
        "title": "RCV proposal",
        "voting_method": "ranked_choice",
        "num_winners": 2,
        "options": [
            {"label": "One"}, {"label": "Two"}, {"label": "Three"},
        ],
    }, _auth(author))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["proposal"]["voting_method"] == "ranked_choice"
    assert body["proposal"]["num_winners"] == 2
    assert len(body["proposal"]["options"]) == 3
    assert test_db.query(models.Proposal).count() == 0


# ---------------------------------------------------------------------------
# 2. Topic-by-name resolution
# ---------------------------------------------------------------------------

def test_import_topic_name_resolves_with_warning(client, test_db, org_and_author):
    org, author = org_and_author
    topic = _make_topic(test_db, org, "Parks & Recreation")
    test_db.commit()

    resp = _preview(client, org.slug, {
        "title": "Topic by name",
        "voting_method": "binary",
        "topics": [{"topic_name": "parks & recreation", "relevance": 0.8}],
    }, _auth(author))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["proposal"]["topics"] == [
        {"topic_id": topic.id, "relevance": 0.8}
    ]
    assert any(topic.id in w for w in body["warnings"])
    assert body["resolved_topics"] == [
        {"topic_id": topic.id, "topic_name": "Parks & Recreation", "relevance": 0.8}
    ]
    assert test_db.query(models.Proposal).count() == 0


def test_import_topic_name_unmatched_warns_and_drops(client, test_db, org_and_author):
    # Phase 72c — an unmatched topic_name is now a WARN-AND-DROP, not a
    # blocking error: the proposal imports topic-less with a warning naming
    # the skipped topic + the available topics.
    org, author = org_and_author
    _make_topic(test_db, org, "Budget")
    _make_topic(test_db, org, "Safety")
    test_db.commit()

    resp = _preview(client, org.slug, {
        "title": "Bad topic",
        "voting_method": "binary",
        "topics": [{"topic_name": "Nonexistent"}],
    }, _auth(author))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "errors" not in body  # single-object success shape
    assert body["proposal"]["topics"] == []  # unmatched topic dropped
    assert body["resolved_topics"] == []
    msg = " ".join(body["warnings"])
    assert "Nonexistent" in msg
    assert "Budget" in msg and "Safety" in msg
    assert test_db.query(models.Proposal).count() == 0


def test_import_topic_by_id(client, test_db, org_and_author):
    org, author = org_and_author
    topic = _make_topic(test_db, org, "Infrastructure")
    test_db.commit()

    resp = _preview(client, org.slug, {
        "title": "Topic by id",
        "voting_method": "binary",
        "topics": [{"topic_id": topic.id}],
    }, _auth(author))
    assert resp.status_code == 200, resp.text
    assert resp.json()["proposal"]["topics"] == [
        {"topic_id": topic.id, "relevance": 1.0}
    ]


# ---------------------------------------------------------------------------
# 3. Forward-compat: unknown keys ignored with a warning
# ---------------------------------------------------------------------------

def test_import_unknown_keys_ignored_with_warning(client, test_db, org_and_author):
    org, author = org_and_author
    resp = _preview(client, org.slug, {
        # Simulates a future export carrying read-only fields.
        "id": "00000000-0000-0000-0000-000000000000",
        "status": "passed",
        "created_at": "2026-01-01T00:00:00Z",
        "title": "Round-trips fine",
        "voting_method": "binary",
    }, _auth(author))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    warned = " ".join(body["warnings"])
    assert "id" in warned and "status" in warned and "created_at" in warned
    # No error from the unknown keys.
    assert body["proposal"]["title"] == "Round-trips fine"
    assert body["proposal"]["status"] != "passed" if "status" in body["proposal"] else True
    assert test_db.query(models.Proposal).count() == 0


# ---------------------------------------------------------------------------
# 4. Validation parity — all errors at once, same messages as create path
# ---------------------------------------------------------------------------

def test_import_validation_parity_multiple_errors(client, test_db, org_and_author):
    org, author = org_and_author
    # Approval with 1 option AND num_winners out of range → BOTH errors.
    resp = _preview(client, org.slug, {
        "title": "Bad approval",
        "voting_method": "approval",
        "num_winners": 3,
        "options": [{"label": "Only one"}],
    }, _auth(author))
    assert resp.status_code == 422, resp.text
    errors = resp.json()["errors"]
    assert "options" in errors
    assert any("at least 2 options" in m for m in errors["options"])
    assert "num_winners" in errors
    assert any("must be 1 for approval" in m for m in errors["num_winners"])
    assert test_db.query(models.Proposal).count() == 0


def test_import_duplicate_labels(client, test_db, org_and_author):
    org, author = org_and_author
    resp = _preview(client, org.slug, {
        "title": "Dupes",
        "voting_method": "approval",
        "options": [{"label": "Same"}, {"label": "same"}],
    }, _auth(author))
    assert resp.status_code == 422, resp.text
    errors = resp.json()["errors"]
    assert any("Duplicate option label" in m for m in errors.get("options", []))


def test_import_rcv_disallowed_matches_create_path(client, test_db):
    # Org that does NOT enable ranked_choice → same error the create path raises.
    org = _make_org(test_db, "no-rcv", settings={"allowed_voting_methods": ["binary", "approval"]})
    author = _make_user(test_db, "rcv-author")
    make_org_membership(test_db, org_id=org.id, user_id=author.id, role="steward")
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals/import-preview",
        json={
            "title": "RCV here",
            "voting_method": "ranked_choice",
            "options": [{"label": "A"}, {"label": "B"}],
        },
        headers=_auth(author),
    )
    assert resp.status_code == 422, resp.text
    errors = resp.json()["errors"]
    assert "voting_method" in errors
    assert any("not allowed by this organization" in m for m in errors["voting_method"])


# ---------------------------------------------------------------------------
# 5. Malformed JSON
# ---------------------------------------------------------------------------

def test_import_malformed_json(client, test_db, org_and_author):
    org, author = org_and_author
    resp = client.post(
        f"/api/orgs/{org.slug}/proposals/import-preview",
        content="{ this is not valid json",
        headers={**_auth(author), "Content-Type": "application/json"},
    )
    assert resp.status_code == 422, resp.text
    errors = resp.json()["errors"]
    assert list(errors.keys()) == ["_file"]
    assert "JSON" in errors["_file"][0]


def test_import_scalar_top_level_rejected(client, test_db, org_and_author):
    # Phase 72 — a top level that is neither object nor array is rejected.
    # (An ARRAY is now a valid multi-import shape; see the Phase 72 tests.)
    org, author = org_and_author
    resp = client.post(
        f"/api/orgs/{org.slug}/proposals/import-preview",
        json=42,
        headers=_auth(author),
    )
    assert resp.status_code == 422, resp.text
    assert "_file" in resp.json()["errors"]


# ---------------------------------------------------------------------------
# 6. Oversize upload
# ---------------------------------------------------------------------------

def test_import_oversize_rejected(client, test_db, org_and_author):
    org, author = org_and_author
    huge = {"title": "x", "body": "a" * (300 * 1024), "voting_method": "binary"}
    resp = client.post(
        f"/api/orgs/{org.slug}/proposals/import-preview",
        json=huge,
        headers=_auth(author),
    )
    assert resp.status_code == 413, resp.text
    assert "_file" in resp.json()["errors"]
    assert test_db.query(models.Proposal).count() == 0


# ---------------------------------------------------------------------------
# 7. Auth — member lacking proposal.create → 403, nothing written
# ---------------------------------------------------------------------------

def test_import_member_without_create_perm_403(client, test_db, org_and_author):
    org, _author = org_and_author
    member = _make_user(test_db, "plain-member")
    make_org_membership(test_db, org_id=org.id, user_id=member.id, role="member")
    test_db.commit()

    resp = _preview(client, org.slug, {
        "title": "Should be blocked",
        "voting_method": "binary",
    }, _auth(member))
    assert resp.status_code == 403, resp.text
    assert test_db.query(models.Proposal).count() == 0


def test_import_non_member_blocked(client, test_db, org_and_author):
    org, _author = org_and_author
    outsider = _make_user(test_db, "outsider")
    test_db.commit()

    resp = _preview(client, org.slug, {
        "title": "Outsider",
        "voting_method": "binary",
    }, _auth(outsider))
    assert resp.status_code in (403, 404), resp.text
    assert test_db.query(models.Proposal).count() == 0


# ---------------------------------------------------------------------------
# Multipart file upload + template
# ---------------------------------------------------------------------------

def test_import_multipart_file_upload(client, test_db, org_and_author):
    org, author = org_and_author
    payload = {"title": "From file", "voting_method": "binary"}
    resp = client.post(
        f"/api/orgs/{org.slug}/proposals/import-preview",
        files={"file": ("proposal.json", json.dumps(payload), "application/json")},
        headers=_auth(author),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["proposal"]["title"] == "From file"
    assert test_db.query(models.Proposal).count() == 0


def test_import_template_available(client, test_db, org_and_author):
    org, author = org_and_author
    resp = client.get(
        f"/api/orgs/{org.slug}/proposals/import-template",
        headers=_auth(author),
    )
    assert resp.status_code == 200, resp.text
    tmpl = resp.json()
    assert "title" in tmpl and "voting_method" in tmpl
    # The template's _readme is an unknown key — re-importing it warns, no error.
    # Drop the example topic (it won't resolve against this test org's topics).
    tmpl.pop("topics", None)
    resp2 = _preview(client, org.slug, tmpl, _auth(author))
    assert resp2.status_code == 200, resp2.text
    assert any("_readme" in w for w in resp2.json()["warnings"])
