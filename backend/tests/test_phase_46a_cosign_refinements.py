"""Phase 46a — Cosign refinements (weight + window-end gate) tests.

Spec: phase46a_cosign_refinements_spec.md.

Verification matrix:
  - Item 1 weight resolution: direct signer = 1; delegate = 1 + topic-
    relevant inbound delegators; multiple signers don't double-count
    overlapping delegators; weight resolves live against the delegation
    graph (not snapshotted at signing time).
  - Item 1 agrees with the tally engine: a user's cosign weight equals
    the count of votes that would resolve to them in compute_tally.
  - Item 2 window-end gate: signing alone does NOT advance; the worker
    evaluates at cosign_expires_at. Live, not latched — a proposal that
    crossed mid-window but dropped back under fails at window-end.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
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

def _make_org(
    db: Session, slug: str, *,
    cosign_threshold: int = 3,
    cosign_expiry_hours: int = 168,
) -> models.Organization:
    org = models.Organization(
        name=slug.replace("-", " ").title(),
        slug=slug,
        description="",
        join_policy="open",
        settings={
            "default_deliberation_days": 1,
            "default_voting_days": 7,
            "default_pass_threshold": 0.50,
            "default_quorum_threshold": 0.40,
            "allowed_voting_methods": ["binary"],
            "cosign": {
                "threshold": cosign_threshold,
                "expiry_hours": cosign_expiry_hours,
            },
            # Phase 49a Cluster B — toggle replaces the legacy
            # ``proposal_creation_mode='cosign_required'`` column.
            "allow_cosign_petition": True,
        },
    )
    db.add(org)
    db.flush()
    return org


def _grant_member_proposal_create(db: Session, org: models.Organization) -> None:
    member_role = db.query(models.Role).filter(
        models.Role.org_id == org.id,
        models.Role.system_key == "member",
    ).first()
    existing = db.query(models.RolePermission).filter(
        models.RolePermission.role_id == member_role.id,
        models.RolePermission.permission_key == "proposal.create",
    ).first()
    if existing is None:
        db.add(models.RolePermission(
            role_id=member_role.id,
            permission_key="proposal.create",
            enabled=True,
        ))
    else:
        existing.enabled = True
    db.flush()


def _make_topic(db: Session, org: models.Organization, name: str) -> models.Topic:
    t = models.Topic(name=name, color="#3A7CA5", org_id=org.id)
    db.add(t)
    db.flush()
    return t


def _setup_petition(
    db: Session, slug: str, *,
    n_members: int = 5,
    cosign_threshold: int = 3,
    cosign_expiry_hours: int = 168,
):
    """Create a cosign-required org with steward + admin + n_members.
    The author of the petition is members[0]."""
    org = _make_org(
        db, slug,
        cosign_threshold=cosign_threshold,
        cosign_expiry_hours=cosign_expiry_hours,
    )
    steward = make_user(db, f"{slug}-steward")
    admin = make_user(db, f"{slug}-admin")
    members = [make_user(db, f"{slug}-m{i}") for i in range(n_members)]
    make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
    make_org_membership(db, org_id=org.id, user_id=admin.id, role="admin")
    for m in members:
        make_org_membership(db, org_id=org.id, user_id=m.id, role="member")
    # Phase 49a Cluster B — DON'T grant member ``proposal.create``
    # here. Under the new model the cosign-petition path is reserved
    # for members WITHOUT that grant (with the toggle on); granting
    # it would route them to direct creation and skip the cosign
    # state these tests are exercising.
    db.commit()
    return org, steward, admin, members


def _create_petition(
    client: TestClient, auth_for, org: models.Organization, author: models.User,
) -> str:
    r = client.post(
        f"/api/orgs/{org.slug}/proposals",
        headers=auth_for(author),
        json={
            "title": "P46a petition",
            "body": "Demonstrate weighted support.",
            "voting_method": "binary",
            "num_winners": 1,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _add_delegation(
    db: Session, *,
    delegator: models.User,
    delegate: models.User,
    org: models.Organization,
    topic_id: str | None = None,
    chain_behavior: str = "revert_direct",
) -> None:
    """Insert a Delegation row (delegator → delegate, optionally scoped
    to a topic). topic_id=None = global delegation."""
    db.add(models.Delegation(
        delegator_id=delegator.id,
        delegate_id=delegate.id,
        org_id=org.id,
        topic_id=topic_id,
        chain_behavior=chain_behavior,
    ))
    db.flush()


# ===========================================================================
# Item 1 — Weighted cosign resolution
# ===========================================================================

class TestCosignWeight:
    """Per the spec: weight = number of eligible voters whose vote on
    this proposal would resolve to ANY signer's ballot if the signers
    had cast direct ballots and no one else had."""

    def test_direct_signer_with_no_delegation_weight_1(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, members = _setup_petition(db, "p46aw-direct")
        pid = _create_petition(client, auth_for, org, members[0])
        from cosign import cosign_weight, signature_count
        # Author is the only signer (their implicit signature).
        assert signature_count(db, pid) == 1
        # No delegations exist → author's weight = 1 (themselves).
        proposal = db.get(models.Proposal, pid)
        assert cosign_weight(db, proposal) == 1

    def test_delegate_carries_inbound_delegators(
        self, client: TestClient, db: Session, auth_for,
    ):
        """If 3 members delegate globally to the author, the author's
        weight = 1 (themselves) + 3 (the delegators) = 4."""
        org, steward, admin, members = _setup_petition(db, "p46aw-deleg")
        author = members[0]
        # members[1..3] delegate globally to the author.
        for delegator in members[1:4]:
            _add_delegation(db, delegator=delegator, delegate=author, org=org)
        db.commit()
        pid = _create_petition(client, auth_for, org, author)
        from cosign import cosign_weight
        proposal = db.get(models.Proposal, pid)
        # author + 3 delegators = 4.
        assert cosign_weight(db, proposal) == 4

    def test_topic_scoped_delegation_only_counts_for_topic_matching_proposals(
        self, client: TestClient, db: Session, auth_for,
    ):
        """A topic-scoped delegation to the author for topic T should
        count toward the author's weight only on proposals tagged with
        topic T."""
        org, steward, admin, members = _setup_petition(db, "p46aw-topic")
        author = members[0]
        topic_a = _make_topic(db, org, "Topic A")
        topic_b = _make_topic(db, org, "Topic B")
        # members[1] delegates to author for topic_a only.
        _add_delegation(
            db, delegator=members[1], delegate=author, org=org,
            topic_id=topic_a.id,
        )
        db.commit()
        # Create a proposal tagged with topic_a → weight = 2 (author + 1).
        r = client.post(
            f"/api/orgs/{org.slug}/proposals",
            headers=auth_for(author),
            json={
                "title": "topic-a petition",
                "body": "x",
                "voting_method": "binary",
                "num_winners": 1,
                "topics": [{"topic_id": topic_a.id, "relevance": 1.0}],
            },
        )
        assert r.status_code == 201, r.text
        pid_a = r.json()["id"]
        # And one tagged with topic_b → weight = 1 (author only).
        r2 = client.post(
            f"/api/orgs/{org.slug}/proposals",
            headers=auth_for(author),
            json={
                "title": "topic-b petition",
                "body": "x",
                "voting_method": "binary",
                "num_winners": 1,
                "topics": [{"topic_id": topic_b.id, "relevance": 1.0}],
            },
        )
        assert r2.status_code == 201, r2.text
        pid_b = r2.json()["id"]
        from cosign import cosign_weight
        proposal_a = db.get(models.Proposal, pid_a)
        proposal_b = db.get(models.Proposal, pid_b)
        # The topic_a-scoped delegation flows to the topic_a proposal.
        assert cosign_weight(db, proposal_a) == 2
        # On a topic_b proposal, members[1] has no delegation that
        # applies → they don't count for the author.
        assert cosign_weight(db, proposal_b) == 1

    def test_multiple_signers_overlap_does_not_double_count(
        self, client: TestClient, db: Session, auth_for,
    ):
        """If member X delegates to BOTH potential signer A and signer B
        (different topics), and only one of A/B is signed, X counts
        once. If both A and B sign, X still counts once (the union of
        users whose resolution lands on any signer)."""
        org, steward, admin, members = _setup_petition(db, "p46aw-overlap")
        author = members[0]  # will sign at create time
        other_signer = members[1]
        delegator = members[2]
        # delegator → other_signer (global).
        _add_delegation(db, delegator=delegator, delegate=other_signer, org=org)
        db.commit()
        pid = _create_petition(client, auth_for, org, author)
        # other_signer signs.
        r = client.post(f"/api/proposals/{pid}/cosign", headers=auth_for(other_signer))
        assert r.status_code == 200
        from cosign import cosign_weight
        proposal = db.get(models.Proposal, pid)
        # weight = author (1) + other_signer (1, themselves) + delegator (1, via other_signer) = 3
        # delegator doesn't double-count even if both author and other_signer signed.
        assert cosign_weight(db, proposal) == 3

    def test_weight_resolves_live_against_delegation_graph_changes(
        self, client: TestClient, db: Session, auth_for,
    ):
        """The author's weight reflects the delegation graph AT
        EVALUATION TIME, not at signing time. A delegation added after
        signing must be picked up; one removed must drop the weight."""
        org, steward, admin, members = _setup_petition(db, "p46aw-live")
        author = members[0]
        pid = _create_petition(client, auth_for, org, author)
        from cosign import cosign_weight
        proposal = db.get(models.Proposal, pid)
        # Before any delegations: weight = 1 (author only).
        assert cosign_weight(db, proposal) == 1
        # Add a delegation AFTER signing.
        _add_delegation(db, delegator=members[1], delegate=author, org=org)
        db.commit()
        # Weight picks up the new delegation immediately.
        assert cosign_weight(db, proposal) == 2
        # Remove the delegation.
        d = db.query(models.Delegation).filter_by(delegator_id=members[1].id).first()
        db.delete(d)
        db.commit()
        # Weight drops back.
        assert cosign_weight(db, proposal) == 1


# ===========================================================================
# Item 2 — Window-end gate, not immediate advance
# ===========================================================================

class TestWindowEndGate:
    """Signing accrues weight; the worker decides advance-or-expire at
    cosign_expires_at against LIVE weight. Live = not latched: a
    proposal that crossed mid-window but dropped back under FAILS at
    window-end."""

    def test_signing_does_not_advance_mid_window(
        self, client: TestClient, db: Session, auth_for,
    ):
        """Even when threshold is reached mid-window, the proposal
        stays in deliberation until the worker fires at expiry."""
        org, steward, admin, members = _setup_petition(
            db, "p46aw-noimmedadv", cosign_threshold=2, cosign_expiry_hours=168,
        )
        author = members[0]
        pid = _create_petition(client, auth_for, org, author)
        # Sign with second member; weight=2, threshold=2 → 46a does
        # NOT advance.
        r = client.post(f"/api/proposals/{pid}/cosign", headers=auth_for(members[1]))
        assert r.status_code == 200, r.text
        proposal = db.get(models.Proposal, pid)
        assert proposal.status == "deliberation"
        assert proposal.voting_start is None

    def test_window_end_advances_when_threshold_met(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, members = _setup_petition(
            db, "p46aw-winend-adv", cosign_threshold=2, cosign_expiry_hours=1,
        )
        author = members[0]
        pid = _create_petition(client, auth_for, org, author)
        client.post(f"/api/proposals/{pid}/cosign", headers=auth_for(members[1]))
        # Backdate expiry.
        proposal = db.get(models.Proposal, pid)
        proposal.cosign_expires_at = (
            datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
        )
        db.commit()
        from sustained_majority_worker import resolve_due_cosign_proposals
        result = resolve_due_cosign_proposals(db)
        assert result == {"advanced": 1, "expired": 0}
        proposal = db.get(models.Proposal, pid)
        assert proposal.status == "voting"

    def test_window_end_expires_when_threshold_not_met(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, members = _setup_petition(
            db, "p46aw-winend-exp", cosign_threshold=3, cosign_expiry_hours=1,
        )
        author = members[0]
        pid = _create_petition(client, auth_for, org, author)
        # Only author signs → weight=1, threshold=3.
        proposal = db.get(models.Proposal, pid)
        proposal.cosign_expires_at = (
            datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
        )
        db.commit()
        from sustained_majority_worker import resolve_due_cosign_proposals
        result = resolve_due_cosign_proposals(db)
        assert result == {"advanced": 0, "expired": 1}
        proposal = db.get(models.Proposal, pid)
        assert proposal.status == "expired_unsigned"

    def test_window_end_NOT_latched_drop_back_under_expires(
        self, client: TestClient, db: Session, auth_for,
    ):
        """D2.3 — a proposal that crossed threshold mid-window but
        dropped back under fails at window-end. The gate evaluates
        LIVE weight at expiry, not the historical maximum."""
        org, steward, admin, members = _setup_petition(
            db, "p46aw-notlatched", cosign_threshold=2, cosign_expiry_hours=1,
        )
        author = members[0]
        pid = _create_petition(client, auth_for, org, author)
        # Sign with second member → weight crosses threshold mid-window.
        client.post(f"/api/proposals/{pid}/cosign", headers=auth_for(members[1]))
        # Withdraw → drops back to weight=1.
        client.request(
            "DELETE", f"/api/proposals/{pid}/cosign",
            headers=auth_for(members[1]),
        )
        # Backdate expiry.
        proposal = db.get(models.Proposal, pid)
        proposal.cosign_expires_at = (
            datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
        )
        db.commit()
        from sustained_majority_worker import resolve_due_cosign_proposals
        result = resolve_due_cosign_proposals(db)
        # Not latched on first crossing → expires.
        assert result == {"advanced": 0, "expired": 1}
        proposal = db.get(models.Proposal, pid)
        assert proposal.status == "expired_unsigned"

    def test_window_end_advance_emits_cosign_threshold_met_audit(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, members = _setup_petition(
            db, "p46aw-met-audit", cosign_threshold=1, cosign_expiry_hours=1,
        )
        author = members[0]
        pid = _create_petition(client, auth_for, org, author)
        proposal = db.get(models.Proposal, pid)
        proposal.cosign_expires_at = (
            datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
        )
        db.commit()
        from sustained_majority_worker import resolve_due_cosign_proposals
        resolve_due_cosign_proposals(db)
        actions = {
            row.action for row in db.query(models.AuditLog).filter(
                models.AuditLog.target_id == pid,
            ).all()
        }
        # cosign_threshold_met now fires at window-end (Phase 46a B2.5).
        assert "proposal.cosign_threshold_met" in actions

    def test_window_end_expire_emits_cosign_window_closed_unmet_audit(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, members = _setup_petition(
            db, "p46aw-unmet-audit", cosign_threshold=3, cosign_expiry_hours=1,
        )
        author = members[0]
        pid = _create_petition(client, auth_for, org, author)
        proposal = db.get(models.Proposal, pid)
        proposal.cosign_expires_at = (
            datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
        )
        db.commit()
        from sustained_majority_worker import resolve_due_cosign_proposals
        resolve_due_cosign_proposals(db)
        actions = {
            row.action for row in db.query(models.AuditLog).filter(
                models.AuditLog.target_id == pid,
            ).all()
        }
        assert "proposal.cosign_window_closed_unmet" in actions
