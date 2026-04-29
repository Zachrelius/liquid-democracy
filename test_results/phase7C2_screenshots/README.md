# Phase 7C.2 Screenshots

Captured 2026-04-28 against local dev (backend port 8002 — phantom socket on 8001 hit again, Vite proxy temporarily redirected for the run, reverted post-test). Driven as alice via demo-login.

| File | What it shows | Tests confirmed |
|---|---|---|
| `steering_committee_tally_pre_fix.json` | Raw `tally.rounds` JSON for the Steering Committee STV proposal pulled from prod **before** the fix. Documents the multi-source bug input: Round 2 has `transferred_from=Eli` and `transfer_breakdown` summing to 2.5416 — but Eli only had 2.25 votes and Cara also dropped 2.125 → 0 in the same round. Confirms Hypothesis A (pyrankvote packs paired surplus+elimination events into one `ElectionResultRound`). | Decision 1 diagnosis |
| `steering_committee_sankey_post_fix.svg` | Steering Committee STV Sankey rendered locally with the Phase 7C.2 frontend fix in place. Cara@R1 now has visible outgoing flow (Boris 0.55, Devon 0.69, Exhausted 0.89 = 2.125). Eli@R1 outflow is constrained to his actual count (Boris 0.58, Devon 0.73, Exhausted 0.94 = 2.25). A muted-gray "Exhausted (1.83)" terminal node appears in the R2 column. Five columns total: Initial / Round 1 / Round 2 / Round 3 / Final, with both winners (Aria + Boris) highlighted in the Final column. | N14, by-link kind tagging verified via DOM inspection |
| `coffee_vendor_irv_sankey_unchanged.svg` | Coffee Vendor IRV Sankey — single-source-per-round, no exhausted volume, no surplus. Renders identically to Phase 7C.1 (no Exhausted node, only `transfer` / `carry` / `initial` / `final` link kinds). Confirms the multi-source path doesn't touch clean IRV data. | N14 regression on simpler IRV |

## Tests not represented as separate captures

- **N15 (surplus vs. elimination tooltip dispatch)** verified by dispatching synthetic mouseenter on three link variants on the Steering Sankey and reading the rendered tooltip:
  - `transfer-surplus` (R0→R1 Aria→Boris): "Aria Chen → Boris Patel · Surplus transfer: 0.13 votes (each ballot above threshold contributed a fractional vote to its next preference)." ✓
  - `transfer-multi-source` (R1→R2 Cara→Boris): "Cara Singh → Boris Patel · Combined-round transfer: ~0.55 votes (this round had multiple eliminations; share is approximate, not ballot-traced)." ✓
  - `transfer-exhausted` (R1→R2 Eli→Exhausted): "Eli Rojas · Exhausted: 0.94 votes (no remaining preference on these ballots)." ✓
  - `transfer` single-source elimination (Coffee Vendor R1→R2 Bean & Brew → Cafe Verde): "Bean & Brew → Cafe Verde · Transfer: 3 votes" — original 7C.1 copy, unchanged ✓
- **M31 (anonymous voter trimmed two-line tooltip)** verified by source review: `OptionAttractorVoteFlowGraph.jsx` lines ~903-940 and `BinaryVoteFlowGraph.jsx` lines ~432-470 both branch on `tooltip.node.isAnonymous` to render a header line ending with the at-a-glance fact (count for approval/RCV, vote chip for binary) and a second line with the trimmed privacy explainer "Their ballot is included; only public delegates and people you follow show names."
- **M32 (detail-panel inherited-abstain copy)** verified by source review:
  - `OptionAttractorVoteFlowGraph.jsx` `renderBallotDetail` returns `renderAbstainTooltipText(n, data, votingMethod)` for empty-ballot delegators (both approval and RCV), and the redundant `<p>via delegation</p>` footer is suppressed via `isInheritedAbstain(selectedNode)`.
  - `BinaryVoteFlowGraph.jsx` detail panel branches on `selectedNode.vote === 'abstain' && selectedNode.vote_source === 'delegation'` and renders `Abstained (via delegation from {Name})` (or `Abstained (via delegation)` when `lookupDelegateName` returns null), suppressing the older `Vote: ABSTAIN ... (via delegation)` form for that case.

## Method note

HTML/SVG capture used the same upload-server pattern Phase 7C/7C.1/7.5 established (local Python `HTTPServer` at :9876 receiving POSTs from the page's JavaScript context). The upload-server file (`.tmp_diag/upload_server.py`) and other diagnostic scratch are not committed.
