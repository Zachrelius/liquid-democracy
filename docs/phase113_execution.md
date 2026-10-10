# Phase 113 execution evidence

Execution authorized October 10, 2026. Baseline fetched origin/master: 27e67accafd3367f66f66ff5a27fc462876159fa. Isolated branch phase-113/multiwinner-methods-and-budget-choices. Approved spec committed first as 4da392b. Root notes, audit sample, backup and recovery stash untouched.

## W0 review

Existing Organization.settings, Proposal.voting_rules and final_method_result JSON support additive capability preferences, versioned rules and winner-set installation records without schema alteration. Existing v1 metadata/result readers must retain byte-for-byte contracts; new rule dispatch must branch explicitly and validate K against the proposal. No migration planned; migration smoke not required, but PostgreSQL transaction/race gates remain mandatory.

New preferences: allowed_multiwinner_methods (four separate opt-ins, absent = []), allowed_budget_aggregations (fresh = median; absent existing = median and trimmed_mean). Allocated Score will be a distinct allowed_voting_methods entry only at W6. Effective preferences are bounded by parent restrictions for new capabilities and include provenance. JSON partial merges preserve unrelated/old-client values. No capabilities exposed by W0.

Independent oracles will be locally authored: literal weighted Score sums, independent sequential STAR finalist/runoff fixtures, expanded-small-histogram MJ median deletion, Kahn fixed-graph Ranked Pairs oracle, and Fraction-based unit-voter Allocated Score oracle compared with pinned Appendix D. No reference code copied into MIT production. Required hand profiles precede randomized checks. Large-weight/replication/scaling fixtures prove counters do not expand shares.

Audit targets: both create paths and shared validator; draft method/K destructive-reset flow; import preview/clone and direct seed initialization; delegation dispatch and ballot schema; frozen record validation and privacy projection; sustained-majority snapshot rule compatibility/winner-set/reason; election candidate snapshot and atomic set preflight/assignment; manual routes and worker notification/close. Scheduled generation stays ranked choice. No production mutation before all release gates.

Chrome extension Person 1 is connected through the supported browser tools; local/prod rendered gates will use it. W0 contracts/security/legacy regressions: 125 passed, 0 failed (11.99s), including existing SQLite migration-cycle regression. W0 initial gate passed; subsequent gates are recorded below.


## W1 local gate

Budget aggregation permissions implemented in organization/sub-organization settings, effective response metadata, creation/import-preview validation, draft grandfathering and service initialization. Fresh root defaults median-only; missing legacy key remains both. Omission stays omitted through schema validation until the effective default is resolved. Same-rule existing drafts retain their choice; new imports/clones never receive grandfathering. Existing seed pipelines currently write no allocation budget config; new direct service creation uses initialize_rules with db.

Backend: 90 budget/weighted/delegation/serializer tests passed, 266 sub-org/import/election/JWT compatibility tests passed, final 80 inheritance/config/settings tests passed after the parent-narrowing regression. Initial import-preview test expected 200 for a rejected upload; corrected to the existing 422 error contract. Existing schema test updated because omitted aggregation now intentionally resolves at the organization-aware creation boundary. No unresolved failure.

Frontend: full 140 tests (+5), build index-DK892QzF.js, changed-file lint clean. Locked npm install reports 14 dependency audit findings; release security review pending; no dependency changes made. Existing build chunk/Browserslist warnings remain.

Chrome local normal-auth synthetic owner PASS: fresh median-only settings; keyboard Space/Enter enable/save/reload both choices; keyboard-expanded 10%/weighted/small-sample help; trimmed-only save and creator fixed label; 380px creator, successful draft submission, exact SQLite trimmed_mean roundtrip; child inherited controls locked, override and median-only save; two-choice labeled dropdown with ArrowDown and actual focused/selected state. Temporary viewport reset. Creator document shows existing 10px horizontal overflow at 380px; changed aggregation controls fit their container. No production mutation. Production QA is W7.

Parent narrowing review: stale child aggregation preferences must not make the child unreadable. New effective choices are bounded by the parent; incompatible new explicit child saves reject, unchanged existing drafts retain their aggregation. Null reset removes the new child key, and the existing allowed_voting_methods reset key, without changing the globally intentional explicit-null org_config contract.


## W2 local gate

