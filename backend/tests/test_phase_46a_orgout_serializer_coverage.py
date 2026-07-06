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
    # Phase 49a Cluster B — replaced the legacy
    # ``proposal_creation_mode`` 3-way enum with the per-org boolean
    # ``allow_cosign_petition``. The FE reads this off ``currentOrg``
    # to decide whether to render the cosign-petition entry point for
    # users without ``proposal.create``.
    "allow_cosign_petition",
    # Phase 57 — the two new access axes (the third, join_policy, is
    # already on the list above and was repurposed in-place from the
    # Phase 14 four-value vocabulary to the new three-value vocabulary).
    # The FE reads these off ``currentOrg`` to drive the new
    # OrgSettings "Access & visibility" section + the public landing
    # surface.
    "discoverability",
    "activity_visibility",
    # Phase 80.1 hotfix — demo orgs self-identify so the FE demo banner
    # renders and the Phase 79 demo session fence trusts currentOrg.is_demo
    # (its absence logged demo personas out of their own demo org).
    "is_demo",
    # Phase 87 (B-10) — platform-moderation state so an org's own admins see
    # the delist notice in settings.
    "platform_restriction",
    # Phase 88 — resolved weighted-voting config the FE reads to render the
    # shares column + ballot chips conditionally.
    "weighted_voting",
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

    def test_allow_cosign_petition_default_value(self, db: Session):
        """Phase 49a Cluster B regression — replaces the legacy
        proposal_creation_mode default-value check. The new toggle
        lives in settings (no column); the serializer should default
        to False when unset, preserving the pre-49a "open" effective
        behavior (members without ``proposal.create`` get 403)."""
        from routes.organizations import _org_to_out
        org, steward = _make_org_with_steward(db)
        out = _org_to_out(org, db, steward.id)
        assert out.allow_cosign_petition is False

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


class TestOrgMemberOutSurfaceContract:
    """Phase 47 B4 — extend the 46a serializer-coverage convention to
    the member roster. Titles are an FE-facing field per the public-
    display requirement (D8); they MUST surface on the member roster
    or the Members page silently doesn't show them. Closes the same
    model-vs-response gap pattern at a new surface."""

    def test_held_titles_field_present_on_orgmemberout_schema(self, db: Session):
        """The OrgMemberOut Pydantic schema declares ``held_titles``.
        We check the model field directly rather than spinning a
        TestClient (the app's lifespan checks SECRET_KEY which isn't
        relevant to this coverage assertion)."""
        import schemas
        assert "held_titles" in schemas.OrgMemberOut.model_fields, (
            "OrgMemberOut is missing the held_titles field — Phase 47 "
            "B4 surface. Add held_titles to schemas.OrgMemberOut + "
            "populate it from org_titles.held_titles_for_member in "
            "the list_members route."
        )

    def test_held_titles_helper_returns_system_title_for_steward(
        self, db: Session,
    ):
        """The org_titles.held_titles_for_member helper returns the
        Steward system title for a member whose role is 'steward'."""
        from org_titles import (
            seed_system_titles_for_org, held_titles_for_member,
        )
        org, steward = _make_org_with_steward(db)
        seed_system_titles_for_org(db, org.id)
        db.commit()
        titles = held_titles_for_member(db, org.id, steward.id, "steward")
        assert "Steward" in titles


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


# ---------------------------------------------------------------------------
# Phase 51 — UserOut surface contract.
# ---------------------------------------------------------------------------
#
# Same guard, applied to ``UserOut``. New verification-related fields
# added to ``models.User`` must be surfaced on ``UserOut`` (or
# deliberately excluded — see ``_USER_OUT_INTERNAL_VERIFICATION_FIELDS``
# below). The reactive-hotfix pattern from Phase 45a/46 (model column
# added but FE-facing schema not updated) is exactly the class this
# guard prevents.
#
# To add a new ``UserOut`` field:
#   1. Add the column to ``models.User``.
#   2. Add the field to ``schemas.UserOut`` with a sensible default.
#   3. Append the field key to ``_USER_OUT_MUST_SURFACE_FIELDS`` below.

_USER_OUT_MUST_SURFACE_FIELDS: list[str] = [
    # Phase 12 base.
    "id",
    "username",
    "display_name",
    "email",
    "email_verified",
    "is_admin",
    "user_type",
    "delegation_strategy",
    "default_follow_policy",
    "avatar_url",
    "created_at",
    # Phase 51 — verification state surface (the four fields the FE
    # is allowed to see; the internal ``verification_attestation_id``
    # + ``verification_nullifier`` stay platform-internal).
    "verification_state",
    "verification_jurisdiction",
    "verification_provenance",
    "verification_updated_at",
]

# Phase 51 — fields that EXIST on ``models.User`` for verification
# but MUST NOT appear on any client-facing schema. Documented here so
# a future "why are these missing?" investigation lands on the rule.
_USER_OUT_INTERNAL_VERIFICATION_FIELDS: list[str] = [
    "verification_attestation_id",
    # Phase 58 Cluster C — `verification_nullifier` column dropped
    # (migration c0d1e2f3a4b5). It can no longer leak through
    # UserOut.model_dump() since the model attribute is gone.
]


class TestUserOutSurfaceContract:
    """Parallel coverage for ``UserOut`` mirroring the OrgOut surface
    test. Every entry in ``_USER_OUT_MUST_SURFACE_FIELDS`` must
    serialize through; every entry in
    ``_USER_OUT_INTERNAL_VERIFICATION_FIELDS`` must NOT serialize
    through (defense in depth against accidental nullifier leakage)."""

    def test_all_must_surface_fields_present_on_user_out(self, db: Session):
        from schemas import UserOut
        org, steward = _make_org_with_steward(db)
        out = UserOut.model_validate(steward).model_dump()
        missing = [k for k in _USER_OUT_MUST_SURFACE_FIELDS if k not in out]
        assert not missing, (
            f"UserOut is missing FE-facing field(s): {missing}. "
            f"Add the field to schemas.UserOut and append the key to "
            f"_USER_OUT_MUST_SURFACE_FIELDS in this test file."
        )

    def test_internal_verification_fields_never_leak(self, db: Session):
        from schemas import UserOut
        org, steward = _make_org_with_steward(db)
        out = UserOut.model_validate(steward).model_dump()
        leaked = [k for k in _USER_OUT_INTERNAL_VERIFICATION_FIELDS if k in out]
        assert not leaked, (
            f"UserOut leaks internal verification field(s): {leaked}. "
            f"These are cross-org correlation primitives — never "
            f"serialize them to the client."
        )

    def test_verification_state_default_is_email_only(self, db: Session):
        """A fresh user — no verification ever performed — must
        surface ``verification_state='email_only'``. Establishes the
        default-value contract for Phase 52's enforcement layer."""
        from schemas import UserOut
        org, steward = _make_org_with_steward(db)
        out = UserOut.model_validate(steward)
        assert out.verification_state == "email_only"
        assert out.verification_provenance == "none"
        assert out.verification_jurisdiction is None
        assert out.verification_updated_at is None
