import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Organization & Multi-tenancy
# ---------------------------------------------------------------------------

class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    # Phase 57 — repurposed to hold the new three-value join semantics
    # (`open` / `approval` / `invite`). The four old values
    # (`open` / `approval_required` / `invite_only_public` /
    # `invite_only_secret`) were rewritten in migration b9c0d1e2f3a4 per:
    #   open / approval_required → open / approval (with discoverability='listed')
    #   invite_only_public       → invite (with discoverability='listed')
    #   invite_only_secret       → invite (with discoverability='hidden')
    # Test fixtures + in-flight callers that still pass an old literal are
    # normalized transparently by the `_normalize_access_axes` validator
    # below; old literals never reach the column.
    join_policy: Mapped[str] = mapped_column(
        String, nullable=False, default="approval", server_default="approval",
    )
    # Phase 57 — discoverability axis (how outsiders find the org).
    # `listed`   — appears on /explore.
    # `unlisted` — reachable at /{slug} by direct link only; not listed.
    # `hidden`   — no public landing page; 404 to non-members.
    # Drives Phase 55 /explore filter + Phase 14 public-landing 404 check.
    discoverability: Mapped[str] = mapped_column(
        String(length=16), nullable=False,
        default="listed", server_default="listed",
        index=True,
    )
    # Phase 57 — activity visibility axis (what non-members see beyond
    # the splash). `public` exposes proposals / aggregate tallies /
    # comments read-only to anonymous viewers; `members_only` keeps the
    # current behavior (splash only, everything else gated).
    # Individual delegate-vote visibility STILL routes through the
    # Phase 30.3 `can_see_votes` gate — this column does NOT bypass it.
    activity_visibility: Mapped[str] = mapped_column(
        String(length=16), nullable=False,
        default="members_only", server_default="members_only",
    )
    settings: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)  # org-specific defaults
    # Phase 8.5: nullable self-referential FK. NULL = parent org (top-level);
    # non-NULL = sub-org whose parent has parent_org_id IS NULL. Two-level
    # enforcement is at the API layer, not the schema (Decision 1).
    parent_org_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=True, index=True
    )
    # Phase 23 (B1, D1, D20) — demo-org flag + per-org reset-in-progress lock.
    # ``is_demo`` is the load-bearing safety filter for the daily-reset job:
    # only orgs where ``is_demo=True`` are touched. Real orgs default False
    # and remain untouched. ``is_demo_resetting`` is set to True for the
    # duration of an in-flight reset transaction (D20); frontend reads it to
    # render a "Demo refreshing..." overlay.
    is_demo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0",
        index=True,
    )
    is_demo_resetting: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0",
    )
    # Phase 23 (D22, Amendment E) — directory-card metadata. ``governance_type``
    # is the human-readable label ("Homeowners' Association", "Labor Union
    # Local", "Civic Advocacy Group"), seeded from per-org config rather
    # than the bible. ``display_order`` controls card sort on `/demo`;
    # NULLS LAST puts real orgs after demo orgs.
    governance_type: Mapped[Optional[str]] = mapped_column(
        String(length=50), nullable=True,
    )
    display_order: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
    )
    # Phase 23 (D25, B6) — per-org demo persona allowlist. Each entry has
    # shape ``{"username": str, "display_name": str, "role": str,
    # "description": str}``. Seeded from each org's bible at reset time;
    # drives the directory cards and the per-org demo-login validation.
    # Real orgs leave NULL.
    personas: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # Phase 49a Cluster B — replaced the legacy three-way
    # ``proposal_creation_mode`` column (open / cosign_required /
    # admin_only) with the single ``settings.allow_cosign_petition``
    # boolean. The new model:
    #
    #   * Users holding ``proposal.create`` create directly.
    #   * Users without ``proposal.create`` AND
    #     ``allow_cosign_petition=True`` → cosign-gated path.
    #   * Otherwise: 403.
    #
    # See ``backend/migrations/versions/b9c2e0f43215_phase_49a_*.py``
    # for the data-migration mapping that preserves each org's
    # effective behavior. The column itself is dropped in that
    # migration — no model field here.
    # Phase 45b — per-org governance mode (B1). Two values:
    #   - ``single_steward`` (default; today's behavior): exactly one
    #     Steward seat always exists; OWNER_ONLY_KEYS + STEWARD_LOCKED
    #     gates resolve to the Steward; cardinality floor is "≥1 active
    #     steward" (the Phase 45a invariant).
    #   - ``admin_council`` (opt-in): no Steward seat required; governing
    #     authority is the admin tier; OWNER_ONLY_KEYS + STEWARD_LOCKED
    #     gates resolve to ANY admin (D4/D5); cardinality floor is "≥1
    #     active admin" (D6).
    # Default + server_default 'single_steward' so untouched orgs +
    # migrated rows behave byte-for-byte as Phase 45a left them.
    governance_mode: Mapped[str] = mapped_column(
        String(length=32), nullable=False,
        default="single_steward", server_default="single_steward",
        index=True,
    )
    # Phase 23 (Amendment F) — Phase 24 branding prep. All NULL in Phase 23;
    # populated in Phase 24 once the asset pipeline lands. Hex colors are
    # 7-char strings like "#3A7CA5"; ``logo_url`` is a path under the static
    # asset mount.
    brand_color: Mapped[Optional[str]] = mapped_column(
        String(length=7), nullable=True,
    )
    brand_secondary_color: Mapped[Optional[str]] = mapped_column(
        String(length=7), nullable=True,
    )
    logo_url: Mapped[Optional[str]] = mapped_column(
        String(length=500), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    # Relationships
    memberships: Mapped[list["OrgMembership"]] = relationship("OrgMembership", back_populates="organization", cascade="all, delete-orphan")
    invitations: Mapped[list["Invitation"]] = relationship("Invitation", back_populates="organization", cascade="all, delete-orphan")
    proposals: Mapped[list["Proposal"]] = relationship(
        "Proposal", back_populates="organization", foreign_keys="Proposal.org_id"
    )
    topics: Mapped[list["Topic"]] = relationship(
        "Topic", back_populates="organization", foreign_keys="Topic.org_id"
    )
    delegate_profiles: Mapped[list["DelegateProfile"]] = relationship(
        "DelegateProfile", back_populates="organization", foreign_keys="DelegateProfile.org_id"
    )
    # Phase 8.5: parent ↔ sub-orgs.
    parent_org: Mapped[Optional["Organization"]] = relationship(
        "Organization",
        remote_side="Organization.id",
        back_populates="sub_orgs",
        foreign_keys=[parent_org_id],
    )
    sub_orgs: Mapped[list["Organization"]] = relationship(
        "Organization",
        back_populates="parent_org",
        foreign_keys=[parent_org_id],
        cascade="all, delete-orphan",
    )
    sub_org_memberships: Mapped[list["SubOrgMembership"]] = relationship(
        "SubOrgMembership",
        back_populates="sub_organization",
        cascade="all, delete-orphan",
        foreign_keys="SubOrgMembership.sub_org_id",
    )
    # Phase 19 (B2) — per-org delegate identity rows for this org.
    delegate_profiles_org: Mapped[list["OrgDelegateProfile"]] = relationship(
        "OrgDelegateProfile", back_populates="org",
        foreign_keys="OrgDelegateProfile.org_id",
        cascade="all, delete-orphan",
    )

    # Phase 57 — compatibility shim that transparently normalizes the
    # four old `join_policy` literals into the new (join_policy,
    # discoverability) tuple. The validator is the load-bearing edge that
    # keeps the ~95 test files + any in-flight FE clients still passing
    # the old vocabulary working without a churn rewrite of every fixture.
    #
    # New callers that pass `discoverability` explicitly always win over
    # the implied default; the validator only AUTO-sets it for legacy
    # callers that haven't been updated yet.
    @validates("join_policy")
    def _normalize_join_policy_legacy(self, key, value):
        # Map old four-value vocabulary → new three-value vocabulary +
        # the discoverability that conserves the old behavior.
        mapping = {
            "open": ("open", None),
            "approval_required": ("approval", None),
            "invite_only_public": ("invite", "listed"),
            "invite_only_secret": ("invite", "hidden"),
        }
        if value in mapping:
            new_join, implied_disc = mapping[value]
            # Don't clobber an explicitly-set discoverability — that
            # comes up in tests that pass both values in the same
            # constructor (kwarg order matters there; we only set if
            # the column hasn't been written yet).
            if implied_disc is not None:
                current_disc = getattr(self, "discoverability", None)
                # `discoverability` defaults to "listed" (server_default
                # +Column default); treat the column-default value as
                # "not yet explicitly set" so the legacy mapping wins.
                if current_disc is None or current_disc == "listed":
                    self.discoverability = implied_disc
            return new_join
        return value


class Role(Base):
    """Phase 12 Stage 1 — per-org role.

    Each org gets four preset rows seeded on creation (steward, admin,
    moderator, member). Custom roles will be created later (Stage 2/3) on
    this same table; ``is_system_preset=True`` distinguishes the built-ins.

    ``system_key`` is the stable identifier used in code; ``name`` is the
    UI-displayed label (renaming "Steward" later is a one-row update).
    """
    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("org_id", "system_key", name="uq_roles_org_system_key"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    system_key: Mapped[str] = mapped_column(String, nullable=False)
    is_system_preset: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    permissions: Mapped[list["RolePermission"]] = relationship(
        "RolePermission", back_populates="role", cascade="all, delete-orphan",
    )


class RolePermission(Base):
    """Phase 12 Stage 1 — per-role permission grant.

    One row per (role_id, permission_key) pair when the permission is
    explicitly recorded. Rows are seeded from the ``DEFAULT_GRANTS`` table
    (see ``backend/permission_registry.py`` / ``backend/role_seed.py``);
    Stage 2 will add UI for toggling ``enabled`` per cell.
    """
    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_key", name="uq_role_permissions_role_key"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    role_id: Mapped[str] = mapped_column(
        String, ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    permission_key: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    role: Mapped["Role"] = relationship("Role", back_populates="permissions")


class OrgMembership(Base):
    __tablename__ = "org_memberships"
    __table_args__ = (UniqueConstraint("user_id", "org_id", name="uq_org_membership_user_org"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    org_id: Mapped[str] = mapped_column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    # Phase 12 Stage 1: replaced the string ``role`` column with an FK to
    # ``roles.id``. The legacy string column is dropped by the
    # phase_12_role_permissions migration; code must reference the role's
    # ``system_key`` (via the ``role`` relationship) rather than this FK
    # directly.
    role_id: Mapped[str] = mapped_column(
        String, ForeignKey("roles.id"), nullable=False, index=True,
    )
    status: Mapped[str] = mapped_column(String, default="active")  # active, suspended, pending_approval
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    # Phase 52f — per-org display name override. NULL falls through
    # to ``User.display_name``. The resolver
    # ``verification.display_name_for(user, org)`` reads this; every
    # name-rendering surface in an org context routes through the
    # resolver.
    display_name: Mapped[Optional[str]] = mapped_column(
        String(length=80), nullable=True,
    )

    user: Mapped["User"] = relationship("User", back_populates="org_memberships")
    organization: Mapped["Organization"] = relationship("Organization", back_populates="memberships")
    role: Mapped["Role"] = relationship("Role", foreign_keys=[role_id])


class SubOrgMembership(Base):
    """Phase 8.5: a user's membership in a specific sub-org.

    Parallel to OrgMembership for the parent-org membership. A user can belong
    to multiple sub-orgs of the same parent (Decision 2). Sub-org membership is
    OPT-IN — being a parent-org member does not auto-create rows here.

    Phase 15 Cluster S — replaced the string ``role`` column with an FK to
    ``roles.id`` (the parent org's Role rows; sub-orgs inherit the
    parent's matrix wholesale, no per-sub-org roles table). The legacy
    string column is dropped by the
    ``98dcd0058ba2_phase_15_sub_org_role_permissions`` migration.
    Code must reference the role's ``system_key`` (via the ``role``
    relationship) rather than the FK directly.
    """
    __tablename__ = "sub_org_memberships"
    __table_args__ = (UniqueConstraint("user_id", "sub_org_id", name="uq_sub_org_membership_user_sub_org"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    sub_org_id: Mapped[str] = mapped_column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    # Phase 15 Cluster S — FK to the PARENT org's Role row (sub-orgs
    # inherit the parent's matrix wholesale; no per-sub-org roles table).
    role_id: Mapped[str] = mapped_column(
        String, ForeignKey("roles.id"), nullable=False, index=True,
    )
    status: Mapped[str] = mapped_column(String, default="active")  # active, suspended, pending_approval
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    user: Mapped["User"] = relationship("User", back_populates="sub_org_memberships")
    sub_organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="sub_org_memberships",
        foreign_keys=[sub_org_id],
    )
    role: Mapped["Role"] = relationship("Role", foreign_keys=[role_id])


class Invitation(Base):
    __tablename__ = "invitations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String, nullable=False)
    invited_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String, default="member")
    token: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending, accepted, expired, revoked
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    organization: Mapped["Organization"] = relationship("Organization", back_populates="invitations")
    inviter: Mapped["User"] = relationship("User")


# Phase 30.1 B4 — DelegateApplication model removed. The Phase 19
# lifecycle (DelegateProfile.visibility transitions through
# private / public / public_accepting with submitted_at/approved_at
# state on the DP row itself) supersedes it; the legacy approve/deny
# flow it backed is gone. Migration `b9e3f51c2a40` drops the underlying
# table.


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Phase 39 B1 — soft-revocation lever. False = account is disabled;
    # ``_get_user_from_token`` and ``refresh_token`` both filter on
    # ``is_active == True`` so a flipped-to-False account can't refresh or
    # use existing access tokens. The migration backfills existing rows
    # to True via ``server_default``; the ORM default mirrors it so
    # freshly-constructed ``User()`` instances pick up True pre-flush.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
    )
    # Phase 39 B4 — per-username soft-lockout counter. Incremented on
    # every bad-password attempt for an existing user; reset to 0 on
    # successful login + on password-reset success. When the counter
    # crosses LOCKOUT_THRESHOLD (10) the login route sets ``locked_until``
    # to ``now + LOCKOUT_WINDOW_SECONDS`` (15 minutes).
    failed_login_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"),
    )
    # Phase 39 B4 — soft-lockout window. NULL = never locked. When set in
    # the future, login returns 401 with ``detail={"reason":
    # "account_locked", "locked_until": <isoformat>}``. Locked attempts
    # still increment ``failed_login_count`` so an attacker can't pause
    # for 15min and resume from where they left off.
    locked_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    user_type: Mapped[str] = mapped_column(
        Enum("human", "ai_agent", name="user_type"),
        nullable=False,
        default="human",
    )
    # Phase 27 — relevance-weighted is the new default. Existing
    # 'strict_precedence' rows were flipped by migration
    # d4e3a91c5f0b. Valid values: "strict_precedence" |
    # "relevance_weighted". The dispatcher in delegation_engine.py
    # gates the relevance-weighted path on voting_method=="binary";
    # other voting methods fall back to strict-precedence regardless.
    delegation_strategy: Mapped[str] = mapped_column(
        String, nullable=False, default="relevance_weighted"
    )
    email: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True, index=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    default_follow_policy: Mapped[str] = mapped_column(
        Enum("require_approval", "auto_approve_view", "auto_approve_delegate",
             name="default_follow_policy"),
        nullable=False,
        default="require_approval",
    )
    # Phase 9.5 — per-user override on the org-creation cap. NULL = use the
    # platform default of 3. A non-null value (including 0) overrides for
    # this user only. Z's account is the obvious case for a high override or
    # NULL passthrough; ordinary users hit the default.
    org_creation_limit: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
    )
    # Phase 9.8 — avatar URL (relative path under the static-files mount,
    # e.g. ``/uploads/avatars/{user_id}/128.jpg``). NULL = no uploaded avatar
    # (frontend renders the initials-on-colored-background fallback). Set by
    # POST /api/users/me/avatar; cleared by DELETE.
    avatar_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Phase 23 (Amendment F) — Phase 24 demo branding prep. Per-person
    # headshot asset path like ``/demo_assets/janet_reilly.jpg``. NULL =
    # no demo headshot (frontend falls back to avatar_url, then to
    # initials). Single image per person — placed on User rather than
    # DelegateProfile because the Stage 8 example is profile-agnostic
    # (one image per person regardless of which topic they're a delegate
    # on). Mirrors the avatar_url pattern above.
    headshot_url: Mapped[Optional[str]] = mapped_column(
        String(length=500), nullable=True,
    )
    # Phase 13 / 13.3 — notification-related per-user preferences.
    # ``timezone`` is an IANA name (e.g. "America/Los_Angeles"); NULL =
    # unknown, treated as UTC by the digest job.
    # ``quiet_hours_enabled`` toggles the local-time email suppression
    # window. ``quiet_hours_start`` / ``quiet_hours_end`` (HH:MM 24-hour
    # strings, Phase 13.3) define the user's adjustable window; defaults
    # 21:00-09:00 match Phase 13's hardcoded behavior.
    # ``notification_intro_dismissed`` records whether the F5 first-time
    # banner has been dismissed.
    #
    # Phase 13.3 retired ``digest_cadence``: per-event cadence is now
    # stored as ``email_immediate`` / ``email_daily`` / ``email_weekly``
    # rows in ``notification_preferences``.
    #
    # The server_default values mirror the migration's column-add defaults
    # so raw-SQL INSERTs that omit these columns (test fixtures, the
    # migration-cycle tests' seed paths) still satisfy the NOT NULL
    # constraint. SQLAlchemy default= covers ORM inserts; server_default=
    # covers the rest.
    timezone: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    quiet_hours_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        server_default="0",
    )
    quiet_hours_start: Mapped[str] = mapped_column(
        String(length=5), nullable=False, default="21:00",
        server_default="21:00",
    )
    quiet_hours_end: Mapped[str] = mapped_column(
        String(length=5), nullable=False, default="09:00",
        server_default="09:00",
    )
    notification_intro_dismissed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        server_default="0",
    )
    # Phase 77 — per-user opt-out of receiving NEW direct-message
    # conversation initiations (conversation_type='direct'). Delegate
    # messages + org-inbox messages still arrive (role-scoped, not
    # personal-preference-scoped); existing conversations stay writable by
    # both participants. server_default mirrors the migration's column-add
    # default so raw-SQL inserts (fixtures, migration-cycle seeds) satisfy
    # NOT NULL. The spec assumed a User.settings JSON blob, which this
    # model doesn't have — a dedicated boolean column is the minimal fit.
    dm_disabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        server_default="0",
    )
    # Phase 19 (D10) — account-level delegate handle. NULL = unset (URL
    # falls back to ``username`` token at /{slug}/delegates/{token}).
    # Reserved-slugs collision validated at write time (route layer);
    # uniqueness enforced at the DB layer via ``uq_users_delegate_handle``.
    delegate_handle: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, unique=True, index=True,
    )
    # Phase 51 — verification state model. Foundation pass: no
    # enforcement is wired against these columns yet (that's Phase
    # 52). ``verification.py`` is the source of truth for the
    # ordered state list + subsumption logic. Provenance ("none" /
    # "persona" / "demo_stub" / "backdoor") distinguishes real-from-
    # stub verifications so demo + audit + (Phase 53) billing
    # surfaces stay honest. The nullifier intentionally has NO
    # ``UniqueConstraint`` here — re-verification semantics live in
    # Phase 52 and the constraint reasoning belongs alongside them.
    verification_state: Mapped[str] = mapped_column(
        String(length=32), nullable=False,
        default="email_only", server_default="email_only",
        index=True,
    )
    verification_jurisdiction: Mapped[Optional[str]] = mapped_column(
        String(length=16), nullable=True,
    )
    # Phase 76c — residency country (ISO 3166-1 alpha-2 code, e.g. "US",
    # "CA"). Captured from the ID's parsed residential address country,
    # independent of the (US-centric) ``verification_jurisdiction`` /
    # state ladder so non-US members can be gated by country. Readable
    # (low-sensitivity, same as jurisdiction); NEVER serialized to
    # non-admin clients. NULL until a verification (or the US backfill)
    # populates it.
    verification_country: Mapped[Optional[str]] = mapped_column(
        String(length=2), nullable=True,
    )
    verification_attestation_id: Mapped[Optional[str]] = mapped_column(
        String(length=128), nullable=True,
    )
    # Phase 58 Cluster C — ``verification_nullifier`` column DROPPED
    # (migration c0d1e2f3a4b5). The Phase 52d hash-dedup model
    # replaced Didit's 1:N nullifier; nothing has written it since.
    # The column + its two indexes (``ix_users_verification_nullifier``,
    # ``ix_users_verification_nullifier_unique``) are gone. Reversible
    # downgrade re-adds the column + the lookup index (not the partial
    # unique).
    verification_provenance: Mapped[str] = mapped_column(
        String(length=16), nullable=False,
        default="none", server_default="none",
    )
    verification_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
    )
    # Phase 52f — readable legal name from Didit's OCR (NOT hashed).
    # The display-name-match feature compares an arbitrary user-entered
    # display name against the legal name, which a hash can't support
    # (partial / first-only matching). Disclosed in consent + Settings
    # copy. NEVER serialized to non-admin clients.
    legal_first_name: Mapped[Optional[str]] = mapped_column(
        String(length=128), nullable=True,
    )
    legal_last_name: Mapped[Optional[str]] = mapped_column(
        String(length=128), nullable=True,
    )
    legal_full_name: Mapped[Optional[str]] = mapped_column(
        String(length=256), nullable=True,
    )
    # Phase 52g — derived age bands; NEVER raw DOB. Stored as a sorted
    # JSON list of met-threshold ints (e.g. ``"[13, 16, 18]"`` =
    # "meets ≥13, ≥16, ≥18; not ≥21"). NULL until a verification
    # populates it. The raw ``date_of_birth`` is consumed only as a
    # hash input + the band-derivation input, then discarded.
    verification_age_bands: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
    )
    # Month-aligned promotion date for the NEXT supported threshold
    # the user will cross. Month granularity (first of the month) so
    # the value can't reconstruct the exact birth day. NULL when the
    # user already meets every supported threshold (the common
    # adult case).
    verification_age_promotes_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
    )
    # Phase 52i — city/locality residency hash.
    # HMAC-SHA256 of ``(normalized_city, normalized_state)`` under
    # the same ``VERIFICATION_HASH_PEPPER`` as the dedup hashes.
    # State is included in the hash so "Springfield, MA" ≠
    # "Springfield, IL". NEVER serialized to clients (extends the
    # 52d hash-exclusion guard). No index — only ever compared to
    # the org's computed gate-hash for the single user being gated,
    # no cross-user lookup.
    verification_locality_hash: Mapped[Optional[str]] = mapped_column(
        String(length=128), nullable=True,
    )
    # Phase 52d — document-hash dedup fields. See
    # ``verification_hashing.compute_hashes`` for the inputs +
    # normalization rules.
    #
    # Phase 58 Cluster C — ``doc_number_hash`` column DROPPED
    # (migration c0d1e2f3a4b5). Phase 52h Stage 2 removed the
    # platform-wide doc-number hard block; Phase 52h Stage 2 also
    # dropped the partial-unique ``ix_users_doc_number_hash_unique``
    # (migration e6f7a8b9c0d1). Nothing wrote it since. Phase 58
    # finishes the cleanup by dropping the column itself plus the
    # remaining ``ix_users_doc_number_hash`` lookup index.
    name_dob_address_hash: Mapped[Optional[str]] = mapped_column(
        String(length=128), nullable=True, index=True,
    )
    name_dob_hash: Mapped[Optional[str]] = mapped_column(
        String(length=128), nullable=True, index=True,
    )
    # Two-tier strength: ``document_hash`` (v1, this phase) or
    # ``biometric`` (architected, deferred). NULL until a unique-tier
    # verification completes.
    uniqueness_strength: Mapped[Optional[str]] = mapped_column(
        String(length=16), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    proposals: Mapped[list["Proposal"]] = relationship("Proposal", back_populates="author")
    delegations_given: Mapped[list["Delegation"]] = relationship(
        "Delegation", foreign_keys="Delegation.delegator_id", back_populates="delegator"
    )
    delegations_received: Mapped[list["Delegation"]] = relationship(
        "Delegation", foreign_keys="Delegation.delegate_id", back_populates="delegate"
    )
    votes: Mapped[list["Vote"]] = relationship("Vote", foreign_keys="Vote.user_id", back_populates="user")
    topic_precedences: Mapped[list["TopicPrecedence"]] = relationship(
        "TopicPrecedence", back_populates="user"
    )
    delegate_profiles: Mapped[list["DelegateProfile"]] = relationship(
        "DelegateProfile", back_populates="user",
        foreign_keys="DelegateProfile.user_id",
    )
    follow_requests_sent: Mapped[list["FollowRequest"]] = relationship(
        "FollowRequest", foreign_keys="FollowRequest.requester_id", back_populates="requester"
    )
    follow_requests_received: Mapped[list["FollowRequest"]] = relationship(
        "FollowRequest", foreign_keys="FollowRequest.target_id", back_populates="target"
    )
    following: Mapped[list["FollowRelationship"]] = relationship(
        "FollowRelationship", foreign_keys="FollowRelationship.follower_id", back_populates="follower"
    )
    followers: Mapped[list["FollowRelationship"]] = relationship(
        "FollowRelationship", foreign_keys="FollowRelationship.followed_id", back_populates="followed"
    )
    org_memberships: Mapped[list["OrgMembership"]] = relationship(
        "OrgMembership", back_populates="user"
    )
    sub_org_memberships: Mapped[list["SubOrgMembership"]] = relationship(
        "SubOrgMembership", back_populates="user"
    )
    # Phase 19 (B2) — per-org delegate identity rows.
    org_delegate_profiles: Mapped[list["OrgDelegateProfile"]] = relationship(
        "OrgDelegateProfile", back_populates="user",
        foreign_keys="OrgDelegateProfile.user_id",
        cascade="all, delete-orphan",
    )


class Topic(Base):
    __tablename__ = "topics"
    # Phase 30.1 B5: uniqueness scoped to (org_id, name) — was previously
    # a global unique on `name`. The change kills the recurring "demo orgs
    # need to prefix Topic.name with bible.slug for global uniqueness"
    # footgun (Phases 23.1 / 25 / 26 / 28 / 30 all patched display-side
    # leakage of that prefix). Migration ``a8c2d51e9f10`` drops the
    # global constraint, adds the scoped one, and strips the prefix from
    # existing rows.
    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_topics_org_id_name"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # Phase 33 D2 — `description` column dropped. Phase 30.1's root-cause
    # fix made `Topic.name` the canonical display name (uniquely scoped per-
    # org via UniqueConstraint("org_id", "name")). The old `description`
    # column was a same-value clone preserved for back-compat; Phase 33
    # drops it.
    color: Mapped[str] = mapped_column(String, nullable=False, default="#6366f1")
    # Phase 56 — optional one-line description of what a topic is for.
    # GUARD: this is NOT the resurrected Phase-33 `description` clone.
    # `name` remains the canonical display name; `purpose` is a separate
    # explanatory text shown as a subtitle in topic management + the
    # proposal-creation picker. Never wire it into display-name fallback.
    # Plain text on render (no markdown / HTML — XSS-safe by treating as
    # text).
    purpose: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Phase 56 — optional free-text label for grouping in pickers when an
    # org enables `settings.topic_categories_enabled`. No validation
    # beyond length (orgs name their own categories). Retained on the row
    # when the toggle is OFF so re-enabling restores grouping.
    category: Mapped[Optional[str]] = mapped_column(
        String(length=80), nullable=True,
    )
    # Phase 65 — per-topic delegation disallow flag. False = proposals
    # touching this topic are direct-vote-only (D1: ANY disallowed topic
    # gates the WHOLE proposal). Existing Delegation rows on a disallowed
    # topic are kept but inert (D2) — never deleted; flipping the flag
    # back restores behavior. default + server_default true so existing
    # rows and freshly-constructed Topic() instances behave unchanged.
    allow_delegation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
    )
    org_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("organizations.id"), nullable=True, index=True)
    # Phase 8.5: NULL = parent-org-wide (default); non-NULL = scoped to that sub-org.
    sub_org_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=True, index=True
    )

    organization: Mapped[Optional["Organization"]] = relationship(
        "Organization", back_populates="topics", foreign_keys=[org_id]
    )
    sub_organization: Mapped[Optional["Organization"]] = relationship(
        "Organization", foreign_keys=[sub_org_id]
    )
    proposal_topics: Mapped[list["ProposalTopic"]] = relationship(
        "ProposalTopic", back_populates="topic"
    )
    delegations: Mapped[list["Delegation"]] = relationship("Delegation", back_populates="topic")
    topic_precedences: Mapped[list["TopicPrecedence"]] = relationship(
        "TopicPrecedence", back_populates="topic"
    )
    delegate_profiles: Mapped[list["DelegateProfile"]] = relationship(
        "DelegateProfile", back_populates="topic"
    )


