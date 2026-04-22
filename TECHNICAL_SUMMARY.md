# Liquid Democracy Platform — Technical Summary

**For: New project manager agent onboarding**
**Date: April 2026**
**Source: PROGRESS.md, spec documents, codebase**

---

## What Exists

A pilot-ready liquid democracy web application. Users can vote directly on proposals or delegate their voting power to trusted people on specific topics, with instant revocability. The platform supports multi-tenant organizations, admin controls, interactive delegation graph visualizations, and Docker deployment.

**Stack**: Python 3.11+ / FastAPI / SQLAlchemy / PostgreSQL (SQLite for dev) / Alembic migrations / NetworkX — React 18 / Vite / Tailwind CSS / D3.js v7 / Recharts — Docker / nginx

**Test status**: 73 backend unit tests passing. 33 browser QA tests passing across Suites E-G. OWASP Top 10 security review completed (all pass).

**Repo**: `github.com/Zachrelius/liquid-democracy` on `master` branch.

---

## Build History by Phase

### Phase 1: Core Backend (spec: `liquid_democracy_claude_code_brief.md`)

The delegation engine and API foundation. Built by a single Claude Code instance.

**Delegation engine** (`backend/delegation_engine.py`): Two-layer architecture — a pure function layer (no DB access, fully testable) and a service layer (DB queries, builds context for pure functions). The pure layer resolves any user's vote on any proposal through:
1. Direct vote check (always overrides)
2. Topic precedence matching (user ranks topics; highest-precedence match wins)
3. Delegation chain resolution with configurable chain behavior per delegation:
   - `accept_sub` — if your delegate didn't vote, follow their delegate (opt-in transitivity)
   - `revert_direct` — you get notified to vote yourself
   - `abstain` — your vote is abstain

**Cycle detection**: Per-topic directed graphs via NetworkX. Checked before any delegation is created.

**Key models**: User, Topic, Proposal (with status lifecycle: draft → deliberation → voting → passed/failed), ProposalTopic (many-to-many with relevance weights), Delegation (per-topic + global fallback), TopicPrecedence (user-controlled priority ordering), Vote (tracks direct vs delegated, stores delegation chain), VoteSnapshot (time-series tally data), AuditLog (append-only).

**API routes**: Auth (register/login/me), Topics CRUD, Proposals CRUD with status advancement, Delegations (upsert/revoke/precedence), Votes (cast/retract with automatic delegation recalculation), Admin (seed data, time simulation for demos).

36 tests at phase end.

---

### Phase 2: Frontend MVP (spec: `phase2_frontend_spec.md`)

React SPA with three screens. Built by a single Claude Code instance.

- **Login/Register** with "Load Demo" button that seeds 20 users, 6 topics, 5 proposals with various delegation patterns
- **Proposals list** with status/topic filtering, vote summary bars
- **Proposal detail** with markdown body rendering, vote panel (cast/change/retract with delegation status display), results panel with live tally
- **My Delegations** with topic delegation table, drag-to-reorder topic precedence (DnD via `@hello-pangea/dnd`), delegate search modal

Frontend proxies API via Vite dev server config. No build step required for development.

---

### Phase 3a: Delegation Permissions Backend (spec: `phase3_spec.md`)

The permission and follow system that gates who can delegate to whom. Built by a single Claude Code instance.

**New models**:
- `DelegateProfile` — public delegate registration per topic (bio, active flag). Makes votes on that topic public; anyone can delegate without permission.
- `FollowRequest` — consent-gated flow with pending/approved/denied status and optional message.
- `FollowRelationship` — active relationship with `view_only` or `delegation_allowed` permission level.
- User gets `default_follow_policy` field: require_approval (default), auto_approve_view, auto_approve_delegate.

**Permission logic** (`backend/permissions.py`):
- `can_delegate_to()`: public delegate profile → yes; delegation_allowed follow → yes; else no.
- `can_see_votes()`: self → yes; public delegate topic → yes; any follow → yes; else hidden.

**Cascade revocation**: Revoking a follow relationship automatically revokes dependent delegations (unless independently covered by a public profile).

28 new tests (64 total at phase end).

---

### Phase 3b: Delegation Permissions Frontend (spec: `phase3b_spec.md`)

Frontend for the permission system plus a new backend feature. Built by a single Claude Code instance.

**Backend addition — Delegation intents** (`DelegationIntent` model): When you want to delegate to someone you don't follow, the system creates a follow request + a delegation intent in one action (`POST /api/delegations/request`). If the target approves with `delegation_allowed`, the intent auto-activates and creates the delegation. Intents expire after 30 days (lazy expiration on read). This is now the primary delegation endpoint for the frontend.

