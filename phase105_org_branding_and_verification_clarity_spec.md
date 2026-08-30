# Phase 105 — Organization Branding and Verification Clarity

**Status:** DEPLOYED / HTTP VERIFIED / RENDERED CHROME QA AND PRIVATE INVENTORY BLOCKED

**Written:** 2026-08-30, after Phase 104 production deployment and Z's review of the California organization settings

**Branch:** `phase-105/org-branding-verification-clarity` from `origin/master` at or after Phase 104 final hotfix merge `c138c99`

**Priority:** Product-coherence and pilot-usability pass. This is not a verification-provider integration change.

## Goal

Make organization branding work on light/gold primary colors, make every administrator-facing verification choice say what the platform actually enforces, and finish the per-organization display-name path so a legal-name rule can apply specifically to public delegates without forcing one account-wide name across unrelated organizations.

Phase 105 has four connected outcomes:

1. Organization branding gains an arbitrary header-text color with white/black presets and a non-blocking contrast warning.
2. Administrator-facing verification requirements collapse to three meaningful choices: none, identity verified, or verified resident of the organization's one shared residency scope. The address-only backend rung remains compatible but is not newly selectable.
3. Proposal verification becomes one coherent policy selector and uses the same shared residency scope instead of a second jurisdiction field.
4. Account Settings exposes the shipped `OrgMembership.display_name` override, and organization settings can apply legal-name matching to public delegates specifically.

This pass does not change Didit vendors, collect new identity data, expose legal names, renumber the verification-state ladder, or invent an organization-specific user account.

## Source-grounded findings

These are confirmed against deployed `origin/master` after Phase 104, not inferred from UI copy.

### Branding

- `Organization.settings.branding` currently stores `logo_url`, `primary_color`, `accent_color`, and `accent_auto_derived`.
- `BrandingThemeApplier.jsx` sets primary/accent CSS variables only.
- `Nav.jsx` hardcodes active/header text to white and inactive/tertiary text to Tailwind blue-200/blue-300. A gold primary therefore receives blue-tinted text regardless of the organization's palette.
- `_org_to_out` already centralizes internal branding serialization and one-level sub-organization inheritance. Public org and Explore serializers have a smaller `OrgPublicBrandingOut` shape.

### Verification requirements

- The membership and role dropdowns label `address_on_id` as “Verified resident,” but residency-scope enforcement is a separate checkbox. With the checkbox off, the user only needs a verified ID address anywhere.
- There is no strong Liquid Democracy product reason to offer “an ID has an address, but the organization neither checks nor uses where it is.” The rung is useful internally because Didit verification progresses through it and old stored policy may reference it; that does not justify a new administrator-facing choice.
- `verification_residency_scope` is already the canonical organization-level list of allowed countries/states/cities. Membership and role gates have separate booleans that reference it.
- The proposal-wide `always` policy still stores `verification_proposal_jurisdiction` and Phase 102b requires a U.S. jurisdiction for address/residency floors. It does not use the shared residency-scope predicate promised by Phase 52j.
- The first proposal selector answers who controls the policy (`never` / `author` / `always`), while the second answers which floor applies. The current labels do not make that distinction clear and previously permitted contradictory “always require” / no-floor states.
- The backend verification ladder still contains `identity_unique`, `address_on_id`, and `residency_verified`. Phase 105 must not remove or reorder them.

### Display names and public delegates

- `OrgMembership.display_name` already stores a per-parent-organization override. `verification.display_name_for(user, org, membership=...)` resolves override then account default.
- `PATCH /api/orgs/{slug}/me/display-name` already writes the override and applies the old all-verified-member legal-name policy.
- No production frontend calls that endpoint. Account Settings only calls `PATCH /api/auth/me`, so users can edit only the global account name in the UI.
- `PATCH /api/auth/me` does not consult organization policies. If an organization-scoped surface falls back to the account name, a global edit can bypass the organization rule.
- The current name-match endpoint does not validate clearing an override, even though clearing can reveal a non-matching global fallback.
- `verification_required_for_public_delegate` delegates to `is_org_verified`. When the membership floor is absent/email-only, `is_org_verified` treats the floor as satisfied; the checkbox can therefore say “Require verification” while requiring no identity verification. The derived predicate also does not incorporate the separate membership-residency boolean.
- Public-facing delegate identity includes profiles in either `public` or `public_accepting` visibility. The current promotion verification gate covers only the transition to `public_accepting`.

