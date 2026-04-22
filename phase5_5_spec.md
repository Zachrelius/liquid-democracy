# Phase 5.5 — Bug Triage from Phase 5

**Type:** Cleanup pass. No new features.
**Dependencies:** Phase 5 complete (current `master`).
**Goal:** Fix three real bugs discovered during Phase 5 execution before dispatching Phase 6.

---

## Context

Phase 5 surfaced four new technical debt items in `PROGRESS.md`. Three of them are real bugs in core flows (members listing, email verification, registration onboarding). The fourth (toast success consistency) is UX inconsistency that can ride with a later frontend-touching pass. Phase 5.5 addresses the three real bugs only.

**Priority rationale:** We're on a path to pilot-ideal. Phase 6 (multi-option voting) will involve creating new users for internal testing and running them through the full registration → verify-email → vote flow. The verify-email 500 and the registration auto-join gap both break that flow. The members backend filtering bug means moderator QA is partially broken. Fixing these now is cheap insurance and clears the deck.

**Explicit non-goal:** The toast success gap (some success paths close the form without calling `toast.success()`) is deferred. Phase 6 will introduce new success paths in the multi-option proposal creation flow anyway; a consistent toast-success audit should happen at the end of Phase 6, not as its own pass.

---

## Fix 1 — Members Backend Returns Empty for Moderator Users

### The bug

Phase 5 Fix 2 decoupled the frontend fetch for members vs invitations. The frontend change landed correctly (confirmed by browser test I10 regression against Suite H11, where the admin view works). However, Suite I4 tested the moderator view and found that the backend endpoint `GET /api/orgs/{slug}/members` itself returns an empty list when called by a moderator.

The frontend coupling bug was real but was masking a second bug behind it. Now that coupling is fixed, the backend issue is visible.

### What we know

The endpoint `GET /api/orgs/{slug}/members` in `backend/routes/organizations.py`:

```python
@router.get("/{org_slug}/members", response_model=list[schemas.OrgMemberOut])
def list_members(
    org_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
```

The dependency `require_org_membership` permits any active member (not just admin/moderator), and the query itself has no role-based filter — it returns all memberships for the org, regardless of caller role. So at face value, a moderator should see the same list as an admin.

The bug is somewhere else. Candidate causes the dev team should investigate (in rough order of likelihood):

1. **Moderator test user isn't actually an active moderator in the seeded org.** Check that Carol (or whoever the moderator is in demo data) has `role='moderator'` and `status='active'` on their `OrgMembership` row for the demo org. If Carol is `status='suspended'` or her membership is missing, `require_org_membership` returns 403, and the frontend's silent catch turns that into an empty list. This is not a backend filter bug — it's a data/dependency issue.
2. **Frontend sends a stale or wrong org slug.** If the moderator's `currentOrg` context resolves to a different org slug than the one they're a member of, the endpoint returns 403 for the wrong org. Check the network tab in the browser during the failing test to confirm the slug being sent.
3. **Moderator's org_id mismatch.** Possible but less likely: the seed data creates the moderator's membership under a different `org_id` than what `org_slug` resolves to.
4. **Actual backend filter bug in list_members.** Least likely given the code, but worth reading the function line-by-line to rule out.

### Scope

1. Reproduce the bug locally. Login as the moderator demo user (Carol), open the browser's network tab, navigate to `/admin/members`, and inspect the actual HTTP response from `GET /api/orgs/{slug}/members`.
2. Based on the actual response (200 with empty list vs 403 vs 404 vs something else), diagnose the root cause.
3. Fix it. The fix will depend on the diagnosis — most likely a seed-data correction or a small backend change.
4. Add or update a backend unit test that specifically exercises "moderator calls list_members and gets the full member list."
5. Re-run Suite I test I4 to confirm it passes. Update the Suite I entry in `browser_testing_playbook.md` from FAIL to PASS.

### Acceptance criteria

- A backend unit test verifies a moderator user calling `GET /api/orgs/{slug}/members` receives a populated list containing all active org members.
- Browser test I4 passes.
- The root cause is documented in the Phase 5.5 section of `PROGRESS.md` (e.g., "the demo user Carol was seeded as suspended, not active" — whatever it actually turns out to be).

---

## Fix 2 — Email Verification Endpoint Returns 500

### The bug

`POST /api/auth/verify-email` returns a 500 server error. Found during Suite I testing. This is a regression in a critical user flow — every new user who registers gets a verification email, clicks the link, and currently hits a server error.

### What we know

The endpoint in `backend/routes/auth.py`:

```python
@router.post("/verify-email", status_code=200)
def verify_email(
    body: schemas.VerifyEmailRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    now = _now()
    record = db.query(models.EmailVerification).filter(
        models.EmailVerification.token == body.token,
    ).first()

    if not record or record.verified_at is not None or record.expires_at < now:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired verification token",
        )

    record.verified_at = now
    user = db.get(models.User, record.user_id)
    if user:
        user.email_verified = True

    log_audit_event(
        db,
        action="user.email_verified",
        target_type="user",
        target_id=record.user_id,
        actor_id=record.user_id,
        details={"email": record.email},
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    return {"message": "Email verified successfully"}
```

Nothing in this code obviously 500s, so the bug is runtime-specific. Possibilities:

1. Schema mismatch — `VerifyEmailRequest` expects a field the frontend isn't sending (or vice versa), causing Pydantic to raise and FastAPI to return 500 instead of 422 for some reason.
2. Database constraint violation — e.g., the audit log table has a non-null `actor_id` foreign key and `record.user_id` is somehow invalid. Unlikely but possible.
3. Datetime comparison issue — `record.expires_at < now` comparing naive and aware datetimes on SQLite vs PostgreSQL. This is the kind of thing that lurks in Python datetime code and only surfaces in certain environments.
4. Missing field on `EmailVerification` model that the query expects.
5. Something specific to how the frontend is calling the endpoint (e.g., sending the token in the wrong place).

