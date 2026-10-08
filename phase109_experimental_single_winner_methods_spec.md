# Phase 109 Experimental single winner voting methods

Status: COMPLETE. Approved by Z October 8, 2026; W0-W5 implemented sequentially, deployed and production-verified October 8, 2026. Application release 09b9da0; helper-only release 550a521. Final evidence: docs/phase109_closeout.md.

This pass plans STAR, Score, Ranked Pairs, and Majority Judgment together so they can share infrastructure, then requires implementation and verification of one method at a time. Every new method is disabled by default. Organizations retain their existing control over early voting and write-ins, including additions during voting.

Approved scope: STAR, Score, Ranked Pairs, and Majority Judgment: four new methods in total. Z approved this specification and authorized an implementation agent to execute it on October 8, 2026.

## Goal and dispatch

Give interested organizations four additional ways to choose one option without expanding the default ballot menu for other organizations. Keep the platform's delegation, eligibility, weighted voting, privacy, proposal lifecycle, and audit behavior coherent across methods.

Z has approved this specification and authorized implementation, testing, and deployment under its gates. The implementation dispatch is: `Read and execute phase109_experimental_single_winner_methods_spec.md`. No further confirmation is required for in-scope work. Report genuine blockers and obtain explicit review before destructive or out-of-scope infrastructure actions.

Read this document in full, then PROGRESS.md, applicable AGENTS.md, and the relevant code. The reviewed implementation baseline is origin/master `0096997`, through Phase 108. The original planning checkout is older and contains user changes: do not reset, clean, or overwrite it. Refresh origin/master before implementation and reconcile intervening changes.

## Branch and delivery sequence

Use `phase-109/experimental-single-winner-methods` in an isolated worktree based on current origin/master. Commit this approved spec before application changes. Use normal phase commits, a no-ff integration merge, and the repository's deployment verification convention. No shared-history rewriting or production data backfill is part of this pass.

Recommended team: lead/integrator, backend developer, frontend developer, and independent QA/reviewer. Backend and frontend may collaborate on the CURRENT method. Do not assign different counting methods to parallel implementation streams. A shared foundation is not an excuse to ship four unfinished methods at once.

| Stage | Work | Gate before starting the following stage |
| --- | --- | --- |
| W0 | Shared method contracts, organization gating, ballot/result infrastructure, migration, fixtures | Legacy regression checks and contract review |
| W1 | STAR end to end | Counting fixtures, delegation/weight/privacy/lifecycle tests, local rendered ballot and results QA |
| W2 | Score end to end using W1 rating infrastructure | Score-specific fixtures plus W1 regression checks and local rendered QA |
| W3 | Ranked Pairs end to end | Pairwise/cycle/tie fixtures, tied-ranking accessibility, compatibility matrix |
| W4 | Majority Judgment end to end | Median/tie/large-weight fixtures, grade-label and distribution QA, compatibility matrix |
| W5 | Whole-pass integration and deployment | Full matrix below, exact deployments, production sanity and closeout |

The default delivery is one release after the gates pass. An earlier method may be released separately only as a complete, tested slice; unfinished methods must remain unavailable to settings and API creation, not merely hidden in the frontend. Record any such release boundaries in this document and the closeout.

## Verification matrix

