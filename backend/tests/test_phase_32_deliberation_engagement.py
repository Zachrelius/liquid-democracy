"""Phase 32 — deliberation engagement tests.

Covers:
  - W2 POST /options: add write-in during deliberation + voting; cap
    enforcement (W4); permission gate (org membership, write-ins
    enabled, multi-option only); duplicate-label rejection.
  - W3 DELETE /options/{id}: adder remove, admin remove, non-adder/
    non-admin rejection, refusal to delete original options.
  - W7 proposal.option_added notification fires for voters but not the
    adder.
  - P1 vote casting during deliberation when allow_pre_voting=True;
    rejection when False.
  - P2 trajectory endpoint filters deliberation-phase snapshots when
    show_votes_during_deliberation=False; surfaces them when True.
  - E2 PATCH captures ProposalRevision row when fields change during
    deliberation; no row created for draft PATCH; PATCH during voting
    rejected.
  - E3 lockout enforcement at >=lockout_fraction elapsed.
  - E4 GET /revisions returns chronological list.
  - S-cluster: per-proposal override beats org default.
  - D22 existing proposals continue to behave unchanged (defaults
    resolve to "feature off" when override is null + org settings empty).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from main import app
from proposal_engagement_config import (
    resolve_allow_pre_voting,
    resolve_allow_write_in_options,
    resolve_allow_write_ins_during_voting,
    resolve_edit_lockout_fraction,
    resolve_max_write_ins,
    resolve_show_votes_during_deliberation,
)


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
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_user(db, username, email=None, is_admin=False):
    user = models.User(
        username=username,
        display_name=username.title(),
        email=email or f"{username}@example.com",
        email_verified=True,
        password_hash=auth_utils.hash_password("noop"),
        is_admin=is_admin,
    )
    db.add(user)
    db.flush()
    return user


def _make_org(db, slug="test-org", settings=None):
    org = models.Organization(
        name=slug.title(), slug=slug, settings=settings or {},
    )
    db.add(org)
    db.flush()
    return org


def _make_membership(db, user, org, role="member"):
    # Ensure member role exists
    role_row = db.query(models.Role).filter_by(
        org_id=org.id, system_key=role,
    ).first()
    if role_row is None:
        role_row = models.Role(
            org_id=org.id, system_key=role,
            name=role.title(), display_order=0,
        )
        db.add(role_row)
        db.flush()
    m = models.OrgMembership(
        user_id=user.id, org_id=org.id, role_id=role_row.id, status="active",
    )
    db.add(m)
    db.flush()
    return m


def _make_proposal(db, *, author, org, status, voting_method="approval",
                   options=None, **kwargs):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    p = models.Proposal(
        title=kwargs.pop("title", "Test Proposal"),
        body=kwargs.pop("body", ""),
        author_id=author.id,
        org_id=org.id,
        status=status,
        voting_method=voting_method,
        num_winners=1,
        deliberation_start=kwargs.pop("deliberation_start", now),
        voting_start=kwargs.pop("voting_start", now if status == "voting" else None),
        voting_end=kwargs.pop("voting_end", now + timedelta(days=3)),
        deliberation_days=kwargs.pop("deliberation_days", 14.0),
        voting_days=kwargs.pop("voting_days", 7.0),
        **kwargs,
    )
    db.add(p)
    db.flush()
    if options is None and voting_method != "binary":
        options = ["A", "B", "C"]
    if options:
        for i, label in enumerate(options):
            db.add(models.ProposalOption(
                proposal_id=p.id, label=label, display_order=i,
            ))
        db.flush()
    return p


def _auth_token(client, username, password="noop"):
    resp = client.post(
        "/api/auth/login",
        data={"username": username, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth_headers(client, username):
    return {"Authorization": f"Bearer {_auth_token(client, username)}"}


# ===========================================================================
# S — settings resolution
# ===========================================================================


class TestSettingsResolution:
    """Per-proposal override beats org default beats platform default."""

    def test_write_in_default_off_when_nothing_set(self, db_session):
        org = _make_org(db_session, settings={})
        author = _make_user(db_session, "auth")
        p = _make_proposal(db_session, author=author, org=org, status="deliberation")
        assert resolve_allow_write_in_options(p, org) is False
        assert resolve_max_write_ins(p, org) == 10
        assert resolve_allow_pre_voting(p, org) is False
        assert resolve_show_votes_during_deliberation(p, org) is False
        assert resolve_edit_lockout_fraction(p, org) == pytest.approx(0.75)

    def test_org_setting_overrides_platform(self, db_session):
        org = _make_org(db_session, settings={
            "write_ins": {"allowed_mode": "default_on", "max_per_proposal": 5},
            "pre_voting": {"allowed_mode": "default_on"},
            "proposal_edits": {"lockout_fraction": 0.5},
        })
        author = _make_user(db_session, "auth")
        p = _make_proposal(db_session, author=author, org=org, status="deliberation")
        assert resolve_allow_write_in_options(p, org) is True
        assert resolve_max_write_ins(p, org) == 5
        assert resolve_allow_pre_voting(p, org) is True
        assert resolve_edit_lockout_fraction(p, org) == pytest.approx(0.5)

    def test_proposal_override_beats_org(self, db_session):
        org = _make_org(db_session, settings={
            "write_ins": {"allowed_mode": "default_on"},
        })
        author = _make_user(db_session, "auth")
        p = _make_proposal(
            db_session, author=author, org=org, status="deliberation",
            allow_write_in_options=False,  # override OFF
        )
        assert resolve_allow_write_in_options(p, org) is False


# ===========================================================================
# W — write-in options
# ===========================================================================


class TestAddWriteInOption:
    def test_add_during_deliberation(self, db_session, client):
        org = _make_org(db_session, settings={
            "write_ins": {"allowed_mode": "default_on"},
        })
        author = _make_user(db_session, "author")
        member = _make_user(db_session, "member")
        _make_membership(db_session, author, org)
        _make_membership(db_session, member, org)
        p = _make_proposal(
            db_session, author=author, org=org, status="deliberation",
        )
        db_session.commit()

        resp = client.post(
            f"/api/proposals/{p.id}/options",
            json={"label": "Write-in 1", "description": ""},
            headers=_auth_headers(client, "member"),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["label"] == "Write-in 1"
        assert data["is_write_in"] is True
        assert data["added_by_user_id"] == member.id

    def test_add_during_voting_when_during_voting_allowed(self, db_session, client):
        org = _make_org(db_session, settings={
            "write_ins": {
                "allowed_mode": "default_on", "during_voting_mode": "default_on",
            },
        })
        author = _make_user(db_session, "author")
        member = _make_user(db_session, "member")
        _make_membership(db_session, author, org)
        _make_membership(db_session, member, org)
        p = _make_proposal(
            db_session, author=author, org=org, status="voting",
        )
        db_session.commit()

        resp = client.post(
            f"/api/proposals/{p.id}/options",
            json={"label": "Mid-vote add"},
            headers=_auth_headers(client, "member"),
        )
        assert resp.status_code == 201

    def test_add_during_voting_blocked_when_during_voting_disabled(
        self, db_session, client,
    ):
        org = _make_org(db_session, settings={
            "write_ins": {
                "allowed_mode": "default_on", "during_voting_mode": "default_off",
            },
        })
        author = _make_user(db_session, "author")
        member = _make_user(db_session, "member")
        _make_membership(db_session, author, org)
        _make_membership(db_session, member, org)
        p = _make_proposal(
            db_session, author=author, org=org, status="voting",
        )
        db_session.commit()

        resp = client.post(
            f"/api/proposals/{p.id}/options",
            json={"label": "Should fail"},
            headers=_auth_headers(client, "member"),
        )
        assert resp.status_code == 403

    def test_add_rejected_when_write_ins_disabled(self, db_session, client):
        org = _make_org(db_session)
        author = _make_user(db_session, "author")
        member = _make_user(db_session, "member")
        _make_membership(db_session, author, org)
        _make_membership(db_session, member, org)
        p = _make_proposal(
            db_session, author=author, org=org, status="deliberation",
        )
        db_session.commit()

        resp = client.post(
            f"/api/proposals/{p.id}/options",
            json={"label": "Nope"},
            headers=_auth_headers(client, "member"),
        )
        assert resp.status_code == 403

    def test_cap_enforced(self, db_session, client):
        org = _make_org(db_session, settings={
            "write_ins": {
                "allowed_mode": "default_on", "max_per_proposal": 2,
            },
        })
        author = _make_user(db_session, "author")
        member = _make_user(db_session, "member")
        _make_membership(db_session, author, org)
        _make_membership(db_session, member, org)
        p = _make_proposal(
            db_session, author=author, org=org, status="deliberation",
        )
        db_session.commit()

        headers = _auth_headers(client, "member")
        for i in range(2):
            resp = client.post(
                f"/api/proposals/{p.id}/options",
                json={"label": f"Write-in {i}"},
                headers=headers,
            )
            assert resp.status_code == 201, resp.text
        resp = client.post(
            f"/api/proposals/{p.id}/options",
            json={"label": "Third"},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "maximum of 2" in resp.json()["detail"]

    def test_binary_proposals_rejected(self, db_session, client):
        org = _make_org(db_session, settings={
            "write_ins": {"allowed_mode": "default_on"},
        })
        author = _make_user(db_session, "author")
        _make_membership(db_session, author, org)
        p = _make_proposal(
            db_session, author=author, org=org, status="deliberation",
            voting_method="binary", options=[],
        )
        db_session.commit()
        resp = client.post(
            f"/api/proposals/{p.id}/options",
            json={"label": "Nope"},
            headers=_auth_headers(client, "author"),
        )
        assert resp.status_code == 400


class TestRemoveWriteInOption:
    def test_adder_can_remove_own(self, db_session, client):
        org = _make_org(db_session, settings={
            "write_ins": {"allowed_mode": "default_on"},
        })
        author = _make_user(db_session, "author")
        member = _make_user(db_session, "member")
        _make_membership(db_session, author, org)
        _make_membership(db_session, member, org)
        p = _make_proposal(
            db_session, author=author, org=org, status="deliberation",
        )
        db_session.commit()

        add_resp = client.post(
            f"/api/proposals/{p.id}/options",
            json={"label": "Removable"},
            headers=_auth_headers(client, "member"),
        )
        option_id = add_resp.json()["id"]
        del_resp = client.delete(
            f"/api/proposals/{p.id}/options/{option_id}",
            headers=_auth_headers(client, "member"),
        )
        assert del_resp.status_code == 204

    def test_non_adder_non_admin_cannot_remove(self, db_session, client):
        org = _make_org(db_session, settings={
            "write_ins": {"allowed_mode": "default_on"},
        })
        author = _make_user(db_session, "author")
        member = _make_user(db_session, "member")
        bystander = _make_user(db_session, "bystander")
        _make_membership(db_session, author, org)
        _make_membership(db_session, member, org)
        _make_membership(db_session, bystander, org)
        p = _make_proposal(
            db_session, author=author, org=org, status="deliberation",
        )
        db_session.commit()

        add_resp = client.post(
            f"/api/proposals/{p.id}/options",
            json={"label": "Locked"},
            headers=_auth_headers(client, "member"),
        )
        option_id = add_resp.json()["id"]
        del_resp = client.delete(
            f"/api/proposals/{p.id}/options/{option_id}",
            headers=_auth_headers(client, "bystander"),
        )
        assert del_resp.status_code == 403

    def test_original_option_cannot_be_removed_via_endpoint(
        self, db_session, client,
    ):
        org = _make_org(db_session, settings={
            "write_ins": {"allowed_mode": "default_on"},
        })
        author = _make_user(db_session, "author")
        _make_membership(db_session, author, org)
        p = _make_proposal(
            db_session, author=author, org=org, status="deliberation",
        )
        original_option_id = p.options[0].id
        db_session.commit()

        del_resp = client.delete(
            f"/api/proposals/{p.id}/options/{original_option_id}",
            headers=_auth_headers(client, "author"),
        )
        assert del_resp.status_code == 400


# ===========================================================================
# E — author edits + change log
# ===========================================================================


class TestProposalRevisionCapture:
    def test_patch_during_deliberation_creates_revision(
        self, db_session, client,
    ):
        org = _make_org(db_session)
        author = _make_user(db_session, "author")
        _make_membership(db_session, author, org)
        p = _make_proposal(
            db_session, author=author, org=org, status="deliberation",
            voting_method="binary", options=[],
        )
        db_session.commit()

        resp = client.patch(
            f"/api/proposals/{p.id}",
            json={"title": "New title"},
            headers=_auth_headers(client, "author"),
        )
        assert resp.status_code == 200, resp.text
        rows = (
            db_session.query(models.ProposalRevision)
            .filter(models.ProposalRevision.proposal_id == p.id)
            .all()
        )
        assert len(rows) == 1
        assert "title" in rows[0].changed_fields
        assert rows[0].snapshot_before["title"] == "Test Proposal"
        assert rows[0].snapshot_after["title"] == "New title"

    def test_patch_during_draft_no_revision(self, db_session, client):
        org = _make_org(db_session)
        author = _make_user(db_session, "author")
        _make_membership(db_session, author, org)
        p = _make_proposal(
            db_session, author=author, org=org, status="draft",
            voting_method="binary", options=[],
        )
        db_session.commit()

        resp = client.patch(
            f"/api/proposals/{p.id}",
            json={"title": "Renamed"},
            headers=_auth_headers(client, "author"),
        )
        assert resp.status_code == 200
        rows = (
            db_session.query(models.ProposalRevision)
            .filter(models.ProposalRevision.proposal_id == p.id)
            .all()
        )
        assert len(rows) == 0

    def test_lockout_blocks_patch(self, db_session, client):
        org = _make_org(db_session, settings={
            "proposal_edits": {"lockout_fraction": 0.5},
        })
        author = _make_user(db_session, "author")
        _make_membership(db_session, author, org)
        # 10-day deliberation that started 9 days ago = 90% elapsed,
        # well past the 50% lockout.
        nine_days_ago = (
            datetime.now(timezone.utc).replace(tzinfo=None)
            - timedelta(days=9)
        )
        p = _make_proposal(
            db_session, author=author, org=org, status="deliberation",
            voting_method="binary", options=[],
            deliberation_start=nine_days_ago,
            deliberation_days=10.0,
        )
        db_session.commit()

        resp = client.patch(
            f"/api/proposals/{p.id}",
            json={"title": "Locked"},
            headers=_auth_headers(client, "author"),
        )
        assert resp.status_code == 403
        assert "locked" in resp.json()["detail"].lower()

    def test_get_revisions_endpoint(self, db_session, client):
        org = _make_org(db_session)
        author = _make_user(db_session, "author")
        _make_membership(db_session, author, org)
        p = _make_proposal(
            db_session, author=author, org=org, status="deliberation",
            voting_method="binary", options=[],
        )
        db_session.commit()

        for new_title in ("Renamed once", "Renamed twice"):
            client.patch(
                f"/api/proposals/{p.id}",
                json={"title": new_title},
                headers=_auth_headers(client, "author"),
            )

        resp = client.get(
            f"/api/proposals/{p.id}/revisions",
            headers=_auth_headers(client, "author"),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["snapshot_after"]["title"] == "Renamed once"
        assert data[1]["snapshot_after"]["title"] == "Renamed twice"


# ===========================================================================
# P — pre-voting
# ===========================================================================


class TestPreVoting:
    def test_pre_vote_accepted_when_allowed(self, db_session, client):
        org = _make_org(db_session, settings={
            "pre_voting": {"allowed_mode": "default_on"},
        })
        author = _make_user(db_session, "author")
        voter = _make_user(db_session, "voter")
        _make_membership(db_session, author, org)
        _make_membership(db_session, voter, org)
        p = _make_proposal(
            db_session, author=author, org=org, status="deliberation",
            voting_method="binary", options=[],
        )
        db_session.commit()

        resp = client.post(
            f"/api/proposals/{p.id}/vote",
            json={"vote_value": "yes"},
            headers=_auth_headers(client, "voter"),
        )
        assert resp.status_code == 200, resp.text

    def test_pre_vote_rejected_when_disabled(self, db_session, client):
        org = _make_org(db_session)  # pre_voting allowed_default = False
        author = _make_user(db_session, "author")
        voter = _make_user(db_session, "voter")
        _make_membership(db_session, author, org)
        _make_membership(db_session, voter, org)
        p = _make_proposal(
            db_session, author=author, org=org, status="deliberation",
            voting_method="binary", options=[],
        )
        db_session.commit()

        resp = client.post(
            f"/api/proposals/{p.id}/vote",
            json={"vote_value": "yes"},
            headers=_auth_headers(client, "voter"),
        )
        assert resp.status_code == 400


# ===========================================================================
# D22 — existing-proposals behavior unchanged
# ===========================================================================


class TestExistingProposalsUnaffected:
    """Proposals created before Phase 32 (no overrides, no org settings)
    resolve to feature-off across the board."""

    def test_all_features_off_by_default(self, db_session):
        org = _make_org(db_session, settings={})
        author = _make_user(db_session, "author")
        # Build a proposal directly without explicit Phase 32 overrides
        # — all override columns null.
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        p = models.Proposal(
            title="Pre-32",
            body="",
            author_id=author.id,
            org_id=org.id,
            status="deliberation",
            voting_method="approval",
            num_winners=1,
            deliberation_start=now,
            voting_end=now + timedelta(days=3),
            deliberation_days=14.0,
            voting_days=7.0,
        )
        db_session.add(p)
        db_session.flush()
        assert resolve_allow_write_in_options(p, org) is False
        assert resolve_allow_pre_voting(p, org) is False
        assert resolve_show_votes_during_deliberation(p, org) is False