class Proposal(Base):
    __tablename__ = "proposals"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    author_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    org_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("organizations.id"), nullable=True, index=True)
    # Phase 8.5: NULL = parent-org-wide (default); non-NULL = scoped to that sub-org.
    sub_org_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(
        Enum(
            "draft", "deliberation", "voting", "passed", "failed",
            "withdrawn", "unresolved",
            # Phase 46 — cosign-gated proposals whose gathering window
            # elapsed without meeting the signature threshold land in
            # this terminal state. Distinct from 'failed' so analytics
            # and the FE can tell "people voted no" apart from "the
            # petition never got off the ground."
            "expired_unsigned",
            name="proposal_status",
        ),
        nullable=False,
        default="draft",
    )
    deliberation_start: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    voting_start: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    voting_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    voting_method: Mapped[str] = mapped_column(
        String, nullable=False, default="binary",
    )
    num_winners: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    tie_resolution: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    pass_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.50)
    quorum_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.40)
    # Phase 16 — per-proposal duration overrides.
    # null = inherit org default at advance-to-voting time; non-null = the
    # author/editor (with `proposal.set_durations`) explicitly set a custom
    # window. Floats so live-poll sub-day voting windows (>= 0.05 days =
    # 72 minutes) are representable.
    #
    # Phase 25 B1.1 wires the actual advance-time consumption:
    # `_compute_voting_end_at_advance` in routes/proposals.py reads
    # `voting_days` at the deliberation → voting transition and sets
    # `voting_end = voting_start + timedelta(days=voting_days)`. Phase 25
    # B2 also reads `deliberation_days` at create time: when it resolves
    # to 0, the proposal skips the deliberation phase and is created
    # directly in `voting` status.
    deliberation_days: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    voting_days: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Phase 75a — absolute voting deadline. NULL = use voting_days or org
    # default (today's behavior). When set, _compute_voting_end_at_advance uses
    # this directly as voting_end instead of computing from voting_days.
    # Timezone stripped at storage (naive UTC, matching voting_end convention).
    voting_end_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
    )
    # Phase 8 / Phase 20: per-proposal "Stable Result Required" override.
    # null = inherit org default; True/False = explicit per-proposal opt-in/out.
    # Authors can only set non-null when org has
    # `stable_result_per_proposal_override: true`. Renamed in Phase 20 from
    # `sustained_majority_enabled` (D12) to align with the user-facing rebrand.
    stable_result_required: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    # Phase 9: structurally-recorded links to Polis artifacts. List of
    # `polises.id` UUID strings. Null = unset (no structural links); empty
    # list = author explicitly cleared. URL-detected links in the proposal
    # body are NOT stored here — they are rendered by the body parser at
    # read time. This column only carries the structurally-recorded set
    # used by the `require_polis_for_new_proposals` enforcement and the
    # admin "linked deliberations" picker.
    linked_polis_ids: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # Phase 32 — per-proposal overrides for org-level deliberation-engagement
    # settings. All nullable; null = inherit the org's ``settings.<key>``
    # JSONB default (resolved at read time by the route handler). Phase 32
    # D22 says pre-existing proposals are unaffected: nulls preserve
    # today's behavior.
    allow_write_in_options: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True,
    )
    allow_write_ins_during_voting: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True,
    )
    max_write_ins: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    allow_pre_voting: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True,
    )
    show_votes_during_deliberation: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True,
    )
    edit_lockout_fraction: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
    )
    # Phase 46 — cosign-gated proposal markers (B2/B3). Set when the
    # creating org is in ``cosign_required`` mode AND the creator is a
    # member-tier user (no proposal.create permission). The proposal
    # enters ``deliberation`` status with these set; signatures accumulate
    # via ``proposal_cosignatures`` rows; reaching the threshold advances
    # to voting via the existing /advance machinery; the worker closes
    # un-met proposals at ``cosign_expires_at`` into ``expired_unsigned``.
    # ``cosign_threshold_snapshot`` is captured at create time so later
    # org-config changes don't move the goalposts mid-petition (D3).
    is_cosign_gated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0",
    )
    cosign_threshold_snapshot: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
    )
    cosign_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True,
    )
    # Phase 48 Stage 1 — election subtype (D1). When ``is_election=True``,
    # this proposal fills the target ``OrgTitle`` (and its optionally
    # bound platform role) on voting close. ``election_title_id`` is
    # the title that will be filled by the winner(s). The candidate set
    # lives in ``election_candidacies``. Non-election proposals carry
    # ``is_election=False`` and ``election_title_id=None`` — the existing
    # proposal behavior is byte-identical.
    is_election: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0",
    )
    election_title_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("org_titles.id"), nullable=True, index=True,
    )
    # Phase 48 Stage 2 — D10 slate behavior. ``refresh_slate`` removes
    # all current holders of the target title before installing the
    # winners (whole-slate refresh); ``fill_vacancies`` adds the winners
    # alongside existing holders. Default ``fill_vacancies`` keeps
    # behavior closest to a non-disruptive single-winner election.
    election_slate_mode: Mapped[str] = mapped_column(
        String(length=16), nullable=False,
        default="fill_vacancies", server_default="fill_vacancies",
    )
    # Phase 49 — record which trigger opened this election so the
    # close hook (``finalize_election``) can decide whether to
    # advance the title's ``next_election_due_at`` (only scheduled
    # elections advance the calendar; off-cycle admin/cosign
    # elections leave the schedule fixed per B4). NULL for non-
    # election proposals + for Stage 1/2 elections that pre-existed
    # this column (the server_default 'admin_direct' is conservative
    # since pre-Stage-3 only the admin-direct path existed).
    election_trigger: Mapped[Optional[str]] = mapped_column(
        String(length=16), nullable=True,
    )
    # Phase 52 (Stage 52) — per-proposal verification gate. NULL =
    # no gate (today's behavior; the additive-layer invariant is
    # that an ungated proposal is byte-for-byte unchanged). Non-null
    # = floor required to cast a *direct* vote on this proposal.
    # ``verification_jurisdiction`` is optional; consistency vs the
    # floor (jurisdiction_required_for) is enforced at the route
    # layer, not the DB, so historical rows don't fail any check.
    verification_floor: Mapped[Optional[str]] = mapped_column(
        String(length=32), nullable=True,
    )
    verification_jurisdiction: Mapped[Optional[str]] = mapped_column(
        String(length=16), nullable=True,
    )
    # Phase 52g — per-proposal minimum age. NULL = no age gate
    # (the default; matches the ``verification_floor`` precedent).
    # Validated against ``verification.SUPPORTED_AGE_THRESHOLDS`` at
    # the route layer.
    min_age: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
    )
    # Phase 66 — multi-winner approval selection config (D1). NULL =
    # legacy single-winner behavior, byte-for-byte (additive-layer
    # invariant). Non-null = the generalized form
    # ``{min_winners: int>=0, max_winners: int>=1|null,
    #   approval_threshold: float in (0,1]|null}``; the FE's three
    # presets (Top X / threshold / floor+extras) all write this shape.
    # Approval voting_method only; rejected at the route layer for
    # binary / ranked_choice and for election proposals (66a wires
    # elections). ``approval_threshold`` is a FRACTION of ballots cast
    # (mirrors ``pass_threshold`` conventions, D2).
    approval_winner_config: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True,
    )
    # Phase 73 — budget-voting config (allocation mode). NULL = not a budget
    # proposal (every non-budget row; additive-layer invariant — an existing
    # proposal with NULL is byte-for-byte unchanged). Shape for allocation:
    #   {"mode": "allocation", "envelope": 100000, "currency": "USD",
    #    "aggregation": "median" | "trimmed_mean"}
    # Phase 74 will reuse this column with mode == "project" (discrete items).
    budget_config: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)

    author: Mapped["User"] = relationship("User", back_populates="proposals")
    organization: Mapped[Optional["Organization"]] = relationship(
        "Organization", back_populates="proposals", foreign_keys=[org_id]
    )
    sub_organization: Mapped[Optional["Organization"]] = relationship(
        "Organization", foreign_keys=[sub_org_id]
    )
    proposal_topics: Mapped[list["ProposalTopic"]] = relationship(
        "ProposalTopic", back_populates="proposal", cascade="all, delete-orphan"
    )
    options: Mapped[list["ProposalOption"]] = relationship(
        "ProposalOption", back_populates="proposal", cascade="all, delete-orphan",
        order_by="ProposalOption.display_order",
    )
    votes: Mapped[list["Vote"]] = relationship("Vote", back_populates="proposal", cascade="all, delete-orphan")
    vote_snapshots: Mapped[list["VoteSnapshot"]] = relationship(
        "VoteSnapshot", back_populates="proposal", cascade="all, delete-orphan"
    )
    revisions: Mapped[list["ProposalRevision"]] = relationship(
        "ProposalRevision", back_populates="proposal",
        cascade="all, delete-orphan",
        order_by="ProposalRevision.edited_at",
    )
    # Phase 46 — cosignature rows (B2). Cascade-delete so withdrawing a
    # cosign-gated proposal cleans up the audit floor too. Ordered by
    # ``created_at`` so the FE can render a chronological list.
    cosignatures: Mapped[list["ProposalCosignature"]] = relationship(
        "ProposalCosignature", back_populates="proposal",
        cascade="all, delete-orphan",
        order_by="ProposalCosignature.created_at",
    )

    @property
    def topic_ids(self) -> list[str]:
        return [pt.topic_id for pt in self.proposal_topics]