| Check | Required | Notes |
| --- | --- | --- |
| Independent hand-counted fixtures for each method | Yes, per method | Include the fixtures in this spec and additional degeneracies; do not compute expected values with the implementation under test |
| Independent reference comparisons | Yes | Pin reference version/rules; synthetic ballots only; specify permitted differences in ultimate tie ordering |
| Delegation and represented-member weights | Yes, per method | Direct override, explicit abstain, retraction, fallback, chains, topic relevance, cross-org/sub-org scope, zero and large weights |
| Ballot validation and authorization | Yes, per method | Strict types, duplicate IDs, foreign/deleted IDs, incompatible fields, disabled-method create/import bypass, malformed stored data |
| Write-ins and early voting | Yes, per method | Both permissions modes, late options on old direct/delegated ballots, re-vote, authorized removal, option-add/close race, edit-lock policy |
| Settings and serializer round trip | Yes | Both proposal create paths, draft edit, import/preview, direct seed path; organization and sub-org effective settings |
| Closing and Stable Result Required | Yes, per method | Manual, org-scoped, worker close; extension caps; no ballots, ties, quorum, rollback, retry; snapshot meaning |
| Final result persistence | Yes | Read after weight/delegation/membership/label changes; no recomputation that changes the recorded outcome |
| Privacy on every result surface | Yes | API, public/authenticated feed, delegate graph/profile, notifications, live update, history/export |
| Performance and numeric limits | Yes | See performance section; no per-share expansion or unbounded tie enumeration |
| Full backend suite | Yes, final integration | Per-method focused suites first; report environment skips and actual count delta |
| Frontend tests, changed-file lint, production build | Yes | Keyboard behavior, payload contracts, labels, disclosure, all four displays |
| SQLite migration cycle | Yes if migration added, expected | Subprocess upgrade/downgrade/upgrade |
| PostgreSQL migration smoke | Yes if migration added, expected | `python backend/scripts/pg_smoke.py --mode both --prior-revision <verified-prior-head>`; reviewed candidate is `f8a9b0c1d2e3`, recheck at dispatch |
| Browser QA | Yes | Desktop and about 380px, keyboard and focus, submit/change/retract, delegate, add write-in, close/results; follow available approved browser tooling and AGENTS.md |
| Production deployment and sanity | Yes | Exact backend commit deployment, frontend bundle, health/readiness/monitor, isolated test-org journeys |
| Spec, source, and diff review | Yes | No changed defaults for existing methods; no secret values or production voter data in fixtures |

Unavailable browser tooling is a reported blocker for the rendered gate, not permission to claim a source review proves the user journey. Do not mark the pass complete without required verification.

## Product decisions and scope

### Decisions from Z

1. Plan the methods together so shared work is visible to the implementation team.
2. Implement and test one system at a time.
3. New methods are organization-level opt-ins and off by default.
4. Preserve organization control of write-ins and early voting. Do not impose a new STAR-only ban on late additions.

### Approved baseline

- Four method IDs: `star`, `score`, `ranked_pairs`, `majority_judgment`.
- Ordinary organization/sub-organization proposals selecting exactly one option. Existing binary, approval, IRV/STV, and budget methods retain their behavior.
- Single-seat officeholder elections remain a separately scoped follow-up. These methods are conceptually suitable, but the current election close path also assigns roles and has different nomination, uncontested-election, and fallback rules. Reject new methods at election creation, scheduled election generation, and any election draft-edit path during this pass.
- No new methods for global proposals without an organization setting to authorize them.
- STAR and Score use the fixed 0-5 integer scale. Majority Judgment uses six ordered verbal grades. Ranked Pairs supports equal ranks and incomplete rankings.
- No arbitrary custom scales, organization-defined algorithms, proportional/multiwinner variants, automatic cross-method comparisons, or ballot conversion between methods in this pass.
- No absolute minimum rating for winning. Existing quorum plus a meaningful submitted preference rule below determines whether a result can be finalized. A rating does not inherit the binary yes/no pass threshold.

Z approved the baseline above, including the grade labels, exact tie variants, and separate officeholder release boundary. Escalate material deviations rather than silently substituting different counting rules.

## Existing integration points and hazards

Paths are relative to the repository root at the reviewed baseline.

