# Phase 3c: Delegation Graph Visualization — Claude Code Build Spec

## Overview

Build interactive delegation graph visualizations that make liquid democracy visually intuitive. This phase adds two graph views: a personal delegation network (on the My Delegations page) and a proposal vote flow graph (on the Proposal Detail page). The proposal view is the higher priority — it's the demo moment that makes people understand the concept.

Read `PROGRESS.md` for current project state.

**Before starting:** Fix the UX issue identified in Phase 3b testing — on user profiles where votes are hidden due to permissions, change the message from "No votes recorded yet" to "Follow this user to see their voting record" (with a Follow/Request Follow button). This should be a quick string change in the frontend.

---

## Part 1: Backend — Graph Data Endpoints

### Proposal Vote Flow Endpoint

`GET /api/proposals/{id}/vote-graph`

Returns the delegation network for a specific proposal, showing how every vote was cast or delegated.

```json
{
  "proposal_id": "uuid",
  "proposal_title": "Universal Healthcare Coverage Act",
  "total_eligible": 20,
  "nodes": [
    {
      "id": "user-uuid",
      "label": "Dr. Chen",
      "type": "direct_voter",
      "vote": "yes",
      "is_public_delegate": true,
      "delegator_count": 5,
      "total_vote_weight": 6
    },
    {
      "id": "user-uuid",
      "label": "Alice",
      "type": "delegator",
      "vote": "yes",
      "vote_source": "delegation",
      "is_current_user": true
    },
    {
      "id": "user-uuid",
      "label": "Bob",
      "type": "direct_voter",
      "vote": "no",
      "is_public_delegate": true,
      "delegator_count": 3,
      "total_vote_weight": 4
    },
    {
      "id": "user-uuid",
      "label": "Carol",
      "type": "direct_voter",
      "vote": "yes",
      "delegator_count": 0,
      "total_vote_weight": 1
    },
    {
      "id": "user-uuid",
      "label": "Dave",
      "type": "non_voter",
      "vote": null,
      "delegator_count": 0,
      "total_vote_weight": 0
    }
  ],
  "edges": [
    {
      "from": "alice-uuid",
      "to": "chen-uuid",
      "topic": "healthcare",
      "topic_color": "#e74c3c",
      "is_active": true
    },
    {
      "from": "delegator2-uuid",
      "to": "chen-uuid",
      "topic": "healthcare",
      "topic_color": "#e74c3c",
      "is_active": true
    }
  ],
  "clusters": {
    "yes": { "count": 12, "direct": 4, "delegated": 8 },
    "no": { "count": 6, "direct": 2, "delegated": 4 },
    "abstain": { "count": 1, "direct": 1, "delegated": 0 },
    "not_cast": { "count": 1 }
  }
}
```

**Node types:**
- `direct_voter` — voted directly on this proposal
- `delegator` — vote was cast via delegation chain
- `chain_delegate` — an intermediate delegate in a chain (for accept_sub chains)
- `non_voter` — eligible but no vote cast (no delegation, no direct vote)

**Privacy rules for this endpoint:**
- The current user always sees their own node with full detail
- Public delegates' nodes show their vote (it's public)
- For other users: show that they voted (and the direction yes/no/abstain) but only show their identity (name) if the current user has a follow relationship with them or if they're a public delegate. Otherwise show them as anonymous nodes ("Voter #7") to preserve ballot privacy while still showing the network structure.
- The graph structure (who delegates to whom) is visible for public delegates' incoming delegations. Private delegation relationships are only visible to the parties involved.

### Personal Delegation Network Endpoint

`GET /api/delegations/graph`

Returns the current user's delegation network (not proposal-specific).

```json
{
  "center": {
    "id": "user-uuid",
    "label": "Alice",
    "delegating_to": 3,
    "delegated_from": 2
  },
  "nodes": [
    {
      "id": "user-uuid",
      "label": "Dr. Chen",
      "relationship": "delegate",
      "topics": ["healthcare"],
      "is_public_delegate": true,
      "total_delegators": 47
    },
    {
      "id": "user-uuid",
      "label": "Bob",
      "relationship": "delegate",
      "topics": ["economy"],
      "is_public_delegate": true,
      "total_delegators": 23
    },
    {
      "id": "user-uuid",
      "label": "Dave",
      "relationship": "delegator",
      "topics": ["global"],
      "total_delegators": 0
    }
  ],
  "edges": [
    {
      "from": "alice-uuid",
      "to": "chen-uuid",
      "topics": [{"name": "healthcare", "color": "#e74c3c"}],
      "direction": "outgoing"
    },
    {
      "from": "alice-uuid",
      "to": "bob-uuid",
      "topics": [{"name": "economy", "color": "#3498db"}],
      "direction": "outgoing"
    },
    {
      "from": "dave-uuid",
      "to": "alice-uuid",
      "topics": [{"name": "global", "color": "#95a5a6"}],
      "direction": "incoming"
    }
  ]
}
```