class ProposalCosignature(Base):
    """Phase 46 — one signature on a cosign-gated proposal (B2).

    Unique on (proposal_id, user_id) so the one-per-member semantic (D4)
    is a DB invariant. The author's implicit first signature is also a
    row (per D3 author-counts-as-1), inserted at create time.
    """
    __tablename__ = "proposal_cosignatures"
    __table_args__ = (
        UniqueConstraint(
            "proposal_id", "user_id",
            name="uq_proposal_cosignatures_proposal_user",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    proposal_id: Mapped[str] = mapped_column(
        String, ForeignKey("proposals.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, nullable=False,
    )

    proposal: Mapped["Proposal"] = relationship(
        "Proposal", back_populates="cosignatures",
    )


class ProposalOption(Base):
    __tablename__ = "proposal_options"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    proposal_id: Mapped[str] = mapped_column(String, ForeignKey("proposals.id"), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    # Phase 32 W1 — write-in attribution. Original options created at
    # proposal-create time have ``added_by_user_id=NULL`` /
    # ``added_at=NULL`` / ``is_write_in=False``. Write-ins added via
    # ``POST /api/proposals/{id}/options`` carry the adder's user ID +
    # the insert timestamp, and ``is_write_in=True``.
    added_by_user_id: Mapped[Optional[str]] = mapped_column(
        String,
        ForeignKey(
            "users.id",
            name="fk_proposal_options_added_by_user_id_users",
        ),
        nullable=True,
    )
    added_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
    )
    is_write_in: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0",
    )

    # Phase 73 — budget bucket metadata. NULL on every non-budget option
    # (additive-layer invariant: approval/RCV options are unchanged). For an
    # allocation-mode bucket this is the per-bucket ceiling: the bucket is
    # fundable in [0, budget_max_amount]. NULL on a budget option means the
    # ceiling is the full envelope (the bucket can absorb the whole pool).
    # Phase 74 will extend this table again (budget_floor_amount, budget_kind,
    # tier columns) for discrete project items.
    budget_max_amount: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
    )
    # Phase 74 — discrete project-item cost metadata. NULL on non-project
    # options. ``budget_floor_amount`` is the all-or-nothing cost (funded at
    # this or $0). ``budget_kind`` ∈ {discrete, continuous-as-discrete,
    # tier_parent}. ``budget_tier_parent_id`` FKs the tier parent on tier
    # children (74b). ``tier_allow_fallback`` controls tier fall-back (74b).
    # (The mandatory-minimum feature was CUT in the 74 follow-up; its dead
    # ``budget_is_mandatory`` column was dropped in migration a5b6c7d8e9f0.)
    budget_floor_amount: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
    )
    budget_kind: Mapped[Optional[str]] = mapped_column(
        String, nullable=True,
    )
    budget_tier_parent_id: Mapped[Optional[str]] = mapped_column(
        String, nullable=True,
    )
    tier_allow_fallback: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True,
    )

    proposal: Mapped["Proposal"] = relationship("Proposal", back_populates="options")
    added_by: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[added_by_user_id],
    )


