"""Phase 72 — multi-proposal import + permission-aware template & preview.

Section A — array import:
  * single object → unchanged 68a {proposal, warnings, resolved_topics}
  * array of N valid → 200 items, summary counts
  * mixed array → one bad item doesn't fail the batch
  * array of one → items shape (FE unwraps)
  * malformed / scalar / over-cap → top-level 422; per-item topic + unknown
  * no-write assertion

Section B — permission-aware:
  * template seeded from ORG defaults, fields omitted by permission
  * preview drops DIVERGENT threshold/duration the caller can't set (warn,
    not error); EQUAL-to-default is retained + silent (the load-bearing
    "diverges, not present" subtlety); permitted caller keeps divergent.

Style mirrors test_phase_68a_proposal_import.py.
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

# Distinctive org defaults (none equal to the OLD hardcoded 0.5/0.4/3/5).
_ORG_DEFAULTS = {
    "allowed_voting_methods": ["binary", "approval", "ranked_choice"],
    "default_pass_threshold": 0.6,
    "default_quorum_threshold": 0.3,
    "default_voting_days": 8,
    "default_deliberation_days": 2,
}


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
    o = models.Organization(name=slug.title(), slug=slug, description="", settings=dict(_ORG_DEFAULTS))
    db.add(o)
    db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _make_topic(db, org, name) -> models.Topic:
    t = models.Topic(name=name, org_id=org.id)
    db.add(t)
    db.flush()
    return t


def _grant(db, org, system_key, permission_key) -> None:
    role = db.query(models.Role).filter_by(org_id=org.id, system_key=system_key).first()
    db.add(models.RolePermission(role_id=role.id, permission_key=permission_key, enabled=True))
    db.flush()


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _preview(client, slug, payload, auth):
    return client.post(f"/api/orgs/{slug}/proposals/import-preview", json=payload, headers=auth)


@pytest.fixture()
def setup(test_db):
    org = _make_org(test_db, "imp72")
    steward = _make_user(test_db, "steward")        # all perms
    # A member granted ONLY proposal.create — can import, lacks both
    # set_thresholds AND set_durations (for the fallback tests).
    creator = _make_user(test_db, "creator")
    make_org_membership(test_db, org_id=org.id, user_id=steward.id, role="steward")
    make_org_membership(test_db, org_id=org.id, user_id=creator.id, role="member")
    _grant(test_db, org, "member", "proposal.create")
    test_db.commit()
    return dict(org=org, steward=steward, creator=creator)


def _bin(title):
    return {"title": title, "voting_method": "binary"}


# ===========================================================================
# Section A — array import
# ===========================================================================

def test_single_object_unchanged_shape(client, test_db, setup):
    resp = _preview(client, setup["org"].slug, _bin("Solo"), _auth(setup["steward"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {"proposal", "warnings", "resolved_topics"}
    assert body["proposal"]["title"] == "Solo"
    assert "items" not in body


def test_array_all_valid(client, test_db, setup):
    arr = [_bin("A"), _bin("B"), _bin("C")]
    resp = _preview(client, setup["org"].slug, arr, _auth(setup["steward"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["summary"] == {"total": 3, "valid": 3, "invalid": 0}
    assert [it["index"] for it in body["items"]] == [0, 1, 2]
    assert all(it["proposal"] is not None and it["errors"] == {} for it in body["items"])
    assert test_db.query(models.Proposal).count() == 0  # no-write


def test_array_mixed_one_bad_does_not_fail_batch(client, test_db, setup):
    arr = [
        _bin("Good 1"),
        {"title": "Bad approval", "voting_method": "approval", "options": [{"label": "only"}]},
        _bin("Good 2"),
    ]
    resp = _preview(client, setup["org"].slug, arr, _auth(setup["steward"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["summary"] == {"total": 3, "valid": 2, "invalid": 1}
    assert body["items"][0]["proposal"] is not None
    assert body["items"][1]["proposal"] is None
    assert "options" in body["items"][1]["errors"]
    assert body["items"][2]["proposal"] is not None
    assert test_db.query(models.Proposal).count() == 0


def test_array_of_one_returns_items_shape(client, test_db, setup):
    resp = _preview(client, setup["org"].slug, [_bin("Lonely")], _auth(setup["steward"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body and body["summary"]["total"] == 1
    assert body["items"][0]["proposal"]["title"] == "Lonely"


def test_array_non_dict_item_indexed_error(client, test_db, setup):
    resp = _preview(client, setup["org"].slug, [_bin("ok"), 42], _auth(setup["steward"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["summary"] == {"total": 2, "valid": 1, "invalid": 1}
    assert body["items"][1]["proposal"] is None
    assert "_item" in body["items"][1]["errors"]


def test_over_cap_array_rejected(client, test_db, setup):
    arr = [_bin(f"P{i}") for i in range(51)]
    resp = _preview(client, setup["org"].slug, arr, _auth(setup["steward"]))
    assert resp.status_code == 422, resp.text
    assert "_file" in resp.json()["errors"]
    assert "max 50" in " ".join(resp.json()["errors"]["_file"])


def test_scalar_top_level_rejected(client, test_db, setup):
    resp = _preview(client, setup["org"].slug, "hello", _auth(setup["steward"]))
    assert resp.status_code == 422, resp.text
    assert "_file" in resp.json()["errors"]


def test_array_per_item_topic_and_unknown(client, test_db, setup):
    topic = _make_topic(test_db, setup["org"], "Budget")
    test_db.commit()
    arr = [
        {"title": "T1", "voting_method": "binary", "topics": [{"topic_name": "Budget"}], "bogus": 1},
        {"title": "T2", "voting_method": "binary", "topics": [{"topic_name": "Nope"}]},
    ]
    resp = _preview(client, setup["org"].slug, arr, _auth(setup["steward"]))
    body = resp.json()
    # Item 0: topic resolved + unknown-key warning; valid.
    assert body["items"][0]["proposal"]["topics"] == [{"topic_id": topic.id, "relevance": 1.0}]
    w0 = " ".join(body["items"][0]["warnings"])
    assert topic.id in w0 and "bogus" in w0
    # Item 1 (Phase 72c): unmatched topic is now warn-and-drop, NOT an error —
    # the item is VALID, imports topic-less, with a warning naming the topic.
    assert body["items"][1]["errors"] == {}
    assert body["items"][1]["proposal"] is not None
    assert body["items"][1]["proposal"]["topics"] == []
    assert any("Nope" in w for w in body["items"][1]["warnings"])


# ===========================================================================
# Section B — permission-aware template
# ===========================================================================

def test_template_with_perms_seeded_from_org_defaults(client, test_db, setup):
    resp = client.get(
        f"/api/orgs/{setup['org'].slug}/proposals/import-template",
        headers=_auth(setup["steward"]),
    )
    assert resp.status_code == 200, resp.text
    tmpl = resp.json()
    # Seeded from the ORG defaults — NOT the old hardcoded 0.5/0.4/3/5.
    assert tmpl["pass_threshold"] == 0.6
    assert tmpl["quorum_threshold"] == 0.3
    assert tmpl["voting_days"] == 8
    assert tmpl["deliberation_days"] == 2


def test_template_without_thresholds_omits_those_keys(client, test_db, setup):
    # creator (member + proposal.create) lacks set_thresholds AND set_durations.
    resp = client.get(
        f"/api/orgs/{setup['org'].slug}/proposals/import-template",
        headers=_auth(setup["creator"]),
    )
    assert resp.status_code == 200, resp.text
    tmpl = resp.json()
    assert "pass_threshold" not in tmpl
    assert "quorum_threshold" not in tmpl
    assert "voting_days" not in tmpl
    assert "deliberation_days" not in tmpl


def test_template_with_durations_only(client, test_db, setup):
    # Moderator has set_durations but not set_thresholds (DEFAULT_GRANTS).
    mod = _make_user(test_db, "mod")
    make_org_membership(test_db, org_id=setup["org"].id, user_id=mod.id, role="moderator")
    test_db.commit()
    tmpl = client.get(
        f"/api/orgs/{setup['org'].slug}/proposals/import-template", headers=_auth(mod),
    ).json()
    assert "voting_days" in tmpl and "deliberation_days" in tmpl
    assert "pass_threshold" not in tmpl and "quorum_threshold" not in tmpl


# ===========================================================================
# Section B — preview warn-and-fallback ("diverges, not present")
# ===========================================================================

def test_preview_divergent_threshold_dropped_with_warning(client, test_db, setup):
    # creator lacks set_thresholds; file carries pass_threshold diverging.
    resp = _preview(client, setup["org"].slug,
                    {"title": "Div", "voting_method": "binary", "pass_threshold": 0.9},
                    _auth(setup["creator"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "pass_threshold" not in body["proposal"]  # dropped → falls back to org default
    assert any("pass threshold" in w and "0.6" in w for w in body["warnings"])


def test_preview_threshold_equal_to_default_retained_no_warning(client, test_db, setup):
    # Load-bearing: equal-to-default must NOT warn and must NOT drop ("diverges, not present").
    resp = _preview(client, setup["org"].slug,
                    {"title": "Eq", "voting_method": "binary", "pass_threshold": 0.6},
                    _auth(setup["creator"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["proposal"]["pass_threshold"] == 0.6
    assert not any("pass threshold" in w for w in body["warnings"])


def test_preview_divergent_duration_dropped_with_warning(client, test_db, setup):
    resp = _preview(client, setup["org"].slug,
                    {"title": "Dv", "voting_method": "binary", "voting_days": 20},
                    _auth(setup["creator"]))
    body = resp.json()
    assert "voting_days" not in body["proposal"]
    assert any("voting duration" in w and "8" in w for w in body["warnings"])


def test_preview_duration_equal_to_default_retained(client, test_db, setup):
    resp = _preview(client, setup["org"].slug,
                    {"title": "Eqd", "voting_method": "binary", "voting_days": 8},
                    _auth(setup["creator"]))
    body = resp.json()
    assert body["proposal"]["voting_days"] == 8
    assert not any("voting duration" in w for w in body["warnings"])


def test_preview_permitted_caller_keeps_divergent(client, test_db, setup):
    # Steward has set_thresholds — divergent value retained, no warning.
    resp = _preview(client, setup["org"].slug,
                    {"title": "Over", "voting_method": "binary", "pass_threshold": 0.9},
                    _auth(setup["steward"]))
    body = resp.json()
    assert body["proposal"]["pass_threshold"] == 0.9
    assert not any("pass threshold" in w for w in body["warnings"])


def test_preview_fallback_payload_creates_without_400(client, test_db, setup):
    """The dropped-field payload is exactly what the create path accepts for
    an unpermitted caller — prove the create-time 400 would NOT fire."""
    resp = _preview(client, setup["org"].slug,
                    {"title": "Clean", "voting_method": "binary", "pass_threshold": 0.9},
                    _auth(setup["creator"]))
    payload = resp.json()["proposal"]
    create = client.post(
        f"/api/orgs/{setup['org'].slug}/proposals", json=payload, headers=_auth(setup["creator"]),
    )
    assert create.status_code == 201, create.text  # no 400 on thresholds


def test_preview_multi_item_warnings_attach_to_right_index(client, test_db, setup):
    arr = [
        {"title": "Plain", "voting_method": "binary"},
        {"title": "DivThresh", "voting_method": "binary", "pass_threshold": 0.95},
    ]
    body = _preview(client, setup["org"].slug, arr, _auth(setup["creator"])).json()
    assert not any("pass threshold" in w for w in body["items"][0]["warnings"])
    assert any("pass threshold" in w for w in body["items"][1]["warnings"])
    assert "pass_threshold" not in body["items"][1]["proposal"]
