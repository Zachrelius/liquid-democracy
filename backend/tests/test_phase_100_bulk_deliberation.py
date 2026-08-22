"""Phase 100 — bounded, retry-safe draft-to-deliberation bulk advance."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from main import app
from role_seed import seed_default_roles_for_org
from tests.conftest import make_org_membership


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


@pytest.fixture()
def db():
    # The endpoint deliberately creates nested transactions. Give this
    # module a plain per-test session rather than conftest's outer-savepoint
    # fixture so the route exercises production-like transaction ownership.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def client(db):
    def _get_db():
        yield db

    app.dependency_overrides[get_db] = _get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _user(db, username: str) -> models.User:
    user = models.User(
        username=username,
        display_name=username,
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=True,
    )
    db.add(user)
    db.flush()
    return user


def _org(db, slug: str) -> models.Organization:
    org = models.Organization(
        name=slug.title(),
        slug=slug,
        description="",
        join_policy="open",
        settings={"default_voting_days": 7},
    )
    db.add(org)
    db.flush()
    seed_default_roles_for_org(db, org.id)
    return org


def _proposal(
    db,
    org: models.Organization,
    author: models.User,
    *,
    status: str = "draft",
    title: str | None = None,
) -> models.Proposal:
    proposal = models.Proposal(
        title=title or f"Proposal {uuid.uuid4()}",
        body="Body",
        author_id=author.id,
        org_id=org.id,
        voting_method="binary",
        num_winners=1,
        status=status,
        voting_days=7,
    )
    db.add(proposal)
    db.flush()
    return proposal


def _auth(user: models.User) -> dict[str, str]:
    token = auth_utils.create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


def _url(org: models.Organization) -> str:
    return f"/api/orgs/{org.slug}/proposals/bulk-advance-to-deliberation"


@pytest.fixture()
def setup(db):
    org = _org(db, "phase-100-org")
    steward = _user(db, "phase100_steward")
    member = _user(db, "phase100_member")
    moderator = _user(db, "phase100_moderator")
    make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
    make_org_membership(db, org_id=org.id, user_id=member.id, role="member")
    moderator_membership = make_org_membership(
        db, org_id=org.id, user_id=moderator.id, role="moderator",
    )
    # The configurable permission is the authority. Exercise a moderator
    # whose starter grant has deliberately been disabled.
    moderator_grant = db.query(models.RolePermission).filter(
        models.RolePermission.role_id == moderator_membership.role_id,
        models.RolePermission.permission_key == "proposal.advance_phase",
    ).one()
    moderator_grant.enabled = False
    db.commit()
    return {
        "org": org,
        "steward": steward,
        "member": member,
        "moderator": moderator,
    }


@pytest.mark.parametrize("count", [1, 3, 500])
def test_authorized_steward_advances_bounded_draft_batches(
    client, db, setup, count,
):
    proposals = [
        _proposal(db, setup["org"], setup["steward"], title=f"Draft {i}")
        for i in range(count)
    ]
    db.commit()

    response = client.post(
        _url(setup["org"]),
        headers=_auth(setup["steward"]),
        json={"proposal_ids": [proposal.id for proposal in proposals]},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["requested"] == count
    assert payload["processed"] == count
    assert payload["advanced"] == count
    assert payload["already_in_deliberation"] == 0
    assert payload["ineligible_status"] == 0
    assert payload["not_found"] == 0
    db.expire_all()
    assert all(db.get(models.Proposal, p.id).status == "deliberation" for p in proposals)
    assert all(db.get(models.Proposal, p.id).deliberation_start for p in proposals)


def test_empty_and_501_payloads_reject_before_mutation(client, db, setup):
    draft = _proposal(db, setup["org"], setup["steward"])
    db.commit()

    empty = client.post(
        _url(setup["org"]),
        headers=_auth(setup["steward"]),
        json={"proposal_ids": []},
    )
    too_many_ids = [draft.id] + [str(uuid.uuid4()) for _ in range(500)]
    too_many = client.post(
        _url(setup["org"]),
        headers=_auth(setup["steward"]),
        json={"proposal_ids": too_many_ids},
    )

    assert empty.status_code == 422
    assert too_many.status_code == 422
    db.expire_all()
    assert db.get(models.Proposal, draft.id).status == "draft"


def test_invalid_uuid_rejects_before_mutation(client, db, setup):
    draft = _proposal(db, setup["org"], setup["steward"])
    db.commit()
    response = client.post(
        _url(setup["org"]),
        headers=_auth(setup["steward"]),
        json={"proposal_ids": [draft.id, "not-a-uuid"]},
    )
    assert response.status_code == 422
    db.expire_all()
    assert db.get(models.Proposal, draft.id).status == "draft"


def test_duplicate_ids_process_mutate_and_audit_once(client, db, setup):
    draft = _proposal(db, setup["org"], setup["steward"])
    db.commit()
    response = client.post(
        _url(setup["org"]),
        headers=_auth(setup["steward"]),
        json={"proposal_ids": [draft.id, draft.id.upper(), draft.id]},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["requested"] == 3
    assert payload["processed"] == 1
    assert payload["advanced"] == 1
    audits = db.query(models.AuditLog).filter(
        models.AuditLog.action == "proposal.status_changed",
        models.AuditLog.target_id == draft.id,
    ).all()
    assert len(audits) == 1
    assert audits[0].details["old_status"] == "draft"
    assert audits[0].details["new_status"] == "deliberation"


@pytest.mark.parametrize("actor_key", ["member", "moderator"])
def test_user_without_advance_permission_gets_403(
    client, db, setup, actor_key,
):
    draft = _proposal(db, setup["org"], setup["member"])
    db.commit()
    response = client.post(
        _url(setup["org"]),
        headers=_auth(setup[actor_key]),
        json={"proposal_ids": [draft.id]},
    )
    assert response.status_code == 403
    db.expire_all()
    assert db.get(models.Proposal, draft.id).status == "draft"


def test_author_without_permission_cannot_bulk_advance_own_draft(
    client, db, setup,
):
    draft = _proposal(db, setup["org"], setup["member"])
    db.commit()
    response = client.post(
        _url(setup["org"]),
        headers=_auth(setup["member"]),
        json={"proposal_ids": [draft.id]},
    )
    assert response.status_code == 403
    db.expire_all()
    assert db.get(models.Proposal, draft.id).status == "draft"


def test_cross_org_and_nonexistent_are_indistinguishable_not_found(
    client, db, setup,
):
    other_org = _org(db, "phase-100-other")
    cross_org = _proposal(db, other_org, setup["steward"])
    missing_id = str(uuid.uuid4())
    db.commit()
    response = client.post(
        _url(setup["org"]),
        headers=_auth(setup["steward"]),
        json={"proposal_ids": [cross_org.id, missing_id]},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["not_found"] == 2
    assert payload["results"] == [
        {"proposal_id": cross_org.id, "result": "not_found", "status": None},
        {"proposal_id": missing_id, "result": "not_found", "status": None},
    ]
    db.expire_all()
    assert db.get(models.Proposal, cross_org.id).status == "draft"


def test_mixed_batch_is_stable_retry_safe_and_draft_only(client, db, setup):
    draft = _proposal(db, setup["org"], setup["steward"], status="draft")
    deliberation = _proposal(
        db, setup["org"], setup["steward"], status="deliberation",
    )
    voting = _proposal(db, setup["org"], setup["steward"], status="voting")
    passed = _proposal(db, setup["org"], setup["steward"], status="passed")
    missing_id = str(uuid.uuid4())
    db.commit()
    submitted = [deliberation.id, voting.id, draft.id, missing_id, passed.id]

    first = client.post(
        _url(setup["org"]),
        headers=_auth(setup["steward"]),
        json={"proposal_ids": submitted},
    )
    assert first.status_code == 200, first.text
    payload = first.json()
    assert [item["proposal_id"] for item in payload["results"]] == submitted
    assert [item["result"] for item in payload["results"]] == [
        "already_in_deliberation",
        "ineligible_status",
        "advanced",
        "not_found",
        "ineligible_status",
    ]
    assert payload["advanced"] == 1
    assert payload["already_in_deliberation"] == 1
    assert payload["ineligible_status"] == 2
    assert payload["not_found"] == 1

    retry = client.post(
        _url(setup["org"]),
        headers=_auth(setup["steward"]),
        json={"proposal_ids": [draft.id]},
    )
    assert retry.status_code == 200
    assert retry.json()["advanced"] == 0
    assert retry.json()["already_in_deliberation"] == 1
    db.expire_all()
    assert db.get(models.Proposal, draft.id).status == "deliberation"
    assert db.get(models.Proposal, voting.id).status == "voting"
    assert db.get(models.Proposal, passed.id).status == "passed"


def test_per_item_failure_does_not_undo_successful_sibling(
    client, db, setup, monkeypatch,
):
    first = _proposal(db, setup["org"], setup["steward"], title="First")
    broken = _proposal(db, setup["org"], setup["steward"], title="Broken")
    third = _proposal(db, setup["org"], setup["steward"], title="Third")
    db.commit()

    from routes import proposals as proposal_routes

    real_transition = proposal_routes._transition_draft_to_deliberation

    def _injected_failure(session, proposal, **kwargs):
        if proposal.id == broken.id:
            raise RuntimeError("private database detail must not leak")
        return real_transition(session, proposal, **kwargs)

    monkeypatch.setattr(
        proposal_routes, "_transition_draft_to_deliberation", _injected_failure,
    )
    response = client.post(
        _url(setup["org"]),
        headers=_auth(setup["steward"]),
        json={"proposal_ids": [first.id, broken.id, third.id]},
    )
    assert response.status_code == 200, response.text
    assert "private database detail" not in response.text
    assert [item["result"] for item in response.json()["results"]] == [
        "advanced", "ineligible_status", "advanced",
    ]
    db.expire_all()
    assert db.get(models.Proposal, first.id).status == "deliberation"
    assert db.get(models.Proposal, broken.id).status == "draft"
    assert db.get(models.Proposal, third.id).status == "deliberation"


@pytest.mark.parametrize("route_kind", ["global", "org"])
def test_existing_single_routes_use_shared_timestamp_and_single_audit(
    client, db, setup, route_kind,
):
    draft = _proposal(db, setup["org"], setup["steward"])
    db.commit()
    path = (
        f"/api/proposals/{draft.id}/advance"
        if route_kind == "global"
        else f"/api/orgs/{setup['org'].slug}/proposals/{draft.id}/advance"
    )
    response = client.post(path, headers=_auth(setup["steward"]), json={})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "deliberation"
    db.expire_all()
    saved = db.get(models.Proposal, draft.id)
    assert saved.deliberation_start is not None
    audits = db.query(models.AuditLog).filter(
        models.AuditLog.action == "proposal.status_changed",
        models.AuditLog.target_id == draft.id,
    ).all()
    assert len(audits) == 1
    assert audits[0].details == {
        "proposal_id": draft.id,
        "old_status": "draft",
        "new_status": "deliberation",
    }


def test_bulk_draft_advance_adds_no_notification(client, db, setup):
    draft = _proposal(db, setup["org"], setup["steward"])
    db.commit()
    before = db.query(models.Notification).count()
    response = client.post(
        _url(setup["org"]),
        headers=_auth(setup["steward"]),
        json={"proposal_ids": [draft.id]},
    )
    assert response.status_code == 200, response.text
    assert db.query(models.Notification).count() == before
