# Phase 12 Stage 1 — Role-Check Audit

Drafted: 2026-05-02
Phase: 12 Stage 1 (Cluster R, R1)
Auditor: Backend dev #3 (R agent)
Branch: `phase-12/role-permissions-stage-1`

## Scope and method

Greps run against `backend/` (tests excluded; only application code):

- `role in (` and `role not in (`
- `role == "..."` (single + double quote)
- `_ADMIN_ROLES`, `_SUB_ORG_PROPOSAL_CREATOR_ROLES`
- `.role ==`
- `models.OrgMembership.role.in_(...)` — SQL-level checks

Per-site classifications:

- **MAPS_TO_KEY** — direct rewrite via
  `has_permission(db, user_id, org_id, "<key>")`. Error-message phrasing
  also gets the role-name-agnostic upgrade per spec.
- **OWNER_ONLY_D4** — call `has_permission(... "org.delete")` or
  `"org.transfer_stewardship"` (helper enforces `system_key=='steward'`
  internally per the D4 hardcoded path).
- **DECISION_6_IMPLICIT_D3** — covered already by `has_permission`'s
  top-rule (parent-org admin/steward → all sub-org permissions).
- **SUB_ORG_STRING_PRESERVED** — `SubOrgMembership.role` stays string
  per Cluster D2; check is on the direct-sub-org side and is correct
  as-is (the D2 "stays string" rule).
- **SERIALIZATION** — site reads `m.role` to embed in an API response
  payload. Now that `role` is a relationship to `Role`, must read
  `m.role.name` (display) or `m.role.system_key` (stable key) and the
  schema may need a small adjustment.
- **DOESNT_MAP_FLAG** — surface for spec clarification.

Sub-org direct-membership role checks (`SubOrgMembership.role`)
intentionally retain string semantics (Decision D2). They are listed
under SUB_ORG_STRING_PRESERVED for traceability but do NOT need code
changes.

---

## R1 audit results

### Module: `backend/permissions.py`

#### `_ADMIN_ROLES` constant + `is_sub_org_admin` (lines 128, 132-179)

- **Status:** mixed (**SUB_ORG_STRING_PRESERVED** for the direct branch,
  **DECISION_6_IMPLICIT_D3** for the parent-org branch)
- **Details:**
  - Line 167 (`sub_membership.role in _ADMIN_ROLES`) — direct
    SubOrgMembership check; STAYS as string per D2. Keep.
  - Line 176 (`parent_membership.role in _ADMIN_ROLES`) — parent-org
    OrgMembership implicit-admin. **R3:** rewrite via Role lookup
    (`role.system_key in ('admin', 'steward')`) so behavior matches the
    rename. Functionally equivalent to invoking `has_permission` with
    any sub-org permission (the Decision-6 rule auto-grants), but a
    role-lookup keeps this helper synchronous + free of cache effects.

#### `_SUB_ORG_PROPOSAL_CREATOR_ROLES` + `can_create_proposal_in_sub_org` (lines 129, 217)

- **Status:** **SUB_ORG_STRING_PRESERVED**
- **Details:** Sub-org-direct check on `SubOrgMembership.role`. Stays as
  string per D2.

#### `is_polis_admin` line 270 (`membership.role in ("moderator", "admin", "owner")`)

- **Status:** **MAPS_TO_KEY** (`polis.create`)
- **Details:** This decides whether an org-wide caller can admin a Polis.
  The legacy "moderator+ tier matches topic creation" semantics map
  cleanly to `polis.create` in the registry. **R2:** rewrite via
  `has_permission(db, user_id, polis.org_id, "polis.create")`.

---

### Module: `backend/org_middleware.py`

#### `require_org_moderator_or_admin` (line 43)

