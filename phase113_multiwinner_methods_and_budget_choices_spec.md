# Phase 113 — Multiwinner methods and organization-controlled budget choices

Status: APPROVED FOR EXECUTION by Z, October 10, 2026, after primary-checkout synchronization. The prior hold is released. Implementation, testing, normal no-ff integration and production deployment are authorized under the gates below. The specified baseline is approved; report material deviations for review.

## Goal and future dispatch

Extend Score, STAR, Majority Judgment and Ranked Pairs to multiple winners in straightforward, explicitly nonproportional ways. Add Allocated Score as a separate proportional method. Let organizations control which budget allocation aggregation rules proposal creators may choose.

Z wants to preserve each method's recognizable logic, not force every method toward proportional representation. Ranked choice/STV remains the existing proportional ranked-ballot option. Allocated Score supplies an additional proportional rating-ballot option. This pass covers ordinary organization/sub-organization proposals and officeholder elections where applicable.

Z has released the hold. Authorized dispatch: `Read and execute phase113_multiwinner_methods_and_budget_choices_spec.md`. Begin in a visible implementation task; no scheduling mechanism is needed.

Read this spec in full, then current PROGRESS.md, applicable AGENTS.md, and Phase 109/110 implementation evidence. Reviewed local origin/master is e3b7a0c, which records Phase 112's JWT hardening closeout; primary-checkout synchronization subsequently merged as 8779bf5. Verify the current security baseline at execution. On actual dispatch, fetch and reconcile the then-current security baseline. Preserve Phase 112 access-token purpose checks, PyJWT migration and token-log redaction. The original root checkout is old and dirty: never reset, clean or broadly stage it.

## Branch, delivery and team

On future dispatch use an isolated worktree and branch `phase-113/multiwinner-methods-and-budget-choices` from current origin/master. Copy and commit this spec before application edits. Use no-ff integration and the existing deployment convention. No force pushes, production history rewrite, real-election backfill or infrastructure/secret changes.

Use a visible project task for implementation, with progress and closeout there. Z explicitly prefers visible tasks for substantial delegated work. A lead may coordinate additional visible workstreams if explicitly dispatched; do not hide a long-running implementation in subagents. One owner per mutable checkout. Work on one counting method at a time; shared groundwork is not permission to ship unfinished methods.

| Stage | Scope | Gate to continue |
| --- | --- | --- |
| W0 | Capability/rule contracts, settings compatibility, independent oracle design | Reviewed defaults, serialization and migration plan; legacy regression checks |
| W1 | Budget aggregation permissions and creator UI | Settings/API/weighted-budget regressions, rendered QA |
| W2 | Score top-N, ordinary proposals and elections | Independent tally and full lifecycle/assignment tests, rendered QA |
| W3 | Bloc STAR, ordinary proposals and elections | Sequential runoff fixtures, W2 regressions, rendered QA |
| W4 | Majority Judgment top-N | Independent full-order and boundary-tie fixtures, rendered QA |
| W5 | Ranked Pairs top-N | Full-order contract review and independent fixtures before enabling; rendered QA |
| W6 | Allocated Score | Pinned reference, rational arithmetic/representation fixtures, integration and rendered QA |
| W7 | Whole-pass release and production verification | Full verification matrix, exact deployment evidence, closeout |

Default delivery is one release after all gates. A smaller complete slice may ship separately after future execution authorization, provided unreleased capabilities remain rejected by the server and unavailable in settings. Document each actual boundary. Do not expose W0 registry entries as working features.

## Verification matrix

