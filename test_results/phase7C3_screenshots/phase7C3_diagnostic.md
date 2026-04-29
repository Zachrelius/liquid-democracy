# Phase 7C.3 Diagnostic — Column Label Derivation

Pulled from prod `/api/proposals/{id}/results` as alice (demo-login) on 2026-04-29.

## Steering Committee STV Tally

**Proposal:** Steering Committee — Two New Members
**ID:** `d298baf3-822d-4b13-9be5-c24acf3881b9`
**Method:** STV, 2 winners, 21 total ballots cast
**Winners:** Aria Chen, Boris Patel
**Quota:** 21 / (2+1) = 7.0 (Hagenbach-Bischoff)

### option_counts per round

| Option | Round 0 | Round 1 | Round 2 | Final |
|--------|---------|---------|---------|-------|
| Aria Chen | 8.0000 | 7.0000 | 7.0000 | 7.0000 |
| Boris Patel | 5.0000 | 5.1250 | 6.2500 | 6.2500 |
| Devon Park | 4.0000 | 4.5000 | 5.9167 | 5.9167 |
| Eli Rojas | 2.0000 | 2.2500 | 0.0000 | 0.0000 |
| Cara Singh | 2.0000 | 2.1250 | 0.0000 | 0.0000 |

Note: Initial column is synthetic — it mirrors Round 0's option_counts identically (same values, no transition from a "prior" state).

### Transition-rule application

**Quota = 7.0** (options crossing this threshold are "elected").

**Transition: Initial → Round 0**
- prev (Initial) = same as Round 0 option_counts (identical values)
- Eliminated (dropped to zero): none
- Newly elected (>= 7.0, not seen prior): **Aria Chen** (8.0 >= 7.0)
- Result: **KEEP — label "✓ Aria Chen"** (rawRoundIdx = 0)

**Transition: Round 0 → Round 1**
- Eliminated (dropped to zero): none
  - Cara: 2.0 → 2.125 (increased, surplus redistributed from Aria)
  - Eli: 2.0 → 2.25 (increased)
  - All counts change; nobody drops to zero
- Newly elected: none (Aria already counted; Boris=5.125, Devon=4.5, all < 7.0)
- Result: **COLLAPSE — no observable event**

**Transition: Round 1 → Round 2**
- Eliminated (dropped to zero):
  - **Eli Rojas**: 2.25 → 0.0
  - **Cara Singh**: 2.125 → 0.0
- Newly elected: Boris=6.25 < 7.0 (no new quota crossings)
- Result: **KEEP — label "✗ Eli Rojas, Cara Singh"** (rawRoundIdx = 2)

**Transition: Round 2 → Final**
- Eliminated: none (same counts as Round 2)
- Newly elected: Boris=6.25 < 7.0 (never crosses quota)
- Result: **COLLAPSE — no event label on Final column**

### Key finding: Boris Patel never crosses quota

Boris Patel's maximum count across all rounds is 6.25, which is below quota=7.0. He is elected by **algorithm halt**: when only 2 candidates remain (Boris and Devon) for 2 seats, the algorithm terminates and declares both elected. This is not a quota-crossing event.

**The spec's predicted column "✓ Boris Patel" cannot be produced by the rule.** Per spec: "reality wins." The Final column shows Boris as a winner (highlighted slab) without a "✓ Boris Patel" column header.

### Devon Park elimination check

| Round | Devon count | Drops to zero? |
|-------|-------------|----------------|
| Round 0 | 4.0000 | No |
| Round 1 | 4.5000 | No |
| Round 2 | 5.9167 | No |
| Final | 5.9167 | No |

Devon never satisfies the elimination predicate. He is a runner-up. No ✗ marking anywhere.

### Actual post-collapse column sequence

```
Initial → "✓ Aria Chen" → "✗ Eli Rojas, Cara Singh" → Final
```

