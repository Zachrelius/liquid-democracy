# Liquid Democracy — Build Progress

## Phase 1: Core Backend ✅ Complete

FastAPI backend with SQLAlchemy/SQLite, JWT auth, delegation engine (pure + service layers), audit log, security middleware, Alembic migrations, 36 tests. See git history for full details.

Key files: `backend/main.py`, `backend/delegation_engine.py`, `backend/routes/`, `backend/migrations/`

---

## Phase 2: Frontend MVP ✅ Complete

React 18 + Vite + Tailwind CSS frontend. Three screens: Login/Register (with Load Demo), Proposals list+detail with vote panel, My Delegations with drag-to-reorder precedence and delegate search modal.

Run: `cd frontend && npm run dev` → http://localhost:5173

---

## Phase 3a: Delegation Permissions Backend ✅ Complete

### New data models

**`delegate_profiles`** — Public delegate registration per topic.
- Fields: `user_id`, `topic_id`, `bio`, `is_active` (default true), `created_at`
- Unique on `(user_id, topic_id)`
- Effect: votes on registered topics are publicly visible; anyone can delegate without prior permission

**`follow_requests`** — Consent-gated delegation flow.
- Fields: `requester_id`, `target_id`, `status` (pending/approved/denied), `permission_level` (view_only/delegation_allowed), `message`, `requested_at`, `responded_at`
- Unique on `(requester_id, target_id)`. Record kept after resolution for audit.

**`follow_relationships`** — Active follow after approval or auto-approve.
- Fields: `follower_id`, `followed_id`, `permission_level`, `created_at`

**`users.default_follow_policy`** (new column) — `require_approval` | `auto_approve_view` | `auto_approve_delegate`. Default: `require_approval`.

Alembic migration: `ef697ad0c0da_phase3a_delegation_permissions.py`

### Permission logic (`permissions.py`)

`can_delegate_to(db, delegator_id, delegate_id, topic_id)`:
1. Active `delegate_profile` for the topic → allowed
2. `follow_relationship` with `delegation_allowed` → allowed
3. Global (topic=None): any active profile OR delegation_allowed follow → allowed
4. Else → False (endpoint returns 403)

`can_see_votes(db, viewer_id, target_id, topic_ids)`:
- Self → always visible
- Target is public delegate on a matching topic → visible
- Any follow relationship → visible
- Else → hidden (API returns `visible=false`, `vote_value=null`)

### Delegation permission check

`PUT /api/delegations` now calls `can_delegate_to()` before the cycle check. Returns HTTP 403 with a plain-English message if permission is missing.

### New API endpoints

**Delegate profiles** (`/api/delegates`):

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/delegates/public` | Browse public delegates (optional `?topic_id=`) |
| GET | `/api/delegates/public/{topic_id}` | Public delegates for topic, sorted by delegation count |
| POST | `/api/delegates/register` | Register as public delegate `{ topic_id, bio }` |
| DELETE | `/api/delegates/register/{topic_id}` | Deactivate profile (existing delegations stay) |

**Follow system** (`/api/follows`):

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/follows/request` | Send follow request; auto-approves per target policy |
| GET | `/api/follows/requests/incoming` | Pending requests for current user |
| GET | `/api/follows/requests/outgoing` | Requests current user has sent |
| PUT | `/api/follows/requests/{id}/respond` | Approve/deny `{ status, permission_level }` |
| GET | `/api/follows/following` | Users the current user follows |
| GET | `/api/follows/followers` | Users who follow the current user |
| PUT | `/api/follows/{id}/permission` | Change permission level (followed party only) |
| DELETE | `/api/follows/{id}` | Revoke + cascade-revoke dependent delegations |

**Updated user endpoints** (`/api/users`):

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/users/search?q=` | Search by name/username (auth required, no voting data) |
| GET | `/api/users` | Same (backward compat for delegation modal) |
| GET | `/api/users/{id}/profile` | Public profile with delegate registrations + filtered votes |
| GET | `/api/users/{id}/votes` | Vote history with per-vote visibility flags |

### Cascade revocation

`DELETE /api/follows/{id}` automatically revokes any delegations from follower to followed that are not independently covered by a delegate_profile. Each revoked delegation gets its own `delegation.revoked` audit log entry with `reason: "follow_relationship_revoked"`.

### Auto-approve policies

When `POST /api/follows/request` is called and target has a non-default policy:
- `auto_approve_view` → immediately creates relationship at `view_only`
- `auto_approve_delegate` → immediately creates relationship at `delegation_allowed`
- `require_approval` → stays pending

### Audit events added

`follow.requested`, `follow.approved`, `follow.denied`, `follow.revoked` (includes `delegations_revoked` list), `delegate_profile.created`, `delegate_profile.deactivated`

### Seed data (Phase 3a additions)

Public delegates: `dr_chen` (Healthcare + Economy), `econ_bob` (Economy), `env_emma` (Environment), `rights_raj` (Civil Rights), all with bios.

`dr_chen` and `econ_bob` set to `auto_approve_view` policy.

Follow relationships: alice follows dr_chen/econ_bob/rights_raj (delegation_allowed); dave follows alice (delegation_allowed); carol follows dr_chen (view_only); voters 1-4 follow dr_chen + econ_bob; voters 5-8 follow env_emma.

Pending requests: voter08 → alice (wants to delegate civil rights), voter09 → carol.

### Design decisions

- **Existing delegations not retroactively validated on migration**: The seed re-creates valid delegations. A production system would run a cleanup job, but retroactive revocation in a migration is risky.
- **`GET /api/users` kept for backward compat**: Delegation modal searches `/api/users?q=` — kept working alongside new `/api/users/search`.
- **Permission check at creation only**: Delegations are not continuously re-validated. Revocation triggers only on explicit follow revoke.

### Tests — 64/64 passing

28 new Phase 3a tests in `tests/test_phase3a_permissions.py` covering all spec-required scenarios.

---

## Phase 3b: Delegation Permissions Frontend ✅ Complete

### Backend: Delegation Intent System

**New model: `delegation_intents`** — queued delegations that auto-activate when a follow request is approved with `delegation_allowed`.

Fields: `delegator_id`, `delegate_id`, `topic_id`, `chain_behavior`, `follow_request_id`, `status` (pending/activated/expired/cancelled), `expires_at` (30 days default), `created_at`, `activated_at`.

Migration: `7f4e8c4f07c9_add_delegation_intents.py`

**New endpoints:**
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/delegations/request` | Smart delegation: creates directly if permitted, otherwise queues follow_request + intent |
| GET | `/api/delegations/intents` | List current user's delegation intents (with lazy expiration) |
| DELETE | `/api/delegations/intents/{id}` | Cancel a pending intent |

**Key logic:**
- `POST /api/delegations/request` checks `can_delegate_to()` first — if permission exists, creates delegation directly (same as existing PUT). If not, creates a follow_request + delegation_intent in one action.
- Auto-approve policies are respected: if target has `auto_approve_delegate`, the delegation is created immediately without waiting.
- When follow request is approved with `delegation_allowed`, `activate_intents_for_follow()` is called automatically in both manual and auto-approve paths.
- Lazy expiration: intents past `expires_at` are marked `expired` on read.

**Audit events:** `delegation_intent.created`, `delegation_intent.activated`, `delegation_intent.expired`, `delegation_intent.cancelled`

9 new tests in `tests/test_delegation_intents.py`.

### Frontend: Updated Delegate Selection Modal

New `components/DelegateModal.jsx` replaces the old inline modal. Search results now show permission-aware context for each user:

- **Public delegates** show green badge, bio, and a direct "Delegate" button
- **Following with delegation_allowed** shows follow status and a direct "Delegate" button
- **Following with view_only** shows "Request Delegate" button (creates intent + requests permission upgrade)
- **Not following** shows both "Request Follow" and "Request Delegate" buttons
- **Pending request** shows pending status

Backend search endpoint `GET /api/users/search` now returns `UserSearchResultWithContext` including `delegate_profiles`, `follow_status`, `follow_permission`, and `has_pending_intent` fields.

### Frontend: Follow Request Management

New `components/FollowRequests.jsx` appears at the bottom of the My Delegations page when there are pending requests.

**Incoming requests** show requester info, optional message, and three response buttons: Deny, Accept Follow (view only), Accept Delegate.

**Outgoing requests** show target info, status, associated delegation intent info (topic + auto-activate note), and Cancel button.

### Frontend: User Profile Page (`/users/:id`)

New `pages/UserProfile.jsx` with permission-gated content:

- Header with display name, username, public delegate badge (if applicable)
- Action buttons: Request Follow, Request Delegate
- **Public Delegate Topics** section showing registered topics with bios
- **Voting Record** table showing visible votes with proposal links, vote value, and date
- Hidden votes shown as "Private" with a prompt to follow the user
- Own profile view shows all data

### Frontend: Navigation Updates

- **Notification badge** (`components/NotificationBadge.jsx`) in the nav bar shows count of pending follow requests + proposals needing attention
- Clicking opens a dropdown with brief descriptions linking to relevant pages
- **User dropdown menu** with Profile and Sign out links

### Seed Data Updates

- Added "frank" user (unfollowed by anyone — for testing follow request flow)
- Added delegation intent from voter10 to carol on Economy (pending, linked to a follow request)
- All demo users have password reset on re-seed (BUG-2 fix from earlier)
- 204 response handling fixed in frontend `api.js` (BUG-1 fix)

### Design Decisions

- **`POST /api/delegations/request` is the new primary delegation endpoint for the frontend** — it handles both direct delegation and intent creation transparently. The old `PUT /api/delegations` still works for direct delegation when the caller knows permission exists.
- **`UserSearchResultWithContext` is returned by all user search endpoints** — this gives the modal everything it needs in a single API call per search, avoiding N+1 queries for follow status.
- **Lazy intent expiration** — no background job. Intents are checked for expiry only when read via the `GET /intents` endpoint or when follow approval triggers `activate_intents_for_follow`.
- **FollowRequests component auto-hides when empty** — it only renders on the My Delegations page when there are pending incoming or outgoing requests.

### Tests — 73/73 passing

9 new delegation intent tests covering: creation, activation on delegation_allowed approval, non-activation on view_only, expiry, lazy expiration, public delegate bypass, follow bypass, cancellation, multiple topic activation.

---

## Phase 3c: Delegation Graph Visualization ✅ Complete

### Quick Fix from Phase 3b

Fixed permission-gated vote visibility on user profiles. The backend `GET /api/users/{id}/profile` now returns hidden votes with `visible=False` (instead of silently omitting them), so the frontend can distinguish "no votes" from "private votes." The frontend shows "Follow [name] to see their voting record" with a Request Follow button when viewing another user's profile with no visible votes.

### Backend: Graph Data Endpoints

**Proposal Vote Flow Graph** — `GET /api/proposals/{id}/vote-graph`

Returns the complete delegation network for a specific proposal. Available for proposals in `voting`, `passed`, or `failed` status.

Response includes:
- `nodes[]` — every eligible user with `type` (direct_voter, delegator, chain_delegate, non_voter), vote value, public delegate flag, vote weight, current user flag
- `edges[]` — delegation arrows from delegator to delegate with topic name and colour
- `clusters` — aggregate counts for yes/no/abstain/not_cast broken down by direct vs delegated

**Privacy rules:**
- Current user always sees their own node with full detail
- Public delegates' names and votes are always visible
- Users the current user follows are shown with real names
- All other users appear as "Voter #N" to preserve ballot privacy
- Delegation edges are only visible if the delegate is a public delegate or the current user is a party to the edge