## Read order

1. This file, fully.
2. `AGENTS.md`.
3. Latest `PROGRESS.md`, especially Phases 12.7, 14, 19, 30.1, 52f, 52j, 76c, 94, 95, 102a, 102b, 103, and 104.
4. `phase12_7_org_branding_and_copy_polish_spec.md`, `phase52f_display_name_match_spec.md`, `phase52j_verification_coherence_spec.md`, `phase76d_residency_full_granularity_spec.md`, and `phase102b_didit_terminal_decision_and_verification_remediation_spec.md`.
5. `backend/verification.py`, `backend/verification_flags.py`, `backend/eligibility.py`, `backend/models.py`, and relevant schemas.
6. `backend/routes/organizations.py`, `backend/routes/auth.py`, `backend/routes/delegate_profiles.py`, `backend/routes/delegates.py`, and proposal create/update/vote routes.
7. `frontend/src/pages/admin/OrgSettings.jsx`, `frontend/src/pages/Settings.jsx`, `frontend/src/pages/DelegateProfile.jsx`, proposal create/edit surfaces, `frontend/src/verificationLabels.js`, `BrandingThemeApplier.jsx`, `Nav.jsx`, `NotificationBadge.jsx`, and `index.css`.
8. Existing branding, Phase 52, Phase 102a, and Phase 102b tests before adding new tests.

## Workspace, branch, and delivery discipline

The planning checkout is dirty and its local `master` is behind `origin/master`. Its staged, unstaged, and untracked files belong to Z.

1. Do not stash, reset, clean, overwrite, or normalize the planning checkout.
2. Create a clean linked worktree from `origin/master` containing Phase 104 final merge `c138c99` or a later Z-approved master.
3. Create `phase-105/org-branding-verification-clarity` in that worktree.
4. Implement and verify all clusters there.
5. Merge to `master` with `--no-ff`, push, verify both Railway deployments, and run production QA per `AGENTS.md`.
6. Do not mutate the California/Massachusetts organization's verification policy for QA, create a real-person Didit session, or consume paid verification capacity. Use local fixtures and a disposable/demo production organization only where a rendered proof requires it.

## Verification matrix

| Check | Required | Notes |
|---|---:|---|
| Read-only production settings inventory | Yes | Count orgs using every affected legacy key combination and count public/public-accepting delegate profiles; report only aggregate/sanitized results. |
| Header-text branding contract | Yes | PATCH round-trip, null reset, invalid hex, internal/public response shape, sub-org inheritance, audit diff. |
| Header desktop/mobile rendering | Yes | Brand name, org switcher, nav links, admin/account controls, bell/icons, mobile links, hover/active/focus states; dropdown panels retain normal dark-on-white text. |
| Contrast warning | Yes | Correct ratio/result for black, white, and a custom low-contrast color; warning does not block save. |
| Three-choice requirement mapping | Yes | None / identity / resident map atomically to the correct stored floor + residency boolean for membership, roles, proposal policy, and author-created proposals. |
| Residency-scope invariant | Yes | Resident cannot be newly saved with an empty/invalid shared scope; OR matching and country/state/city behavior remain correct. |
| Legacy address-only compatibility | Yes | Existing address-only/stale ladder values still enforce and render an honest non-selectable legacy state; no new UI can select them. |
| Proposal-policy selector | Yes | Never / author chooses / identity for every proposal / resident for every proposal; no “always + none” state. |
| Proposal resolver agreement | Yes | Create/update/serializer/import/seed and vote enforcement agree on the new residency flag; legacy jurisdiction proposals retain old behavior. |
| Migration cycle | Yes | Upgrade → downgrade → upgrade on SQLite for the Proposal residency field; exact old rows survive. |
| PostgreSQL smoke | Yes | Prior revision `e7f8a9b0c1d2`; run fresh and upgrade modes per `AGENTS.md`. |
| Per-org display-name API | Yes | OrgOut effective/override fields, set/reset, length/blank handling, parent-org scope, no cross-org write, audit behavior. |
| Account Settings display-name UX | Yes | Default-name edit, org selector, per-org override, reset-to-default, loading/error/race handling, current-org deep link, keyboard/mobile. |
| Global-name bypass prevention | Yes | Applicable org without override blocks/flags a nonmatching global edit; org with explicit override is unaffected; clearing override validates fallback. |
| Public-delegate name rule | Yes | Both public and public-accepting transitions, new promotion, later org/global name changes, and existing-delegate activation preflight. |
| Public-delegate identity floor | Yes | Verification checkbox always means at least identity; stronger membership/residency rules compose; duplicate flags still block. |
| Privacy | Yes | No API/error/audit/browser surface returns legal name, address, DOB, hashes, or provider payload. |
| Additive-layer parity | Yes | Organizations with no affected settings and users with no overrides behave unchanged. |
| Full backend suite | Yes | Baseline is Phase 104's 3,140 passed / 20 environment skips; report exact delta. |
| Full frontend tests + build | Yes | Baseline is Phase 104's 69/69; changed-file lint, production build, bundle artifacts, and existing chunk warning. |
| Production deploy + HTTP smoke | Yes | Exact deploy IDs/SHA, bundle hash, health/readiness/monitor, branding response, authenticated own-name shape; no real identity mutation. |
| Rendered production QA | Yes | Chrome MCP per `AGENTS.md`; if the trusted-path blocker persists, report BLOCKED and do not claim rendered PASS. |