**Frontend components**:
- `DelegateModal.jsx` — permission-aware search results showing different UI per relationship state (public delegate → direct delegate button; following with permission → delegate button; view_only → request upgrade; not following → request follow + request delegate; pending → cancel)
- `FollowRequests.jsx` — incoming requests with Deny / Accept Follow / Accept Delegate buttons; outgoing requests labelled as "Follow request" vs "Delegation request"
- `UserProfile.jsx` — `/users/:id` page with public delegate section, permission-gated voting record, action buttons based on relationship
- `NotificationBadge.jsx` — nav badge with pending follow requests and unresolved votes count

9 new tests (73 total at phase end).

---

### Phase 3c: Delegation Graph Visualization (spec: `phase3c_spec.md`)

Interactive D3.js v7 force-directed graphs. Built by a single Claude Code instance.

**Proposal Vote Flow Graph** (`GET /api/proposals/{id}/vote-graph` + `VoteFlowGraph.jsx`):
- Shows every user's vote on a specific proposal as a force-directed network
- Yes voters cluster left (green zone), No voters cluster right (red zone), abstain/non-voters in bottom white zone
- Nodes sized proportional to vote weight (delegate carrying 10 votes is larger)
- Privacy: public delegates and followed users show real names; users who privately delegate to you show real names; everyone else is an anonymous blank circle
- Edges show delegation arrows colored by topic, with arrowheads positioned at target node border
- Non-voters hidden by default with toggle to show
- Hover highlights connected subgraph; click opens detail panel with "View Profile" link
- Zoom/pan with fit-to-content reset button
- Soft zone clamping: yes nodes stay left of center, no nodes stay right, abstain/non-voters stay in bottom zone

**Personal Delegation Network** (`GET /api/delegations/network` + `DelegationNetworkGraph.jsx`):
- Star/ego graph with current user at center
- Delegates (outgoing) on right, delegators (incoming) on left
- Edges colored by topic, labels stacked below nodes (deduplicated, max 2 + "+N more")
- Click panel with "Change delegate" / "Remove delegation" buttons for outgoing nodes, "View Profile" link for all

---

### Phase 3c Polish Fixes (spec: `phase3c_fixes.md`)

9 fixes from human review and QA. Built by a single Claude Code instance.

Key fixes: background zones changed to infinite half-planes, legend icons fixed, topic label stacking, action buttons on graph nodes, non-voter toggle, reset zoom to fit content, unicode rendering fixes, follow request type labelling, seed data message clarity.

**Post-fix polish** (from direct user feedback, same Claude Code instance):
- Soft zone clamping replaced hard clamping (which caused nodes to collapse into horizontal lines)
- Arrow tips always visible (edge lines shortened to target node circumference)
- Private delegator names visible (backend checks follow relationship with `delegation_allowed`)
- Anonymous "Voter #N" labels removed (blank circles for anonymous nodes)
- Toggle button text fixed

---

### Phase 3 Cleanup (spec: `phase3_cleanup.md`)

Navigation gaps and missing features. Built by the same Claude Code instance.

- **`UserLink.jsx`** — reusable component deployed in 6 locations (vote panel, graph detail panels, delegation table, delegate modal, follow requests)
- **Settings page** (`/settings`) — profile editing, follow policy radio buttons, public delegate registration/edit/step-down per topic, change password. New endpoints: `PATCH /api/auth/me`, `POST /api/auth/change-password`
- **Profile page completed** — own profile shows "Edit settings" link; public view has delegate badges, bios, permission-gated voting record
- **Nav updated** — "My Profile" + "Settings" + "Sign out" in user dropdown

---

### Phase 4a: Deployment Infrastructure (spec: `phase4_spec.md`)

Docker containerization and production readiness. **Built by a multi-agent team (manager + dev + QA), not by the instance that built Phases 2-3.**

- Backend Dockerfile (Python 3.11-slim, healthcheck, Alembic migrations on startup)
- Frontend Dockerfile (two-stage: Node build → nginx serve with SPA fallback and API proxy)
- Docker Compose with PostgreSQL 16, backend, frontend
- Health endpoints: `/api/health` and `/api/health/ready` (DB connectivity check)
- PostgreSQL support alongside SQLite (conditional connection params)
- Structured JSON production logging with request IDs (`X-Request-ID` header)
- `DEPLOYMENT.md` covering Docker Compose, Railway, Fly.io, VPS, HTTPS, backup/restore

