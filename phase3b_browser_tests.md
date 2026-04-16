# Phase 3b Browser Tests — Append to browser_testing_playbook.md

## Test Suite C: Delegation Permissions Frontend (Phase 3b)

### C1: Follow Request from UI

**Goal:** Verify the follow request flow works through the frontend.

**Steps:**
1. Login as alice
2. Navigate to My Delegations page
3. Click to change or add a delegate on any topic
4. In the search/selection modal, search for "frank" (a user Alice doesn't follow)
5. Verify frank shows as "Not following" with "Request Follow" and "Request Delegate" buttons
6. Click "Request Follow"
7. Verify confirmation feedback appears (success message or status change to "pending")

**Expected:** Frank appears in search results with correct unfollowed status. After clicking Request Follow, the UI confirms the request was sent. Frank now shows as "pending" if searched again.

**Result:** ___

### C2: Delegation Intent (Request Delegate)

**Goal:** Verify the combined follow + delegation intent flow works.

**Steps:**
1. Login as alice
2. Navigate to My Delegations page
3. Open delegate selection for a topic where alice doesn't have a delegate (or remove an existing one first)
4. Search for a user Alice doesn't follow (use a demo user or register a new one)
5. Click "Request Delegate" instead of "Request Follow"
6. Verify the UI shows a pending state: something like "Pending approval — will activate when [name] approves"

**Expected:** Request is sent. The delegation row shows a pending/waiting indicator. The outgoing requests section (if visible) shows the pending intent with topic and expiration info.

**Result:** ___

### C3: Approving a Follow Request

**Goal:** Verify the incoming request approval flow works from the approver's side.

**Steps:**
1. Login as the user who received the follow request from C1 (frank)
2. Navigate to My Delegations page (or wherever incoming requests appear)
3. Find the incoming request from Alice
4. Verify three response buttons are visible: Deny, Accept Follow (view only), Accept Delegate
5. Click "Accept Follow (view only)"
6. Verify the request disappears from pending and a confirmation is shown

**Expected:** Request is visible with all three options. After approval, the request is removed from the pending list. Alice now appears in frank's followers list (if visible).

**Result:** ___

### C4: Delegation Intent Auto-Activation

**Goal:** Verify that approving a delegation request auto-creates the delegation.

**Steps:**
1. If the delegation intent from C2 is still pending, login as the target user
2. Find the incoming request (which was a delegate request)
3. Click "Accept Delegate"
4. Login as alice
5. Navigate to My Delegations
6. Check whether the delegation is now active (no longer showing "pending")

**Expected:** After the target approves with delegate permission, Alice's delegation is automatically activated. The My Delegations page shows the delegate as active, not pending.

**Result:** ___

### C5: Public Delegate — Direct Delegation

**Goal:** Verify that delegating to a public delegate skips the permission flow entirely.

**Steps:**
1. Login as a user who does NOT currently delegate to dr_chen (register a new user or use one without that delegation)
2. Navigate to My Delegations
3. Open delegate selection for the Healthcare topic
4. Search for "chen"
5. Verify Dr. Chen shows as "Public Delegate" with a direct "Delegate" button (no request needed)
6. Click "Delegate"
7. Verify the delegation is created immediately (no pending state)

**Expected:** Dr. Chen's search result shows public delegate badge, bio, and delegation count. Single click creates the delegation. No follow request flow needed.

**Result:** ___

### C6: User Profile — Public Delegate View

**Goal:** Verify the user profile page shows public delegate info and voting record correctly.

**Steps:**
1. Login as any user
2. Navigate to Dr. Chen's profile (search for chen, click their name, or navigate to /users/{chen_id})
3. Observe the profile page

**Expected:** Profile shows Dr. Chen's display name, public delegate badge for Healthcare and Economy, bio text for each topic, delegation counts, and their voting record on Healthcare and Economy proposals. Voting record is visible because these are public delegate topics.

**Result:** ___

### C7: User Profile — Permission-Gated Voting Record

**Goal:** Verify that non-public voting records are hidden from users without follow permission.

**Steps:**
1. Login as a user who does NOT follow Carol and Carol is NOT a public delegate
2. Navigate to Carol's profile
3. Observe the voting record section

**Expected:** Carol's profile shows basic info (display name, username) but voting record shows "Follow Carol to see their voting record" or "Private" indicators instead of actual votes. A "Request Follow" button is visible.

**Result:** ___

### C8: Notification Badge

**Goal:** Verify the notification indicator shows correct counts and links.

**Steps:**
1. Login as a user who has pending follow requests and/or unresolved votes (alice with demo data should have some)
2. Observe the navigation bar for a notification badge
3. Click the notification indicator
4. Verify the dropdown shows relevant items with links

**Expected:** A numbered badge appears in the nav. Dropdown lists pending follow requests and proposals needing attention. Clicking an item navigates to the relevant page.

**Result:** ___

### C9: Cross-User Delegation Flow (End-to-End)

**Goal:** Full end-to-end test of the complete delegation permission lifecycle through the frontend.

**Steps:**
1. Register a brand new user "e2e_tester" through the frontend registration form
2. Login as e2e_tester
3. Go to My Delegations, try to delegate Healthcare to Dr. Chen → should succeed (public delegate)
4. Go to My Delegations, try to delegate Environment to env_emma → should succeed (public delegate)
5. Search for Carol, click "Request Delegate" for Economy
6. Observe pending state in delegations
7. Logout, login as Carol
8. Find and approve the request with "Accept Delegate"
9. Logout, login as e2e_tester
10. Check My Delegations — Economy should now show Carol as active delegate
11. Go to a proposal tagged Economy — verify vote status shows delegation to Carol
12. Cast a direct vote on the proposal — verify it overrides the delegation
13. Retract the direct vote — verify it reverts to Carol's delegation

**Expected:** Every step succeeds. The full lifecycle — public delegation, private delegation request, approval, auto-activation, vote via delegation, direct override, retraction — works through the frontend UI.

**Result:** ___

### C10: Regression — Previous Phase Tests

**Goal:** Verify Phase 2 functionality still works after Phase 3b changes.

**Steps:**
1. Re-run tests B2 through B5 from the original browser testing playbook (Demo Login, Proposals Page, Proposal Detail & Voting, My Delegations Page)

**Expected:** All previously passing tests still pass. No regressions from the Phase 3b additions.

**Result:** ___

---

## Updated Summary Template

Add to the existing summary:

```
Suite C (Delegation Permissions Frontend — Phase 3b):
  C1 Follow Request from UI:           [PASS/FAIL]
  C2 Delegation Intent:                [PASS/FAIL]
  C3 Approving Follow Request:         [PASS/FAIL]
  C4 Intent Auto-Activation:           [PASS/FAIL]
  C5 Public Delegate Direct:           [PASS/FAIL]
  C6 Profile — Public Delegate View:   [PASS/FAIL]
  C7 Profile — Permission-Gated:       [PASS/FAIL]
  C8 Notification Badge:               [PASS/FAIL]
  C9 End-to-End Delegation Flow:       [PASS/FAIL]
  C10 Regression (B2-B5):              [PASS/FAIL]
```

Save results to `test_results/phase3b_browser_tests.md`.
