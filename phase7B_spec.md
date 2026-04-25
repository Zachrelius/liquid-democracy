# Phase 7B — Vote Network Visualization for Multi-Option Proposals

**Type:** Visualization redesign. Frontend-heavy with a small backend graph-data extension.
**Dependencies:** Phase 7 complete (current `master`, 191 backend tests passing, RCV/STV live in production at `https://www.liquiddemocracy.us`).
**Goal:** Replace the binary-only `VoteFlowGraph` with a method-aware visualization that handles binary (preserved as-is), approval, and ranked-choice voting. Also fix the proposal-list "0 of N votes cast" inaccuracy for ranked_choice. Phase 7C handles the round-by-round elimination Sankey separately.

---

## Context

The current `VoteFlowGraph` (`frontend/src/components/VoteFlowGraph.jsx`) is hardcoded for binary voting: green/red half-plane zones, "yes/no" labels, abstain bottom zone, vote tally bar showing yes/no/abstain counts. None of that maps to approval or ranked-choice voting. For non-binary proposals, the graph currently renders nonsensically — zero yes, zero no, X abstained, with the colored zones still drawn.

The underlying voting and tabulation work correctly. This is a visualization gap, not a regression. Phase 7B closes it for the network graph; the round-by-round elimination Sankey for RCV/STV is split into Phase 7C because it's standalone work that doesn't share code with the network graph.

---

## Design Decisions Locked In Before Dispatch

These are the planning agent and Z's resolved decisions. The dev team should not re-litigate these without surfacing a concrete blocker.

### Decision 1: Option-attractor force layout for approval and RCV

Each proposal option becomes a fixed/pinned node in the graph. Voters are subject to multiple simultaneous forces — attraction toward the options they approved (or ranked, for RCV), plus the standard voter-voter repulsion that keeps nodes from stacking. The simulation runs and each voter settles at force equilibrium, which is one position per voter. Voters with similar approval/ranking patterns naturally cluster together; voters with unusual or conflicting patterns end up centrally located where their force vectors partially cancel.

This is a force-directed graph with extra attractor nodes — D3's existing force simulation handles the physics natively. The implementation is mostly a question of force tuning, not algorithmic novelty.

**Expected emergent behavior** (the planning agent and Z described this; the dev team should aim for this and note if the force tuning produces something different):

