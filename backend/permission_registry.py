"""Phase 12 Stage 1 — Permission registry (Cluster H, H3).

Static module-level data describing the full permission vocabulary used
by the configurable role-permission system. Stage 2's matrix UI consumes
this registry directly via ``GET /api/permissions/registry``.

The registry pairs each permission key with:
  * key — stable identifier referenced from code and the
    ``role_permissions`` table.
  * label — human-readable, ~3-5 words.
  * description — single sentence describing what the permission grants.
  * category — UI grouping (matches the matrix's row sections in Stage 2).

DEFAULT_GRANTS describes which preset roles get each permission TRUE on
a freshly-seeded org. Roles are referenced by their stable
``Role.system_key`` ("steward", "admin", "moderator", "member"), never
by their display name.

Hardcoded gates outside this registry (per spec D3, D4):

  * Decision-6 implicit power (parent-org admin/steward → all sub-org
    permissions): handled in ``role_permissions.has_permission``.
  * ``org.delete`` and ``org.transfer_stewardship``: hardcoded gates on
    ``role.system_key == 'steward'``. Not present in this registry.
  * Platform admin (``User.is_admin``): completely separate concern,
    not part of this system at all.

See ``phase12_configurable_role_permissions_stage1_spec.md`` §"Permission
registry" for the canonical table this file mirrors.
"""

from __future__ import annotations

from typing import NamedTuple


class PermissionDefinition(NamedTuple):
    key: str
    label: str
    description: str
    category: str


# Categories — order is preserved for the matrix UI grouping in Stage 2.
CATEGORIES: list[str] = [
    "Proposals",
    "Topics",
    "Members",
    "Sub-organizations",
    "Delegate applications",
    "Polis (deliberation)",
    "Comments",
    "Organization",
    "Audit and analytics",
    "Messages",
]