| Check | Required | Notes |
| --- | --- | --- |
| Independent counters and hand-calculated fixtures | Every method | Expected winners must not be calculated by the production implementation |
| Single-winner backwards compatibility | Yes | Existing rule IDs, ballots, ties, labels, results and office assignment unchanged |
| Settings/defaults/inheritance | Yes | Fresh/existing orgs, sub-org inheritance/overrides, disabled parent methods, stale client saves |
| Creation/edit/import/service enforcement | Yes | Generic and org create, election route, draft changes, cloning, preview/import, seed/service paths |
| Ballots/delegation/weights | Every method | Direct overrides, abstention/retraction, chain/topic behavior, represented-member weight, zero/large weights |
| Ranked Pairs ordering | Yes before W5 release | Ties, incomplete rankings, cycles, one fixed graph vs recomputation, independent topological oracle |
| Allocated Score arithmetic | Yes before W6 release | Exact quotas, split boundary, remaining fractions, reference match, no per-share expansion |
| Election side effects | Every method | Correct winner SET installed; capacity/slate/verification/permission failures, no legacy fallback |
| Lifecycle and frozen results | Every method | Both manual routes, worker, quorum/no-result/partial results, stability, retry, archive/history |
| PostgreSQL races and rollback | Yes | Vote/option/close races, concurrent closes, overlapping title assignments, injected failures |
| Privacy | Yes | Early/private results, graph/profile, notifications, exports; no ballot identities in public allocation trace |
| Frontend tests/build/changed-file lint | Yes | Accessible controls, state/payload transitions, result disclosures; baseline lint debt separate |
| Full backend suite | Final integration | Focused suites per stage; report real baseline/delta, skips and failures |
| SQLite migration cycle | If migration added | Subprocess upgrade/downgrade/upgrade; reversible schema/data compatibility |
| PostgreSQL migration smoke | If migration added | Verify actual prior head at dispatch; reviewed head a109b0c1d2e3, never assume still current |
| Performance and response size | Yes | Existing 120-option bound, large weights, multiple seats, dense pairwise and repeated allocation |
| Browser QA local and production | Yes | Desktop/380px/keyboard, settings to ballot to results/office; supported Chrome tooling |
| Production deployment | Yes | Exact backend SHA/deployment, frontend bundle, health/readiness/monitor and isolated synthetic journeys |
| Diff/security/license review | Yes | Preserve Phase 112 fixes and MIT notices; do not copy reference code without license review |

No migration is assumed unnecessary: settings may fit existing JSON, but frozen rules/result versioning and compatibility must be reviewed. If no migration is needed, explicitly say migration smoke not required; PostgreSQL transaction tests remain required. Missing browser tools are a blocker for rendered gates, not permission to substitute source review.

## Agreed product decisions

1. Multiwinner Score selects the highest totals. Multiwinner STAR means Bloc STAR with repeated runoffs. Multiwinner Majority Judgment selects the highest entries in its majority ranking. Multiwinner Ranked Pairs selects from one collective ordering, subject to explicit tie/order review.
2. These four extensions do not redistribute voting influence between groups. Say so plainly. Similar candidates may win several or all seats; this is not automatically a bug.
3. Allocated Score is ONE distinct method with ONE organization setting, ballot identity and counting rule. It is not duplicated under Score and STAR. Explain its association with the name Proportional STAR in help. It has no automatic runoff.
4. Organizations control availability; creators choose among allowed capabilities. New methods/capabilities are opt-in. Existing single-winner settings stay unchanged.
5. Budget allocation defaults to median for new organizations. Trimmed mean is available only when permitted by the organization. A single available aggregation is displayed without a redundant dropdown; two choices produce a dropdown.
6. Existing proposals/elections keep their rules when org settings change. No live ballot conversion, retroactive counting change or historical result recomputation.
7. Ordinary write-ins and early voting retain current org policies. Elections retain the authorized candidate workflow and nomination restrictions; arbitrary text cannot nominate someone or grant office.

## W0 — Capabilities, settings and frozen rules

Prefer a shared capability registry over new scattered allow-lists. Separate method identity, supported seat count and enabled organization capability. Suggested representation (implementation may choose equivalent names): retain existing IDs `score`, `star`, `majority_judgment`, `ranked_pairs`; add `allocated_score`. Freeze an explicit rule/variant and requested winner count on new proposals. STAR uses single-winner v1 for K=1 and a new Bloc rule for K>1. Allocate Score is multiwinner-only in this release (K>=2); do not silently substitute Score or STAR at K=1.

Existing enabled methods remain enabled for their existing single-winner use. Add separate opt-ins for each of the four new multiwinner capabilities, initially false, so existing orgs do not unknowingly gain new election rules. Show “Allow multiple winners” beneath the relevant method with its description (STAR: “Allow Bloc STAR for multiple winners”). Allocated Score is its own top-level row, initially false. No new overarching category that duplicates entries or reverses Phase 110's unified-list design.

