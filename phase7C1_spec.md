# Phase 7C.1 — Visualization Polish + Demo Data Refresh

**Type:** Polish/cleanup pass with three workstreams. Frontend, small backend privacy fix, and seed-data refactor.
**Dependencies:** Phase 7C complete (current `master`, 200 backend tests, Sankey live in production).
**Goal:** Address four issues from Z's review of the live Phase 7C demo, fix a backend privacy-boundary conflation that's hiding ballot content from views where only identity should be hidden, and do a meaningful refresh of demo data so the visualizations actually showcase the platform's value to EA visitors.

---

## Context

After Phase 7C shipped, Z reviewed the live site and surfaced four findings:

1. **Sankey lacks pre-elimination and post-elimination context columns.** The current rendering jumps straight into "Round 1 with Urban Workshop already eliminated." Viewers can't see the initial first-choice tally or the final winner state clearly.
2. **Anonymous voters don't appear meaningfully on the vote network graph.** Investigation: this is actually a backend bug, not just a visual treatment issue. The vote-graph endpoint redacts both identity AND ballot content for anonymous voters, but those are two different privacy boundaries. Identity should be hidden ("you can't see who voted"); ballot content should remain visible ("but you can see how the population voted"). The demo's value proposition includes seeing aggregate voting patterns, which the current code defeats.
3. **Steering Committee STV proposal not on prod.** Confirmed: this is the deferred "additive idempotent seed" tech debt — `seed_if_empty.py` only runs on empty databases.
4. **Delegator hover tooltips show "Abstained" without the via-delegation qualifier**, making it look like the delegator personally chose abstain when they actually inherited an abstain ballot.

Plus the demo data is thin (5-15 voters per proposal) and several voters have placeholder names like "Voter 01" through "Voter 13" which makes the admin Members page show meaningless rows.

The fix is one combined pass that addresses all of these. Bundling makes sense because the seed refactor enables the visualization fixes to actually be visible (more anonymous voters means the new privacy boundary is exercised; more voters period means the Sankey and option-attractor layouts have meaningful patterns to render).

---

## Design Decisions Locked In Before Dispatch

### Decision 1: Privacy boundary — identity hidden, ballot content visible

The current backend logic in `routes/proposals.py` (`get_vote_graph`) gates ballot data on `can_see_identity`:

```python
ballot_obj: Optional[schemas.VoteFlowBallot] = None
if can_see_identity and result is not None and result.ballot is not None:
    # ... populate ballot_obj
```

This conflates two distinct privacy boundaries:

- **Identity privacy:** can the viewer see *who* this voter is? **Yes** for: self, public delegates, users the viewer follows, users who privately delegate to the viewer. **No** for everyone else.
- **Ballot content:** can the viewer see *what each ballot contains*? **Yes** for everyone — ballot content is already aggregated into the per-option counts shown to all users.

The fix: separate these. An anonymous voter still gets their `ballot` field populated in the API response (so the frontend can compute attractor pulls and render ballot arrows), but their `label` stays empty and other identity-revealing fields stay redacted.

This change makes the privacy story crisper: "We hide who voted what, not what was voted." The current implementation hides both, which is stricter than the privacy claim and worse for the demo's informational value.

**Specific code change:** in `routes/proposals.py`, the `ballot_obj` construction should drop the `can_see_identity` gate. Ballot data is populated for every voter who has a ballot, regardless of identity visibility. Only identity fields (`label`) are gated.

**Privacy regression test (backend):** new test verifying that for an anonymous voter (viewer doesn't follow them, they're not a public delegate), the API response includes the ballot (`approvals` or `ranking` array populated) but `label` is empty and the node can't be back-referenced to the user's identity through any field.

### Decision 2: Sankey gets explicit "Initial" and "Final" columns

Add two columns to the Sankey:

- **Initial column (leftmost):** shows first-choice counts for every option before any eliminations. Source data: `RCVTally.rounds[0].option_counts` (already returned).
- **Final column (rightmost):** highlights winner(s), de-emphasizes already-eliminated options. For STV with `num_winners > 1`, all elected options highlighted.

Middle columns continue to show round-by-round eliminations as currently.

For single-round IRV (winner takes majority outright): render Initial + Final only, no middle columns.

For STV: middle columns continue to show eliminations and elected-option transfers per round; Final column highlights all winners.

### Decision 3: Anonymous voters render with arrows and distinct treatment

Building on Decision 1 (backend now returns ballot data for anonymous voters):