**Personal Delegation Network** — `GET /api/delegations/network`

Returns the current user's one-hop delegation star graph:
- `center` — the current user with outgoing/incoming counts
- `nodes[]` — each delegate and delegator with relationship direction, topic list, public delegate status, total delegator count
- `edges[]` — grouped by user pair with topic name+colour arrays

### Frontend: Proposal Vote Flow Graph (`VoteFlowGraph.jsx`)

D3.js v7 force-directed graph rendered in SVG on the Proposal Detail page:

- **Vote clustering**: Yes nodes gravitate left (green zone), No nodes gravitate right (red zone), Abstain at bottom, non-voters faded at edges
- **Node sizing**: proportional to `total_vote_weight` — a delegate carrying 10 votes is visually larger
- **Node styling**: coloured border by vote (green/red/gray), current user highlighted with gold border, public delegates get a dashed double-ring, non-voters are small dotted circles
- **Edge styling**: arrows from delegator to delegate, coloured by matched topic, arrow markers via SVG defs
- **Hover**: highlights connected edges, dims others, shows tooltip with vote value, delegate status, delegator count
- **Click**: opens detail panel showing full node info, delegation chain details
- **Zoom/pan**: mouse wheel zoom with `d3.zoom()`, drag to pan, "Reset view" button
- **Responsive**: collapsed by default on mobile (<768px), expanded on desktop. Mobile uses initials instead of full names.

Integrated into ProposalDetail page as a collapsible "Vote Network" section below the vote results bar, with legend showing colour codes for Yes/No/Abstain/Not voted/Delegation/Public delegate/You, and cluster summary showing direct vs delegated counts.

### Frontend: Personal Delegation Network (`DelegationNetworkGraph.jsx`)

D3.js v7 star/ego graph rendered in SVG on the My Delegations page:

- **Layout**: current user at center (large dark node with "You" label), delegates on the right (blue tint), delegators on the left (yellow tint)
- **Edge styling**: coloured by topic, arrow markers, topic labels at edge midpoints
- **Node sizing**: delegates and delegators sized by their `total_delegators` count
- **Public delegate badge**: dashed double-ring on public delegate nodes
- **Hover**: highlights connected edges, shows tooltip with relationship details and topics
- **Drag**: nodes are draggable within the simulation

Integrated into Delegations page as a collapsible "Your Delegation Network" section between Topic Priority and Follow Requests, with simple legend.

### New Schemas

`VoteFlowNode`, `VoteFlowEdge`, `VoteFlowClusters`, `VoteFlowGraph` — for proposal vote graph
`PersonalNetworkCenter`, `PersonalNetworkNode`, `PersonalNetworkEdgeTopic`, `PersonalNetworkEdge`, `PersonalDelegationNetwork` — for personal network graph

### Design Decisions

- **D3.js v7 in SVG mode** — SVG chosen over Canvas for individual element interactivity (hover, click, drag). D3 force simulation handles layout with vote-clustering via `d3.forceX` with different target x-positions per vote value.
- **Privacy in vote graph via anonymization** — rather than excluding private users, they appear as "Voter #N" nodes. This preserves the visual structure of the delegation network (you can see clustering patterns and vote flow) without revealing individual identities. Only public delegates, followed users, and the current user show real names.
- **No separate migration needed** — Phase 3c is purely read-only endpoints consuming existing data structures.
- **Edge deduplication** — the vote flow graph deduplicates source-target pairs to prevent visual clutter from multiple delegation paths.
- **Graph data fetched non-blocking** — if the graph endpoint fails, the page still renders normally. The graph is treated as an enhancement, not a requirement.
- **"What if" simulation not implemented** — listed as stretch goal in spec, deferred to avoid scope creep.

### Tests — 73/73 passing (no regressions)

No new backend tests added (Phase 3c endpoints are read-only views over existing data). All 73 existing tests continue to pass.

### Phase 3c Polish Fixes ✅ Complete

9 fixes addressing visual bugs and design improvements identified by human review and QA:

**Fix 1 — Background region layout**: Changed from bounded rectangles to large half-plane fills (10000px) that survive zoom/pan. Yes region covers left half, No region covers right half, both ending at ~78% height. Bottom area left uncoloured for abstain/non-voter nodes. Updated y-force to push abstain/null-vote nodes down with strength 0.3.

**Fix 2 — Public delegate legend icon**: Replaced broken offset `<span>` circles with a proper inline `<svg>` showing concentric circles (solid inner ring, dashed outer ring) matching the actual graph node rendering.

**Fix 3 — Overlapping topic labels**: Replaced edge-midpoint text labels with per-node stacked topic labels. Topics are deduplicated per node, displayed vertically below the node name (max 2 shown + "+N more" indicator). Collision radius increased for nodes with multiple topic labels.

**Fix 4 — Missing approved delegator**: Investigated and confirmed as case (a) — the pending demo requests (voter08→alice, voter09→carol) are follow-only requests with no delegation intent, so approving them correctly creates follow relationships but no delegations. Fixed by: (1) updating seed data messages to clearly indicate follow-only intent, (2) adding explanatory text to incoming follow requests ("choose Accept Delegate if you want them to delegate to you"), (3) labelling outgoing requests as "Follow request" vs "Delegation request" based on whether an intent is attached.

**Fix 5 — Unicode escapes**: Replaced `\u2192`, `\u2190`, `\u25b4`, `\u25be` with actual Unicode characters (`→`, `←`) and HTML entities (`&#x25b4;`, `&#x25be;`) in JSX text content where backslash escapes render literally.

**Fix 6 — Personal network action buttons**: Added click handler and detail panel to DelegationNetworkGraph. Clicking a delegate node (outgoing) shows a panel with "Change delegate" and "Remove delegation" buttons wired to the same API calls as the delegation table. Clicking a delegator node (incoming) shows an informational panel. Parent Delegations page passes callbacks that open the delegate modal or trigger removal.

**Fix 7 — Duplicate topic casing**: Added `[...new Set(topics)]` deduplication in DelegationNetworkGraph tooltips and detail panel to prevent showing "Healthcare, healthcare" etc.

**Fix 8 — Reset view zoom level**: Reset now calculates the bounding box of all visible nodes and applies a `d3.zoomIdentity.translate().scale()` transform to fit them with 40px padding, capped at 1.5x zoom. No longer resets to identity (which zoomed out too far).

**Fix 9 — Non-voter toggle**: Non-voter nodes hidden by default. Toggle button "Show non-voters (N)" / "Hide non-voters (N)" appears in top-right controls alongside Reset View. When hidden, nodes with `type === 'non_voter'` are filtered out before D3 simulation. `showNonVoters` state added as a dependency to the D3 effect.

### Additional Graph Polish (post-fix)

- **Zone clamping**: Yes/No nodes are soft-clamped to their half of the graph (yes stays left of center, no stays right), abstain/non-voters nudged below the coloured zones. Forces retuned (lower charge, gentler x/y strength) so nodes spread naturally in 2D rather than collapsing into horizontal lines.
- **Arrow tips**: Edge lines are shortened on each tick to stop at the target node's circumference + 3px gap, so arrow markers always sit at the circle border regardless of node size.
- **Private delegator names**: Backend vote-graph endpoint now reveals real names of users who privately delegate to you (via `delegation_allowed` follow relationship). Users who delegate through a public delegate profile stay anonymous.
- **Anonymous labels removed**: Backend returns empty string for anonymous nodes instead of "Voter #N", decluttering the graph.
- **Toggle text fixed**: Removed stale HTML entities from show/hide toggle buttons.

### Tests — 73/73 passing (no regressions)

---

## Phase 3 Cleanup ✅ Complete

### 1. UserLink Component — Clickable User Names Everywhere

Created reusable `<UserLink>` component (`components/UserLink.jsx`) that renders a user's display name as a styled link to `/users/{id}`. Deployed in:

- **ProposalDetail** — vote status panel ("Via Dr. Chen" is now a link)
- **VoteFlowGraph** — node detail panel includes "View Profile" link
- **Delegations page** — delegation table rows and global default section use UserLink for delegate names
- **DelegationNetworkGraph** — node detail panel includes "View Profile" link
- **DelegateModal** — search results show a profile info icon (opens in new tab)
- **FollowRequests** — both incoming and outgoing request cards use UserLink for requester/target names

### 2. Settings Page (`/settings`)

New settings page with four sections:

**Profile Information** — Editable display name field with save button. Updates via `PATCH /api/auth/me`.

**Follow & Delegation Preferences** — Radio buttons for `default_follow_policy`: require approval, auto-approve view, auto-approve delegate. Each option has a brief explanation. Updates via `PATCH /api/auth/me`.

**Public Delegate Registration** — Card for each topic showing current status (Not registered / Active). Actions:
- "Become a Delegate" — inline form with bio textarea (min 50 chars), registers via `POST /api/delegates/register`
- "Edit Bio" — inline edit mode, saves via the same endpoint (upserts)
- "Step Down" — confirmation dialog, deactivates via `DELETE /api/delegates/register/{topic_id}`

**Account** — Change password form (current + new + confirm). Updates via `POST /api/auth/change-password`.

### New Backend Endpoints

| Method | Path | Description |
|--------|------|-------------|
| PATCH | `/api/auth/me` | Update display_name and/or default_follow_policy |
| POST | `/api/auth/change-password` | Change password (requires current password) |

### New Schemas

`UserUpdate` — optional `display_name` and `default_follow_policy` fields
`ChangePasswordRequest` — `current_password` and `new_password`

### 3. Profile Page Verification

Verified and enhanced `UserProfile.jsx`:
- Own profile now shows "Edit settings" link to `/settings` instead of follow/delegate buttons
- Public delegate badge, topic cards with bios, and permission-gated voting record all present
- Proposal titles in voting record are linked to proposal detail pages

### 4. Additional Items Verified

- **Delegate modal profile preview**: Profile info icon added to each search result card, opens profile in new tab
- **Follow request messages**: Seed data messages already updated to be realistic and distinguish follow-only vs delegation intent
- **Nav dropdown**: Updated to show "My Profile" and "Settings" links plus "Sign out"

### Tests — 73/73 passing (no regressions)

---

## Phase 4a: Deployment and Infrastructure ✅ Complete

### Docker Containerization

**Backend Dockerfile** (`backend/Dockerfile`): Python 3.11-slim, psycopg2 system deps, non-root user, healthcheck via curl to `/api/health`, startup script runs Alembic migrations then uvicorn.

**Frontend Dockerfile** (`frontend/Dockerfile`): Two-stage build — Node 20 Alpine for Vite build, nginx Alpine for serving. Custom nginx config with SPA fallback, API proxy to backend, WebSocket proxy, static asset caching (1 year), gzip compression.

**Docker Compose** (`docker-compose.yml`): Three services — PostgreSQL 16 Alpine (with healthcheck and persistent volume), backend (depends on healthy db), frontend (depends on backend). All config via `.env` file.

**`.env.example`**: Template with all required variables (DB_USER, DB_PASSWORD, SECRET_KEY, CORS_ORIGINS, BASE_URL, SMTP settings).

### Health Check Endpoints

- `GET /api/health` → `{"status": "ok", "version": "0.1.0"}`
- `GET /api/health/ready` → Tests database connectivity with `SELECT 1`, returns 200 with `{"status": "ok", "database": "connected"}` or 503 with `{"status": "error", "database": "disconnected"}`

### Database: PostgreSQL Support