vs. spec's prediction:
```
Initial → "✓ Aria Chen" → "✗ Cara Singh, Eli Rojas" → "✓ Boris Patel" → Final
```

Differences:
1. The order within the elimination label is Eli then Cara (order they appear in option_counts at R2→Final transition scan). Either order is correct display-wise; the implementation uses iteration order of the option_counts object.
2. There is no "✓ Boris Patel" column because Boris never crosses quota by count.

---

## Annual Team Offsite IRV Tally (Regression Check)

**Proposal:** Annual Team Offsite Destination
**ID:** `6b7ec039-b398-41fc-9773-745c2a73be77`
**Method:** IRV, 1 winner, 17 total ballots cast
**Winner:** Beach Resort
**Quota:** 17 / (1+1) = 8.5 (Hagenbach-Bischoff)

### option_counts per round

| Option | Round 0 | Round 1 | Round 2 | Final |
|--------|---------|---------|---------|-------|
| Beach Resort | 5.0 | 6.0 | 8.0 | 8.0 |
| Mountain Lodge | 5.0 | 6.0 | 7.0 | 7.0 |
| Forest Cabin | 4.0 | 4.0 | 0.0 | 0.0 |
| Urban Workshop | 3.0 | 0.0 | 0.0 | 0.0 |

### Transition-rule application

**Transition: Initial → Round 0**
- Initial mirrors Round 0 (same counts)
- Eliminated: none
- Newly elected: none (all counts < 8.5)
- Result: **COLLAPSE**

**Transition: Round 0 → Round 1**
- Eliminated: **Urban Workshop** (3.0 → 0.0)
- Newly elected: none (Beach=6, Mountain=6, Forest=4, all < 8.5)
- Result: **KEEP — label "✗ Urban Workshop"** (rawRoundIdx = 1)

**Transition: Round 1 → Round 2**
- Eliminated: **Forest Cabin** (4.0 → 0.0)
- Newly elected: none (Beach=8, Mountain=7, both < 8.5)
- Result: **KEEP — label "✗ Forest Cabin"** (rawRoundIdx = 2)

**Transition: Round 2 → Final**
- Eliminated: none (same counts)
- Newly elected: Beach=8.0 < 8.5 (wins by algorithm halt, not quota)
- Result: **COLLAPSE**

### Actual post-collapse column sequence

```
Initial → "✗ Urban Workshop" → "✗ Forest Cabin" → Final
```

This is clean and correct. All three IRV elimination events are visible. Beach Resort wins in Final as the last remaining winner.

---

## Implementation implications

1. **`deriveDisplayColumns(tally)`** must walk transitions (Initial→R0, then R[i]→R[i+1] for all rounds, then R[last]→Final) and apply the rule. Columns with no event are omitted from the returned list.

2. **No "✓ Boris" column.** The Final column in the Steering tally will show Boris as a winner (dark border per existing winner-highlighting logic) without a "✓ Boris Patel" column header.

3. **Devon Park.** Never eliminated, never elected by quota. Appears in Final at 5.92 with dimmed opacity (non-winner dimming already in existing code). No ✗ mark.

4. **IRV regression.** The Annual Team Offsite tally will produce exactly the right elimination-event labels with no quota-crossing events (IRV winners typically win by algorithm halt in practice, not strict majority).

5. **`buildSankeyData` impact.** The link-generation code in `buildSankeyData` currently iterates `rounds` pairwise. Since visible columns map back to specific `rawRoundIdx` values (which are pyrankvote round indices), and slabs between visible columns use adjacent visible `rawRoundIdx` pairs for their delta computation, `buildSankeyData` does **not** need changes — it already iterates all pyrankvote rounds pairwise. The column-derivation change is purely in the rendering/labeling section of the D3 effect.

6. **The column-label rendering loop** (lines ~480-527) currently reads `round.eliminated` and `round.elected` from pyrankvote metadata. It must be replaced to use `deriveDisplayColumns()` output instead.