## Suggested team structure

- **Lead:** clean-worktree setup, preflight inventory, contract review, cross-cluster integration, migration/PG proof, deploy, and closeout. No direct implementation in the default four-role structure.
- **Backend dev:** settings normalization/validation, effective requirement resolver, Proposal migration, display-name enforcement, delegate gates, schemas, and pytest coverage.
- **Frontend dev:** branding control/theme/nav sweep, coherent verification controls, Account Settings name editor, proposal-form changes, and frontend tests/build.
- **QA teammate:** post-deploy branding, settings, per-org name, and public-delegate scenarios via the required Chrome MCP without creating a paid verification session.

## Sequence

1. Record Phase 104 baseline and run the read-only affected-settings/public-delegate inventory.
2. Implement header-text color end to end and verify nav coverage before touching verification logic.
3. Introduce one canonical visible-requirement mapper and replace membership/role controls.
4. Add the Proposal residency field and central effective-requirement resolver; migrate org policy and author proposal UI.
5. Surface per-org display names in Account Settings and close global/reset bypasses.
6. Add public-delegate-specific legal-name scope and repair the delegate verification floor.
7. Run focused tests, migration cycle, PG smoke, full suites, lint/build, and privacy/source audits.
8. Merge/push/deploy, verify production, run rendered QA if Chrome is available, and update `PROGRESS.md`.

## Locked decisions

### 1. Header text color is an explicit optional branding value

Add nullable `settings.branding.header_text_color`.

- Accept `#RGB` and `#RRGGBB` through the existing shared hex validator.
- `null` / absent means exact legacy header behavior: active white, inactive blue-200, tertiary blue-300. Do not silently change every existing organization's header.
- A configured color applies to header text/icons only. It does not change white text on primary-colored buttons, invitation emails, result charts, badges, or arbitrary body components.
- Branding Reset clears it with the other color overrides.
- The branding audit event includes before/after for this key without adding a new action type.

Thread the field through:

- `BrandingOut` and `BrandingUpdate`;
- `OrgPublicBrandingOut` because the public org route can theme the global header;
- `_org_to_out`, public org, Explore/demo card serializers that reuse branding, logo/color mutation responses, and sub-org inheritance;
- branding response-shape tests and any explicit expected dicts.

Invitation/digest email theming continues to use primary color only.

### 2. Branding UI offers white, black, and arbitrary custom color

Org Settings adds **Header text color** alongside primary/accent controls:

- White preset (`#FFFFFF`)
- Black preset (`#000000`)
- Custom color picker + synchronized hex input
- Reset to platform default (`null`)

Show a live header preview using the selected primary + text colors. Compute the WCAG contrast ratio against the primary background and show pass/warning copy for normal text. A low contrast ratio is advisory only: do not disable Save or reject the backend write. The user explicitly retains arbitrary color choice.

The control remains under `org.edit_branding` and participates in the existing save/loading/error behavior.

### 3. One header color drives deliberate text hierarchy

When configured, derive three CSS variables from the exact selected color:

- `--brand-header-text` — 100% color for active/hover/brand text;
- `--brand-header-text-muted` — the same RGB at approximately 78% opacity for inactive links;
- `--brand-header-text-subtle` — the same RGB at approximately 62% opacity for tertiary/mobile footer copy.