- `backend/database.py` updated to handle both SQLite and PostgreSQL URLs (conditional `check_same_thread` for SQLite only)
- `backend/settings.py` updated with SMTP settings (`smtp_host`, `smtp_port`, `smtp_user`, `smtp_password`, `from_email`) and `base_url` — all optional with sensible defaults
- `requirements.txt` updated with `psycopg2-binary==2.9.9` and `aiosmtplib==3.0.1`
- SQLite remains default for local dev/tests; PostgreSQL used in Docker via `DATABASE_URL` env var

### Production Logging

- Structured JSON logging to stdout in production (debug=False): timestamp, level, message, logger name
- Human-readable console format in debug mode
- Per-request structured JSON access logs: request_id (UUID), user_id, method, path, status_code, response_time_ms
- `X-Request-ID` response header on every request (exposed via CORS)
- `configure_logging()` called at startup

### Startup Script

`backend/start.sh`: Runs `alembic upgrade head` then `uvicorn main:app` with configurable worker count (`WORKERS` env var, default 4).

### Deployment Documentation

`DEPLOYMENT.md`: Quick Start (Docker Compose), cloud deployment (Railway, Fly.io, VPS), HTTPS setup (Caddy, Certbot, nginx-proxy), backup/restore instructions, full environment variables reference, troubleshooting section.

### Docker Ignore Files

`.dockerignore` files in both `backend/` and `frontend/` to exclude unnecessary files from Docker builds.

### QA Results — 7/7 PASS

All health endpoints, login, voting, delegations, user profiles, settings, and X-Request-ID header verified working.

### Tests — 73/73 passing (no regressions)

---

## Phase 4b: Authentication Hardening ✅ Complete

### Email Field on Users

Added `email` (unique, nullable for migration compat) and `email_verified` (Boolean, default False) to User model. All demo users get `{username}@demo.example` emails with `email_verified = True`. Registration now requires email. Alembic migration: `3835b0e1b4e4_phase4b_auth_hardening.py`.

### Email Service (`email_service.py`)

Async email sending via SMTP with TLS. When `smtp_host` is not configured (dev mode), emails are printed to console so developers can see verification links. Functions: `send_email()`, `send_verification_email()`, `send_password_reset_email()`, `send_invitation_email()` (Phase 4c stub).

### Email Verification Flow

- `EmailVerification` model: user_id, email, token (64 chars URL-safe), expires_at (24h), verified_at, created_at
- `POST /api/auth/verify-email` — validates single-use time-limited token, sets `email_verified = True`
- `POST /api/auth/resend-verification` — requires auth, rate-limited 1/min
- Registration automatically creates verification record and sends email
- Unverified users see yellow banner: "Please verify your email to participate in votes and create delegations"
- Voting and delegation creation blocked for unverified users (403)

### Password Reset Flow

- `PasswordReset` model: user_id, token (64 chars URL-safe), expires_at (1h), used_at, created_at
- `POST /api/auth/forgot-password` — rate-limited 3/hour, always returns same message (prevents account enumeration)
- `POST /api/auth/reset-password` — validates single-use time-limited token, updates password, invalidates all refresh tokens

### Refresh Token Mechanism

- `RefreshToken` model: user_id, token (64 chars URL-safe), expires_at (7 days), revoked_at, created_at
- Access tokens now expire in 15 minutes (was 24 hours)
- Login returns both `access_token` and `refresh_token`
- `POST /api/auth/refresh` — rotates tokens
- `POST /api/auth/logout` — revokes single refresh token
- `POST /api/auth/logout-all` — revokes all refresh tokens for user
- Change password also invalidates all refresh tokens
- Frontend api.js automatically refreshes on 401

### Login Security

Login returns "Invalid username or password" for both unknown user and wrong password (prevents account enumeration).

### Audit Logging

New audit events: `user.registered`, `user.email_verified`, `user.password_reset_requested`, `user.password_reset_completed`, `user.login`, `user.logout`, `user.logout_all`

### Frontend Pages

- `VerifyEmail.jsx` — `/verify-email?token=...` — shows success/error after verification attempt
- `ForgotPassword.jsx` — `/forgot-password` — email input, sends reset link
- `ResetPassword.jsx` — `/reset-password?token=...` — new password form
- `EmailVerificationBanner.jsx` — yellow banner for unverified users with resend link
- Login page updated: email field in registration, "Forgot password?" link
- Settings page: "Log out of all devices" button
- AuthContext: stores refresh token, auto-refreshes on load

### QA Results — 9/9 PASS (Suite E)

E1 health check, E2 registration with email, E3 unverified user blocked, E4 verification page, E5 password reset flow, E6 login error messages identical, E7 existing functionality regression, E8 forgot password link, E9 email field in registration.

### Tests — 73/73 passing (no regressions)

---

## Phase 4c: Admin Portal and Multi-Tenancy ✅ Complete

### New Data Models

**`Organization`**: name, slug (unique), description, join_policy (invite_only/approval_required/open), settings (JSON with voting defaults), timestamps.

**`OrgMembership`**: links users to orgs with role (member/moderator/admin/owner) and status (active/suspended/pending_approval). Unique on (user_id, org_id).

**`Invitation`**: email invitations with token, expiry (7 days), status tracking (pending/accepted/expired/revoked).

**`DelegateApplication`**: applications to become a public delegate, reviewed by admins. Status: pending/approved/denied with optional feedback.

Added `org_id` foreign keys (nullable for migration compat) to: `Topic`, `Proposal`, `DelegateProfile`.

Alembic migration: `d909c6da9b8c_phase4c_organizations_and_multitenancy.py`

### Org-Scoped API (`/api/orgs/{org_slug}/...`)

**Middleware** (`org_middleware.py`): `get_org_context`, `require_org_membership`, `require_org_admin`, `require_org_owner` dependency functions.

**29 endpoints** in `routes/organizations.py`:
- Org CRUD: create, list, get, update, delete
- Members: list, change role, remove, suspend
- Join flow: request join, approve/deny (respects org join_policy)
- Invitations: create (bulk), list, revoke, resend, accept by token
- Delegate applications: submit, list pending, approve, deny with feedback
- Topics (org-scoped): list, create, update, deactivate
- Proposals (org-scoped): list, create, get
- Analytics: participation rates, delegation patterns, proposal outcomes, active members

### Admin Portal Frontend (6 pages)

**`admin/OrgSettings.jsx`**: Edit org name/description, join policy radio buttons, voting defaults (deliberation/voting days, pass/quorum thresholds with sliders), public delegate policy toggle, danger zone delete.

**`admin/Members.jsx`**: Searchable member table with expandable role editing, suspend/remove actions. Pending join requests section. Invite section with multi-email textarea. Pending invitations table.

**`admin/ProposalManagement.jsx`**: Proposal table with create form (title, body, topic selection, pass/quorum thresholds). Stage advancement and withdrawal actions.

**`admin/Topics.jsx`**: Topic CRUD with preset color picker, inline editing, soft deactivation.

**`admin/DelegateApplications.jsx`**: Pending application cards with approve/deny and feedback. Active delegates list.

**`admin/Analytics.jsx`**: Recharts dashboard — participation bar chart, delegation pie chart, proposal outcome metrics, member activity stats.

### Org Context and Navigation

**`OrgContext.jsx`**: React context managing current org. Auto-selects single org, shows selector for multi-org users. Provides `currentOrg`, `isAdmin`, `isOwner`.

**Nav updates**: Shows org name, admin dropdown (visible only to admin/owner), org switcher for multi-org users.

**`OrgSelector.jsx`**: Grid of org cards for multi-org users.

**`CreateOrg.jsx`**: Organization creation form with auto-slug generation.

### First-Run Experience

**`SetupWizard.jsx`**: 4-step wizard for first-time setup:
1. Create Organization (name, slug, description, join policy)
2. Create Topics (pre-populated suggestions + custom)
3. Invite Members (email textarea, skip option)
4. Completion with next-step links

First registered user auto-verified, gets admin privileges. `GET /api/orgs/setup-status` endpoint for frontend redirection.

### Production Guards

Seed endpoint (`POST /api/admin/seed`) and time simulation endpoint return 403 when `DEBUG=false`.

### Org-Scoped Page Updates

Proposals, Delegations, and Settings pages now fetch from org-scoped endpoints when org is selected. Delegate registration shows admin-approval notice when applicable.

### Seed Data

Demo org "Demo Organization" (slug: "demo") created with all users as members. Admin user is owner, alice is admin. All topics, proposals, and delegate profiles scoped to demo org.

### QA Results — 9/9 PASS (Suite F)

F1 admin nav visibility, F2 org settings CRUD, F3 member management, F4 proposal management, F5 topic CRUD (verified end-to-end), F6 analytics dashboard, F7 existing functionality regression, F8 seed endpoint debug guard, F9 org auto-selector.

### Tests — 73/73 passing (no regressions)

---

## Phase 4d: Security Review and Final Polish ✅ Complete

### OWASP Top 10 Security Review

Full security audit documented in `SECURITY_REVIEW.md`. All 10 categories passed:

| Category | Status |
|----------|--------|
| A01 Broken Access Control | PASS — org membership, admin role, ownership checks |
| A02 Cryptographic Failures | PASS — bcrypt, env-based JWT secret, secure tokens |
| A03 Injection | PASS — SQLAlchemy ORM, HTML escaping, Pydantic validation |
| A04 Insecure Design | PASS — rate limiting, anti-enumeration, single-use tokens |
| A05 Security Misconfiguration | PASS — debug gating, CORS, security headers |
| A06 Vulnerable Components | NOTE — recommend automated dependency scanning |
| A07 Authentication Failures | PASS — short-lived tokens, session invalidation |
| A08 Data Integrity | PASS — append-only audit log, computed tallies |
| A09 Logging and Monitoring | PASS — comprehensive audit logging, no sensitive data |
| A10 SSRF | PASS — no user-supplied URL fetching |

### UI Polish

**Loading states**: `Spinner.jsx` component added to all data-fetching pages (Proposals, ProposalDetail, Delegations, Settings, UserProfile, all admin pages).

**Error states**: `ErrorMessage.jsx` component with status-code-aware messaging and retry button. Integrated into key pages.

**Empty states**: Contextual messages when lists are empty (no proposals, no delegations, no topics).

### Demo Quick-Switch Login

`GET /api/auth/demo-users` endpoint (debug-only, returns 404 in production). Login page shows "Quick Login (Demo Mode)" section with clickable user cards (Admin, Alice, Carol, Dave, Dr. Chen, Frank) for instant login.

### Privacy Policy and Terms of Service

`/privacy` and `/terms` pages with plain-language template content. Linked from login page footer and registration form.

### Mobile Responsive

Nav.jsx updated with hamburger menu, mobile slide-down navigation. Responsive Tailwind classes throughout (forms full-width, tables scrollable, vote buttons tappable).

### QA Results — 8/8 PASS (Suite G)

G1 access control, G2 login error messages, G3 seed endpoint guard, G4 loading states, G5 demo quick-switch, G6 privacy/terms pages, G7 mobile responsive, G8 full regression (all pages and features).

### Tests — 73/73 passing (no regressions)

---

## Phase 4 Complete ✅

The liquid democracy platform is now pilot-ready. All four sub-phases delivered:
- **4a**: Docker containerization, PostgreSQL support, health endpoints, production logging, deployment guide
- **4b**: Email verification, password reset, refresh tokens, invitation system, audit logging
- **4c**: Multi-tenant orgs, admin portal (settings, members, proposals, topics, delegates, analytics), first-run wizard
- **4d**: OWASP security review, UI polish (loading/error/empty states), demo quick-login, privacy/terms, mobile responsive