# Full registry — 29 entries. Stage 1 shipped 23; Stage 2 added
# `role_permissions.edit`; Phase 12.5 adds `proposal.set_thresholds`;
# Phase 16 adds `proposal.set_durations`; Phase 32.2 adds
# `org.edit_proposal`; Phase 47 adds `title.manage`; Phase 68b adds
# `proposal.archive`.
# See spec §"Permission registry" lines 105-144 for Stage 1's 23-key table.
PERMISSION_REGISTRY: list[PermissionDefinition] = [
    # --- Proposals (6) ---
    PermissionDefinition(
        "proposal.create",
        "Create proposals",
        "Allow creating new proposals in this organization.",
        "Proposals",
    ),
    PermissionDefinition(
        "proposal.delete",
        "Delete proposals",
        # Phase 71c (69.1 Tier-A relabel) — corrected to reality. The only
        # proposal-deletion route removes DRAFT proposals only and is gated by
        # author / "Edit any proposal" (org.edit_proposal) / platform admin —
        # it does NOT read this key. Proposals past draft are archived
        # (withdrawn), never deleted. This key is currently vestigial.
        "Currently has no effect: the only deletion path removes draft proposals and is gated by the author, the 'Edit any proposal' permission, or a platform admin — not by this toggle. Proposals past the draft stage are archived, never deleted.",
        "Proposals",
    ),
    PermissionDefinition(
        "proposal.advance_phase",
        "Advance proposal phases",
        "Allow moving a proposal between deliberation, voting, and closed phases — including closing the voting phase early. Authors may advance their own proposal from draft to deliberation to voting without this permission, but closing voting requires it.",
        "Proposals",
    ),
    PermissionDefinition(
        "proposal.resolve_tie",
        "Resolve voting ties",
        # Phase 71c (69.1 Tier-A relabel) — tie resolution is automated. At
        # proposal close the configured tie-break method runs automatically
        # (_maybe_resolve_tie); there is no manual tie-resolution action
        # gated by this key. Kept registered (removal needs a backfill
        # migration — out of scope).
        "Automated — no manual action: ties are resolved automatically at proposal close using the organization's configured tie-break method. This toggle currently gates nothing.",
        "Proposals",
    ),
    # Phase 12.5 — gate on overriding org-default approval thresholds.
    PermissionDefinition(
        "proposal.set_thresholds",
        "Set proposal thresholds",
        "Allow overriding the organization's default pass and quorum thresholds when creating or editing a proposal. Without this permission, proposals use the organization defaults.",
        "Proposals",
    ),
    # Phase 16 — gate on overriding org-default deliberation/voting durations.
    PermissionDefinition(
        "proposal.set_durations",
        "Set proposal durations",
        "Allow overriding the organization's default deliberation and voting durations when creating or editing a proposal. Without this permission, proposals use the organization defaults.",
        "Proposals",
    ),
    # Phase 32.2 — gate on editing another member's proposal during
    # deliberation. Phase 32 D14 specified the gate but the key was
    # never registered; Phase 32.1 hotfix #4 worked around the gap by
    # tightening the FE gate to platform-admin only. This pass registers
    # the key, seeds it to admin/steward by default, restores the
    # spec'd backend PATCH gate, and reverts the FE workaround.
    PermissionDefinition(
        "org.edit_proposal",
        "Edit any proposal",
        "Allow editing proposals authored by other members during deliberation (subject to the org's edit lockout setting). Authors can always edit their own proposals.",
        "Proposals",
    ),
    # Phase 68b — archive (move to the closed/withdrawn bucket) any
    # proposal at any phase. Authors can always archive their own draft /
    # deliberation proposals without this key.
    PermissionDefinition(
        "proposal.archive",
        "Archive proposals",
        "Allow moving any proposal — at any phase — out of the active list into the archive (preserves the proposal and any votes; nothing is deleted). Authors can always archive their own draft or deliberation proposals.",
        "Proposals",
    ),
    # --- Topics (3) ---
    PermissionDefinition(
        "topic.create",
        "Create topics",
        "Allow creating new topics for delegation and proposal classification.",
        "Topics",
    ),
    PermissionDefinition(
        "topic.edit",
        "Edit topics",
        "Allow editing topic names, descriptions, and precedence.",
        "Topics",
    ),
    PermissionDefinition(
        "topic.delete",
        "Delete topics",
        "Allow permanently removing topics.",
        "Topics",
    ),
    # --- Members (5) ---
    PermissionDefinition(
        "member.approve_join",
        "Approve member join requests",
        "Allow accepting or denying requests to join the organization.",
        "Members",
    ),
    PermissionDefinition(
        "member.remove",
        "Remove members",
        "Allow removing members from the organization (preserves their account; only ends membership).",
        "Members",
    ),
    PermissionDefinition(
        "member.suspend",
        "Suspend members",
        "Allow temporarily suspending a member's ability to vote and delegate without removing them.",
        "Members",
    ),
    PermissionDefinition(
        "member.change_role",
        "Change member roles",
        "Allow promoting or demoting other members between roles (cannot promote to or demote from Steward).",
        "Members",
    ),
    PermissionDefinition(
        "member.invite",
        "Send invitations",
        "Allow sending email invitations to join the organization.",
        "Members",
    ),
    # --- Sub-organizations (3) ---
    PermissionDefinition(
        "sub_org.create",
        "Create sub-organizations",
        "Allow creating new sub-organizations under this parent.",
        "Sub-organizations",
    ),
    PermissionDefinition(
        "sub_org.delete",
        "Delete sub-organizations",
        "Allow permanently removing a sub-organization.",
        "Sub-organizations",
    ),
    PermissionDefinition(
        "sub_org.edit_settings",
        "Edit sub-organization settings",
        "Allow modifying sub-org name, visibility, and configuration.",
        "Sub-organizations",
    ),
    # --- Delegate applications (1) ---
    PermissionDefinition(
        "delegate_application.approve",
        "Approve public delegate applications",
        "Allow accepting or denying users who apply to be public delegates within this organization.",
        "Delegate applications",
    ),
    # --- Polis (2) ---
    PermissionDefinition(
        "polis.create",
        "Create Polis conversations",
        "Allow creating Polis deliberation conversations linked to proposals.",
        "Polis (deliberation)",
    ),
    PermissionDefinition(
        "polis.manage",
        "Manage Polis conversations",
        "Allow editing or archiving existing Polis conversations.",
        "Polis (deliberation)",
    ),
    # --- Comments (1) ---
    PermissionDefinition(
        "comment.moderate",
        "Moderate comments",
        # Phase 85 (B-1) — this key is now enforced by DELETE /api/comments/{id}.
        # Moderator removal is a distinct, attributed action: the comment shows
        # as removed by a moderator, the author is notified, and the acting
        # moderator is recorded in the audit log. Members can always edit and
        # delete their own comments within the edit window.
        "Allow removing comments posted by other members. Removal is attributed (the comment shows as removed by a moderator) and the author is notified. Members can always edit and delete their own comments within the edit window.",
        "Comments",
    ),
    # --- Organization (3) ---
    PermissionDefinition(
        "org.edit_settings",
        "Edit organization settings",
        "Allow modifying org name, description, voting method defaults, and other org-wide configuration. Does not include branding (separate permission).",
        "Organization",
    ),
    PermissionDefinition(
        "org.edit_branding",
        "Edit organization branding",
        # Phase 71c (69.1 Tier-A relabel) — dropped the stale "Reserved for
        # Stage 3" clause; the logo/color endpoints (routes/org_logos.py) are
        # live and this key gates them.
        "Allow uploading a logo and choosing the organization's display color.",
        "Organization",
    ),
    # Phase 12 Stage 2 — meta-permission for editing the matrix itself.
    PermissionDefinition(
        "role_permissions.edit",
        "Edit role permissions",
        "Allow editing the matrix of which roles have which permissions in this organization.",
        "Organization",
    ),
    # Phase 47 — manage org titles / offices (define, edit, delete custom
    # titles; assign/revoke titles to members). System titles (Steward,
    # Admin) are uneditable + undeletable; their underlying roles are
    # still managed via the existing transfer-stewardship +
    # change-member-role flows.
    PermissionDefinition(
        "title.manage",
        "Manage organization titles",
        "Allow defining, editing, and assigning org titles (offices/positions).",
        "Organization",
    ),
    # --- Audit and analytics (2) ---
    PermissionDefinition(
        "audit.view_org",
        "View organization audit log",
        "Allow viewing the per-org audit log of administrative actions.",
        "Audit and analytics",
    ),
    PermissionDefinition(
        "analytics.view",
        "View organization analytics",
        "Allow viewing org-level participation, voting, and delegation analytics.",
        "Audit and analytics",
    ),
    # --- Messages (1) — Phase 77 ---
    PermissionDefinition(
        "org_inbox.view",
        "View org inbox",
        "Allow viewing and responding to messages sent to the organization's shared inbox.",
        "Messages",
    ),
]