Use a small tested color utility; do not hand-build unvalidated CSS strings. `BrandingThemeApplier` sets and removes all three variables with primary/accent variables.

Audit every element rendered on the colored nav background, including desktop and mobile `Nav`, `OrgSwitcher`, `NotificationBadge`, user/admin triggers, icons, Privacy/Terms links, and current/inactive states. White dropdown/popover panels keep their existing gray/black text and must not inherit the header variable accidentally. Preserve visible focus indicators on both light and dark primary colors.

### 4. User-facing verification requirements have only three choices

For membership, each role, proposal policy, and author-chosen proposal gates, expose only:

1. **No verification required**
2. **Identity verified**
3. **Verified resident of the allowed locations**

Do not expose “identity and address verified,” `address_on_id`, `identity_unique`, `residency_verified`, rank numbers, or backend state codes as selectable administrator vocabulary.

The shared UI/domain mapper is:

| Visible choice | Base floor | Require shared residency scope |
|---|---|---:|
| none | unset / email-only sentinel | false |
| identity | `identity` | false |
| resident | `address_on_id` | true |

`address_on_id` remains the minimum technical evidence needed to compare an ID address against the org scope. `residency_verified` and higher stale states still satisfy by rank. Do not renumber or remove any state in `ORDER` / `VALID_STATES`.

Centralize this mapping in one backend helper and one frontend utility rather than reproducing conditionals across Org Settings and proposal forms.

### 5. “Verified resident” always means scope match

Remove the membership and role “Also require residency” checkboxes. Selecting resident atomically writes both the base floor and the gate's residency boolean. Selecting identity/none atomically clears the gate's residency boolean.

The residency editor remains one organization-wide list. Rename its heading to **Allowed residency locations** and explain that every resident requirement below/above references this same list.

New/changed resident settings cannot be saved unless the normalized scope contains at least one valid matchable entry:

- non-US country entry: valid supported country code;
- US country-wide entry: `US` without state is allowed if current Phase 76 semantics support it;
- U.S. state entry: valid two-letter state/DC code;
- city entry: nonblank city plus valid state;
- malformed/empty rows do not count.

If the scope is being removed while any non-legacy membership/role/proposal gate requires resident, reject the settings write atomically with field-addressable dependency errors. Do not silently turn those gates into address-only checks.

### 6. Legacy address-only and stale ladder settings stay enforceable but are not selectable

No data migration guesses what an administrator intended from an old combination.

- Existing membership/role/proposal settings that require `address_on_id` or `residency_verified` without the new/appropriate residency flag continue through the legacy resolver exactly as before.
- When such a value is loaded, the relevant control displays an honest disabled placeholder such as **Legacy: verified ID address requirement** plus copy: changing this setting requires choosing identity or verified resident.
- Saving an unrelated setting preserves the legacy value.
- Once the administrator chooses one of the supported choices and saves, the legacy combination is replaced atomically and cannot be reselected.
- Tests cover legacy jurisdiction, address-only, dead-rung, partial-settings PATCH, and sub-org inheritance cases.

### 7. Proposal policy becomes one coherent selector

Replace the two org-level selectors with one **Who must verify to vote on proposals?** selector:

- **No proposal-level verification** → policy `never`
- **Proposal author chooses** → policy `author`
- **Identity verified for every proposal** → policy `always`, floor `identity`, no residency
- **Verified resident for every proposal** → policy `always`, floor `address_on_id`, shared-residency true

There is no “always require verification” option followed by “no verification required.” Fresh-org default remains `never`; missing legacy policy still resolves to `author` for old-org parity.

Add `verification_proposal_require_residency` to organization settings. New resident policy clears `verification_proposal_jurisdiction`; that old key is deprecated/read-only compatibility data and is not shown in the new UI.

Refactor Phase 102b's `validate_org_proposal_settings` into the canonical merged-settings validator for these new invariants. It must continue rejecting malformed direct API writes, return field-addressable errors, preserve valid partial PATCH behavior, and tolerate untouched legacy states per Decision 6.

### 8. Author-chosen proposal residency uses the same org scope

Add nullable boolean `Proposal.verification_require_residency` through a reversible Alembic migration from prior head `e7f8a9b0c1d2`.

Semantics:

- `True`: base floor must require an address and vote enforcement also calls `user_satisfies_residency_scope(user, org)`.
- `False`: no residency-scope check.
- `NULL`: legacy proposal. Continue interpreting its existing `verification_floor` + `verification_jurisdiction` exactly as before.

New UI/API writes may create only none, identity, or resident. They never create a new address-only proposal. Resident writes `address_on_id`, `verification_require_residency=True`, and `verification_jurisdiction=None`.

Replace the `(floor, jurisdiction)` tuple with one small typed effective-requirement object used by vote enforcement, eligibility helpers, response copy, and proposal-form policy resolution. The object must distinguish new shared-scope residency from legacy jurisdiction enforcement.

Wire the new field through:

- `ProposalCreate`, `ProposalUpdate`, `ProposalOut`;
- both global and organization-scoped create paths;
- explicit `_build_proposal_out` construction;
- edit/update and import preview/template paths;
- seed/demo paths that write Proposal directly;
- author-policy frontend create/edit controls;
- structured verification-required payload/copy.

Follow the `AGENTS.md` schema-round-trip convention: both create endpoints, serializer builder, and direct seed path need explicit tests. Existing imported JSON carrying legacy floor/jurisdiction remains accepted; newly downloaded templates document the three supported choices and prefer the new residency boolean.

### 9. Account Settings is the primary display-name editor

Keep `/settings` as the single primary place for a user to edit names. Replace the lone “Display Name” input with a **Display names** section containing a labeled **Name to edit** selector:

- **Default name — used wherever you have not customized it**
- one option per active top-level organization membership, ordered by org name

When Default is selected, Save calls `PATCH /api/auth/me`. Copy must say that the default also appears on platform-level surfaces and in organizations without an override; it does not overwrite existing per-org names.

When an organization is selected, the input edits that membership's override through the typed org display-name endpoint. Show:

- organization name;
- current effective name;
- whether it is customized or using the default;
- **Save for this organization**;
- **Reset to default** when an override exists.

Do not add “apply to every organization,” bulk-copy, or bulk-overwrite. Those actions could erase deliberate legal-name policies and are not how the fallback model works.

Support a stable deep link such as `/settings#display-names?org={slug}` or an equivalent hash/query contract. Public-delegate setup errors and prompts link directly to the relevant org selection. Changing the selector cancels/ignores stale save responses and never writes the wrong organization.

### 10. Per-org names are parent-organization scoped

An `OrgMembership.display_name` applies to the parent organization and all its sub-organizations, matching the existing membership/resolver model. Phase 105 does not add display-name fields to `SubOrgMembership` or allow a different name per committee/department.

Account Settings lists top-level memberships only. Contextual copy may say the name also applies inside that organization's sub-organizations.

### 11. Surface the current user's name state without N requests

Add current-user-only fields to authenticated `OrgOut`:

- `my_display_name` — effective org name (`display_name_for` result);
- `my_display_name_override` — nullable stored membership override.

Populate them in `_org_to_out` from the already-loaded current membership. They are absent/null for a nonmember/implicit sub-org context and never added to `OrgPublicOut`, Explore cards, public feeds, or another member's response.

Use the existing `GET /api/orgs` call in `OrgContext`/Settings to hydrate the selector; do not issue one GET per organization. Convert the display-name PATCH body/response from raw `dict` to typed schemas. The endpoint returns both effective and override values after set/reset.

Add a focused authenticated serializer-coverage test. This is not a new `Organization` model field, so the Phase 46a `_MUST_SURFACE_FIELDS` list should change only if its explicit contract requires response-only current-user fields.

### 12. Legal-name policy gains an explicit scope

Add `settings.verification_name_match_scope` with values:

- `public_delegates`
- `all_verified_members`

Org Settings presents one **Legal-name display rule** selector:

- Off
- Public delegates only (recommended)
- All verified members

When non-off, show the existing first / last / either / full match-mode selector. Preserve Phase 52j's token semantics.

- New enablement defaults to `public_delegates`.
- An absent scope with an existing non-off `verification_require_name_match` resolves to `all_verified_members` for backward compatibility.
- `public_delegates` is always blocking; hide/ignore the flag action because a “required public identity” rule that merely logs mismatch is contradictory.
- `all_verified_members` retains the existing block/flag choice and behavior.

Update stale comments/copy in `verificationLabels.js` that still claim display-name matching is not implemented.

### 13. Public-delegate scope covers public and public-accepting profiles

