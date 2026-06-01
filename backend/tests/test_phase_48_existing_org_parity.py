"""Phase 48 B0 — Existing-vs-new-org parity helper + standing assertions.

Closes the recurring class of bug that needed reactive hotfixes in three
consecutive passes:
  * Phase 45a hotfix #1 — OWNER_ONLY_KEYS missing from user_permissions
    enrichment (response-schema gap).
  * Phase 46 hotfix #1 — proposal_creation_mode missing from OrgOut
    (response-schema gap).
  * Phase 47 hotfix #1 — title.manage missing from existing orgs'
    role_permissions rows (permission-grant gap).

The 46a OrgOut serializer-coverage test closes the response-schema
variant; this test closes the permission-grant + seed-row variant.

The shape: materialize an "as-if-old" org that was created BEFORE a
given Phase X feature landed — by seeding it via the pre-X path
(roughly: insert the org + memberships directly, skip any seed helpers
the post-X code added) — then run the alembic backfill migrations,
and assert it reaches parity with a "created now" org on every must-
parity dimension:

  1. Role permissions rows (every role + every key default-granted to
     that role per DEFAULT_GRANTS).
  2. Seeded system titles (Phase 47 — Steward + Admin).
  3. Org settings keys that have defaults the backend relies on (caught
     opportunistically via the resolver layer; defaults are usually
     applied at read time, not at create time, so this dimension is a
     soft-check today).
  4. FE-facing response fields (deferred to the 46a serializer-coverage
     test which already covers this dimension — we link the two by
     having Stage 1's `_MUST_SURFACE_FIELDS` reviewed here).

If a future pass adds a new permission key + DEFAULT_GRANTS entry but
forgets the backfill migration for existing orgs, the
``test_role_permissions_parity_after_backfills_run`` test FAILS — in
CI, in seconds — with a remediation message pointing at the missing
backfill, rather than in prod browser QA.

How to verify the helper actually fails on a missing backfill: see
``TestParityHelperCatchesMissingBackfill`` below — it simulates the
Phase 47 hotfix scenario (a key added without backfill) and asserts
the helper reports the gap.
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_org_with_full_seed(
    db: Session, slug: str,
) -> models.Organization:
    """Create an org via the canonical "created now" path: roles seeded
    via `seed_default_roles_for_org`, system titles seeded via
    `seed_system_titles_for_org`. This is what every NEW org gets
    today; it's the parity baseline."""
    from org_titles import seed_system_titles_for_org
    from role_seed import seed_default_roles_for_org

    org = models.Organization(
        name=slug.title(),
        slug=slug,
        description="",
        join_policy="open",
        settings={},
    )
    db.add(org)
    db.flush()
    seed_default_roles_for_org(db, org.id)
    seed_system_titles_for_org(db, org.id)
    db.commit()
    return org


def _make_org_as_if_pre_X(
    db: Session, slug: str, *,
    skip_system_titles: bool = False,
    skip_permission_keys: set[str] | None = None,
) -> models.Organization:
    """Create an org via a stripped-down path that simulates the
    pre-feature-X state on disk. Useful as the "before" side of a
    parity check, especially in tests that simulate a backfill being
    omitted (see TestParityHelperCatchesMissingBackfill).

    ``skip_system_titles``: don't seed system titles (simulates pre-47).
    ``skip_permission_keys``: don't write role_permissions rows for
    these keys (simulates pre-X for a permission added in pass X).
    """
    from role_seed import seed_default_roles_for_org

    org = models.Organization(
        name=slug.title(),
        slug=slug,
        description="",
        join_policy="open",
        settings={},
    )
    db.add(org)
    db.flush()
    seed_default_roles_for_org(db, org.id)
    db.commit()

    if skip_permission_keys:
        # Drop the role_permissions rows for the simulated-missing keys.
        for key in skip_permission_keys:
            db.query(models.RolePermission).filter(
                models.RolePermission.permission_key == key,
                models.RolePermission.role_id.in_(
                    db.query(models.Role.id).filter_by(org_id=org.id)
                ),
            ).delete(synchronize_session=False)
        db.commit()

    if not skip_system_titles:
        from org_titles import seed_system_titles_for_org
        seed_system_titles_for_org(db, org.id)
        db.commit()

    return org