| Surface | Existing behavior relevant to this pass |
| --- | --- |
| `backend/routes/organizations.py` | `DEFAULT_ORG_SETTINGS.allowed_voting_methods` references `ALL_SUPPORTED_VOTING_METHODS`. Adding IDs there currently opts fresh organizations in automatically. Separate the available list from the default-enabled list. |
| `frontend/src/pages/admin/SubOrgSettings.jsx` | Hard-coded method list and labels; audit effective inheritance and do not discard unrelated enabled methods when saving. |
| `backend/schemas.py`, `backend/models.py` | Method allowlists, create/edit contracts, response builders, JSON `Vote.ballot`, string `Proposal.voting_method`. |
| `backend/delegation_engine.py` | Unified Ballot, method dispatch, DB JSON decoding, whole-ballot multi-option relevance resolver, represented-member integer weights. Unknown methods currently fall through to binary counting. |
| `backend/routes/votes.py` | Method-specific validation, persistence, retraction, notification ballot formatting, response and tally construction. |
| `backend/routes/proposals.py`, `backend/routes/organizations.py` | Dual create/close paths, previews/imports, options, rationale/graph/results/trajectory serializers. |
| `backend/proposal_engagement_config.py` | Existing organization modes and proposal overrides for write-ins and pre-voting; these remain authoritative. |
| `backend/routes/proposals.py` write-in routes | Add gate currently recognizes only approval/RCV; removal cleans their JSON arrays. Extend both explicitly. |
| `backend/tie_resolution.py`, `backend/proposal_lifecycle.py` | Existing method-specific tie eligibility and close handling. `expand_winners` is incompatible with this pass. |
| `backend/sustained_majority*.py` | Snapshot and close branches explicitly recognize current tally types. Unknown types can create empty snapshots or enter binary pass/fail handling. |
| `backend/elections.py`, `backend/routes/elections.py` | Separate office assignment path; a legacy fallback can choose first-declared candidates after tally failure. Do not route new methods into it. |
| Frontend vote/results/create/import/settings/profile/help components | Audit all method labels, switches, charts, ballot summaries and payload adapters rather than only adding a new form control. |

No wholesale rewrite of old methods is required. Introduce a small shared method-capability registry where it removes duplicated allowlists, with explicit tests that it preserves existing defaults and behavior. A missing handler for a registered new method must fail loudly rather than tally as binary.

## Shared ballot and counting contract

### Inputs

Extend request and stored JSON contracts deliberately. Recommended payloads:

```json
{"scores": {"option-uuid-a": 5, "option-uuid-b": 3}}
{"grades": {"option-uuid-a": 5, "option-uuid-b": 2}}
{"rank_groups": [["option-uuid-a", "option-uuid-b"], ["option-uuid-c"]]}
{"abstain": true}
```

`scores` applies to STAR/Score; `grades` to Majority Judgment; `rank_groups` to Ranked Pairs. UUID strings above are illustrative placeholders. Within a rank group, order has no meaning. Earlier groups outrank later groups. Use explicit method context to distinguish STAR and Score; a score map alone cannot identify which counter applies.

Reject inappropriate combinations, including a new-method payload on a legacy method and `abstain: true` with preference fields. Reject booleans, strings and nonintegral values as grades/scores before coercion; values must be integers 0 through 5. Reject repeated IDs across rank groups, empty inner groups, and option IDs outside the current proposal. All structured fields must have bounded sizes. Keep current UUID, label, option-count, and write-in-cap validation; do not create an unbounded option path through imports.

An explicit abstention is stored and overrides delegation. Retracting it removes the direct ballot and allows ordinary delegation fallback. Empty maps/all-zero ratings and an empty outer rank list are submitted neutral ballots, not missing votes or automatically deleted ballots. Preserve explicit-vs-implicit values in storage when useful for explaining late additions; apply omitted-option defaults in counting, not by rewriting old votes.

### Omitted options and late additions

| Method | Meaning of an option not present on a submitted ballot |
| --- | --- |
| STAR and Score | 0 points |
| Majority Judgment | Lowest grade, Reject |
| Ranked Pairs | Tied below every explicitly ranked option and tied with all other unranked options |

These apply equally to options originally omitted and options added after casting. An explicit abstention remains an abstention after any option additions. It does not become a lowest-grade evaluation and must not dilute Majority Judgment distributions.

Explain defaults beside the ballot and in a short late-option notice when viewing an older ballot. Do not invent favorable scores, use a per-option respondent-only average, discard old ballots, reopen a closed vote, or require all voters to recast. Members may update their ballots while existing policy permits. An unchanged delegate ballot also uses these defaults for newly added options.

### Delegation and weights

Resolve one effective ballot for each eligible represented member using the existing engine. Carry it whole; do not average delegates, combine different score maps, or use a different delegate for each option. Preserve topic relevance, precedence, global fallback, chain policy, membership and verification gates.