- Options with many shared voters end up as neighbors (because shared voters pull them together)
- Voters who approved only two adjacent options sit outside the option ring between those two
- Voters who approved three or more options, or unusual pairings, sit centrally where their force vectors balance
- Voter-voter repulsion (D3's default `charge` force) prevents stacking but allows clustering
- The 2D space cannot positionally distinguish "voted for opposite-diagonal pairs" — that ambiguity is unavoidable and is the reason delegation arrows and hover-cluster-highlighting matter for legibility

### Decision 2: Single position per voter, achieved through force equilibrium

Each voter has exactly one position on the graph, which is the equilibrium of all forces acting on them. This is what a force-directed simulation produces by default — there's nothing special to build. The relevant terminology was clarified during planning: "single position via force equilibrium," not "single position via centroid-of-attractors."

### Decision 3: Linear ranking decay for RCV

For RCV proposals, option attractors pull voters with strength weighted by ranking position. Use **linear decay**:

- 1st preference: full strength (1.0)
- 2nd preference: 0.66
- 3rd preference: 0.33
- 4th and lower: scaled proportionally, but with a minimum strength floor (e.g., 0.1) so lower-ranked options still register visually

The exact strength values are tunable — these are the starting point. If the layout doesn't read well in practice, the team can adjust during implementation. Document the chosen values in code comments so the choice is visible.

Linear is the default because it's interpretable: "how strongly is voter pulled toward Option A" maps directly to "how high did they rank A." Exponential decay (1.0, 0.5, 0.25) was considered and rejected because it makes lower preferences nearly invisible in the layout.

### Decision 4: Binary visualization preserved as-is

The current binary graph (green/red half-plane clustering with color zones) stays exactly as it is. Reasons: it works, it's readable, the green/red color coding is information-rich, and rebuilding it on the new option-attractor architecture would lose visual signal without obvious benefit.

The new component dispatches on `proposal.voting_method`:

- `binary` → existing rendering, unchanged
- `approval` → new option-attractor layout
- `ranked_choice` → new option-attractor layout with linear ranking decay

Future re-architecting to unify all three under one visualization model is possible but explicitly not in scope. If we later decide unified-architecture is worth it, that's a separate pass.

### Decision 5: Node visual conventions carry over

The current visualization conventions stay consistent across all three voting methods:

- **Node sizing by `total_vote_weight`** (a delegate carrying 10 votes is visually larger than a single voter) — applies to approval and RCV the same way it applies to binary.
- **Public delegates get a dashed double-ring** — applies to all methods.
- **Current user gets a gold border highlight** — applies to all methods.
- **Delegation arrows from delegator to delegate, colored by topic** — applies to all methods.
- **Hover highlights connected subgraph and dims unrelated nodes** — applies to all methods.
- **Click opens detail panel with View Profile, Change/Remove delegate (when applicable), and method-appropriate vote summary** — applies to all methods.
- **Privacy rules unchanged** — public delegates and followed users show real names; users who privately delegate to the current user show real names; everyone else is anonymous.

Only the layout logic and the tally summary text differ across methods.

### Decision 6: Tally summary text dispatches on voting method

The existing graph component shows a "yes/no/abstain" cluster summary alongside the visualization. For approval and RCV proposals this text is wrong. Replace with method-appropriate summaries:

- **Binary:** unchanged. "X yes, Y no, Z abstain, N not voted."
- **Approval:** "X ballots cast (Y abstain), top option: [label] with N approvals" with a small breakdown of approval counts per option visible on hover or expansion.
- **Ranked-choice:** "X ballots cast (Y abstain), winner: [label] after N rounds" with elimination summary on hover or in a small expandable panel. (Detailed round-by-round visualization is Phase 7C's Sankey — this is just the headline summary.)

### Decision 7: Mitigation controls for high-option-count density

The option-attractor layout works elegantly with 3-5 options but gets dense with more. Build mitigation controls into the v1:

- **Toggle individual option attractors on/off** via legend or option list. Disabling Option B's attractor removes it from the layout; voters who had been pulled toward it relax to equilibrium with their remaining preferences. Visualization filter: "show only voters who interacted with these options."
- **Hover-to-isolate.** Hovering over an option attractor highlights voters strongly pulled toward it (high approval/ranking weight), dims others. Hovering over a voter highlights their connections (delegations) and the options pulling them.
- **Hide voters who approved/ranked zero options** (default off — abstain voters are minor visual noise). Toggle in the controls panel.
- **Adapt force parameters based on option count.** With 5+ options, increase repulsion or decrease attractor strength so the visualization doesn't compress. The team should tune empirically — there's no formula here, just "what looks readable with N options." Test with 3, 5, 8, 10 options.

These don't all need to be polished in v1. The toggle-attractors and hover-to-isolate are the most important; the rest can land in v1 lightly and be refined later.

---

## Backend Scope

### Extension to `GET /api/proposals/{id}/vote-graph`

The existing endpoint returns nodes (users) and edges (delegations) for binary proposals. For approval and RCV proposals, extend to also return option data and ballot data:

```python
class VoteFlowGraph:
    nodes: list[VoteFlowNode]      # existing — voters and delegates
    edges: list[VoteFlowEdge]       # existing — delegations
    options: list[VoteFlowOption]   # NEW — present for approval and RCV; empty for binary
    clusters: VoteFlowClusters       # existing — extend with method-aware fields
    voting_method: str               # NEW — "binary" | "approval" | "ranked_choice"
```

```python
class VoteFlowOption:
    id: str             # ProposalOption.id
    label: str          # ProposalOption.label
    display_order: int  # for stable ordering in the layout
    approval_count: int # how many ballots approved this option (approval only; 0 for RCV)
    first_pref_count: int # how many ballots ranked this first (RCV only; 0 for approval)
```

For each voter node, add the voter's resolved ballot in a method-appropriate field:

```python
class VoteFlowNode:
    # ... existing fields ...
    ballot: Optional[VoteFlowBallot]  # NEW

class VoteFlowBallot:
    # Exactly one is populated based on voting_method
    vote_value: Optional[str]                    # binary: "yes" / "no" / "abstain"
    approvals: Optional[list[str]]               # approval: list of option_ids
    ranking: Optional[list[str]]                 # rcv: list of option_ids in rank order
```

The privacy rules from the existing endpoint apply: anonymous nodes still get anonymous ballot data (all option_ids are public — they're proposal-scoped — but the ballot's *attribution* to a real person is gated by follow relationships and public-delegate status, exactly like binary vote_value is now).

### Extension to `clusters` field

The existing `VoteFlowClusters` returns binary-specific counts (yes/no/abstain/not_cast, broken down by direct vs delegated). For approval and RCV, return method-appropriate aggregates:

```python
class VoteFlowClusters:
    voting_method: str                    # "binary" | "approval" | "ranked_choice"
    total_eligible: int
    total_cast: int
    total_abstain: int                    # empty ballots for approval/RCV; "abstain" votes for binary
    not_cast: int

    # Method-specific (exactly one populated)
    binary: Optional[BinaryClusters]      # existing yes/no breakdown
    approval: Optional[ApprovalClusters]  # option_id -> approval count + winner(s)
    rcv: Optional[RCVClusters]            # winner(s) + total rounds
```

The existing binary frontend code reads from `clusters.yes`, `clusters.no`, etc. To preserve back-compat without refactoring, keep the top-level binary fields populated when `voting_method=="binary"` and leave them null/zero otherwise. New frontend code reads `clusters.binary.yes` etc.; this gives a clean migration path.

### Backend tests

New tests in `tests/test_vote_graph.py` (or extend the existing test file):

1. Vote graph for an approval proposal returns options list with correct approval counts.
2. Vote graph for an approval proposal includes `ballot.approvals` for visible voters; anonymous voters have `ballot=null` (not just hidden — actually null, so the frontend doesn't render them with attractor pulls).
3. Vote graph for an RCV proposal returns options list with correct first-preference counts.
4. Vote graph for an RCV proposal includes `ballot.ranking` for visible voters in the correct rank order.
5. Vote graph for a tied RCV proposal returns the cluster `rcv.winners` list with length > 1.
6. Vote graph for a binary proposal preserves existing structure (regression).
7. Privacy: anonymous voters' ballots are null in the response.
8. Privacy: voters who privately delegate to the current user have visible ballots (per existing rule).

Target: ~6-8 new backend tests. Backend test count from 191 → ~199.

---

## Frontend Scope

### Component refactor: `VoteFlowGraph.jsx` becomes method-aware

The existing component is one big file. Refactor:

- `VoteFlowGraph.jsx` — top-level dispatcher. Reads `data.voting_method` and renders the appropriate sub-component. Owns shared state (zoom, pan, selected node, hover state).
- `BinaryVoteFlowGraph.jsx` — extracted from existing code with no logic changes. Pure rendering of the green/red half-plane clustering.
- `OptionAttractorVoteFlowGraph.jsx` — new component handling approval and RCV. Internally dispatches force weights based on `voting_method` (uniform attractor strength for approval, linear ranking decay for RCV).

Shared utilities (privacy filtering, edge deduplication, node sizing, hover/click handlers) move to a separate `voteFlowGraphUtils.js` so both sub-components consume the same code.

### `OptionAttractorVoteFlowGraph` implementation details

**Force simulation setup:**

D3's `forceSimulation` with the following forces:

- `forceManyBody()` — voter-voter repulsion. Tune strength based on option count (more options = need more repulsion to prevent crowding).
- `forceCollide()` — prevents node overlap. Radius based on `nodeRadius(d)`.
- For each option, a custom attractor force: each voter is pulled toward each option's pinned position with strength proportional to their relationship to that option (approval: 1.0 if approved, 0 if not; RCV: 1.0 / 0.66 / 0.33 / ... based on rank position).
- Light `forceCenter()` to keep the whole graph from drifting off-screen.

**Pinning options in a circle:**

Options are placed at fixed positions arranged in a circle around the center. With N options, each option sits at angle `(i / N) * 2π` and distance `R` from center. Use `fx` and `fy` to pin them so the simulation doesn't move them. Initial radius `R` is roughly 35% of the smaller viewport dimension; tune empirically.

Each option attractor renders as a distinct node — visually different from voter nodes. Suggestions: larger size, distinctive color (e.g., dark navy or a per-option color from a palette), label clearly visible (full option label, not truncated unless the label is very long).

**Voter forces toward options:**

Each voter has an array of `(option_id, weight)` tuples. The custom force iterates voters, looks up each option's pinned position, and applies pull toward that position scaled by weight. Implementation pattern (D3-flavored pseudocode):

```javascript
function optionAttractorForce(strength) {
  let nodes;
  function force(alpha) {
    for (const voter of nodes.filter(n => n.type !== 'option')) {
      for (const [optionId, weight] of voter.optionWeights || []) {
        const option = nodeMap.get(optionId);
        if (!option) continue;
        voter.vx += (option.x - voter.x) * weight * strength * alpha;
        voter.vy += (option.y - voter.y) * weight * strength * alpha;
      }
    }
  }
  force.initialize = (n) => { nodes = n; };
  return force;
}
```

The exact `strength` is tuning territory. Start with something like 0.05-0.1 and adjust based on visual readability.

**Voter `optionWeights` derivation:**

For approval ballots: every option in `ballot.approvals` gets weight 1.0; everything else gets weight 0 (no force).

For RCV ballots: walk through `ballot.ranking` in order. First option gets 1.0, second gets 0.66, third gets 0.33, fourth and lower get max(0.1, 0.33 - 0.1*(rank-3)) or similar — flat floor of 0.1 below rank 3 is fine for v1.

For voters with empty ballots (abstain): no option weights, only the center force keeps them in frame. Render them faded or in a small "abstain cluster" zone if the visual reads well; otherwise just let them float toward the center via the center force.

For voters with no ballot at all (non_voter): same as abstain visually — small, faded, no option pulls.

### Mitigation controls (UI)

A controls panel near the top-right of the graph (alongside the existing zoom-reset and show-non-voters toggles):

- **Option toggles.** A small list of options with checkboxes. Unchecking an option removes its attractor from the simulation; voters relax to equilibrium with remaining attractors. Implementation: rebuild the simulation's force list when toggles change.
- **Hover-to-isolate** behavior: when the user hovers an option, dim voters whose weight toward that option is below some threshold (e.g., 0.5). When hovering a voter, highlight the options pulling them and dim other voters.
- **Hide non-voters / Hide abstainers** toggle (already exists for non-voters; extend to also hide empty-ballot voters).

### Tally summary update

Below the graph, replace the binary-specific summary with method-appropriate text. See Decision 6 for the format. The implementation is straightforward — read `data.clusters.voting_method` and render the appropriate block.

### Detail panel (click-on-node) update

Clicking a voter node currently shows their binary vote and chain info. Update to show method-appropriate ballot:

- **Binary:** unchanged. "Voted Yes via Dr. Chen."
- **Approval:** "Approved 2 of 4 options: [Label A, Label C]" plus chain info if delegated.
- **RCV:** "Ranked 3 of 4 options: 1. Label B  2. Label D  3. Label A" plus chain info.

Empty-ballot voters: "Abstained (no options selected)" or "Abstained (no options ranked)."

Public-delegate badge, "View Profile" link, and Change/Remove delegate buttons remain unchanged.

### Proposal-list counter fix

This is the small-but-visible bug from Phase 7's tech debt: the proposals list shows "0 of N votes cast" for ranked_choice proposals because the list aggregator likely reads `vote_value` distinct counts, which is null for multi-option ballots.

Fix: the aggregator should count `Vote` rows for the proposal regardless of which column (`vote_value` or `ballot`) is populated. The actual fix is one or two lines depending on where the count is computed.

Backend or frontend? The list page calls `GET /api/proposals` (or org-scoped equivalent). Inspect the response shape — if the count is computed backend-side and returned in the proposal summary, fix it backend. If the frontend computes it from the proposal payload, fix it frontend. Either way, the fix is small.

Add a backend test (or frontend, depending on where the bug lives) to ensure the count is correct for each voting method.

---

## Testing

### Suite M — new browser test suite

Add a new suite to `browser_testing_playbook.md` (Suite L is taken by Phase 6.5; M is the next available). Execute via Claude-in-Chrome. Keep it focused — the network graph is visual and most of the value comes from human eyeballing the result, but a few automated tests catch regressions.

**M1: Binary vote graph renders unchanged.** Open a binary proposal in voting/passed status. Confirm green/red zones, yes/no clustering, existing node behavior all work. Regression check.

**M2: Approval proposal shows option attractor layout.** Open an approval proposal. Confirm options render as distinct pinned nodes arranged in a circle. Voters cluster toward options they approved. No green/red zones.

**M3: Approval voter ballot in detail panel.** Click a voter node on the approval graph. Confirm detail panel shows "Approved X of Y options: [labels]."

**M4: RCV proposal shows weighted option attractor layout.** Open an RCV proposal. Confirm options pinned in a circle. Voters with strong first preferences sit near their first option; voters who ranked many options sit more centrally.

**M5: RCV voter ballot in detail panel.** Click a voter node on an RCV graph. Confirm detail panel shows "Ranked N of M options: 1. [Label] 2. [Label] ..."

**M6: Tally summary dispatches on voting method.** Confirm binary, approval, and RCV proposals show method-appropriate summary text below the graph.

**M7: Toggle option attractor.** On approval graph, uncheck one option in the controls panel. Confirm that option's attractor disappears and voters relax to equilibrium with remaining options.

**M8: Hover-to-isolate.** Hover an option attractor on an approval graph. Confirm voters strongly pulled toward that option are highlighted; others dim.

**M9: Privacy preserved.** As a non-admin viewing an approval graph, confirm anonymous voters render with attractor-derived positions but their ballot details aren't shown in tooltips/panels.

**M10: Proposal-list counter accurate for RCV.** Navigate to the proposals list. Confirm RCV proposals show the correct "X of N votes cast" rather than 0.

**M11: Regression — Suites H, I, J, K, L.** Re-run prior browser test suites. All previously passing tests must still pass.

### PostgreSQL smoke test

Same pattern as previous passes. After Suite M passes locally, bring up docker-compose stack and verify:

1. Open an approval proposal's vote graph endpoint — JSON response includes options and ballot fields, no 500.
2. Open an RCV proposal's vote graph endpoint — JSON includes ranking ballots, no 500.
3. Render the proposal-list page — RCV counter shows correct value, no 500.

If anything 500s, diagnose from logs and fix before declaring done.

---

## Definition of Done

- All backend scope items implemented. Single Alembic migration if any model changes are needed (probably none — graph endpoint is read-only over existing data).
- All frontend scope items implemented. Method-aware dispatch in `VoteFlowGraph`, option-attractor layout for approval and RCV, mitigation controls (option toggles, hover-to-isolate), updated tally summary, updated detail panel.
- Proposal-list counter bug fixed for ranked_choice. Tests added.
- Backend tests: ~6-8 new tests added. Target 197+ passing total.
- Suite M added to `browser_testing_playbook.md` and all 11 tests pass.
- PostgreSQL smoke test passes.
- `PROGRESS.md` updated with Phase 7B section: what was built, design decisions referenced, test counts, Suite M results, prod state after merge.
- `future_improvements_roadmap.md` updated: Phase 7B marked complete; Phase 7C reordered if necessary.
- Production deploy via merge to `master` per the Phase 7 pattern. Quick post-deploy sanity check that prod renders correctly for binary, approval, and RCV proposals.
- The visualization v1 may not be perfect. If the force tuning produces a layout that's *functional but not as pretty as we'd like*, that's acceptable for v1 — log specific issues as tech debt for a v2 pass rather than blocking the merge. The bar is "readable, no obvious bugs, dispatches correctly on voting method." Polish iteration is fine to defer.

---

## Out of Scope

Deferred to Phase 7C:
- Round-by-round elimination Sankey visualization for RCV/STV
- Animation of vote transfers between rounds
- Per-round network graph snapshots ("show me what the graph looked like at round 2")

Deferred post-sequence:
- Unified visualization architecture (migrating binary to the new option-attractor model)
- Per-voter 3D-positioning to resolve 2D-space ambiguities
- Animated transitions when toggling option attractors
- Heatmap or density visualizations as alternatives to force-directed
- Voter clustering algorithms beyond what D3's force simulation provides

If the dev team discovers adjacent issues during execution, log them as new technical debt in `PROGRESS.md` rather than expanding this spec.

---

## Notes for the Dev Team

- **Force tuning is iterative.** The strength values (attractor pull, repulsion, ranking decay) given in this spec are starting points, not requirements. Tune until the visualization reads well across 3-option, 5-option, and 8-option proposals. Document final values in code comments.
- **Test with the live demo data.** The seed includes RCV proposals from Phase 7. Use those as the primary test cases for the new layout. If they don't read well, the seed might need tuning or the layout does — figure out which during implementation.
- **Don't over-engineer the mitigation controls.** Toggle attractors and hover-to-isolate are the two most important. The rest can land lightly. If you find yourself building a complex preference panel, you've gone too far.
- **The spec calls for a small backend extension.** Don't expand it into a refactor of the graph endpoint. Add `options`, `voting_method`, and `ballot` fields; don't restructure existing fields beyond what's needed for back-compat.
- **Phase 7C (Sankey) is a separate pass.** Don't start it as part of 7B. The round-by-round Sankey is its own visualization with its own design considerations.
