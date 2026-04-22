# Phase 4 Cleanup Spec

**Status:** Ready for dev team execution
**Estimated scope:** ~1 week of focused work for the multi-agent team
**Author:** Planning agent (Claude Chat)
**Date:** April 2026

---

## Purpose

Phase 4 shipped the multi-tenancy, admin portal, and deployment infrastructure that made the platform "pilot-ready" in name. Manual testing has since revealed a consistent pattern: several admin features were built but never end-to-end verified, resulting in silent failures, missing UI controls, and dead-end workflows. This spec closes those gaps, adds the automated test coverage that would have caught them in the first place, and establishes testing expectations going forward.

This is **not** a feature pass. No new roadmap items are being implemented here. The goal is to make Phase 4 actually trustworthy.

## Testing Philosophy — Read This First

The human's time is the scarcest resource on this project. Every minute spent on manual verification of "does this work" is a minute not spent on design, planning, or judgment calls only the human can make.

**Operating principle going forward:** Before any feature ships, automated tests must cover it end-to-end. Manual testing is reserved for evaluating feel, identifying missing features, and making design judgments — not for confirming that wired-up functionality actually round-trips.

**Every fix in this spec must ship with:**

1. A backend unit test or integration test that would have caught the original bug
2. A Claude-in-Chrome browser test that exercises the full user-facing flow
3. Documented addition to the browser testing playbook (`browser_testing_playbook.md`)

**If a fix cannot be covered by automated tests, explicitly call that out in the PR description with the reasoning.** Some things genuinely need human judgment (e.g., "does this feel polished?"), but those should be the exception, flagged explicitly, not the default.

---

## Background: What Manual Testing Revealed

A manual admin portal test pass surfaced four confirmed bugs and one architectural deviation from spec. The dev agent has already diagnosed each at the code level. Findings summary:

1. **Org settings silently drop changes to voting defaults and public delegate policy.** Root cause: SQLAlchemy JSON column mutation tracking doesn't detect in-place dict mutation. The `org.settings` object identity doesn't change, so SQLAlchemy skips the UPDATE. Location: `routes/organizations.py` lines 203-206.

2. **Proposal lifecycle has a triple-layered dead end.** (a) Frontend calls `/api/admin/proposals/${id}/advance` which doesn't exist (working endpoint is `/api/proposals/${id}/advance`, no `/admin/` prefix); every advance/withdraw action returns 404 silently. (b) Frontend is missing the draft→deliberation transition button entirely. (c) Backend lacks an org-scoped version of the advance endpoint under `routes/organizations.py`. All three must be fixed.

3. **No way to reactivate a suspended member.** Neither the backend endpoint nor the frontend button exists. Suspension is currently a one-way operation with "remove + re-invite" as the only recovery path.

4. **Moderator role has no effective powers.** The role exists in the data model but has no meaningful capabilities — moderators are indistinguishable from regular members in practice. This blocks adoption by any org with more than one trusted coordinator.

5. **Frontend URL structure deviates from spec.** The original multi-tenancy spec called for path-based org URLs (`/boston-ea/proposals`). What shipped uses flat URLs with org context stored in React state/localStorage. This is a UX regression, not a security issue — the dev agent verified that backend org membership enforcement (`org_middleware.py`) is correctly implemented and purely server-side.

Items 1-4 are in scope for this cleanup. Item 5 is explicitly **deferred** to a separate phase (see "Explicit Non-Goals" below).

---

## Fix 1: Org Settings JSON Mutation Persistence

### Problem

Admin can change org name, description, and join policy in the General section of org settings, and changes persist correctly. But changes to voting defaults and public delegate policy in the same form appear to save (no error shown, success toast if one exists), then revert when the user navigates away and returns.

### Root Cause

In `routes/organizations.py` (approximately lines 203-206):

```python
if body.settings is not None:
    current_settings = org.settings or {}
    current_settings.update(body.settings)
    org.settings = current_settings
```

