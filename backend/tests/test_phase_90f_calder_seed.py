"""Phase 90f — Calder Tool & Machine Works demo-org seed pipeline.

Asserts the weighted-governance bible seeds correctly and survives the daily
wipe/reseed cycle (the §1 critical proof — a second reseed failing on the
(org_id, period_key) partial-unique index is the symptom of a wipe-list miss).
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base


@pytest.fixture(scope="function")
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def _seed(db):
    from demo_content.calder_bible import CALDER_BIBLE
    from demo_content.seed_pipeline import seed_org_from_bible
    seed_org_from_bible(db, CALDER_BIBLE)
    db.commit()
    return db.query(models.Organization).filter_by(slug="calder-tool").first()


def test_calder_weighted_config_and_cast(db):
    from org_config import get_weighted_voting_config, outstanding_total
    org = _seed(db)
    cfg = get_weighted_voting_config(org)
    assert cfg["enabled"] is True
    assert cfg["issuance_mode"] == "member_vote"
    assert cfg["authorized_total"] == 10000
    assert cfg["show_event_parties"] is True
    assert cfg["transfers_enabled"] is True
    # Exactly the 14 named owners (no filler padding), canonical total.
    assert db.query(models.OrgMembership).filter_by(
        org_id=org.id, status="active").count() == 14
    assert outstanding_total(db, org) == 7900


def test_calder_rules_ledger_and_showcase_proposals(db):
    org = _seed(db)
    # Two distribution rules + five backdated ledger rows.
    assert db.query(models.ShareDistributionRule).filter_by(org_id=org.id).count() == 2
    assert db.query(models.ShareEvent).filter_by(org_id=org.id).count() == 5
    # A vote-gated issuance proposal (90e) with a cap_raise payload.
    iss = db.query(models.Proposal).filter_by(org_id=org.id, is_issuance=True).first()
    assert iss is not None
    assert iss.issuance_payload["action"] == "cap_raise"
    assert iss.issuance_payload["params"]["authorized_total"] == 12000
    # A one-member-one-vote approval proposal (90c).
    opm = db.query(models.Proposal).filter_by(
        org_id=org.id, count_mode="one_per_member").first()
    assert opm is not None
    # A member with weight 0 (the zero-share case shown honestly).
    zero = [m for m in db.query(models.OrgMembership).filter_by(org_id=org.id).all()
            if m.voting_weight == 0]
    assert len(zero) == 1


def test_calder_wipe_reseed_twice_clean(db):
    """§1 — wipe→reseed twice; the second reseed must not collide."""
    from demo_reset_job import _wipe_demo_orgs
    from org_config import outstanding_total
    org = _seed(db)
    for _ in range(2):
        _wipe_demo_orgs(db, [org])
        db.commit()
        org = _seed(db)
    # Still exactly the canonical cast + total after repeated cycles.
    assert db.query(models.OrgMembership).filter_by(
        org_id=org.id, status="active").count() == 14
    assert outstanding_total(db, org) == 7900
    # No duplicate share events accumulated across resets.
    assert db.query(models.ShareEvent).filter_by(org_id=org.id).count() == 5
