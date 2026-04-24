# Phase 7 — Multi-Option Voting Pass B: RCV and STV

**Type:** Feature pass. Builds on Phase 6 scaffolding.
**Dependencies:** Phase 6 complete (current `master`, 136 backend tests passing). PostgreSQL smoke test should be complete before dispatch — if it surfaced bugs, those are fixed first.
**Goal:** Add ranked-choice voting (Instant Runoff / IRV) and Single Transferable Vote (STV) on top of the validated multi-option scaffolding from Phase 6. Binary and approval voting remain unchanged.

---

## Context

Phase 6 shipped the multi-option scaffolding (data model, delegation engine branching, proposal-type-aware frontend, org config) with approval voting as the first method. The scaffolding has been validated through 136 backend tests, 14/15 Suite J browser tests, and (assuming the smoke-test pass completed cleanly) PostgreSQL deployment. Phase 7 adds ranked ballots on top of that foundation.

The hard parts of multi-option voting — ballot storage, delegation resolution branching, method-aware tabulation, options editor, org-level enablement — already work. Phase 7 reuses all of that. The new work is concentrated in three areas:

1. Ranked-ballot storage and validation (small)
2. RCV/IRV and STV tabulation via `pyrankvote` (medium — library handles the algorithms but the integration plus per-round breakdown extraction is real work)
3. Drag-to-rank ballot UI and round-by-round results display (medium-large)

**Explicitly out of scope:** Network visualization redesign for multi-option proposals. The current `VoteFlowGraph` is hardcoded to binary yes/no clustering and renders nonsense for approval and ranked-choice. This is a known gap, captured as Phase 7B in the roadmap. For Phase 7, the network graph continues to render incorrectly for non-binary proposals; this is acceptable because the platform is internal-test-only at this stage and Phase 7B will address it cleanly with proper design attention. The Sankey-style round-by-round elimination *flow* visualization is also Phase 7B work.

For Phase 7, the round-by-round elimination data is displayed as a clear text/table breakdown ("Round 1: Option D eliminated, votes transferred — Option A: 5→7, Option B: 4→4, Option C: 3→3"). Functional, not pretty. Phase 7B will turn this into a proper Sankey.

---

## Design Decisions Made Before Dispatch

### Decision 1: `pyrankvote` for tabulation

Use `pyrankvote` (or whichever well-maintained Python ranked-voting library is current at dispatch time — confirm during initial research) for IRV and STV tabulation. Do not implement these algorithms from scratch. RCV/STV have well-known edge cases (tie-breaking during elimination, batch elimination, Meek vs. Scottish STV variants) that have caused real-world controversies; using a library that has been audited and battle-tested is the right call.

The library's tie-breaking behavior should be documented in code comments and in the help page so users understand what method is being used (likely random with a configurable seed, but confirm during integration). For Phase 7, accept the library's defaults. If a future pilot org needs a specific tie-breaking method, that's its own work.

### Decision 2: Ballot inheritance for delegation

Same model as binary and approval: delegators inherit their delegate's full ballot. For RCV/STV, that means inheriting the complete ranking. Partial ballots inherit as-is (a delegate ranking 2 of 4 options is making a deliberate choice — they didn't rank C and D because they don't want to support them). Chain behavior (`accept_sub` / `revert_direct` / `abstain`) only fires when the delegate has no ballot at all.

A ballot ranking zero options (empty ranking `[]`) is technically possible. Treat the same way as approval's empty-approvals case: it's a valid abstention, but submitting one requires a ConfirmDialog confirmation per the Phase 6 pattern. Wording: "You haven't ranked any options. Submitting now counts as an abstention — you're saying you don't support any of them. This is different from not voting at all. Continue?"

### Decision 3: Strict-precedence delegation only

Same restriction as approval (Phase 6). Other delegation strategies (`majority_of_delegates`, `weighted_majority`) fall back to strict-precedence for ranked-choice proposals with the same UI note used for approval: "This proposal uses ranked-choice voting, which currently supports only strict-precedence delegation. Your delegate was selected based on your highest-priority matching topic."

Aggregating different rankings across delegates is genuine research territory (Kemeny-Young, Borda variants). Not in scope.

### Decision 4: STV uses `num_winners` field

The `num_winners` column on `Proposal` was added in Phase 6 as scaffolding for this. Phase 7 actually uses it. Validation:

- For `voting_method="ranked_choice"`: `num_winners` must be ≥ 1 and ≤ number of options. Default 1 (which makes the proposal IRV — single winner).
- For `voting_method="binary"` or `voting_method="approval"`: `num_winners` must be 1 (already enforced in Phase 6).
- The proposal creation form exposes `num_winners` only when ranked-choice is selected.
- The tabulation logic dispatches: `num_winners == 1` → IRV; `num_winners > 1` → STV.

### Decision 5: Tie-breaking for IRV/STV uses `pyrankvote` defaults; final-round multi-winner ties surface to admin

Within the elimination algorithm itself, `pyrankvote` handles intermediate tie-breaking (when multiple options are tied for last place during elimination, or when multiple options simultaneously cross the threshold). Use the library's defaults; don't override.

When the elimination process ends with a final-round tie among the top `num_winners` options (e.g., for IRV with `num_winners=1`, both remaining options have the same vote count), surface this to the admin using the same tie-resolution flow built in Phase 6 (`POST /api/orgs/{slug}/proposals/{id}/resolve-tie`). The endpoint already exists; just extend the `tied=True` detection logic in tabulation to cover IRV/STV final-round ties.

This keeps tie handling consistent across approval and RCV — admin resolves with audit trail.

---

## Scope

### Backend: Data Model

**Migration:** Single Alembic migration. The `Vote.ballot` JSON column already exists (Phase 6); no schema change needed. The `Proposal.voting_method` enum already includes `ranked_choice`; no migration there either. The migration may be empty if Phase 6 fully prepared the schema — verify and either skip the migration or add any small adjustments needed.

**Ballot payload extension:** `Vote.ballot` for ranked-choice proposals stores `{"ranking": [option_id_1, option_id_2, ...]}` where order matters. First in the list is the voter's first preference. Voters can rank some, all, or none of the options.

**No new tables.** `ProposalOption` from Phase 6 is reused.

### Backend: Validation

**Proposal creation (`POST /api/orgs/{org_slug}/proposals`):**

- Remove the existing rejection of `voting_method="ranked_choice"` (Phase 6 returned 400 with "planned for future release"). Now accept it.
- For ranked-choice proposals:
  - `options` must contain between 2 and 20 entries (same as approval).
  - `num_winners` must be ≥ 1 and ≤ `len(options)`. Default 1.
  - Org's `allowed_voting_methods` must include `"ranked_choice"`, else reject with 403.
- Default `allowed_voting_methods` for new orgs: `["binary", "approval"]`. Ranked-choice is opt-in per org. Existing orgs do **not** automatically get ranked-choice enabled — they need to enable it in org settings.

**Proposal editing while in draft:** Same rules as approval. Options editable in draft, locked once voting begins. `voting_method` and `num_winners` immutable after creation.

### Backend: Vote Casting

`POST /api/proposals/{proposal_id}/vote` for ranked-choice proposals:

- Accept `{"ranking": [option_id, ...]}` in the request body.
- Validate:
  - Each option_id belongs to this proposal.
  - No duplicates in the ranking array.
  - Empty array is allowed (counts as abstain after frontend confirms).
  - Length ≤ number of proposal options (a ranking longer than the option count is malformed).
- Store in `Vote.ballot`; `vote_value` stays null.
- Same delegation chain metadata handling as binary and approval.

### Backend: Delegation Engine Extension

The Phase 6 `Ballot` dataclass currently has `vote_value` (binary) and `approvals` (approval). Add a third field:

```python
@dataclass
class Ballot:
    vote_value: Optional[str] = None       # binary
    approvals: Optional[list[str]] = None  # approval
    ranking: Optional[list[str]] = None    # ranked_choice — order matters

    @property
    def voting_method(self) -> str:
        if self.vote_value is not None:
            return "binary"
        if self.approvals is not None:
            return "approval"
        if self.ranking is not None:
            return "ranked_choice"
        return "unknown"
```

**`_get_direct_ballot()` extension:** Add a third branch in `DelegationService._build_context()` to read ranked ballots:

```python
if voting_method == "ranked_choice":
    ballot_data = row.ballot or {}
    ranking = ballot_data.get("ranking", [])
    direct_ballots[row.user_id] = Ballot(ranking=ranking)
```

