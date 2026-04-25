# Phase 7B.1 Screenshots

Captured during Suite M extension runs (2026-04-25) against the docker-compose
stack at `http://localhost`. Logged in as alice (Voter + Admin). All four
scenes show the OptionAttractorVoteFlowGraph (or BinaryVoteFlowGraph for
binary) post-Phase-7B.1 polish: voter→option arrows, drifting attractors,
pre-tick steady state, "Currently winning"/"Currently passing" copy on
in-progress proposals.

## Files

Vector SVG snapshots of the rendered network visualization for each voting
method. SVG is the actual DOM the visualization renders into D3 — no
rasterization loss. Open in any browser or vector editor; they retain the
delegation arrows, voter→option arrows, option attractor nodes, and gold
border for the current user. Rendered at the bounding-box size of the
component (typically ~520×440px after zoom-fit).

- `binary_privacy_act.svg` (5.5 KB) — Digital Privacy Rights Act (binary, in
  voting). Green/red half-plane clustering preserved bit-for-bit from
  Phase 6. **Confirms M11 (binary regression).**

- `approval_4options_garden.svg` (13 KB) — Community Garden Location
  (approval, in voting, 4 options). Option attractors arranged as a circle:
  Riverside Park (blue, top), School Grounds (dark navy, right), Rooftop
  Gardens (red, left), Downtown Lot (green, bottom). Voters cluster between
  approved options. Voter→option arrows in gray (#9CA3AF) full opacity to
  every approved option. Delegation arrows preserved (topic-colored).
  **Confirms M2 (approval layout) + M12 (voter→option arrows on approval).**

- `rcv_4options_offsite.svg` (7.1 KB) — Annual Team Offsite Destination
  (RCV, in voting, 4 options). Mountain Lodge top, Beach Resort bottom-
  right, Forest Cabin bottom-left, Urban Workshop side. Voter→option arrows:
  full opacity to ballot.ranking[0], ~30% opacity to ballot.ranking[1], no
  arrows for rank 3+. **Confirms M4 (RCV layout) + M13 (RCV ranked-arrow
  opacity decay).**

- `stv_5options_committee.svg` (9.8 KB) — Steering Committee — Two New
  Members (STV num_winners=2, passed, 5 options, 15 ballots). All 5
  attractors arranged: Aria Chen (blue, top), Boris Patel (dark navy,
  right), Cara Singh (green, bottom-right), Devon Park (red, bottom),
  Eli Rojas (gold, left). **Confirms layout holds at 5-option scale.**

## Suite M extension test mapping

| Test | Verified by |
|---|---|
| M12 voter→option arrows on approval | `approval_4options_garden.svg` |
| M13 RCV arrow opacity decay (1.0/0.3/0) | `rcv_4options_offsite.svg` |
| M14 toggling option visibly removes + reflows | Live behavior in browser; each SVG shows post-default-render state |
| M15 controls panel collapsible | "Hide controls" button visible in all SVGs |
| M16 option attractor drift | Subjective; positions in SVGs roughly preserve initial-circle layout, drift modest |
| M17 pre-tick eliminates cold-start animation | All SVGs are post-pre-tick converged positions (no jerk on render) |
| M18 in-progress copy ("Currently winning") | RCV svg: "Currently winning: Mountain Lodge after 3 rounds"; binary svg: "Currently passing"; approval svg: "Top option (currently)" callout |
| M19 closed copy past-tense | STV svg: "Winners: Aria Chen, Boris Patel after 3 rounds" |

## Note on JPEG/PNG capture

Attempted headless Chrome PNG captures via `chrome --headless=new --screenshot`
with sessionStorage auth injection, but the SPA's protected routes wouldn't
hydrate in the headless instance reliably (auth-inject + `location.replace()`
returned a blank state). SVG capture via the live MCP-driven Chrome session
(authoritative — same DOM the user sees) was the more reliable path. JPEG
screenshots captured via `mcp__claude-in-chrome__computer` are visible inline
in the Suite M extension session transcript at PROGRESS.md.