7 QA tests passed (Suite E partial).

---

### Phase 4b: Authentication Hardening (spec: `phase4_spec.md`)

**Built by the multi-agent team.**

- Email field on users (unique, required for new registrations)
- Email verification flow: `EmailVerification` model, token-based, 24h expiry, unverified users blocked from voting/delegating, yellow banner with resend link
- Password reset flow: `PasswordReset` model, token-based, 1h expiry, rate-limited, anti-enumeration (same response for valid/invalid emails)
- Refresh token mechanism: `RefreshToken` model, 7-day expiry, rotation on refresh, access tokens shortened to 15 minutes, auto-refresh in frontend
- `POST /api/auth/logout` (single token) and `POST /api/auth/logout-all` (revoke all sessions)
- Frontend pages: VerifyEmail, ForgotPassword, ResetPassword, EmailVerificationBanner
- Login page updated with email field in registration and "Forgot password?" link

9 QA tests passed (Suite E).

---

### Phase 4c: Admin Portal and Multi-Tenancy (spec: `phase4_spec.md`)

**Built by the multi-agent team.**

**New models**:
- `Organization` — name, slug, description, join_policy (invite_only/approval_required/open), JSON settings (voting defaults)
- `OrgMembership` — user-org link with role (member/moderator/admin/owner) and status
- `Invitation` — email invitations with 7-day token expiry
- `DelegateApplication` — admin-reviewed applications to become public delegate
- `org_id` foreign keys added to Topic, Proposal, DelegateProfile

**29 org-scoped API endpoints** in `routes/organizations.py`: CRUD, member management, join flow, invitations (bulk create), delegate applications (approve/deny with feedback), org-scoped topics/proposals, analytics.

**6 admin pages**: OrgSettings, Members (with invite/suspend/role editing), ProposalManagement (create + advance), Topics (CRUD with color picker), DelegateApplications (approve/deny), Analytics (Recharts dashboard).

**Org context**: `OrgContext.jsx` manages current org, auto-selects for single-org users, shows selector for multi-org. Nav shows org name and admin dropdown.

**First-run wizard**: `SetupWizard.jsx` — 4-step flow (create org → create topics → invite members → done). First registered user auto-verified and gets admin.

**Production guards**: Seed and time simulation endpoints return 403 when `DEBUG=false`.

9 QA tests passed (Suite F).

---

### Phase 4d: Security Review and Final Polish (spec: `phase4_spec.md`)

**Built by the multi-agent team.**

- OWASP Top 10 audit (all 10 categories pass, documented in `SECURITY_REVIEW.md`)
- `Spinner.jsx` and `ErrorMessage.jsx` reusable components deployed across all pages
- Demo quick-switch login (debug-only `GET /api/auth/demo-users` with clickable user cards)
- Privacy Policy and Terms of Service pages (`/privacy`, `/terms`)
- Mobile responsive nav (hamburger menu, slide-down navigation)
- Empty states with contextual messages throughout

8 QA tests passed (Suite G).

---

## Current Architecture Summary

### Backend File Structure
```
backend/
  main.py              — FastAPI app, middleware, startup
  delegation_engine.py — Pure + service layer vote resolution
  permissions.py       — can_delegate_to(), can_see_votes()
  auth.py              — JWT, password hashing
  email_service.py     — SMTP email sending (dev: console output)
  org_middleware.py     — Org-scoped dependency functions
  audit_utils.py       — log_audit_event() helper
  models.py            — All SQLAlchemy models
  schemas.py           — All Pydantic request/response schemas
  seed_data.py         — Demo scenario with 20 users, 6 topics, 5 proposals
  settings.py          — Pydantic settings from env vars
  database.py          — Engine, session, create_tables
  routes/
    auth.py            — Register, login, refresh, verify email, reset password
    proposals.py       — CRUD, advance, results, my-vote, vote-graph
    delegations.py     — CRUD, precedence, intents, graph, network
    votes.py           — Cast, retract
    users.py           — Search, profile, votes
    delegates.py       — Public delegate register/browse
    follows.py         — Request, respond, following/followers, revoke
    admin.py           — Seed, time simulation, audit log
    organizations.py   — 29 org-scoped endpoints
    topics.py          — CRUD
  migrations/          — Alembic versions (6 migrations)
  tests/               — 73 tests across 3 files
```

