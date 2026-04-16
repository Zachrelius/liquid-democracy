# Phase 4: Multi-Agent Coordination Plan

## Agent Structure

- **Manager/Architect** (you): Reads specs, breaks work into tasks, assigns to Dev and QA agents, reviews their output, and ensures everything integrates correctly. You own the overall quality and make decisions when the spec is ambiguous.
- **Dev Agent**: Writes code — backend and frontend. Does not make architectural decisions. Asks the manager when the spec is unclear.
- **QA Agent**: Tests via browser (Chrome access required). Does not modify application code. Reports findings to the manager who decides what to fix.

## Key Project Files

- `PROGRESS.md` — current project state, updated after every significant work session
- `phase4_spec.md` — the full Phase 4 specification covering all four sub-phases
- `browser_testing_playbook.md` — existing browser test suites (A through D) plus templates for new suites
- `phase3c_fixes.md` — reference for the fix documentation pattern
- `SECURITY_REVIEW.md` — to be created during Phase 4d

All agents should read `PROGRESS.md` before starting any work.

## Execution Plan

Work through Phase 4 in strict sub-phase order. Each sub-phase follows the same cycle:

1. **Manager** reads the relevant section of `phase4_spec.md` and creates a focused task description for the Dev agent
2. **Dev** implements the task, runs backend tests, and reports completion
3. **Manager** reviews the Dev's report and creates a test plan for the QA agent
4. **QA** executes browser tests and reports results
5. **Manager** reviews QA results, creates fix tasks for Dev if needed, and confirms the sub-phase is complete
6. **Manager** updates `PROGRESS.md` before moving to the next sub-phase

---

## Sub-Phase 4a: Deployment and Infrastructure

### Dev Tasks (in order)
1. Create `Dockerfile` for backend (Python/FastAPI with uvicorn)
2. Create `Dockerfile` for frontend (Node build stage → nginx serve stage)
3. Create `docker-compose.yml` with PostgreSQL, backend, and frontend services
4. Create `.env.example` with all required environment variables
5. Add health check endpoints: `GET /api/health` and `GET /api/health/ready`
6. Update database configuration to use PostgreSQL via DATABASE_URL environment variable
7. Add startup script that runs `alembic upgrade head` before starting the backend
8. Configure production structured JSON logging
9. Test: run `docker-compose up` from scratch, verify the app starts, all Alembic migrations run, and the health endpoints respond
10. Run full backend test suite against PostgreSQL (not SQLite) to catch compatibility issues
11. Write `DEPLOYMENT.md` with quick start, cloud deployment, HTTPS, and backup instructions

### QA Tasks
- Verify `docker-compose up` produces a working app accessible in the browser
- Run existing browser test Suite B (B2-B5) against the Docker deployment to confirm basic functionality
- Verify health endpoints return correct responses
- Verify demo seed data works in the Docker environment

### Manager Checkpoints
- Review Dockerfiles for security (no secrets baked in, non-root user, minimal base images)
- Review `.env.example` for completeness
- Confirm PostgreSQL migration works cleanly
- Confirm all existing tests pass against PostgreSQL

---

## Sub-Phase 4b: Authentication Hardening

### Dev Tasks (in order)
1. Add `email` and `email_verified` fields to users model, Alembic migration
2. Create `email_service.py` — SMTP sending with console fallback when SMTP is not configured
3. Implement email verification flow: token generation, verification endpoint, frontend banner for unverified users, restriction on voting/delegating until verified
4. Create `invitations` model and Alembic migration
5. Implement admin invitation flow: send invite endpoint, invitation email, join-via-invite registration page
6. Implement open-with-approval join flow: request-to-join endpoint, admin approval queue
7. Implement password reset: forgot password endpoint, reset email, reset page
8. Implement refresh token mechanism: short-lived access tokens (15 min), refresh tokens (7 days), logout invalidation
9. Add audit logging for all new auth events
10. Run full test suite

### QA Tasks (new Suite E from phase4_spec.md)
- E1: Health check
- E2: Registration with email verification (check console log for verification link in dev mode)
- E3: Unverified user cannot vote
- E4: Email verification flow
- E5: Password reset flow
- E6: Admin invitation flow

### Manager Checkpoints
- Verify email verification tokens are single-use and time-limited (24 hours)
- Verify password reset tokens are single-use and time-limited (1 hour)
- Verify login error messages don't reveal whether a username exists
- Verify the console fallback for email works correctly in development

---