Use the existing parent/sub-org settings inheritance model, including locked fields and who may narrow/override. Resolve method and capability through one server-side effective-settings function; never broaden a parent's restriction by fallback. Disabling a parent method makes its multiwinner capability unavailable for new creation; stored child preference can remain but must not override the disabled parent method. Preserve unrelated settings on saves and old clients. Return effective values and inheritance metadata to the FE.

Freeze K, algorithm version, omission policy, tie policy and allocation/quota policy before any ballot, including allowed early ballots. Changing method, variant or K is draft-only under the existing preliminary-ballot destructive-change rules. Cloning/import must create fresh rules and seed. Client input cannot supply protected rules, frozen results or tie seed. Keep old v1 rules/results readable byte-for-byte; new rules never reinterpret an old election. Invalid registry dispatch must fail loudly, not count as binary.

Validate strict integer K against existing safe limits, title capacity and distinct options at the appropriate lifecycle stage. Ordinary contested votes require K<=eligible options; early draft/nomination states may temporarily have fewer options under existing workflows. Never install more than K winners. Budget modes and approval-winner configuration cannot be combined with these new variants. Global proposals without an org authorization remain out of scope.

## W1 — Budget aggregation permissions

Current `budget_config.aggregation` accepts `median` or `trimmed_mean` and defaults to median. Preserve these counters; do not implement a new averaging rule. Add an effective org allow-list, e.g. `allowed_budget_aggregations`, with validated members and at least one entry whenever budget allocation is enabled.

- Fresh organizations: median only, recommended; do not enable budget voting if it was otherwise disabled.
- Existing organizations without this setting: compatibility fallback permits both currently supported aggregations, with median still the creation default. This preserves existing availability without a production scan/backfill. Settings must visibly show the inherited/legacy effective values; saving an unrelated setting must not silently reduce them. Org admins may then choose median-only explicitly.
- If only trimmed mean is enabled deliberately, it becomes the sole/default creation choice. No separate default-setting control is needed this pass.
- Existing proposals, including existing drafts retaining the same aggregation, remain usable after a restriction change. New clones/imports and changes to a different aggregation use the current allow-list. An omitted aggregation at creation resolves to the permitted default, not unconditionally median. Invalid explicit choices fail with a clear message rather than silently switching.
- Apply enforcement to both create paths, draft edit and import/preview/service/seed paths. Existing trusted data reads are not new creation. Preserve exact aggregation in response builders and result display.

Settings copy: **Median (recommended):** “Use the middle suggested amount for each category, then adjust the combined amounts to fit the budget and category limits.” **Trimmed mean:** “Average suggested amounts after trimming the highest and lowest portions, then adjust the combined amounts to fit the budget and category limits.” Expanded help must state the actual trimming fraction and weighted/small-sample behavior verified in the existing code. Do not claim the complete normalized budget algorithm is strategyproof based only on the per-category median.

## Common multiwinner semantics

K means up to K supported selections, with a visible reason if fewer can be selected. Do not invent positive support or award a wholly unsupported option just to fill the count. These no-support rules are platform policy, separate from the mathematical rank order, and must be disclosed. Preserve Phase 109's single-winner no-result behavior.

For Score/Bloc STAR, an option with zero total positive-weight score is unsupported. For Majority Judgment, an option with no grade above Reject from any positive weight is unsupported (a Reject median alone does not make it unsupported). For Ranked Pairs, exclude wholly unranked options, and require at least one strict preference somewhere among eligible candidates; if all eligible candidates are tied with each other, there is no meaningful result. Rank supported eligible options using the specified procedure. For Allocated Score, stop if no remaining candidate has positive score under remaining influence. Never expand the winner count to resolve a tie.

Quorum is determined once by established participation/count-mode rules, including explicit abstention as currently implemented. A valid neutral ballot is still a direct override and participation; it is not a missing/delegated ballot. Method-specific preference aggregates exclude abstentions. No new rating threshold, minimum median or approval threshold is introduced.

Ordinary multiwinner outcomes may finalize with fewer than K winners when support is exhausted; disclose selected count and reason. Do not call partial selection “all seats filled.” When quorum is unmet, no official winners/office grants are finalized; provisional tallies follow current visibility policy. No-result and tie cases must remain distinct.

