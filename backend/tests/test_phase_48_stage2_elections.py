"""Phase 48 Stage 2 — Multi-seat council elections + admin-seat
elections + slate config.

Verification matrix items (per spec):
  - Admin-seat single + multi-seat elections in both governance modes.
  - Multi-winner tally produces N winners → N seats; STV path
    correct; floor respected.
  - Slate behavior config (D10): fill_vacancies vs refresh_slate, and
    refresh_slate respects the floor.
  - Auto-win shortcut generalizes to "candidates <= num_winners → all
    win" (D6).
"""
from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

import models
from main import app
from database import Base, get_db
from tests.conftest import make_user, make_org_membership


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db() -> Iterator[Session]:
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


@pytest.fixture()
def client(db: Session) -> Iterator[TestClient]:
    def _override():
        try:
            yield db
        finally:
            pass
    app.dependency_overrides[get_db] = _override
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def auth_for(db: Session):
    import auth as auth_utils

    def _headers(user: models.User) -> dict[str, str]:
        token = auth_utils.create_access_token(user.id)
        return {"Authorization": f"Bearer {token}"}
    return _headers


# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------

def _make_org(db: Session, slug: str) -> models.Organization:
    from org_titles import seed_system_titles_for_org
    from role_seed import seed_default_roles_for_org

    org = models.Organization(
        name=slug.title(),
        slug=slug,
        description="",
        join_policy="open",
        settings={
            "default_deliberation_days": 3,
            "default_voting_days": 7,
            "default_pass_threshold": 0.50,
            "default_quorum_threshold": 0.0,
            "allowed_voting_methods": ["binary", "approval", "ranked_choice"],
            "elections": {"enabled": True},
        },
    )
    db.add(org)
    db.flush()
    seed_default_roles_for_org(db, org.id)
    seed_system_titles_for_org(db, org.id)
    db.commit()
    return org


def _create_multi_council_title(
    db: Session, org: models.Organization, *,
    max_holders: int | None = None,
) -> models.OrgTitle:
    """Create a custom multi-holder Council Member title bound to
    admin. ``fill_method='elected'`` so the open-election endpoint
    accepts it."""
    title = models.OrgTitle(
        org_id=org.id,
        name="Council Member",
        bound_role="admin",
        cardinality_mode="multi",
        max_holders=max_holders,
        fill_method="elected",
        is_system=False,
        display_order=50,
    )
    db.add(title)
    db.flush()
    db.commit()
    return title


def _setup_council_org(db: Session, slug: str = "p48s2council"):
    """Steward + 1 admin + 5 members; Council Member custom title
    available with bound admin."""
    org = _make_org(db, slug)
    steward = make_user(db, f"{slug}-steward")
    admin = make_user(db, f"{slug}-admin")
    members = [make_user(db, f"{slug}-m{i}") for i in range(5)]
    make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
    make_org_membership(db, org_id=org.id, user_id=admin.id, role="admin")
    for m in members:
        make_org_membership(db, org_id=org.id, user_id=m.id, role="member")
    db.commit()
    council_title = _create_multi_council_title(db, org)
    return org, steward, admin, members, council_title


def _advance(client: TestClient, auth_for, proposal_id, actor):
    return client.post(
        f"/api/proposals/{proposal_id}/advance",
        headers=auth_for(actor),
        json={},
    )


def _user_role(db: Session, org_id: str, user_id: str) -> str | None:
    m = db.query(models.OrgMembership).filter_by(
        org_id=org_id, user_id=user_id, status="active",
    ).first()
    if m is None or m.role_id is None:
        return None
    return db.get(models.Role, m.role_id).system_key


def _is_holder(db: Session, title_id: str, user_id: str) -> bool:
    return db.query(models.OrgTitleAssignment).filter_by(
        title_id=title_id, user_id=user_id,
    ).first() is not None


# ===========================================================================
# Multi-winner mechanics
# ===========================================================================