When `org.settings` already exists as a dict, `current_settings` becomes a reference to the same dict object. Mutating it in place and reassigning doesn't change the object identity, so SQLAlchemy's default JSON change detection skips the UPDATE. The model uses `mapped_column(JSON, default=dict)` without `MutableDict.as_mutable()`, so mutation tracking is not enabled.

### Fix

Replace the in-place mutation with a new-dict construction:

```python
if body.settings is not None:
    org.settings = {**(org.settings or {}), **body.settings}
```

This creates a new dict with a different object identity, triggering SQLAlchemy's change detection and causing the UPDATE to flush.

### Expanded Scope: Pattern Audit

This bug pattern may exist elsewhere. Grep the backend for any other route handler that mutates a JSON column in place:

```bash
grep -rn "\.update(body\." backend/routes/
grep -rn "\.append(" backend/routes/ | grep -i "json\|settings\|config"
```

For each match, verify whether it has the same silent-failure pattern. Fix any additional instances using the same new-dict construction approach. Document all instances found in the PR description.

### Acceptance Criteria

- All fields in `body.settings` persist across save and reload
- Backend test added to `tests/` that calls `PATCH /api/orgs/{slug}` with nested settings fields and verifies persistence by re-fetching the org
- Claude-in-Chrome test added that logs in as admin, changes voting defaults and public delegate policy in org settings, navigates away, navigates back, verifies values persisted
- Any other JSON-mutation instances found in the pattern audit are documented and fixed

---

## Fix 2: Proposal Lifecycle — Three Connected Issues

### Problem

Admin can create a proposal, which correctly lands in `draft` status. From there:
- No UI button to advance draft → deliberation
- Every existing advance/withdraw button silently 404s because the frontend calls a nonexistent endpoint path
- No org-scoped version of the advance endpoint exists in the org-scoped routes

The result is that proposals created through the admin portal are stuck in `draft` forever with no way to advance, edit, or take any other action.

### Fix — Three Parts

**Part A: Fix the frontend endpoint path.**

In `pages/admin/ProposalManagement.jsx` (approximately lines 204 and 214), change the advance and withdraw calls from `/api/admin/proposals/${id}/advance` (nonexistent) to `/api/proposals/${id}/advance` (existing and functional).

Actually, per Part C below, we want these calls to go through the org-scoped endpoint instead: `/api/orgs/${orgSlug}/proposals/${id}/advance`. Finalize the path based on Part C's implementation.

**Part B: Add the missing draft → deliberation button.**

In the same file, the existing expandable-row action UI supports deliberation→voting and voting→closed transitions but has no button for draft status. Add a "Advance to Deliberation" button that appears when `status === 'draft'`. Also add an "Edit" button for draft proposals that routes to an editable view of the proposal (see "Fix 3" below).

**Part C: Add org-scoped advance endpoint.**

In `routes/organizations.py`, add a route handler:

```python
@router.post("/{org_slug}/proposals/{proposal_id}/advance")
async def advance_org_proposal(
    org_slug: str,
    proposal_id: int,
    body: ProposalAdvanceRequest,
    org: Organization = Depends(require_org_admin),  # or whatever the permission gate should be
    db: Session = Depends(get_db)
):
    # Reuse logic from routes/proposals.py advance handler
    # Verify proposal belongs to this org before advancing
    ...
```

Verify the proposal's `org_id` matches the requested org before processing. Return 404 (not 403 — don't leak existence of cross-org resources) if the proposal exists but belongs to a different org.

### Fix 3: Draft Proposal Editability (related)

Draft proposals should be fully editable by their author and by org admins. Verify whether an edit endpoint exists for drafts:

- If `PATCH /api/proposals/{id}` or equivalent exists and works: wire up the "Edit" button added in Part B above to a draft-editing page/modal
- If no edit endpoint exists: build one. Only drafts should be editable; proposals in deliberation or later status should return 400 "cannot edit proposal in {status} status"

### Acceptance Criteria