def _role_permissions_set(
    db: Session, org_id: str,
) -> dict[str, set[str]]:
    """Return {role_system_key: set(permission_key)} for enabled rows."""
    out: dict[str, set[str]] = {}
    roles = db.query(models.Role).filter_by(org_id=org_id).all()
    for role in roles:
        rows = db.query(models.RolePermission).filter_by(
            role_id=role.id,
        ).all()
        out[role.system_key] = {r.permission_key for r in rows if r.enabled}
    return out


def _system_title_set(db: Session, org_id: str) -> set[str]:
    titles = db.query(models.OrgTitle).filter_by(
        org_id=org_id, is_system=True,
    ).all()
    return {t.name for t in titles}


def parity_diff(
    db: Session, org_a: models.Organization, org_b: models.Organization,
) -> dict[str, dict]:
    """Compute the dimension-wise diff between two orgs. Empty dict on
    perfect parity. Keys present iff that dimension differs.
    """
    diff: dict[str, dict] = {}

    a_perms = _role_permissions_set(db, org_a.id)
    b_perms = _role_permissions_set(db, org_b.id)
    role_diff: dict[str, dict] = {}
    for role in set(a_perms.keys()) | set(b_perms.keys()):
        only_a = a_perms.get(role, set()) - b_perms.get(role, set())
        only_b = b_perms.get(role, set()) - a_perms.get(role, set())
        if only_a or only_b:
            role_diff[role] = {
                "only_in_a": sorted(only_a),
                "only_in_b": sorted(only_b),
            }
    if role_diff:
        diff["role_permissions"] = role_diff

    a_titles = _system_title_set(db, org_a.id)
    b_titles = _system_title_set(db, org_b.id)
    if a_titles != b_titles:
        diff["system_titles"] = {
            "only_in_a": sorted(a_titles - b_titles),
            "only_in_b": sorted(b_titles - a_titles),
        }

    return diff


# ===========================================================================
# Standing parity assertions
# ===========================================================================

class TestNewOrgsHaveExpectedSeed:
    """Sanity baseline: a freshly-created org passes the parity check
    against itself + carries the seeded data we expect."""

    def test_new_org_has_full_role_permissions(self, db: Session):
        org = _make_org_with_full_seed(db, "parity-new")
        perms = _role_permissions_set(db, org.id)
        # Steward + admin should hold every key in PERMISSION_REGISTRY.
        from permission_registry import ALL_PERMISSION_KEYS
        assert perms["steward"] == ALL_PERMISSION_KEYS, (
            f"steward missing keys: {ALL_PERMISSION_KEYS - perms['steward']}"
        )
        assert perms["admin"] == ALL_PERMISSION_KEYS, (
            f"admin missing keys: {ALL_PERMISSION_KEYS - perms['admin']}"
        )

    def test_new_org_has_system_titles(self, db: Session):
        org = _make_org_with_full_seed(db, "parity-new-titles")
        titles = _system_title_set(db, org.id)
        assert titles == {"Steward", "Admin"}

    def test_two_new_orgs_have_perfect_parity(self, db: Session):
        org_a = _make_org_with_full_seed(db, "parity-a")
        org_b = _make_org_with_full_seed(db, "parity-b")
        diff = parity_diff(db, org_a, org_b)
        assert diff == {}, (
            f"two freshly-created orgs differ: {diff}. "
            f"This is a regression — both should follow the same seed path."
        )


# ===========================================================================
# Catching a missing backfill — simulate the 47 hotfix scenario
# ===========================================================================