Score top-N uses score_0_5_top_n_v1, frozen K/omission/selection/tie metadata and a v2 frozen result. Positive weighted sums alone determine the selected prefix; zero-score options never fill a place. Original weights and single-winner v1 remain unchanged. Strict integer K is bounded at 120. Draft method/K changes require explicit preliminary-ballot reset and fresh rules; same-choice saves after organization restriction preserve rules. Ordinary voting cannot open with K above options. Write-ins and locked nominations honor the 120-option counting bound.

The versioned election-set path preflights all candidates and capacity, preserves incumbents for partial refresh rejection or any pending/rejected candidate, and installs every selected office/role inside one savepoint. Expected second-assignment rejection rolls back all grants while freezing per-candidate/overall reasons; unexpected assignment or audit failures roll the entire close back for retry. Frozen snapshots compare winner sets and unfilled reasons and reject any consulted priority. Existing one-winner paths retain their format and notifications.

Backend gates: 37 new W2 tests; combined current capabilities/budget/contracts/single-winner-election gate 276 passed. Score/archive/stability/privacy/Phase112 compatibility gate 202 passed. Final focused gate recorded in the test log. No migration; PostgreSQL transaction races remain W7, migration smoke not required. The independent hand totals are 12/10/8, grouped/replicated and billion-scale weights, committed SHA priority computed without the production priority helper, unsupported partials and aggregate-corruption rejection. Real Vote.ballot and downstream roles/assignment rows are asserted across both manual routes and scoped worker, including neutral/direct override, abstention/retraction, same-count grandfathering and second-step rollback/retry.

Frontend 146 tests (+6 from W1), build index-DLOh6xrK.js before final copy corrections; final release build remains W7. A Vite dependency-scan shutdown race caused one initial test-file failure; disabling discovery in the two new SSR test servers removed the race. Changed-file lint has zero new findings. Existing OrgTitlesPanel has 2 baseline errors; ProposalDetail has 6 baseline errors and 1 warning (existing effect/unused-code debt). Preserve rather than suppress these globally.

Chrome local PASS: keyboard opt-in/save; parent creator K=2/three options, mobile 380px, actual 5/4/0 ballot, ordinary close and frozen selected set/seed; desktop frozen view; election modal permits Score with two officeholders, three fictional candidates nominated through guarded service fixture, keyboard cast/normal close, plural frozen installation message. Actual database rows: Fictional Candidate 1 and 2 both assigned and promoted to moderator, exactly one election.resolved audit. Screenshots saved under the task visualization directory (phase113_score_mobile.jpg, phase113_score_desktop.jpg, phase113_score_election_mobile.jpg). Browser found stale single-winner header/help/modal copy; corrected before gate. Viewport reset. No production writes. W3-W7 remain pending.


## W3 local gate

Bloc STAR repeats the exact released STAR counter on each remaining supported pool with original represented weights. Every pool, finalist/runoff/equal preference and tie stage is preserved; a sole supported option is explicitly selected without a competitive runoff. The frozen v2 reader validates original scores/histograms in every round, remaining pools, counts, rules and the selected order. Legacy v1 records reject injected multiwinner fields. Confirmed departure from budget allocation clears obsolete budget config before experimental rule initialization.

Independent hand profiles verify 4/3/2 runoffs and a first-runoff loser displaced in the next round. Pinned test-only starvote 2.1.5 comparisons include 200 Bloc profiles and the unchanged Phase 109 single-STAR corpus. Final focused W3 gate: 99 passed, no skips/failures; prior broader compatibility gate 124 passed. Shared office lifecycle/rollback tests now parameterize Score and STAR; ordinary delegated-weight routes and workers likewise cover both. Reference adapter initially passed removed candidates to the oracle tiebreaker; corrected the adapter to filter that fixed priority list, with no production algorithm change.

Frontend: 147 tests passed, build index-OIC-pgBI.js before final election-picker copy correction. Changed-file lint has no new findings; baseline lint debt recorded under W2. Settings, creator, ballot, headers and office picker identify Bloc STAR and unchanged full influence. Results disclose every competitive or singleton round.

Chrome local normal-auth keyboard PASS: separate opt-in, ordinary two-selection creation/ratings, normal close, frozen two-round results on desktop and 380px. With four synthetic members, a second identical fictional ballot met quorum without changing settings. Office journey PASS: three fictional nominees, two competitive rounds, normal management close; Fictional Candidate 2 and 3 both installed with moderator roles and exactly one election.resolved audit. Frozen plural installation message and mobile results verified. Evidence: phase113_bloc_star_mobile.jpg and phase113_bloc_star_election_mobile.jpg in the task visualization directory. Viewport restored. No production mutation. W4-W7 pending.
