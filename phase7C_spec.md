# Phase 7C — Round-by-Round Elimination Sankey for RCV/STV

**Type:** Visualization addition. Frontend-heavy with no expected backend work. Bundled with two small Phase 7B.2 polish items.
**Dependencies:** Phase 7B.1 complete (current `master`, 200 backend tests passing, method-aware vote graph live in production at `https://www.liquiddemocracy.us`).
**Goal:** Add a standard Sankey-style flow visualization for RCV/STV proposals showing how votes transfer between options across elimination rounds. Bundle in two small visualization fixes from Z's review of Phase 7B.1: suppress voter-to-option arrows for delegators, and replace the binary "Yes/No/Abstain" legend with method-appropriate legends on approval and RCV graphs.

---

## Context

Phase 7 shipped IRV and STV tabulation via `pyrankvote==2.0.6` and surfaced round-by-round results through `RCVResultsPanel.jsx` as a text/table breakdown. Phase 7B redesigned the network graph to dispatch on voting method and added the option-attractor force layout for approval and RCV. Phase 7B.1 polished the visualization with voter-to-option arrows, working option toggles, and pre-tick simulation.

What's missing: the standard visualization for round-by-round elimination flow is a Sankey diagram, not a text table. This pass adds it. The Sankey lives below the network graph on RCV/STV proposal detail pages — the two visualizations show different things and complement each other.

The bundled Phase 7B.2 polish items are small visualization fixes Z surfaced from the live demo. They're not separate-pass-worthy on their own; folding them into Phase 7C while the team is in the visualization layer is more efficient than another visualization-only pass.

---

## Design Decisions Locked In Before Dispatch

### Decision 1: D3-Sankey for the Sankey component

D3-Sankey is the standard library for Sankey diagrams in the D3 ecosystem and is already part of the broader D3 family the codebase uses. Use it unless there's a concrete blocker (library not maintained, doesn't render correctly with the data shape, etc.). Confirm the library is still actively maintained before integrating — if it's stale or abandoned, flag back to planning rather than substituting silently. This is the same library-vetting pattern Phase 7 used for `pyrankvote`.

### Decision 2: Backend data is already sufficient — no backend changes expected

The Phase 7 implementation built `RCVRound` and `RCVTally` dataclasses that already include everything the Sankey needs:

- `RCVRound.option_counts` — `{option_id: vote count}` per round
- `RCVRound.eliminated` — option_id eliminated this round (if any)
- `RCVRound.elected` — option_ids elected this round (relevant for STV)
- `RCVRound.transferred_from` — option whose votes transferred this round
- `RCVRound.transfer_breakdown` — `{option_id: gain}` showing where votes flowed

The team building this knew the visualization was coming and shaped the data accordingly. The Sankey reads from the existing results endpoint (already returns `RCVTally` with rounds populated). Verify this assumption early in the pass — if for some reason the existing data isn't sufficient, flag it before investing in the frontend, but the expectation is that no backend work is needed.

