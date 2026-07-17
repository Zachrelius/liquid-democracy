"""Phase 96 adversarial security regression tests.

These tests exercise object-substitution and stale-authorization paths with
disposable local data. They intentionally assert both the denial and the
absence of a write-side effect.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import auth as auth_utils
import models
from database import get_db
from main import app
from tests.conftest import make_org_membership, make_sub_org_membership, make_user


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _auth(user: models.User) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _org(db, slug: str, *, parent_id: str | None = None, settings=None):
    org = models.Organization(
        name=slug.replace("-", " ").title(),
        slug=slug,
        parent_org_id=parent_id,
        join_policy="invite_only",
        settings=settings or {},
    )
    db.add(org)
    db.flush()
    return org


def _private_suborg_world(db):
    parent = _org(db, "p96-parent")
    sub = _org(
        db,
        "p96-private-sub",
        parent_id=parent.id,
        settings={"private": True},
    )
    author = make_user(db, "p96_sub_author")
    parent_only = make_user(db, "p96_parent_only")
    make_org_membership(db, org_id=parent.id, user_id=author.id, role="member")
    make_org_membership(db, org_id=parent.id, user_id=parent_only.id, role="member")
    make_sub_org_membership(
        db, sub_org_id=sub.id, user_id=author.id, role="member",
    )
    proposal = models.Proposal(
        title="Private sub-org plan",
        body="Confidential deliberation body",
        author_id=author.id,
        org_id=parent.id,
        sub_org_id=sub.id,
        status="deliberation",
        voting_method="approval",
        allow_write_in_options=True,
        max_write_ins=10,
    )
    db.add(proposal)
    db.flush()
    return parent, sub, author, parent_only, proposal


def test_invitation_cannot_be_consumed_by_a_different_verified_email(client, db):
    org = _org(db, "p96-invite")
    inviter = make_user(db, "p96_inviter")
    intended = make_user(db, "p96_intended")
    attacker = make_user(db, "p96_attacker")
    make_org_membership(db, org_id=org.id, user_id=inviter.id, role="admin")
    invitation = models.Invitation(
        org_id=org.id,
        email=intended.email,
        invited_by=inviter.id,
        role="admin",
        token="p96-email-bound-invitation-token",
        status="pending",
        expires_at=_now() + timedelta(days=7),
    )
    db.add(invitation)
    db.commit()

    response = client.post(
        f"/api/orgs/join/{invitation.token}", headers=_auth(attacker),
    )

    assert response.status_code in (400, 403), response.text
    assert db.query(models.OrgMembership).filter_by(
        org_id=org.id, user_id=attacker.id,
    ).first() is None
    db.refresh(invitation)
    assert invitation.status == "pending"
    assert invitation.accepted_at is None


@pytest.mark.parametrize(
    "path_suffix",
    ["", "/revisions", "/trajectory", "/my-vote", "/verification-weight"],
)
def test_private_suborg_proposal_surfaces_hide_from_parent_only_member(
    client, db, path_suffix,
):
    parent, _sub, _author, parent_only, proposal = _private_suborg_world(db)
    db.commit()
    path = (
        f"/api/orgs/{parent.slug}/proposals/{proposal.id}"
        if path_suffix == ""
        else f"/api/proposals/{proposal.id}{path_suffix}"
    )

    response = client.get(path, headers=_auth(parent_only))

    assert response.status_code == 404, (path, response.text)


def test_parent_only_member_cannot_add_writein_to_private_suborg(client, db):
    _parent, _sub, _author, parent_only, proposal = _private_suborg_world(db)
    db.commit()

    response = client.post(
        f"/api/proposals/{proposal.id}/options",
        headers=_auth(parent_only),
        json={"label": "Injected option"},
    )

    assert response.status_code == 404, response.text
    assert db.query(models.ProposalOption).filter_by(
        proposal_id=proposal.id, label="Injected option",
    ).first() is None


def test_parent_only_member_cannot_cosign_private_suborg_proposal(client, db):
    _parent, _sub, _author, parent_only, proposal = _private_suborg_world(db)
    proposal.is_cosign_gated = True
    proposal.cosign_threshold_snapshot = 2
    db.commit()

    response = client.post(
        f"/api/proposals/{proposal.id}/cosign", headers=_auth(parent_only),
    )

    assert response.status_code == 404, response.text
    assert db.query(models.ProposalCosignature).filter_by(
        proposal_id=proposal.id, user_id=parent_only.id,
    ).first() is None


def test_suspended_proposal_author_cannot_mutate_org_content(client, db):
    org = _org(db, "p96-removed-author")
    author = make_user(db, "p96_removed_author")
    make_org_membership(
        db, org_id=org.id, user_id=author.id, role="member", status="suspended",
    )
    proposal = models.Proposal(
        title="Original title",
        body="",
        author_id=author.id,
        org_id=org.id,
        status="draft",
        voting_method="binary",
    )
    db.add(proposal)
    db.commit()

    response = client.patch(
        f"/api/proposals/{proposal.id}",
        headers=_auth(author),
        json={"title": "Unauthorized edit"},
    )

    assert response.status_code == 404, response.text
    db.refresh(proposal)
    assert proposal.title == "Original title"


def test_suspended_comment_author_cannot_edit_org_content(client, db):
    org = _org(db, "p96-suspended-commenter")
    author = make_user(db, "p96_suspended_commenter")
    make_org_membership(
        db, org_id=org.id, user_id=author.id, role="member", status="suspended",
    )
    proposal = models.Proposal(
        title="Discussion", body="", author_id=author.id, org_id=org.id,
        status="deliberation", voting_method="binary",
    )
    db.add(proposal)
    db.flush()
    comment = models.Comment(
        proposal_id=proposal.id, author_id=author.id, body="Original comment",
    )
    db.add(comment)
    db.commit()

    response = client.patch(
        f"/api/comments/{comment.id}", headers=_auth(author),
        json={"body": "Unauthorized edit"},
    )

    assert response.status_code == 404, response.text
    db.refresh(comment)
    assert comment.body == "Original comment"


def test_org_proposal_create_rejects_topic_from_another_org(client, db):
    org_a = _org(db, "p96-topic-a")
    org_b = _org(db, "p96-topic-b")
    admin_a = make_user(db, "p96_topic_admin")
    make_org_membership(db, org_id=org_a.id, user_id=admin_a.id, role="admin")
    foreign_topic = models.Topic(
        org_id=org_b.id, name="Foreign confidential topic", color="#123456",
    )
    db.add(foreign_topic)
    db.commit()

    response = client.post(
        f"/api/orgs/{org_a.slug}/proposals",
        headers=_auth(admin_a),
        json={
            "title": "Cross-org topic attempt",
            "body": "",
            "voting_method": "binary",
            "topics": [{"topic_id": foreign_topic.id, "relevance": 1.0}],
        },
    )

    assert response.status_code == 400, response.text
    assert db.query(models.Proposal).filter_by(
        title="Cross-org topic attempt",
    ).first() is None


def test_proposal_update_rejects_foreign_topic_without_dropping_current_topic(
    client, db,
):
    org_a = _org(db, "p96-update-topic-a")
    org_b = _org(db, "p96-update-topic-b")
    author = make_user(db, "p96_update_topic_author")
    make_org_membership(db, org_id=org_a.id, user_id=author.id, role="member")
    local_topic = models.Topic(
        org_id=org_a.id, name="Local topic", color="#111111",
    )
    foreign_topic = models.Topic(
        org_id=org_b.id, name="Foreign topic", color="#222222",
    )
    db.add_all([local_topic, foreign_topic])
    db.flush()
    proposal = models.Proposal(
        title="Scoped proposal", body="", author_id=author.id,
        org_id=org_a.id, status="draft", voting_method="binary",
    )
    db.add(proposal)
    db.flush()
    db.add(models.ProposalTopic(
        proposal_id=proposal.id, topic_id=local_topic.id, relevance=1.0,
    ))
    db.commit()

    response = client.patch(
        f"/api/proposals/{proposal.id}", headers=_auth(author),
        json={"topics": [{"topic_id": foreign_topic.id, "relevance": 1.0}]},
    )

    assert response.status_code == 400, response.text
    topic_ids = {
        row.topic_id for row in db.query(models.ProposalTopic).filter_by(
            proposal_id=proposal.id,
        ).all()
    }
    assert topic_ids == {local_topic.id}


def test_global_proposal_creation_is_platform_admin_only(client, db):
    user = make_user(db, "p96_global_spammer")
    db.commit()

    response = client.post(
        "/api/proposals",
        headers=_auth(user),
        json={"title": "Global spam", "body": "", "voting_method": "binary"},
    )

    assert response.status_code == 403, response.text
    assert db.query(models.Proposal).filter_by(title="Global spam").first() is None


def test_hidden_org_topic_names_are_not_enumerable(client, db):
    org = _org(db, "p96-hidden-topics")
    org.discoverability = "hidden"
    member = make_user(db, "p96_hidden_member")
    outsider = make_user(db, "p96_hidden_outsider")
    make_org_membership(db, org_id=org.id, user_id=member.id, role="member")
    topic = models.Topic(
        org_id=org.id, name="Confidential acquisition", color="#123456",
    )
    db.add(topic)
    db.commit()

    anonymous = client.get("/api/topics")
    unrelated = client.get("/api/topics", headers=_auth(outsider))
    authorized = client.get("/api/topics", headers=_auth(member))

    assert topic.id not in {row["id"] for row in anonymous.json()}
    assert topic.id not in {row["id"] for row in unrelated.json()}
    assert topic.id in {row["id"] for row in authorized.json()}


@pytest.mark.parametrize("suffix", ["", "/not-a-real-topic"])
def test_retired_unscoped_delegate_directory_is_not_public(client, suffix):
    response = client.get(f"/api/delegates/public{suffix}")
    assert response.status_code == 404, response.text


def test_removed_polis_creator_cannot_update_or_deanonymize_export(
    client, db, monkeypatch,
):
    from routes import polises as polis_routes

    org = _org(db, "p96-polis")
    creator = make_user(db, "p96_removed_polis_creator")
    make_org_membership(
        db, org_id=org.id, user_id=creator.id, role="moderator", status="suspended",
    )
    polis = models.Polis(
        org_id=org.id,
        title="Original Polis",
        prompt="Private participant input",
        created_by=creator.id,
        polis_conversation_id="p96-conversation",
        status="active",
    )
    db.add(polis)
    db.commit()

    update = client.patch(
        f"/api/orgs/{org.slug}/polises/{polis.id}",
        headers=_auth(creator),
        json={"title": "Unauthorized title"},
    )
    assert update.status_code == 403, update.text
    db.refresh(polis)
    assert polis.title == "Original Polis"

    monkeypatch.setattr(polis_routes.app_settings, "polis_auth_token", "test-token")
    monkeypatch.setattr(
        polis_routes.polis_service,
        "fetch_export",
        lambda _conversation_id: b"participant,xid\n1,secret",
    )
    export = client.get(
        f"/api/orgs/{org.slug}/polises/{polis.id}/export?deanonymize=true",
        headers=_auth(creator),
    )
    assert export.status_code == 403, export.text
    assert b"participant,xid" not in export.content