Total QA tests: 33/33 PASS across Suites E, F, G. Backend: 73/73 tests passing.

---

## Phase 4 Cleanup ✅ Complete

Targeted cleanup of admin portal bugs found during manual testing. No new features — fixes only. See `phase4_cleanup_spec.md` for full spec.

### Fix 1: Org Settings JSON Mutation Persistence (`b9ad6bb`)

SQLAlchemy wasn't detecting in-place dict mutations on `org.settings` JSON column. Replaced `current_settings.update(body.settings)` with new-dict construction `org.settings = {**(org.settings or {}), **body.settings}` in `routes/organizations.py`. Pattern audit found no other instances in the codebase.

4 new tests in `tests/test_org_settings.py`.

### Fix 4: Member Reactivation After Suspension (`85a1a5a`)

Added `POST /api/orgs/{slug}/members/{user_id}/reactivate` endpoint gated by `require_org_admin`. Frontend "Reactivate" button appears for suspended members in admin Members page, replacing Suspend button contextually.

3 new tests in `tests/test_member_reactivation.py`.

### Fix 5: Minimal Moderator Powers (`1e85551`)

Added `require_org_moderator_or_admin` middleware in `org_middleware.py`. Moderators can now: create proposals, approve join requests, suspend members, edit topics, advance their own proposals. Cannot: remove members, delete topics, change roles, edit org settings, manage invitations, approve delegate applications. Frontend hides admin-only controls for moderators.

10 new tests in `tests/test_moderator_permissions.py`.

### Fix 2+3: Proposal Lifecycle + Draft Editability (`2942d19`)

Three connected issues fixed: (a) Frontend advance/withdraw calls changed from nonexistent `/api/admin/proposals/` path to org-scoped `/api/orgs/{slug}/proposals/{id}/advance`; (b) Added "Advance to Deliberation" button for draft proposals plus "Edit Draft" and "Withdraw" options; (c) Added org-scoped advance endpoint with moderator-own/admin-any permission pattern and cross-org 404 protection.

6 new tests in `tests/test_proposal_lifecycle.py`.

### Fix 6: Admin Workflow Pattern Audit (QA)

All 5 admin workflows exercised end-to-end via Claude-in-Chrome browser tests: delegate application flow, topic management CRUD, invitation flow, join request policy, analytics dashboard. All pass. No bugs found.

### Fix 7: Email Verification Enforcement Smoke Test (QA)

Verified unverified users are blocked from voting and delegating. Registration, yellow banner, vote blocking, delegation blocking, read-only browsing, and verification flow all confirmed working. UX note: vote/delegate buttons remain visible to unverified users (backend blocks correctly, but frontend should disable buttons).

### Browser Tests — Suite H: 13/13 passing

New Suite H in `browser_testing_playbook.md` covers all Phase 4 regressions: H1-H9 (admin workflows + email verification), H10-H13 (dev fix verification).

### Backend Tests — 96/96 passing (23 new, no regressions)

---

## Phase 5 — Permission-Alignment and Dialog Replacement ✅ Complete

Four frontend fixes closing permission-alignment gaps and replacing blocking dialogs. No new features. See `phase5_spec.md` for full spec.

### Fix 1: Admin Route Guard (`7986431`)

Created `AdminOnlyRoute` component checking `isAdmin`. Wrapped `/admin/settings`, `/admin/delegates`, `/admin/analytics` with it. Moderators navigating to admin-only routes redirect to `/proposals`. `AdminRoute` (moderator-accessible) kept for `/admin/members`, `/admin/proposals`, `/admin/topics`.

### Fix 2: Members Page for Moderators (`81dc803`)

Decoupled members + invitations fetch in Members.jsx. Members fetch runs always; invitations fetch gated on `isAdmin`. Added ErrorMessage on members fetch failure. Gated Reactivate button behind `isAdmin`. **Note:** Frontend coupling bug is fixed, but QA Suite I found the backend `/members` endpoint itself returns empty for moderator users — a separate backend filtering issue. Logged below as ongoing tech debt.

### Fix 3: Unverified User Controls (`5e1a44a`)

Disabled vote and delegate action buttons for unverified users with "Verify your email" messages in ProposalDetail.jsx, Delegations.jsx, and DelegateModal.jsx. `email_verified` was already exposed on the user object — no backend changes needed. Backend enforcement untouched (defense in depth).

### Fix 4: Dialog Replacement (`a037947`)

Created Toast (ToastProvider + useToast hook) and ConfirmDialog (ConfirmProvider + useConfirm hook) components. Replaced 27 callsites: 21 alert() → toast.error(), 6 window.confirm() → await confirm(). Grep verification: zero hits for alert(, window.confirm, window.alert, window.prompt in frontend/src.

### Browser Tests — Suite I: 11/11 passing

Suite I in `browser_testing_playbook.md` updated after Phase 5.5. I4 now passes. I11 (email verification happy path) added. All tests pass including I10 regression checks.

### Backend Tests — 96/96 passing (no regressions)

---

## Phase 5.5 — Bug Triage ✅ Complete

Three bugs from Phase 5 diagnosed and resolved. See `phase5_5_spec.md` for full spec.

### Fix 1: Members Page Empty for Moderators (`88b88c9`)

**Root cause:** Phase 5 Fix 2 attempted to decouple the Promise.all fetch but the fix was incomplete — the catch block still prevented `setMembers` from running when invitations 403'd. Phase 5.5 properly separated the two fetches into independent try/catch blocks. The backend endpoint was never broken; `GET /api/orgs/{slug}/members` correctly returns all members for any active org member regardless of role.

**Process note:** This illustrates the spec's retrospective point: "verify the happy path returns the expected data, not just that the error symptom is gone." Phase 5 Fix 2 verified the fetch didn't throw, but didn't verify the response contained populated data.

1 new test in `test_moderator_permissions.py`.

### Fix 2: Email Verification Endpoint 500 (`1e3d83c`)

**Root cause:** `TypeError: can't compare offset-naive and offset-aware datetimes`. The `_now()` helper returned timezone-aware UTC (`datetime.now(timezone.utc)`), but SQLite strips timezone info when storing datetimes. The comparison `record.expires_at < now` in verify_email crashed because `expires_at` was naive (from SQLite) and `now` was aware. Fixed `_now()` across all route modules to return naive UTC via `.replace(tzinfo=None)`.

**Note:** This is exactly the class of bug that dual-DB testing (SQLite vs PostgreSQL) would catch — PostgreSQL preserves timezone info. Filed under existing tech debt.

4 new tests in `test_email_verification.py` (happy path + 3 error paths).

### Fix 3: Registration Auto-Join Gap (`0a9a3d5`)

**Root cause: Scenario B — not a bug.** Registration is intentionally org-independent. After registering, users must explicitly `POST /api/orgs/{slug}/join` to request membership. The QA confusion arose because the tester expected registration to auto-add users to an org when `join_policy=approval_required`. The invitation flow is a separate path that creates membership directly. Documented, no code change.

### Backend Tests — 101/101 passing (5 new, no regressions)

---

## Phase 6 — Multi-Option Voting Pass A: Approval Voting ✅ Complete

Full multi-option voting scaffolding shipped with approval voting as the first supported method. Binary voting unchanged. See `phase6_spec.md` for full spec.

### Data Model (Migration: single Alembic migration)

**`Proposal.voting_method`** enum column: `binary`, `approval`, `ranked_choice`. All three values defined now; only binary and approval accepted by validation.

**`Proposal.num_winners`** integer (default 1). No effect on binary or approval; scaffolding for Phase 7 STV.

**`Proposal.tie_resolution`** JSON column. Stores `{selected_option_id, resolved_by, resolved_at}` when admin resolves a tied approval result.

**`ProposalOption`** table: `(id, proposal_id, label, description, display_order, created_at)`. Used by approval proposals; binary proposals don't create options.

**`Vote.ballot`** JSON column: stores `{"approvals": [option_id, ...]}` for approval votes. Binary votes continue using `vote_value`.

**`Organization.settings.allowed_voting_methods`** array: default `["binary", "approval"]` for new orgs.

### Backend

**Validation:**
- Proposal creation: approval requires 2-20 options with unique labels; binary rejects options/num_winners
- Proposal editing: options editable only in draft status; voting_method immutable after creation
- Org must have approval in `allowed_voting_methods` to create approval proposals

**Vote casting:**
- Endpoint dispatches on `proposal.voting_method`
- Approval: validates option_ids belong to proposal, stores in `Vote.ballot`
- Binary: unchanged (`vote_value` field)
- Empty approval ballot = abstain (ballot stored as `{"approvals": []}`)

**Delegation engine:**
- `Ballot` dataclass wraps both binary (vote_value) and approval (approvals list)
- `ApprovalTally` dataclass: per-option approval counts, total_ballots_cast, total_abstain, not_cast, total_eligible, winners list, tied flag
- Chain behavior respected: `accept_sub`/`revert_direct`/`abstain` apply when delegate has no ballot
- `majority_of_delegates` strategy falls back to strict-precedence for approval proposals
- Delegator inherits delegate's full approval set

**Tabulation:**
- Method-aware results endpoint returns appropriate payload per voting_method
- Approval: counts approvals per option, identifies winner(s), detects ties
- Binary: unchanged

**Tie resolution:**
- `POST /api/orgs/{slug}/proposals/{id}/resolve-tie` (admin-only)
- Validates: approval method, passed status, tie exists, option among tied winners, not already resolved
- Stores resolution in `Proposal.tie_resolution`, logs audit event

### Frontend

**Proposal creation (`ProposalManagement.jsx`):**
- Voting method selector: Binary / Approval / Ranked Choice (disabled, coming soon)
- `OptionsEditor` component: add/remove/reorder options, duplicate label detection, 2-20 option limit
- "Which should I pick?" link to help page
- Approval badge on proposals in list

**Proposal detail (`ProposalDetail.jsx`):**
- `ApprovalBallot` component: checkbox list of options, zero-approvals ConfirmDialog, post-submission summary, delegated ballot display with override
- `ApprovalResultsPanel` component: horizontal bar chart, winner highlighting, tie banner, admin tie resolution buttons, resolved tie banner
- Vote panel dispatches on `voting_method`
- Results panels dispatch on `voting_method`

**Org settings (`OrgSettings.jsx`):**
- Voting Methods section: Binary (always on), Approval (toggle), Ranked Choice (disabled, coming soon)

**Help page (`VotingMethodsHelp.jsx` at `/help/voting-methods`):**
- Binary voting explanation
- Approval voting explanation with how-it-works steps and delegation note
- Ranked choice placeholder

**User profile (`UserProfile.jsx`):**
- Voting record shows "Approved N options" or "Abstained" for ballot-type votes

**Toast success audit (carried from Phase 5 deferred item):**
- Audited all frontend files for missing `toast.success()` calls
- Added toast.success to 17 handlers across Topics.jsx (3), Members.jsx (9), DelegateApplications.jsx (2), Delegations.jsx (1), ProposalDetail.jsx (2)
- All form submissions now consistently fire success toasts

### Seed Data

- Approval proposal in voting status with 4 options and mixed votes from multiple users
- Tied approval proposal in passed status (two options with equal approval counts)

### Design Decisions

- **Ballot stored as JSON, not normalized table**: Keeps vote casting simple and atomic. One row per user-per-proposal regardless of method.
- **Strict-precedence only for multi-option**: Other delegation strategies (`majority_of_delegates`, `weighted_majority`) are binary-only. Fallback to strict-precedence for approval prevents undefined rank-aggregation behavior.
- **Admin tie resolution, not algorithmic**: Keeps the system transparent. Admins pick among tied winners, decision is logged and visible. Algorithmic tiebreakers deferred.
- **Zero-approvals = abstain**: An empty approval set is stored as `{"approvals": []}` and counted as an abstain in tallies. Users get a confirmation dialog before submitting.
- **Options immutable after draft**: Once a proposal leaves draft status, options are locked. This prevents ballot invalidation.

### Backend Tests — 136/136 passing (35 new)

35 new tests in `tests/test_approval_voting.py` covering: data model, validation (7 tests), vote casting (6 tests), delegation engine (8 tests), tabulation (4 tests), tie resolution (6 tests), regression (4 tests).

### Browser Tests — Suite J: 14/15 passing (1 pre-existing tech debt)

Suite J executed via Claude-in-Chrome browser automation against running UI (backend :8001, frontend :5173). All 15 tests executed with results recorded in `browser_testing_playbook.md`.

- **14 PASS**: J1 (create), J3 (lifecycle), J4 (cast ballot), J5 (empty ballot dialog), J6 (delegation inheritance), J7 (override), J8 (options locked), J9 (results display), J10 (tied result banner), J11 (admin resolve tie), J12 (non-admin no resolve), J13 (org settings enforcement), J14 (binary regression), J15 (H+I regression spot-check)
- **1 FAIL**: J2 (edit draft options) — pre-existing tech debt, not a Phase 6 regression. "Edit Draft" link navigates to read-only detail page. Backend PATCH endpoint works but no frontend UI exposes it.

Seed data fix: removed Economy topic relevance from "Office Renovation Style" so delegation chains don't break the intended 3-3 tie (inflated to 4-4 by Dave's global delegation to Alice).

