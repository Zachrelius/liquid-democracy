# Phase 4: Pilot-Ready Deployment — Claude Code Build Spec

## Overview

Phase 4 transforms the liquid democracy platform from a local demo into a deployable product that a civic organization can use for real decision-making. The goal is a system where an org admin can set up their organization, invite members, create proposals, and run votes — with no technical knowledge required after initial deployment.

This phase has four sub-phases: deployment infrastructure (4a), authentication hardening (4b), admin portal and multi-tenancy (4c), and security review with final polish (4d).

Read `PROGRESS.md` for current project state.

---

## Part A: Deployment and Infrastructure (Phase 4a)

### 1. Docker Containerization

Create a production-ready Docker setup:

**`Dockerfile` (backend):**
- Python 3.11+ slim base image
- Install dependencies from requirements.txt
- Copy application code
- Run with uvicorn in production mode (multiple workers)
- Health check endpoint: `GET /api/health` returning `{"status": "ok", "version": "0.1.0"}`

**`Dockerfile` (frontend):**
- Node 20 for build stage
- Build the React app with Vite (`npm run build`)
- Nginx alpine for serving stage
- Copy built static files to nginx
- Nginx config that serves the SPA (all routes fallback to index.html) and proxies `/api/*` to the backend

**`docker-compose.yml`:**
```yaml
services:
  db:
    image: postgres:16-alpine
    volumes:
      - pgdata:/var/lib/postgresql/data
    environment:
      POSTGRES_DB: liquid_democracy
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    healthcheck:
      test: ["CMD-LINE", "pg_isready -U ${DB_USER}"]
      interval: 5s
      retries: 5

  backend:
    build: ./backend
    depends_on:
      db:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql://${DB_USER}:${DB_PASSWORD}@db:5432/liquid_democracy
      SECRET_KEY: ${SECRET_KEY}
      CORS_ORIGINS: ${CORS_ORIGINS}
      SMTP_HOST: ${SMTP_HOST}
      SMTP_PORT: ${SMTP_PORT}
      SMTP_USER: ${SMTP_USER}
      SMTP_PASSWORD: ${SMTP_PASSWORD}
      FROM_EMAIL: ${FROM_EMAIL}
      BASE_URL: ${BASE_URL}
    ports:
      - "8000:8000"

  frontend:
    build: ./frontend
    depends_on:
      - backend
    ports:
      - "80:80"
      - "443:443"

volumes:
  pgdata:
```

**`.env.example`:**
```
DB_USER=liquid_democracy
DB_PASSWORD=CHANGE_ME_strong_random_password
SECRET_KEY=CHANGE_ME_another_strong_random_string
CORS_ORIGINS=["https://yourdomain.org"]
BASE_URL=https://yourdomain.org
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=notifications@yourdomain.org
SMTP_PASSWORD=CHANGE_ME
FROM_EMAIL=notifications@yourdomain.org
```

### 2. Database Migration to PostgreSQL

- Update SQLAlchemy configuration to use PostgreSQL via the DATABASE_URL environment variable
- Test all existing functionality against PostgreSQL (there may be minor SQLite-to-Postgres incompatibilities in queries or migrations)
- Ensure Alembic migrations run cleanly against a fresh PostgreSQL database
- Add a startup script that runs `alembic upgrade head` before starting the backend

### 3. Health and Readiness Endpoints

- `GET /api/health` — returns 200 if the server is running
- `GET /api/health/ready` — returns 200 if the server can connect to the database
- These are used by Docker health checks and cloud platform monitoring

### 4. Production Logging

- Configure structured JSON logging for production (not the dev-friendly console output)
- Log to stdout (Docker captures this)
- Include: timestamp, level, message, request_id (generate a UUID per request for tracing), user_id if authenticated
- Separate access logs from application logs

### 5. Self-Hosted Deployment Documentation

Create a `DEPLOYMENT.md` in the project root:

```markdown
# Deployment Guide

## Quick Start (Docker Compose)
1. Clone the repository
2. Copy .env.example to .env and fill in your values
3. Run: docker-compose up -d
4. Access the app at http://localhost (or your configured domain)
5. Create your first admin account at /register
6. Set up your organization at /admin/setup

## Cloud Deployment
Instructions for deploying to:
- Railway
- Fly.io
- A VPS with Docker

## HTTPS Setup
How to add Let's Encrypt SSL certificates

## Backups
How to back up and restore the PostgreSQL database

## Environment Variables Reference
Full list of all configuration options
```

---

## Part B: Authentication Hardening (Phase 4b)

### 1. Email Verification

Add email verification to the registration flow:

**New model:**
```
email_verifications
  id: UUID
  user_id: FK -> users
  email: string
  token: string (random, URL-safe, 64 chars)
  expires_at: datetime (24 hours from creation)
  verified_at: datetime (nullable)
  created_at: datetime
```

**Add to users model:**
```
email: string (unique, nullable initially for migration — required for new registrations)
email_verified: boolean (default false)
```

**Flow:**
1. User registers with username, display_name, email, and password
2. System creates the account with `email_verified = false`
3. System sends a verification email with a link: `{BASE_URL}/verify-email?token={token}`
4. User clicks the link, system verifies the token and sets `email_verified = true`
5. Until verified, the user can log in but sees a banner: "Please verify your email to participate in votes" and cannot cast votes or create delegations

**Email sending:**
- Use Python's `smtplib` or `aiosmtplib` with the SMTP configuration from environment variables
- Create an `email_service.py` module with a `send_email(to, subject, html_body)` function
- For development/testing without SMTP: if SMTP_HOST is not configured, log the email content to the console instead of sending (print the verification link so devs can click it)
- Email template: simple HTML with the org name, a clear "Verify your email" button, and a fallback plain-text link

### 2. Admin Invitation System

Org admins can invite members by email:

**New model:**
```
invitations
  id: UUID
  org_id: FK -> organizations
  email: string
  invited_by: FK -> users
  role: enum [member, admin] (default: member)
  token: string (random, URL-safe, 64 chars)
  status: enum [pending, accepted, expired, revoked]
  expires_at: datetime (7 days from creation)
  accepted_at: datetime (nullable)
  created_at: datetime
```

**Flow:**
1. Admin enters one or more email addresses in the admin portal
2. System sends invitation emails: "You've been invited to join [Org Name] on Liquid Democracy. Click here to create your account."
3. Invitation link: `{BASE_URL}/{org_slug}/join?token={token}`
4. Recipient clicks link, sees a registration form pre-filled with their email
5. After registration, they're automatically added to the org with email verified (the invitation email proves ownership)

**Alternative join flow (for orgs that prefer open registration with approval):**
1. User visits `{BASE_URL}/{org_slug}` and clicks "Request to Join"
2. User registers normally with email verification
3. Admin sees pending join requests in the admin portal
4. Admin approves or denies each request
5. Approved users gain full access

Both flows should be configurable per organization (invite-only vs. open with approval vs. fully open).

**New field on organizations:**
```
join_policy: enum [invite_only, approval_required, open] (default: approval_required)
```

### 3. Password Reset

- "Forgot password" link on login page
- Sends a reset email with a time-limited token (1 hour expiry)
- Reset page lets user set a new password
- Invalidates all existing sessions for that user after password change

### 4. Session Management Improvements

- Refresh token mechanism: short-lived access tokens (15 minutes) with longer-lived refresh tokens (7 days)
- Logout endpoint that invalidates the refresh token
- "Log out of all devices" option in user settings

### 5. Audit Logging for Auth Events

Add audit events for: `user.email_verified`, `user.password_reset_requested`, `user.password_reset_completed`, `user.invited`, `invitation.accepted`, `org.join_requested`, `org.join_approved`, `org.join_denied`

---

## Part C: Admin Portal and Multi-Tenancy (Phase 4c)

### 1. Organization Data Model

**New models:**