Use existing committed candidate priority for irreducible ties; freeze the seed once, no redraw on seat rounds, retries or deadline extensions. Disclose boundary tie handling and any priority-dependent stage. Conservative early-close stability: if any consulted arbitrary priority affected counting, do not mark stable. Otherwise stability compares the winner SET and unfilled-seat reason, not merely first winner or display ordering. Later option changes invalidate relevant snapshots as in Phase 109; maximum-extension behavior remains intact.

Resolve effective ballots with existing whole-ballot delegation and represented-member integer weights. A delegate's ballot may represent many members, but it does not become one vote or acquire the delegate's own weight for all members. All multiwinner round calculations preserve this. No expansion into one record per share. Cross-org visibility/membership/verification and count-mode boundaries are unchanged.

## W2 — Score top-N

New rule e.g. `score_0_5_top_n_v1`. Sum the same 0–5 scores with existing effective weights, sort supported options by descending total, use committed priority for exact ties, take first K. No reweighting, runoff, maximum-score-count tiebreak or new average denominator. Preserve omitted=0 and existing common denominator for averages.

Results: winner set, ranked totals, requested/filled count, tie at selection boundary and no-support reason if any. Public copy: “Rate each option from 0 to 5. The options with the highest total scores win. Every ballot counts at full weight toward every selection; this does not provide proportional representation.”

## W3 — Bloc STAR

New rule e.g. `star_bloc_0_5_v1`. Select a winner using exact Phase 109 STAR finalist and runoff rules; exclude that winner and repeat with unchanged original ballot weights. Finalists are the highest-scoring remaining supported options, not the first runoff's two finalists automatically becoming winners. When only one supported option remains, fill at most one remaining place with it and disclose selection without a competitive runoff. Stop on support exhaustion.

Reuse the pinned Phase 109 tie stages, including finalist boundary preference/five-star rules, with each round's remaining pool. Never re-normalize scores or reallocate voting weight. Results preserve every round's pool, finalists, totals, runoff/equal preference, consulted tie stages and selected option. Do not present original score order as STAR's winner order.

Copy: “Select each winner using STAR's scoring and automatic runoff. Remove that winner and repeat for the remaining places. Every ballot retains its full weight in every round; this does not provide proportional representation.”

## W4 — Majority Judgment top-N

New rule e.g. `majority_judgment_lower_median_top_n_v1`. Build the same original weighted grade histogram for each option. Order candidates by the existing lower-middle grade and repeated-median-removal comparison, using committed priority only for identical distributions. Select first K supported candidates. Temporary grade removal is solely for comparing a tie; do not carry depleted histograms from one comparison/seat to the next or reduce voters' influence between winners.

Implement the full ranking with a consistent comparator or equivalent algorithm verified by an independent literal-removal oracle on small histograms. Test transitivity, equal medians/deep ties and tie at the K/K+1 boundary. Skip histogram runs mathematically; no per-share iteration. Display original majority grades and distributions plus the selection-boundary explanation, never numeric averages as the deciding metric.

Copy: “Grade each option from Reject to Excellent. Select the options highest in the majority-grade ranking, using the same grade-based tie rules. Each option is judged by the full electorate; this does not provide proportional representation.”

## W5 — Ranked Pairs top-N: exact ordering gate

New rule e.g. `ranked_pairs_margins_top_n_v1`. This is our explicitly specified top-N extension, not a claim that every multiwinner Ranked Pairs variant is identical.

Build ONE pairwise matrix and ONE locked acyclic graph across the supported eligible options using Phase 109's margin, winning-support and committed-priority edge ordering. To produce a full order, repeatedly choose a zero-indegree node from that same graph, append it and remove its outgoing edges. If several source nodes are available, choose by committed candidate priority and record its use. Take the first K nodes. Do not recompute victories or re-lock edges after each selected winner; do not substitute pairwise win counts, first preferences or repeated fresh elections.

Before enabling W5, explicitly review that topological completion gives a deterministic order consistent with every locked edge and that K=1 matches the current rule whenever the supported candidate pool is unchanged. Test complete rankings, equal ranks, omitted-last, pairwise equalities, equal-strength cycles, multiple source nodes, renamed labels, ballot iteration permutations and boundary ties. Independently implement a small-profile oracle. If these contracts cannot be met or reveal a material product ambiguity, keep this capability disabled and report a scoped blocker; do not silently choose another method under the name.

