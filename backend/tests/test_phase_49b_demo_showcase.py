"""Phase 49b — Cedar Hollow governance showcase tests.

Verifies that the bible-driven seed materializes:
  * Three custom Phase 47 titles (President / Secretary / Treasurer)
    with the locked role bindings (steward / admin / admin).
  * Holder assignments via ``OrgTitleAssignment`` rows.
  * Treasurer's ``fill_method='elected'`` (B2).
  * Org-level ``settings.elections.enabled=True`` +
    ``settings.allow_cosign_petition=True``.
  * A cosign-petition Proposal in deliberation state with the seeded
    sub-threshold signatures (B3).
  * The post-reset cycle reproduces the entire showcase (B4).

The seed pipeline is exercised against an in-memory SQLite — fast +
isolated. The reset-cycle test runs the wipe helper directly + re-runs
the seed so we can assert the "no half-state" property without
needing the demo_reset_job's schedule-gate logic.
"""
from __future__ import annotations

from typing import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

import models
from database import Base


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


def _seed_hoa(db: Session):
    """Run the HOA seed and return the org row."""
    from demo_content.hoa_bible import HOA_BIBLE
    from demo_content.seed_pipeline import seed_org_from_bible
    seed_org_from_bible(db, HOA_BIBLE)
    return db.query(models.Organization).filter_by(
        slug="demo-cedar-hollow",
    ).one()


def _wipe_hoa(db: Session) -> None:
    """Run the wipe path against the seeded HOA org."""
    org = db.query(models.Organization).filter_by(
        slug="demo-cedar-hollow",
    ).first()
    if org is None:
        return
    from demo_reset_job import _wipe_demo_orgs
    _wipe_demo_orgs(db, [org])
    db.flush()


def _titles_by_name(db: Session, org_id: str) -> dict[str, models.OrgTitle]:
    rows = db.query(models.OrgTitle).filter_by(org_id=org_id).all()
    return {r.name: r for r in rows}


def _user_role_key(db: Session, org_id: str, user_id: str) -> str | None:
    m = db.query(models.OrgMembership).filter_by(
        org_id=org_id, user_id=user_id, status="active",
    ).first()
    if m is None or m.role_id is None:
        return None
    return db.get(models.Role, m.role_id).system_key


class TestB1TitlesSeededWithBindings:
    def test_president_secretary_treasurer_present_with_correct_bindings(
        self, db: Session,
    ):
        org = _seed_hoa(db)
        titles = _titles_by_name(db, org.id)
        assert "President" in titles
        assert "Secretary" in titles
        assert "Treasurer" in titles
        assert titles["President"].bound_role == "steward"
        assert titles["Secretary"].bound_role == "admin"
        assert titles["Treasurer"].bound_role == "admin"
        assert titles["President"].is_system is False
        # System titles preserved alongside the custom ones (Phase 47
        # D6 — uneditable label layer over role).
        assert "Steward" in titles
        assert "Admin" in titles
        assert titles["Steward"].is_system is True

    def test_titles_assigned_to_correct_holders_and_roles_bumped(
        self, db: Session,
    ):
        org = _seed_hoa(db)
        titles = _titles_by_name(db, org.id)
        # Janet → President → steward.
        janet = db.query(models.User).filter_by(username="janet_reilly").one()
        assert _user_role_key(db, org.id, janet.id) == "steward"
        a = db.query(models.OrgTitleAssignment).filter_by(
            title_id=titles["President"].id, user_id=janet.id,
        ).one()
        assert a is not None
        # Brenda → Secretary → admin (bumped from moderator).
        # Non-cross-org users keep the bible_user_id as their
        # username (see _underlying_username).
        brenda = db.query(models.User).filter_by(username="hoa_brenda").one()
        assert _user_role_key(db, org.id, brenda.id) == "admin"
        # Linda → Treasurer → admin (bumped from moderator).
        linda = db.query(models.User).filter_by(username="hoa_linda").one()
        assert _user_role_key(db, org.id, linda.id) == "admin"

    def test_floor_preserved_exactly_one_steward(self, db: Session):
        org = _seed_hoa(db)
        stewards = db.query(models.OrgMembership).join(
            models.Role, models.Role.id == models.OrgMembership.role_id,
        ).filter(
            models.OrgMembership.org_id == org.id,
            models.OrgMembership.status == "active",
            models.Role.system_key == "steward",
        ).all()
        assert len(stewards) == 1