**`resolve_vote_pure()`:** Already returns `BallotResult` containing the full `Ballot` — no logic change needed. The function is method-agnostic, which is the payoff for the Phase 6 scaffolding design.

**`compute_tally_pure()` dispatch:** Add a third branch in `_compute_*_tally_pure` for ranked-choice. New function `_compute_rcv_tally_pure()` returns a new dataclass:

```python
@dataclass
class RCVTally:
    rounds: list[RCVRound]                   # ordered: round 0 = first preferences
    winners: list[str]                       # option_ids of final winner(s); len > 1 = unresolved tie
    total_ballots_cast: int
    total_abstain: int                        # empty rankings
    not_cast: int
    total_eligible: int
    tied: bool                                # final-round tie surfaces to admin
    method: str                               # "irv" or "stv"
    num_winners: int

    def quorum_met(self, threshold: float) -> bool:
        if self.total_eligible == 0:
            return False
        return self.total_ballots_cast / self.total_eligible >= threshold


@dataclass
class RCVRound:
    round_number: int
    option_counts: dict[str, float]           # option_id → vote count (float for STV fractional transfers)
    eliminated: Optional[str]                 # option_id eliminated this round (None for final round)
    elected: list[str]                        # option_ids meeting threshold this round (mostly STV; usually empty for IRV)
    transferred_from: Optional[str]           # which option's votes transferred this round
    transfer_breakdown: dict[str, float]      # option_id → votes received from transfer
```

**Service layer dispatch:** `compute_tally()` returns the appropriate tally type based on `proposal.voting_method`. Routes that consume the tally need to handle all three return types.

### Backend: `pyrankvote` Integration

Add `pyrankvote` (or current equivalent) to `requirements.txt`. Confirm at install time: as of last roadmap update, `pyrankvote` was the recommended choice — if a better-maintained library has emerged, use that instead and document the choice.

Wrap the library's tabulation in a service function that:

1. Builds `Candidate` and `Ballot` objects from the proposal's options and resolved rankings (after delegation resolution).
2. Calls `pyrankvote.instant_runoff_voting()` for `num_winners=1` or `pyrankvote.single_transferable_vote()` for `num_winners > 1`.
3. Extracts the per-round breakdown from the library's result object into the `RCVRound` structure above.
4. Determines winners and tie status.

The library's result object exposes round-by-round data; the wrapper translates that to our `RCVTally` shape so frontend doesn't need to know about `pyrankvote`.

### Backend: Results Endpoint

`GET /api/proposals/{proposal_id}/results` already dispatches on voting method (Phase 6). Add a third branch for ranked-choice that returns the `RCVTally` payload along with option labels (for display) and the resolution status.

### Backend: Tie Resolution Endpoint

The Phase 6 `POST /api/orgs/{org_slug}/proposals/{proposal_id}/resolve-tie` endpoint extends naturally to RCV. Validation changes:

