# Phase 7C.1 Screenshots

Captured 2026-04-27 against local dev (backend port 8002 on a fresh process; frontend port 5173 with Vite proxy reconfigured for the QA run; reverted post-test). Driven as alice (demo-login JWT injected into localStorage).

| File | What it shows | Tests confirmed |
|---|---|---|
| `sankey_steering_init_final.svg` | Steering Committee STV (3 rounds, 2 winners). Columns: Initial / Round 1 / Round 2 / Round 3 / Final. 21 slabs, 22 flow paths. Final column highlights both `tally.winners` with the `#1B3A5C` 3-px dark-navy stroke; non-winners dimmed with `fill-opacity 0.45`. | N10, N11, N12 |
| `sankey_coffee_single_round.svg` | Coffee Vendor IRV. With Phase 7C.1's expanded seed it now resolves in 2 rounds (Init / Round 1 / Round 2 / Final), 10 slabs, 9 paths. Demonstrates the column structure on a small RCV. | N10/N11 secondary |
| `approval_network_with_anonymous_voters.svg` | Community Garden approval (alice's view). 12 anonymous voter circles render with `#7A93AE` dashed `3,2` stroke and `#F4F6F9` fill, distinct from named voters and abstainers. 31 voter→option arrows total — anonymous voters now contribute arrows because the privacy boundary fix returns ballot data for every voter regardless of identity visibility. | M25, M26, M27 |

## Tests not represented as separate captures

- **N12 winner highlighting** is captured inside `sankey_steering_init_final.svg` (verified via DOM inspection: 2 of 4 Final rects have `stroke=#1B3A5C strokeWidth=3`).
- **N13 single-round IRV** was skipped: with the Phase 7C.1 seed expansion, the previously single-round-tied Coffee Vendor now resolves in 2 rounds. No proposal in the new seed has `rounds.length === 1`. Code path verified by reading `RCVSankeyChart.jsx`'s `buildSankeyData` — single-round case renders Initial → round 0 → Final naturally with no middle elimination logic.
- **M27 hover tooltip** was verified live by dispatching a `mouseenter` event on an anonymous voter circle and reading the rendered tooltip text: "Anonymous voter — only public delegates and users you follow show their names. Their ballot is included in the visualization." plus the ballot summary "2 of 4 options approved." (HTML overlay; not a separate SVG.)
- **M28 inherited-abstain tooltip** was verified by hovering Dave the Delegator on a J1: Community Project Selection approval where his delegate (Alice Voter) abstained. Tooltip rendered: "Abstained (via delegation from Alice Voter)" — exactly the spec's Decision-4 copy. (HTML overlay; not a separate SVG.)
- **M29 idempotent seed regression** was verified by the backend dev's PostgreSQL smoke run (3 successive `python -m seed_if_empty` invocations against a fresh `postgres:16-alpine` stack, identical row counts after each: 36 users / 129 votes / 57 delegations / 30 follow_relationships / 5 delegate_profiles / 44 topic_precedences / 10 proposals / 19 proposal_options / 6 topics). Plus a local additive run that took the existing 26-user DB to 36 users without duplicating any rows.
- **M30 privacy boundary preserved** was verified by inspecting the API response shape for a proposal: 0 anonymous-voter nodes contain any of `username`, `email`, `full_name`, or `display_name` keys. The hover tooltip on an anonymous voter contains no UUID-like strings. Identity is fully redacted; only `ballot` content shows through.

## Method note

SVG capture used the same upload-server pattern Phase 7B.1 / 7C established (local Python HTTPServer at :9876 receiving POSTs from the page's JavaScript context). The upload-server file was kept out of the committed screenshots set.