class TestB2ElectionsEnabledOnTreasurer:
    def test_treasurer_fill_method_elected(self, db: Session):
        org = _seed_hoa(db)
        treasurer = _titles_by_name(db, org.id)["Treasurer"]
        assert treasurer.fill_method == "elected"

    def test_president_fill_method_assigned(self, db: Session):
        """Per spec: leave President stable so the top-of-org doesn't
        churn each reset."""
        org = _seed_hoa(db)
        pres = _titles_by_name(db, org.id)["President"]
        assert pres.fill_method == "assigned"

    def test_elections_enabled_at_org_level(self, db: Session):
        org = _seed_hoa(db)
        cfg = (org.settings or {}).get("elections") or {}
        assert cfg.get("enabled") is True


class TestB3CosignPetitionInGatheringState:
    def test_petition_seeded_with_correct_signatures(self, db: Session):
        org = _seed_hoa(db)
        petition = db.query(models.Proposal).filter_by(
            org_id=org.id, title="Petition: Add bike rack at the pool entrance",
        ).one()
        assert petition.is_cosign_gated is True
        assert petition.status == "deliberation"
        assert petition.cosign_threshold_snapshot == 5
        sigs = db.query(models.ProposalCosignature).filter_by(
            proposal_id=petition.id,
        ).all()
        # Author + 2 named co-signers = 3, below the threshold of 5.
        assert len(sigs) == 3

    def test_allow_cosign_petition_toggle_on(self, db: Session):
        org = _seed_hoa(db)
        assert (org.settings or {}).get("allow_cosign_petition") is True


class TestB4ResetCycleReproducesShowcase:
    """The daily reset must reproduce the whole showcase — wipe +
    re-seed leaves the same end-state, NOT a half-state."""

    def test_wipe_clears_custom_titles_and_petition(self, db: Session):
        org = _seed_hoa(db)
        org_id = org.id
        # Pre-wipe sanity.
        assert (
            db.query(models.OrgTitle).filter_by(
                org_id=org_id, is_system=False,
            ).count() == 3
        )
        assert (
            db.query(models.Proposal).filter_by(
                org_id=org_id, is_cosign_gated=True,
            ).count() == 1
        )
        _wipe_hoa(db)
        db.expire_all()
        # Custom titles + petition gone; system titles survive.
        assert (
            db.query(models.OrgTitle).filter_by(
                org_id=org_id, is_system=False,
            ).count() == 0
        )
        assert (
            db.query(models.OrgTitle).filter_by(
                org_id=org_id, is_system=True,
            ).count() == 2
        )
        assert (
            db.query(models.Proposal).filter_by(
                org_id=org_id, is_cosign_gated=True,
            ).count() == 0
        )

    def test_reseed_after_wipe_restores_showcase(self, db: Session):
        org = _seed_hoa(db)
        org_id = org.id
        _wipe_hoa(db)
        # Re-run the seed.
        from demo_content.hoa_bible import HOA_BIBLE
        from demo_content.seed_pipeline import seed_org_from_bible
        seed_org_from_bible(db, HOA_BIBLE)
        db.expire_all()
        # All three titles back with correct bindings + assignments.
        titles = _titles_by_name(db, org_id)
        assert titles["President"].bound_role == "steward"
        assert titles["Secretary"].bound_role == "admin"
        assert titles["Treasurer"].bound_role == "admin"
        # Petition back with the same signature count.
        petition = db.query(models.Proposal).filter_by(
            org_id=org_id, is_cosign_gated=True,
        ).one()
        sigs = db.query(models.ProposalCosignature).filter_by(
            proposal_id=petition.id,
        ).count()
        assert sigs == 3