- **Anonymous voters get arrows to options just like visible voters do.** Approval: full-opacity arrow to each approved option. RCV: full-opacity arrow to first choice, ~30% opacity to second, none beyond. The arrows render the same way as for visible voters; they just aren't tied to a named voter.
- **Distinct visual treatment for the voter node itself:** dashed border instead of solid, slightly more saturated gray fill than abstainers, larger size than the current near-invisible rendering.
- **No name label on the node.** Anonymous voters don't show a name or initials.
- **Hover tooltip explains the privacy state:** "An anonymous voter — only public delegates and users you follow show their names. Their ballot is included in the visualization."
- **Cluster label optional:** if there are 5+ anonymous voters in a connected region, optionally render a small floating label like "5 voters not visible to you." Defer this if it adds visual noise; the per-node treatment plus arrows already conveys the right information.

This combination — arrows visible, identity hidden — is what makes the visualization show "how the group is voting" while preserving the privacy boundary on individual identity. It also makes the seed expansion (Decision 5) genuinely valuable: more anonymous voters means more visible aggregate ballot patterns.

### Decision 4: Hover tooltip qualifies inherited abstain votes

In `OptionAttractorVoteFlowGraph.jsx`, hover tooltip for delegators who inherited an abstain ballot currently renders "Abstained (no options selected)" / "Abstained (no options ranked)." This matches direct abstainers, causing the confusion Z flagged.

Update:
- **Direct abstain:** "Abstained (no options selected)" — unchanged.
- **Inherited abstain:** "Abstained (via delegation from [Delegate Name])." If the delegate's identity isn't visible to the viewer (delegate is anonymous), fall back to "Abstained (via delegation)" without naming.

Logic: the node has `vote_source: "direct" | "delegation"` and (for delegated votes) a delegate reference. Use those to dispatch the tooltip text.

Apply the same fix to `BinaryVoteFlowGraph` if it has the same issue (verify during implementation).

### Decision 5: Seed data refresh — substantial expansion

Replace the 13 placeholder "Voter NN" users with 25-30 realistically-named seed users with diverse first/last name combinations. Keep existing named demo personas (alice, dr_chen, carol, etc.) unchanged — those are referenced in tests, the persona-picker, and other tooling.

Each seeded proposal gets meaningful voter coverage:

- **Healthcare, Carbon Tax, Privacy Rights, Universal Healthcare:** 15-20 voters each with realistic delegation patterns (healthcare delegates, economy delegates, mixed precedence, environment overlap).
- **Office Renovation (approval), Community Garden (approval):** 12-15 voters each with overlapping approvals showing visual clustering.
- **Annual Team Offsite (RCV), Steering Committee (STV), Coffee Vendor (RCV):** 15-20 voters each with varied rankings producing meaningful Sankey patterns.

The expanded voter base needs follow-relationship distribution such that alice (the default demo login) sees roughly half the voters as anonymous on each proposal. This makes Decision 1's privacy boundary visible in the live demo — visitors as alice see some named voters and some anonymous voters, both contributing to the aggregate visualization.

**Voter naming guidance:** realistically diverse first/last name pairs. No single-locale skew, no profession skew, no demographic skew. The existing named personas are American-flavored; the expansion should mix in names from a broader range without being forced. Aim for the naming variety a real civic organization might actually have.

### Decision 6: Additive idempotent seed mechanism

The structural fix to the deferred "additive seed" tech debt. Refactor `seed_data.py` so every insertion is idempotent — checks for existing rows before creating, never overwrites existing data.

The existing `_get_or_create_*` helpers handle users, topics, and proposals correctly. The remaining issue is vote-casting and delegation-creation: these currently insert without checking, so re-running the seed could either duplicate-key error or silently overwrite real visitor data.

The fix: every vote/delegation/follow insertion checks for prior existence. Specifically:

- `_cast_vote`, `_cast_approval_vote`, `_cast_ranked_vote`: check if a `Vote` row exists for `(user_id, proposal_id)`. If exists, **leave it alone** — don't update, don't replace. The seed should never touch existing vote data.
- `_set_delegation`: check if a `Delegation` row exists for `(delegator_id, topic_id)`. If exists, leave it alone.
- `_create_follow_relationship`, `_create_follow_request`: same pattern, check before insert.
- `_register_delegate`: check if a `DelegateProfile` exists for `(user_id, topic_id)`. Leave alone if yes.
- `_set_precedence`: check if a `TopicPrecedence` row exists for `(user_id, topic_id)`. Leave alone if yes.

After the refactor, the entire `_seed_demo` function is safe to re-run on any database state. New seed content (new proposals, new voters, new patterns added in future phases) gets added; existing data is preserved.

