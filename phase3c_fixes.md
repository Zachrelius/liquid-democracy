# Phase 3c Polish Fixes — Claude Code Build Spec

## Overview

Phase 3c graphs are functional and the core visualization works. This document specifies fixes for visual bugs and design improvements identified by both human review and automated QA. Address all items before moving to Phase 3d.

Read `PROGRESS.md` for current state.

---

## Fix 1: Proposal Graph — Background Region Layout (Human Review)

**Problem:** The pale green (yes) and red (no) background regions are sized boxes that don't fully contain their respective vote clusters. Abstain/undecided nodes overlap into the colored regions, making the visual grouping confusing.

**Fix:** Change the background regions from sized rectangles to half-plane fills that extend to the edges of the viewport:
- **Green region**: extends from the left edge of the SVG to the center (or just past center), and from the top to the bottom. Semi-transparent (current opacity is fine).
- **Red region**: extends from the center (or just past center) to the right edge, top to bottom.
- The two regions should touch or nearly touch at the center vertical line (small gap of ~4px is fine for visual clarity).
- **Bottom area below both regions** (roughly the lower 20-25% of the graph area): leave uncolored (white/transparent background) for abstain and non-voter nodes. These nodes should be pushed down by the force simulation's y-force so they naturally settle in this uncolored zone.
- The regions should extend as far as the user zooms/pans — they should feel like infinite half-planes, not bounded boxes. Technically, make them large enough (e.g., 10000x10000px) that zooming out doesn't reveal their edges.

Update the D3 force simulation's y-force to push abstain and non-voter nodes toward the bottom of the graph, away from the yes/no clusters:
```javascript
.force("y", d3.forceY()
  .y(d => d.vote === "abstain" || d.vote === null 
    ? height * 0.85   // push to bottom
    : height * 0.4)   // yes/no stay in upper area
  .strength(0.3))
```

## Fix 2: Proposal Graph — Public Delegate Legend Icon (Human Review)

**Problem:** The public delegate icon in the legend shows the dashed and solid circles offset from each other instead of concentric, making it look like a misprint rather than a recognizable symbol.

**Fix:** Update the legend SVG for the public delegate symbol so the two circles (dashed outer, solid inner) are perfectly concentric — same center point, outer circle ~4px larger radius than inner. Match exactly how public delegate nodes appear in the main graph.

## Fix 3: Personal Network — Overlapping Topic Labels (Human Review)

**Problem:** When a user delegates multiple topics to the same person, the topic labels (e.g., "Healthcare" and "Economy") render on top of each other as overlapping text.

**Fix:** Stack multiple topic labels vertically below the node:
- First topic label positioned at the standard label position (below the node circle)
- Each additional topic label offset further down by ~16px (line height)
- Adjust the node's collision radius and the force simulation spacing to accommodate the taller label area — nodes with multiple topic labels need more vertical clearance
- If more than 3 topics, show the first 2 and a "+N more" indicator to prevent excessive vertical expansion

## Fix 4: Personal Network — Missing Approved Delegator (Human Review)

**Problem:** After approving a follow/delegation request in the demo, the approved user doesn't appear in the personal delegation network graph.

**Investigation needed:** Check whether this is:
- (a) A seed data issue — the demo request might be a follow-only request (not a delegation intent), so approving it creates a follow relationship but no delegation, meaning the person correctly doesn't appear in the delegation graph (which only shows delegation relationships, not follow relationships)
- (b) A bug — the person delegated but the graph endpoint doesn't pick up newly created delegations

If (a): This is expected behavior but confusing. Add a note in the follow requests section that distinguishes request types more clearly. Also fix the demo seed data so the pending request message says "I've been following your advocacy and would like to see your voting record" (for follow requests) or "I'd like you to represent me on [topic]" (for delegation requests) rather than generic text that implies delegation when it's just a follow.

If (b): Fix the graph endpoint to include all active delegations, including recently created ones.