### Scope

1. Reproduce the 500 locally. Get the actual stack trace from the server logs.
2. Fix based on the stack trace. Most of these are one-liner fixes once you know the cause.
3. Add a backend unit test that exercises the happy path of verify-email (register, get token, call verify-email, confirm success and `email_verified=True`). If this test didn't exist before Phase 4b landed, that's a gap worth filling.
4. Also add a test for the error paths: invalid token returns 400, expired token returns 400, already-verified token returns 400.

### Acceptance criteria

- `POST /api/auth/verify-email` with a valid token returns 200 and sets `user.email_verified = True`.
- Invalid, expired, and already-used tokens return 400 (not 500).
- New backend tests for happy and error paths, all passing.
- Root cause documented in Phase 5.5 section of `PROGRESS.md`.

---

## Fix 3 — Registration Auto-Join Gap for Approval-Required Orgs

### The bug

Phase 5 team described this as: "When join_policy is approval_required, newly registered users aren't added to the org pending approval. Pre-existing."

### What we need to clarify first

Reading the current code, `/api/auth/register` does not touch org membership at all. Registration creates a user; org membership is separate and happens through:
- `POST /api/orgs/{slug}/join` (explicit join request — respects `join_policy`)
- `POST /api/orgs/join/{token}` (invitation acceptance — creates active membership)
- First-run setup where the first registered user creates an org and becomes owner

So "registration doesn't auto-join" is correct for non-invited users who haven't explicitly joined. The question is: what flow did the QA agent actually try, and what did they expect?

Two scenarios where a bug is real:

**Scenario A:** User receives an invitation email with a link, registers through that link, and expects to be a member of the inviting org immediately. If registration via invitation link doesn't consume the invitation and create the membership, that's a real bug.

**Scenario B:** Admin sets join policy to `approval_required`, a new user registers, and the admin expects to see that user in the pending-approvals list. This wouldn't actually be a bug given current design — the user has to explicitly request to join. But it might be surprising UX.

### Scope

1. Talk to the QA agent (or check the Suite I failure notes) to confirm which scenario triggered the report. Read the browser test steps if Suite I captured them.
2. If Scenario A: this is a real bug in the invitation-acceptance flow. Fix it. The expected behavior is: user registers via `/accept-invitation?token=X`, registration creates the user AND consumes the invitation AND creates the `OrgMembership` with status matching the invitation role. Add backend tests for the full register-via-invitation flow.
3. If Scenario B: this is UX confusion, not a backend bug. Document the expected behavior in the settings page ("Members who register still need to explicitly request to join. Invite them directly to skip the request step.") and don't change the backend.
4. If something else entirely: adjust the spec accordingly and report back to the planning agent.

### Acceptance criteria

- The scenario behind the bug report is clearly identified and documented in the Phase 5.5 section of `PROGRESS.md`.
- If it's Scenario A: registration via invitation link creates the membership correctly. Backend test covers the flow.
- If it's Scenario B: UX text is updated on the relevant page and no backend change is made.
- Either way: the issue is closed out, not left in ambiguous technical-debt purgatory.

---

## Testing

### Backend tests

- Fix 1: Moderator-can-list-members test.
- Fix 2: Email verification happy path and three error paths.
- Fix 3 (Scenario A only): Registration-via-invitation test.

Target: all existing backend tests still pass, at least 3-5 new tests added depending on which fixes require what.

### Browser tests — update Suite I

- Update I4 to PASS after Fix 1.
- If Fix 2 requires QA validation, add a new I11 test for "verify email with valid token succeeds."
- If Fix 3 is Scenario A, add a new I12 test for "register via invitation link becomes member."

Suite I should end at 10/10 or 11/11 or 12/12 passing (depending on how many new tests are added), all committed to `browser_testing_playbook.md`.

---

## Process note for the team

A brief retrospective on Fix 2 from Phase 5 is worth the team's attention before starting Phase 5.5. Fix 2 (Members coupling) shipped with a subtle issue: the fix correctly decoupled the fetches, but the verification appears to have checked only that the members fetch didn't throw — not that it actually returned populated data. QA caught it, which is the right backstop, but it's worth spending a minute on the habit being exercised.

Suggested habit: "when fixing a bug, verify the happy path returns the expected data, not just that the error symptom is gone." This is a small phrasing difference but it changes what "done" feels like. Not a blame item — process improvement for future passes. The dev agent for Fix 2 did good work. This is about the verification step between dev and QA.

---

## Definition of Done

- All three fixes implemented and tested.
- Backend tests still pass with new tests added: `cd backend && python -m pytest tests/ -v`.
- Suite I updated with Fix 1's test moving to PASS and any new tests committed.
- `PROGRESS.md` updated with Phase 5.5 section documenting:
  - What was diagnosed for each bug (root cause, not just what was fixed)
  - Whether Fix 3 was Scenario A or B
  - Any new technical debt surfaced
- Three resolved items moved from Open to Resolved in the technical debt section.
- Toast success gap remains in the Open list — intentional, will be addressed in Phase 6 wrap-up.

---

## Out of Scope

- Toast success consistency (deferred to Phase 6 wrap-up)
- Any other bugs not listed above — log to technical debt rather than fixing inline
- Phase 6 multi-option voting prep work — do not start on this until Phase 5.5 is complete