**Critical constraint:** the seed must never overwrite a real visitor's actual vote or delegation. If someone cast a ballot on the Coffee Vendor proposal during the demo, re-running the seed must not replace that ballot with a seeded one. The check is purely "if a row exists, skip."

**`seed_if_empty.py`:** relax the "only on empty DB" guard. New behavior: always run additively. Document the change.

### Decision 7: Run additive seed on prod after deploy

After this pass merges and Railway auto-deploys, manually trigger the additive seed via `docker exec` per the procedure documented in `DEPLOYMENT.md`. Expected outcome: prod gains the Steering Committee STV, the realistically-named voters, and expanded patterns. Existing visitor data preserved.

---

## Scope

### Backend — Privacy boundary fix

**`backend/routes/proposals.py` — `get_vote_graph`:**

In the node-construction loop, decouple ballot population from identity visibility:

```python
# BEFORE (current):
ballot_obj = None
if can_see_identity and result is not None and result.ballot is not None:
    # ... populate ballot_obj

# AFTER:
ballot_obj = None
if result is not None and result.ballot is not None:
    # ... populate ballot_obj (regardless of can_see_identity)
```

The `can_see_identity` gate stays in place for the `label` field and any other identity-revealing fields. Only `ballot` is decoupled.

**Backend tests:**

New test in `tests/test_vote_graph_privacy.py` (or extend existing test file):
- Seed a multi-option proposal with several voters, where a non-admin viewer doesn't follow most of them.
- Call `GET /api/proposals/{id}/vote-graph` as the non-admin viewer.
- Assert that nodes for non-followed voters have empty `label` (privacy preserved on identity).
- Assert that those same nodes have populated `ballot` field with the correct approvals/ranking.
- Assert that no other field reveals the voter's identity.

Target: 2-3 new backend tests for this fix specifically.

### Backend — Seed refactor

**`backend/seed_data.py`:**

- Replace the placeholder voter list with 25-30 realistically-named voters.
- Expand vote casting and delegation relationships per Decision 5.
- Add follow relationships such that alice sees roughly half the voters as anonymous.
- Make every vote/delegation/follow insertion idempotent — check for existence, never overwrite.
- The `_seed_demo` function safe to re-run on any database state.

**`backend/seed_if_empty.py`:**

- Relax the "only on empty DB" guard. New behavior: always run additively.

**Backend tests:**

New test file `backend/tests/test_seed_idempotency.py`:
- Run `_seed_demo` once; record row counts (users, votes, delegations, follow_relationships, delegate_profiles, topic_precedences).
- Run `_seed_demo` again. Assert row counts unchanged.
- Cast a fake user vote on a proposal between runs. Assert the second seed run does not overwrite it.
- Set a fake user delegation between runs. Assert the second seed run does not overwrite it.

Target: 3-4 new backend tests.

Combined with the privacy boundary tests above and the existing 200, target ~205-207 backend tests total.

### Frontend — Sankey enhancements

**`RCVSankeyChart.jsx` (or wherever Phase 7C placed it):**

- Add Initial column showing first-choice counts per option. Source data: `RCVTally.rounds[0].option_counts`.
- Add Final column showing winner state per Decision 2.
- Middle columns (round-by-round eliminations) stay as currently implemented.
- For single-round IRV: render Initial + Final only.
- For STV: middle columns show round eliminations and transfers; Final highlights all `num_winners` elected options.
- Update column labels: "Initial" / "Round 1" / "Round 2" / ... / "Final."

### Frontend — Anonymous voter rendering

**`OptionAttractorVoteFlowGraph.jsx`:**

- Anonymous voters (those with empty `label`) get the new visual treatment from Decision 3: dashed border, distinct fill, larger size than current rendering.
- **Anonymous voters now render ballot arrows.** Because the backend now returns their ballot data (per Decision 1), the existing arrow-rendering loop should pick them up automatically — but verify the loop doesn't have a `label`-based gate that would skip them. The arrow-rendering condition should be `vote_source === 'direct' && ballot is populated` with no identity check.
- Hover tooltip on anonymous voter nodes shows the privacy explanation.
- Optional: cluster label "N voters not visible to you" when 5+ anonymous voters cluster spatially. Implement only if it doesn't add visual noise.

The same anonymous voter treatment applies to `BinaryVoteFlowGraph` if anonymous voters render there too — verify and extend.

### Frontend — Hover tooltip qualifier

**`OptionAttractorVoteFlowGraph.jsx`:**

- For delegator nodes (`vote_source === "delegation"`) with empty/abstain inherited ballot, append the via-delegation qualifier per Decision 4.
- Look up delegate name from graph data; fall back to anonymous form if delegate is also anonymous.
- Apply same fix to `BinaryVoteFlowGraph` if needed (verify).