```
organizations
  id: UUID
  name: string ("Boston Effective Altruism", "Portland DSA Chapter")
  slug: string (unique, URL-safe, lowercase: "boston-ea", "portland-dsa")
  description: text
  join_policy: enum [invite_only, approval_required, open] (default: approval_required)
  settings: JSON (org-specific defaults — see below)
  created_at: datetime
  updated_at: datetime

org_memberships
  id: UUID
  user_id: FK -> users
  org_id: FK -> organizations
  role: enum [member, moderator, admin, owner]
  status: enum [active, suspended, pending_approval]
  joined_at: datetime
  
  UNIQUE(user_id, org_id)
```

**Organization settings JSON structure:**
```json
{
  "default_deliberation_days": 14,
  "default_voting_days": 7,
  "default_pass_threshold": 0.50,
  "default_quorum_threshold": 0.40,
  "allow_public_delegates": true,
  "public_delegate_policy": "admin_approval",
  "require_email_verification": true,
  "sustained_majority_floor": 0.45
}
```

**`public_delegate_policy` values:**
- `admin_approval` (default): Users apply to become public delegates. Applications go to a queue in the admin portal for review. Admin approves or denies with optional feedback message.
- `open`: Users can register as public delegates immediately without admin approval. Suitable for small, high-trust orgs.