For this policy, a user is a public delegate in an organization if they have at least one org-scoped `DelegateProfile.visibility IN ('public', 'public_accepting')`.

Create one canonical org-scoped predicate/helper and use it for:

- transitions from private/followers-only into `public`;
- requests/transitions into `public_accepting`;
- per-org display-name set/reset;
- global default-name changes when no override exists;
- activation/change validation of the org's public-delegate name rule.

Do not use the tenant-unscoped form of `public_delegate_user_ids` for enforcement. Every query filters `org_id`; topic filtering is additional, never a replacement for org scope.

### 14. Public-delegate legal-name matching is strict and continuous

Unlike the legacy all-verified-member rule, a public-delegate legal-name requirement cannot treat “no legal name on file” as a match.

To expose a profile publicly under this rule, the user must:

1. have at least identity-level genuine verification and usable legal-name components;
2. have an effective per-org display name matching the configured mode;
3. pass applicable duplicate-flag/demotion checks.

On failure:

- missing verification returns the existing structured verification-required shape with `scope='delegate'` and links to Identity Verification;
- a name mismatch returns typed `name_match_required` detail including match mode, org slug/name-safe context, and a Settings deep link target;
- no legal name, address, hash, DOB, provider state, or document field appears in the payload.

If a user already has a public profile, a later per-org or relevant global name change is blocked when it would violate the rule. A global name edit does not affect organizations with explicit overrides and therefore is not checked against those orgs.

Clearing an override validates the resulting account-default fallback before the write. This closes the current reset bypass.

### 15. Enabling/changing a public-delegate rule cannot create silent noncompliance

When an admin changes from off/legacy-all-member behavior into `public_delegates`, or tightens the match mode, validate all existing public/public-accepting delegates in that org before saving.

- If all comply, save normally.
- If any do not, reject atomically with 409/422 typed detail containing only total count plus bounded items of `{user_id, display_name, reason_code}`. Reason codes may distinguish `verification_required` and `name_mismatch`; never return legal-name values.
- Org Settings renders an actionable summary telling the admin that those members must verify or change their name before the policy can be enabled.
- Do not auto-rename, auto-demote, hide profiles, revoke delegations, or message members in this pass.

This precondition applies to public-delegate scope only. Preserve existing all-verified-member policy semantics for backward compatibility.

### 16. “Require verification to become a public delegate” always means identity

Keep the existing checkbox for organizations that want verified public-accepting delegates without imposing a legal-name rule, but repair its semantics and copy.

When enabled, the canonical public-delegate verification check requires:

- at least identity verification even if the membership floor is absent/email-only;
- any stronger membership floor;
- membership residency-scope match when the membership gate requires resident;
- no open duplicate flag and no durable resolved-same demotion.

Do not reuse `is_org_verified` blindly because its email-only parity behavior and current residency omission make it too weak for this promise. Create one canonical delegate-eligibility helper used by route enforcement and tests.

When public-delegate legal-name scope is enabled, identity verification is implied. Render the verification checkbox checked/disabled or replace it with explanatory derived copy so the UI cannot represent “legal name must match, but identity verification is off.” Turning the legal-name rule off restores the independent checkbox value.

The identity checkbox continues to gate `public_accepting` promotion. The stricter public-delegate legal-name rule covers both `public` and `public_accepting` per Decision 13.

### 17. Global name edits enforce only policies they can affect

Before `PATCH /api/auth/me` changes `User.display_name`, load active parent-org memberships where `OrgMembership.display_name IS NULL`.

For each such membership:

- legacy/all-verified policy: preserve its block/flag semantics for verified users;
- public-delegate policy: enforce only if the user currently has a public/public-accepting profile in that org;
- off/non-applicable: no check.

If one or more blocking rules fail, reject the global write atomically. Return a bounded, privacy-safe list of affected org slugs/names and match modes so Account Settings can explain where to set a compliant per-org override. Do not partially change the global name or some memberships.

For flag-mode legacy rules, allow the global write and emit the same org-scoped mismatch audit event per affected org. Avoid duplicate events on retries/no-op writes.

### 18. Settings validation is merged-state, atomic, and field-addressable

The generic organization settings PATCH remains the write path, but affected verification keys must be normalized and validated together before assignment.

Validation covers:

- supported name-match scope/mode/action combinations;
- resident gates requiring a valid shared scope;
- supported role keys and boolean maps;
- proposal policy/floor/residency agreement;
- legal-name public-delegate activation precondition;
- legacy untouched-state exception.

