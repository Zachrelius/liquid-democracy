"""Phase 12 Stage 1 — tests for ``backend/role_seed.py::seed_default_roles_for_org``.

The seed helper is called from ``routes/organizations.py::create_organization``
for new orgs and (via duplicated raw SQL) from the migration. Tests here
exercise the application-level helper directly against an in-memory SQLite
DB built via ``Base.metadata.create_all``.
"""
from __future__ import annotations

import models
from role_seed import (
    DEFAULT_GRANTS,
    PRESET_ROLES,
    seed_default_roles_for_org,
)


def _make_org(db, slug: str = "alpha") -> models.Organization:
    org = models.Organization(name=slug.title(), slug=slug, description="")
    db.add(org)
    db.flush()
    return org


def test_seed_creates_four_preset_roles(db):
    org = _make_org(db, "alpha")
    roles = seed_default_roles_for_org(db, org.id)

    assert set(roles.keys()) == {"steward", "admin", "moderator", "member"}
    for system_key, display_name, display_order in PRESET_ROLES:
        r = roles[system_key]
        assert r.org_id == org.id
        assert r.system_key == system_key
        assert r.name == display_name
        assert r.display_order == display_order
        assert r.is_system_preset is True


def test_seed_creates_default_role_permissions_per_grant_table(db):
    org = _make_org(db, "alpha")
    roles = seed_default_roles_for_org(db, org.id)

    # For each preset, the inserted permission_keys should equal the
    # DEFAULT_GRANTS entry.
    for system_key, granted in DEFAULT_GRANTS.items():
        role = roles[system_key]
        actual_keys = {
            rp.permission_key for rp in
            db.query(models.RolePermission)
            .filter(models.RolePermission.role_id == role.id)
            .all()
        }
        assert actual_keys == set(granted), (
            f"role {system_key}: expected {set(granted)}, got {actual_keys}"
        )

    # All inserted permissions should have enabled=True.
    enabled_count = (
        db.query(models.RolePermission)
        .filter(models.RolePermission.enabled.is_(True))
        .count()
    )
    total_count = db.query(models.RolePermission).count()
    assert enabled_count == total_count


def test_seed_is_idempotent(db):
    """Re-seeding an already-seeded org returns the same roles without
    duplicating any rows."""
    org = _make_org(db, "alpha")
    first = seed_default_roles_for_org(db, org.id)
    role_count_after_first = (
        db.query(models.Role).filter(models.Role.org_id == org.id).count()
    )
    perm_count_after_first = db.query(models.RolePermission).count()

    second = seed_default_roles_for_org(db, org.id)

    role_count_after_second = (
        db.query(models.Role).filter(models.Role.org_id == org.id).count()
    )
    perm_count_after_second = db.query(models.RolePermission).count()

    assert role_count_after_first == role_count_after_second == 4
    assert perm_count_after_first == perm_count_after_second
    # Same role IDs returned (the helper reuses, doesn't replace).
    for system_key in ("steward", "admin", "moderator", "member"):
        assert first[system_key].id == second[system_key].id


def test_seed_for_separate_orgs_does_not_collide(db):
    org_a = _make_org(db, "alpha")
    org_b = _make_org(db, "beta")
    roles_a = seed_default_roles_for_org(db, org_a.id)
    roles_b = seed_default_roles_for_org(db, org_b.id)

    # Distinct role rows per org.
    for system_key in ("steward", "admin", "moderator", "member"):
        assert roles_a[system_key].id != roles_b[system_key].id

    # Each org has its own 4 roles.
    assert (
        db.query(models.Role).filter(models.Role.org_id == org_a.id).count()
        == 4
    )
    assert (
        db.query(models.Role).filter(models.Role.org_id == org_b.id).count()
        == 4
    )


def test_default_grants_counts_match_spec():
    """Sanity-check the DEFAULT_GRANTS table itself (not the seed call).

    Stage 1 shipped at 23/23/8/0. Phase 12 Stage 2 added the
    `role_permissions.edit` meta-permission (steward/admin both go to 24).
    Phase 12.5 added `proposal.set_thresholds` (steward/admin both go to
    25; moderator/member get it absent per Q2: reserved for Steward and
    maybe Admin). Phase 16 adds `proposal.set_durations` (steward/admin
    both go to 26; moderator gets it TRUE since durations are logistics
    not governance — Q1; member still absent). New totals: 26/26/9/0.
    """
    assert len(DEFAULT_GRANTS["steward"]) == 27
    assert len(DEFAULT_GRANTS["admin"]) == 27
    assert len(DEFAULT_GRANTS["moderator"]) == 9
    assert len(DEFAULT_GRANTS["member"]) == 0