- Admin can click "Advance to Deliberation" on a draft proposal and it moves to deliberation status
- Admin can click "Advance to Voting" on a deliberation proposal and it moves to voting status
- Admin can click "Close" or equivalent on a voting proposal and it resolves to passed/failed based on current tally
- Admin can edit a draft proposal's title, body, topics, and voting window
- Attempting to edit a non-draft proposal returns a clear error
- Backend integration test covers the full lifecycle: create draft → edit → advance to deliberation → advance to voting → close
- Claude-in-Chrome test covers the full lifecycle through the admin UI
- Browser test playbook updated with the full flow as a standard regression test

---

## Fix 4: Member Reactivation

### Problem

The member management page has a Suspend button that works. After suspension, only a Remove button is shown — no way to reactivate a suspended member. The `OrgMembership.status` field can be set to "suspended" but never back to "active" through any code path.

### Fix

**Backend:** Add `POST /api/orgs/{slug}/members/{user_id}/reactivate` in `routes/organizations.py`, mirroring the existing suspend endpoint. Sets status back to "active". Gated by `require_org_admin` (or the appropriate permission check once Fix 5 lands).

**Frontend:** In `pages/admin/Members.jsx`, add a "Reactivate" button that appears for members with `status === 'suspended'`. Should be the same place the Suspend button appears for active members — one or the other is visible based on status, not both.

### Acceptance Criteria

- Admin can suspend an active member, then reactivate them
- Reactivated member regains full access (can vote, delegate, etc.) immediately on their next request
- Backend test covers suspend → reactivate → suspend cycle, verifying membership status and access rights at each step
- Claude-in-Chrome test covers the same flow through the admin UI

---

## Fix 5: Minimal Moderator Powers (Staging for Roadmap 2.2)

### Problem

The `moderator` role exists in the data model but has no effective powers. This blocks any org with more than one trusted coordinator from functioning well — either everyone gets full admin (too risky) or the one admin becomes a bottleneck for routine tasks.

Roadmap item 2.2 (Configurable Organization Role Permissions) describes the full solution: a permissions-per-role data model with configurable defaults. That's out of scope for this cleanup pass.

### Fix — Minimal Interim Step

Give moderators a small, hardcoded set of capabilities that enable day-to-day operational work without touching destructive actions. Specifically:

**Moderators can:**

- Create proposals (currently admin-only)
- Approve pending member join requests (currently admin-only)
- Suspend members (but not remove them)
- Edit topics (but not delete them)
- Advance proposals they created through the lifecycle (but not proposals created by others, and not delete any proposal)

**Moderators cannot (remains admin-only):**

- Delete proposals, topics, or users
- Remove members from the org
- Edit org settings
- Manage invitations beyond approving pending join requests
- Approve delegate applications
- Change member roles

### Implementation Note

This is deliberately a **hardcoded interim step**, not the start of the full permissions system. Add a simple `require_org_moderator_or_admin` dependency function in `org_middleware.py` alongside the existing `require_org_admin`. Route handlers that should allow moderators switch to the new dependency; everything else stays on `require_org_admin`.

When roadmap item 2.2 is built, this interim pattern gets replaced with a proper `has_permission(user, org, permission_key)` helper. Keep the interim fix simple and contained — don't start designing the full permission system inside this cleanup.

### Acceptance Criteria