Results explain collective order, selected prefix, ordered/locked/skipped victories and source-node ties; retain readable summaries with expandable details. Copy: “Compare options head to head and build a collective ranking, honoring the strongest victories without creating a cycle. Select the highest-ranked options. Votes are not redistributed between winners; this does not provide proportional representation.”

## W6 — Allocated Score, independent proportional method

Method ID `allocated_score`; top-level label **Allocated Score**. Secondary help: “Also known as Proportional STAR. Uses 0–5 ratings and proportional allocation, without an automatic runoff.” It has one independent org opt-in, off by default. Enabling ordinary STAR/Score/Bloc STAR does not enable it. It is available only for K>=2, ordinary proposals or eligible multi-holder elections. No proportional-vs-bloc dropdown hidden under STAR; creators select the distinct method explicitly.

Freeze the published Allocated Score procedure identified by STAR Voting Technical Specifications v1.3 (December 20, 2024), Appendix D, with explicit platform policies below. Pin reference version/hash and record rule ID, quota denominator, allocation sorting convention, tie rule and arithmetic representation. Do not substitute Sequential Monroe, Sequentially Spent Score or Reweighted Range Voting; they are different rules. Reference code is an oracle candidate, not automatically production-safe or MIT-compatible.

### Exact weighted counting contract

For each effective ballot i, let b_i be its original represented integer weight and f_i its remaining fraction, initially 1. Keep b_i separate from f_i. Ballots with b_i=0 contribute nothing. Explicit abstentions and completely all-zero ballots contribute no Allocated Score allocation weight (but retain established participation/quorum/direct-override semantics). Freeze the quota Q=sum(b_i for informative ballots)/K at the start; never shrink Q after seats are filled.

At each round:

1. Compute remaining candidate totals as sum(b_i * f_i * score_i,c), elect the highest positive total with committed candidate priority for an exact tie. Remove the winner from future consideration.
2. Allocate up to Q of remaining voting weight to that winner. Follow the reference's contribution ordering at the unit-of-voting-weight level: sort ballot groups by f_i * score_i,w descending, not by b_i * f_i * score_i,w. The latter would unfairly prioritize large represented groups and violate replication equivalence. For unweighted voters this reduces to the reference's remaining contribution per voter.
3. Consume whole equal-contribution groups while their remaining mass fits. At the boundary group, consume an equal FRACTION of each group's remaining mass sufficient to fill the quota. No arbitrary selection of individual supporters. Never allocate negative weight or more than remains. Record quota shortfall if remaining mass is less than Q.
4. Continue until K winners or no remaining candidate has positive remaining total. Following the reference, zero-contribution ballots can be reached in the allocation ordering if needed to fill a quota; do not invent a positive-support-only variant. If this produces a product concern, document a concrete fixture for review rather than silently changing the method.

Use exact rational arithmetic for comparisons, allocations and frozen values, or another proven equivalent exact scheme. Store fractional quantities as numerator/denominator or equivalent exact decimal-string contracts; UI rounding is presentation only. No floating-point epsilon can decide a seat. Unweighted grouped ballots must match literal expanded ballots; multiplying all original weights by a constant must leave winners/fractions unchanged. Splitting an otherwise identical represented group must not change results.

The quota convention (excluding all-zero ballots) and stopping on no remaining positive support are explicit product policies. Test and explain them; do not claim every conceivable Allocated Score implementation uses these conventions. Missing/new options score zero exactly as Phase 109. This may change whether an edited ballot is informative; all live calculations use a coherent option/ballot snapshot.

### Results and disclosure

Show selected order, initial totals, per-round remaining-weight totals, quota, aggregate weight allocated/remaining and why counting stopped. Explain that election order is not a universal best-to-worst quality ranking. Include “No automatic runoff” beside ballot instructions and in results/help. Show aggregate allocation by contribution band if useful; never reveal named represented voters, raw ballots or delegation chains through the trace. Avoid individual trace data even for apparently anonymous tiny groups where existing privacy rules prohibit it.

Copy: “Rate options from 0 to 5. Winners are selected in rounds by score. After each selection, a share of voting influence is allocated to that winner, giving voters who are not yet represented more influence over the remaining places. No automatic runoff.”

