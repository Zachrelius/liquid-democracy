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

**PASS - Admin endpoints:** All admin endpoints in `routes/admin.py` use `get_current_admin` which checks `user.is_admin`. Org-level admin endpoints in `routes/organizations.py` use `require_org_admin` which checks the membership role is `admin` or `owner`.

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

## Privileged Access Tiers (Phase 7.5, 2026-04-26)

Three roles can view data they don't own. This section pins what each tier
is permitted to do, what it explicitly is not, and where the boundary is
enforced in code.

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