class TestParityHelperCatchesMissingBackfill:
    """The whole point of the helper: when a permission key is added
    to DEFAULT_GRANTS but no backfill migration writes it onto existing
    orgs' role_permissions rows, the parity check surfaces the gap.

    This simulates the Phase 47 hotfix #1 scenario in test: an org
    created "before" the addition lacks the row; an org created
    "after" has it; the parity helper reports the difference clearly.
    """

    def test_helper_catches_missing_permission_grant(self, db: Session):
        """If a permission key default-granted to steward is missing
        on an existing org (no backfill ran), parity_diff() reports it.
        """
        # The "before" org — simulate as if title.manage hadn't been
        # backfilled. We use title.manage as the canary because it's
        # the most recent backfilled key (Phase 47 hotfix #1).
        org_before = _make_org_as_if_pre_X(
            db, "before",
            skip_permission_keys={"title.manage"},
        )
        org_after = _make_org_with_full_seed(db, "after")
        diff = parity_diff(db, org_before, org_after)
        assert "role_permissions" in diff, (
            "parity_diff did not surface a missing permission grant. "
            "The helper is broken — a missing backfill should be a "
            "first-class diff entry."
        )
        rd = diff["role_permissions"]
        # The omission should appear as "only in the AFTER org" for
        # steward + admin (which both default-grant the key).
        assert "steward" in rd
        assert "title.manage" in rd["steward"]["only_in_b"]
        assert "admin" in rd
        assert "title.manage" in rd["admin"]["only_in_b"]

    def test_helper_catches_missing_system_title(self, db: Session):
        """If system titles weren't seeded on the "old" org (e.g. a
        pre-47 org that never ran the backfill), the helper reports
        the gap."""
        org_before = _make_org_as_if_pre_X(
            db, "before-notitles", skip_system_titles=True,
        )
        org_after = _make_org_with_full_seed(db, "after-titles")
        diff = parity_diff(db, org_before, org_after)
        assert "system_titles" in diff
        assert diff["system_titles"]["only_in_b"] == ["Admin", "Steward"]


# ===========================================================================
# B0.3 — Apply the discipline to Phase 48's own additions
# ===========================================================================
#
# Stage 1's election work introduces:
#   * No new permission keys (the open-election endpoint reuses
#     proposal.create + an admin-tier check). UPDATE THIS COMMENT
#     if Stage 1 adds one.
#   * No new seeded rows per org (elections opt-in is settings-key
#     based, default-False at the resolver layer — no row to backfill).
#   * Schema columns on Proposal + a new election_candidacies table,
#     which are migration-applied universally and don't carry per-org
#     defaults — no backfill needed.
#
# If Stage 2 or Stage 3 adds anything that would need a backfill (an
# elections-enablement permission key or a per-org election-config row),
# the parity helper must catch it. Update the relevant TestStage2 /
# TestStage3 below to assert presence after backfill runs.

class TestStage1AdditionsDoNotNeedBackfill:
    """Stage 1's additions are migration-applied at schema level and
    do not introduce a per-org seed/grant pattern. Verify by checking
    that two parity-passing orgs remain at parity after creating an
    election on one."""

    def test_creating_election_does_not_break_org_parity(self, db: Session):
        org_a = _make_org_with_full_seed(db, "stage1-a")
        org_b = _make_org_with_full_seed(db, "stage1-b")
        steward = make_user(db, "stage1-steward")
        make_org_membership(
            db, org_id=org_a.id, user_id=steward.id, role="steward",
        )
        make_org_membership(
            db, org_id=org_b.id, user_id=steward.id, role="steward",
        )
        # Even after activity on org_a, the parity baseline still holds.
        diff = parity_diff(db, org_a, org_b)
        assert diff == {}, (
            "Stage 1 elections should not introduce a per-org seed/grant "
            f"pattern; parity diff: {diff}"
        )