class ProposalRevision(Base):
    """Phase 32 E1 — versioned snapshot of every author edit during
    deliberation.

    One row per ``PATCH /api/proposals/{id}`` call that mutates editable
    fields (D15). Snapshots are JSON-serialized states of the relevant
    fields BEFORE and AFTER the edit; ``changed_fields`` lists which keys
    actually differ. Visible to all org members per D17 (transparency-
    first; opt-in inspection via the change-log accordion on the
    proposal detail page).

    Phase 18 multi-tenancy convention: ``org_id`` on day one so any
    cross-org / org-scoped query against revisions is correctly scoped
    without joining through Proposal.
    """
    __tablename__ = "proposal_revisions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    proposal_id: Mapped[str] = mapped_column(
        String, ForeignKey("proposals.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=False, index=True,
    )
    edited_by_user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True,
    )
    edited_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, nullable=False,
    )
    snapshot_before: Mapped[dict] = mapped_column(JSON, nullable=False)
    snapshot_after: Mapped[dict] = mapped_column(JSON, nullable=False)
    changed_fields: Mapped[list] = mapped_column(JSON, nullable=False)

    proposal: Mapped["Proposal"] = relationship(
        "Proposal", back_populates="revisions",
    )
    editor: Mapped["User"] = relationship(
        "User", foreign_keys=[edited_by_user_id],
    )


