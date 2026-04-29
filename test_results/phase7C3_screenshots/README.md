# Phase 7C.3 Screenshots

Captured 2026-04-29 against prod (`https://www.liquiddemocracy.us`, frontend bundle `index-0pxEDS4b.js`, deployed Wed 29 Apr 13:14:59 GMT). Driven as alice via demo-login.

| File | What it shows | Tests confirmed |
|---|---|---|
| `steering_committee_tally_diagnostic.json` | Raw tally JSON for the Steering Committee STV proposal pulled before the fix. Documents the input shape (`option_counts` per round, eliminated/elected pyrankvote-metadata mismatches). | Pre-fix diagnostic input |
| `annual_team_offsite_tally_diagnostic.json` | Raw tally JSON for the Annual Team Offsite IRV proposal. Used to confirm the new transition-derived logic still produces the correct "✗ Urban Workshop" → "✗ Forest Cabin" sequence on a clean IRV case. | Pre-fix diagnostic input |
| `phase7C3_diagnostic.md` | Dev-side diagnostic write-up. Documents Hypothesis B (pyrankvote labels Devon eliminated despite his count never dropping to zero) and the resolution: derive labels from observed `option_counts` transitions, accepting the spec deviation that Boris is elected by algorithm halt at 6.25 < quota 7.0 (no "✓ Boris" column will ever appear). | Hypothesis B diagnosis + spec-deviation rationale |
| `steering_committee_sankey_post_fix.svg` | Steering Committee STV Sankey rendered against the deployed 7C.3 frontend. Three event columns: `Initial` → `✓ Aria Chen` → `✗ Eli Rojas, Cara Singh` → `Final`. Round 2 (pyrankvote-only metadata, no observable count change for Cara) is collapsed. Devon Park appears in `Final` at 5.92 with no ✗ annotation and no winner-highlight. Boris Patel appears in `Final` at 6.25 with the dark-navy winner-highlight border (`stroke="#1B3A5C"` width `3`) but no "✓" column annotation — confirms the spec deviation: he's elected by algorithm halt, not quota crossing. Aria Chen is winner-highlighted in `Final` at 7. | AC1 (event-only column derivation), AC2 (collapse rule), AC3 (Devon no ✗), AC4 (Boris highlighted via halt without "✓"), AC5 (Aria highlighted) |
| `annual_team_offsite_sankey_post_fix.svg` | Annual Team Offsite IRV Sankey rendered against the deployed 7C.3 frontend. Three event columns: `Initial` → `✗ Urban Workshop` → `✗ Forest Cabin` → `Final`. Beach Resort wins by halt at 8 (quota = 17/2 = 8.5; never crossed) and is winner-highlighted in `Final` (dark-navy stroke width 3). Mountain Lodge appears in `Final` at 7 (runner-up, no highlight). Two `Exhausted` terminal nodes (1, 1) are present from the elimination rounds. No regression vs. Phase 7C.2 — clean IRV with no collapsed columns mid-flow (every round has an event). | AC6 (IRV regression — clean transitions still labeled) |

## SVG text-content verification

`Array.from(document.querySelectorAll('text')).map(t => t.textContent).filter(t => t.includes('✓') || t.includes('✗'))` returned:

- **Steering Committee:** `["✓ Aria Chen", "✗ Eli Rojas, Cara Singh"]` — exactly two annotations, matching the as-shipped expected sequence (no "✓ Boris" because his 6.25 < quota 7.0; no "✗ Devon" because his count never drops to zero).
- **Annual Team Offsite:** `["✗ Urban Workshop", "✗ Forest Cabin"]` — exactly two annotations, both eliminations (no "✓" because Beach Resort 8 < quota 8.5; wins by algorithm halt).

## Spec deviation note

Phase 7C.3's `phase7C3_spec.md` Acceptance Criterion 1 predicted a 4-column Steering sequence including "✓ Boris Patel". The dev's pre-fix diagnostic (`phase7C3_diagnostic.md`) confirmed Boris's max round count is 6.25, below the quota of 7.0 — pyrankvote elects him by algorithm halt (2 seats remaining, 2 candidates left after Eli/Cara elimination). The transition-based derivation rule cannot synthesize a "✓" event column without a quota crossing, so reality wins: Boris shows in `Final` with the existing `winners.has(...)` highlight styling but no "✓" column annotation. This is documented in the dev's diagnostic md and is the intended outcome per the spec's higher-priority "reality wins" directive.

## Method note

Captured the rendered Sankey SVG via `mcp__claude-in-chrome__javascript_tool` from the live production page. Initial attempts to POST to a localhost upload server (`http://localhost:9876/`, the same pattern used for Phase 7C/7C.1/7C.2) failed because Chrome's mixed-content policy blocks `https://www.liquiddemocracy.us` → `http://localhost`. As a fallback, the SVG was base64-chunked through `console.log`, captured via `read_console_messages`, and reconstructed locally via a small Node helper. The reconstruction script and chunk JSON are in `.tmp_diag/` (git-ignored).