### Documentation

- `DEPLOYMENT.md`: update the demo-data section to reflect the new additive seeding model. Document the new `docker exec` procedure for running the additive seed on prod.
- `PROGRESS.md`: Phase 7C.1 section covering all four visualization fixes plus the privacy boundary fix and the seed refresh.
- `SECURITY_REVIEW.md`: brief note on the privacy boundary clarification (identity vs. ballot content distinction).

---

## Testing

### Browser tests — extend Suite N (Sankey) and Suite M (vote graph)

**N10: Sankey Initial column renders.** Open a multi-round RCV proposal in `passed` status. Confirm leftmost column labeled "Initial" shows first-choice counts for every option.

**N11: Sankey Final column renders.** Same proposal. Confirm rightmost column labeled "Final" highlights the winner.

**N12: STV Final column shows all winners.** Open Steering Committee STV proposal. Confirm Final column highlights all `num_winners` elected options.

**N13: Single-round IRV renders Initial + Final only.** If a single-round IRV proposal exists in seed, confirm Sankey renders with two columns and no middle elimination columns.

**M25: Anonymous voters render with arrows.** Log in as alice. View an approval/RCV proposal where alice doesn't follow most voters. Confirm anonymous voters have ballot arrows pointing to options. Arrow rendering matches visible voters (full opacity for approvals/first choice, ~30% for RCV second choice).

**M26: Anonymous voters render with distinct visual treatment.** Same setup as M25. Confirm anonymous voter nodes have dashed borders and the new fill treatment, distinct from abstainers.

**M27: Anonymous voter hover tooltip.** Hover an anonymous voter. Confirm tooltip shows the privacy explanation ("only public delegates and users you follow...").

**M28: Inherited abstain tooltip qualifier.** Find a delegator who inherited an abstain ballot. Hover the delegator. Confirm tooltip shows "Abstained (via delegation from [Name])" or anonymous fallback.

**M29: Idempotent seed regression.** After re-running the seed on a populated database (via `docker exec`, in dev environment), open the demo proposals and confirm no votes are duplicated, no relationships doubled.

**M30: Privacy boundary preserved.** As alice, view a proposal where she doesn't follow some voters. Confirm those voters appear in the graph (with arrows and clustering effects from their ballots) but their names/usernames don't appear in any tooltip, detail panel, or other UI.

### Backend tests

- 2-3 tests for the privacy boundary fix (`test_vote_graph_privacy.py`)
- 3-4 tests for seed idempotency (`test_seed_idempotency.py`)

Target ~205-207 backend tests total.

### PostgreSQL smoke test

**Required this pass.** The seed refactor changes how rows are inserted; PostgreSQL constraint behavior on duplicate inserts can differ from SQLite. Specifically:

- Run the new seed against a fresh PostgreSQL docker-compose stack — verify it completes.
- Run it a second time against the same DB — verify no duplicate-key errors.
- Confirm row counts after the second run match counts after the first.
- Verify the privacy boundary fix works correctly with PostgreSQL's JSON column behavior.

This is exactly the SQLite-vs-PostgreSQL divergence territory we've been bitten by before. Don't skip the smoke test.

### Production deploy verification

After merge to `master` and Railway auto-deploys:

1. **Browser-driven verification on prod** — actual eyeball check, not bundle-string substitution.
2. Open an RCV proposal on prod. Confirm Sankey has Initial and Final columns.
3. Open as alice. Confirm anonymous voters render with arrows and distinct treatment.
4. Hover a delegator with inherited abstain. Confirm tooltip qualifier.
5. **Run the additive seed on prod via `docker exec`** per documented procedure. Confirm Steering Committee STV proposal now appears. Confirm existing visitor data wasn't disturbed.
6. Open admin Members page. Confirm realistic voter names render.
7. Re-test after seed run: confirm anonymous voter visualization is meaningfully visible (lots of anonymous nodes contributing to the cluster shape).

Capture screenshots demonstrating: Sankey Initial+Final, anonymous voters with arrows visible, hover tooltip qualifier, expanded admin Members page. Save to `test_results/phase7C1_screenshots/` and commit.

---

## Definition of Done