## Sub-Phase 4c: Admin Portal and Multi-Tenancy

This is the largest sub-phase. Break it into three Dev sessions:

### Dev Session 1: Data Model and API
1. Create `organizations` and `org_memberships` models, Alembic migration
2. Add `org_id` foreign keys to `proposals`, `topics`, `delegate_profiles`
3. Create org-scoped API middleware (extract org_slug from URL path, verify membership)
4. Migrate ALL existing endpoints to be org-aware (this touches nearly everything — work through endpoints methodically, run tests after each batch)
5. Update seed data to work within org context
6. Add `public_delegate_policy` to org settings
7. Create delegate application model and endpoints (submit, approve, deny, list pending)
8. Add audit logging for delegate application events
9. Run full test suite — expect some failures that need fixing due to org-scoping changes

### Dev Session 2: Admin Portal Frontend
1. Admin navigation (visible only to admin/owner roles)
2. Org settings page (name, description, join policy, voting defaults, public delegate policy)
3. Member management page (list, search, role changes, suspend, remove, pending approvals, invite)
4. Proposal management page (create with full options, advance stages, close/withdraw)
5. Topic management page (CRUD, colors, delegation stats)
6. Delegate applications page (pending list with approve/deny/feedback)
7. Analytics dashboard (participation rates, delegation patterns, proposal outcomes — Recharts)

### Dev Session 3: Org UX and First-Run
1. Org selection UI for multi-org users
2. URL structure: `/{org_slug}/proposals`, `/{org_slug}/delegations`, etc.
3. First-run setup wizard (first user → create org → create topics → invite members)
4. Disable seed endpoint when `DEBUG=false`
5. Full integration test: fresh database → register → create org → invite member → member joins → create topic → create proposal → vote

### QA Tasks (new Suite F from phase4_spec.md)
- F1-F9 as defined in the spec
- Additional: test the delegate application flow (apply → pending → admin approves → active)
- Additional: test the first-run experience from a completely fresh database

### Manager Checkpoints
- After Dev Session 1: verify org-scoping middleware works — try accessing org A's data as a member of org B (should fail)
- After Dev Session 2: review admin portal for completeness against spec
- After Dev Session 3: walk through the first-run experience to verify it's coherent
- Verify existing demo mode still works (seed data, quick login)

---

## Sub-Phase 4d: Security Review and Final Polish

### Dev Tasks
1. Systematic OWASP Top 10 review (follow the checklist in phase4_spec.md Part D, Section 1). Document every check and finding in `SECURITY_REVIEW.md`
2. Fix any security issues found
3. Audit all pages for loading states — add skeleton/spinner wherever missing
4. Audit all API calls for error handling — add user-friendly error messages wherever missing
5. Add empty state messages to all list pages
6. Add demo quick-switch login (only when `DEBUG=true`)
7. Mobile responsive pass on all pages including new admin portal
8. Create privacy policy and terms of service pages (use templates from spec)
9. Update project `README.md` with screenshots, features, deployment guide link
10. Final full backend test suite run

### QA Tasks (new Suite G from phase4_spec.md)
- G1-G8 as defined in the spec
- Re-run ALL previous suites (A through F) as final regression
- Mobile testing: run the core user flow (login → view proposal → vote → check delegations → view delegate profile → change delegation) at 375px viewport width

### Manager Checkpoints
- Review `SECURITY_REVIEW.md` for thoroughness
- Verify privacy policy and terms of service are linked from registration page and footer
- Verify demo mode is completely disabled when DEBUG=false (seed endpoint, quick-switch login, any debug UI)
- Final review of all pages for visual consistency and polish

---

## Important Notes for All Agents

**Database:** Starting from Phase 4a, the app runs on PostgreSQL, not SQLite. All development and testing should use PostgreSQL via Docker.

**Org context:** Starting from Phase 4c, nearly every API endpoint requires an org context. The URL pattern is `/api/orgs/{org_slug}/...`. The frontend must include the org slug in all API calls and URLs.

**Backward compatibility:** The demo/seed data must continue to work after every change. If the seed data needs updating to work with new models (org-scoping, email fields), update it. A broken demo is a blocking issue.

**Test-first mindset:** Run existing tests BEFORE writing new code in each session. If anything is already failing, fix it first. Run tests AFTER every significant change. Don't let test failures accumulate.

**PROGRESS.md:** The manager updates this file after each sub-phase is complete. Include: what was built, what tests pass, any known issues, and what's next. This is the handoff document between sessions.
