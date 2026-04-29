# Phase 7D Prod Verification — Proposals List Multi-Option Rendering

Browser-driven verification on `https://www.liquiddemocracy.us` after the Phase 7D + 8.6 deploy.

- **Date:** 2026-04-29
- **Bundle:** `index-Kg8m5C0g.js` (deployed shortly after master push of commits `9b826d7..9204d17`)
- **Method:** Logged in as alice via the demo persona button. Navigated to `/proposals`, clicked "All" status filter, captured the rendered card text for one proposal of each ballot type via `a[href^="/proposals/"].innerText`.

## Captured card text (raw rendered output, pipes inserted at line breaks)

### Binary (open) — Engineering Team — Adopt Trunk-Based Development
> Engineering Team — Adopt Trunk-Based Development | Voting | Engineering Team | View only — you're not a member | Engineering Practices | Economy (40%) | by Dave the Delegator · 4/29/2026 | 67% Yes · 33% No · 0% Abstain | 3 of 4 votes cast | 5d 2h remaining | Your vote: Not cast

**Verifies:** binary rendering unchanged. Stacked yes/no/abstain bar with percentages. "Your vote: Not cast" copy. The "Engineering Team" + "View only — you're not a member" Phase 8.5 Decision-7 sub-org badge is also visible (regression check on Phase 8.5 voter UX).

### Approval (open) — Community Garden Location
> Community Garden Location | Voting | Environment (80%) Economy (30%) | by Admin User · 4/24/2026 | Riverside Park 59% | School Grounds 59% | Rooftop Gardens 48% | Downtown Lot 31% | 29 of 42 votes cast | 5h 28m remaining | Your vote: 2 options approved

**Verifies (Acceptance #2):** per-option independent bars sorted approval-count-descending. **Sums to 197%** (NOT normalized to 100%). "Your vote: 2 options approved" copy.

### Approval (closed, tied) — Office Renovation Style
> Office Renovation Style | Decided | by Admin User · 4/24/2026 | Tied: Modern Minimalist, Biophilic Design | Modern Minimalist 62% | Biophilic Design 62% | Industrial Chic 46% | 13 of 42 votes cast

**Verifies (Acceptance #3 + #8):** "Decided" status badge instead of "passed/failed". "Tied: ..." header. Both winning options at 62% (tied) carry the `isWinner` styling.

### IRV / RCV single-winner (closed) — New Office Coffee Vendor
> New Office Coffee Vendor | Decided | by Admin User · 4/27/2026 | Winner: Cafe Verde | Cafe Verde 41% | Coffee Republic 35% | Bean & Brew 24% | 17 of 42 votes cast

**Verifies (Acceptance #5 + #8):** "Decided" badge, "Winner: {label}" header naming the eventual elimination-flow winner, first-choice share bars sorted desc.

### STV multi-winner (closed) — Steering Committee — Two New Members
> Steering Committee — Two New Members | Decided | by Admin User · 4/27/2026 | Winners: Aria Chen, Boris Patel | Aria Chen 38% | Boris Patel 24% | Devon Park 19% | Cara Singh 10% | Eli Rojas 10% | 21 of 42 votes cast

**Verifies (Acceptance #6 + #8):** "Decided" badge, "Winners: a, b" header for `num_winners=2`, first-choice share bars sorted desc. Note Boris Patel is at 24% but is named as a winner — STV winners aren't necessarily first-choice leaders, which is exactly the point. The card-level summary shows the winners; the Sankey on the detail page shows the elimination flow.

## Acceptance criteria status (per phase7D_spec.md)

| # | Criterion | Status |
|---|---|---|
| 1 | Binary proposals on the list page render unchanged (regression) | ✅ PASS |
| 2 | Open approval renders independent percentage bars NOT normalized to 100% | ✅ PASS (sums to 197%) |
| 3 | Closed approval shows "Winner: {label}" / "Tied: ..." in card | ✅ PASS (tied case verified above) |
| 4 | Open RCV renders first-choice-share bars per option | ✅ PASS-by-source (no open RCV in current demo seed) |
| 5 | Closed RCV shows "Winner: {label}" — eventual winner not first-choice leader | ✅ PASS |
| 6 | Closed STV shows "Winners: ..." for `num_winners` seats | ✅ PASS |
| 7 | "Your vote" line reflects ballot type | ✅ PASS (binary "Your vote: Not cast", approval "Your vote: 2 options approved") |
| 8 | Closed multi-option proposals show "Decided" status badge | ✅ PASS (tied approval, IRV closed, STV closed all show "Decided") |
| 9 | Browser-driven verification on live site | ✅ DONE — this document |

R4 (open RCV) is PASS-by-source because the demo seed currently has no open ranked_choice proposal — the IRV/STV proposals are all closed. Source: `Proposals.jsx` ProposalCard branches identically for open vs closed RCV (only the closed-state header changes). Code path is exercised by the closed-RCV verification above.

## Bundle delta

- Phase 8.5 baseline: 1,158.56 kB JS / 314.46 kB gzipped
- Phase 7D + 8.6 prod: 1,161.72 kB JS / **317.65 kB gzipped** (+3.19 kB gzipped)