When `allow_public_delegates` is `false`, the public delegate feature is disabled entirely — no one can register, and the delegate search only shows users the searcher already follows.
```

**Add `org_id` foreign keys to:**
- `proposals` (required)
- `topics` (required — each org defines its own topic set)
- `delegate_profiles` (required — you're a public delegate within a specific org)

**Do NOT add org_id to:**
- `users` — users exist globally and join orgs via memberships
- `delegations` — these are implicitly scoped to an org through the topic (which is org-scoped)
- `votes` — implicitly scoped through the proposal (which is org-scoped)

### 2. Org Context in API

Every API request (except auth and global user endpoints) must include org context. Two approaches — choose whichever is simpler to implement:

**Option A — Path prefix:** All org-scoped endpoints live under `/api/orgs/{org_slug}/...`
- `GET /api/orgs/boston-ea/proposals`
- `POST /api/orgs/boston-ea/proposals`
- `GET /api/orgs/boston-ea/topics`

**Option B — Header/cookie:** The frontend stores the current org context and sends it as a header (`X-Org-Slug: boston-ea`) with every request.

Option A is more RESTful and makes the URL shareable. Recommend Option A.

**Middleware:** Create middleware that extracts the org_slug from the path, resolves it to an org_id, verifies the current user is a member of that org, and makes the org context available to all route handlers.

### 3. Admin Portal Frontend

Add an admin section accessible to users with `admin` or `owner` role in the current org. Accessible via nav menu when the user has admin privileges.

**Admin pages:**

**Org Setup / Settings (`/admin/settings`):**
- Edit org name, description
- Change join policy (invite-only / approval required / open)
- Configure voting defaults (deliberation period, voting period, pass threshold, quorum)
- Public delegates section:
  - Toggle public delegates on/off (`allow_public_delegates`)
  - If on: set policy to "Require admin approval" or "Open registration" (`public_delegate_policy`)
- Danger zone: delete organization (with confirmation)

**Member Management (`/admin/members`):**
- List all members with roles, join dates, and status
- Search/filter members
- Change member roles (member → moderator → admin)
- Suspend or remove members
- View pending join requests (if approval_required policy) with approve/deny buttons
- Invite members by email (single or bulk — textarea with one email per line)
- View pending invitations with resend/revoke options

**Proposal Management (`/admin/proposals`):**
- List all proposals with status
- Create new proposals (enhanced version of the existing create flow):
  - Title, body (markdown with preview)
  - Topic selection with relevance sliders
  - Deliberation period start/end dates
  - Voting period start/end dates
  - Pass threshold (with default from org settings)
  - Quorum threshold (with default from org settings)
- Advance proposals through stages (deliberation → voting → closed)
- Close/withdraw proposals early if needed
- Pin important proposals to the top of the proposals list

**Topic Management (`/admin/topics`):**
- Create, edit, rename, deactivate topics
- Set topic colors
- View delegation statistics per topic (how many delegations, who are the top delegates)

**Delegate Applications (`/admin/delegates`):**
Only shown when `public_delegate_policy` is `admin_approval`. Displays pending applications from members who want to become public delegates.

Each application card shows:
```
┌──────────────────────────────────────────────────────────────┐
│ 👤 Jane Smith wants to be a public delegate for Healthcare   │
│                                                              │
│ Bio: "Registered nurse with 15 years of experience in        │
│ public health policy. I serve on the county health board..."  │
│                                                              │
│ Member since: Jan 2026 · Participation rate: 78%             │
│ Current delegators: 3 (private)                              │
│                                                              │
│ [Deny (with feedback)]  [Approve]                            │
└──────────────────────────────────────────────────────────────┘
```

- Approve: activates the delegate profile immediately, user is notified
- Deny: sends optional feedback message to the applicant ("We'd like to see more participation history before approving. Please reapply in 3 months.")
- Admin can also view and manage existing public delegates: see all active public delegates per topic, revoke delegate status if needed (with notification to the delegate and their delegators)

Add audit events: `delegate_application.submitted`, `delegate_application.approved`, `delegate_application.denied`, `delegate_profile.admin_revoked`

**Analytics Dashboard (`/admin/analytics`):**
- Participation rate over time (what percentage of members vote or delegate on each proposal)
- Delegation patterns: how many members delegate vs. vote directly, average number of delegations per member
- Proposal outcomes: pass rate, average margin, average participation
- Active members: daily/weekly active users
- Keep this simple — basic Recharts line and bar charts. Don't over-engineer.

### 4. Org Selection UI

If a user belongs to multiple orgs, they need a way to switch between them:

- After login, if the user belongs to one org, go directly to that org's proposals page
- If the user belongs to multiple orgs, show an org selector: cards with org name, description, and member count
- Org switcher in the nav bar (small dropdown next to the user menu) for users in multiple orgs
- URL always reflects the current org: `/boston-ea/proposals`, `/boston-ea/delegations`

### 5. First-Run Experience

When someone deploys a fresh instance:

1. First user to register becomes the instance admin
2. They're prompted to create their organization (name, slug, description, join policy)
3. After org creation, they land on the admin portal with prompts:
   - "Create your first topics" (with suggested defaults: General, Budget, Policy, Operations)
   - "Invite members" (email invite form)
   - "Create your first proposal" (quick-start template)
4. Each step can be skipped and returned to later

This replaces the demo seed data for production — the seed endpoint should only be available when `DEBUG=true`.

---

## Part D: Security Review and Final Polish (Phase 4d)

### 1. OWASP Top 10 Security Review

Systematically review the codebase against each OWASP Top 10 category:

**A01 — Broken Access Control:**
- Verify every endpoint checks that the current user is a member of the org they're accessing
- Verify admin endpoints check admin role
- Verify users can't access other users' private data (votes, delegations) without permission
- Verify proposal/topic/delegation modifications check ownership or admin role
- Test: try accessing org A's data while authenticated as a member of org B

**A02 — Cryptographic Failures:**
- Verify passwords are hashed with bcrypt (not MD5, SHA1, or plaintext)
- Verify JWT secret is loaded from environment, not hardcoded
- Verify no sensitive data in JWT payload (no passwords, no email addresses — just user_id and expiry)
- Verify HTTPS is enforced in production (redirect HTTP to HTTPS)

**A03 — Injection:**
- Verify all database queries use SQLAlchemy parameterized queries (no raw SQL string concatenation)
- Verify markdown rendering sanitizes HTML (nh3/bleach — already implemented)
- Verify user input in URLs is validated (org slugs, UUIDs)

**A04 — Insecure Design:**
- Verify rate limiting on login, registration, password reset, and email verification endpoints
- Verify account enumeration is prevented (login error message doesn't distinguish "user not found" from "wrong password")
- Verify password reset tokens are single-use and time-limited
- Verify email verification tokens are single-use and time-limited

**A05 — Security Misconfiguration:**
- Verify debug mode is off in production (`DEBUG=false`)
- Verify CORS is restricted to the actual frontend domain
- Verify security headers are set (already implemented)
- Verify the seed data endpoint is disabled in production
- Verify stack traces are not returned in API error responses in production

**A06 — Vulnerable Components:**
- Run `pip audit` to check Python dependencies for known vulnerabilities
- Run `npm audit` to check Node dependencies
- Update any flagged packages

**A07 — Authentication Failures:**
- Verify session tokens expire appropriately
- Verify password reset invalidates old sessions
- Verify brute-force protection on login (already implemented with rate limiting)

**A08 — Data Integrity Failures:**
- Verify the audit log is truly append-only (no update/delete endpoints or queries)
- Verify vote tallies are computed from actual vote records, not stored separately (already the case)
- Verify Alembic migrations are tracked and reviewed

**A09 — Logging and Monitoring:**
- Verify all auth events are audit-logged (already implemented)
- Verify all state-changing actions are audit-logged (already implemented)
- Verify logs don't contain sensitive data (passwords, tokens, full email addresses)

**A10 — Server-Side Request Forgery:**
- Verify the application doesn't fetch user-supplied URLs
- If any URL fetching exists, validate against an allowlist

For each category, document: what was checked, what was found, what was fixed. Save to `SECURITY_REVIEW.md`.

### 2. Remaining UI Polish

**Loading states:** Every page and data-fetching component should show a skeleton or spinner while loading. Audit all pages systematically.

**Error states:** Every API call should handle errors gracefully:
- Network failure: "Unable to connect. Check your connection and try again."
- 401: redirect to login
- 403: "You don't have permission to do this."
- 404: "Not found."
- 422: show field-specific validation errors
- 500: "Something went wrong. Please try again."

**Empty states:** Appropriate messages when lists are empty:
- No proposals: "No proposals yet. [Create one] if you're an admin, or ask your org admin to get started."
- No delegations: "You haven't set up any delegations yet. [Browse public delegates] to get started."
- No members (admin view): "No members yet. [Invite members] to get started."
- No topics: "No topics configured. [Create topics] to enable delegation."

**Demo quick-switch login:** On the login page, when demo data is loaded (DEBUG=true), show a row of user avatars/names that log in with one click. This is for demo purposes only and should not appear in production.

**Mobile responsive final pass:**
- Test every page at 375px width
- Verify navigation hamburger menu works
- Verify vote buttons are full-width and easy to tap
- Verify delegation graph is usable on mobile
- Verify admin portal is usable on mobile (tables convert to cards)

### 3. Privacy Policy and Terms of Service

Create two pages accessible from the footer and registration flow:

**Privacy Policy** (`/privacy`):
- What data is collected (account info, votes, delegations, audit logs)
- How data is stored (encrypted at rest in PostgreSQL, encrypted in transit via HTTPS)
- Who can see your data (permission model: private by default, visible to approved followers and on public delegate topics)
- Data retention (how long data is kept)
- Data export (users can request a copy of their data)
- Data deletion (users can delete their account and all associated data)
- Third-party sharing (none — no analytics, no advertising, no data sales)
- Contact for privacy questions

**Terms of Service** (`/terms`):
- What the platform is and isn't (a tool for organizational decision-making, not a legally binding election system)
- User responsibilities (accurate identity, no manipulation, respect other members)
- Org admin responsibilities (fair governance, member rights)
- Platform availability (best-effort, no uptime guarantee for free/self-hosted instances)
- Open source license (MIT)

These should be written in plain language, not legalese. Keep them short — one page each. They're templates that org admins can customize.

### 4. README and Project Documentation

Update the project README.md to reflect the production-ready state:
- What the project is (one paragraph)
- Features list
- Screenshots (capture key pages)
- Quick start (Docker Compose)
- Deployment guide link
- Contributing guide
- License
- Links to documentation, privacy policy template, and security review

---

## Build Order

### Phase 4a: Deployment (2-3 days)
1. Create Dockerfiles for backend and frontend
2. Create docker-compose.yml with PostgreSQL
3. Migrate to PostgreSQL and test all functionality
4. Add health check endpoints
5. Configure production logging
6. Write DEPLOYMENT.md
7. Test: full docker-compose up from scratch, run backend tests against PostgreSQL

### Phase 4b: Auth Hardening (2-3 days)
1. Add email field to users model, migration
2. Email verification flow (model, endpoints, email sending, frontend)
3. Admin invitation system (model, endpoints, email, frontend join flow)
4. Password reset flow
5. Refresh token mechanism
6. Audit logging for new auth events
7. Test: full registration → verification → login flow, invitation → join flow, password reset flow

### Phase 4c: Admin Portal and Multi-Tenancy (5-7 days)
1. Organizations and memberships models, migration
2. Add org_id to proposals, topics, delegate_profiles
3. Org-scoped API middleware
4. Migrate all existing endpoints to be org-aware
5. Admin portal: org settings page
6. Admin portal: member management page
7. Admin portal: proposal management page
8. Admin portal: topic management page
9. Admin portal: analytics dashboard
10. Org selection UI and nav updates
11. First-run experience (setup wizard)
12. Update seed data to work within org context
13. Test: create org, invite member, member joins, create proposal, vote — full lifecycle within org context

### Phase 4d: Security and Polish (2-3 days)
1. OWASP security review (document findings in SECURITY_REVIEW.md)
2. Fix any security issues found
3. Loading/error/empty states audit
4. Demo quick-switch login (debug mode only)
5. Mobile responsive final pass
6. Privacy policy and terms of service pages
7. Update README and project documentation
8. Final full test suite run (backend unit tests + browser playbook)

---

## Browser Testing for Phase 4

### New Test Suites

**Suite E: Deployment and Auth (Phase 4a + 4b)**
- E1: Health check endpoint returns 200
- E2: Registration with email — verify email field is required, verification email is sent (check console log in dev mode)
- E3: Unverified user cannot vote — verify the restriction banner appears and vote buttons are disabled
- E4: Email verification — click verification link, verify banner disappears and voting is enabled
- E5: Password reset — request reset, use reset link, verify new password works
- E6: Admin invitation — send invitation, open invitation link, complete registration, verify org membership

**Suite F: Admin Portal (Phase 4c)**
- F1: Admin nav — verify admin menu appears for admin users, not for regular members
- F2: Org settings — change org name and verify it updates
- F3: Member management — view members list, change a member's role, verify the change
- F4: Invite member — send invitation, verify pending invitation appears in list
- F5: Approve join request — create pending request, approve as admin, verify member gains access
- F6: Proposal management — create proposal from admin, set custom voting window, advance through stages
- F7: Topic management — create, edit, and deactivate a topic
- F8: Analytics — verify analytics page loads with charts showing participation data
- F9: Org switcher — if user is in multiple orgs, verify switcher works

**Suite G: Security and Polish (Phase 4d)**
- G1: Access control — try accessing another org's proposals via URL manipulation, verify 403
- G2: Login error messages — verify "wrong password" and "user not found" show the same generic error
- G3: Seed endpoint disabled — verify /api/admin/seed returns 403 or 404 when DEBUG=false
- G4: Loading states — navigate to proposals page and verify a loading indicator appears before content
- G5: Error handling — stop the backend, try to load proposals in frontend, verify friendly error message
- G6: Privacy policy and terms — verify pages exist and are linked from registration and footer
- G7: Mobile — run core flow (login, view proposal, vote, check delegations) at 375px width
- G8: Full regression — re-run B2, B4, B5, C9, D1, D10

---

## What This Phase Does NOT Include

These are deferred to future phases based on real user feedback from the pilot:

- Native mobile app or PWA configuration (optional future enhancement)
- AI delegation support (on-device advisor or public AI delegates)
- Customizable delegation strategies (majority-of-delegates, weighted)
- WebSocket real-time updates (polling is adequate for pilot-scale)
- Advanced analytics (voting pattern analysis, delegate influence metrics)
- Multi-language support / internationalization
- Accessibility audit (WCAG compliance — important but scoped for a dedicated pass)
- Formal penetration testing (the OWASP self-review is sufficient for a pilot)