Compute each member's contribution with that member's effective integer voting weight, not the terminal delegate's weight. Apply weight to score sums, score histograms, pairwise preferences, STAR runoff votes, and Majority Judgment grade frequencies. One-member-one-vote mode uses weight one throughout. Zero-weight members have zero effect on the decision. Retain separate headcount and voting-power reporting where the existing product does so.

### Participation and no-result behavior

Explicit abstentions count for quorum as current multi-option abstentions do, but are excluded from method preference aggregates and rating/grade averages or histograms. Neutral submitted ballots count for participation and contribute their actual zero/equal values. Unresolved delegation and no direct ballot are not participation.

Use the proposal's existing effective count mode and quorum policy consistently. Never compare a weighted numerator with an unweighted denominator. Zero eligible voting power cannot meet quorum by division-by-zero or vacuous truth.

Product rule, distinguished from the mathematical methods: return no winner if there are fewer than two remaining eligible options, zero positive-weight non-abstaining ballots, no score/grade above the bottom level anywhere (rated methods), or no strict pairwise preference anywhere (Ranked Pairs). Show the precise reason. All-bottom ballots do not produce a winner by lottery. Equal positive ratings can still produce a legitimate unresolved tie. If quorum is unmet, display a provisional tally if visibility permits, but do not finalize a passed decision.

## Counting rules

Freeze a versioned rule identifier on each new-method proposal before any ballot is accepted, including early voting. Configuration and method changes remain draft-only and must follow the existing destructive-change confirmation for any stored preliminary material. No automatic conversion of a Score ballot to STAR, or of ranks to grades, when editing a draft.

The following algorithm definitions are the approved v1 rules. A team must not substitute another variant under the same method ID.

### STAR