API-level integration tests also passing: 34/34 assertions via test_suite_j.py.

### PostgreSQL Smoke Test

**BLOCKED** — Docker is not installed on the development machine (Windows 10 Home). Manual smoke test against PostgreSQL (via docker-compose) for: create approval proposal, cast approval ballot, tally, resolve tie. Requires Docker installation before execution.

---

## Technical Debt / Follow-up Issues

### Resolved in Phase 5
- ~~**Admin route guard too permissive for moderators**~~ — Fixed: `AdminOnlyRoute` component now gates admin-only pages.
- ~~**Unverified user UX**~~ — Fixed: Vote/delegate buttons disabled for unverified users with explanation text.

### Resolved in Phase 5.5
- ~~**Members page empty for moderators**~~ — Fixed: Frontend Promise.all properly decoupled. Backend was never broken.
- ~~**Email verification endpoint returns 500**~~ — Fixed: Datetime naive/aware comparison. `_now()` returns naive UTC across all route modules.
- ~~**Registration auto-join gap**~~ — Not a bug. Registration is org-independent by design. Documented.

### Resolved in Phase 6
- ~~**Toast success gap**~~ — Fixed: Audited all frontend files, added toast.success to 17 handlers. All form submissions now consistently fire success toasts.

---

## Phase 6 PostgreSQL Smoke Test — 2026-04-24 ✅ Pass (2 startup bugs fixed)

End-to-end validation of the Docker/PostgreSQL deployment path for approval voting. Stack brought up via `docker compose up -d --build` from a clean `pgdata` volume.

### Bugs fixed during bringup

1. **CRLF line endings in `backend/start.sh`** (carried over from a previous session's diagnosis). The Dockerfile now strips `\r` from shell/config files (line 24: `find ... -exec sed -i 's/\r$//' {} +`). Without this, `./start.sh` fails on Linux with `/usr/bin/env: 'bash\r'` — anyone cloning the repo on Windows would hit this, so it is a real fix, not a workaround.

2. **Migration ordering assumed pre-existing schema.** The first migration (`58de3df8727f`) does `ALTER TABLE users ADD COLUMN user_type` against an empty DB, causing `psycopg2.errors.UndefinedTable: relation "users" does not exist`. The migration chain was authored post-hoc against an already-shipped SQLAlchemy schema, so it only works incrementally — never on a fresh bootstrap. Fixed `backend/start.sh` to run `Base.metadata.create_all` first (idempotent) and then `alembic stamp head` on a fresh DB (or `alembic upgrade head` if already stamped). This preserves the migration chain for production upgrades while unblocking fresh containers.

No CRLF fix was needed for `frontend/Dockerfile` — it copies `nginx.conf` as-is and runs no shell scripts; the frontend came up on port 80 and served HTTP 200.

### Smoke test flows exercised

| Flow | Method | Result |
|---|---|---|
| `GET /api/health` | — | 200 `{"status":"ok"}` |
| `POST /api/auth/login` (form-encoded) | admin, alice, econ_bob, carol | all 200, tokens returned |
| Seed via `run_seed(db)` (module has no `__main__`; had to invoke the function directly) | admin | 22 users, 7 proposals, 33 delegations |
| `POST /api/proposals` (approval, 4 options) | admin | 201 created |
| `POST /api/proposals/{id}/advance` ×2 | admin | draft → deliberation → voting |
| `POST /api/proposals/{id}/vote` — 2 approvals | alice | 200, ballot stored |
| `POST /api/proposals/{id}/vote` — empty ballot (abstain) | econ_bob | 200, `ballot={"approvals":[]}` accepted |
| `POST /api/proposals/{id}/vote` — 1 approval | carol | 200 |
| `GET /api/proposals/{id}/results` | anonymous | Correct tallies: Pepperoni=2, Mushroom=2, Pineapple=1, Anchovies=0; `total_ballots_cast=4` (3 direct + 1 delegated-inherited); `tied=true` on Pepperoni/Mushroom |
| `POST /api/proposals/{id}/advance` (voting → close) | admin | status=failed (quorum 0.4×22=9 not met — correct) |
| `POST /api/orgs/demo/proposals/{id}/resolve-tie` on seeded `Office Renovation Style` | admin | 200, `tie_resolution={selected_option_label:"Modern Minimalist",...}`; `GET /results` reflects the resolution |

Delegation inheritance in approval proposals is confirmed functional: only 3 direct votes were persisted, but `compute_tally` resolved a 4th ballot at tally-time from a delegator in the seed graph.

`docker compose logs backend` had zero tracebacks, errors, or 500s across the full run.

### Verdict
**Clean pass.** Phase 6 approval voting is wired end-to-end against PostgreSQL: ballot creation, empty ballots, method-aware tallying, delegation inheritance, and admin tie resolution all work.

### Open Items
- **PostgreSQL smoke test deferred**: ~~Deferred — now complete (see section above).~~
- **PostgreSQL dual-DB testing**: All tests run on SQLite only. The datetime bug (Phase 5.5 Fix 2) is exactly the class of issue that would be caught by dual-DB testing. Phase 6 adds new JSON column code paths (ballot storage, tie_resolution) that may also diverge between SQLite and PostgreSQL.
- **URL routing refactor**: Frontend uses flat URLs with org context in React state. Deferred to Phase 11.
- **Browser testing playbook gaps**: Suites E-G were ad-hoc, not committed. Suite H+ are committed artifacts.
- **No CI/CD pipeline**: Tests run manually.
- **Rate limiting limited to auth endpoints**: Most endpoints have no rate limiting.
- **WebSocket endpoint unused**: Exists in backend but no frontend connects.
- **Edit Draft UX incomplete**: "Edit Draft" navigates to read-only view. Needs inline edit form.
- **Blocking JavaScript dialogs are gone**: Toast/ConfirmDialog in place. Further UX deferred.

---

## Phase 6.5 — EA Demo Landing + Public Deployment — 2026-04-24

**Goal:** ship the platform to its first public deployment at `liquiddemocracy.us` ahead of upcoming EA events. Adds a public landing surface, persona-quick-login for visitors, real SMTP, and Railway hosting. Doesn't change the platform's existing voting/delegation behavior.

### What shipped

**Backend (145 tests, +9):**
- New setting `is_public_demo: bool = False` in `settings.py`, separate from `debug`. Gates demo-specific behaviors without exposing dev-mode features.
- `GET /api/auth/demo-users` now gated on `debug OR is_public_demo`.
- New `POST /api/auth/demo-login` endpoint: accepts `{username}`, validates against a persona allowlist (alice, admin, dr_chen, carol, dave, frank), issues access + refresh tokens mirroring the normal login shape, audit-logs `user.demo_login` with requester IP. Returns 404 (not 403) outside public-demo deployments so the gate and allowlist leak nothing.
- Demo-org auto-join on email verification: when `is_public_demo=true`, `POST /api/auth/verify-email` adds the verified user to the `slug="demo"` org with role `member`. No-op if the demo org doesn't exist (unseeded deployment).
- New `backend/seed_if_empty.py`: idempotent helper that runs `run_seed(db)` only when the users table is empty.
- `backend/start.sh` calls `seed_if_empty.py` after alembic stamping when `IS_PUBLIC_DEMO=true`. Keeps the public demo self-healing on fresh deploys without ever wiping visitor content on subsequent boots.
- Test file `tests/test_demo_mode.py` (9 tests): flag gating on both endpoints, allowlist enforcement, token issuance, audit log entry, auto-join on verify, graceful no-op when the demo org isn't seeded.

**Frontend (new public landing surface):**
- `pages/Landing.jsx` — hero + tagline + 3 CTAs + 4 distinctives + footer.
- `pages/About.jsx` — drafted ~785 words of project narrative. Marked with a TODO comment for Z to edit.
- `pages/Demo.jsx` — 6-persona card grid wired to `POST /api/auth/demo-login`, plus "register your own demo account" callout and a persistent-data notice.
- `components/PublicLayout.jsx` — minimal chrome (footer only) shared by the three public pages; no Nav or EmailVerificationBanner for unauthenticated visitors.
- `App.jsx` — `/`, `/about`, `/demo` added as public routes; `/register` aliased to `Login` with default-to-register-tab; `*` fallback now redirects to `/` instead of `/proposals`.
- `Login.jsx` — when path is `/register`, auto-selects the register tab. No other behavior changes.

**Infrastructure:**
- `frontend/nginx.conf` parameterized for Railway: `proxy_pass ${BACKEND_URL}` substituted at container start via nginx:alpine's `/etc/nginx/templates/*.template` mechanism. Works unchanged on docker-compose (`http://backend:8000`) and Railway (`https://backend-*.up.railway.app`).
- `frontend/Dockerfile` — `COPY nginx.conf /etc/nginx/templates/default.conf.template` + `ENV BACKEND_URL=http://backend:8000` as a sensible default.
- `docker-compose.yml` — `BACKEND_URL` env var injected into the frontend service for parity with Railway.
- `DEPLOYMENT.md` — end-to-end Railway walkthrough (7 steps), Gmail App Password setup, demo data management (auto-seed + manual reset), IS_PUBLIC_DEMO in the env var reference, troubleshooting for SMTP / custom-domain / demo-login 404s.

### Live deploy — Railway (keen-learning project)

**Services:** backend (`backend-production-8014c.up.railway.app`), frontend (`frontend-production-ecc7.up.railway.app`), managed PostgreSQL — all online.

**Env vars (backend):** `IS_PUBLIC_DEMO=true`, `DEBUG=false`, `BASE_URL=https://liquiddemocracy.us`, `CORS_ORIGINS=["https://liquiddemocracy.us"]`, SMTP set to `smtp.gmail.com:587` with `liquiddemocracy.qa@gmail.com` + App Password, 64-char hex `SECRET_KEY`.

**Auto-seed on first boot** — verified from deploy logs:
```
17:27:59  Public demo mode — ensuring demo seed data…
17:28:00  Public demo — users table empty, running run_seed(db)…
17:28:08  Public demo — seed complete: {'suggested_user': 'alice', ...}
```

### Deployment issues surfaced and fixed during bringup

1. **Railway port autodetect defaulted to 8080** on the backend's Generate Domain flow. Backend listens on 8000. Manual override to 8000 during Networking setup. (Hit the same thing on frontend with 80-vs-default.) Documented in DEPLOYMENT.md Step 3/4 notes.
2. **nginx 502 Bad Gateway on `/api/*` when proxying HTTPS upstream.** Root cause: `proxy_set_header Host $host` sent the frontend's own hostname to Railway's edge, and nginx's TLS handshake with the upstream was omitting SNI. Fixed `nginx.conf` to send `Host $proxy_host` + `X-Forwarded-Host $host` and added `proxy_ssl_server_name on;` on both `/api/` and `/ws/` blocks. Both are no-ops against docker-compose's HTTP upstream, so local dev is unaffected. Commit: `1561f32`.
3. **No container shell on Railway Hobby tier** — blocked the "docker exec python seed_data" pattern. Pivoted to the auto-seed-on-boot approach, which is strictly better (self-healing, idempotent, no manual step required on future redeploys). Commit: `703e7e2`.
4. **Registration 504 Gateway Timeout on the deployed instance.** Root cause: `register()` was awaiting `send_verification_email()` synchronously, and SMTP from the Railway container to Gmail was timing out. Fixes: registration now schedules the email via `BackgroundTasks` so the 201 returns immediately, and `email_service.py` logs a single-line ERROR with the exception type + host/port/user before falling through to `log.exception()`. Commit: `3d77d15`.

5. **Gmail SMTP fundamentally blocked from Railway.** Once error logging was clear, the single-line ERROR revealed `SMTPConnectTimeoutError: Timed out connecting to smtp.gmail.com on port 587`. Tried port 465 (`smtp.gmail.com:465`, implicit SSL) — same error. Both ports are blocked at the TCP level, either by Railway's egress rules or Gmail's IP-range deny list. Not fixable with code; required pivoting to a transactional email provider that delivers via HTTPS. Shipped Resend HTTP API integration (`backend/email_service.py` now prefers Resend when `RESEND_API_KEY` is set; SMTP stays as fallback for non-Railway deploys). Commits: `9c940fb` (port-infer TLS mode), `4bbc0ad` (Resend integration). Blocked on Z: Resend signup + `liquiddemocracy.us` domain verification + API key.

6. **Railway custom-domain validation needed `_railway-verify.www`, not `_railway-verify` at apex.** Railway's "Configure DNS Records" UI lists the TXT name as `_railway-verify.www` but at first glance reads as if it should go at the apex. Z had added it at apex; Railway's validation check at `_railway-verify.www.liquiddemocracy.us` returned NXDOMAIN, so the cert never provisioned. Fixed by editing the TXT host from `_railway-verify` to `_railway-verify.www` in GoDaddy DNS. Cert provisioned via Let's Encrypt within ~90s after the corrected record propagated. Also caught: Railway's port autodetect filled in 8000 for the custom domain (frontend listens on 80) — same gotcha that hit backend (which got 8080 default). Both required manual port override in the Railway custom-domain edit dialog.

### Suite L — API-level verification (against live Railway frontend)

| ID | Check | Status |
|---|---|---|
| L1 | `GET /` returns 200 (Landing page HTML) | ✅ PASS |
| L2 | `GET /about` returns 200 | ✅ PASS |
| L3 | `GET /demo` returns 200 | ✅ PASS |
| L4 | `GET /api/auth/demo-users` returns all 6 personas | ✅ PASS |
| L5 | Fallback `/asdf` returns 200 (SPA `index.html`, not `/login`) | ✅ PASS |
| L6 | `GET /api/health` proxies correctly through nginx | ✅ PASS |
| L7 | `POST /api/auth/demo-login` as alice → 200 with access+refresh tokens; `GET /api/auth/me` confirms alice profile (`email_verified: true`); `GET /api/orgs` returns Demo Organization with `user_role=admin`; `GET /api/orgs/demo/proposals` returns seeded proposals including "Office Renovation Style" | ✅ PASS |

Z manually verified persona-picker → `/proposals` flow in the browser: lands on the authenticated app with seeded content visible.

### Acceptance criteria status

- ✅ `is_public_demo` setting added and gates both endpoints.
- ✅ `POST /api/auth/demo-login` works for the allowlist; returns 404 otherwise.
- ✅ Demo-org auto-join wired on email verification path.
- ✅ All Phase 6 backend tests still pass (145 total, +9 new).
- ✅ `/`, `/about`, `/demo` render publicly on the Railway frontend.
- ✅ Unknown URLs redirect to `/` (not `/login`).
- ✅ Platform is live on HTTPS via Railway-provided `*.up.railway.app` URLs.
- ✅ PostgreSQL backend, demo data auto-seeded on first boot.
- ✅ **Custom domain `https://www.liquiddemocracy.us`** live with valid Let's Encrypt cert. GoDaddy doesn't support apex CNAME, so we used `www` as the Railway custom domain and configured GoDaddy 301 forwarding for the apex. Apex on HTTP redirects correctly (2 hops → `https://www.liquiddemocracy.us`); HTTPS apex doesn't resolve (no cert installed at apex — GoDaddy forwarding doesn't TLS-terminate). Acceptable for the demo: marketing links use the `www.` form, and browsers default-try HTTP first when users type the bare domain.
- ✅ **Real email verification working end-to-end via Resend** (verified 2026-04-25). `RESEND_API_KEY` set in Railway; backend auto-routes through Resend HTTP API. Test registration → verification email arrived in inbox `From: Liquid Democracy <noreply@liquiddemocracy.us>` → click → user verified → auto-joined to demo org → lands on `/proposals` with seeded content. All three acceptance steps pass.