- **Status:** **MAPS_TO_KEY** — but the gate guards heterogeneous
  endpoints (suspend member, approve join, advance proposal, etc.). The
  honest fix is to retire this Depends() and inline the appropriate
  per-endpoint `has_permission` call at each call site, but that risks a
  larger ripple than R targets. **PRAGMATIC R2:** keep the dependency
  shape as a coarse "moderator-or-better" membership check, but
  re-implement against `Role.system_key` (admin/moderator/steward)
  rather than the dropped string column. This preserves the contract
  for routes that still depend on it; the spec-mandated MAPS_TO_KEY
  rewrites happen at the truly-action-specific call sites
  (`organizations.py` line 1339 etc.), where the helper still provides
  membership/active-status enforcement.

#### `require_org_admin` (line 52)

- **Status:** **MAPS_TO_KEY** — same shape. Pragmatic R2: keep as a
  membership-and-role-tier check via `Role.system_key in
  ('admin', 'steward')`.

#### `require_org_owner` (line 61)

- **Status:** **OWNER_ONLY_D4** — guards `DELETE /api/orgs/{slug}`.
  Pragmatic R2: keep dependency shape, re-implement against
  `Role.system_key == 'steward'`. (The has_permission helper would
  reach the same answer for `org.delete` / `org.transfer_stewardship`
  but the dependency itself is loaded before we know which permission
  key applies.)

---

### Module: `backend/routes/organizations.py`

#### Line 86 — `_org_to_out` user_role serialization

- **Status:** **SERIALIZATION**
- **Details:** Reads `membership.role` to populate `user_role` in the
  response payload. Post-migration, `membership.role` is a `Role` ORM
  object (or None). **R2:** read `membership.role.system_key` (matches
  Stage 2 frontend expectations and is the spec-canonical wire form).

#### Line 427 — `list_members` endpoint serialization

- **Status:** **SERIALIZATION**
- **Details:** Same fix — emit `m.role.system_key` not `m.role`.

#### Line 453 — `change_member_role` `if m.role == "owner"`

- **Status:** **SERIALIZATION + OWNER_ONLY_D4**
- **Details:** Block "Cannot change owner role". Post-rename: block
  changes to a Steward. Rewrite via `m.role and m.role.system_key ==
  'steward'`. Schema validator (`MemberRoleUpdate`) also needs to accept
  the new role values.

#### Line 455 — `m.role = body.role` mutation

- **Status:** **SERIALIZATION**
- **Details:** Now must resolve `body.role` (a system_key string) to a
  Role row and set `m.role_id`. Default-grants are already seeded for
  every org; lookup by `(org_id, system_key)`.

#### Line 465 — response payload

- **Status:** **SERIALIZATION** (same as 427).

#### Line 489 — `if m.role == "owner"` (remove member)

- **Status:** **OWNER_ONLY_D4** (defensive — Steward cannot be removed).
  Same fix as 453.

#### Line 513 — `if m.role == "owner"` (suspend member)

- **Status:** **OWNER_ONLY_D4** (Steward cannot be suspended). Same
  fix.

#### Line 579, 590, 833 — `OrgMembership(..., role="member")` / `inv.role`