This endpoint only returns nodes the current user has a direct delegation relationship with (one hop). No privacy concerns since you can only see your own delegates and delegators.

---

## Part 2: Proposal Vote Flow Graph (Primary Visualization)

This is the most important deliverable in Phase 3c. It appears on the Proposal Detail page, below the vote results bar.

### Layout Concept

Use a **force-directed graph** with vote-based clustering:

- **Yes voters** cluster on the left (green-tinted region)
- **No voters** cluster on the right (red-tinted region)
- **Abstain** voters cluster at the bottom (gray region)
- **Non-voters** are small, faded nodes at the edges

Within each cluster, **direct voters with delegations** are larger nodes (they carry more weight), and **delegators** are smaller nodes connected to their delegate by arrows.

The visual effect should be: you can immediately see the two "camps" and which delegates are anchoring each camp. The arrows show where voting power flows. A delegate with 10 arrows pointing at them is visually prominent — that's a lot of trust.

### Node Styling

- **Size**: proportional to total_vote_weight (direct vote + delegated votes). A delegate carrying 10 votes is noticeably larger than someone with just their own vote.
- **Color**: green border for yes, red border for no, gray for abstain, dotted/faded for non-voters.
- **Shape**: circles for everyone. Public delegates get a subtle badge or double-ring to distinguish them.
- **Label**: name shown below the node (or "Voter #N" for privacy-restricted nodes).
- **Current user**: highlighted with a distinct border (gold or bright blue) so you can immediately find yourself in the graph.

### Edge Styling

- **Direction**: arrows pointing from delegator → delegate (showing where the vote power flows TO)
- **Color**: matches the topic badge color that determined this delegation
- **Width**: thin (1px) for single delegations. If the edge represents the path of many votes (fan-in to a popular delegate), keep individual edges thin but they'll visually cluster.
- **Opacity**: active delegations are full opacity. If showing chain delegations (A→B→C), the chain edges could be slightly dashed.

### Interactivity

**Hover on a node:**
- Tooltip showing: name, vote (yes/no/abstain/not cast), "X votes via delegation" if they're a delegate, topic they were delegated for
- Highlight all edges connected to this node (dim everything else)

**Click on a node:**
- Side panel or modal showing:
  - Full name and vote
  - If a delegate: list of who delegates to them on this proposal
  - If a delegator: who their delegate is and why (which topic determined it)
  - For the current user: "This is you. Your vote is [X] via [delegate name] because of your [topic] delegation." with a link to change delegation or vote directly

**Hover on an edge:**
- Tooltip: "[Delegator] → [Delegate] via [topic] delegation"

**Zoom and pan:**
- Mouse wheel / pinch to zoom
- Click and drag background to pan
- "Reset view" button to return to default zoom

**"What if" interaction (stretch goal — implement if time allows):**
- When the current user clicks their own node: show a mini panel with "What if you voted directly?" options
- Selecting Yes/No/Abstain temporarily updates the graph to show what would change (without actually casting a vote)
- This helps voters understand the impact of overriding their delegation

### Technical Implementation

Use **D3.js v7** with force simulation:

```javascript
// Suggested force configuration
const simulation = d3.forceSimulation(nodes)
  .force("charge", d3.forceManyBody().strength(-200))
  .force("center", d3.forceCenter(width / 2, height / 2))
  .force("link", d3.forceLink(edges).id(d => d.id).distance(80))
  .force("x", d3.forceX()  // cluster by vote
    .x(d => d.vote === "yes" ? width * 0.3 
          : d.vote === "no" ? width * 0.7 
          : width * 0.5)
    .strength(0.3))
  .force("collision", d3.forceCollide().radius(d => nodeRadius(d) + 5));
```

Key D3 considerations:
- Use `<svg>` for rendering (not canvas) so individual elements are interactive
- Arrow markers on edges via SVG `<defs>` and `<marker>`
- Node labels as `<text>` elements positioned below circles
- Background regions (yes/no/abstain zones) as translucent rectangles behind the graph
- The component should accept the graph data as a prop and re-render when data changes

