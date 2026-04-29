# Phase 8.1 Prod Verification Screenshots

Browser-driven verification on production after the Phase 8.1 Railway deploy.

- **Date:** 2026-04-29
- **Bundle:** `index-DBV4tyoe.js` (deployed shortly after master push of commits 5b29620..94e4e75)
- **Method:** Logged in as alice via `/api/auth/demo-login`, navigated to the live STV proposals, inspected the Sankey SVG via `XMLSerializer().serializeToString()` and DOM `text` element queries.

## Files

### `Q1_Q2_steering_sankey_prod.svg`

Canonical screenshot covering both Q1 (Item 4) and Q2 (Item 5). Full Sankey from `https://www.liquiddemocracy.us/proposals/d298baf3-822d-4b13-9be5-c24acf3881b9` (Steering Committee — Two New Members, STV, 2 winners).

**Q1 evidence — column-header alphabetization:**
- The mid-Sankey eliminated-options column reads `✗ Cara Singh, Eli Rojas` (alphabetical: C before E).
- Pre-fix would have been `✗ Eli Rojas, Cara Singh` (object-iteration order from `option_counts`).

**Q2 evidence — halt-winner annotation:**
- Below the bold `Final` column header (font-size 11, `#1B3A5C`, weight 600) there is a smaller italic gray text: `Boris Patel (seat filled by remaining-candidate)` (font-size 9, font-style italic, `#6B7280`).
- Boris won by halt: max count 6.25 < quota 7.0 = 21/3, with 2 seats and 2 remaining candidates so the algorithm terminated.
- Aria Chen also wins (crossed quota in round 1) but she's NOT in the annotation — she's not a halt-winner.
- The Final-column dark-border highlight on the winners is unchanged (Boris and Aria both render with stroke `#1B3A5C` width 3).

## Annual Team Offsite (verified, no separate SVG file)

The proposal at `https://www.liquiddemocracy.us/proposals/6b7ec039-b398-41fc-9773-745c2a73be77` (Annual Team Offsite Destination, status `voting`) was also confirmed to render the halt annotation. The full SVG was not captured to disk because the canonical Steering example sufficiently demonstrates both items; offsite verification was done via DOM `text` element enumeration.

Observed `<text>` elements on Annual Team Offsite Sankey (key entries):

| text | font-size | font-style | fill | font-weight |
|---|---|---|---|---|
| `Initial` | 11 | — | `#1B3A5C` | 600 |
| `✗ Urban Workshop` | 10 | — | `#C0392B` | 500 |
| `✗ Forest Cabin` | 10 | — | `#C0392B` | 500 |
| `Final` | 11 | — | `#1B3A5C` | 600 |
| `Beach Resort (seat filled by remaining-candidate)` | **9** | **italic** | **`#6B7280`** | — |

Same styling, same template, different proposal — confirms the annotation generalizes.

## Item 1 + Item 3 verification (no screenshots required)

Item 1: `https://www.liquiddemocracy.us/help/voting-methods` loaded without auth (verified after `localStorage.clear()`). Pathname stayed `/help/voting-methods`, h1 rendered `Voting Methods`, no redirect to `/login`, no errors.

Item 3 audit: every public-content route in `App.jsx` was hit unauthenticated and returned 200 without redirect. List captured in the Phase 8.1 completion notes.

## Suite Q result

- **Q1 (column-header alphabetization):** ✅ PASS — `✗ Cara Singh, Eli Rojas` exact text on Steering.
- **Q2 (halt-winner annotation):** ✅ PASS — exact spec template present on both Steering (Boris Patel) and Annual Team Offsite (Beach Resort), with the prescribed smaller/italic/secondary visual treatment.