- **Status:** **PRODUCTION_INSERT** (D's flag)
- **Details:** Construction sites for new memberships. Must convert
  `role="member"` → `role_id=<member-role-id>`. Need the org's preset
  role rows seeded (already true for orgs created post-migration; the
  migration backfills existing orgs).

#### Line 1073 — `is_parent_admin = membership.role in ("admin", "owner")` (list_org_topics)

- **Status:** **MAPS_TO_KEY** (`topic.create` is the closest semantic;
  but this is actually a *visibility* check — admins see all sub-org
  topics. Spec-honest: the right gate is "admin tier", which we model
  via `Role.system_key in ('admin', 'steward')`). **R2:** rewrite via a
  small local helper `_is_parent_org_admin_role(membership)` that
  inspects the resolved Role row.

#### Line 1114 — `if membership.role not in ("admin", "owner")` (create_org_topic)

- **Status:** **MAPS_TO_KEY** (`topic.create`)
- **Details:** Direct rewrite to
  `has_permission(db, current_user.id, org.id, "topic.create")`. Error
  copy: "You do not have permission to create topics in this
  organization."

#### Line 1242 — `is_parent_admin = membership.role in ("admin", "owner")` (list_org_proposals)

- **Status:** **MAPS_TO_KEY** (visibility gate). Same shape as 1073.
  Use the role-tier helper.

#### Line 1339 — `if membership.role not in ("moderator", "admin", "owner")` (parent-scope create_org_proposal)

- **Status:** **MAPS_TO_KEY** (`proposal.create`)
- **Details:** Direct rewrite. Error copy: "You do not have permission
  to create proposals in this organization."

#### Line 1525 — `if membership.role == "moderator"` (advance_org_proposal)

- **Status:** **DOESNT_MAP_FLAG** (intentional, see below)
- **Details:** This is the "moderators may only advance their own
  proposals" rule — distinguishes moderator from admin behavior. It is
  not a permission gate per se but a tier-based scope restriction. The
  permission to *advance* is granted by `proposal.advance_phase`; the
  *whose-proposals* restriction is a separate semantic. **R2:** keep
  the tier check but re-implement via `Role.system_key ==
  'moderator'`. The new permission registry intentionally doesn't
  carry "moderator-only restricted to own proposals" because Stage 1
  preserves existing behavior; Stage 2 may revisit. Flagged for spec
  awareness; no behavior change.

---

### Module: `backend/routes/proposals.py`

#### Line 578 — `if membership.role in ("admin", "owner")` (advance_proposal flat endpoint)

- **Status:** **MAPS_TO_KEY** (`proposal.advance_phase`)
- **Details:** Same advance endpoint as `organizations.py:1503` but
  reachable via the legacy flat path. **R2:** rewrite via
  `has_permission(... "proposal.advance_phase")`. Preserve the "author
  may always advance own proposal" branch and the platform-admin
  branch — both orthogonal to the permission system.

#### Line 580 — `elif membership.role == "moderator"` (own-proposals-only)

- **Status:** **DOESNT_MAP_FLAG** (same rationale as `organizations.py:1525`)

---

### Module: `backend/routes/sub_organizations.py`

#### Line 91 — `_is_parent_org_admin` helper (`m.role in ("admin", "owner")`)

- **Status:** **MAPS_TO_KEY** (admin-tier role check)
- **Details:** Rewrite via Role lookup (`role.system_key in
  ('admin', 'steward')`). Used by `delete_sub_org` permission check;
  Decision-6 implicit-power gate.

#### Line 265, 309, 516 — `is_parent_admin = membership.role in ("admin", "owner")` (visibility filters)

- **Status:** **MAPS_TO_KEY** (admin-tier role check)
- **Details:** Same fix; pragmatic helper.

#### Line 455, 890, 942 — `sm.role == "owner"` (sub-org-direct owner protection)

- **Status:** **SUB_ORG_STRING_PRESERVED**
- **Details:** Operates on `SubOrgMembership.role` (still string per
  D2). Keep.

#### Lines 226, 590, 675, 732 — `SubOrgMembership(..., role=...)` constructions

- **Status:** **SUB_ORG_STRING_PRESERVED**. Keep.

---

### Module: `backend/routes/proposals.py` line 578 — covered above.

### Module: `backend/routes/comments.py`

#### Line 74 + 131 — `_ADMIN_ROLES` + `models.OrgMembership.role.in_(_ADMIN_ROLES)` (eligible viewers query)

- **Status:** **MAPS_TO_KEY**, but **SQL-bulk** flavor.
- **Details:** This SELECTs the user_id set of parent-org admins for
  visibility-set computation. Calling `has_permission` per row is
  N+1-disastrous. **R2 pragmatic:** join through Role table:
  `models.OrgMembership.role_id == models.Role.id` AND
  `models.Role.system_key.in_(('admin', 'steward'))`. Equivalent set,
  same query count.

---

### Module: `backend/routes/topics.py`

#### Line 51 — `models.OrgMembership.role.in_(("admin", "owner"))` (parent-admin org id resolution)

- **Status:** **MAPS_TO_KEY**, **SQL-bulk** flavor.
- **Details:** Same fix shape as comments.py line 131.

---

### Module: `backend/routes/polises.py`

#### Line 95 — `_is_org_moderator_plus` returns `membership.role in ("moderator", "admin", "owner")`

- **Status:** **MAPS_TO_KEY** (`polis.create` gate)
- **Details:** Used inline by polis routes. **R2:** rewrite via
  `has_permission(db, user_id, org_id, "polis.create")` at call sites
  (the helper itself can be retired or kept as a wrapper).

---

### Module: `backend/polis_engine.py`

#### Line 19, 72, 116, 123, 131 — bulk SQL `.role.in_(...)` in eligible-viewer / eligible-admin computations

- **Status:** **SQL-bulk** (mix of MAPS_TO_KEY and
  SUB_ORG_STRING_PRESERVED)
- **Details:**
  - Line 72 — parent-org admins for sub-org Polis visibility.
    OrgMembership join → Role check (`system_key in
    ('admin', 'steward')`).
  - Line 116 — sub-org admins. SubOrgMembership; STAYS as string per
    D2.
  - Line 123 — parent-org admins. OrgMembership; rewrite via Role join.
  - Line 131 — parent-org moderator+. OrgMembership; rewrite via Role
    join with `system_key in ('admin', 'steward', 'moderator')`.

---

### Module: `backend/routes/auth.py`

#### Line 74-79 — auto-join demo org `OrgMembership(..., role="member", ...)`

- **Status:** **PRODUCTION_INSERT** (D's flag)
- **Details:** Lookup the demo org's `member` role row, set `role_id`.

#### Line 137 — `_consume_invitation` `OrgMembership(..., role=inv.role, ...)`

- **Status:** **PRODUCTION_INSERT**
- **Details:** `inv.role` is a string ('member' / 'admin') from the
  Invitation table (which keeps a string column per spec — invitations
  are pre-membership artifacts, not coupled to the per-org role rows).
  Resolve to the org's matching Role row, set `role_id`.

#### Line 135 — `existing.role = inv.role` (idempotent reactivation)

- **Status:** **PRODUCTION_INSERT** (mutation flavor)
- **Details:** Same fix — set `existing.role_id` from a Role lookup.

#### `routes/organizations.py` line 828 — `existing.role = inv.role` (accept_invitation flat path)

- **Status:** **PRODUCTION_INSERT** (mutation flavor)
- **Details:** Same fix.

---

### Module: `backend/seed_data.py`

#### Line 362 — `_add_org_membership` `OrgMembership(..., role=role, ...)`

- **Status:** **PRODUCTION_INSERT** (development-seed only — not hit
  by Railway prod, but used by `python seed_data.py` for QA / local).
- **Details:** Lookup org's role row by system_key; set `role_id`.
  Seed the org's preset roles first if they don't exist (the production
  migration handles this for prod, but local-dev use should be
  defensive).

#### Lines 1231-1234 — SubOrgMembership inserts

- **Status:** **SUB_ORG_STRING_PRESERVED**. Keep (already confirmed by D).

---

## Summary counts

| Classification               | Count |
|------------------------------|-------|
| MAPS_TO_KEY                  | 11    |
| OWNER_ONLY_D4                | 4     |
| DECISION_6_IMPLICIT_D3       | 1     |
| SUB_ORG_STRING_PRESERVED     | 7     |
| SERIALIZATION                | 5     |
| PRODUCTION_INSERT            | 7     |
| SQL-bulk (subset of above)   | 5     |
| DOESNT_MAP_FLAG              | 2     |

DOESNT_MAP_FLAG items (both intentional, no behavior change):

1. `routes/organizations.py:1525` and `routes/proposals.py:580` — the
   "moderators can only advance proposals they created" tier-scoped
   restriction. Stage 1 preserves; revisit in Stage 2 if/when a
   "manage_others_proposals" permission is added.