class ProposalTopic(Base):
    __tablename__ = "proposal_topics"

    proposal_id: Mapped[str] = mapped_column(String, ForeignKey("proposals.id"), primary_key=True)
    topic_id: Mapped[str] = mapped_column(String, ForeignKey("topics.id"), primary_key=True)
    relevance: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    proposal: Mapped["Proposal"] = relationship("Proposal", back_populates="proposal_topics")
    topic: Mapped["Topic"] = relationship("Topic", back_populates="proposal_topics")


class Delegation(Base):
    __tablename__ = "delegations"
    # Phase 18 (org-scoping retrofit): the unique constraint now includes
    # ``org_id`` + ``sub_org_id`` so a user can have one global-per-org
    # delegation per org (and one global-per-sub-org per sub-org). NULL
    # treatment in PG/SQLite is "distinct," so the constraint allows the
    # NULL/NULL/NULL row shape (org-wide global) once per (delegator, org).
    __table_args__ = (
        UniqueConstraint(
            "delegator_id", "org_id", "sub_org_id", "topic_id",
            name="uq_delegation_delegator_org_subor_topic",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    delegator_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    delegate_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    # Phase 18: nullable in 18a (backfill running), flipped to NOT NULL in
    # 18b once the backfill has been verified. Phase 39 B3 — ORM declaration
    # synced to the post-18b DB shape (the DB has been NOT NULL since
    # migration e9419ee5906f; the model was still declaring nullable=True,
    # producing divergent schemas on the fresh-DB vs upgraded-DB branches).
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=False, index=True,
    )
    # Phase 18 (D4): sub-org scope is optional and stays nullable post-18b.
    sub_org_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=True, index=True,
    )
    topic_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("topics.id"), nullable=True, index=True)
    chain_behavior: Mapped[str] = mapped_column(
        Enum("accept_sub", "revert_direct", "abstain", name="chain_behavior"),
        nullable=False,
        default="accept_sub",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)

    delegator: Mapped["User"] = relationship(
        "User", foreign_keys=[delegator_id], back_populates="delegations_given"
    )
    delegate: Mapped["User"] = relationship(
        "User", foreign_keys=[delegate_id], back_populates="delegations_received"
    )
    topic: Mapped[Optional["Topic"]] = relationship("Topic", back_populates="delegations")


class TopicPrecedence(Base):
    __tablename__ = "topic_precedences"
    __table_args__ = (UniqueConstraint("user_id", "topic_id", name="uq_precedence_user_topic"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    topic_id: Mapped[str] = mapped_column(String, ForeignKey("topics.id"), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    user: Mapped["User"] = relationship("User", back_populates="topic_precedences")
    topic: Mapped["Topic"] = relationship("Topic", back_populates="topic_precedences")


class Vote(Base):
    __tablename__ = "votes"
    __table_args__ = (UniqueConstraint("proposal_id", "user_id", name="uq_vote_proposal_user"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    proposal_id: Mapped[str] = mapped_column(String, ForeignKey("proposals.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    vote_value: Mapped[Optional[str]] = mapped_column(
        Enum("yes", "no", "abstain", name="vote_value"),
        nullable=True,
    )
    ballot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    is_direct: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    delegate_chain: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    cast_by_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    cast_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)

    proposal: Mapped["Proposal"] = relationship("Proposal", back_populates="votes")
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id], back_populates="votes")
    cast_by: Mapped["User"] = relationship("User", foreign_keys=[cast_by_id])
    # Phase 19 (D4) — optional one-to-one rationale row.
    rationale: Mapped[Optional["DelegateVoteRationale"]] = relationship(
        "DelegateVoteRationale", back_populates="vote", uselist=False,
        cascade="all, delete-orphan",
    )


class VoteSnapshot(Base):
    """Periodic tally snapshots during the voting window for time-series tracking.

    Phase 8: extended with `multi_option_winners` JSON to record the live
    winner set for approval / ranked_choice proposals at snapshot time, used
    by the sustained-majority worker to detect winner changes across restarts.
    Null for binary proposals.
    """

    __tablename__ = "vote_snapshots"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    proposal_id: Mapped[str] = mapped_column(String, ForeignKey("proposals.id"), nullable=False, index=True)
    simulated_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    yes_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    no_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    abstain_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    not_cast_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_eligible: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    # Phase 8 — multi-option winner snapshot for stable-result evaluation.
    # Shape: {"winners": [option_id, ...], "total_ballots_cast": int}
    multi_option_winners: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    proposal: Mapped["Proposal"] = relationship("Proposal", back_populates="vote_snapshots")


class AuditLog(Base):
    """
    Append-only audit log — records every state-changing action.
    No UPDATE or DELETE operations ever. Write in same transaction as the action.
    """

    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False, index=True)
    actor_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String, nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String, nullable=False)
    target_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class DelegateProfile(Base):
    """
    A user registered as a public delegate for a specific topic.
    Makes their votes on that topic publicly visible and allows anyone to delegate
    to them on that topic without a prior follow relationship.
    """
    __tablename__ = "delegate_profiles"
    __table_args__ = (UniqueConstraint("user_id", "topic_id", name="uq_delegate_profile_user_topic"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    topic_id: Mapped[str] = mapped_column(String, ForeignKey("topics.id"), nullable=False, index=True)
    org_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("organizations.id"), nullable=True, index=True)
    # Phase 8.5: NULL = parent-org-wide (default); non-NULL = profile scoped to that sub-org.
    # Stored explicitly (rather than derived from topic) for query efficiency per spec.
    sub_org_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=True, index=True
    )
    bio: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Phase 19 (D1) — per-topic visibility enum. Replaces the implicit
    # "having a row = publicly accepting delegation" model with three
    # explicit states. ``server_default='public_accepting'`` mirrors the
    # migration's D8 backwards-compat default so existing rows keep
    # behaving as public-accepting delegates without action.
    # Phase 30.3 — added "followers_only" between private and public to
    # collapse the two-layer visibility model (was: this column + the
    # separate OrgDelegateProfile.page_visibility). The new ladder:
    # private < followers_only < public < public_accepting. Default for
    # new rows is "followers_only" so a user with at least one approved
    # follower has their activity visible by default (matches the
    # de-facto pre-Phase-30.3 behavior where any follow-relationship
    # row granted vote visibility).
    visibility: Mapped[str] = mapped_column(
        Enum(
            "private", "followers_only", "public", "public_accepting",
            name="delegate_profile_visibility",
        ),
        nullable=False,
        default="followers_only",
        server_default="followers_only",
    )
    # Phase 19 — optional per-topic position statement (markdown).
    position_statement: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Phase 19 (D6) — approval-workflow lifecycle metadata. Pending iff
    # ``submitted_at IS NOT NULL AND approved_at IS NULL``.
    public_accepting_submitted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
    )
    public_accepting_approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
    )
    public_accepting_approved_by_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id"), nullable=True,
    )
    public_accepting_denied_comment: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    user: Mapped["User"] = relationship(
        "User", back_populates="delegate_profiles", foreign_keys=[user_id],
    )
    topic: Mapped["Topic"] = relationship("Topic", back_populates="delegate_profiles")
    organization: Mapped[Optional["Organization"]] = relationship(
        "Organization", back_populates="delegate_profiles", foreign_keys=[org_id]
    )
    sub_organization: Mapped[Optional["Organization"]] = relationship(
        "Organization", foreign_keys=[sub_org_id]
    )
    public_accepting_approved_by: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[public_accepting_approved_by_id],
    )