## Fix 5: Unicode Escapes in Legends (QA Finding)

**Problem:** Arrow characters showing as literal `\u2192` and `\u2190` text instead of → and ← in the graph legends.

**Fix:** Replace the escaped unicode strings with actual unicode characters in the source code, or ensure the rendering pipeline handles the escapes correctly. Check both the proposal graph legend and the personal network legend.

## Fix 6: Personal Network — Missing Action Buttons (QA Finding)

**Problem:** Clicking a delegate node in the personal network shows a detail panel but the "Change delegate" and "Remove delegation" action buttons are missing.

**Fix:** Add functional buttons to the click detail panel for delegate nodes (outgoing edges):
- "Change delegate" — opens the delegate selection modal pre-filtered to the relevant topic
- "Remove delegation" — removes the delegation after a confirmation prompt, then refreshes the graph

These should call the same API endpoints as the equivalent buttons in the delegation table above the graph.

## Fix 7: Duplicate Topic Casing in Tooltips (QA Finding)

**Problem:** Tooltips show duplicate topic names with inconsistent casing, e.g., "Healthcare, healthcare."

**Fix:** Deduplicate topic names in tooltip text. If the same topic appears multiple times (possibly from different sources in the data), show it only once. Normalize casing to match the canonical topic name from the database.

## Fix 8: Reset View Zoom Level (QA Finding)

**Problem:** The "Reset view" button zooms out too far, making the graph appear small and hard to read.

**Fix:** Set the reset zoom level to fit all nodes with ~10% padding rather than zooming to the full SVG extent. Use D3's `zoom.transform` to calculate the bounding box of all nodes and set the zoom to contain them comfortably:
```javascript
function resetView() {
  const bounds = getNodeBoundingBox(nodes); // min/max x,y of all nodes
  const padding = 40;
  const scale = Math.min(
    width / (bounds.width + padding * 2),
    height / (bounds.height + padding * 2)
  );
  // ... apply transform
}
```

## Fix 9: Non-Voter Node Visibility (QA Suggestion)

**Problem:** Non-voter nodes (eligible users who neither voted nor delegated) add visual clutter without much information value, especially as the number of users grows.

**Fix:** Hide non-voter nodes by default. Add a toggle: "Show non-voters (N)" that reveals them when clicked. When hidden, update the cluster summary to note: "N eligible voters have not voted." When shown, display them as small, faded nodes in the uncolored bottom area (per Fix 1).

---

## Build Order

1. Fix 5 (unicode) and Fix 7 (duplicate casing) — quick string fixes
2. Fix 2 (legend icon) — quick SVG fix
3. Fix 1 (background regions) — force simulation and layout change
4. Fix 3 (topic label stacking) — layout and spacing change
5. Fix 6 (action buttons) — add buttons and wire to API
6. Fix 8 (reset zoom) — zoom calculation fix
7. Fix 9 (non-voter toggle) — add toggle and default hide
8. Fix 4 (missing delegator) — investigate and fix appropriately

After all fixes, run the full backend test suite to confirm no regressions. Then update `PROGRESS.md`.

---

## Re-Test After Fixes

After completing all fixes, the QA agent should re-run:
- D1 (graph renders)
- D2 (node identification)
- D3 (hover interaction)
- D7 (personal network renders)
- D8 (personal graph click — specifically verify Fix 6 action buttons work)
- D10 (overall demo quality — verify the background regions and label fixes improve clarity)
- D12 (regression)

Plus verify each specific fix:
- Fix 1: Green/red regions extend to edges, abstain/non-voters in uncolored bottom zone
- Fix 2: Legend icon matches graph node styling
- Fix 3: Multiple topic labels stack without overlapping
- Fix 5: Arrows render as actual arrow characters
- Fix 6: Change/Remove buttons present and functional on delegate node click
- Fix 7: No duplicate topic names in tooltips
- Fix 8: Reset view fits nodes comfortably
- Fix 9: Non-voters hidden by default, toggle reveals them
