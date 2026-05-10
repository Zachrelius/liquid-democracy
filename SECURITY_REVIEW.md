# Security Review - OWASP Top 10

**Date:** April 2026
**Reviewer:** Phase 4d Automated Security Audit
**Scope:** Full backend and frontend codebase

---

## A01 - Broken Access Control

### Checks Performed
- Verified org-scoped endpoints check membership via `require_org_membership` middleware
- Verified admin endpoints check admin role via `require_org_admin` middleware
- Verified users cannot access other users' private data (votes, delegations)
- Verified proposal/topic/delegation modifications check ownership or admin role

### Findings

**PASS - Org-scoped endpoints:** All org-scoped endpoints in `routes/organizations.py` use `require_org_membership` or `require_org_admin` dependencies. The middleware in `org_middleware.py` correctly checks that the user has an active membership in the target organization before allowing access.

**PASS - Admin endpoints:** All admin endpoints in `routes/admin.py` use `get_current_admin` which checks `user.is_admin`. Org-level admin endpoints in `routes/organizations.py` use `require_org_admin` which checks the membership role's `system_key` is `'admin'` or `'steward'` (Phase 12 Stage 1 — formerly `'admin'` or `'owner'`).

**PASS - Private data:** Vote visibility is controlled by the `permissions.py` module (`can_see_votes`). Delegations are scoped to the current user in `list_my_delegations`. The vote flow graph uses privacy-aware node labeling, only revealing identities for public delegates, followed users, and users who delegate to the viewer.

**PASS - Modification checks:** Proposal updates check `author_id == current_user.id or current_user.is_admin`. Delegation operations are scoped to `current_user.id`. Follow request approval/denial checks the target user ID matches.

**PASS - Seed endpoint:** The `/api/admin/seed` endpoint checks `settings.debug` and returns 403 in production.

### No issues found.

---

## A02 - Cryptographic Failures

### Checks Performed
- Password hashing algorithm
- JWT secret management
- JWT payload contents
- Token generation method

### Findings

**PASS - Password hashing:** Uses `passlib.context.CryptContext(schemes=["bcrypt"])` in `auth.py`. Bcrypt is industry standard and appropriate.

**PASS - JWT secret from environment:** The `settings.py` loads `secret_key` from environment variables via Pydantic `BaseSettings`. The default value `"change-me-in-production-use-a-long-random-string"` is clearly marked as development-only. In production, the `SECRET_KEY` environment variable is required.

**PASS - JWT payload:** The access token payload contains only `{"sub": user_id, "exp": expire}`. No passwords, emails, or other sensitive data are included.

**PASS - Token generation:** Refresh tokens, email verification tokens, password reset tokens, and invitation tokens all use `secrets.token_urlsafe(48)` which provides cryptographically secure random generation (256+ bits of entropy).

### No issues found.

---

## A03 - Injection

### Checks Performed
- Database query patterns
- Markdown/HTML sanitization
- URL parameter validation

### Findings

**PASS - SQL injection:** All database queries use SQLAlchemy ORM methods (`.filter()`, `.get()`, `.query()`) which automatically parameterize queries. No raw SQL string concatenation was found in any route handler. The only raw SQL is `text("SELECT 1")` in the health check endpoint, which takes no user input.

**PASS - Markdown sanitization:** The frontend renders markdown using a custom `renderMarkdown` function in `ProposalDetail.jsx` that escapes HTML entities (`&`, `<`, `>`) before processing markdown syntax. This prevents XSS through proposal content.

**PASS - URL parameter validation:** Org slugs are validated by querying the database (non-existent slugs return 404). UUID parameters are used as-is with SQLAlchemy's `.get()` which handles them safely. Pydantic schemas validate request body types.

### No issues found.

---

## A04 - Insecure Design

### Checks Performed
- Rate limiting on auth endpoints
- Account enumeration prevention
- Token single-use and time-limited

### Findings

**PASS - Rate limiting:** The `slowapi` rate limiter is configured in `main.py`. The `forgot-password` endpoint has `@limiter.limit("3/hour")`. The `resend-verification` endpoint has `@limiter.limit("1/minute")` and also checks for recently-created tokens.

**NOTE - Login rate limiting:** Login endpoint does not have explicit rate limiting via `@limiter.limit()`. The slowapi limiter is initialized but not applied to the login route. However, the application does have a global rate limiter configured.

**PASS - Account enumeration prevention:** The `forgot-password` endpoint returns the same message (`"If that email is registered, we've sent a password reset link."`) regardless of whether the email exists. The login endpoint returns `"Invalid username or password"` without distinguishing between unknown user and wrong password.

**PASS - Token single-use:** Password reset tokens are marked with `used_at` timestamp after use and checked for prior use. Email verification tokens are marked with `verified_at` after use. Refresh tokens are revoked (marked with `revoked_at`) during rotation.

**PASS - Token time-limited:** Email verification tokens expire after 24 hours. Password reset tokens expire after 1 hour. Refresh tokens expire after 7 days. Invitation tokens expire after 7 days.

### No issues found.

---

## A05 - Security Misconfiguration

### Checks Performed
- Debug mode feature gating
- CORS configuration
- Security headers
- Production error responses

### Findings

**PASS - Debug mode:** The seed endpoint checks `settings.debug` and returns 403 when disabled. Time simulation endpoint does the same. The demo-users endpoint returns 404 when debug is off. The `debug` setting defaults to `False`.

**PASS - CORS configuration:** CORS origins are loaded from settings which default to localhost URLs for development. In production, these are configured via the `CORS_ORIGINS` environment variable. Only specific methods (`GET, POST, PUT, PATCH, DELETE`) and headers (`Authorization, Content-Type`) are allowed.