class OrgDelegateProfile(Base):
    """Phase 19 (D2) — per-user-per-org delegate identity.

    Holds the org-scoped intro markdown. Phase 30.3 dropped the
    ``page_visibility`` column + its supporting enum (and the
    ``effective_page_visibility`` derivation method); per-topic
    ``DelegateProfile.visibility`` is the sole source of truth for
    audience now.
    """

    __tablename__ = "org_delegate_profiles"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "org_id",
            name="uq_org_delegate_profile_user_org",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True,
    )
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=False, index=True,
    )
    intro: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False,
    )

    user: Mapped["User"] = relationship(
        "User", back_populates="org_delegate_profiles",
        foreign_keys=[user_id],
    )
    org: Mapped["Organization"] = relationship(
        "Organization", back_populates="delegate_profiles_org",
        foreign_keys=[org_id],
    )


class DelegateVoteRationale(Base):
    """Phase 19 (D4) — per-vote rationale row.

    One row per ``Vote`` (``vote_id`` is unique). Absence of a row means
    no rationale. Vote rows themselves stay append-only audit-grade —
    rationale lives in this side table so editing/deleting a rationale
    doesn't touch the vote record.

    Visibility on the public delegate page filters to votes whose
    proposal's primary topic is in non-``'private'`` state for that
    user-org pair (centralized in ``can_view_vote_rationale`` helper
    in B6, not duplicated across endpoints).
    """

    __tablename__ = "delegate_vote_rationales"
    __table_args__ = (
        UniqueConstraint(
            "vote_id",
            name="uq_delegate_vote_rationale_vote_id",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    vote_id: Mapped[str] = mapped_column(
        String, ForeignKey("votes.id"), nullable=False, index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False,
    )

    vote: Mapped["Vote"] = relationship("Vote", back_populates="rationale")


class FollowRequest(Base):
    """
    A request from one user to follow another.
    Kept after approval/denial for audit purposes.
    """
    __tablename__ = "follow_requests"
    # Phase 18 follow-up (1cc8f3f27717): unique key includes ``org_id`` so
    # the same pair can have separate per-org follow requests. NULL/NULL
    # rows during the 18a backfill window are distinct under PG/SQLite
    # NULL semantics.
    __table_args__ = (
        UniqueConstraint(
            "requester_id", "target_id", "org_id",
            name="uq_follow_request_requester_target_org",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    requester_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    target_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    # Phase 18 (D2): follow requests are now org-scoped to prevent
    # delegation_allowed approvals leaking cross-org. Nullable in 18a;
    # NOT NULL in 18b once backfill is verified. Phase 39 B3 — ORM
    # declaration synced to the post-18b DB shape.
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=False, index=True,
    )
    status: Mapped[str] = mapped_column(
        Enum("pending", "approved", "denied", name="follow_request_status"),
        nullable=False,
        default="pending",
    )
    permission_level: Mapped[Optional[str]] = mapped_column(
        Enum("view_only", "delegation_allowed", name="follow_permission_level"),
        nullable=True,
    )
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    responded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    requester: Mapped["User"] = relationship(
        "User", foreign_keys=[requester_id], back_populates="follow_requests_sent"
    )
    target: Mapped["User"] = relationship(
        "User", foreign_keys=[target_id], back_populates="follow_requests_received"
    )


class FollowRelationship(Base):
    """
    An active follow relationship created when a FollowRequest is approved,
    or automatically when target has auto_approve_* policy.
    """
    __tablename__ = "follow_relationships"
    # Phase 18 follow-up (1cc8f3f27717): unique key includes ``org_id`` so
    # the same pair can co-exist as separate per-org follow rows (the D2
    # back-door-leak fix). NULL/NULL rows during the 18a backfill window
    # are distinct under PG/SQLite NULL semantics; once 18b lands and
    # ``org_id`` is NOT NULL, the constraint is fully meaningful.
    __table_args__ = (
        UniqueConstraint(
            "follower_id", "followed_id", "org_id",
            name="uq_follow_relationship_org",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    follower_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    followed_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    # Phase 18 (D2): follows are now org-scoped to prevent the cross-org
    # delegation_allowed back-door. Nullable in 18a; NOT NULL in 18b once
    # backfill is verified. The (follower_id, followed_id) unique constraint
    # is intentionally LEFT in place for 18a — the production "one
    # account-level follow per pair" shape is preserved during backfill;
    # the next pass that exercises per-org follows on the write side will
    # need to revisit the constraint shape (e.g., add org_id to it).
    # Phase 39 B3 — ORM declaration synced to the post-18b DB shape.
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=False, index=True,
    )
    permission_level: Mapped[str] = mapped_column(
        Enum("view_only", "delegation_allowed", name="follow_permission_level"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    follower: Mapped["User"] = relationship(
        "User", foreign_keys=[follower_id], back_populates="following"
    )
    followed: Mapped["User"] = relationship(
        "User", foreign_keys=[followed_id], back_populates="followers"
    )


class EmailVerification(Base):
    __tablename__ = "email_verifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String, nullable=False)
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    user: Mapped["User"] = relationship("User")


class PasswordReset(Base):
    __tablename__ = "password_resets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    user: Mapped["User"] = relationship("User")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    user: Mapped["User"] = relationship("User")


class PlatformSetting(Base):
    """Phase 9.5 — single-row-per-key platform-wide config.

    Picked Option A (table) per the spec: a `(key, value, updated_at)` table
    is more extensible than stuffing JSON onto an existing row. Initial seed
    inserted by the 373e1f066cc1 migration: ``('org_creation_mode', 'open')``.

    `value` is JSON so we can store strings, bools, numbers, or nested
    config without further schema work. Read at hot paths (e.g.
    `POST /api/orgs` reads `org_creation_mode`); writes go through the
    `PATCH /api/admin/platform-settings` endpoint, which audits old/new.
    """
    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Optional[object]] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False,
    )


class DelegationIntent(Base):
    """
    Queued delegation that auto-activates when the linked follow_request
    is approved with delegation_allowed permission.
    """
    __tablename__ = "delegation_intents"
    # Phase 18: unique constraint extended with org_id + sub_org_id to
    # match the new Delegation table shape. NULL/NULL/NULL is allowed by
    # PG/SQLite distinct-NULL semantics, so the constraint only catches
    # exact (delegator, delegate, org, sub_org, topic) duplicates.
    __table_args__ = (
        UniqueConstraint(
            "delegator_id", "delegate_id", "org_id", "sub_org_id", "topic_id",
            name="uq_delegation_intent_org_subor",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    delegator_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True
    )
    delegate_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True
    )
    # Phase 18: nullable in 18a (backfill running), NOT NULL in 18b.
    # Phase 39 B3 — ORM declaration synced to the post-18b DB shape.
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=False, index=True,
    )
    sub_org_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=True, index=True,
    )
    topic_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("topics.id"), nullable=True
    )
    chain_behavior: Mapped[str] = mapped_column(
        Enum("accept_sub", "revert_direct", "abstain", name="chain_behavior"),
        nullable=False,
        default="accept_sub",
    )
    follow_request_id: Mapped[str] = mapped_column(
        String, ForeignKey("follow_requests.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Enum("pending", "activated", "expired", "cancelled",
             name="delegation_intent_status"),
        nullable=False,
        default="pending",
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    delegator: Mapped["User"] = relationship("User", foreign_keys=[delegator_id])
    delegate: Mapped["User"] = relationship("User", foreign_keys=[delegate_id])
    topic: Mapped[Optional["Topic"]] = relationship("Topic")
    follow_request: Mapped["FollowRequest"] = relationship("FollowRequest")


# ---------------------------------------------------------------------------
# Phase 9 — Polis (standalone deliberation artifact)
# ---------------------------------------------------------------------------

class Polis(Base):
    """A standalone deliberation artifact, parallel to Topic and Proposal.

    Phase 9 Decision 1: a Polis is a first-class organizational artifact
    with its own lifecycle (`active` -> `archived`), not a phase coupled
    to a proposal. Visibility scope mirrors topics/proposals: org-wide
    when ``sub_org_id`` IS NULL, sub-org-scoped otherwise.

    The platform stores ``polis_conversation_id`` (the opaque slug returned
    by pol.is, 6-300 chars per pol.is API) so we can build embed URLs and
    fetch live participation stats. The column is nullable to support the
    manual-creation fallback flow (admin creates the conversation on pol.is
    first, then pastes the conversation_id into the platform); see
    `phase9_polis_api_findings.md`.
    """
    __tablename__ = "polises"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=False, index=True,
    )
    # Phase 9 Decision 5: NULL = org-wide, non-NULL = sub-org-scoped.
    sub_org_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=True, index=True,
    )
    # Opaque slug from pol.is. 6-300 chars per pol.is API; nullable for
    # manual-creation fallback / pending states.
    polis_conversation_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True,
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True,
    )
    # Phase 9 Decision 8: lifecycle is `active` -> `archived`. Stored as
    # plain String to match Phase 8's pattern (avoids enum-rebuild
    # migration headaches across PG/SQLite).
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False,
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Phase 9 Session 2: operator-entered seed statements at create-Polis time.
    # Programmatic path (POLIS_AUTH_TOKEN set): source of truth for
    # polis_service.add_seed_statements() so a partial-failure replay can
    # know what was supposed to be inserted. Manual-fallback path (no token):
    # reference list for the "paste these into pol.is admin UI" UX in the
    # frontend. Nullable; treated as "none recorded" (== empty list) by
    # consumers. Stored as a JSON array of strings.
    intended_seed_statements: Mapped[Optional[list[str]]] = mapped_column(
        JSON, nullable=True,
    )

    organization: Mapped["Organization"] = relationship(
        "Organization", foreign_keys=[org_id],
    )
    sub_organization: Mapped[Optional["Organization"]] = relationship(
        "Organization", foreign_keys=[sub_org_id],
    )
    creator: Mapped["User"] = relationship("User", foreign_keys=[created_by])