Rule ID `star_0_5_v1`. Total each option's weighted scores; advance the top two. In the runoff add each ballot's represented weight to the finalist it scored higher; equal scores go to neither and are reported separately. Higher runoff support wins. These are the standard two stages described by [STAR Voting](https://www.starvoting.org/star).

Use the score-tie procedure implemented by the pinned `starvote` reference: within the tied boundary pool, sum weighted strict preferences over the other tied options, select available finalist places, then use weighted five-star counts for a remaining boundary tie. Preserve any already-qualified finalist at each step. If still tied, use the shared final priority. For a runoff tie compare original total scores, then five-star counts, then final priority. Cross-check multiway boundary selection against the pinned reference rather than inventing a pairwise-elimination tournament. [Reference source](https://github.com/larryhastings/starvote)

Return all scores, finalists, both runoff totals, equal-preference weight, consulted tie stages, and winner. Do not rank all losing options by their score and imply that STAR established a complete preference ordering.

### Score

Rule ID `score_0_5_sum_v1`. Use the same score map as STAR. The highest weighted sum wins; equal maxima use shared final priority. No runoff or implicit five-star tiebreak is added. This is the total-score method described in the [STAR FAQ's comparison with Score](https://www.starvoting.org/faq).

Show total scores and an optional average with one common denominator: all positive-weight non-abstaining submitted ballots, including their omitted-zero contributions. A rarely rated write-in must not receive an inflated respondent-only average. Scores are not approval percentages.

### Ranked Pairs

Rule ID `ranked_pairs_margins_v1`. Convert rank groups plus unranked-last into weighted ordered-pair counts `P[a,b]`. Equal ranks contribute to neither direction. Form a directed victory only where `P[a,b] > P[b,a]`. Process victories in descending margin `P[a,b] - P[b,a]`, then descending winning support `P[a,b]`, then ascending shared candidate-priority tuple `(priority[a], priority[b])`. Lock an edge unless it would create a directed cycle. Select the unique zero-indegree candidate, or use shared final priority among multiple zero-indegree candidates. Include every current option as a graph node. This is a specifically defined margins variant of the [Ranked Pairs family](https://www.condorcet.vote/assets/DOCS/IndependenceofClones.pdf).

Return the pairwise matrix, ordered victories, locked/skipped edges with reasons, source candidates, winner, and whether priority ordering was consulted. Pairwise equalities create no victory edge. Do not resolve cycles by counting first choices, by Copeland wins, or by running IRV. Do not advertise this finite-tie convention as every possible Ranked Pairs variant or claim clone-independence in all tie cases.

The ballot must support tied ranks without requiring dragging: move up/down, assign rank group, and leave unranked with clear labels. Reuse existing ranked UI mechanics only where they preserve these semantics; do not change IRV/STV ballot semantics.

### Majority Judgment

Rule ID `majority_judgment_lower_median_v1`. Approved fixed scale, worst to best: `0 Reject`, `1 Poor`, `2 Acceptable`, `3 Good`, `4 Very good`, `5 Excellent`. Numeric codes are ordered identifiers, not points to add or average. The candidate with the highest majority grade leads. This distinction follows [Balinski and Laraki's grading framework](https://pdodds.w3.uvm.edu/research/papers/others/2007/balinski2007a.pdf).

Build a six-bin weighted histogram per option. For total non-abstaining weight W, take the grade at ascending position `ceil(W/2)` (one-based): the lower middle grade when W is even. Do not average the two central grades. Compare tied options by the classic repeated-median-removal rule: remove one unit at each tied candidate's current median, recompute, keep candidates with the highest median, and repeat until separated or identical distributions are exhausted. Identical distributions use shared final priority. This precisely specifies the rule; do not silently replace it with a simplified majority-gauge shortcut, Usual Judgment, or an average-grade tiebreak.

The literal repeated-removal algorithm is a small-test oracle only. Production must compare compact histograms with a proven equivalent algorithm that skips repeated runs and does not loop once per share. Test equivalence against the oracle exhaustively on small histograms, including even totals, and with randomized larger profiles.

Show the initial majority grade and grade distribution, plus the tie explanation when used. Removing grades for tie comparison does not mutate stored ballots or the displayed original distribution. No invented decimal grade or star average in the results.

## Shared final tie priority

Approved platform convention for these new methods only: a reproducible server-generated draw order. Generate one cryptographically random proposal seed before accepting the first ballot, persist it, and publish its SHA-256 commitment in the rules metadata. The client cannot choose or update it. Derive each candidate priority from SHA-256 of a versioned, unambiguously encoded tuple `(seed, proposal_id, option_id)`; lower digest sorts first, with canonical option ID as the collision fallback. Late write-ins obtain their priority through the same rule without reordering existing candidates relative to one another.

Keep the seed out of ordinary pre-close responses; reveal it with the finalized result so the disclosed priorities can be verified. Internal live tallies may use this same order and must flag any use of it. A live result that consulted this arbitrary priority is provisional and not stable for automatic early closing. This is a conservative rule, including equal-strength Ranked Pairs edge ordering; it may extend some votes whose winner would actually be invariant. It avoids exponential enumeration of all tie orders. Normal deadline and maximum-extension behavior still terminate the vote.

Persist every consulted tie stage and the final outcome. Repeated reads, worker retries, and deadline extensions must not redraw. Do not derive priority from deadline, latest vote timestamp, ballot iteration order, labels, mutable counts, or a user-supplied seed. Do not offer expand-winners or earliest-voter priority for these single-winner methods. Do not claim this protocol prevents all strategic use of public live tallies; it supplies reproducibility and removes routine retry/deadline redraws.

## Organization controls and proposal lifecycle

### Enablement and inheritance

Each new method gets an independent checkbox under an optional methods section in Organization Settings. Keep existing authorization for changing voting rules. All four are absent from default-enabled lists for fresh organizations and from fallbacks for old organizations; never backfill them into enabled settings. The settings panel may describe available methods, but proposal authors see only effective enabled choices.

Respect existing sub-org inheritance and explicit overrides. Do not treat any newly introduced method as globally enabled merely because the parent has no settings row. Saving an old client list must not inadvertently replace unrelated settings. Enforce availability in server-side create, draft method edit, both org/global endpoint paths, import validation/execution, and seed helpers; fixtures may explicitly opt a test organization in. Global/no-org proposals and officeholder elections reject these IDs in this release.

Turning a method off prevents new proposals and draft transitions into that method. Existing proposals already using it remain votable, editable within their existing rules, closable, and readable. A draft already using a disabled method may retain its method; do not strand it or silently switch it to binary. Explain this effect next to the settings toggle.

### Write-ins and preliminary ballots

Extend the existing write-in method allowlist to all four new methods. Preserve the canonical permission resolvers, proposal overrides, existing maximums, duplicate-label rules, moderation, and audit behavior. Preserve early voting and its visibility controls. A draft method switch cannot bypass option validation or retain incompatible ballots.

Adding an option must invalidate tally caches and capture a new snapshot when applicable. It is an event for Stable Result Required as described below, even if the current winner did not change. No mass email or forced revote is introduced. Existing notification behavior may be reused only within current preferences and privacy gates.

Extend authorized write-in removal to remove keys from scores/grades or membership in rank groups; remove empty groups, retain the submitted ballot and its override-delegation meaning, and reassign JSON so SQLAlchemy tracks changes. Preserve the existing removal permissions and lifecycle rules for legacy methods. For these new methods, reject option/ballot mutations after finalization; historical final-result labels and totals must remain intact. Serialize option additions/removals and ballot submission with closing so a ballot cannot be counted against a half-updated option set. Return a useful stale-option error if an option was removed before submission.

### Stable Result Required and closure

Use the same logical tally service for manual close, org close, scheduled worker close, and final results. No binary fallback and no election-role assignment hook for ordinary proposals.

For new methods, stable means: quorum is met; there is a meaningful result; one winner is identified without consulting the arbitrary priority; that winner is unchanged through the required observation window; and the option set has not changed in that window. Track an option-set version in snapshots. A late write-in invalidates prior stability evidence rather than pretending that all options have been observed for the full interval. Preserve existing extension-duration limits and maximum-extension closing policy. Do not restart an unlimited extension budget on option additions.

Method-specific ballot-based tiebreaks that produce one winner are legitimate results; only remaining arbitrary-priority dependence is treated as unstable. STAR tracks the runoff winner, not its score leader. A finalist change with the same winner need not restart stability unless another rule above is violated. Missing or incompatible snapshot data must not be interpreted as proof of stability. Keep legacy-method stability semantics unchanged.

At the actual permitted closing time, resolve any remaining tie with the committed priority, apply quorum and meaningful-result rules, and atomically persist status, final method result, audit, and existing notification intent. If validation/counting fails, roll back, keep the proposal unfinalized, and expose the failure through existing operational monitoring; never fabricate a winner or mark a software failure as voter rejection. Retried worker/manual closes must not emit duplicate notifications or repeat side effects.

## Persistence and result presentation

Keep raw direct ballots in `Vote.ballot` with strict version-aware decoding. Introduce nullable server-owned proposal JSON fields `voting_rules` and `final_method_result` (names may be adapted consistently during W0). Existing proposals stay null and use their legacy paths. `voting_rules` stores method/version/scale, omission policy, tie commitment and protected seed. Only an explicit public projection may reach a serializer; pre-close raw rules must never expose the seed. Draft cloning/import must generate fresh server rules and cannot accept client-owned seed or final result data.

`final_method_result` stores the immutable final option IDs/labels, aggregate participation and eligible weight at close, method aggregates, winner/no-result reason, tie trace and revealed seed, method version, count mode, option-set version and closing timestamp. No raw private ballot, delegation chain or identity goes in this public-safe aggregate object. Its distribution/matrix remains subject to the same result-visibility policy as any other aggregate results.

Final responses for new methods use the persisted result even if membership, delegation, weights, titles, or organization defaults later change. Separately permissioned voter/ballot history remains separate; do not claim aggregates alone are a full reconstruction of individual ballots. If a closed new-method proposal lacks its required final record, report an integrity error rather than silently recompute. No migration of historical legacy results is included.

Extend all response builders and exports explicitly. New nullable schema fields alone do not guarantee serialization. Add create/read/import/seed round-trip tests, and the organization serializer coverage test if a new FE-facing organization field is introduced.

Present each method in its own terms:

- STAR: scoring table, finalists, runoff vote totals, equal preference, winner and tie explanation.
- Score: total points, optional correctly denominated average, winner and tied top scores.
- Ranked Pairs: winner, readable head-to-head summary, expandable pairwise matrix and locking explanation. No first-choice chart presented as the deciding tally.
- Majority Judgment: majority grade and stacked distribution of verbal grades, with tie detail. No average-as-winner substitution.

Keep people/weight units explicit. A 4/5 rating is not 80% of voters' approval. Snapshot charts must carry method-specific units and preserve old snapshots. For STAR record both score totals and runoff state; for Majority Judgment store histograms/median grades; for Ranked Pairs record winner and aggregate pairwise summary as needed rather than persisting raw ballots every tick. Cap response sizes and retain existing trajectory downsampling.

Use numeric 0-5 buttons with accessible names for STAR/Score, fixed grade labels for Majority Judgment, and rank groups for Ranked Pairs. Include keyboard operation, focus/error association, mobile layout, visible selection, and an explicit abstain action. Show each method's exact ballot instruction and omitted-option meaning. Do not autosave a rating click as a cast vote; use the existing submit/change flow.

Public delegate pages, vote graphs/clusters, notifications and summaries must either support the actual new ballot or give an explicit method-appropriate summary. Do not show empty/binary data for a scored ballot. Reuse current access controls and disclosure settings; adding a rich grade distribution must not expose a private individual's ballot.

## Performance and security boundaries

Pure counters receive already-resolved weighted ballots; no database query per candidate pair and no network access. Reuse one resolved snapshot for score totals, histograms and pairwise work. Store weighted frequencies, not repeated copies of shares. Use integer arithmetic for outcomes; floating point is display-only. Preserve large exact aggregate values across the backend/JavaScript boundary using validated safe ranges or decimal-string transport, with tested consistency across all new result fields.

STAR/Score/grade accumulation is linear in ballots times options; pairwise accumulation is quadratic in options. Build the full pairwise matrix once when needed, not per displayed cell or tie iteration. Limit initial options to the existing maximum 20 and write-ins to the effective existing cap, currently up to 100. Explicitly cover 120-option cases instead of benchmarking only the creation cap.

Benchmark deterministic synthetic profiles at 1,000 voters x 20 options, 10,000 x 20, and 1,000 x 120; include ties, deep delegation chains and weights up to at least one billion. Report timings, query counts, peak memory and machine details. A 1,000-fold increase in weight magnitude must not produce 1,000-fold runtime/memory growth. Check concurrent vote/tally and background snapshot workloads against the repository's available latency/connection budgets. Optimize or reduce the new feature's advertised capacity explicitly before release if these paths overload the normal vote workflow.

No new external counting service, production ballot export, paid infrastructure, identity-provider change, or secret rotation. Reference implementations are validation aids, not authority to copy unreviewed dependencies into production. Record license and pinned commit/version for any borrowed implementation or fixture; use synthetic ballots only.

## Hand-counted acceptance fixtures

All unspecified options score zero, grade Reject, or rank jointly last. Use stable symbolic IDs in pure tests and real UUID/model rows in integration tests. The following fixtures supplement, not replace, method-specific edge-case coverage.

| Fixture | Ballots | Expected result |
| --- | --- | --- |
| STAR differs from Score | 3 x A=5 B=4 C=0; 2 x A=0 B=4 C=5 | Totals A=15 B=20 C=10. STAR finalists B/A, A wins runoff 3-2. Score elects B. |
| STAR runoff equality | A=5 B=4; A=0 B=4 | Runoff 1-1; B wins on original total 8 versus 5. |
| STAR equal finalist preference | A=5 B=5 plus ballots giving an unequal preference | Equal ballot increases both scores but neither runoff side; it appears in equal-preference weight. |
| Ranked Pairs cycle | 3 x A>B>C; 2 x B>C>A; 2 x C>A>B | A>B margin 3, B>C margin 3, C>A margin 1. Lock first two, skip cycle-closing C>A; A wins. |
| Ranked Pairs equal rank | One ballot [A,B]>C, weight 7 | A>B=0 and B>A=0; A>C=7 and B>C=7. No artificial preference between A and B. |
| Ranked Pairs equal-strength cycle | A>B>C; B>C>A; C>A>B; test priority A then B then C | With specified edge ordering lock A>B and B>C, skip C>A, elect A; record priority use and provisional stability status. |
| MJ differs from mean | 3 x A=Excellent B=Very good; 2 x A=Reject B=Very good | A majority grade Excellent, B Very good; A wins, although numeric averages would be 3 versus 4. |
| MJ even population | One candidate's grades 0,0,5,5 | Majority grade 0, not 2.5 or 5. |
| MJ median tie | A grades 2,2,5; B grades 0,2,2 | Initial medians both 2; remove one 2 each; lower medians become A=2, B=0; A leads. Original displayed grades remain intact. |
| Late write-in | Cast a ballot on A/B, then authorized addition C | Old ballots give C zero/Reject/unranked-last; no mutation to saved original expressions, no extra ballot, and option version changes. |
| Weight parity | A weight-7 effective ballot versus seven weight-1 identical effective ballots | Same method aggregates and winner for every method, including all tie stages; headcount differs explicitly. |
| No meaningful decision | All abstain; all zero/Reject; or no strict rank preference | Quorum accounting remains accurate; no fabricated winner; precise no-result reason. |

Also require zero ballots, exactly two options, all-positive equal ballots, multiway first/second place ties, equal MJ histograms, changed input iteration order, recreated tally reads, and round-trip use of real `Vote.ballot` JSON. With candidate-priority data permuted consistently, renaming input keys or labels must not change the outcome.

For method properties, test what each rule actually promises: a clear Condorcet winner must win Ranked Pairs; that property is not required of STAR, Score or Majority Judgment. Do not write tests that enforce one method's desired outcome onto another method.

## Follow-up boundaries

Single-seat officeholder support is NOT STARTED. A later spec should cover nomination closure/write-in candidacy rather than arbitrary labels, scheduled election method configuration, uncontested races, no-winner outcomes, quorum, term/role assignment and revocation side effects, and removal of first-declared-candidate error fallbacks for the new methods. It must not enable methods merely by broadening the election route allowlist.

Proportional or bloc variants, custom grade scales, ballot-method comparison experiments and new aggregate privacy thresholds are also outside this pass. The common contracts may accommodate them later without advertising support now.

## Operational notes and closeout

Add a reversible migration for the new nullable proposal fields; verify the actual prior revision before authoring it. No production downgrade, historical ballot rewrite, or automatic enablement. Deployment rollback must retain code capable of reading any newly cast ballots; disabling new creation does not authorize removing counters used by open votes.

Production QA uses a disposable explicitly enabled organization, synthetic consenting test accounts and no identity-provider sessions. Keep real organizations' methods disabled unless their authorized administrator opts in. Verify each method's ballot and result journey, late option behavior, parent/sub-org settings, and manual/worker close; avoid unwanted email through test preferences and existing demo-email safeguards. Do not mutate unrelated production proposals.

Closeout reports per-stage DONE/blocked/scoped-up, tests and count delta, reference versions and disagreements, migration cycles and PG smoke, actual rendered browser evidence, performance measurements, changed files, branch/commit/merge SHAs, exact Railway deployments and frontend bundle, production sanity, unresolved defects, and any deferred boundary. A green algorithm test alone is not a completed voting method.

## Research references

These sources establish counting concepts; the organization gates, omission disclosures, lifecycle rules, weights, tie priority and approved labels above are explicit platform choices.

1. [STAR Voting explanation](https://www.starvoting.org/star) and [blank versus zero](https://www.starvoting.org/blank_vs_zero).
2. [Larry Hastings starvote](https://github.com/larryhastings/starvote), a reference tabulator with explicit tie stages. Pin the exact version during W1 and retain fixtures; do not rely on a moving branch at runtime.
3. [STAR FAQ](https://www.starvoting.org/faq), including the contrast with total-score voting. Advocacy claims of superiority or immunity to strategy are not product guarantees.
4. [Tideman, Independence of Clones as a Criterion for Voting Rules, 1987](https://www.condorcet.vote/assets/DOCS/IndependenceofClones.pdf). Ranked Pairs variants differ on equal strengths; this spec states ours explicitly.
5. [Balinski and Laraki, A Theory of Measuring, Electing, and Ranking, 2007](https://pdodds.w3.uvm.edu/research/papers/others/2007/balinski2007a.pdf).
6. [Mieux Voter FAQ](https://app.mieuxvoter.fr/en/faq), for the verbal-grade user experience. Its concise majority-gauge explanation is not a substitute for the full tie algorithm fixed here.