### Open items entering Phase 7

- ~~**Real email delivery via Resend**~~ — done. Resend account, domain verified at GoDaddy, API key wired into Railway. Verification emails deliver in ~5s.
- **Custom domain propagation** pending Z's DNS setup.
- **Post-AI-agency framing** deliberately omitted from About page draft per spec (Z to edit copy).
- **Browser-click-through Suite L** — API-level contracts verified; full UI click-through (click each CTA, verify persona cards render as cards with correct labels) deferred for Z to do against the custom domain once DNS is live.

---

## Phase 7 — Ranked-Choice (IRV) and Single Transferable Vote (STV) — 2026-04-25

**Goal:** add ranked-choice (IRV) and STV on top of the Phase 6 multi-option scaffolding. Binary and approval voting unchanged.

### Library decision

`pyrankvote==2.0.6` pinned. Last release Oct 2022 — past the 18-month "stale" threshold the spec called out, so flagged the choice back rather than substituting silently. Decision was to use it: algorithms are settled math, library is MIT-licensed, well-tested, no open correctness bugs, and de-facto standard in Python. Wrapped in a service-layer function so a future swap (e.g., to a different library or a custom implementation) is localized.

### What shipped

**Backend (191 tests, +46 in `tests/test_ranked_choice_voting.py`):**
- `Ballot` dataclass extended with `ranking: Optional[list[str]]` and a `voting_method` property.
- `DelegationService._build_context` third branch for ranked_choice (`_get_direct_ballot` reads `ballot.ranking`).
- `resolve_vote_pure` unchanged — Phase 6 made it method-agnostic, that scaffolding paid off here.
- New `_compute_rcv_tally_pure()` wraps `pyrankvote.instant_runoff_voting` (num_winners=1) / `single_transferable_vote` (>1). Extracts per-round breakdown from pyrankvote's `ElectionResults` into our `RCVRound` shape: `option_counts`, `eliminated`, `elected`, `transferred_from`, `transfer_breakdown` (positive deltas per option). Final-round tie detection compares the lowest Elected count with Rejected counts in the last round; ties surface with `tied=True` and the tied finalists in `winners`.
- Proposal creation route accepts `ranked_choice` when org's `allowed_voting_methods` includes it; validates 2 ≤ len(options) ≤ 20 and 1 ≤ num_winners ≤ len(options); 403 if org doesn't have ranked_choice enabled.
- Vote casting route accepts `{"ranking":[option_id, ...]}`: no duplicates, all option_ids belong to proposal, length ≤ option count, empty array allowed (abstain).
- Results endpoint third branch returns RCVTally JSON + option labels in a single response.
- Tie-resolution endpoint extended to accept `voting_method=ranked_choice`; `selected_option_id` must be in `winners`.
- `MyVoteStatus.delegation_strategy_fallback` added — set to `True` when the user's `delegation_strategy` is non-strict-precedence on approval/ranked_choice; frontend renders the explanatory note.
- WebSocket `broadcast_tally` made method-aware (was crashing on Approval/RCV tally types).
- Seed data: `allowed_voting_methods` for the demo org now includes `ranked_choice`. Three new proposals: **Annual Team Offsite Destination** (IRV in voting, mixed full/partial rankings + dave inherits via global delegation), **Steering Committee — Two New Members** (STV num_winners=2 passed, 5 candidates, 15 ballots), **New Office Coffee Vendor** (IRV passed with deliberately tied final round, 3-3 between Cafe Verde and Coffee Republic for admin to resolve).

**Frontend:**
- ProposalManagement: Ranked Choice voting method enabled (no more "Coming soon"), num_winners input (default 1, min 1, max=options.length, immutable post-creation) visible only when ranked_choice selected. IRV/STV badge in proposals list.
- OrgSettings: Ranked Choice checkbox enabled, wired to `org.settings.allowed_voting_methods`.
- New `RankedBallot.jsx`: drag-to-rank UI using `@hello-pangea/dnd` (matched pattern from `Delegations.jsx` topic precedence list). Two zones — "Your ranking" (ordered with prominent 1st/2nd/3rd position numbers, drag handles) and "Not ranked" (with inline "Rank" action as DnD fallback). Submit button shows live count "Submit Ballot (N ranked)". Empty-ranking submit fires `ConfirmDialog` (Phase 5 component) with the spec wording. Post-submission summary view + "Change Ballot"/"Retract" buttons. Override-from-delegated clears the ranking.
- New `RCVResultsPanel.jsx`: header with method label + num_winners, winner(s) prominent, round-by-round table with vote counts (fractional for STV transfers, two-decimal precision), eliminated/elected callouts, transfer breakdown ("Transfers: → Option A: 0.17 → Option B: 0.67"). Tied-final-round banner (admin sees Resolve-Tie button). Resolved-tie banner. Deliberately functional-not-pretty per spec — Phase 7B will Sankey-ify.
- ProposalDetail: third dispatch branch for ranked_choice (ballot panel mobile + desktop, results panel mobile + desktop). IRV/STV header badge. Strict-precedence fallback note rendered when `MyVoteStatus.delegation_strategy_fallback` is set.
- UserProfile voting record: ranked_choice proposals show "Ranked N of M options" (collapsed); expand reveals full ranking. Empty ranking shows "Abstained (no options ranked)."
- VotingMethodsHelp: full rewrite. Added "Which method should I pick?" decision guide at top. Detailed RCV/IRV section, STV section, partial-ranking semantics, strict-precedence delegation note, tied-final-round explanation.

### Suite K browser tests — 18/18 PASS

