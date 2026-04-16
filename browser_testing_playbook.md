# Browser Testing Playbook

## Overview

This document defines browser-based integration tests for the liquid democracy platform. These tests are executed by Claude Code using Claude in Chrome, navigating the actual running application to verify end-to-end functionality.

These tests complement (not replace) the automated code tests. Code tests verify logic in isolation. Browser tests verify that the full stack — frontend, API, database, auth — works together as a user would experience it.

## Prerequisites

Before running browser tests:
1. Backend server is running at http://localhost:8000
2. Frontend dev server is running at http://localhost:5173 (or whatever port Vite uses)
3. Database has been reset and demo data loaded (run the seed endpoint or script)

If either server is not running, start them before proceeding.

## How to Use This Document

Each test scenario has:
- **Goal**: What we're verifying
- **Steps**: Exact actions to take in the browser
- **Expected**: What should happen at each step
- **Result**: Record PASS or FAIL with notes

After running all scenarios, produce a summary report at the end listing: total tests, passed, failed, and details on any failures including screenshots if possible.

---

## Test Suite A: API Smoke Tests via FastAPI Docs

Navigate to http://localhost:8000/docs for these tests.

### A1: Demo Data Loading

**Goal:** Verify demo data loads correctly and the system is ready for testing.

**Steps:**
1. Navigate to http://localhost:8000/docs
2. Find the demo/seed data endpoint (likely POST /api/admin/seed or similar — check available endpoints)
3. Execute it
4. Verify response shows created users, topics, proposals, delegations, and follow relationships

**Expected:** Response includes a list of demo usernames and a message confirming data was loaded. No errors.

**Result:** ___

### A2: Authentication Flow

**Goal:** Verify login works and returns a valid token.

**Steps:**
1. Find POST /api/auth/login
2. Execute with: `{"username": "alice", "password": "demo1234"}`
3. Copy the token from the response
4. Click the "Authorize" button at the top of the page
5. Enter the token (with "Bearer " prefix if required by the scheme)
6. Execute GET /api/auth/me

**Expected:** Login returns a token. /auth/me returns Alice's user info including display_name and user_id.

**Result:** ___

### A3: Public Delegate Browsing

**Goal:** Verify public delegates are visible and filterable.

**Steps:**
1. Ensure authorized as Alice (from A2)
2. Execute GET /api/delegates/public
3. Note which users appear and their topics
4. Execute GET /api/delegates/public/{healthcare_topic_id} (use the healthcare topic ID from the demo data)

**Expected:** Dr. Chen appears as a public delegate for Healthcare (and possibly Economy). The topic-filtered endpoint returns only delegates for that topic. Each delegate entry includes bio text and delegation count.

**Result:** ___

### A4: Permission-Blocked Delegation

**Goal:** Verify that delegation to a non-public, non-followed user is rejected.