- Allow it for `voting_method="ranked_choice"` in addition to `"approval"`.
- When resolving an RCV tie, the admin picks one of the tied final-round winners (not all options — only the ones tied at elimination's final step).
- Audit event is the same `proposal.tie_resolved`.

### Frontend: Proposal Creation Form

`frontend/src/pages/admin/ProposalManagement.jsx`:

- Voting method selector: enable Ranked Choice (currently disabled with "Coming soon"). Remove the disabled state.
- When Ranked Choice is selected:
  - Show the same options editor used for approval (already built — just dispatch on method).
  - Show a `num_winners` input (number, default 1, min 1, max = number of options entered). Show only when ranked-choice is selected. Below the input, contextual help: "1 winner = ranked-choice voting (IRV). More than 1 winner = single transferable vote (STV)."

### Frontend: Org Settings

`frontend/src/pages/admin/OrgSettings.jsx`:

- Voting Methods section: enable the Ranked Choice checkbox. Currently disabled with "Coming soon" — remove that and wire it to `org.settings.allowed_voting_methods`.

### Frontend: Ballot UI

`frontend/src/pages/ProposalDetail.jsx`:

- Add a third dispatch branch for `voting_method="ranked_choice"`.
- New `RankedBallot` component:
  - Drag-to-rank UI for the proposal's options. Reuse the DnD library and pattern from topic precedence reordering (`@hello-pangea/dnd`).
  - Voters can rank some options and leave others unranked. Unranked options sit in a separate "Not ranked" zone.
  - Each ranked option displays its position number (1st, 2nd, 3rd) prominently.
  - "Submit Ballot" button at bottom.
  - On submit:
    - If at least one option ranked: submit directly.
    - If zero options ranked: fire `ConfirmDialog` per Decision 2.
  - Post-submission summary view: "Your ranking: 1. Option B  2. Option D  3. Option A" with a "Change ballot" button if proposal still in voting.

### Frontend: Delegated Ballot Display

When the current user's vote is delegated on a ranked-choice proposal:

- "Your vote: via [delegate name]"
- "[Delegate]'s ranking: 1. Option B  2. Option D  3. Option A"
- Or "[Delegate] abstained (no options ranked)" if applicable
- "[Delegate] has not voted yet" if no ballot, with chain behavior handling (same as binary/approval)
- "Override — vote directly" button

If the user's `delegation_strategy` is non-strict-precedence, show the same fallback note used for approval: "This proposal uses ranked-choice voting, which currently supports only strict-precedence delegation. Your delegate was selected based on your highest-priority matching topic."

### Frontend: Results Display

`ProposalDetail.jsx` results panel adds a third dispatch branch for ranked-choice:

- **Header:** Method label ("Ranked-Choice (IRV)" or "Single Transferable Vote (STV)") and `num_winners` if > 1.
- **Final result:** Winner(s) prominently displayed at top.
- **Round-by-round breakdown:** Text/table format. Each round shows:
  - Round number
  - Vote counts per option in that round
  - Which option(s) eliminated
  - Which option(s) elected (STV)
  - Where votes transferred (e.g., "Votes from Option D: 3 → Option A, 1 → Option B")
- **Tied final round:** Same banner pattern as approval. Admin sees "Resolve tie" button. Resolution flow identical to approval.
- **Resolved tie banner:** Same as approval.

This is the deliberately-functional-not-pretty version. Phase 7B will replace the round-by-round table with a Sankey visualization.

### Frontend: Public Delegate Profiles

`frontend/src/pages/UserProfile.jsx` voting record:

- Ranked-choice proposals: show compact summary. "[Proposal title] — ranked 3 of 5 options" (collapsed). Click to expand shows the ranking. Empty ranking shows "Abstained (no options ranked)."

### Frontend: Help Page

`frontend/src/pages/VotingMethodsHelp.jsx`:

- Replace the "Ranked-choice voting (coming soon)" placeholder with a real section.
- Cover: what RCV is, how IRV elimination works, what STV is and when to use it, how delegation works for ranked ballots, what happens with partial rankings, what "tied final round" means and how it's resolved.
- Add a brief "Which method should I pick?" decision guide at the top, e.g., "One winner from a slate of candidates, want majority preference? → IRV. Multiple winners from a slate, want proportional representation? → STV. Multiple options where any combination could be acceptable? → Approval. Simple yes/no? → Binary."

### Seed Data

Update `backend/seed_data.py`:

- Add at least one ranked-choice (IRV) proposal in voting status with 4-5 options and varied rankings from multiple users (some full rankings, some partial, at least one delegated ballot inheriting a ranking).
- Add at least one STV proposal in passed status with `num_winners=2` or 3 to exercise the multi-winner display.
- Optional: one ranked-choice proposal in passed status with a tied final round so the admin tie-resolution flow has something to exercise.
- Enable ranked-choice in the demo org's `allowed_voting_methods`.

---

## Testing

### Backend Unit Tests

**New file `tests/test_ranked_choice_voting.py`.** Cover the following scenarios as separate test functions:

**Data model / proposal creation:**
1. Create RCV proposal with 4 options, num_winners=1 — succeeds.
2. Create STV proposal with 5 options, num_winners=3 — succeeds.
3. Create RCV proposal with num_winners=0 — rejected.
4. Create RCV proposal with num_winners > options count — rejected.
5. Create RCV proposal in org without `ranked_choice` enabled — rejected with 403.
6. Org with ranked_choice in `allowed_voting_methods` can create RCV proposals — succeeds.
7. Existing demo org defaults: confirm `allowed_voting_methods` does NOT auto-include ranked_choice (must be opt-in).

**Vote casting:**
8. Cast ranked ballot with 3 of 4 options ranked — vote record has `ballot={"ranking": [...]}` in correct order.
9. Cast ranked ballot with empty ranking `[]` — accepted, stored.
10. Cast ranked ballot with duplicate option_ids in ranking — rejected.
11. Cast ranked ballot with option_id not in proposal — rejected.
12. Cast ranked ballot longer than option count — rejected.
13. Order of options in ranking is preserved (rank 1, rank 2, rank 3 stay in submission order).

**Delegation for ranked-choice:**
14. Delegator's vote resolves to delegate's full ranking (identical, in order).
15. Delegator inherits delegate's empty ranking (abstain-equivalent).
16. Delegator inherits delegate's partial ranking (3 of 5) as-is — no chain behavior fired.
17. Delegate hasn't voted, chain_behavior=accept_sub, sub-delegate has ranking — delegator inherits sub-delegate's ranking.
18. Delegate hasn't voted, chain_behavior=revert_direct — delegator's resolved vote is "not_cast."
19. Delegate hasn't voted, chain_behavior=abstain — delegator's resolved ballot is empty ranking.
20. User with `delegation_strategy="majority_of_delegates"` on RCV proposal — fallback to strict-precedence.

**Tabulation (IRV, num_winners=1):**
21. IRV with clear majority in round 1 — single round, that option wins.
22. IRV requiring 2 rounds — last-place option eliminated, votes transfer to remaining options' next preferences, winner emerges.
23. IRV requiring 3+ rounds — multiple eliminations correctly produce final winner.
24. IRV where a voter's ranked options are all eliminated before majority — voter's ballot exhausted, doesn't count in subsequent rounds.
25. IRV with all empty rankings — winners empty, all ballots counted as abstain.
26. IRV final-round tie — `tied=True`, winners list has 2+ option_ids.

**Tabulation (STV, num_winners > 1):**
27. STV with `num_winners=2` and clear preferences for 2 options — those options win in early rounds via threshold.
28. STV with proportional minority support (30% prefer Option C) — Option C wins one of the seats.
29. STV with vote transfers from over-quota winners (surplus distribution) — fractional vote transfers handled correctly.
30. STV final-round tie — `tied=True` with admin tie-resolution available.

**Per-round data extraction:**
31. `RCVTally.rounds` correctly populated with round-by-round data from `pyrankvote`.
32. Each round shows correct option_counts, eliminated option, elected options (STV), transfer_breakdown.

**Tie resolution:**
33. Admin resolves an RCV final-round tie via the existing endpoint — works correctly, audit event logged.
34. Non-admin attempts RCV tie resolution — 403.
35. RCV tie resolution with option_id not among tied finalists — 400.

**Regression:**
36. All existing binary and approval voting tests continue to pass.

**Coverage target:** ~30+ new tests. Backend test count should go from 136 → approximately 165+.

### Browser Tests — New Suite K in `browser_testing_playbook.md`

Same format as Suite J. Execute with Claude-in-Chrome. Commit results.

**K1: Create RCV proposal (admin).** Login as admin. Org settings → enable ranked-choice in voting methods. Navigate to Admin > Proposals. Create proposal with voting method "Ranked Choice", 4 options, num_winners=1. Confirm proposal appears with ranked-choice indicator.

**K2: Create STV proposal (admin).** Same as K1 but num_winners=2. Confirm STV badge or indicator.

**K3: Edit options in draft.** Add a 5th option to the K1 proposal in draft. Confirm changes persist.

**K4: Advance to voting.** Advance K1 through deliberation to voting.

**K5: Cast ranked ballot.** Login as a member. Open K1 proposal. Drag to rank options 2, 4, 1 (in that order). Submit. Confirm vote panel shows "Your ranking: 1. Option 2  2. Option 4  3. Option 1" (or however the labels read).

**K6: Cast partial ranking.** As another member, rank only 2 of 4 options. Submit. Confirm partial ranking accepted.

**K7: Cast empty ranking triggers ConfirmDialog.** As a third member, don't rank anything. Click Submit. Confirm ConfirmDialog appears with abstention explanation. Cancel — ballot empty. Submit again, Confirm — ballot saved as abstain.

**K8: Delegated RCV ballot inheritance.** As a user delegating to a member who voted in K5, open the proposal. Confirm vote panel shows "Your vote: via [delegate]" and lists the delegate's ranking.

**K9: Override delegated ranking.** From K8, click "Override — vote directly". Drag a different ranking. Submit. Confirm override took effect.

**K10: Options locked after voting starts.** As admin, attempt to edit options on K1 (now in voting). Confirm blocked.

**K11: IRV results display.** As any user, view results section of K1 once voting closes (use admin to advance status). Confirm:
- Header shows method ("Ranked-Choice (IRV)") and winner.
- Round-by-round breakdown visible with vote counts and eliminations.
- Transfer breakdown shows where eliminated votes went.

**K12: STV results display.** Same as K11 but for K2 (STV with multiple winners). Confirm multi-winner display and round breakdown.

**K13: Tied final round.** Use seed data tied RCV proposal (or craft one). Confirm tie banner appears, admin sees "Resolve tie" button.

**K14: Admin resolves RCV tie.** Resolve the tie from K13. Confirm resolution banner shows resolved-by and selected winner.

**K15: Non-admin sees no resolve-tie button on RCV.** As regular member, confirm no resolve button visible on tied RCV proposal.

**K16: Ranked-choice disabled in org settings.** As admin of an org without ranked-choice enabled, confirm voting method selector doesn't offer ranked-choice (or rejects with "not enabled" message).

**K17: Binary and approval voting unchanged.** Spot-check binary and approval flows still work.

**K18: Regression.** Re-run Suites H, I, J. All previously passing tests must still pass.

### PostgreSQL Smoke Test

Same pattern as Phase 6 completion pass. After Suite K passes against SQLite, bring up the docker-compose PostgreSQL stack and run through:

1. Seed data
2. Create RCV proposal with 4 options
3. Cast multiple ranked ballots (full ranking, partial ranking, empty ranking)
4. Have a delegator inherit a ranking via delegation
5. Close voting, verify tally computes without errors
6. Resolve a tie if one occurs (or craft a separate STV proposal that ties)

Any 500 is in scope for this pass — diagnose from logs, fix, add regression test, re-run. Most likely failure modes: JSON serialization of the ranking array (PostgreSQL JSONB array handling), datetime issues if any new timestamp fields were added.

---

## Definition of Done

- All backend scope items implemented. Single Alembic migration (or none if Phase 6 fully prepared the schema).
- All frontend scope items implemented. Every RCV/STV flow works end-to-end in the browser.
- Backend tests: at least ~30 new tests added. Target 165+ passing total.
- Suite K added to `browser_testing_playbook.md` and all 18 tests pass.
- Seed data updated to include at least one IRV proposal in voting, one STV proposal in passed, ideally one tied IRV proposal.
- PostgreSQL smoke test executed and results documented in `PROGRESS.md` (pass clean, or bugs-found-and-fixed).
- `PROGRESS.md` updated with Phase 7 section: what was built, design decisions referenced, backend test count, Suite K results, PostgreSQL result.
- `future_improvements_roadmap.md` updated: Phase 7 marked complete in the sequencing section.
- No regressions in existing binary, approval, delegation, or admin workflows.
- The non-binary network graph continues to render incorrectly for approval and ranked-choice proposals. **This is acceptable** — Phase 7B addresses it. Do not attempt to fix it in this pass.

---

## Out of Scope

Deferred to Phase 7B:
- Network graph redesign for multi-option proposals
- Round-by-round elimination Sankey visualization
- Updated tally summary replacing yes/no/abstain counts in the network graph view

Deferred to Phase 8:
- Sustained-majority interaction with RCV/STV

Deferred post-sequence:
- Non-strict-precedence delegation strategies for multi-option (Kemeny-Young, proportional approval)
- Condorcet methods, STAR, score voting
- User-configurable IRV tie-breaking (uses library defaults for now)
- Animation of vote transfers in the round-by-round display

If the dev team discovers adjacent issues during execution, log them as new technical debt in `PROGRESS.md` rather than expanding this spec.

---

## Note on Library Choice

`pyrankvote` is the current recommendation but the dev team should briefly verify it's still actively maintained at dispatch time. Alternative candidates (in case `pyrankvote` is stale):

- `python-rcv` — simpler, may not handle STV edge cases well
- `ranked-choice-voting` — newer, less battle-tested
- Custom implementation using OpenSTV algorithms — too much work, prone to subtle bugs

If `pyrankvote` shows commit activity within the last 12 months and has no obvious open critical bugs, use it. If it's stale (no commits in 18+ months) or has open correctness issues, evaluate alternatives and flag the choice back to planning before proceeding. Don't silently substitute without surfacing.
