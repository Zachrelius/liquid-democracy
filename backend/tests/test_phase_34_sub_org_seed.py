"""Phase 34 — Cedar Court Condos sub-org seed tests.

Covers:
- B1: HOA bible's voting_methods_used surfaces into
  Organization.settings['allowed_voting_methods'] (rcv → ranked_choice).
- B2: Cedar Court Condos sub-org seeds with parent_org_id, 18 sub-org
  memberships (SubOrgMembership), 3 topics scoped via sub_org_id,
  2 proposals with sub_org_id, 3 sub-org-scoped DelegateProfiles.
- B3: Linda + Brenda + Yolanda delegations on General Issues carry the
  sub_org_id reference — exercises Phase 18's sub_org_id retrofit on
  Delegation.
- Schema: SubOrg dataclass importable.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
import models  # noqa: F401 — register ORM classes
from demo_content.hoa_bible import HOA_BIBLE
from demo_content.seed_pipeline import ORG_SEED_CONFIG, seed_org_from_bible


@pytest.fixture(scope="module")
def seeded_session():
    """Spin up a fresh in-memory SQLite, seed the HOA bible end-to-end,
    return a session for assertions. Module-scoped to amortize the
    ~30s seed work across tests."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False)
    session = SessionLocal()
    cfg = ORG_SEED_CONFIG.get(HOA_BIBLE.slug, {})
    seed_org_from_bible(session, HOA_BIBLE, cfg)
    session.commit()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


# ============================================================================
# Schema
# ============================================================================


def test_schema_has_sub_org_dataclass():
    from demo_content.schema import SubOrg  # noqa: F401


# ============================================================================
# B1 — voting_methods_used → allowed_voting_methods
# ============================================================================


def test_b1_allowed_voting_methods_seeded(seeded_session):
    org = seeded_session.query(models.Organization).filter(
        models.Organization.slug == "demo-cedar-hollow",
    ).first()
    assert org is not None
    allowed = (org.settings or {}).get("allowed_voting_methods")
    assert allowed is not None
    assert "binary" in allowed
    assert "approval" in allowed
    assert "ranked_choice" in allowed
    assert "rcv" not in allowed


# ============================================================================
# B2 — sub-org structure
# ============================================================================


def test_b2_sub_org_organization_row(seeded_session):
    parent = seeded_session.query(models.Organization).filter(
        models.Organization.slug == "demo-cedar-hollow",
    ).first()
    sub = seeded_session.query(models.Organization).filter(
        models.Organization.slug == "cedar-court-condos",
    ).first()
    assert sub is not None
    assert sub.parent_org_id == parent.id
    assert sub.name == "Cedar Court Condos"
    assert sub.is_demo is True


def test_b2_sub_org_18_memberships(seeded_session):
    sub = seeded_session.query(models.Organization).filter(
        models.Organization.slug == "cedar-court-condos",
    ).first()
    memberships = seeded_session.query(models.SubOrgMembership).filter(
        models.SubOrgMembership.sub_org_id == sub.id,
    ).all()
    assert len(memberships) == 18


def test_b2_karen_is_sub_org_admin(seeded_session):
    sub = seeded_session.query(models.Organization).filter(
        models.Organization.slug == "cedar-court-condos",
    ).first()
    karen = seeded_session.query(models.User).filter(
        models.User.username == "hoa_karen",
    ).first()
    karen_mem = seeded_session.query(models.SubOrgMembership).filter(
        models.SubOrgMembership.user_id == karen.id,
        models.SubOrgMembership.sub_org_id == sub.id,
    ).first()
    assert karen_mem is not None
    role = seeded_session.get(models.Role, karen_mem.role_id)
    assert role.system_key == "admin"


def test_b2_sub_org_3_topics(seeded_session):
    sub = seeded_session.query(models.Organization).filter(
        models.Organization.slug == "cedar-court-condos",
    ).first()
    topics = seeded_session.query(models.Topic).filter(
        models.Topic.sub_org_id == sub.id,
    ).all()
    names = sorted([t.name for t in topics])
    assert names == ["Building Maintenance", "General Issues", "Special Assessments"]
    for t in topics:
        assert t.org_id == sub.parent_org_id
        assert t.sub_org_id == sub.id


def test_b2_sub_org_2_proposals(seeded_session):
    sub = seeded_session.query(models.Organization).filter(
        models.Organization.slug == "cedar-court-condos",
    ).first()
    proposals = seeded_session.query(models.Proposal).filter(
        models.Proposal.sub_org_id == sub.id,
    ).all()
    assert len(proposals) == 2
    statuses = {p.status for p in proposals}
    assert {"voting", "deliberation"} <= statuses


def test_b2_sub_org_delegate_profiles(seeded_session):
    sub = seeded_session.query(models.Organization).filter(
        models.Organization.slug == "cedar-court-condos",
    ).first()
    dps = seeded_session.query(models.DelegateProfile).filter(
        models.DelegateProfile.sub_org_id == sub.id,
    ).all()
    assert len(dps) == 3
    by_user = {}
    for dp in dps:
        user = seeded_session.get(models.User, dp.user_id)
        by_user[user.username] = dp
    assert by_user["marcus_pham"].visibility == "public_accepting"
    assert by_user["hoa_karen"].visibility == "public_accepting"
    assert by_user["hoa_yolanda"].visibility == "public"


# ============================================================================
# B3 — topic relocation + sub_org_id on Delegation
# ============================================================================


def test_b3_delegations_carry_sub_org_id(seeded_session):
    sub = seeded_session.query(models.Organization).filter(
        models.Organization.slug == "cedar-court-condos",
    ).first()
    delegations = seeded_session.query(models.Delegation).filter(
        models.Delegation.sub_org_id == sub.id,
    ).all()
    assert len(delegations) == 3
    for d in delegations:
        topic = seeded_session.get(models.Topic, d.topic_id)
        assert topic.name == "General Issues"
        assert topic.sub_org_id == sub.id


def test_b3_cedar_court_issues_removed_from_main_org(seeded_session):
    parent = seeded_session.query(models.Organization).filter(
        models.Organization.slug == "demo-cedar-hollow",
    ).first()
    main_cc = seeded_session.query(models.Topic).filter(
        models.Topic.org_id == parent.id,
        models.Topic.sub_org_id.is_(None),
        models.Topic.name == "Cedar Court Issues",
    ).first()
    assert main_cc is None
