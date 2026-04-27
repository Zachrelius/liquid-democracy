# Phase 7C Screenshots

Captured 2026-04-26 against local dev (backend :8001, frontend :5173) using the same
SVG-via-upload-server pattern Phase 7B.1 established.

| File | What it shows |
|---|---|
| `stv_sankey_steering.svg` | STV multi-winner Sankey on closed Steering Committee proposal — 3 rounds, 13 slabs, 12 transfer/carry links (N1 + N2). |
| `irv_sankey_offsite.svg` | IRV multi-round Sankey on in-voting Offsite proposal — 2 rounds, 7 slabs, 4 links, "(Provisional)" header (N3). |
| `irv_provisional.svg` | Earlier capture of the same Offsite Sankey from initial QA pass — kept as before/after evidence of pre-fix render. |
| `irv_single_round_coffee.svg` | Single-round Sankey on closed Coffee Vendor proposal (tied final) — 2 slabs, 0 flow links (N9). |
| `rcv_network_offsite_polished.svg` | Offsite IRV vote-network graph showing voter→option arrows from direct voters only — Dave (delegator) is visible in the cluster but has no ballot arrows, only his delegation arrow (M21). |
| `approval_network_office_renovation.svg` | Approval vote-network graph also showing M21 — 4 arrows from 3 direct voters (matches `sum(approvals)` for direct), 1 delegator excluded. |
| `rcv_legend.html` | Method-aware legend on RCV proposal: Mountain Lodge / Beach Resort / Urban Workshop / Forest Cabin + Abstain (empty ballot) + Delegation + Public delegate + You + Anonymous voter (M23). |
| `approval_legend.html` | Method-aware legend on approval proposal: option labels with attractor colors (M22). |
| `binary_legend.html` | Binary legend unchanged — Yes / No / Abstain / Not voted / Delegation / Public delegate / You (M24 regression). |

The HTML legend captures are wrapped `<div>` elements with inline classes; open in any browser to render.

Fix shipped during QA: backend `/vote-graph` ships `vote_source: "direct"|"delegation"`, NOT
`is_direct`. The frontend implementer assumed `is_direct` and Polish A's
`if (!v.is_direct) continue;` was suppressing every voter's ballot arrows. Replaced with
`if (v.vote_source !== 'direct') continue;` in `OptionAttractorVoteFlowGraph.jsx`.
Verified post-fix: 6 arrows on Offsite (3 direct × 2 ranks), 4 arrows on Office Renovation
(direct ballots × approvals), 0 arrows attributed to delegators in either case.

The `upload_server.py` is the local SVG capture helper; do not commit it. Kept here only
during the run.