- Privacy boundary fix: backend now returns ballot data for anonymous voters; identity stays redacted.
- Backend tests for privacy boundary added.
- All four visualization fixes implemented and verified on the live site.
- Seed refactor complete: idempotent, safe to re-run, adds 25-30 realistically-named voters and expanded patterns.
- Backend tests for idempotency added.
- Total backend test count ~205-207.
- Suite N extension (N10-N13) and Suite M extension (M25-M30) all pass via Claude-in-Chrome.
- PostgreSQL smoke test passes — explicitly required this pass.
- Browser-driven prod sanity check performed (not bundle-string substitution).
- Additive seed run on prod, populating new content without disturbing existing data.
- Screenshots committed to `test_results/phase7C1_screenshots/`.
- `PROGRESS.md` updated with Phase 7C.1 section.
- `DEPLOYMENT.md` updated to reflect additive seeding.
- `SECURITY_REVIEW.md` updated with privacy boundary clarification.
- `future_improvements_roadmap.md`: mark Phase 7C.1 complete; note that "Additive Idempotent Seed Mechanism" deferred item is now resolved.

---

## Out of Scope

- **Phase 7.5 (Privacy and Access Hardening)** — separate pass, dispatched after this. Phase 7.5 is about admin access boundaries to audit logs and delegation graphs; this pass's privacy fix is about the public vote-graph endpoint's identity-vs-ballot boundary. They're complementary but distinct.
- **Sankey animation** between rounds — could be polish for a future pass.
- **Bundle size optimization** — flagged in Phase 7C tech debt, deferred.
- **STV fractional reconciliation visual treatment** — flagged in Phase 7C tech debt, deferred.
- **Mid-column Sankey labels** — flagged in Phase 7C tech debt, deferred.
- **Periodic demo data auto-reset** — separate deferred item; this pass makes the seed re-runnable but doesn't add automation.
- **Force tuning v2 for high-option-count proposals** — Phase 7B tech debt, deferred.

If the dev team discovers adjacent issues during execution, log them as new tech debt rather than expanding this spec.

---

## Notes for the Dev Team

- **Read `backend/routes/proposals.py` (`get_vote_graph`) carefully before changing the privacy boundary.** The `can_see_identity` flag is used in multiple places — for `label`, for edge visibility, etc. Only the ballot field decoupling is in scope. Don't change other privacy gates.

- **The privacy boundary clarification has positive demo implications.** With ballot data now visible for anonymous voters, the option-attractor visualization becomes much richer — visitors see the actual voting pattern of the whole population, not just the small subset of named voters. This is the whole point of the fix.

- **Seed file refactor is the most technically risky piece.** It's currently 700+ lines. The existing `_get_or_create_*` helpers handle users/topics/proposals; the remaining work is making vote/delegation/follow insertions idempotent. Don't restructure the file; just add existence checks before each insert. The pattern: query for existing row matching the unique key, return-or-skip if found, otherwise insert.

- **Names matter for the demo.** The voter list visitors see in the Members page is what makes the org feel real. Spend a few minutes on a name list that reads as a real civic organization — diverse first/last name combinations, no single-locale skew. Don't generate from a single source.

- **Anonymous voter visual treatment shouldn't make the graph noisier overall.** With ballot arrows now rendering for anonymous voters, the graph will have meaningfully more visual content. The dashed-border treatment plus distinct fill should make anonymous nodes readable without being obtrusive. If during implementation it looks too busy, drop the cluster label and rely on per-node treatment.

- **The hover tooltip change is one conditional.** Don't refactor the whole tooltip rendering. Add a branch for `vote_source === "delegation" && inherited_ballot_is_empty`.

- **Sankey Initial/Final columns add visual weight.** With 5+ options across many rounds (Steering Committee STV is the stress test), the diagram could compress badly. If it gets cramped, consider variable column widths or scrollable horizontal layout.

- **Browser-driven prod verification is required this pass.** Phase 7C declined this in favor of bundle-string evidence. For a pass that's all about what visitors see, the actual eyeball check is the deliverable. The QA teammate should pull up the live site as multiple personas (alice, frank, a fresh registered user) and confirm each fix renders.

- **`docker exec` for the prod additive seed run is the manual step Z performs after deploy.** Coordinate with Z — write clear instructions, confirm Z has the command before running.

- **PostgreSQL smoke test on idempotency:** the specific risk is constraint-based duplicate-insert behavior. SQLite is permissive in some cases where PostgreSQL raises. Run the seed against a fresh PG stack, run it again, confirm no errors.

- **Suggested team structure:** Lead in delegate mode. Backend dev for the privacy boundary fix + seed refactor + all backend tests + PostgreSQL smoke. Frontend dev for Sankey columns, anonymous voter rendering (now with arrows), hover tooltip qualifier. QA teammate for browser tests + prod verification + screenshots committed.

Report completion with: backend test count, Suite N + M extension results, PostgreSQL smoke result with explicit note on idempotency behavior, prod state after merge AND after additive seed run, screenshot paths, any new tech debt found.