Explain proportionality in terms of expressed support/voting weight, not guarantees about demographic attributes or one seat for every informal group. In share-weighted orgs, representation follows eligible voting weight, not headcount. The allocation reduces influence only within this vote; it never changes a member's shares, delegation permissions or voting power on other proposals.

## Lifecycle, election integration and persistence

Audit the Phase 110 `experimental_elections.py` path, which currently stores a singular winner_user_id and validates one winner. Extend with a versioned winner-set/installation structure while preserving old records and notifications. Adapt all capability guards, registry dispatch, schemas, `experimental_voting.initialize_rules`, final result serializers, manual/worker close and snapshot logic; changing only a winner-count validator is insufficient.

Election winner selection must use one authoritative frozen tally; never recount after roles or membership change. Map options by stable candidate user IDs, freeze human-readable names separately, reject foreign/ineligible identities. Never use the legacy first-declared fallback or exception-as-quorum-success path. Preserve Phase 112 token rules in tests and QA harnesses.

Use the existing nominations, cosign, term, elected-revert, capacity, fill-vacancies and refresh-slate policies. System roles that cannot support K occupants reject that election configuration. Do not open a multiple-steward election. Scheduled elections retain current ranked-choice generation; adding per-title scheduled method selection remains out of scope.

Uncontested policy: when eligible candidates number at most K, preserve the existing election-policy auto-election on met quorum, recorded distinctly from a competitive tally. Zero candidates remains no-election/holdover. Ordinary proposals do not gain this shortcut. For contested elections, an exhausted-support partial winner set leaves vacancies and reports the reason. A partial set MUST NOT silently clear an entire incumbent slate: allow fill-vacancies where valid; reject refresh-slate installation as an explicit expected policy outcome when fewer than K supported winners were determined. Keep tally results visible subject to privacy, with seats unchanged and a clear installation reason.

Preflight the entire winner set and capacity before granting/revoking anything. For this pass, assignment is all-or-nothing across the selected set: if any winner has a policy rejection or pending-verification restriction, freeze per-candidate reasons and an overall not-installed/pending outcome, leave all prior seats/roles intact, and grant no new privilege. No silent runner-up substitution. A later authorized installation action follows existing capabilities; do not promise automatic installation after verification. This conservative set-level policy must be explicit in admin results/help.

If preflight succeeds, install the whole set with slate refresh/role transitions in one transaction/savepoint boundary. Expected assignment-time rejection rolls back ALL seat/role mutations while retaining a truthful frozen rejected outcome. Unexpected tally/serialization/assignment/audit failures roll back the entire close for retry. Serialize on proposal plus organization/title state in consistent lock order, including races with other elections for the same title. Retry cannot duplicate grants, revoke twice, emit duplicate audit/notification intent, advance a schedule again, or redraw ties.

Frozen results include method/version, K, supported/selected/unfilled sets and reasons, weighting unit, quota (Allocated Score), aggregate traces, option/candidate snapshots, rules commitment/revealed seed, actual close timestamp and installation outcomes. No historic recomputation after membership, delegation, scores, labels or settings change. Existing one-winner exports/notifications must remain compatible; new ones pluralize accurately. Preserve privacy for results, histories, graphs, live messages and export, including before-close seed secrecy.

## Independent fixtures and regression requirements

