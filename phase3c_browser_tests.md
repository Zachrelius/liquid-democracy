# Phase 3c Browser Tests — Append to browser_testing_playbook.md

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

## Updated Summary Template

Add to the existing summary:

```
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
```

Save results to `test_results/phase3c_browser_tests.md`.

---

## Note for Human Reviewer

**Test D10 is the one you should personally check.** The QA agent can verify that the graph renders and is interactive, but only you can judge whether the visualization actually makes liquid democracy intuitive and compelling. After the QA agent completes its run, log in as Alice, look at the Healthcare proposal's vote flow graph, and ask yourself: "If I showed this to someone who'd never heard of liquid democracy, would they get it?" If the answer is no, come back to the planning agent with specific feedback about what's confusing.
