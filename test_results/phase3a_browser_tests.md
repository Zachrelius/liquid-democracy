# Browser Test Run: 2026-04-14

Server: Backend on :8000, Frontend on :5173
Demo data: Loaded via `POST /api/admin/seed` with `{"scenario":"healthcare"}`

---

## Suite A (API via direct curl calls)

| Test | Name | Result |
|------|------|--------|
| A1 | Demo Data Loading | **PASS** |
| A2 | Authentication Flow | **PASS** |
| A3 | Public Delegate Browsing | **PASS** |
| A4 | Permission-Blocked Delegation | **PASS** |
| A5 | Public Delegate Delegation | **PASS** |
| A6 | Follow → Approve → Delegate | **PASS** |
| A7 | Vote Visibility Permissions | **PASS** |
| A8 | Follow Revocation Cascade | **PASS** |
| A9 | Audit Trail Completeness | **PASS** |

### A1 Details
- `POST /api/admin/seed` returned 23 users including alice, dr_chen, econ_bob, carol, dave, env_emma, rights_raj, admin, voter01–voter13.

### A2 Details
- Login as alice returned JWT token. `/auth/me` returned full profile: id, username, display_name, is_admin, default_follow_policy.

### A3 Details
- `GET /api/delegates/public` returned 4 public delegates: dr_chen (Healthcare + Economy), econ_bob (Economy), env_emma (Environment), rights_raj (Civil Rights). Each has bio text and delegation_counts.
- `GET /api/delegates/public/{healthcare_topic_id}` returned only dr_chen with 10 delegations on Healthcare.

### A4 Details
- Registered testuser1. Attempted delegation to Carol on Healthcare. Got 403 with message: "Cannot delegate to this user for topic ... They are not a public delegate for this topic and you do not have a follow relationship with delegation permission."

### A5 Details
- testuser1 delegated to Dr. Chen on Healthcare — returned 200 with full delegation object. No follow relationship required.

### A6 Details
- testuser1 sent follow request to Carol → status "pending" with message.
- Carol's incoming requests showed testuser1's request alongside voter09's seed request.
- Carol approved with `delegation_allowed` → status changed to "approved".
- testuser1 then successfully delegated to Carol on Environment (200).

### A7 Details
- testuser1 (follows Carol): `GET /api/users/{carol_id}/votes` → 3 votes, all `visible: true` with full vote data.
- testuser2 (no relationship): same endpoint → 3 entries, all `visible: false` with `vote_value: null`.

### A8 Details
- Carol revoked follow relationship with testuser1 → 204.
- testuser1's delegations: Carol/Environment delegation was automatically cascade-revoked. Only Dr. Chen/Healthcare remained (public delegate, no follow needed).

### A9 Details
- Audit log contains all expected events for testuser1 in chronological order:
  - `user.registered` (testuser1)
  - `delegation.created` (testuser1 → dr_chen, Healthcare)
  - `follow.requested` (testuser1 → carol)
  - `follow.approved` (carol approved testuser1, delegation_allowed)
  - `delegation.created` (testuser1 → carol, Environment)
  - `delegation.revoked` (cascade from follow revocation)
  - `follow.revoked` (carol revoked testuser1, includes delegations_revoked list)
- All entries have timestamps, actor_ids, and details JSON.

---

## Suite B (Frontend Integration via Chrome)

| Test | Name | Result |
|------|------|--------|
| B1 | Login Page Loads | **PASS** |
| B2 | Demo Login | **PASS** |
| B3 | Proposals Page | **PASS** |
| B4 | Proposal Detail & Voting | **FAIL** |
| B5 | My Delegations Page | **PASS** |
| B6 | Cross-User Perspective | **PASS** |

### B1 Details
- Login page renders with styled Tailwind UI: "Liquid Democracy" header, Login/Register tabs, username/password fields, Sign In button, Load Demo Scenario section. No console errors.

### B2 Details
- Typed alice / demo1234, clicked Sign In. Redirected to `/proposals`. Nav bar shows "Proposals", "My Delegations", "Alice Voter", "Sign out".

### B3 Details
- Multiple proposals displayed with colored topic badges, status indicators (Voting, Deliberation, Passed), vote tally bars with percentages, vote counts, time remaining.
- "Universal Healthcare Coverage Act" shows Healthcare + Economy (30%) badges, 73% Yes / 27% No, "Your vote: YES via Dr. Chen".
- Filter tabs (All, Deliberation, Voting, Passed, Failed) and topic dropdown present.