Reject the whole settings write on any error. Never partially apply the residency scope while leaving dependent gates stale, or vice versa. Preserve unrelated settings and the established SQLAlchemy new-dict assignment pattern.

The frontend maps backend errors to the correct control, focuses the first invalid field, and keeps unsaved edits intact. Direct API clients receive the same invariants as the browser.

### 19. Privacy and audit boundaries remain strict

- Org administrators can configure name-match modes but never receive members' legal names.
- Account Settings shows only the current user's account/per-org display names.
- Audit events may contain candidate public display name, user/org IDs, mode, scope, and result; never legal name, address, DOB, locality hash, identity hashes, provider payload, or document fields.
- Structured errors contain policy requirements and public display names only.
- No new identity material is stored. `Proposal.verification_require_residency` is policy metadata, not user data.

### 20. No unrelated branding or identity expansion

Out of scope:

- automatic black/white header-color selection;
- blocking arbitrary header colors based on accessibility score;
- changing button text colors across the app;
- font-family/font-size branding;
- per-sub-organization display names;
- administrator edits of another member's display name;
- legal-name disclosure or admin lookup;
- legal-name enforcement for ordinary unverified members under public-delegate-only scope;
- removal/renumbering of old verification states;
- Didit workflow, webhook, metering, or provider-console changes;
- automatic delegate demotion/renaming/notification;
- new proposal jurisdiction taxonomies beyond the existing shared residency scope.

## Scope clusters

### A — Preflight and compatibility inventory

1. Record `origin/master`, Phase 104 deployments/bundle, schema head, health/readiness/monitor, and suite baselines.
2. Read-only aggregate inventory of affected org settings:
   - membership/role/proposal floors by value;
   - address/residency floor combined with residency booleans/scope presence;
   - proposal jurisdictions;
   - name-match mode/action and whether a future scope is absent;
   - public/public-accepting delegate counts per affected org, sanitized in closeout.
3. Confirm every frontend call site for global and per-org display-name writes (expected: global exists; per-org has none).
4. Confirm every route that can transition a delegate profile into or out of public/public-accepting visibility.

The inventory does not authorize policy mutation. If it reveals a non-demo legacy combination not covered by Decision 6, stop that row's normalization and report; do not guess.

### B — Header text branding

Implement Decisions 1–3. Extend schemas/serializers/endpoints, theme variables, branding controls/preview/contrast warning, and the full desktop/mobile nav text/icon sweep. Add backend and frontend tests. Confirm unconfigured org visual parity.

### C — Verification requirement vocabulary and residency coherence

Implement Decisions 4–6 and 18 for membership/role gates. Create shared mappers, remove selectable address-only choices and residency checkboxes, validate shared scope dependencies, preserve conditional legacy states, and update copy/labels.

Membership join enforcement and role cardinality-floor behavior remain authoritative and need side-effect tests, not just settings-round-trip tests.

### D — Proposal policy and shared residency

Implement Decisions 7–8. Add/reverse the Proposal field migration, replace the effective tuple with a typed requirement, update org/author controls, wire every create/update/serializer/import/seed path, and prove vote/eligibility side effects.

Do not alter existing proposal results, ballots, lifecycle, or Phase 103/104 compact feed pagination beyond adding a field only where a current UI demonstrably needs it. Compact feeds do not need the new field unless source review proves they render verification policy.

### E — Per-org display-name settings

Implement Decisions 9–11 and the relevant parts of 17. Add typed current-user fields/responses, build the Account Settings selector/editor/deep link, support reset, and test no-N-request hydration plus race-safe org switching.

Audit org-context name serializers after changes; preserve `display_name_for` as the one resolver and pass membership objects in list loops to avoid N+1 queries.

### F — Public-delegate legal-name and verification enforcement

Implement Decisions 12–17 and 19. Add scoped policy reads, canonical org-public-delegate predicate, strict matching, activation precondition, global/per-org enforcement, repaired delegate identity floor, typed errors, and privacy-safe audit coverage.

Test both `public` and `public_accepting`, not only the existing submit-for-accepting endpoint. Assert rejected transitions/name edits create no profile/name mutation and no misleading success audit/notification.

### G — Integration, QA, and closeout