If a small backend extension does turn out to be needed (e.g., a field that's computable from existing data but not currently surfaced), keep it minimal. Don't restructure the results endpoint.

### Decision 3: Sankey renders only on RCV/STV proposals

Binary and approval don't have rounds — there's nothing to Sankey. The component dispatches on `proposal.voting_method` like the rest of the visualization work and renders nothing for binary or approval.

For RCV/STV proposals **in voting status** (not yet finalized), the Sankey should render based on the current ballot state — same data, just provisional rather than final. The "winning" vs "winner" copy from Phase 7B.1 already handles the provisional framing; the Sankey follows the same pattern. If the elimination structure shifts as ballots come in during the voting window, the Sankey re-renders accordingly.

For RCV/STV proposals with no ballots cast yet, render a placeholder ("Sankey will appear once ballots are cast") rather than an empty diagram or an error.

### Decision 4: Layout and positioning relative to the network graph

The Sankey lives **below** the network graph on the proposal detail page. Both visualizations are visible simultaneously — the network graph shows who voted how and how delegations flowed; the Sankey shows how votes moved through elimination rounds. They answer different questions and complement each other.

Spacing and visual treatment should be consistent with the rest of the proposal detail page. The Sankey gets its own labeled section ("Elimination flow" or similar) so visitors understand what they're looking at. Help-page link or info tooltip that explains how to read it.

### Decision 5: Visual conventions

- **Option colors match the option attractor colors** in the network graph above. If "Mountain Lodge" is purple in the option-attractor layout, it's purple in the Sankey too. Visual consistency between the two visualizations is important — visitors should immediately see "this option here is that option there."
- **Round labels** on each column — "Round 1", "Round 2", etc. — with the eliminated/elected option called out below the round label.
- **Transfer counts visible per round** — when votes flow from option X to option Y between rounds, the link's thickness encodes the count; hovering surfaces the exact number.
- **Final round visually distinct** — winner(s) highlighted clearly. STV multi-winner proposals show all elected options highlighted.
- **Hover behavior** — hovering an option block highlights its incoming and outgoing flows; hovering a flow link surfaces the transfer details.

### Decision 6: Phase 7B.2 polish — suppress voter-to-option arrows for delegators

Currently every voter on an approval/RCV graph renders ballot arrows to their approved/ranked options, including delegators (whose ballot was inherited from their delegate). For delegators, the meaningful relationship is the delegation arrow ("I delegated to X"). Adding ballot arrows to options is redundant and creates clutter, especially since delegators tend to cluster near their delegates and arrows visually overlap.

Fix: skip ballot-to-option arrows for any voter where `is_direct=False`. Their delegation arrow stays. The clustering force still pulls them toward the right region of the graph (because the inherited ballot data drives the force calculation), but the visual lines come only from the delegate.

Implementation is a small condition in the arrow-rendering loop. Check `node.is_direct` (already on the graph nodes) and skip the option-arrow render path if false.

### Decision 7: Phase 7B.2 polish — method-aware legend

The current legend on approval and RCV graphs still shows "Yes / No / Abstain" — copy left over from binary. Replace with method-appropriate legends:

- **Binary:** keep existing Yes/No/Abstain legend unchanged.
- **Approval:** show option labels with their attractor colors as the primary legend. Add a row for "Abstain (empty ballot)" if those voters render distinctly. Add a row for "Anonymous voter" if anonymous voters have distinct visual treatment.
- **RCV:** same as approval — option labels with their colors, plus abstain and anonymous indicators where applicable.

The legend component should dispatch on `proposal.voting_method` like the rest of the visualization work. Reuse the existing legend slot in the layout — this is a content change, not a layout change.

---

## Scope

### Frontend — Sankey component

**New component: `RCVSankeyChart.jsx`** (or whatever naming convention matches the existing component structure).

- Reads `RCVTally` from the proposal results endpoint (same data `RCVResultsPanel.jsx` already consumes).
- Builds D3-Sankey nodes and links from `rounds` data:
  - Nodes: one per (round, option) pair, sized by `option_counts[option_id]` for that round.
  - Links: connect (round_n, option_X) to (round_n+1, option_Y) with width equal to vote transfer count from `transfer_breakdown`.
  - Eliminated options "drop out" visually after their elimination round.
  - Elected options (STV) highlight with distinct treatment and continue forward to subsequent rounds with reduced flow.
- Renders inside a labeled section below the network graph.
- Hover interactions: highlight flow paths, show exact counts on hover.
- Empty/missing data: render placeholder ("Sankey will appear once ballots are cast").
- Provisional rendering for in-voting proposals: render based on current ballot state with provisional framing, same pattern as Phase 7B.1's "currently winning" copy.

**Integration into proposal detail page:**

- Conditional render: only on RCV/STV proposals (`proposal.voting_method === "ranked_choice"`).
- Lives below the existing `OptionAttractorVoteFlowGraph`.
- The existing `RCVResultsPanel.jsx` (text table breakdown) stays — Sankey supplements it, doesn't replace it. The text table is still useful for screen readers and for users who prefer numeric detail.

**Library work:**

- Add `d3-sankey` to `package.json`.
- Verify it's still maintained (last commit within 12-18 months, no critical open issues). If stale or abandoned, flag back to planning before integrating.

### Frontend — Phase 7B.2 polish items

**Item A: Suppress voter-to-option arrows for delegators.**

In `OptionAttractorVoteFlowGraph.jsx` (or wherever Phase 7B.1 placed the arrow-rendering code), update the ballot-arrow render loop to skip nodes where `is_direct=false`. The `is_direct` flag is already available on graph nodes — Phase 7B's backend extension included it.

Verify the delegation arrow path is unchanged for these nodes. They should still show their delegation arrow to their delegate, just not the redundant ballot arrows to options.

**Item B: Method-aware legend.**

Update the legend component (whatever it's called — possibly inline in the visualization component, possibly extracted) to dispatch on `proposal.voting_method`:

```javascript
if (voting_method === "binary") {
  // existing Yes/No/Abstain legend
} else if (voting_method === "approval" || voting_method === "ranked_choice") {
  // option labels with their attractor colors
  // + "Abstain (empty ballot)" entry if abstain voters render distinctly
  // + "Anonymous voter" entry if anonymous voters render distinctly
}
```

Reuse the existing legend layout slot. Don't restructure the panel.

### Backend

No backend work is expected. Verify early in the pass that `RCVTally` and `RCVRound` data is sufficient for the Sankey by hitting the results endpoint for an existing RCV proposal and inspecting the response. If something is missing, flag it before investing in the Sankey component.

If a small backend extension turns out to be needed, keep it minimal and add a backend test for the new field.

---

## Testing

### Suite N — new browser test suite for Sankey

Add a new suite to `browser_testing_playbook.md`. Suite M was used for the network graph; Suite N is the next available letter for Sankey-specific tests. Execute via Claude-in-Chrome.

**N1: Sankey renders on closed RCV proposal.** Open an RCV proposal in `passed` status with multiple rounds of elimination. Confirm the Sankey renders below the network graph with one column per round, eliminated options dropping out, winner highlighted in the final round.

**N2: Sankey renders on closed STV proposal.** Open an STV proposal (multi-winner) in `passed` status. Confirm the Sankey shows multiple winners highlighted in the final round.

**N3: Sankey renders provisionally on in-voting RCV proposal.** Open an RCV proposal currently in `voting` status with some ballots cast. Confirm the Sankey renders with provisional framing.

**N4: Sankey doesn't render on binary proposal.** Open a binary proposal. Confirm no Sankey is shown — only the network graph and existing tally summary.

**N5: Sankey doesn't render on approval proposal.** Open an approval proposal. Confirm no Sankey is shown.

**N6: Sankey placeholder when no ballots cast.** Open an RCV proposal in `voting` status with zero ballots cast (if seedable). Confirm the placeholder text appears rather than an empty diagram or error.

**N7: Hover interactions work.** Hover an option block in the Sankey — incoming and outgoing flows highlight. Hover a flow link — transfer count surfaces on hover.

**N8: Option colors match the network graph.** On an RCV proposal with the network graph and Sankey both visible, confirm the option colors match between the two visualizations.

**N9: Single-round IRV (winner takes majority in round 1).** Open or seed an RCV proposal where the first-choice winner takes a majority outright with no eliminations needed. Confirm the Sankey renders with one column showing the result, no flows.

### Suite M extension — Phase 7B.2 polish tests

Add to the existing Suite M in `browser_testing_playbook.md`:

**M21: Delegator voter-to-option arrows suppressed.** On an approval or RCV proposal with at least one delegator (a voter whose `is_direct=false`), confirm the delegator's node has no ballot arrows to options. The delegation arrow to their delegate is still visible.

**M22: Method-aware legend on approval graph.** On an approval proposal, confirm the legend shows option labels with their colors instead of "Yes/No/Abstain."

**M23: Method-aware legend on RCV graph.** On an RCV proposal, confirm the legend shows option labels with their colors instead of "Yes/No/Abstain."

**M24: Binary legend unchanged.** On a binary proposal, confirm the legend still shows "Yes/No/Abstain" — regression check.

### PostgreSQL smoke test

Same pattern as previous passes. After Suite N + Suite M extensions pass locally, bring up docker-compose stack and verify:

1. Open an RCV proposal — Sankey renders correctly against PostgreSQL-backed data.
2. Open an STV proposal — multi-winner Sankey renders correctly.
3. Open an approval proposal — method-aware legend renders.
4. Open a binary proposal — original legend unchanged.

Zero backend tracebacks expected. If any 500s occur, diagnose from logs.

### Production deploy verification

After merge to `master` and Railway auto-deploys, do a quick post-deploy sanity check on the live site:

- Open an RCV proposal on prod — confirm Sankey renders.
- Open an approval proposal on prod — confirm method-aware legend, no delegator ballot arrows.
- Confirm no regressions in existing proposal flows.

Capture screenshots of the Sankey at IRV (single-winner, multi-round) and STV (multi-winner) scales, plus screenshots of the updated approval and RCV graphs showing the legend change and delegator-arrow suppression. Save to `test_results/phase7C_screenshots/` and commit. The Phase 7B.1 pattern of committing screenshots to the repo continues — this prevents the artifact-loss issue we hit in Phase 7B.

---

## Definition of Done

- D3-Sankey component implemented and rendering correctly on RCV/STV proposals.
- Sankey integrated into proposal detail page below the network graph; conditional render on voting method.
- Provisional rendering for in-voting proposals working.
- Empty-ballot placeholder rendering when no ballots cast.
- Phase 7B.2 polish items: delegator ballot arrows suppressed; method-aware legend live for approval and RCV.
- Help page updated to explain Sankey reading.
- Suite N (9 tests) all pass via Claude-in-Chrome.
- Suite M extension (M21-M24, 4 new tests) all pass.
- PostgreSQL smoke test passes.
- Screenshots committed to `test_results/phase7C_screenshots/`.
- `PROGRESS.md` updated with Phase 7C section: what was built, polish items, test counts, screenshot path.
- `future_improvements_roadmap.md` updated: Phase 7C marked complete.
- Production deploy via merge to `master`. Post-deploy sanity check confirms Sankey, legend, and arrow suppression all work on prod.

---

## Out of Scope

- **Phase 7.5 (Privacy and Access Hardening).** Separate pass, dispatched after this. The Sankey work touches public proposal results data; the privacy work touches admin endpoints. They don't overlap.
- **Animation of vote transfers between rounds.** Could be polish for a future pass; not required for v1. Static Sankey is the established standard.
- **Per-round network graph snapshots** — "show me what the network graph looked like at round 2 of elimination." Different feature, not in scope.
- **Sankey for binary or approval voting.** These don't have rounds. The Sankey is RCV/STV-only by design.
- **Replacing `RCVResultsPanel.jsx` text table with the Sankey.** The text breakdown stays — it's accessible to screen readers and useful for users who want exact numbers. Sankey supplements it.
- **Force tuning v2 for 7-8+ option proposals** (Phase 7B tech debt #1). Defer.
- **Hover-to-isolate dim intensity adjustment** (Phase 7B tech debt #2). Defer.
- **Anonymous voter visual treatment** (Phase 7B.1 tech debt). Defer; the legend update will surface that they exist as a category, but giving them more distinct rendering is a separate small polish pass.
- **994 KB JS bundle optimization** (Phase 7B tech debt #4). Adding D3-Sankey will likely grow the bundle further. Note size impact in PROGRESS.md but don't optimize this pass.

If the dev team discovers adjacent issues during execution, log them as new tech debt rather than expanding this spec.

---

## Notes for the Dev Team

- **Verify backend data sufficiency early.** First task: hit the results endpoint for an existing RCV proposal, inspect the `RCVTally`/`RCVRound` shape, confirm it has what the Sankey needs. If something is missing, flag back before investing in the frontend component. The expectation is that nothing is missing — Phase 7 built the data shape with this visualization in mind.
- **D3-Sankey library check.** Standard pattern from Phase 7's `pyrankvote` vetting. If maintained, use it. If stale, flag back rather than substituting silently.
- **Color consistency between network graph and Sankey is important.** Visitors will look back and forth between the two. The same option should be the same color in both. Reuse whatever color-derivation logic Phase 7B uses for the option attractors.
- **Don't replace `RCVResultsPanel.jsx`.** It's accessible and useful. The Sankey is additional.
- **Phase 7B.2 polish items are small.** The delegator-arrow suppression is a one-line condition; the method-aware legend is content dispatching on voting method. Don't over-engineer either. They should fit easily alongside the Sankey work.
- **Production deploy timing is flexible.** Z is not planning to share the live demo broadly until Phase 7.5 (privacy hardening) ships. So while we still do post-deploy sanity checks, the urgency level is normal — no need to schedule the merge around external events.
- **Suggested team structure:** Lead in delegate mode, frontend dev for Sankey + polish items + help page update, backend dev probably has minimal-to-no work (verify data sufficiency, that's likely it), QA teammate for Suite N + Suite M extension + PostgreSQL smoke + screenshots + post-deploy sanity check.

Report completion with: backend test count (likely unchanged), Suite N results (X/9), Suite M extension results (X/4), PostgreSQL smoke result, prod state after merge, screenshot paths, library decision (D3-Sankey or alternative + why), any new tech debt found.