# Set of all permission keys for quick membership tests.
ALL_PERMISSION_KEYS: set[str] = {p.key for p in PERMISSION_REGISTRY}


# Default-grant table — which preset roles have each permission TRUE on a
# freshly-seeded org. Keyed by Role.system_key. The seed helper in
# backend/role_seed.py (Cluster D) imports DEFAULT_GRANTS to populate
# role_permissions rows when an org is created.
#
# Counts (verified by test_permission_registry.py) — Phase 71a totals:
#   steward   = 30  (every key; Phase 77 added org_inbox.view)
#   admin     = 30  (every key; Phase 77 added org_inbox.view)
#   moderator = 11  (+2 from Phase 71a: member.suspend, polis.manage —
#                    NOT new powers; moderators could already suspend +
#                    manage polises via the moderator+ tier. Phase 71
#                    makes the config authoritative, so the starter config
#                    must seed these TRUE to keep current behavior. See
#                    phase71_permission_config_authoritative_2026-06-14.md.)
#   member    =  0  (no change)
DEFAULT_GRANTS: dict[str, set[str]] = {
    "steward": set(ALL_PERMISSION_KEYS),
    "admin": set(ALL_PERMISSION_KEYS),
    "moderator": {
        "proposal.create",
        "proposal.advance_phase",
        "topic.create",
        "topic.edit",
        "member.approve_join",
        "member.invite",
        "polis.create",
        "comment.moderate",
        # Phase 16 — moderators can override per-proposal durations.
        "proposal.set_durations",
        # Phase 71a — config-authoritative starter values matching the
        # moderator+ tier behavior that already exists today.
        "member.suspend",
        "polis.manage",
    },
    "member": set(),
}


__all__ = [
    "PermissionDefinition",
    "PERMISSION_REGISTRY",
    "ALL_PERMISSION_KEYS",
    "CATEGORIES",
    "DEFAULT_GRANTS",
]