- Moderator can create a proposal, see it land in draft, edit it, and advance it through the lifecycle
- Moderator can approve pending join requests
- Moderator can suspend members but not remove them
- Moderator cannot edit org settings (UI should hide or disable admin-only controls)
- Backend tests cover: moderator can/cannot perform each action in the matrix above
- Claude-in-Chrome test covers: log in as moderator, verify visible admin portal pages match moderator permissions (not showing controls they can't use)

---

## Fix 6: Pattern Audit — "Built But Not Tested End-to-End"

### Problem

The Proposal Lifecycle bug (Fix 2) revealed a pattern: features were built but their end-to-end flow was never tested, so 404s, missing buttons, and missing endpoints survived QA. This pattern likely exists elsewhere in the Phase 4 admin portal.

### Fix

Systematically exercise every admin workflow end-to-end and add Claude-in-Chrome tests for each. At minimum, the following flows need end-to-end tests if they don't already have them:

1. **Delegate application flow** (if applicable based on org public_delegate_policy):
   - User applies to be public delegate for a topic
   - Application appears in admin Delegate Applications queue
   - Admin approves with optional feedback
   - User is now registered as public delegate for that topic
   - Test also covers denial path

2. **Topic management:**
   - Admin creates a topic with custom color
   - Topic appears in topic list
   - Topic can be edited (name, color, description)
   - Topic can be deleted
   - Deletion behavior when proposals are tagged with that topic (blocked? orphaned? cascade?) — if the current behavior is unclear or buggy, document and fix

3. **Invitation flow:**
   - Admin creates invitation for an email address
   - Invitation email is sent (or logged to console in dev mode)
   - Invited user registers via the invitation link
   - User lands in the correct org with correct role
   - Invitation cannot be reused
   - Invitation expires after 7 days

4. **Join request flow (when join_policy = approval_required):**
   - User registers and requests to join an org
   - Admin sees pending join request
   - Admin approves → user gains access
   - Admin denies → user does not gain access, gets appropriate notification

5. **Analytics dashboard:**
   - Charts render with actual data (not just smoke-test-empty)
   - Changing time ranges updates the charts correctly
   - Exports (if present) produce valid output

For each flow, document the test in the browser testing playbook. Any bugs discovered during this audit should be fixed as part of this cleanup (minor fixes) or documented as new issues (larger fixes warranting their own spec).

### Acceptance Criteria

- Each of the 5 flows above has an automated Claude-in-Chrome test
- Browser testing playbook updated with documented expected behavior for each
- Any bugs found during audit are either fixed or tracked as explicit follow-ups in the PR description

---

## Fix 7: Email Verification Restrictions (Smoke Test)

### Problem

Phase 4b allegedly blocks unverified users from voting and delegating. This is a pilot-trust-critical claim that hasn't been independently verified end-to-end.

### Fix

Add an automated test covering the full flow:

1. Register a new user with an unverified email
2. Verify the yellow banner appears with resend-link option
3. Attempt to cast a vote → should be blocked with clear error message
4. Attempt to create a delegation → should be blocked with clear error message
5. Attempt to accept a follow request → should be blocked with clear error message
6. Verify the user can still browse proposals and delegates (read-only actions)
7. Verify the email (via console output capture in dev mode, or test email inbox — see "Testing Infrastructure" below)
8. Verify the user can now perform write actions after verification

### Acceptance Criteria

- Automated test covers all 7 steps
- If any step fails (e.g., unverified user CAN vote), it's treated as a security/trust bug and fixed in this pass

---

## Testing Infrastructure

### Dummy Email Setup for Claude-in-Chrome

To enable automated testing of email-dependent flows (verification, password reset, invitations), set up a dedicated dummy email account the QA agent can use.

**Recommended approach:**

Create a Gmail account dedicated to this project (e.g., `liquiddemocracy.qa.dummy@gmail.com`). Use Gmail's `+` aliasing to create variations without needing separate accounts:
- `liquiddemocracy.qa.dummy+user1@gmail.com`
- `liquiddemocracy.qa.dummy+user2@gmail.com`
- etc.

All variations route to the same inbox, making it easy for the QA agent to check for verification emails, invitation links, etc.

Store credentials in a project-level secrets file that's gitignored. The QA agent needs:
- Gmail address
- App password (not the account password — generate via Google account settings)
- Access pattern documented in `browser_testing_playbook.md`

Alternative: Use a disposable email service with API access (e.g., Mailosaur, MailSlurp). These are designed for test automation and avoid any residual risk of the Gmail account being locked. Lower setup effort; some services have free tiers adequate for this volume.

**The human will set this up separately.** The cleanup spec assumes a dummy email is available. If not, email-dependent tests should be skipped with a clear note, not silently omitted.

### Browser Testing Playbook Updates

After this cleanup, `browser_testing_playbook.md` should have a new "Suite H: Phase 4 Regression" covering:

- H.1: Org settings persistence (all fields)
- H.2: Proposal lifecycle (full draft → closed cycle, edit, withdraw)
- H.3: Member suspend/reactivate cycle
- H.4: Moderator role capabilities and restrictions
- H.5: Delegate application flow
- H.6: Topic management
- H.7: Invitation flow
- H.8: Join request approval flow
- H.9: Analytics dashboard
- H.10: Email verification enforcement

Each test should be self-contained: set up required state, execute the flow, verify outcome, clean up.

### Backend Test Coverage

Current backend test count is 73. After this cleanup, expect ~95-110 depending on how many pattern-audit issues are found. Each fix in this spec adds at least one test; the moderator powers matrix alone adds a dozen (one per permission boundary).

All tests should pass on both SQLite (current test DB) and PostgreSQL (production DB). Add a CI configuration or documented manual process for running tests against both, because the SQLAlchemy JSON mutation bug (Fix 1) manifests differently on different databases and we shouldn't regress.

---

## Explicit Non-Goals for This Cleanup

To prevent scope creep, the following are **out of scope** for this pass:

1. **Frontend URL routing refactor (flat → path-based org slugs).** Deferred to a dedicated phase. Ticket it as "Phase 4e: URL Routing Refactor" for a future pass.

2. **Full configurable role permissions (Roadmap 2.2).** Fix 5 in this spec is a minimal interim step. The full permission-matrix system is a future roadmap item.

3. **Any new features from the improvement roadmap.** No multi-option voting, Polis integration, sustained-majority windows, profile pictures, PWA, or WebSocket work in this pass. This is cleanup only.

4. **Refactoring that isn't directly required for fixes.** Avoid the temptation to "clean up this other thing while I'm in here." Discipline matters. If a dev agent notices something worth refactoring, document it as a follow-up issue rather than including it in this cleanup.

5. **Production deployment.** This cleanup prepares the platform for its next feature pass, not for pilot deployment. Deployment prep is a separate workstream.

---

## Dispatch Guidance

This spec is ready for a focused multi-agent pass. Recommended team composition:

- **Lead agent:** Coordinates, tracks progress against acceptance criteria, updates `PROGRESS.md`. Operates in delegate mode (Shift+Tab) to avoid implementing things itself.
- **Dev agent:** Implements Fixes 1-5 sequentially. Runs the pattern audit for Fix 1 and documents findings. Writes unit/integration tests for each fix.
- **QA agent:** Writes Claude-in-Chrome tests for each fix as it lands. Runs Fix 6 (end-to-end pattern audit) and Fix 7 (email verification smoke test). Reports bugs found during audit back to dev for in-scope fixes or to the lead for scoping decisions.

**Sequence:** Fix 1 first (smallest, highest confidence). Fix 4 next (similarly small). Then Fix 5 (defines permission structure that Fix 2 Part C may use). Then Fix 2 (largest, most interconnected). Fix 3 is bundled with Fix 2. Fixes 6 and 7 run in parallel with the others.

**Estimated duration:** 4-6 hours for a well-coordinated team given the scoped clarity of each fix and the diagnostic work already done. Pattern audits (Fix 6) may surface additional work that extends this.

---

## Success Criteria for the Cleanup Pass

The cleanup is complete when:

1. All seven fixes above have landed with their acceptance criteria met
2. Backend test count has grown proportionally, all passing
3. Browser testing playbook has a new Suite H covering Phase 4 regressions
4. `PROGRESS.md` is updated with cleanup completion notes and any follow-up issues surfaced during pattern audits
5. No new features have been added (scope discipline maintained)
6. The human can re-run the original manual test priorities (from the Phase 4 QA checklist) and find them all passing

After that, the human does a final spot-check focused on feel and design judgment — not on verification that things work mechanically. Automated tests cover the latter.
