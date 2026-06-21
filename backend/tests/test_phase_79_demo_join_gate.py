"""Phase 79 — demo user join gate (backend half of demo session fencing).

The frontend auto-logs demo users out before they can reach a join action;
this gate is the defense-in-depth backstop for a stale bundle or a direct
API call. The backend gate is the EXISTING ``ensure_can_join_real_org``
chokepoint (Phase 52a), already wired into both join endpoints
(``/{org_slug}/join`` and ``/{org_slug}/join-request``).

Key Phase 79 finding: the gate targets ``demo_stub`` ONLY. ``demo_stub`` is
the only provenance that marks a genuine demo identity (set by the demo
seed pipeline). ``backdoor`` provenance marks REAL users whose verification
was granted via the admin verification-state endpoint (routes/admin.py) —
those users must be able to join real orgs. These tests lock that boundary
so a future "tighten to backdoor too" change can't silently break the
verification-granting path (which the Phase 52 enforcement suite depends
on). Status stays 422 to preserve the structured-error contract.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

import models
import verification
from database import Base
from tests.conftest import make_user


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=engine
    )
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


def _make_org(db: Session, slug: str, *, is_demo: bool = False) -> models.Organization:
    org = models.Organization(
        name=slug.title(), slug=slug,
        description="", join_policy="open",
        governance_mode="single_steward",
        is_demo=is_demo,
        settings={"allowed_voting_methods": ["binary"]},
    )
    db.add(org)
    db.flush()
    return org


class TestDemoJoinGate:
    def test_demo_stub_user_blocked_from_real_org(self, db: Session):
        real_org = _make_org(db, "real-coop", is_demo=False)
        user = make_user(db, "demo_persona")
        user.verification_provenance = verification.PROV_DEMO_STUB
        with pytest.raises(HTTPException) as exc:
            verification.ensure_can_join_real_org(user, real_org)
        assert exc.value.status_code == 422
        assert "Demo accounts cannot join" in exc.value.detail

    def test_demo_stub_user_allowed_into_demo_org(self, db: Session):
        demo_org = _make_org(db, "demo-org", is_demo=True)
        user = make_user(db, "demo_persona_2")
        user.verification_provenance = verification.PROV_DEMO_STUB
        # Demo identities may roam demo orgs — should not raise.
        verification.ensure_can_join_real_org(user, demo_org)

    def test_backdoor_user_NOT_blocked_from_real_org(self, db: Session):
        # Phase 79 boundary lock: backdoor = a REAL user verified via the
        # admin verification-state endpoint. Must be able to join real orgs.
        # (The FE demo fence is a separate, FE-only concern.)
        real_org = _make_org(db, "real-coop-2", is_demo=False)
        user = make_user(db, "backdoor_verified_real_user")
        user.verification_provenance = verification.PROV_BACKDOOR
        # Should not raise.
        verification.ensure_can_join_real_org(user, real_org)

    def test_real_user_unaffected(self, db: Session):
        real_org = _make_org(db, "real-coop-3", is_demo=False)
        user = make_user(db, "real_user")
        user.verification_provenance = verification.PROV_DIDIT
        # Should not raise.
        verification.ensure_can_join_real_org(user, real_org)