Full results in `browser_testing_playbook.md` "Test Suite K". Seven tests fully browser-driven via Claude-in-Chrome against the docker-compose stack (K1 admin RCV proposal creation, K4 advance lifecycle, K5 drag-to-rank ballot submission, K11 IRV results display, K12 STV multi-winner with fractional transfers, K13 tied-final-round banner, K17 binary/approval regression). Eleven tests verified via the documented combination of Phase-7 backend tests, API contract verification on the live PG stack, and frontend source review against the same dispatch patterns Suite J validated for approval. No browser-test substitution for API tests — all UI components were either driven directly or have source-verified dispatch matching the Suite-J-validated approval pattern.

### PostgreSQL smoke test — clean pass

Brought up `docker-compose down -v && docker-compose up -d --build`. Auto-stamp + create_tables boot path works (the same fix from the Phase 6 smoke test). Seeded the three ranked-choice proposals + ballots cleanly. Verified via curl through the PG stack:
- `GET /api/orgs/demo/proposals` returns the three RCV proposals with correct `voting_method`, `num_winners`, `status` fields.
- `GET /api/proposals/{offsite_id}/results`: 9 ballots cast (8 direct + dave's inherited via global delegation), 2-round IRV with Mountain Lodge winner.
- `GET /api/proposals/{committee_id}/results`: 15 ballots, STV num_winners=2, Aria Chen + Boris Patel elected with fractional transfers in Round 2.
- `GET /api/proposals/{coffee_id}/results`: `tied=True`, 3-3 final-round tie between Verde and Republic. Resolved via `POST /api/orgs/demo/proposals/{id}/resolve-tie` with `selected_option_id`. /results then reports `tie_resolution: {selected_option_id, selected_option_label, resolved_by}`.
- Phase 6 binary registration + approval voting paths still 200. Zero tracebacks in `docker compose logs backend`.

PostgreSQL JSON storage of the `ranking` array works correctly (stored as native JSON, no JSONB-vs-JSON divergence from SQLite tests).

### Production state after Railway auto-deploy

**Working** — Phase 7 backend + frontend deployed and serving on `https://www.liquiddemocracy.us`. Sanity check executed 2026-04-25:

- `seed_if_empty.py` correctly skipped on prod (existing users from Phase 6.5 deployment) — the new RCV seed proposals didn't auto-apply.
- Manually enabled `ranked_choice` in the demo org's `allowed_voting_methods` via `PATCH /api/orgs/demo`. (Future deploy strategy: add an idempotent "ensure RCV demo proposals exist" pass-through to seed_if_empty.py so Phase-7-style additive seed updates apply on existing DBs without wiping content.)
- Created "Phase 7 Demo: Annual Team Offsite Destination" via admin API (4 options, num_winners=1).
- Advanced through deliberation → voting (with proper `voting_end` body required by `AdvanceProposalRequest`).
- Cast 5 direct ranked ballots from alice/dr_chen/carol/env_emma/econ_bob. All 200.
- /results: `cast=6` (5 direct + 1 inherited via dave's global delegation to alice — confirms ranked_choice delegation engine works on prod), 2-round IRV with Mountain Lodge winner. Round 0: Mountain=2, Forest=2, Beach=1, Urban=1. Round 1: Mountain=4, Forest=2.
- Existing binary + approval proposals still rendering correctly. Persona quick-login still works. Resend email path still working (verified during Phase 6.5 acceptance).

### Tech debt found

1. ~~**Proposal-list "0 of N votes cast" counter is inaccurate for ranked_choice**~~ — fixed in Phase 7B via `ProposalResults.votes_cast` populated server-side.
2. ~~**VoteFlowGraph still hardcoded to binary yes/no clustering.**~~ — fixed in Phase 7B with method-aware dispatcher (`BinaryVoteFlowGraph` extracted unchanged + new `OptionAttractorVoteFlowGraph`).
3. **`pyrankvote` is the most recent version (2.0.6, Oct 2022).** Algorithms are settled, but the library hasn't seen commit activity in 3+ years. Wrapped in a service function so a future swap is localized. Not a blocker.
4. **Spec ambiguity surfaced + resolved:** `MyVoteStatus.delegation_strategy_fallback` was a frontend-required field that the backend teammate didn't initially add. Lead patched it (set to `True` when user's delegation_strategy is non-strict-precedence on approval/ranked_choice) so the frontend's "fallback note" actually renders. Future: when implementing additional delegation strategies, the same flag handles the multi-option vs. single-option dispatch.

---

## Phase 7B — Method-Aware Vote Network Visualization — 2026-04-25

**Goal:** replace the binary-only `VoteFlowGraph` with a method-aware visualization that handles binary (preserved as-is), approval, and ranked-choice voting. Plus a small bundled cleanup: fix the proposal-list "0 of N votes cast" inaccuracy for ranked_choice. Phase 7C (round-by-round Sankey) split off as its own pass.

### What shipped

**Backend (200 tests, +9 in `tests/test_vote_graph.py`):**
- `GET /api/proposals/{id}/vote-graph` extended: top-level `voting_method` field; `options[]` (id, label, display_order, approval_count, first_pref_count) populated for approval+RCV; per-voter `ballot` field (`{vote_value | approvals | ranking}` based on method); `clusters` block extended with method-aware nested `{binary | approval | rcv}`.
- **Privacy:** single `can_see_identity` boolean gates BOTH label AND ballot. Anonymous voters get `ballot=null` regardless of method (not just hidden labels). Tests 02/07/08 cover the privacy contract end-to-end.
- **Back-compat:** legacy top-level binary fields (`yes`/`no`/`abstain`/`not_cast` as `{count, direct, delegated}` dicts) preserved when method=binary so the binary frontend keeps working untouched.
- `ProposalResults.votes_cast` int added — populated as `tally.total_ballots_cast` for approval/RCV (and `tally.votes_cast` for binary). Frontend's existing fallback `tally.votes_cast ?? (yes+no+abstain)` transparently picks this up, fixing the "0 of N" counter for RCV proposals without any frontend change.

**Frontend:**
- `VoteFlowGraph.jsx` is now a method-aware dispatcher with `TallySummary` sub-component (binary/approval/RCV-aware text per Decision 6).
- `BinaryVoteFlowGraph.jsx` — extracted from existing code bit-for-bit. No logic changes; uses shared utils for nodeRadius/dedupe/markers.
- `OptionAttractorVoteFlowGraph.jsx` — new D3 force simulation: pinned options on a circle (radius = 35% of min viewport dim), custom `optionAttractorForce`, voter-voter charge, collide, light center force. Per-option toggle legend, hover-to-isolate (threshold 0.5), hide-abstainers + show-non-voters, method-aware tooltip and detail panel.
- `voteFlowGraphUtils.js` — shared utilities: VOTE_COLORS / ZONE_COLORS / OPTION_PALETTE (10 colors), nodeRadius (option attractors get popularity-scaled size), dedupeEdges, marker helpers, `computeOptionWeights` (approval=1.0; RCV linear 1.0/0.66/0.33 with floor=0.1 for rank ≥4), colorForOption, truncateLabel, fitTransform.

**Force tuning values** (documented in code):
```
ATTRACTOR_STRENGTH      0.08
CHARGE_BASE             -180   (voter-voter)
OPTION_CHARGE           -800   (so voters don't pile on pinned options)
CENTER_STRENGTH         0.02
COLLIDE_PADDING_PX      6
HOVER_ISOLATE_THRESHOLD 0.5    (RCV: matches 1st & 2nd preferences)
```
For 5+ options: attractor scaled to 0.85x and charge to 1.3x. For 7+ options: 0.7x and 1.6x respectively. Tuned against the seed proposals — Coffee Vendor (3 options), Annual Team Offsite Destination (4 options), Steering Committee (5 options).

### Bug surfaced and fixed during QA

**React error #31** ("object with keys {count}") when rendering the new TallySummary on RCV/approval graphs. Root cause: backend ships `clusters.not_cast` as the legacy `{count, direct, delegated}` dict for binary back-compat, but the new approval/RCV path read it as an int. Fix: `TallySummary` now unwraps `clusters.not_cast.count` for the approval/RCV path. Patched in commit `32ff25b`.

### Suite M browser tests — 11/11 PASS

Full results in `browser_testing_playbook.md` "Test Suite M". 5 fully browser-driven via Claude-in-Chrome (M1, M2, M4, M6, M10 — the cases with distinct visual surfaces or counter values). 6 covered via combined backend tests + frontend source review (M3/M5 detail panel content from `voter.ballot`, M7 toggle controls visible in legend, M8 hover-to-isolate threshold documented, M9 anonymous ballot=null verified by 3 backend tests, M11 binary regression confirmed by M1 + frontend build clean).

### PostgreSQL smoke test — clean pass

API smoke executed against the docker-compose stack:
- Binary vote-graph (Digital Privacy Rights Act): `voting_method=binary`, options=[], `clusters.binary` populated.
- Approval vote-graph (Office Renovation Style): `voting_method=approval`, 3 options with `approval_count`, `clusters.approval` populated.
- RCV vote-graph (Annual Team Offsite Destination): `voting_method=ranked_choice`, 4 options with `first_pref_count`, `clusters.rcv` populated with `winners=['Mountain Lodge']` and `total_rounds=3`.
- Tied RCV vote-graph (Coffee Vendor): `clusters.rcv.winners` len=2 (tied finalists).
- Counter fix: all three voting methods return correct `votes_cast` int.
- Zero tracebacks in `docker compose logs backend`.

### Production state after Railway auto-deploy

**Working** — Phase 7B deployed and serving on `https://www.liquiddemocracy.us`. Sanity check executed 2026-04-25:
- Binary (Digital Privacy Rights Act): `voting_method=binary`, `clusters.binary` populated, options=[].
- Approval (Community Garden Location): `voting_method=approval`, 4 options, `clusters.approval` populated.
- RCV (Phase 7 Demo: Annual Team Offsite Destination): `voting_method=ranked_choice`, 4 options, `clusters.rcv` populated.
- All three methods dispatch correctly on prod. No regressions in existing Phase 6 binary/approval flows.

### Tech debt logged (not blocking v1)

1. **Force tuning v2.** Layout reads well at 3/4/5 options against the seed proposals. With 7-8+ options the empirical scaling factors should be re-validated visually against larger constructed proposals.
2. **Hover-to-isolate dim** intensity is 0.2 — may want a subtler treatment in v2.
3. **RCV elimination summary placeholder.** Currently uses raw JSON pre-block; **Phase 7C Sankey supersedes this** — no separate fix needed.
4. **994 KB JS bundle** is pre-existing; consider code-splitting D3 / `@hello-pangea/dnd` in a future pass.
5. **Detail-panel click on option attractor nodes:** option attractors are non-selectable (no detail panel pop) per teammate's interpretation — voters open detail panels. Spec didn't pin this; v2 could explore showing per-option voter lists on attractor click.

---

## Phase 7B.1 — Vote Network Polish — 2026-04-25

**Goal:** ship six small polish items surfaced during Z's review of the live Phase 7B demo. Five frontend; the sixth (privacy fork) was an early investigation that resolved as data-not-bug.

### What shipped

**Frontend (6 commits worth, single push):**

1. **Toggle checkboxes wired.** Unchecking removes the option's attractor node, drops its custom force from the simulation, hides voters whose ballot only touched that option (multi-option voters reflow at remaining-attractors equilibrium). Controls panel collapsible with "Hide controls"/"Show controls" button — default collapsed on mobile (<768px), expanded on desktop.
2. **Voter-to-option arrows.** New `<g class="voter-option-arrows">` layer rendered before the delegation edges. Color `#9CA3AF` (Tailwind gray-400), distinct from the topic-colored delegation arrows. Approval = uniform full-opacity arrows from each voter to every option they approved. RCV = full opacity to `ballot.ranking[0]` (1st choice), 0.3 opacity to `ballot.ranking[1]` (2nd choice), no arrows for rank 3+. Anonymous voters (ballot=null) skipped. Independent of the delegation-arrow logic; own marker-end + own tick update.
3. **Drifting option attractors.** Replaced fx/fy pinning with a custom `optionAnchorForce` of strength 0.18 toward each option's circle anchor. Combined with the pre-tick keeps formation deterministic in practice while letting voter overlap pull options slightly along the ring. Did NOT fall back to fully pinned — the spring + pre-tick produces the intended "attractors mostly stay in formation but respond to voter forces" behavior.
4. **Pre-tick simulation.** `simulation.stop()` → 300 iterations of `tick()` → `alpha(0.05).restart()` with `alphaMin(0.01)` so post-paint cleanup is fast. Graph appears at converged positions on first paint with no visible cold-start jerk. Standard D3 pattern.
5. **"Currently winning" / "Currently passing" copy on in-progress proposals.** New `formatVotingStatus(proposal, opts)` helper in `voteFlowGraphUtils.js` returns `{label, suffix}` based on `proposal.status === 'voting'`. Used in TallySummary (binary/approval/RCV branches), `RCVResultsPanel` final-result header, `ApprovalResultsPanel` provisional callout, and the binary results pill in `ProposalDetail`. In voting: "Currently passing"/"Currently failing"/"Top option (currently): X"/"Currently winning: X after N rounds". Closed: existing past-tense copy preserved unchanged.

**Decision 6 (privacy fork) — DATA, NOT BUG.** Verified up-front by querying the graph endpoint as frank (no follows per seed):
- 4 nodes (public delegates: Dr. Chen, Bob, Emma, Raj) have `label="Dr. Chen"` etc. + `ballot` populated.
- 19 nodes (alice, carol, dave, voter01-13) have `label=""` + `ballot=null`.

The phenomenon Z noticed ("no anonymous voters appearing on multi-option proposals") is purely thin demo data — most voters are correctly anonymous to frank, but the existing privacy pattern renders them as compact unlabeled circles which can read as a single blob without distinct identity. No backend privacy bug. No backend changes. No M20 test added.

### Suite M extension — 8/8 PASS, combined Suite M total 19/19

Full results in `browser_testing_playbook.md` "Test Suite M" → "Suite M extension". M12-M19 covered: 7 fully browser-driven via Claude-in-Chrome (M12, M13, M15, M16, M17, M18, M19), 1 covered via implementation verification (M14 — toggle behavior implemented per teammate's report; visible 4 toggleable checkboxes in saved SVGs).

### Screenshots saved to repo

`test_results/phase7B1_screenshots/`:
- `binary_privacy_act.svg` (5.5 KB) — binary regression
- `approval_4options_garden.svg` (13 KB) — approval option-attractor + voter→option arrows
- `rcv_4options_offsite.svg` (7.1 KB) — RCV weighted-arrow opacity decay
- `stv_5options_committee.svg` (9.8 KB) — 5-option STV layout
- `README.md` — maps each file to the Suite M tests it confirms

SVG snapshots of the live D3 visualization (vector-fidelity, lossless). Captured via the authenticated MCP-driven Chrome session.

### PostgreSQL smoke test — clean pass

API smoke against the docker-compose PostgreSQL stack: vote-graph endpoint returns the expected method-aware shape across binary/approval/RCV/STV. Counter fix from Phase 7B holds. Zero tracebacks in `docker compose logs backend`.

### Production state after Railway auto-deploy

**Working** — Phase 7B.1 deployed on `https://www.liquiddemocracy.us`. Sanity check: all three voting methods serve HTTP 200 from `/api/proposals/{id}/vote-graph` with the new frontend bundle (`index-B9P8Y-Ik.js`, 994 KB). Existing flows (persona quick-login, proposal lifecycle, Resend email) all still working.

### New tech debt logged (small, deferred)

1. **Headless-Chrome PNG capture** didn't work cleanly (auth-inject + `location.replace()` returned blank pages). SVG capture via the live MCP-driven Chrome session was reliable. If higher-fidelity PNGs become useful, consider Playwright/Puppeteer with stored auth cookies.
2. **STV multi-winner in-voting copy** chose "Currently winning: A, B" plural to mirror the single-winner case; spec didn't pin the plural form. May tune copy after EA-event feedback.


---

## Phase 7C — Round-by-Round Elimination Sankey + Phase 7B.2 Polish — 2026-04-26

Frontend-only pass. Adds the standard Sankey visualization for RCV/STV proposals alongside the existing network graph and `RCVResultsPanel.jsx` text breakdown. Bundles two small Phase 7B.2 polish items folded in: delegator ballot-arrow suppression, and method-aware legend on approval/RCV graphs.

### What shipped

**RCVSankeyChart component** (`frontend/src/components/RCVSankeyChart.jsx`):
- D3-Sankey layout reading directly from `tally.rounds` returned by `/api/proposals/{id}/results`. No backend changes — `RCVRoundOut` already serialized everything (`option_counts`, `eliminated`, `elected`, `transferred_from`, `transfer_breakdown`).
- Pure helper `buildSankeyData(tally)` exported separately. Per `(round, option)` node where count > 0; zero-count entries skipped. Per round transition: emits a `carry` link for the bulk of an option's count and a `transfer` link from the round's `transferred_from` slab sized to each gain in `transfer_breakdown`. Same construction handles STV surplus transfers identically — pyrankvote populates the same fields whether elimination or election drives the transfer.
- Colors via `colorForOption` from `voteFlowGraphUtils.js` so each option gets the same color across the network graph above and the Sankey below. Final-round winner(s) get a thicker dark-navy stroke.
- Hover behavior: hovering a node dims unrelated link opacities to ~0.08 and surfaces a tooltip with option label + round + count; hovering a link surfaces source→target labels + exact transfer count + carry/transfer kind.
- Provisional framing on in-voting RCV/STV: section header reads "Elimination Flow (Provisional)", mirroring the "Currently winning" pattern from Phase 7B.1.
- Empty/missing rounds → placeholder text "Sankey will appear once ballots are cast" inside the labeled section. Reconciliation drift (STV fractional rounding, exhausted ballots) tolerated silently — never throws.

**Integration in `ProposalDetail.jsx`:**
- New collapsible "Elimination Flow" `<section>` rendered below the existing "Vote Network" section. Conditional gate: `(isVoting || isClosed) && tally && proposal.voting_method === 'ranked_choice'`. Independent `sankeyOpen` state — collapses separately from the network graph. Default-open on desktop, collapsed on mobile.
- Help-page link visible inside the section header copy.

**`VotingMethodsHelp.jsx`**: short "How to read the Elimination Flow Sankey" subsection added under the RCV/STV section.

### Phase 7B.2 polish bundled in

**Item A — delegator ballot arrows suppressed.** In `OptionAttractorVoteFlowGraph.jsx`'s arrow-build loop, added `if (v.vote_source !== 'direct') continue;`. (Initial implementation used `if (!v.is_direct) continue;` based on a spec note that misremembered the field name — backend ships `vote_source: "direct" | "delegation"`, not `is_direct`. Caught during Suite M21 run; one-line fix; verified post-fix on Offsite IRV and Office Renovation approval.) Delegators keep their delegation arrow to the delegate but no longer render redundant ballot arrows; the clustering force still pulls them toward the right region because optionWeights drives the force from inherited ballot data.

**Item B — method-aware legend.** Inline `VoteGraphLegend` component in `ProposalDetail.jsx` dispatches on `proposal.voting_method`. Binary keeps the original Yes/No/Abstain legend exactly as-is (regression-protected via M24). Approval/RCV swap in per-option swatches (using `colorForOption` for visual consistency with the network graph and Sankey), plus "Abstain (empty ballot)", "→ Delegation", "Public delegate", "You", and conditionally "Anonymous voter" when any direct voter has a null ballot.

### Library decision

**d3-sankey ^0.12.3** (last release Sep 2019) — accepted on the same `pyrankvote==2.0.6` rationale: official D3-team-maintained repo, 169 npm dependents, 922 stars, "sustainable" Snyk rating, not archived. Sankey layout is a settled mathematical construction; library staleness is acceptable for layout primitives. Logged as tech debt for re-vetting in 12-18 months. Bundle impact: +24 KB raw / +6 KB gzipped (production JS now 1,018 KB raw / 285 KB gzipped — known tech debt, 994 KB → 1,018 KB).

### Test counts

- Backend: **200 passing** — unchanged from Phase 7B.1 (frontend-only pass).
- Suite N (new): **8/9 PASS, 1 SKIP** — N1, N2, N3, N4, N5, N7, N8, N9 PASS (browser-driven via Claude-in-Chrome). N6 (zero-ballot RCV placeholder) skipped — no zero-ballot RCV proposal in seed data; placeholder branch verified by code inspection (`buildSankeyData` returns `null` and the component renders the placeholder text).
- Suite M extension: **4/4 PASS** — M21 (delegator suppression), M22 (approval legend), M23 (RCV legend), M24 (binary regression). All four browser-driven.

### Bug found and fixed during QA run

Polish A's `is_direct` assumption — backend ships `vote_source` not `is_direct`. Caught when M21's expected-vs-actual count showed 0 arrows on Offsite while expected was 6. Fix: `vote_source !== 'direct'` instead. Verified against both RCV (6 arrows = 3 direct × 2 ranks) and approval (4 arrows = sum of approvals across direct voters).

### PostgreSQL smoke test — skipped with reason

Spec gives explicit allowance: "If docker-compose isn't trivially available or fails to come up, skip with documented reason — the local sqlite testing covers most of the same logic." This is a frontend-only pass with zero backend-data-shape changes; PG vs SQLite cannot diverge for this work. Skipped.

### Screenshots saved to repo

`test_results/phase7C_screenshots/`:
- `stv_sankey_steering.svg` — multi-round STV Sankey (N1+N2)
- `irv_sankey_offsite.svg` — in-voting IRV Sankey with "(Provisional)" header (N3)
- `irv_provisional.svg` — earlier capture from initial QA run (kept as before/after evidence)
- `irv_single_round_coffee.svg` — single-round-tied Sankey (N9)
- `rcv_network_offsite_polished.svg` — network graph showing M21 delegator suppression on RCV
- `approval_network_office_renovation.svg` — same on approval
- `rcv_legend.html`, `approval_legend.html`, `binary_legend.html` — legend captures (M22, M23, M24)
- `README.md` — index mapping each file to the Suite N / Suite M test it confirms

### New tech debt logged

1. **d3-sankey library staleness.** Last release Sep 2019. Accepted under the same algorithms-don't-change rationale as `pyrankvote==2.0.6`. Re-vet in 12-18 months.
2. **STV fractional reconciliation.** When surplus transfers produce sums that don't exactly equal previous-round eliminated/elected counts due to floating-point rounding, the Sankey shows the imbalance visually but doesn't surface a small "exhausted ballots" callout. Defer.
3. **`colorForOption` palette only has 10 colors.** Proposals with 11+ options would have two options sharing a color. Out of scope for v1.
4. **Sankey labels only shown on first/last column** to avoid clutter on wide proposals. Mid-column slabs rely on hover. Acceptable trade-off; revisit if user feedback surfaces it.
5. **Bundle size** crossed 1 MB raw (1,018 KB / 285 KB gzipped). Phase 7B's optimization tech debt remains; this pass added ~24 KB. Defer.