### Frontend File Structure
```
frontend/src/
  App.jsx              — Routes (28 routes including admin)
  AuthContext.jsx       — JWT + refresh token management
  OrgContext.jsx        — Current org state management
  api.js               — Fetch wrapper with auto-refresh
  components/
    Nav.jsx            — Responsive nav with admin dropdown
    VoteFlowGraph.jsx  — D3 proposal vote network
    DelegationNetworkGraph.jsx — D3 personal delegation star graph
    DelegateModal.jsx  — Permission-aware delegate search
    FollowRequests.jsx — Incoming/outgoing request cards
    NotificationBadge.jsx — Nav notification dropdown
    UserLink.jsx       — Clickable user name link
    TopicBadge.jsx, StatusBadge.jsx, VoteBar.jsx
    Spinner.jsx, ErrorMessage.jsx, EmailVerificationBanner.jsx
  pages/
    Login.jsx, Proposals.jsx, ProposalDetail.jsx
    Delegations.jsx, UserProfile.jsx, Settings.jsx
    VerifyEmail.jsx, ForgotPassword.jsx, ResetPassword.jsx
    OrgSelector.jsx, CreateOrg.jsx, SetupWizard.jsx
    Privacy.jsx, Terms.jsx
    admin/ — OrgSettings, Members, ProposalManagement, Topics, DelegateApplications, Analytics
```

### Key API Endpoints (selected)

| Endpoint | Purpose |
|----------|---------|
| `POST /api/delegations/request` | Smart delegation (direct or intent+follow) |
| `GET /api/proposals/{id}/vote-graph` | Privacy-aware vote network for D3 |
| `GET /api/delegations/network` | Personal delegation star graph |
| `PATCH /api/auth/me` | Update display name / follow policy |
| `POST /api/auth/refresh` | Rotate access + refresh tokens |
| `POST /api/auth/verify-email` | Email verification |
| `POST /api/auth/reset-password` | Password reset |
| `GET /api/orgs/{slug}/...` | All org-scoped endpoints |
| `GET /api/health/ready` | DB connectivity check |

### Database Models (17 tables)

User, Organization, OrgMembership, Topic, Proposal, ProposalTopic, Delegation, TopicPrecedence, Vote, VoteSnapshot, AuditLog, DelegateProfile, DelegateApplication, FollowRequest, FollowRelationship, DelegationIntent, EmailVerification, PasswordReset, RefreshToken, Invitation

---

## What's NOT Built Yet

From `future_improvements_roadmap.md` and design discussions:

**Tier 1 (high impact, near-term)**:
- Polis integration for structured deliberation (the biggest missing piece — voting without deliberation is just polling)
- Sustained-majority voting windows (proposals must maintain support throughout a week, not just pass at one moment)
- Delegation analytics dashboard for individual users (how often your delegate votes, alignment score)
- Real-time updates via WebSocket (currently static page loads)

**Tier 2 (important, medium-term)**:
- AI voting agents (data model supports it via `user_type` field; needs confirmation model, public rationale, no AI-to-AI chains)
- Proposal amendment workflow (community can propose amendments during deliberation)
- Graduated security tiers (digital for routine, mail-in for major, in-person for constitutional)
- Mobile native app

**Tier 3 (future)**:
- Federation between instances
- E2E verifiable voting (for high-stakes tier)
- Integration with government systems
- Accessibility audit (WCAG compliance)

---

## Known Technical Debt

- Tests only cover the delegation engine and permissions — no API integration tests, no frontend tests
- SQLite used for tests; PostgreSQL not tested in CI
- No CI/CD pipeline configured
- Alembic migrations may need consolidation (6 migrations for what could be 1-2)
- Some frontend components import patterns that evolved organically (e.g., OrgContext added later, wraps most but not all routes)
- The `email_service.py` just prints to console in dev mode — no actual SMTP tested
- No rate limiting on most endpoints (only auth endpoints have slowapi)
- WebSocket endpoint exists but isn't used by any frontend component

---

## Development Notes for New Agents

- **Always read `PROGRESS.md` first** — it's the authoritative state of the project
- **Run `cd backend && python -m pytest tests/ -v` to verify** before and after changes
- **Frontend build**: `cd frontend && npm run build` — catches import errors and type issues
- **Server**: `cd backend && python -m uvicorn main:app --port 8000` (needs `.venv` with Python 3.12)
- **Demo data**: `POST /api/admin/seed` with `{"scenario":"healthcare"}` — creates 20 users (password: `demo1234`), suggested login: `alice`
- **The user (Z) is non-technical** — always run terminal commands directly, never ask Z to run things
- **Spec-driven development** — the planning agent produces detailed specs, dev agents execute them
- **Update PROGRESS.md at session end** with what was built, design decisions, and test results