### B4 Details — FAILURE
- **Steps 1-3 PASS**: Proposal detail page shows full description, Current Results (11 Yes / 4 No), quorum/threshold indicators. Vote panel shows "YOUR VOTE: YES — Via Dr. Chen" with "Override — Vote Directly" button.
- **Steps 4-6 PASS**: Clicked Override, selected "No". Vote updated to "YOUR VOTE: NO — You voted directly". Tallies updated (9 Yes / 6 No). "Change Vote" and "Retract" buttons appeared.
- **Steps 7-8 FAIL**: Clicked "Retract". Error displayed: `"Failed to execute 'json' on 'Response': Unexpected end of JSON input"`. UI did not update — still showed "NO / You voted directly".
- **Backend state is correct**: After page refresh, vote correctly shows "YES via Dr. Chen" and tallies revert to 11/4. The retract succeeded on the backend.
- **Root cause**: `DELETE /api/proposals/{id}/vote` returns HTTP 204 No Content with `Content-Type: application/json` header but an empty body (0 bytes). The frontend's `api.js` line 37-38 checks Content-Type, sees `application/json`, and calls `res.json()` which throws on the empty body.
- **Fix options**:
  1. **Backend fix** (preferred): Remove `Content-Type: application/json` from 204 responses, or change the endpoint to return 200 with a body like `{"status": "retracted"}`.
  2. **Frontend fix**: In `api.js`, check for 204 status before attempting to parse: `if (res.status === 204) return null;`

### B5 Details
- My Delegations page shows three sections:
  - **Global Default**: "No default delegate set" with "Set Default Delegate" button.
  - **Topic Delegations**: Table with Healthcare → Dr. Chen, Economy → Bob the Economist, Civil Rights → Raj, Defense → Raj. Each row has chain behavior dropdown (Accept sub-delegation / Revert to direct / Abstain) and Change/Remove buttons. Education and Environment show "Not delegated" with "Set Delegate".
  - **Topic Priority**: Numbered drag-to-reorder list (1. Healthcare, 2. Economy, 3. Civil Rights, 4. Environment, 5. Education, 6. Defense).
- **Observation**: Duplicate lowercase topics ("economy", "healthcare") appear as additional rows from an earlier seed run. Not a code bug — data cleanup issue.

### B6 Details
- Logged out as Alice, logged in as dr_chen.
- Proposals page: Nav shows "Dr. Chen". Healthcare proposal shows "Your vote: YES" (direct, no delegation chain). Carbon Tax shows "Your vote: Not cast".
- My Delegations: All topics show "Not delegated" — Dr. Chen has no outgoing delegations.
- No incoming delegation count or "people trust you" indicator visible (feature not yet implemented — Phase 3b scope).

---

## Summary

```
Suite A (API via direct calls):
  A1 Demo Data Loading:            PASS
  A2 Authentication Flow:          PASS
  A3 Public Delegate Browsing:     PASS
  A4 Permission-Blocked Delegation: PASS
  A5 Public Delegate Delegation:    PASS
  A6 Follow → Approve → Delegate:  PASS
  A7 Vote Visibility Permissions:   PASS
  A8 Follow Revocation Cascade:     PASS
  A9 Audit Trail Completeness:      PASS

Suite B (Frontend Integration):
  B1 Login Page Loads:              PASS
  B2 Demo Login:                    PASS
  B3 Proposals Page:                PASS
  B4 Proposal Detail & Voting:      FAIL
  B5 My Delegations Page:           PASS
  B6 Cross-User Perspective:        PASS

Total: 14/15 passed
```

## Bugs Found

### BUG-1: Vote Retract Fails in Frontend (B4)
- **Severity**: Medium — functional regression, data integrity not affected
- **Location**: Backend `DELETE /api/proposals/{id}/vote` + Frontend `src/api.js:37-38`
- **Symptom**: Clicking "Retract" on a direct vote shows error "Failed to execute 'json' on 'Response': Unexpected end of JSON input". UI does not update. Backend operation succeeds.
- **Root cause**: Backend returns 204 No Content with `Content-Type: application/json` and empty body. Frontend calls `res.json()` based on Content-Type header, which throws on empty input.
- **Suggested fix (either or both)**:
  - Backend: Return 200 with `{"status": "retracted"}` instead of 204, or remove the `Content-Type: application/json` header from 204 responses.
  - Frontend: In `src/api.js` `request()` function, add early return for 204: `if (res.status === 204) return null;` before the Content-Type check.

### BUG-2: Seed Data Doesn't Reset Passwords for Existing Users (A1 prerequisite)
- **Severity**: Low — only affects re-seeded environments
- **Location**: `backend/seed_data.py:34-47` (`_get_or_create_user`)
- **Symptom**: Carol could not log in with `demo1234` after re-seeding because she was created in a prior seed run (possibly with a different password hash). The `_get_or_create_user` function returns existing users without updating their password_hash.
- **Suggested fix**: Update password_hash for existing users in `_get_or_create_user`:
  ```python
  if user:
      user.password_hash = hash_password(DEMO_PASSWORD)
      user.display_name = display_name
  ```

## Observations (Non-blocking)

1. **Duplicate topics**: Both "Healthcare"/"healthcare" and "Economy"/"economy" exist as separate topics, likely from multiple seed runs with different casing. The seed's `_get_or_create_topic` does a case-sensitive match.
2. **Carol shows is_admin: true**: In the A6 delegation response, Carol's user object has `is_admin: true`, which seems unintended for a regular user. May be a seed data issue.
3. **No incoming delegation indicator**: Dr. Chen's delegations page has no indicator showing how many users delegate to them. This is acknowledged as Phase 3b scope.
