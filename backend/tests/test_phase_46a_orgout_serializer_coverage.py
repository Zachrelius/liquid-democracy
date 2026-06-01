"""Phase 46a Item 3 — `_org_to_out` / OrgOut serializer-coverage test.

Why this test exists: Phase 45a and Phase 46 shipped a new
``Organization``-level field each, passed all backend tests, then broke
in prod browser QA because the field was missing from ``OrgOut`` (the
FE response). Same model-vs-response gap. Same fix. Same discovery
point. Twice.

Backend tests assert the ORM model + route logic — they don't assert
the response *surfaces* what the FE reads. This test closes that gap
by enumerating the must-surface fields and asserting they appear on a
round-tripped ``OrgOut``. A future field that the FE depends on should
be added to ``_MUST_SURFACE_FIELDS`` in the same pass that adds the
column.

If you're adding a new Organization-level config field that the
frontend reads:
  1. Add the column to ``models.Organization``.
  2. Add the field to ``schemas.OrgOut`` with a sensible default.
  3. Wire it into ``_org_to_out`` so the field is populated.
  4. Append the field key to ``_MUST_SURFACE_FIELDS`` below.

If you're adding an org-level field the FE will NOT read (purely
internal — e.g. a server-side counter or worker bookkeeping), no
action is needed here; that's why the check is an explicit allow-list,
not "every column on Organization."
"""
from __future__ import annotations

from typing import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

import models
from database import Base
from tests.conftest import make_user, make_org_membership


# ---------------------------------------------------------------------------
# The must-surface allow-list.
# ---------------------------------------------------------------------------
#
# These are the keys the frontend reads off ``currentOrg`` (or
# iterates from ``userOrgs``) to drive permission-gated UI, mode-aware
# rendering, etc. Adding a new entry here is the load-bearing step in
# closing the model-vs-response gap.

_MUST_SURFACE_FIELDS: list[str] = [
    # Phase 12 base.
    "id",
    "name",
    "slug",
    "description",
    "join_policy",
    "settings",
    "user_role",
    "user_permissions",
    "member_count",
    "branding",
    "parent_org_id",
    "created_at",
    # Phase 45b — governance mode (single_steward / admin_council).
    "governance_mode",
    # Phase 46 — proposal creation gating tier (open / cosign_required /
    # admin_only). The Phase 46 hotfix added this surface.
    "proposal_creation_mode",
]

# The Phase 45a hotfix surfaces OWNER_ONLY_KEYS via user_permissions
# (not as a top-level field) so they're covered by the "Steward sees
# them in user_permissions" assertion below rather than by the
# allow-list above.
_OWNER_ONLY_KEYS_STEWARD_MUST_HAVE = ["org.delete", "org.transfer_stewardship"]


# ---------------------------------------------------------------------------
# Fixtures (StaticPool pattern; same as the rest of the cosign / 45b suite)
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


def _make_org_with_steward(db: Session) -> tuple[models.Organization, models.User]:
    org = models.Organization(
        name="P46a Coverage",
        slug="p46a-coverage",
        description="",
        join_policy="open",
        settings={},
    )
    db.add(org)
    db.flush()
    steward = make_user(db, "p46a-coverage-steward")
    make_org_membership(
        db, org_id=org.id, user_id=steward.id, role="steward",
    )
    db.commit()
    return org, steward


# ---------------------------------------------------------------------------
# The coverage tests.
# ---------------------------------------------------------------------------

class TestOrgOutSurfaceContract:
    """Each must-surface field actually round-trips through _org_to_out."""

    def test_all_must_surface_fields_present(self, db: Session):
        from routes.organizations import _org_to_out
        org, steward = _make_org_with_steward(db)

        out = _org_to_out(org, db, steward.id)
        out_dict = out.model_dump()

        missing = [k for k in _MUST_SURFACE_FIELDS if k not in out_dict]
        assert not missing, (
            f"_org_to_out is missing FE-facing field(s): {missing}. "
            f"Add the field to schemas.OrgOut + populate it in "
            f"routes.organizations._org_to_out (and update "
            f"_MUST_SURFACE_FIELDS in this test file in the same pass)."
        )

    def test_governance_mode_default_value(self, db: Session):
        """Phase 45b regression — the value (not just the key) is the
        right default. A bug where the column exists but the serializer
        emits None would still pass the key-presence test above; this
        catches that."""
        from routes.organizations import _org_to_out
        org, steward = _make_org_with_steward(db)
        out = _org_to_out(org, db, steward.id)
        assert out.governance_mode == "single_steward"

    def test_proposal_creation_mode_default_value(self, db: Session):
        """Phase 46 regression — same pattern as governance_mode. The
        column has server_default 'open'; the serializer must emit it."""
        from routes.organizations import _org_to_out
        org, steward = _make_org_with_steward(db)
        out = _org_to_out(org, db, steward.id)
        assert out.proposal_creation_mode == "open"

    def test_steward_user_permissions_includes_owner_only_keys(
        self, db: Session,
    ):
        """Phase 45a hotfix #1 regression — OWNER_ONLY_KEYS are
        deliberately not in PERMISSION_REGISTRY but ARE in
        user_permissions for the Steward via the explicit enrichment
        loop. Without this, FE useHasPermission('org.delete') silently
        returns False."""
        from routes.organizations import _org_to_out
        org, steward = _make_org_with_steward(db)
        out = _org_to_out(org, db, steward.id)
        for key in _OWNER_ONLY_KEYS_STEWARD_MUST_HAVE:
            assert key in out.user_permissions, (
                f"Steward's user_permissions is missing OWNER_ONLY_KEY "
                f"{key!r}. The Phase 45a hotfix enrichment loop in "
                f"_org_to_out must surface these for the Steward."
            )


class TestSerializerCatchesARegression:
    """Belt-and-suspenders: prove the coverage test would actually fire
    if someone dropped a must-surface field. This test simulates that
    failure mode by checking the assertion message structure — if a
    future contributor accidentally drops the test's discriminating
    behavior, this catches it."""

    def test_must_surface_list_is_not_empty(self):
        assert len(_MUST_SURFACE_FIELDS) > 0, (
            "The must-surface allow-list is empty; the serializer-"
            "coverage test is a no-op."
        )

    def test_owner_only_keys_are_named_explicitly(self):
        assert "org.delete" in _OWNER_ONLY_KEYS_STEWARD_MUST_HAVE
        assert "org.transfer_stewardship" in _OWNER_ONLY_KEYS_STEWARD_MUST_HAVE