**Steps:**
1. Register a new user: POST /api/auth/register with `{"username": "testuser1", "display_name": "Test User", "password": "test12345"}`
2. Login as testuser1 and authorize
3. Attempt PUT /api/delegations with `{"delegate_id": "<carol_user_id>", "topic_id": "<healthcare_topic_id>", "chain_behavior": "accept_sub"}` (Carol is not a public delegate and testuser1 doesn't follow her)

**Expected:** Returns 403 with a message explaining that delegation is not permitted — Carol is not a public delegate for this topic and no follow relationship with delegation permission exists.

**Result:** ___

### A5: Public Delegate Delegation (No Permission Needed)

**Goal:** Verify delegation to a public delegate works without a follow relationship.

**Steps:**
1. Still authorized as testuser1
2. Execute PUT /api/delegations with `{"delegate_id": "<dr_chen_user_id>", "topic_id": "<healthcare_topic_id>", "chain_behavior": "accept_sub"}`

**Expected:** Returns success (200 or 201). Delegation is created. No follow relationship was required because Dr. Chen is a public delegate for healthcare.

**Result:** ___

### A6: Follow Request → Approval → Delegation Flow

**Goal:** Verify the complete private delegation lifecycle.

**Steps:**
1. Still as testuser1: send a follow request to Carol via POST /api/follows/request with `{"target_id": "<carol_user_id>", "message": "Hi Carol, I'd like to follow your votes"}`
2. Verify response shows request created with status "pending"
3. Login as Carol (logout testuser1, login carol)
4. Execute GET /api/follows/requests/incoming
5. Find testuser1's request. Execute PUT /api/follows/requests/{id}/respond with `{"status": "approved", "permission_level": "delegation_allowed"}`
6. Verify response confirms approval
7. Login as testuser1 again
8. Retry the delegation to Carol: PUT /api/delegations with `{"delegate_id": "<carol_user_id>", "topic_id": "<environment_topic_id>", "chain_behavior": "accept_sub"}`

**Expected:** Follow request succeeds (step 2). Carol sees the request (step 4). Approval creates the relationship (step 6). Delegation now succeeds (step 8) because the follow relationship with delegation_allowed permission exists.

**Result:** ___

### A7: Vote Visibility Permissions

**Goal:** Verify that vote visibility respects the permission model.

**Steps:**
1. As testuser1 (who now follows Carol): Execute GET /api/users/{carol_id}/votes
2. Note whether Carol's votes are visible
3. Login as a different user who does NOT follow Carol (register testuser2 if needed)
4. Execute GET /api/users/{carol_id}/votes

**Expected:** testuser1 can see Carol's votes (follow relationship exists). testuser2 cannot — votes show as "private" or are excluded.

**Result:** ___

### A8: Follow Revocation Cascade

**Goal:** Verify that revoking a follow relationship auto-revokes dependent delegations.

**Steps:**
1. Login as Carol
2. Execute GET /api/follows/followers to find the follow relationship with testuser1
3. Execute DELETE /api/follows/{relationship_id} to revoke
4. Login as testuser1
5. Execute GET /api/delegations to list current delegations
6. Check whether the delegation to Carol on environment still exists

**Expected:** The delegation to Carol is gone — it was automatically revoked when Carol revoked the follow relationship. The environment topic should show no delegate for testuser1 (unless they have a global fallback).

**Result:** ___

### A9: Audit Trail Completeness

**Goal:** Verify the audit log captured every action from the previous tests.

**Steps:**
1. Login as an admin user (alice or whichever has admin access)
2. Execute GET /api/audit with a filter for actions by testuser1 (or recent timestamps)
3. Review the returned entries

**Expected:** The audit log contains entries for (in chronological order):
- user.registered (testuser1)
- delegation.created (testuser1 → dr_chen on healthcare)
- follow.requested (testuser1 → carol)
- follow.approved (carol approved testuser1)
- delegation.created (testuser1 → carol on environment)
- follow.revoked (carol revoked testuser1)
- delegation.revoked (testuser1 → carol auto-revoked)

All entries have timestamps, actor_ids, and details JSON with relevant context.

**Result:** ___

---

## Test Suite B: Frontend Integration Tests

Navigate to http://localhost:5173 for these tests.

### B1: Login Page Loads

**Goal:** Verify the frontend loads and the login page renders.

**Steps:**
1. Navigate to http://localhost:5173
2. Observe the page

**Expected:** Login form with username and password fields, login button, and a register option. No console errors. Page is styled (not raw HTML).

**Result:** ___

### B2: Demo Login

**Goal:** Verify login works through the frontend UI.

**Steps:**
1. If a demo quick-login selector exists, use it to log in as Alice. Otherwise, type username "alice" and password "demo1234" and click login.
2. Observe the page after login

**Expected:** Redirected to proposals page (or dashboard). Navigation bar appears with links to Proposals, My Delegations, etc. Alice's name or username is visible in the nav.

**Result:** ___

### B3: Proposals Page

**Goal:** Verify proposals display correctly with vote status.

**Steps:**
1. Navigate to the proposals page (click Proposals in nav)
2. Observe the list of proposals
3. Look for the "Universal Healthcare Coverage Act" proposal

**Expected:** Multiple proposals visible with topic badges, status indicators, and vote tallies. The Healthcare proposal shows its topics (Healthcare, Economy) with colored badges. If in voting status, a vote tally bar is visible. Alice's vote status is shown (should indicate voting via delegation to Dr. Chen).

**Result:** ___

### B4: Proposal Detail and Voting

**Goal:** Verify the proposal detail page shows delegation status and allows direct voting.

**Steps:**
1. Click on the "Universal Healthcare Coverage Act" proposal
2. Observe the detail page
3. Look for the vote panel showing Alice's current vote status
4. If an "Override — Vote Directly" button exists, click it
5. Cast a direct "No" vote
6. Observe the vote status update
7. If a "Retract Vote" button exists, click it
8. Observe the vote status revert

**Expected:**
- Step 3: Vote panel shows "Your vote: Yes via Dr. Chen" (or similar)
- Step 5-6: Vote changes to "Your vote: No (direct)"
- Step 7-8: Vote reverts to delegation: "Your vote: Yes via Dr. Chen"
- Vote tallies update after each action

**Result:** ___

### B5: My Delegations Page

**Goal:** Verify the delegations page shows current delegations and allows management.

**Steps:**
1. Navigate to My Delegations page
2. Observe the delegation list
3. Look for Healthcare → Dr. Chen delegation
4. Look for the topic precedence ordering section
5. If available, try changing the chain behavior dropdown on one delegation
6. If available, try reordering topic precedence via drag-and-drop

**Expected:**
- Delegation table/cards show Alice's delegations per topic
- Each row shows the delegate name, topic, and chain behavior
- Topic precedence section shows the priority ordering
- Changes save without errors (check that no error messages appear)

**Result:** ___

### B6: Cross-User Perspective

**Goal:** Verify the system looks different from different users' perspectives.

**Steps:**
1. Logout (find logout button in nav or user menu)
2. Login as dr_chen (password: demo1234)
3. Navigate to My Delegations page
4. Navigate to proposals and check a Healthcare proposal

**Expected:** Dr. Chen's delegations page shows different (or no) outgoing delegations. On the proposals page, Dr. Chen's vote shows as direct (not via delegation). If a delegation count or "people trust you" indicator exists, Dr. Chen should show incoming delegations from Alice and others.

**Result:** ___

---

## Test Summary Template

After completing all tests, fill in this summary:

```
Browser Test Run: [date]
Server: Backend on :8000, Frontend on :5173
Demo data: Loaded via [method]

Suite A (API via FastAPI Docs):
  A1 Demo Data Loading:        [PASS/FAIL]
  A2 Authentication Flow:      [PASS/FAIL]
  A3 Public Delegate Browsing: [PASS/FAIL]
  A4 Permission-Blocked Delegation: [PASS/FAIL]
  A5 Public Delegate Delegation:    [PASS/FAIL]
  A6 Follow → Approve → Delegate:  [PASS/FAIL]
  A7 Vote Visibility Permissions:   [PASS/FAIL]
  A8 Follow Revocation Cascade:     [PASS/FAIL]
  A9 Audit Trail Completeness:      [PASS/FAIL]

Suite B (Frontend Integration):
  B1 Login Page Loads:          [PASS/FAIL]
  B2 Demo Login:                [PASS/FAIL]
  B3 Proposals Page:            [PASS/FAIL]
  B4 Proposal Detail & Voting:  [PASS/FAIL]
  B5 My Delegations Page:       [PASS/FAIL]
  B6 Cross-User Perspective:    [PASS/FAIL]

Total: __/15 passed
Failures: [details of any failures]
Notes: [any observations, UI issues, or suggestions]
```

Save this completed summary to `test_results/phase3a_browser_tests.md` in the project root.

---

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

## Updated Test Summary Template

After completing all tests, fill in this summary:

```
Browser Test Run: [date]
Server: Backend on :8000, Frontend on :5173
Demo data: Loaded via [method]

Suite A (API via FastAPI Docs):
  A1 Demo Data Loading:        [PASS/FAIL]
  A2 Authentication Flow:      [PASS/FAIL]
  A3 Public Delegate Browsing: [PASS/FAIL]
  A4 Permission-Blocked Delegation: [PASS/FAIL]
  A5 Public Delegate Delegation:    [PASS/FAIL]
  A6 Follow → Approve → Delegate:  [PASS/FAIL]
  A7 Vote Visibility Permissions:   [PASS/FAIL]
  A8 Follow Revocation Cascade:     [PASS/FAIL]
  A9 Audit Trail Completeness:      [PASS/FAIL]

Suite B (Frontend Integration):
  B1 Login Page Loads:          [PASS/FAIL]
  B2 Demo Login:                [PASS/FAIL]
  B3 Proposals Page:            [PASS/FAIL]
  B4 Proposal Detail & Voting:  [PASS/FAIL]
  B5 My Delegations Page:       [PASS/FAIL]
  B6 Cross-User Perspective:    [PASS/FAIL]

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

Total: __/25 passed
Failures: [details of any failures]
Notes: [any observations, UI issues, or suggestions]
```

Save completed summaries to `test_results/` in the project root.

---

## Test Suite D: Delegation Graph Visualization (Phase 3c)

### D1: Proposal Vote Flow Graph Renders

**Goal:** Verify the vote flow graph appears on a proposal detail page and renders without errors.

**Steps:**
1. Login as alice (demo data loaded)
2. Navigate to a proposal in "voting" status (e.g., "Universal Healthcare Coverage Act")
3. Scroll down past the vote results bar
4. Look for the "Vote Network" section

**Expected:** A force-directed graph is visible with multiple nodes and edges. No console errors. Nodes are color-coded (green for yes, red for no). At least two visually distinct clusters are visible (yes voters and no voters). A legend is present explaining the visual encoding.

**Result:** ___

### D2: Graph Node Identification

**Goal:** Verify the current user and key delegates are identifiable in the graph.

**Steps:**
1. On the same proposal graph from D1
2. Find Alice's node (should be visually highlighted/distinct)
3. Find Dr. Chen's node (should be one of the larger nodes)
4. Observe the relative sizes of nodes

**Expected:** Alice's node has a distinct visual treatment (different border color or glow) making it immediately findable. Dr. Chen's node is larger than most others because they carry multiple delegated votes. Nodes with more delegated vote weight are visibly larger than those with just their own vote.

**Result:** ___

### D3: Graph Hover Interaction

**Goal:** Verify hovering on nodes and edges shows useful information.

**Steps:**
1. Hover over Dr. Chen's node
2. Observe the tooltip or info display
3. Hover over an edge connecting a delegator to Dr. Chen
4. Observe the edge tooltip

**Expected:** Node hover shows: name, vote (yes/no), number of delegated votes or "X votes via delegation." Connected edges are highlighted while others dim. Edge hover shows: delegator name, delegate name, and the topic that determined the delegation.

**Result:** ___

### D4: Graph Click Interaction

**Goal:** Verify clicking nodes shows detailed information.

**Steps:**
1. Click on Alice's node (the current user)
2. Observe the detail panel or modal
3. Click on Dr. Chen's node
4. Observe the detail panel

**Expected:** Clicking Alice shows her delegation status on this proposal: "Your vote is Yes via Dr. Chen (healthcare delegation)" with options to vote directly or change delegation. Clicking Dr. Chen shows who delegates to them on this proposal and their vote. Detail panels close when clicking elsewhere or on a close button.

**Result:** ___

### D5: Graph Zoom and Pan

**Goal:** Verify the graph supports zoom and pan navigation.

**Steps:**
1. Use mouse wheel (or pinch on trackpad) to zoom in on the graph
2. Click and drag the background to pan
3. Look for a "Reset view" button and click it

**Expected:** Zoom smoothly changes the scale. Pan moves the viewport. Reset view returns to the default centered view. No nodes or labels are clipped or hidden after reset.

**Result:** ___

### D6: Graph Privacy — Anonymous Nodes

**Goal:** Verify that users Alice doesn't follow are shown anonymously.

**Steps:**
1. On the proposal graph, look for nodes that are NOT public delegates and NOT users Alice follows
2. Check their labels

**Expected:** Non-public, non-followed users appear as "Voter #N" or similar anonymous labels rather than showing their real names. Their vote direction (yes/no/abstain) is visible but their identity is not. Public delegates and followed users show real names.

**Result:** ___

### D7: Personal Delegation Network Renders

**Goal:** Verify the personal delegation graph appears on the My Delegations page.

**Steps:**
1. Navigate to My Delegations
2. Look for the "Your Delegation Network" section
3. If collapsed, expand it

**Expected:** A star/ego graph is visible with Alice at the center. Nodes to the right represent users Alice delegates to (Dr. Chen, Bob, etc.) with arrows pointing from Alice to them. Nodes to the left (if any) represent users who delegate to Alice. Edges are colored by topic. A legend is present.

**Result:** ___

### D8: Personal Graph Click Interaction

**Goal:** Verify clicking delegate nodes shows management options.

**Steps:**
1. On the personal delegation network, click on a delegate node (e.g., Dr. Chen on the right side)
2. Observe the detail panel

**Expected:** Panel shows which topics Alice delegates to Dr. Chen, their recent voting record on those topics, and buttons to "Change delegate" and "Remove delegation." These buttons should be functional (they modify the delegation, same as the table controls above).

**Result:** ___

### D9: Graph Responsive Behavior

**Goal:** Verify the graph works on narrow viewports.

**Steps:**
1. Resize the browser window to approximately 375px wide (mobile simulation)
2. Navigate to a proposal with the vote flow graph
3. Check the graph section
4. Navigate to My Delegations and check the personal graph

**Expected:** On mobile, graphs are collapsed by default behind a toggle button ("View Vote Network" / "View Delegation Network"). When expanded, the graph takes full width. Node labels may be simplified (initials instead of full names). The graph is usable via tap (instead of hover) for tooltips.

**Result:** ___

### D10: Graph with Demo Data Quality

**Goal:** Verify the demo data produces a visually compelling and understandable graph.

**Steps:**
1. Load fresh demo data
2. Login as alice
3. Navigate to the "Universal Healthcare Coverage Act" proposal
4. View the vote flow graph
5. Take a step back and assess: does this graph make liquid democracy understandable at a glance?

**Expected:** The graph clearly shows two vote clusters (yes and no). Dr. Chen is visibly a major delegate anchoring the yes side. Delegation arrows make it obvious that many people's votes flow through a few trusted delegates. Alice is findable and her delegation relationship to Dr. Chen is clear. The overall visual tells the story: "votes flow through trusted delegates, and you can see exactly how."

This is a subjective quality assessment. If the graph is confusing, cluttered, or doesn't communicate the concept clearly, note specific issues (too many overlapping labels, nodes too close together, colors hard to distinguish, etc.).

**Result:** ___

### D11: UX Fix Verification (from Phase 3b)

**Goal:** Verify the permission-gated vote message was fixed.

**Steps:**
1. Login as a user who does NOT follow Carol
2. Navigate to Carol's profile
3. Check the voting record section

**Expected:** The message now says "Follow this user to see their voting record" (or similar) with a Follow button — NOT "No votes recorded yet."

**Result:** ___

### D12: Regression — Previous Phase Tests

**Goal:** Verify Phases 2 and 3b functionality still works.

**Steps:**
1. Re-run tests B4 (Proposal Detail & Voting) and B5 (My Delegations Page) from the original playbook
2. Re-run test C9 (End-to-End Delegation Flow) from Phase 3b

**Expected:** All previously passing tests still pass. The graph additions haven't broken existing proposal or delegation functionality.

**Result:** ___

---

## Updated Test Summary Template

After completing all tests, fill in this summary:

```
Browser Test Run: [date]
Server: Backend on :8000, Frontend on :5173
Demo data: Loaded via [method]

Suite A (API via FastAPI Docs):
  A1 Demo Data Loading:        [PASS/FAIL]
  A2 Authentication Flow:      [PASS/FAIL]
  A3 Public Delegate Browsing: [PASS/FAIL]
  A4 Permission-Blocked Delegation: [PASS/FAIL]
  A5 Public Delegate Delegation:    [PASS/FAIL]
  A6 Follow → Approve → Delegate:  [PASS/FAIL]
  A7 Vote Visibility Permissions:   [PASS/FAIL]
  A8 Follow Revocation Cascade:     [PASS/FAIL]
  A9 Audit Trail Completeness:      [PASS/FAIL]

Suite B (Frontend Integration):
  B1 Login Page Loads:          [PASS/FAIL]
  B2 Demo Login:                [PASS/FAIL]
  B3 Proposals Page:            [PASS/FAIL]
  B4 Proposal Detail & Voting:  [PASS/FAIL]
  B5 My Delegations Page:       [PASS/FAIL]
  B6 Cross-User Perspective:    [PASS/FAIL]

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

Suite D (Delegation Graph Visualization — Phase 3c):
  D1 Vote Flow Graph Renders:          [PASS/FAIL]
  D2 Node Identification:              [PASS/FAIL]
  D3 Hover Interaction:                [PASS/FAIL]
  D4 Click Interaction:                [PASS/FAIL]
  D5 Zoom and Pan:                     [PASS/FAIL]
  D6 Privacy — Anonymous Nodes:        [PASS/FAIL]
  D7 Personal Network Renders:         [PASS/FAIL]
  D8 Personal Graph Click:             [PASS/FAIL]
  D9 Responsive Behavior:              [PASS/FAIL]
  D10 Demo Data Quality:               [PASS/FAIL/NOTES]
  D11 UX Fix Verification:             [PASS/FAIL]
  D12 Regression (B4, B5, C9):         [PASS/FAIL]

Total: __/37 passed
Failures: [details of any failures]
Notes: [any observations, UI issues, or suggestions]
```

Save completed summaries to `test_results/` in the project root.

---

## Extending This Document

When new phases are completed, add new test suites to this document following the same format:
- Suite D, E, F, etc. for each phase
- Each test has Goal, Steps, Expected, Result
- Summary template updated with new tests
- Previous test suites remain and are re-run as regression tests (at minimum the critical path: A2, A6, B2, B4, B5)