If D3 proves too complex for the timeline, **vis.js Network** is an acceptable alternative — it handles force layout, zoom/pan, and hover tooltips out of the box with much less code, though with less visual control.

### Responsive Behavior

- **Desktop (>768px)**: full graph, expanded below the vote results bar. Approximately 600px tall.
- **Mobile (<768px)**: collapsed by default behind a "View Vote Network" button. When expanded, takes full viewport width. Simpler labels (initials instead of full names). Tap instead of hover for tooltips.

---

## Part 3: Personal Delegation Network Graph

This appears on the My Delegations page as a collapsible section below the topic precedence ordering.

### Layout

Simpler than the proposal graph — this is a **star/ego graph** with the current user at the center:

- **Center**: the current user (large node, highlighted)
- **Right side**: users the current user delegates TO (outgoing edges, arrow pointing right)
- **Left side**: users who delegate TO the current user (incoming edges, arrows pointing left)
- Edges are colored by topic (matching topic badge colors)
- If a user appears in multiple roles (you delegate to them on healthcare AND they delegate to you on economy), show both edges with different colors

### Node Styling

- Current user: largest node, centered, distinct color
- Delegates (outgoing): medium nodes, positioned right. Labeled with name + topic badges.
- Delegators (incoming): medium nodes, positioned left. Labeled with name + topic badges.
- Node size for delegates/delegators reflects their total_delegators count (more trusted delegates are visually larger)

### Interactivity

**Click on a delegate node (right side):**
- Shows: which topics you delegate to them, their voting record on those topics (last 5 votes), "Change delegate" and "Remove delegation" buttons
- Essentially a quick-access version of the delegation row in the table above

**Click on a delegator node (left side):**
- Shows: which topics they delegate to you, their name
- Informational only — you can't change someone else's delegation

**Hover:** Highlight the edges connected to that node, show topic labels.

### Section Header

```
Your Delegation Network
[Show Graph ▾]  /  [Hide Graph ▴]
```

Default to expanded on desktop, collapsed on mobile.

---

## Part 4: Graph Integration Points

### Proposal Detail Page Updates

Add the vote flow graph to the proposal detail page:
- Position: below the current vote results bar, above the deliberation/comments section
- Only shown when proposal status is "voting" or "passed" or "failed" (not during "deliberation" or "draft")
- Section header: "Vote Network" with a collapse toggle
- Include a legend:
  ```
  ● Yes (green)  ● No (red)  ● Abstain (gray)  ○ Not voted
  → Delegation    ★ Public delegate    ◆ You
  ```

### My Delegations Page Updates

Add the personal delegation network graph:
- Position: after the topic precedence section, before the follow requests section
- Collapsible with "Your Delegation Network" header
- Include a simple legend:
  ```
  → You delegate to    ← Delegates to you
  Edge colors match topic badges
  ```

---

## Part 5: Demo Data Verification

The existing demo data should produce a compelling graph. Verify that with 20 demo users, the proposal vote flow graph shows:
- Dr. Chen as a large node (many delegators) in the Yes cluster
- Bob as a medium node in the No cluster
- Several smaller delegator nodes connected to each
- Alice highlighted as the current user, connected to Dr. Chen
- The visual immediately communicates: "most of the voting power flows through a few trusted delegates"

If the demo data doesn't produce a visually interesting graph (too sparse, too uniform), enhance the seed data with additional delegation patterns to create a more compelling visualization.

---

## Build Order

1. **Quick fix**: Update the permission-gated vote message from Phase 3b (change "No votes recorded yet" to "Follow this user to see their voting record")
2. **Backend**: Implement the two graph data endpoints with privacy-aware node/edge construction
3. **Proposal vote flow graph component**: D3 (or vis.js) component with force-directed layout, vote clustering, node/edge styling, hover tooltips, click details
4. **Integrate proposal graph**: Add to proposal detail page with collapse toggle and legend
5. **Personal delegation network component**: Simpler star/ego graph component
6. **Integrate personal graph**: Add to My Delegations page with collapse toggle
7. **Demo verification**: Check that demo data produces a compelling graph. Adjust seed data if needed.
8. **Polish**: Responsive behavior, loading states, smooth animations on simulation, zoom controls

After each step, run existing backend tests to confirm no regressions.

---

## What NOT to Build in Phase 3c

- "What if" vote simulation (listed as stretch goal — only if time allows after everything else works)
- Real-time graph updates via WebSocket (static graph that refreshes on page load is fine)
- Graph export/screenshot functionality
- Animated transitions showing vote changes over time
- 3D graph visualization
- Dashboard page (Phase 3d)