class Comment(Base):
    """Phase 10 — proposal comments.

    Lightweight discussion thread attached to a proposal. Supports one level
    of reply threading (``parent_comment_id`` non-null = reply, must point at
    a top-level comment; enforced at the route layer). Soft-delete via
    ``deleted_at``: when set, the row stays so reply children still render
    correctly but the body is replaced with ``[deleted]`` in the UI.

    Hard-delete cascade on ``proposal_id`` and ``author_id`` matches existing
    patterns: a deleted user's comments go away; a deleted proposal's
    comments go away. The CASCADE on ``parent_comment_id`` means hard-deleting
    a top-level comment also hard-deletes its replies — separate from the
    soft-delete affordance the *author* exercises via DELETE.
    """
    __tablename__ = "comments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    proposal_id: Mapped[str] = mapped_column(
        String, ForeignKey("proposals.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    author_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    parent_comment_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("comments.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False,
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    proposal: Mapped["Proposal"] = relationship("Proposal", foreign_keys=[proposal_id])
    author: Mapped["User"] = relationship("User", foreign_keys=[author_id])
    parent: Mapped[Optional["Comment"]] = relationship(
        "Comment", remote_side="Comment.id",
    )


class PolisXid(Base):
    """Per-user-per-org pseudonymous ID for pol.is participation.

    Phase 9 Decision 4 — identity bridging. The `polis_xid` is an opaque
    random string passed to pol.is via the embed's ``data-xid`` attribute,
    so that:
      - participants get cross-session continuity within a Polis (same xid
        -> same dot in the visualization);
      - pol.is doesn't see platform user identity;
      - the platform can deanonymize for moderation by joining
        ``polis_xid -> user_id``.

    Generated lazily on the user's first Polis interaction in the org via
    `polis_service.get_or_create_polis_xid`. Per-org-isolated: the same
    user gets a different xid in different orgs.
    """
    __tablename__ = "polis_xids"
    __table_args__ = (
        UniqueConstraint("user_id", "org_id", name="uq_polis_xid_user_org"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True,
    )
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=False, index=True,
    )
    # Opaque random string. Format: secrets.token_urlsafe(16) ~ 22 chars.
    # Pol.is accepts xid 1-999 chars (see phase9_polis_api_findings.md), so
    # this fits comfortably with headroom.
    polis_xid: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])
    organization: Mapped["Organization"] = relationship(
        "Organization", foreign_keys=[org_id],
    )


# ---------------------------------------------------------------------------
# Phase 13 — Notifications
# ---------------------------------------------------------------------------

class Notification(Base):
    """Phase 13 — a single notification row delivered to a user.

    A row is inserted by ``backend/notification_emit.emit_notification`` when
    the recipient has the (event_type, "in_app") preference enabled (opt-in
    default = absent row treated as False). Email-channel delivery is a
    parallel path; rows here are the in-app feed source-of-truth.

    ``org_id`` is the load-bearing field for click-through routing — see
    Item 22 in ``docs/tech_debt_audit_2026-05.md``. The legacy
    NotificationBadge defaulted to "first parent org"; the new system uses
    this column to resolve the correct ``org_slug`` for the click target.
    Account-level notifications (``follow.approved``, etc.) carry NULL
    ``org_id`` and route to the account-level full feed instead.

    ``actor_id`` is the user who *caused* the event (the commenter, the
    inviter, etc.) — distinct from ``user_id`` (the recipient). Nullable
    for system-originated events. ``target_type`` + ``target_id`` together
    identify the entity the event references (e.g. ("comment", "<uuid>"),
    ("proposal", "<uuid>")) so the frontend can build deep-link URLs.
    ``payload`` carries event-specific context (comment body excerpt,
    proposal title, etc.) — kept as JSON so adding event types doesn't
    require a schema change.

    Rows expire after 90 days via the cleanup function in
    ``backend/notification_emit.cleanup_expired_notifications``.
    """
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    org_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("organizations.id"),
        nullable=True, index=True,
    )
    actor_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id"), nullable=True,
    )
    target_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    target_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, nullable=False, index=True,
    )

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])
    actor: Mapped[Optional["User"]] = relationship("User", foreign_keys=[actor_id])
    organization: Mapped[Optional["Organization"]] = relationship(
        "Organization", foreign_keys=[org_id],
    )


class NotificationPreference(Base):
    """Phase 13 — per-user-per-event-per-channel notification preference.

    Opt-in by default: absent rows are treated as ``enabled=False`` by
    ``emit_notification``. Stored explicitly only when a user has actively
    flipped a switch in the preferences UI (``PATCH /api/notifications/
    preferences``). The unique constraint enforces one row per
    (user, event_type, channel) triple.

    ``channel`` is one of ``"in_app" | "email"``; ``event_type`` is one of
    the keys from ``backend/notification_events.EVENT_REGISTRY``. Neither
    is checked at the DB layer (no enums) — the route layer and the
    EVENT_REGISTRY are the source of truth, matching the lightweight
    posture used elsewhere (proposal status, etc.).
    """
    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "event_type", "channel",
            name="uq_notif_pref_user_event_channel",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    channel: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False,
    )

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])


# ---------------------------------------------------------------------------
# Phase 44 — Multi-Admin Approval (ratification queue for destructive actions)
# ---------------------------------------------------------------------------

class PendingAdminAction(Base):
    """One submitted destructive admin action awaiting N-of-M ratification.

    Status transitions: ``pending`` → one of ``executed`` | ``declined``
    | ``expired`` | ``failed``. Resolution is terminal — no row is ever
    re-opened. Approvals live in the ``PendingActionApproval`` child
    table so the audit trail is queryable rather than a JSON blob.

    ``payload`` carries the action-type-specific data (e.g. target user
    id for ``member.remove``; proposed grants + baseline snapshot for
    ``role_permissions.edit``). The shape per type is enforced by the
    action registry's payload validator.
    """

    __tablename__ = "pending_admin_actions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=False, index=True,
    )
    action_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    initiator_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True,
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending",
        server_default="pending", index=True,
    )
    threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, nullable=False,
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    resolution_detail: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    organization: Mapped["Organization"] = relationship(
        "Organization", foreign_keys=[org_id],
    )
    initiator: Mapped["User"] = relationship("User", foreign_keys=[initiator_id])
    approvals: Mapped[list["PendingActionApproval"]] = relationship(
        "PendingActionApproval",
        back_populates="pending_action",
        cascade="all, delete-orphan",
    )


class PendingActionApproval(Base):
    """One approver decision (approve or decline) on a pending action.

    Unique on (pending_action_id, approver_id) so a single approver
    cannot weigh in twice. The initiator's submission is recorded here
    too (decision=approve, reason=null) per Phase 44 D4 — the
    submission IS the initiator's approval.
    """

    __tablename__ = "pending_action_approvals"
    __table_args__ = (
        UniqueConstraint(
            "pending_action_id",
            "approver_id",
            name="uq_pending_action_one_decision_per_approver",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    pending_action_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("pending_admin_actions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    approver_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True,
    )
    decision: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, nullable=False,
    )

    pending_action: Mapped["PendingAdminAction"] = relationship(
        "PendingAdminAction", back_populates="approvals",
    )
    approver: Mapped["User"] = relationship("User", foreign_keys=[approver_id])


# ---------------------------------------------------------------------------
# Phase 47 — Org titles / offices
# ---------------------------------------------------------------------------

class OrgTitle(Base):
    """Phase 47 — a labeled office/position within an org.

    A title carries a display name plus optional configuration:
      * ``bound_role`` — when set ('steward' | 'admin' | 'moderator' |
        'member'), holding the title grants the corresponding platform
        role via the existing 45a/45b role-assignment machinery. None
        = pure label, no permission effect.
      * ``cardinality_mode`` — 'single' (President, Treasurer; one
        holder) or 'multi' (Council Member; N holders).
      * ``max_holders`` — optional cap for multi-holder titles. NULL =
        uncapped.
      * ``fill_method`` — 'assigned' (direct grant — this pass),
        'elected' (Phase 48), 'both' (either). Stored now; the
        elected path is implemented in 48.
      * ``is_system`` — system-seeded titles (Steward, Admin) that are
        uneditable + undeletable. Per Phase 47 D6 these are a label
        layer over the existing role; the role remains the source of
        truth for permissions and the cardinality floor.
      * ``display_order`` — sort priority for display surfaces.

    Per D2 + D6: the role model + governance.py floor are unchanged.
    Titles are additive. A custom title binding steward is a
    convenience that goes through the existing transfer-stewardship +
    floor machinery — it does not bypass them.
    """
    __tablename__ = "org_titles"
    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_org_titles_org_name"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(length=80), nullable=False)
    bound_role: Mapped[Optional[str]] = mapped_column(
        String(length=16), nullable=True,
    )
    cardinality_mode: Mapped[str] = mapped_column(
        String(length=8), nullable=False, default="single",
        server_default="single",
    )
    max_holders: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fill_method: Mapped[str] = mapped_column(
        String(length=12), nullable=False, default="assigned",
        server_default="assigned",
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0",
    )
    display_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    # Phase 49 — fixed-term scheduled re-election (D1, D4, D6).
    # term_length_days NULL => no term => Phase 48 "elected-until-
    # challenged" behavior preserved. Setting it opts the title into
    # the `scheduled` trigger path; ``next_election_due_at`` tracks
    # when the next scheduled election should open (advanced on
    # resolution per D6). ``election_lead_time_days`` is how far
    # before ``next_election_due_at`` the tick opens the election so
    # the vote concludes around term-end (D4).
    term_length_days: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
    )
    election_lead_time_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=7, server_default="7",
    )
    next_election_due_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, nullable=False,
    )

    assignments: Mapped[list["OrgTitleAssignment"]] = relationship(
        "OrgTitleAssignment", back_populates="title",
        cascade="all, delete-orphan",
    )


