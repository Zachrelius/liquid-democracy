# Phase 7D Diagnostic — Proposals List Card Data Shapes

Pulled from prod `/api/proposals/{id}/results` and `/api/proposals/{id}/my-vote` as alice (demo-login) on 2026-04-29. One proposal of each ballot type from the demo seed.

## 1. Binary — Universal Healthcare Coverage Act (`3a3b63f1...`, voting)

```json
{"voting_method":"binary","yes":14,"no":7,"abstain":0,"votes_cast":21,"total_eligible":42,
 "yes_pct":0.6667,"no_pct":0.3333,"abstain_pct":0.0,"quorum_met":true,"threshold_met":true,
 "option_approvals":null,"option_labels":null,"winners":null,"tied":null,"rounds":null,"method":null,"num_winners":null}
```

**Card reads:** `tally.yes`, `tally.no`, `tally.abstain`, `tally.votes_cast`, `tally.total_eligible`. Status badge from `proposal.status` ("voting"/"passed"/"failed"). No change from current behavior.

`my-vote` shape: `{vote_value: "yes"|"no"|"abstain", is_direct, cast_by}`.

## 2. Approval — Community Garden Location (`d936cd15...`, voting) and Office Renovation Style (`62f25765...`, passed)

```json
{"voting_method":"approval","option_approvals":{"7d67...":17,"a352...":17,"2b8c...":9,"9756...":14},
 "option_labels":{"7d67...":"Riverside Park","a352...":"School Grounds",...},
 "total_ballots_cast":29,"total_abstain":1,"votes_cast":29,"total_eligible":42,
 "winners":["7d67...","a352..."],"tied":true,"tie_resolution":null,
 "yes":0,"no":0,"abstain":0,"rounds":null,"method":null,"num_winners":null}
```

**Card reads:**
- Per-option approval count: `tally.option_approvals[optionId]`
- Per-option label: `proposal.options[].label` keyed by id (also available via `tally.option_labels`; we'll use `proposal.options` since the spec says so)
- Denominator for percentage: `tally.votes_cast` (= `tally.total_ballots_cast`). Bars are independent (do NOT normalize across options).
- Closed-state winner(s): `tally.winners` is an array of option IDs (already exposed). `tally.tied` is a boolean. Use `tally.tied === true` to render "Tied: ..." instead of "Winner: ...".

`my-vote`: `{approvals: [optionId, ...], is_direct, cast_by}`. "Your vote: N options approved" — N = `myVote.approvals?.length ?? 0`. Append "via {cast_by.display_name}" if `!is_direct`.

## 3. RCV (single-winner / IRV) — Annual Team Offsite (`6b7ec039...`, voting)

```json
{"voting_method":"ranked_choice","method":"irv","num_winners":1,
 "option_labels":{"699c...":"Mountain Lodge","27a1...":"Beach Resort","ebc4...":"Urban Workshop","a567...":"Forest Cabin"},
 "rounds":[{"round_number":0,"option_counts":{"27a1...":5.0,"699c...":5.0,"a567...":4.0,"ebc4...":3.0},"eliminated":"ebc4...","elected":[]},
           {"round_number":1,...},{"round_number":2,"elected":["27a1..."]}],
 "winners":["27a1..."],"tied":false,"tie_resolution":null,
 "votes_cast":17,"total_eligible":42,"total_ballots_cast":17,"option_approvals":null}
```

**Card reads:**
- Per-option first-choice count: `tally.rounds[0].option_counts[optionId]` (round_number=0 is the first round).
- Per-option label: `proposal.options[].label` (or `tally.option_labels`).
- Denominator: `tally.votes_cast`.
- Closed-state winner: `tally.winners[0]` (single ID), look up label.
- `tally.tied` boolean for tie state (rare on IRV; the Coffee Vendor proposal which the seed describes as a "tied final round" actually resolved to non-tied `winners=["6de1..."]` by the time we sampled — so `tied` is reliable on the response).

`my-vote`: `{ranking: [optionId, ...], is_direct, cast_by}`. "Your vote: ranked N of M options" — N = `myVote.ranking?.length ?? 0`, M = `proposal.options.length`. "via {cast_by.display_name}" when delegated.

## 4. STV (multi-winner) — Steering Committee (`d298baf3...`, passed, num_winners=2)

Same shape as RCV. Distinguishing fields: `tally.method === "stv"`, `tally.num_winners > 1`, `tally.winners` length matches `num_winners`. Same `rounds[0].option_counts` for first-choice bars. Same `option_labels`. Same my-vote shape (`ranking`).

**Card reads:** Identical to RCV plus list all winner labels for closed state ("Winners: a, b, ...").

## Branching key on the card

`proposal.voting_method` is sufficient for the binary/approval/ranked_choice split. To distinguish IRV vs STV in the closed-state heading, branch on `proposal.num_winners` (already on the proposal payload — line 73 confirms via `num_winners":2` for STV vs `num_winners":1` for IRV).

## Diagnostic confirmations

1. **Field names confirmed:**
   - Approval per-option counts: `tally.option_approvals` (object keyed by option id)
   - RCV/STV first-choice counts: `tally.rounds[0].option_counts` (object keyed by option id)
2. **Winners exposed directly:** Yes — `tally.winners` is an array of option IDs on every multi-option response. No frontend derivation needed.
3. **Tie state:** `tally.tied` is a boolean on multi-option responses. Reliable. No need to infer from equal counts.

**No backend changes needed.** Every field the card needs is already on `/results`.