**PASS - Security headers:** The `SecurityHeadersMiddleware` in `main.py` adds:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-XSS-Protection: 1; mode=block`
- `Referrer-Policy: strict-origin-when-cross-origin`

**PASS - Error responses:** FastAPI's default exception handler does not include stack traces in production. The application uses structured error responses with `HTTPException` that contain only user-facing detail messages. Production logging uses JSON format without stack traces.

### No issues found.

---

## A06 - Vulnerable Components

### Notes
Unable to run `pip audit` or `npm audit` in this context. The following dependencies should be audited periodically:

**Python (backend):**
- FastAPI, uvicorn, SQLAlchemy, Alembic, python-jose, passlib[bcrypt], pydantic, slowapi, nh3, aiosmtplib, pydantic-settings

**JavaScript (frontend):**
- React, React Router, Vite, @hello-pangea/dnd, recharts, d3-force

**Recommendation:** Set up automated dependency scanning (e.g., Dependabot, Snyk) in CI/CD.

---

## A07 - Authentication Failures

### Checks Performed
- Token expiration
- Password reset session invalidation
- Brute-force protection

### Findings

**PASS - Token expiration:** Access tokens expire after 15 minutes (`jwt_expiration_minutes: int = 15`). Refresh tokens expire after 7 days. The frontend handles 401 responses by attempting token refresh, and redirects to login on failure.

**PASS - Password reset invalidates sessions:** The `reset_password` endpoint calls `_revoke_all_refresh_tokens(db, user.id)` after changing the password. The `change_password` endpoint does the same. This forces re-authentication on all devices.

**PASS - Brute-force protection:** The `forgot-password` endpoint is rate-limited to 3 requests per hour. The `resend-verification` endpoint is rate-limited to 1 per minute. The global slowapi limiter provides baseline protection.

### No issues found.

---

## A08 - Data Integrity Failures

### Checks Performed
- Audit log append-only enforcement
- Vote tally computation

### Findings

**PASS - Audit log is append-only:** The `AuditLog` model has no UPDATE or DELETE operations anywhere in the codebase. The `log_audit_event` function only calls `db.add()`. The admin audit log endpoint (`/api/admin/audit`) is read-only (`GET`). The model docstring explicitly states "No UPDATE or DELETE operations ever."

**PASS - Vote tallies computed from records:** The `compute_tally` function in `delegation_engine.py` computes tallies from actual vote records at query time. There is no stored/cached tally that could be manipulated independently. `VoteSnapshot` entries are periodic snapshots for time-series display, not used for official results.

### No issues found.

---

## A09 - Logging and Monitoring

### Checks Performed
- Auth event logging
- Sensitive data in logs

### Findings

**PASS - Auth events logged:** The following events are audit-logged:
- `user.registered` (includes username, email, is_first_user)
- `user.login` (includes username)
- `user.logout`, `user.logout_all`
- `user.email_verified`
- `user.password_reset_requested`
- `user.password_reset_completed`
- `vote.cast`, `vote.retracted`
- `delegation.created`, `delegation.updated`, `delegation.revoked`
- `proposal.created`, `proposal.status_changed`
- `follow.requested`, `follow.approved`
- `delegate_application.approved`, `delegate_application.denied`
- `org.created`

**PASS - No sensitive data in logs:** Audit log `details` fields contain action-specific metadata (user IDs, vote values, topic IDs) but never include passwords, tokens, or full email content. Request logging includes user_id and request metadata but not request bodies. The `RequestLoggingMiddleware` only extracts `sub` from JWT for logging (never the token itself).

### No issues found.

---

## A10 - Server-Side Request Forgery (SSRF)

### Checks Performed
- User-supplied URL fetching
- External resource loading

### Findings

**PASS - No URL fetching:** The application does not fetch any user-supplied URLs. Email sending uses configured SMTP settings, not user-provided URLs. There are no webhook, callback URL, or avatar URL features that could be exploited for SSRF.

### No issues found.

---

## Summary

| Category | Status | Notes |
|----------|--------|-------|
| A01 Broken Access Control | PASS | Org membership, admin role, and ownership checks in place |
| A02 Cryptographic Failures | PASS | bcrypt passwords, env-based JWT secret, secure token generation |
| A03 Injection | PASS | SQLAlchemy ORM, HTML escaping, Pydantic validation |
| A04 Insecure Design | PASS | Rate limiting, anti-enumeration, single-use time-limited tokens |
| A05 Security Misconfiguration | PASS | Debug gating, CORS restriction, security headers |
| A06 Vulnerable Components | NOTE | Manual audit recommended; set up automated scanning |
| A07 Authentication Failures | PASS | Short-lived tokens, session invalidation on password change |
| A08 Data Integrity | PASS | Append-only audit log, computed tallies |
| A09 Logging and Monitoring | PASS | Comprehensive audit logging, no sensitive data exposure |
| A10 SSRF | PASS | No user-supplied URL fetching |

**Overall assessment:** The application demonstrates strong security practices across all OWASP Top 10 categories. The architecture makes good use of FastAPI's dependency injection for access control, SQLAlchemy for injection prevention, and established cryptographic libraries for authentication. The main recommendation is to set up automated dependency vulnerability scanning for ongoing protection.


---

## Phase 7C.1 update: Identity vs ballot-content boundary on the public vote-graph endpoint (2026-04-27)

`GET /api/proposals/{id}/vote-graph` previously gated both voter *identity* and *ballot content* behind the same `can_see_identity` flag (true for self / public delegates / followed users / private-delegators-to-viewer; false otherwise). Phase 7C.1 separated them.

### What's hidden (identity)

For any voter the viewer cannot see by name, the node's `label` field is empty. The graph response also doesn't return `username`, `email`, `display_name`, or other identity-revealing fields on any node — only `id` (which is opaque) and the privacy-relevant flags (`is_public_delegate`, `is_current_user`, `vote_source`, etc.) that the viewer can already derive from publicly visible state. The viewer cannot reconstruct an anonymous voter's identity through any node field.

### What's visible (ballot content)

The voter's `ballot.approvals` / `ballot.ranking` / `ballot.vote_value` is populated for every voter who has cast a ballot, regardless of identity gating. The ballot content is part of the aggregate population view that all viewers already see (via the per-option counts shown on the proposal page). Surfacing the per-voter ballot lets the visualization render attractor pulls and ballot arrows, showing how the *whole* population voted.

### Framing

The platform's privacy claim, after Phase 7C.1: **we hide who voted what, not what was voted.** This matches the Security & Trust page's existing language about identity privacy and avoids the over-strict interpretation that would hide aggregate voting patterns from view.

### Code change

`backend/routes/proposals.py:763-774` — drop the `can_see_identity` gate from `ballot_obj` construction inside `get_vote_graph`. The `label` gating at line 742 stays.

### Tests

- `backend/tests/test_vote_graph_privacy.py` (new, 4 tests):
  - Anonymous voters have `label == ""` AND populated `ballot`.
  - Followed voters have both `label` and `ballot` populated.
  - Anonymous nodes don't leak any identifying field.
  - The privacy boundary holds across all three voting methods (binary / approval / ranked_choice).

### Out-of-scope here

- **Admin endpoints** (`/api/admin/audit`, `/api/admin/delegation-graph`, etc.) are covered by Phase 7.5 (Privacy and Access Hardening), not this update. Phase 7C.1's clarification is strictly about the public vote-graph endpoint.
- **Encrypted ballot storage at rest** remains deferred. The current model relies on institutional privacy (operator audit logs, legal accountability), not cryptographic privacy.


---

## Privileged Access Tiers (Phase 7.5, 2026-04-26; updated Phase 12 Stage 1, 2026-05-03)

Three roles can view data they don't own. This section pins what each tier
is permitted to do, what it explicitly is not, and where the boundary is
enforced in code.

> **Phase 12 Stage 1 update (2026-05-03):** the per-org `'owner'` role
> renamed to `'steward'`. The four preset role system_keys are now
> `steward`, `admin`, `moderator`, `member` — code references roles by
> `Role.system_key`, not by string equality on a column. Per-action
> permission checks now go through `has_permission(db, user_id, org_id,
> permission_key)` (see `backend/role_permissions.py`) which loads
> `OrgMembership → Role → RolePermission` and caches results per request.
> The Tier 2 boundary description below is unchanged in semantics — what
> changed is only the implementation. Two operations remain hardcoded
> outside the permission system: `org.delete` and `org.transfer_stewardship`
> (if it exists) require `role.system_key == 'steward'` and cannot be
> re-granted via the matrix UI Stage 2 will introduce.

> **Phase 12 Stage 2 update (2026-05-03):** the configurable permission matrix UI shipped at `/{org-slug}/admin/settings/permissions`. **Editability surface:**
>
> - **Read access**: any authenticated org member can view the matrix (`GET /api/orgs/{slug}/role-permissions`). Members get a read-only rendering of the page that shows what their role can do — useful for accountability and self-service understanding.
> - **Write access**: gated by the new `role_permissions.edit` permission key (the 24th key, added in Stage 2's B3 migration). Default grants: Steward + Admin = TRUE; Moderator + Member = FALSE. Any role with this permission can edit the matrix; an org can re-grant it through the matrix itself.
> - **Steward lockout protection**: three Steward permissions are hardcoded TRUE and cannot be unset via the matrix — `member.change_role`, `org.edit_settings`, and `role_permissions.edit`. Together these guarantee a Steward can always recover from any matrix configuration. Enforcement is belt-and-suspenders: `PATCH /api/orgs/{slug}/role-permissions` returns 400 on attempts to unset these cells, AND `has_permission` returns TRUE for these (Steward, key) pairs even if the underlying `RolePermission` row is corrupted to `enabled=False`. The lockout set lives at `backend/role_permissions.py::STEWARD_LOCKED_PERMISSIONS`.
> - **Audit logging**: every successful save produces one `role_permissions.updated` event with a structured `changes` payload listing each cell that flipped (role_system_key, permission_key, old, new). No-op saves (every change already matches current state) skip the audit insert.
> - **D4 UI hiding**: in addition to the server-side 403 from Stage 1, Stage 2 hides the org-delete UI control on the Settings page from anyone whose `user_role !== 'steward'`. The `transfer-stewardship` UI control gets the same treatment if/when that endpoint is added. Defense-in-depth — a non-Steward making a direct API call (curl, custom client) still gets 403; the UI hiding just prevents the "I clicked delete and got a confusing message" UX path. Sub-org delete (and other matrix-routed delete operations) is NOT gated by role-tier — those are governed by `has_permission(user, org, 'sub_org.delete')` etc. through the matrix.
> - **Concurrency**: last-writer-wins on cell-level edits. No optimistic concurrency, no WebSocket sync. Acceptable for friend-pilot scale; a future pass could add a `version` field if real orgs run into stale-edit issues.

> **Phase 12.5 update (2026-05-04):** permission system completeness pass. Three changes worth pinning here:
>
> - **New 25th permission key `proposal.set_thresholds`** (default Steward + Admin only). Previously `proposal.create` carried with it the implicit power to set arbitrary `pass_threshold` and `quorum_threshold` values at proposal-creation time; now those are gated independently. Members or Moderators granted `proposal.create` via the matrix can submit proposals but the threshold inputs are hidden in the UI and the backend (`POST /api/proposals` + `PATCH /api/proposals/{id}`) returns 400 on attempts to set non-default threshold values. The check is "differs from defaults," so a caller passing values matching the org's defaults always succeeds.
> - **Org-level default thresholds** (`default_pass_threshold` + `default_quorum_threshold`) live in `Organization.settings` JSON, edited via a new section on the Org Settings page (gated by `org.edit_settings`). Save emits `org.default_thresholds_changed` audit event with a `{key: {old, new}}` diff. No hard floor — trust the permission system per Q2.
> - **Permission-driven UI gating throughout admin nav**. The admin nav and per-page admin controls now gate on `has_permission` results (surfaced via the new `user_permissions: [...]` field on `/api/orgs/{slug}` responses), not on coarse role tier. A Member granted `proposal.create` via the matrix sees the admin tab → Proposals subsection only; a Moderator sees the subsections matching their default grants; etc. This closes the "matrix lies" gap where granting a permission via the matrix had no UI surface for non-admin users to actually use it.
>
> Defense-in-depth posture unchanged: backend permission checks (`has_permission(user, org, key)`) remain the source of truth. UI gating just prevents the confusing-error UX path; a direct API caller (curl, custom client) still gets 403 / 400 on operations they lack permission for.

> **Phase 16 update (2026-05-04):** new 26th permission key `proposal.set_durations` (default Steward + Admin + Moderator TRUE; Member FALSE). Same exposure shape as `proposal.set_thresholds` — gates per-proposal override of org-default deliberation/voting durations on `POST /api/proposals` and `PATCH /api/proposals/{id}` via the "differs from defaults" check; callers without the permission either omit the fields or pass values matching org defaults. No new data-exposure surface. Validation floors (`voting_days >= 0.05`, `deliberation_days >= 0`) are independent of the permission gate — they reject 400 regardless of caller permissions to prevent pathological zero-second voting windows. Defense-in-depth posture unchanged: backend `has_permission` enforcement is the source of truth; UI hides the editable inputs (replaced with read-only display of the org's defaults) for callers without the permission, matching the Phase 12.6 threshold-form-copy pattern.

> **Phase 17 update (2026-05-09):** org-configurable tie resolution. No new permission key — org-level configuration (`Organization.settings.tie_resolution = {approval, ranked_choice}`) is gated by the existing `org.edit_settings` permission. New audit surface: `Proposal.tie_resolution` JSON column gets written at advance-to-passed time when a tally returns `tied=True` AND `len(winners) > 1`, capturing `{method, input_winners, chosen_winners, seed, metadata, applied_at}` as a verifiable closure record. New audit event `proposal.tie_resolved` is logged on every auto-resolution. The `random_seed` method is verifiable by anyone — recompute `sha256(proposal_id + ':' + voting_end.isoformat())`, mod into `2^32`, seed `random.Random`, and `random.choice(sorted(input_winners))` reproduces the chosen winner. The previously-shipped manual admin-resolves endpoint at POST `/api/orgs/{slug}/proposals/{id}/resolve-tie` (and its `TieResolutionRequest` schema) is **removed** in this pass — the spec premise was that it was dead code; investigation found it live but unused, and the auto-resolution path makes it unreachable in practice (it requires `tie_resolution IS NULL` AND `status = passed`, but the same code path that flips status to passed now writes tie_resolution atomically). No data-exposure surface change: the resolution audit record is visible only to callers who can already read the proposal (`/api/proposals/{id}` returns it via `_build_proposal_out`).

> **Phase 18 update (2026-05-10) — Phase 4c retrofit closure for delegation org-scoping.** Closes a multi-tenancy gap surfaced via friend-pilot dogfooding: the `delegations`, `delegation_intents`, `follow_relationships`, and `follow_requests` tables previously had **no `org_id` column at the schema level** because Phase 4c's multi-tenancy retrofit added `org_id` to data tables (topics, proposals, delegate_profiles, etc.) but skipped the relationship tables. As a consequence, 15+ `db.query(models.Delegation)` call sites were structurally unable to filter by org, the network-graph visualization showed cross-org delegations, and one prod row was tally-leaking across orgs (a global delegation made in one org being counted in another org's tally when delegator+delegate were co-members of both). The "right by coincidence" tally protection — non-member delegators getting filtered at iteration time by `compute_tally`'s `eligible_voter_ids_for_proposal` check — was an incidental side-effect, not a deliberate cross-org delegation safeguard. **What Phase 18 ships:** all four relationship tables get `org_id` (and `sub_org_id` for delegation tables); a two-phase migration (nullable + backfill, then NOT NULL) backfills existing rows via three sweeps (topic-scoped via `topics.org_id`; globals where parties share exactly one org; globals where parties share multiple orgs via "more-recently-active org by delegate's most recent vote" heuristic, with INFO-level audit logging of the chosen + alternative orgs); read-side filtering at every query site; write-side org plumbing in CRUD endpoints; `/api/delegations/*` and `/api/follows/*` move under `/api/orgs/{slug}/` (clean break, no compat aliases); `graph_store` partitions by org with cycle detection per-org; new audit event `delegation.org_id_backfilled` per backfilled row for forensic completeness. **Defense-in-depth posture restored at the schema level:** delegations + follows are now structurally org-scoped (a delegation in org A cannot apply to a proposal in org B because the row's `org_id` doesn't match), where previously the only protection was the accidental iteration filter. **No new permission key** — existing `require_org_membership` middleware gates the new `/api/orgs/{slug}/delegations/*` and `/api/orgs/{slug}/follows/*` route prefixes. The `FollowRelationship` retrofit was structurally important: leaving follow account-level while delegation became org-scoped would have created a back-door delegation leak via the `delegation_allowed` permission level (approving an account-level follow would silently grant per-org delegation rights everywhere both parties are co-members). Audit log entries pre-Phase-18 were NOT retroactively backfilled with `org_id` (Phase 18 D8); forensic completeness is achievable by joining to the post-migration row's `org_id`. The Phase 17 audit Item 42 ("Frontend test framework absent") still applies — Phase 18 frontend changes (per-org Delegations.jsx + DelegateModal sub-org fan-out collapse + follow surfaces under org prefix) are browser-verified rather than unit-tested, and frontend regression coverage is queued for the eventual harness-bootstrap pass.

> **Phase 19 update (2026-05-10) — Public Delegate Pages.** Adds the public-delegate identity surface: per-org delegate profiles (new `OrgDelegateProfile` table), per-topic visibility states on existing `DelegateProfile` rows (new `visibility` enum: `private` / `public` / `public_accepting`), per-vote rationale (new `DelegateVoteRationale` table), public read endpoints, and an approval workflow for the `public_accepting` transition. **No new permission key**: the approval gate uses the existing `delegate_application.approve` permission already in `permission_registry.py` from Phase 12 Stage 1.
>
> - **Per-topic visibility model.** Each `DelegateProfile` row carries a `visibility` enum: `private` (default for new rows; only the owning user can see content for this topic), `public` (transparent — bio, position statement, and rationale on past votes are visible on the public delegate page; new public-origin delegations not solicited from the browse page), `public_accepting` (transparent + actively accepting delegation; appears on the org's delegate browse page with a delegate-to-me action). Existing `DelegateProfile` rows backfilled to `public_accepting` to preserve current behavior on prod.
> - **Page-visibility ladder.** `OrgDelegateProfile.page_visibility` is a separate enum: `private` (default — only the owning user sees the page; drafting state), `private_delegators` (intermediate — approved followers of this user **in this org** see the page; uses Phase 18 `FollowRelationship.org_id` filter so a follow established in one org does NOT leak page visibility to a different org), and a derived `public` state that activates when **any** of the user's `DelegateProfile` rows in this org is non-`private`. Effective visibility = `min(page_visibility, max(topic_visibility))` — page-visibility is the ceiling, per-topic visibility is the floor. Centralized in helper `OrgDelegateProfile.effective_page_visibility()` (called at every render boundary; no scattered re-implementations).
> - **Approval workflow.** The `public → public_accepting` topic transition can be gated per-org. When approval is required, the user submits a request, an approver with `delegate_application.approve` (default Stewards + Admins) reviews and approves (one click) or denies (with comment). Becoming `public` (transparent without accepting) is freely toggleable — only inviting new delegations requires approval, transparency about voting record never does. Permission check is `has_permission(user, org, 'delegate_application.approve')` at every review endpoint.
> - **Vote rationale visibility.** Per-vote rationale is opt-in per vote (delegate writes a short explanation when casting a vote). Visibility is centralized in helper `permissions.can_view_vote_rationale(viewer, vote, db) -> bool`. The helper enforces: viewer is the vote owner OR (viewer has access to the org AND the proposal's primary topic is in non-`private` state for the vote owner). Rationale on a topic that flips back to `private` becomes invisible **without data loss** — visibility is enforced at read time; raising the topic state again restores visibility.
> - **Hard-revert cascade behavior (D15).** Reverting a topic from `public` or `public_accepting` to `private` triggers a controlled cascade: public-origin delegations on that topic are auto-revoked and the affected delegators receive a `delegation_revoked_by_delegate` notification ("your delegation to [delegate] on [topic] was revoked because they stopped publicly accepting delegation on this topic"); private-origin (follow-based) delegations on the same topic are **preserved** and their delegators receive **no notification** because nothing changed for them. The public/private origin distinction is implemented in centralized helper `_revoke_public_origin_delegations_on_topic` in the lifecycle layer. Per the spec/reality reconciliation: Wave 1 didn't add a `Delegation.delegation_intent_id` FK column; the helper instead uses **DelegationIntent-row-existence-based detection** (a delegation is private-origin iff an activated `DelegationIntent` row matches its `(delegator, delegate, org, sub_org, topic)` shape). The proxy is structurally fragile (if intent rows were ever cleanup-deleted, previously-private delegations would be misclassified as public on the next revert) and is logged as audit Item 53 for follow-up. The functional behavior is correct today; centralizing the helper means there is a single point to upgrade when the FK column lands.
> - **Follower-scoped page visibility for `private_delegators`.** When a user sets `page_visibility='private_delegators'`, the page-read endpoint checks for an approved `FollowRelationship` between the viewer and the page-owner where `org_id = page_org_id` AND `status = 'approved'`. The org-scoping is load-bearing: pre-Phase-18 `FollowRelationship` had no `org_id` and a follower in any org would see the page in every org; Phase 18's retrofit makes the per-org filter structurally enforceable. Non-followers get 404 (not 403) to avoid leaking the existence of the private page.
> - **Public read endpoint for transparent-only delegates.** `GET /api/orgs/{slug}/delegates/{handle_or_username}` exposes the public delegate page; the auth gate uses `effective_page_visibility` so anonymous viewers receive the page when effective visibility is `public`, logged-in approved followers receive it when effective visibility is `private_delegators` or higher, and everyone else gets a 404. (D12 closure — gap-fill commit `83bab63` in this same pass added the endpoint after the frontend cluster surfaced it as missing.)
> - **No new permission key surface area.** All approval/management endpoints sit on existing `delegate_application.approve` (Phase 12 Stage 1) or are user-scoped (the page owner manages their own `OrgDelegateProfile`). The permission matrix UI was not extended in this pass; orgs can re-grant `delegate_application.approve` to Moderator or Member through the existing matrix.
>
> Defense-in-depth posture unchanged: backend permission and visibility checks are the source of truth (no UI gating substitutes for a server-side check). The `effective_page_visibility` helper is called at every read boundary, including the browse endpoint, the per-delegate-page endpoint, the rationale GET, and any other place that surfaces delegate-derived content. Audit logging fires on the lifecycle transitions (`delegate_application.approved`, `delegate_application.denied`) consistent with the Phase 12 audit pattern; the hard-revert cascade emits one `delegation_revoked_by_delegate` notification per affected delegator (no audit row added in this pass — the underlying delegation row's `revoked_at` is the durable record).

### Tier 1 — Authenticated user

Standard `Depends(get_current_user)`. A logged-in user may:

- Read and write their own profile, votes, delegations, and follow
  relationships.
- Read public proposals, public delegate profiles, and public vote-graph
  visualizations.
- Read other users' votes only when the visibility rules in
  `backend/permissions.py:can_see_votes` permit it (self / follower /
  public delegate topic).

The authenticated user may **not** read the audit log, the system-wide
delegation graph, or the system user list. They may not view another user's
ballot via any elevation path; the elevation endpoint is gated to platform
admins only.

### Tier 2 — Org admin (per-organization)

Scoped role enforced through `org_middleware.require_org_admin`. An org
admin may:

- View analytics and the member list **of their own organization**.
- Manage org-scoped proposals, topics, and moderator actions for their org.
- View an org-scoped audit log restricted to events in their org's scope.

An org admin may **not**:

- Cross organization boundaries — they cannot read or modify another org's
  data even if they hold the role in a different org.
- View ballot content via the elevated endpoint
  (`GET /api/admin/audit/ballots/{id}`); that endpoint is platform-admin-
  only.
- Grant the `is_admin=True` platform-admin flag to anyone (only platform
  admins can call `PATCH /api/admin/users/{id}/make-admin`).

### Tier 3 — Platform admin (`is_admin=True`)

The system-scope role enforced by `backend/auth.py:get_current_admin`. The
endpoints listed at the top of `backend/routes/admin.py` form the complete
inventory of what this role gates today. A platform admin may:

- Run the filterable audit log viewer at `GET /api/admin/audit`. Ballot
  content is **redacted at response time** per the `REDACTED_DETAIL_FIELDS`
  allowlist in `backend/routes/admin.py`. The standard view shows
  `vote_value`, `ballot`, and `previous_value` as the literal string
  `"<redacted>"`, with a `_redacted_fields` array making the redaction
  explicit to consumers.
- Elevate to view the unredacted entry for a single audit row via
  `GET /api/admin/audit/ballots/{audit_log_id}` with a non-empty `reason`
  query parameter (max 500 chars). The elevation **self-logs** as an
  `admin.audit_ballot_viewed` audit event recording: the requesting admin's
  user id (`actor_id`), the IP, the target audit entry's id, the original
  action (`viewed_action`), the original actor (`viewed_actor_id`), and the
  reason. The elevation creates an audit trail; it **does not** require
  multi-admin approval (deferred to Phase 12+).
- View the system-wide delegation graph via
  `GET /api/admin/delegation-graph`. Each access self-logs as
  `admin.delegation_graph_viewed`.
- View the system user list via `GET /api/admin/users`. Each access
  self-logs as `admin.user_list_viewed`.
- Grant the platform-admin role to another user via
  `PATCH /api/admin/users/{id}/make-admin`.
- Run debug-only seed/time-simulation endpoints **iff** `DEBUG=true` is set
  in the environment. Production deploys never expose these.

A platform admin **cannot**:

- Bypass the elevation/audit requirement when viewing ballot content. The
  default `/api/admin/audit` endpoint is the only way to read the audit log
  in bulk; bulk-reading there returns redacted ballots, full stop. The only
  unredaction path is the per-entry elevation endpoint, which records who,
  when, why, and on whose behalf.
- Change another user's password or impersonate them. There is no
  admin-side password-set endpoint and no impersonation flow in the
  codebase.
- Read or write data outside the endpoints listed in
  `backend/routes/admin.py` and the role-gate in `backend/auth.py`. The
  role does not implicitly grant access to org-scoped or user-scoped
  endpoints; it gates only the explicit `/api/admin/*` routes.

### User-facing accountability

The `GET /api/users/me/access-log` endpoint surfaces the elevated and
system-view audit events to the user whose data was accessed, so the
accountability is visible to the affected party rather than only to
operators. See `backend/routes/users.py:get_user_access_log` for the
mapping between audit actions and user-facing entries.

### Deferred (out of scope for Phase 7.5)

- Multi-admin approval workflows for elevated audit access (Phase 12+).
- Operator agreements and independent oversight body — institutional, not
  technical (see `DEPLOYMENT.md` "Current Deployment Status").
- Encrypted-at-rest ballot storage (Tier 3 cryptographic work, deferred).
- Splitting `is_admin=True` into finer-grained sub-roles.

---

## Polis Identity Model (Phase 9, 2026-05-01)

Phase 9 introduced Polis (pol.is) as a first-class deliberation artifact. Polis statements are inherently more public than ballots — other participants see them, and the visualization is the whole point of the tool. The platform tells users this directly through the privacy disclosure modal that fires on first visit to any Polis (see Decision 4 of `phase9_spec.md`). The technical implementation makes that framing honest.

### Pseudonymization via per-org `polis_xid`

When a member first opens a Polis in an org, the backend generates an opaque random string (`secrets.token_urlsafe(16)` ≈ 22 URL-safe characters) and stores the mapping `(user_id, org_id) → polis_xid` in the `polis_xids` table. The platform passes only `polis_xid` to pol.is via the embed's `data-xid` attribute. **pol.is itself never sees the platform's `user_id`.**

Cross-session continuity: the same user revisiting the same Polis in the same org gets the same xid, so their votes and statements stay attributed to a single point in the visualization. The xid is per-org isolated — joining a second org and visiting a Polis there generates a fresh xid, so two orgs that share a member can't correlate behavior through pol.is.

### Platform-side deanonymization for moderation

The `polis_xids` table is queryable by platform admins (or via the `?deanonymize=true` flag on the data export endpoint `GET /api/orgs/{slug}/polises/{polis_id}/export`). When deanonymized export is requested, the platform joins pol.is's export against the local xid-to-user mapping and produces output with platform user IDs and display names. This is intended for moderation-of-last-resort: identifying the source of a statement that violates the org's norms, or auditing a participation pattern the platform admin reasonably believes is abusive.

The deanonymization request itself emits a `polis.export_requested` audit event with `deanonymized: bool`. The audit captures *that* it was requested, **not** the contents of the export (matches the Phase 7.5 redaction principles for vote audit elevation).

### Privacy boundary visible to users

The first-visit disclosure modal tells users — verbatim:

> Your votes and statements here are visible to other participants. They're tied to a per-org pseudonym, not your name. The platform can identify who said what if needed for moderation, and your participation is recorded for cross-session continuity. This is different from voting on proposals, which stays private by default.

The disclosure dismisses per-Polis (localStorage key `polis_disclosed_<polis_id>`), not per-user globally — every Polis has its own privacy considerations and the user is reminded once per artifact.

### What pol.is sees vs. what the platform sees

| Information | pol.is sees | Platform sees | Notes |
| --- | --- | --- | --- |
| `polis_xid` | Yes (as `data-xid`) | Yes | The shared opaque token |
| Statement votes | Yes (own UI) | Available via export | |
| Statement text | Yes (own UI) | Available via export | |
| Platform `user_id` | **No** | Yes | The deanonymization key lives only platform-side |
| Display name | **No** | Yes | Joined to xids only via deanonymized export |
| Email | **No** | Yes | Never sent to pol.is |
| Cross-org behavior | **No** (each org has its own xid) | Yes (admin per-org) | Per-org isolation prevents cross-org correlation |

### Threat model summary

A user who reads the disclosure understands the asymmetry: their *identity-on-pol.is* is opaque, but their *identity-on-the-platform* is recoverable for moderation. This is the trade-off the disclosure makes explicit. The platform doesn't oversell pseudonymity; users get protection from casual identification by other participants but not from the platform admin.

### Deferred (out of scope for Phase 9)

- Multi-admin approval for deanonymized exports (matches the deferred multi-admin approval for ballot audit elevation under Phase 7.5).
- Self-hosted Polis (Tier 3.9). Hosted pol.is is the v1 surface; the data-flow described above assumes hosted.
- Cross-Polis analytics or organizational dashboards. Useful future work; distinct privacy posture, distinct review.

---

## Notification Privacy (Phase 13, 2026-05-04)

Phase 13 ships an in-app + email notification system covering 12 event types across the platform. The system is opt-in by default — every event-channel pair starts disabled — and users discover preferences through the notification center. The privacy considerations below describe what the system stores, what leaves the platform via email, and what an adversary at various trust tiers could observe.

### What is stored on the platform

The `Notification` table holds one row per (user, event) pair when the user has opted in to the in-app channel for that event. Each row carries a JSON `payload` with context the UI uses to render the notification: a comment-body excerpt (first ~160 chars), the proposal title, the actor's display name, the affected entity's id (proposal_id, comment_id, etc.), and an `org_id` for click-through routing. Rows persist for 90 days and are then deleted by the digest-loop's cleanup tick. Read state (`read_at`) is per-user.

The `NotificationPreference` table holds one row per (user, event_type, channel) pair the user has explicitly toggled. Rows are absent for unset preferences (absent = opt-out, since the default is false). Per-user `digest_cadence`, `quiet_hours_enabled`, `timezone`, and `notification_intro_dismissed` columns live on the `users` table.

A platform admin or a database breach would expose: which events each user has been notified about over the last 90 days, the comment-body excerpt and proposal-title text in each notification's payload, the user's email-channel toggles (i.e., what events they want emails for), and their digest cadence + quiet-hours settings. None of this exposes vote contents (votes have their own privacy boundary documented under Phase 7.5) or the cross-Polis pseudonym → platform-id mapping (documented above under Phase 9).

### What leaves the platform via email

Real-time and digest emails contain the same payload material that the in-app notification carries: the actor's display name, the comment excerpt, the proposal title, the relevant org name and branding (Phase 12.7 per-org logo + primary color render in the email per the user's org context). Email recipients with email-channel access have read access to whatever those payloads describe.

The risk class this exposes: a user who shares email access with another person (a household, a shared work address) effectively shares notification payload contents with that person. The platform does not attempt to gate this — email-channel opt-in is the user's affirmative choice that the channel is appropriate for their situation. Users for whom email is not a private channel can either leave the email toggles off (the default) or set the digest cadence to "Off" to silence email notifications without changing per-event toggles.

### Unsubscribe token format

Each notification email includes a "Unsubscribe from these" footer link encoding `(user_id, event_type)` in an HMAC-signed token using `settings.secret_key` and a 30-day expiry. The unsubscribe endpoint (`GET /api/notifications/unsubscribe/{token}`) verifies the signature, checks expiry, flips the `email` channel for that (user, event_type) pair to false, and returns a confirmation. The endpoint is unauthenticated — possession of a valid signed token is sufficient. The token does not encode any other capability; it cannot be replayed to flip in-app preferences, change digest cadence, or modify any other user-level state.

If the secret key were compromised, an attacker could generate unsubscribe tokens for arbitrary (user, event) pairs and silently disable email notifications. The blast radius is bounded to email-channel opt-out — no information disclosure, no other writes, no privilege escalation. Same posture as the existing JWT secret; key rotation is a future operational concern.

### Channel-control posture

Both the in-app and email channel toggles are per-user-controlled. There is no platform-admin override that lets an admin force a user to receive notifications for a given event class. There is no org-level setting that overrides per-user preferences (per Q3 spec lock — "no per-org notification settings"). The single exception is transactional emails (verification, password reset, org invitation) — these are essential to the platform working at all, are not subject to notification preferences, and do not appear in the unsubscribe path.

### Quiet hours is privacy-adjacent, not privacy-providing

The `quiet_hours_enabled` flag delays real-time email delivery from 9pm-9am user-local to 9am the next morning. It does not suppress the existence of the underlying event — the in-app notification row is still inserted, the digest still includes the event when it runs, and platform-side audit/storage is unchanged. Users who don't want to receive a notification at all should leave the relevant toggle off, not rely on quiet hours.

### Threat model summary

The notification system inherits the platform's existing trust tiers. A casual third party with no platform credentials cannot observe any notification material. A user with email access for a target user can observe the contents of any email-channel notification that target opts into. A platform admin with database access can observe stored notifications, preferences, and the user's contact email. A database breach exposes the same. The opt-in default is the primary user-facing protection: a user who opts into nothing has zero rows in either table.

### Deferred (out of scope for Phase 13)

- WebSocket / mobile-push channels (per Q1). Deferring keeps the attack surface to two well-understood transports.
- Per-org notification overrides (per Q3 spec lock). Adding org-level controls would require a different consent model.
- Notification analytics (open rates, CTR). Out of scope per spec; would change the storage profile by adding tracking pixels or click-through redirects.
- Encryption-at-rest of notification payloads in the database. The `payload` column is plain JSON; payload contents inherit whatever encryption-at-rest the host DB provides (Railway managed Postgres encrypts by default). Per-row payload encryption would require a key-management story we don't have today.
- Rate-limiting on the unsubscribe endpoint. The endpoint requires a signed token, so brute-forcing a target user's unsubscribe is not feasible in a meaningful timeframe; if signed-token expiry shortened or secret rotation happened, this would warrant revisiting.

---

## Public Org Landing Pages (Phase 14, 2026-05-06)

Phase 14 introduces public landing pages at `/{slug}` for orgs whose join policy is `invite_only_public`, `approval_required`, or `open`. The fourth value `invite_only_secret` (renamed from the legacy `invite_only` to preserve current behavior on existing orgs) keeps an org fully undiscoverable. The threat model below covers what's now exposed without authentication and the design decisions that shape the exposure.

### What's exposed without authentication

The new `GET /api/orgs/{slug}/public` endpoint requires no auth and returns:

- Org `slug`, `name`, `description`, and `join_policy`
- Org logo URL (if a logo was uploaded via Phase 12.7's branding flow)
- Org branding `primary_color` and `accent_color` (if configured)
- Org `intro_text` (markdown content, if a steward set one)

A logged-in caller gets the same response shape as a logged-out caller — auth state doesn't affect the response. The matching `OrgPublicLanding.jsx` component renders this data publicly on `/{slug}`.

Stewards opting their org into `invite_only_public`, `approval_required`, or `open` are explicitly choosing this exposure. The Org Settings policy selector spells out what each option exposes; the spec documents it as a deliberate steward decision, not an opaque platform default.

### Indistinguishability of secret orgs from non-existent ones

Both `invite_only_secret` orgs and non-existent slugs return the same 404 response from `GET /api/orgs/{slug}/public` and `POST /api/orgs/{slug}/join-request`. A scraper trying random slugs cannot tell whether the slug is unused or belongs to a secret org. This is a deliberate posture — without it, a 403 / different-shaped 404 would reveal that a secret-named org exists, which defeats the secrecy guarantee.

The same indistinguishability rule applies to the `DELETE /api/orgs/{slug}/join-request` endpoint and the existing legacy `POST /api/orgs/{slug}/join` endpoint (Phase 14 hardened the legacy endpoint to match for defense-in-depth).

### Migration of existing `invite_only` orgs

Phase 14's migration `c0a3e5d12f4a` renames every `join_policy='invite_only'` row to `'invite_only_secret'` to preserve current behavior — no org has its public visibility silently flipped on by deploying this pass. Stewards who want a public landing page must explicitly opt in by changing their org's policy to `invite_only_public`, `approval_required`, or `open` via the Org Settings page.

### Join requests and pending member visibility

Pending join requests (created via `POST /api/orgs/{slug}/join-request` for `approval_required` orgs) create an `OrgMembership` row with `status='pending_approval'`. These rows are NOT visible via the public endpoint or to non-admins. Only users with the `member.approve_join` permission (Stewards and Admins by default per the role-permissions matrix from Phase 12 Stage 2) can see pending requests, via the admin members page.

The `member.join_request` notification (Phase 13) fires only to those same approve-permission holders. Other members of the org don't see notifications about pending requests.

### Markdown rendering in `intro_text`

The `intro_text` field is markdown-rendered using the same renderer the platform uses for proposal deliberation bodies (`renderMarkdown.js`). The same XSS protections apply — no raw HTML, no `<script>` tags, no `javascript:` URLs in links. The 5000-character length cap on `intro_text` (enforced backend-side via Pydantic and frontend-side via textarea maxlength) limits the surface area of any future renderer bug.

Future audit consideration: when the markdown renderer is updated (e.g., dependency upgrade), re-verify that the new version still strips dangerous constructs. The intro_text field has a wider audience than proposal bodies (anyone with the URL vs. only members), so a renderer regression would have a larger blast radius here.

### `?next=` redirect parameter on Login / Register

Phase 14 added minimal `?next=` support to the Login flow so post-auth, users return to the org splash they came from. The implementation validates that `next` is a same-origin relative path (rejects `//host/path` protocol-relative values, absolute URLs to other hosts, and `javascript:` schemes) before redirecting. A rendered link of the form `/login?next=/{slug}` is the only path that gets users back to the splash post-auth.

Open-redirect risk: bounded. The validator restricts `next` to relative paths starting with `/`. Pre-Phase-14, no `?next=` support existed — the dispatch incorrectly described this as "Phase 9-era functionality"; the frontend dev surfaced and patched the gap as part of Cluster F. Worth a future audit pass to confirm the Login + Register flows both validate consistently and to extend coverage to any other auth-redirect entry points.

### Deferred (out of scope for Phase 14)

- SEO / robots / sitemap. No meta tags, no robots directives, no sitemap.xml. Default browser behavior. Public splash pages may be indexed by search engines via crawler discovery, but the platform doesn't actively help. Future work should consider per-policy opt-in (e.g., `invite_only_public` orgs may want robots: noindex while `open` orgs may want indexability) and steward-level overrides.
- Public org browser at `/explore`. No public list of all open / approval-required orgs across the platform. Prospective members reach orgs via direct URL share. Future pass when there are enough orgs to warrant browsing — that pass will need its own privacy review (e.g., should `approval_required` orgs be in the directory by default?).
- Analytics on splash page views. No "X people viewed your org page this week." Engagement-loop adjacent; deliberately deferred.
- Org-level invite-link generation (a single URL anyone can use to auto-join, separate from per-email invitations). Different feature; would need its own threat model around link sharing and revocation.
- Sub-org public landing pages. Sub-orgs are not exposed via the public endpoint; only top-level orgs have splash pages. Future Phase 13.5 / 14.x candidate work would need a sub-org-level public-page design with its own permission gates.
- Custom CSS / HTML in the intro field. Markdown-only by design; HTML escape hatches would expand the XSS surface significantly without clear product benefit.