- Score: totals A=12, B=10, C=8, K=2 -> A/B; equal boundary and zero-support tail. Old K=1 results unchanged.
- Bloc STAR: 4 ballots A5 B4 C0, 3 ballots A0 B5 C4, 2 ballots A0 B0 C5. Scores A20/B31/C22. B beats C 7–2 for seat one. With B removed, C beats A 5–4 for seat two -> B/C. Include a separate fixture where first runoff loser does NOT win the next seat.
- Majority Judgment: independently graded profiles with tied medians but distinct deeper grades around K/K+1; literal-removal full order; verify original histograms unchanged after every comparison.
- Ranked Pairs: 3*A>B>C, 2*B>C>A, 2*C>A>B locks A>B and B>C before skipping C>A; K=2 -> A/B. Add incomplete graphs, equal ranks and a case distinguishing fixed-graph prefix from recomputation.
- Proportionality illustration: 60 ballots give all five A options 5 and five B options 0; 40 reverse. K=5. Allocated Score -> three A/two B; Score/Bloc/MJ and coherent majority rankings may select five A. Test group counts despite within-group ties. Do not advertise the illustration as a demographic guarantee.
- Allocated Score boundary: 30 identical ballots score A5/B0, 20 score A0/B5, K=2. Q=25; after A, the first group's remaining fraction is 1/6, not five arbitrarily retained people. B wins next. Verify exact aggregate conservation.
- Allocated Score after fractional allocation: a fixture where original score ordering and remaining-contribution ordering differ; prove the pinned reference ordering is followed. Weighted group splitting/replication and billion-weight cases; neutral/exhausted remainder and zero-score allocation bands.
- Every variant: zero ballots, all abstain, all neutral, fewer supported options than K, ties at the boundary, deleted/withdrawn options, late additions, changed vote, count-mode and quorum, disabled after creation, archive/frozen retrieval, invalid payloads and malicious cross-org IDs.
- Election matrix: correct multi-person office grants and bound-role effect, explicit uncontested/partial outcomes, inactive winner, capacity change, refresh-slate preservation, pending verification, failure on SECOND assignment, audit staging exception, retry and concurrent close. Assert actual rows/roles, not just HTTP response.
- Budget matrix: fresh median-only, old missing-key both, explicit overrides/inheritance, trimmed-only, empty/unknown list rejection, disallowed explicit aggregation, default omitted, unrelated save preservation, existing draft/grandfathered vote and clone/import checks.

Random/reference tests supplement rather than replace these hand fixtures. Test real SQLAlchemy Vote.ballot shapes and production autoflush=False. Independent code must not import the counter under test for expected results. Preserve exact single-winner reference behavior from Phase 109/110.

## Performance, UI and operational constraints

Use existing candidate/option caps and server-validated K. Benchmark 1,000 voters x 20 options, 10,000 x 20 and 1,000 x 120 with varying K, dense ties, large weights and long delegations. Compare query count, elapsed time, memory and serialized response size with Phase 109 evidence. Rational denominators and round traces must not grow without bound in practical supported limits. If necessary optimize/group identical ballots or propose a measured lower Allocated Score capacity; do not silently truncate ballots/options or approximate seat decisions. Avoid per-seat DB/delegation recomputation.

Settings and creator controls use Phase 110's shared descriptions, parent/sub-org lock indicators and accessible labels. Show selected method/variant and K before casting. A creator changing K/method must explicitly resolve incompatibility rather than silently convert an existing ballot. Show multiwinner capability only where enabled. Desktop, roughly 380px mobile, keyboard/focus and read-only/frozen results must be verified. Do not turn choosing a method into an unexplained technical configuration screen.

On future execution use private synthetic QA orgs/accounts with notification channels disabled. No real role changes, production resets, global worker tick, secrets in logs/screenshots or one-shot prior-phase harness reruns. Use scoped exact-fixture worker helpers and preserve current auth/token security. Reuse authenticated sessions when appropriate; report password-manager UI blockers rather than blind keystrokes.

## Closeout and references

When eventually implemented, update this spec, PROGRESS.md and docs/phase113_closeout.md. Report per-stage DONE/blocked/scoped-up, exact variant/rule versions, defaults/compatibility decisions, test baseline/delta and skips, migration/PG status, browser evidence, commits/files, exact Railway deployment IDs/SHAs, frontend bundle, health/readiness/monitor, remaining debt and deviations. A merge alone is not completion. Do not imply unfinished methods will continue invisibly.

Sources for counting concepts (platform policies above are explicitly ours):

- STAR technical specification v1.3, Bloc procedures and Allocated Score Appendix D: https://assets.nationbuilder.com/unifiedprimary/pages/501/attachments/original/1734730674/STAR_Voting_Technical_Specifications_V1.3.pdf?1734730674=
- Equal Vote's identification of Allocated Score: https://www.equal.vote/pr
- Proportional STAR overview: https://www.starvoting.org/star-pr
- Tideman's Ranked Pairs ranking: https://www.condorcet.vote/assets/DOCS/IndependenceofClones.pdf
- Balinski/Laraki majority ranking: https://www.rangevoting.org/BalinskiLarakiPNASpdf.pdf

No source's advocacy claims about guaranteed honesty or universal superiority are adopted. Implementation must verify pinned reference licensing under the repository's MIT license. Proportional STAR terminology is an explanatory alias; Allocated Score remains the canonical independent product method.