1. Run focused backend/frontend suites after each cluster.
2. Run migration cycle and PostgreSQL fresh/upgrade smoke from `e7f8a9b0c1d2`.
3. Run the authoritative full suites, changed-file lint, production build, Python compile, diff check, and scoped secret/privacy scans.
4. Merge with `--no-ff`, push, and verify exact Railway frontend/backend deployments plus production bundle/health/readiness/monitor.
5. Run rendered desktop/mobile/keyboard QA via Chrome MCP if available. If the trusted-path failure persists, report the exact blocker without substituting source review.
6. Update `PROGRESS.md` only after verified deployment.

## Production QA scenarios

Use a disposable hidden organization or an existing demo organization whose reset/cleanup path is known. Do not alter the real California/Massachusetts policy merely to prove the feature.

1. Configure a gold primary color; set header text black, then white, then custom purple; verify desktop/mobile header, hover/active/focus, dropdown readability, public org landing, and reset-to-platform behavior.
2. Configure membership identity, then resident with a two-entry allowed scope; verify UI has no address-only option and cannot save resident with empty scope. Do not create a provider session; enforcement can be proven with existing safe test/demo identities or backend coverage.
3. Configure proposal policy through all four visible choices; verify no second jurisdiction input appears and resident points to the same allowed scope.
4. In Account Settings, change an org-specific name, verify org-context surfaces change while the account default and another org remain unchanged, then reset to default.
5. On a disposable user/profile or deterministic demo fixture, verify public-delegate name mismatch routes to the selected org name editor and a matching per-org name allows the transition. Do not expose/inspect a real legal name in QA output.
6. Verify an organization with no new branding/verification/name settings remains visually and behaviorally unchanged.

Production cleanup removes only exact disposable Phase 105 rows/files created for QA and reports what was removed. Do not delete or rewrite unrelated audit history.

## Operational watch-outs

- Phase 102b repaired the live Massachusetts proposal policy to legacy `always / address_on_id / MA`. Decision 6 must preserve that exact enforcement until an authorized admin explicitly changes it; Phase 105 must not auto-convert it to the shared residency scope.
- Phase 104 added no migration. The prior Alembic revision for the new Proposal boolean remains `e7f8a9b0c1d2` unless a later approved master adds one before branch creation; re-ground before writing the migration.
- Settings JSON mutation must use new-dict assignment so SQLAlchemy persists changes.
- Do not leak current-user `my_display_name*` fields into public organization schemas or caches.
- Avoid N+1 policy checks on global-name update: bulk-load memberships/orgs/public-profile presence, then evaluate in memory or bounded grouped queries.
- The standard Chrome MCP has recently been blocked at its trusted native-host path. Attempt the required path; do not silently substitute another browser or claim rendered QA from source tests.
- No Railway environment variable, paid service, Didit console change, or production verification consumption is required.

## Closeout must report

- Per-cluster DONE / blocked / scoped-up status.
- Source-grounded legacy-settings inventory and how each observed shape was handled, without sensitive values.
- Header-text schema/serialization/inheritance/nav coverage and contrast-warning behavior.
- The exact user-visible verification choices and confirmation that no new address-only choice remains.
- Shared residency enforcement for membership, roles, org proposal policy, and author proposals; legacy Massachusetts jurisdiction parity.
- Migration revision, reversibility cycle, PostgreSQL smoke, and schema head.
- Per-org display-name API/UI behavior, global fallback semantics, reset validation, and query/request count.
- Public/public-accepting delegate enforcement, existing-delegate activation precondition, global-name bypass proof, and privacy audit.
- Backend test delta from 3,140 passed / 20 skipped and frontend delta from 69/69.
- Files added/modified, branch state, commit SHAs, no-ff merge SHA.
- Railway frontend/backend deployment IDs, production bundle hash, health/readiness/monitor, and rendered QA result/blocker.
- Confirmation that no real org verification policy, legal name, identity payload, paid verification, or Railway configuration was mutated for QA.
- New debt and any follow-up explicitly marked NOT STARTED.

## Go

Read the entire spec, create the clean worktree/branch, and execute Phase 105 through verified production deployment. No additional approval is needed for the code, tests, reversible Proposal migration, normal merge/push/deploy, bounded read-only production inventory, or exact disposable/demo QA described here. Pause for destructive production-data action, a change to a real organization's verification policy, legal-name disclosure, paid verification consumption, Railway environment/infrastructure changes, or another material decision this spec does not resolve.