class OrgTitleAssignment(Base):
    """Phase 47 — one (title, user) record meaning this user holds this
    title. Cardinality is enforced at the application layer (single
    vs. multi vs. max_holders); the DB invariant is one row per
    (title, user) so a user can't hold the same title twice.

    System titles (Steward, Admin) are NOT recorded here — they're
    derived at response-build time from the user's membership role.
    Per D6, the role is the source of truth; system titles are a
    label layer over it. Storing system-title assignments separately
    would create a sync problem with the role.
    """
    __tablename__ = "org_title_assignments"
    __table_args__ = (
        UniqueConstraint(
            "title_id", "user_id",
            name="uq_org_title_assignments_title_user",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    title_id: Mapped[str] = mapped_column(
        String, ForeignKey("org_titles.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True,
    )
    granted_by: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id"), nullable=True,
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, nullable=False,
    )

    title: Mapped["OrgTitle"] = relationship(
        "OrgTitle", back_populates="assignments",
    )


# ---------------------------------------------------------------------------
# Phase 48 Stage 1 — Elections (proposal subtype + candidacy)
# ---------------------------------------------------------------------------

class ElectionCandidacy(Base):
    """Phase 48 Stage 1 — one self-nomination on an election proposal.

    D5: candidacy is self-nomination only — no draft-nominating other
    people. The user_id is the candidate themselves; the row records
    their declaration during the nomination window. ``status='declared'``
    is the active state; ``status='withdrawn'`` allows the FE to show a
    history (we soft-delete by status rather than hard-delete to keep an
    audit-friendly trail), but the active-candidates query filters on
    ``status='declared'``.

    The ballot for the election (the candidate set used by the tally) is
    the set of users with ``status='declared'`` at voting-open time.
    Withdrawals after voting opens are out of scope for this stage.
    """
    __tablename__ = "election_candidacies"
    __table_args__ = (
        UniqueConstraint(
            "proposal_id", "user_id",
            name="uq_election_candidacies_proposal_user",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    proposal_id: Mapped[str] = mapped_column(
        String, ForeignKey("proposals.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True,
    )
    status: Mapped[str] = mapped_column(
        String(length=16), nullable=False, default="declared",
        server_default="declared",
    )
    declared_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, nullable=False,
    )
    withdrawn_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
    )


class OrgDuplicateFlag(Base):
    """Phase 52e Stage 2 E4 — org-scoped duplicate-identity flag.

    Created when a name-based hash match is detected between two
    members of the SAME org at a participation point (join, delegate
    promotion). Cross-org matches are deliberately NOT flagged —
    harm is org-scoped (one human with two accounts only distorts
    outcomes if both participate in the same org).

    Confidence tiers:
      * ``name_dob_address`` (high) → may default to block-pending-
        appeal (membership routes to ``pending_approval``).
      * ``name_dob`` (low) → route-to-review only; NEVER drives an
        automatic block (birthday-paradox math makes false
        collisions near-certain at scale).

    Status lifecycle:
      * ``open`` (default) — flag exists, no admin decision yet.
      * ``resolved_distinct`` — admin confirmed these ARE two real
        different people; suppresses re-flagging.
      * ``resolved_same`` — admin confirmed these ARE the same
        person; v1 records only (enforcement is manual / future).

    No PII stored on this row — only the user_ids. The admin
    adjudication surface shows WHICH members are flagged, not the
    matched name/DOB values (the admin already knows their members).
    """

    __tablename__ = "org_duplicate_flags"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # The pair of users implicated. Stored in lexical order (a < b)
    # so the unique constraint catches duplicates regardless of which
    # user triggered the match.
    user_a_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_b_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # "name_dob_address" (high) or "name_dob" (low).
    confidence: Mapped[str] = mapped_column(
        String(length=32), nullable=False,
    )
    # "open" / "resolved_distinct" / "resolved_same".
    status: Mapped[str] = mapped_column(
        String(length=32), nullable=False,
        default="open", server_default="open", index=True,
    )
    resolved_by_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
    )
    # Phase 52h Stage 1 H4 — durable demoted-side marker for
    # ``resolved_same`` flags. NULL until the admin's verdict is
    # ``resolved_same``; populated at that time with the newer-of-
    # pair's user_id. Read by ``is_org_verified`` so the predicate
    # stays False post-resolution (without this column, the
    # open-only check would re-verify the duplicate when the flag's
    # status moves away from ``open``).
    demoted_user_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "org_id", "user_a_id", "user_b_id", "confidence",
            name="uq_org_duplicate_flags_pair",
        ),
    )


class VerificationConsumption(Base):
    """Phase 52b — append-only log of real Didit verifications
    consumed against the shared monthly free pool.

    One row per real completion. ``year_month`` ("YYYY-MM") keys the
    monthly bucket — current-month total = ``COUNT(*) WHERE
    year_month = current``, no cron / no worker / implicit reset on
    the 1st. ``org_id`` is the triggering org (nullable — verifies
    initiated from Settings without an org context come back NULL);
    per-org rows give a future sub-allocation policy real data
    without enforcing one now. ``demo_stub`` / ``backdoor``
    provenance NEVER produces a row (Phase 51 forward-constraint;
    enforced in ``verification_metering.record_consumption``).
    """

    __tablename__ = "verification_consumption"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    year_month: Mapped[str] = mapped_column(
        String(length=7), nullable=False, index=True,
    )
    org_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    provider_session_id: Mapped[Optional[str]] = mapped_column(
        String(length=128), nullable=True,
    )
    # Always "didit" today; captured anyway so a future provider swap
    # makes per-provider attribution trivial.
    provenance: Mapped[str] = mapped_column(
        String(length=16), nullable=False,
        default="didit", server_default="didit",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, nullable=False,
    )


class VerificationSession(Base):
    """Phase 52a — bookkeeping for in-flight Didit verification
    sessions. One row per session, keyed by ``provider_session_id``
    so the webhook receiver can resolve session → user and dedupe
    replays by ``(provider_session_id, webhook_type_last)``.

    No raw PII / document images / selfies stored. The decision
    payload from Didit is consumed by ``verification_provider.
    map_decision_to_state`` and discarded; only the derived state
    + nullifier + attestation id land on the ``users`` row.
    """

    __tablename__ = "verification_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    provider_session_id: Mapped[str] = mapped_column(
        String(length=128), nullable=False, unique=True,
    )
    status: Mapped[str] = mapped_column(
        String(length=32), nullable=False,
        default="initiated", server_default="initiated",
    )
    webhook_type_last: Mapped[Optional[str]] = mapped_column(
        String(length=64), nullable=True,
    )
    # Phase 52b — the triggering org id (if any) the user came from
    # when starting this verification. Threaded through to the
    # ``verification_consumption`` row at webhook approval so per-org
    # consumption can be recorded. NULL when verification was
    # initiated from Settings without an org context.
    triggering_org_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False,
    )


# ===========================================================================
# Phase 77 — Org-scoped direct messaging
# ===========================================================================

class Conversation(Base):
    """Phase 77 — a 1:1 (or org-inbox) message thread, scoped to one org.

    ``conversation_type`` differentiates the three surfaces (D1):
      * ``direct``    — member-to-member DM (gated by member_dm_policy).
      * ``delegate``  — a member contacting a delegate (gated by the
                        delegate's profile visibility).
      * ``org_inbox`` — a member contacting org leadership; ``recipient_id``
                        is NULL and any ``org_inbox.view`` holder can read/reply.

    Creation gates control who can START a conversation; once it exists both
    participants can always send (D5) unless a MessageBlock intervenes.
    """
    __tablename__ = "conversations"
    __table_args__ = (
        # Dedup guard for direct/delegate (recipient_id non-null). org_inbox
        # rows have recipient_id NULL — NULLs are distinct under PG/SQLite, so
        # this does not enforce one-inbox-per-initiator; that's handled at the
        # application layer (access-control matrix §org_inbox dedup).
        UniqueConstraint(
            "org_id", "conversation_type", "initiator_id", "recipient_id",
            name="uq_conversation_participants",
        ),
        Index("ix_conversations_org_recipient_status", "org_id", "recipient_id", "status"),
        Index("ix_conversations_org_initiator_status", "org_id", "initiator_id", "status"),
        Index("ix_conversations_org_type", "org_id", "conversation_type"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=False, index=True,
    )
    conversation_type: Mapped[str] = mapped_column(String, nullable=False)
    initiator_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False,
    )
    recipient_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id"), nullable=True,
    )
    context_proposal_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("proposals.id"), nullable=True,
    )
    subject: Mapped[Optional[str]] = mapped_column(String(length=200), nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="active", server_default="active",
    )
    # Denormalized sort key for conversation lists; updated on each new message.
    last_message_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, nullable=False,
    )


class Message(Base):
    """Phase 77 — a single message in a conversation. Append-only (D12):
    no edit, no delete. Body sanitized via the comment nh3 pipeline."""
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversations.id"), nullable=False, index=True,
    )
    sender_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # System messages ("Conversation closed by {name}.") render distinctly.
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, nullable=False,
    )


class ConversationRead(Base):
    """Phase 77 — per-user read marker for a conversation. Unread count =
    messages with ``created_at > last_read_at`` and ``sender_id != user_id``.
    """
    __tablename__ = "conversation_reads"

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), primary_key=True,
    )
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversations.id"), primary_key=True,
    )
    last_read_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class MessageBlock(Base):
    """Phase 77 — org-scoped block (D7). Blocking someone in one org does not
    affect another. Blocks are silent: the blocked user gets a generic
    'unable to send' error, never 'you are blocked'."""
    __tablename__ = "message_blocks"
    __table_args__ = (
        UniqueConstraint(
            "blocker_id", "blocked_id", "org_id",
            name="uq_message_block_pair_org",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    blocker_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True,
    )
    blocked_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True,
    )
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=False, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, nullable=False,
    )