class TestMultiWinnerCouncilElection:
    """N candidates declared, N winners installed. Bound-role grants
    flow through 47's machinery."""

    def test_open_multi_winner_election(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, members, council_title = _setup_council_org(db, "p48s2open")
        r = client.post(
            f"/api/orgs/{org.slug}/elections",
            headers=auth_for(admin),
            json={
                "title_id": council_title.id,
                "voting_method": "ranked_choice",
                "num_winners": 3,
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["is_election"] is True
        assert body["num_winners"] == 3
        assert body["voting_method"] == "ranked_choice"

    def test_multi_winner_auto_win_when_candidates_le_num_winners(
        self, client: TestClient, db: Session, auth_for,
    ):
        """D6 generalization: if candidates <= num_winners, all win
        (they stood; nobody contested for the remaining seats).
        Bound role granted to each."""
        org, steward, admin, members, council_title = _setup_council_org(db, "p48s2auto")
        r = client.post(
            f"/api/orgs/{org.slug}/elections",
            headers=auth_for(admin),
            json={
                "title_id": council_title.id,
                "voting_method": "ranked_choice",
                "num_winners": 3,
            },
        )
        pid = r.json()["id"]
        # Two members declare for 3 seats → both auto-win.
        client.post(
            f"/api/orgs/{org.slug}/elections/{pid}/candidacies",
            headers=auth_for(members[0]),
        )
        client.post(
            f"/api/orgs/{org.slug}/elections/{pid}/candidacies",
            headers=auth_for(members[1]),
        )
        _advance(client, auth_for, pid, admin)  # → voting
        _advance(client, auth_for, pid, admin)  # → close
        db.expire_all()
        # Both members hold the title + the bound admin role.
        assert _is_holder(db, council_title.id, members[0].id)
        assert _is_holder(db, council_title.id, members[1].id)
        assert _user_role(db, org.id, members[0].id) == "admin"
        assert _user_role(db, org.id, members[1].id) == "admin"
        # The unfilled third seat is just unfilled — no error.

    def test_multi_winner_creates_proposal_options_per_candidate_on_advance(
        self, client: TestClient, db: Session, auth_for,
    ):
        """When the election advances to voting, ProposalOption rows
        are created from the candidate set with label=user_id."""
        org, steward, admin, members, council_title = _setup_council_org(db, "p48s2opts")
        r = client.post(
            f"/api/orgs/{org.slug}/elections",
            headers=auth_for(admin),
            json={
                "title_id": council_title.id,
                "voting_method": "ranked_choice",
                "num_winners": 2,
            },
        )
        pid = r.json()["id"]
        for m in members[:3]:
            client.post(
                f"/api/orgs/{org.slug}/elections/{pid}/candidacies",
                headers=auth_for(m),
            )
        _advance(client, auth_for, pid, admin)  # → voting
        db.expire_all()
        proposal = db.get(models.Proposal, pid)
        labels = {o.label for o in proposal.options}
        assert labels == {m.id for m in members[:3]}


# ===========================================================================
# Slate mode (D10)
# ===========================================================================

class TestSlateMode:
    def test_fill_vacancies_does_not_remove_existing_holders(
        self, client: TestClient, db: Session, auth_for,
    ):
        """The default slate mode adds winners to existing holders."""
        org, steward, admin, members, council_title = _setup_council_org(db, "p48s2fillvac")
        # Pre-seed members[0] as a current Council Member holder via
        # direct assignment (simulates an org that has used the seat
        # by appointment before).
        db.add(models.OrgTitleAssignment(
            title_id=council_title.id, user_id=members[0].id,
        ))
        # And bump their role to admin to reflect the bound role.
        m0 = db.query(models.OrgMembership).filter_by(
            org_id=org.id, user_id=members[0].id,
        ).one()
        admin_role = db.query(models.Role).filter_by(
            org_id=org.id, system_key="admin",
        ).one()
        m0.role_id = admin_role.id
        db.commit()
        # Open an election for 2 seats; members[1] + members[2] declare.
        r = client.post(
            f"/api/orgs/{org.slug}/elections",
            headers=auth_for(admin),
            json={
                "title_id": council_title.id,
                "voting_method": "ranked_choice",
                "num_winners": 2,
                "slate_mode": "fill_vacancies",
            },
        )
        pid = r.json()["id"]
        client.post(
            f"/api/orgs/{org.slug}/elections/{pid}/candidacies",
            headers=auth_for(members[1]),
        )
        client.post(
            f"/api/orgs/{org.slug}/elections/{pid}/candidacies",
            headers=auth_for(members[2]),
        )
        _advance(client, auth_for, pid, admin)
        _advance(client, auth_for, pid, admin)
        db.expire_all()
        # Pre-existing holder (members[0]) STILL has the title.
        assert _is_holder(db, council_title.id, members[0].id)
        # New winners also have it.
        assert _is_holder(db, council_title.id, members[1].id)
        assert _is_holder(db, council_title.id, members[2].id)

    def test_refresh_slate_removes_existing_holders_not_in_winners(
        self, client: TestClient, db: Session, auth_for,
    ):
        """refresh_slate wipes current holders of the title before
        installing the winners. Current holders who are ALSO winners
        keep their seat (no-op rather than churn-then-restore)."""
        org, steward, admin, members, council_title = _setup_council_org(db, "p48s2refresh")
        # Seed members[0] + members[1] as pre-existing holders.
        for m in (members[0], members[1]):
            db.add(models.OrgTitleAssignment(
                title_id=council_title.id, user_id=m.id,
            ))
            mb = db.query(models.OrgMembership).filter_by(
                org_id=org.id, user_id=m.id,
            ).one()
            admin_role = db.query(models.Role).filter_by(
                org_id=org.id, system_key="admin",
            ).one()
            mb.role_id = admin_role.id
        db.commit()
        # New election: members[1] (incumbent) + members[2] declare;
        # members[0] doesn't run (will be wiped by refresh_slate).
        r = client.post(
            f"/api/orgs/{org.slug}/elections",
            headers=auth_for(admin),
            json={
                "title_id": council_title.id,
                "voting_method": "ranked_choice",
                "num_winners": 2,
                "slate_mode": "refresh_slate",
            },
        )
        pid = r.json()["id"]
        client.post(
            f"/api/orgs/{org.slug}/elections/{pid}/candidacies",
            headers=auth_for(members[1]),
        )
        client.post(
            f"/api/orgs/{org.slug}/elections/{pid}/candidacies",
            headers=auth_for(members[2]),
        )
        _advance(client, auth_for, pid, admin)
        _advance(client, auth_for, pid, admin)
        db.expire_all()
        # members[0] no longer a holder (refresh wiped them).
        assert not _is_holder(db, council_title.id, members[0].id)
        # members[1] still holder (kept across refresh).
        assert _is_holder(db, council_title.id, members[1].id)
        # members[2] is new holder.
        assert _is_holder(db, council_title.id, members[2].id)


# ===========================================================================
# Floor preservation (council mode regression)
# ===========================================================================

class TestFloorPreservedAcrossMultiWinner:
    def test_multi_winner_install_doesnt_violate_floor(
        self, client: TestClient, db: Session, auth_for,
    ):
        """After a multi-winner election closes, the governance floor
        still holds (≥1 governor per mode)."""
        org, steward, admin, members, council_title = _setup_council_org(db, "p48s2floor")
        r = client.post(
            f"/api/orgs/{org.slug}/elections",
            headers=auth_for(admin),
            json={
                "title_id": council_title.id,
                "voting_method": "ranked_choice",
                "num_winners": 2,
            },
        )
        pid = r.json()["id"]
        client.post(
            f"/api/orgs/{org.slug}/elections/{pid}/candidacies",
            headers=auth_for(members[0]),
        )
        client.post(
            f"/api/orgs/{org.slug}/elections/{pid}/candidacies",
            headers=auth_for(members[1]),
        )
        _advance(client, auth_for, pid, admin)
        _advance(client, auth_for, pid, admin)
        from governance import count_active_governors
        db.expire_all()
        assert count_active_governors(db, org) >= 1
