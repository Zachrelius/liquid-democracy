# Phase 113 execution evidence

Execution authorized October 10, 2026. Baseline fetched origin/master: 27e67accafd3367f66f66ff5a27fc462876159fa. Isolated branch phase-113/multiwinner-methods-and-budget-choices. Approved spec committed first as 4da392b. Root notes, audit sample, backup and recovery stash untouched.

## W0 review

Existing Organization.settings, Proposal.voting_rules and final_method_result JSON support additive capability preferences, versioned rules and winner-set installation records without schema alteration. Existing v1 metadata/result readers must retain byte-for-byte contracts; new rule dispatch must branch explicitly and validate K against the proposal. No migration planned; migration smoke not required, but PostgreSQL transaction/race gates remain mandatory.

New preferences: allowed_multiwinner_methods (four separate opt-ins, absent = []), allowed_budget_aggregations (fresh = median; absent existing = median and trimmed_mean). Allocated Score will be a distinct allowed_voting_methods entry only at W6. Effective preferences are bounded by parent restrictions for new capabilities and include provenance. JSON partial merges preserve unrelated/old-client values. No capabilities exposed by W0.

Independent oracles will be locally authored: literal weighted Score sums, independent sequential STAR finalist/runoff fixtures, expanded-small-histogram MJ median deletion, Kahn fixed-graph Ranked Pairs oracle, and Fraction-based unit-voter Allocated Score oracle compared with pinned Appendix D. No reference code copied into MIT production. Required hand profiles precede randomized checks. Large-weight/replication/scaling fixtures prove counters do not expand shares.

Audit targets: both create paths and shared validator; draft method/K destructive-reset flow; import preview/clone and direct seed initialization; delegation dispatch and ballot schema; frozen record validation and privacy projection; sustained-majority snapshot rule compatibility/winner-set/reason; election candidate snapshot and atomic set preflight/assignment; manual routes and worker notification/close. Scheduled generation stays ranked choice. No production mutation before all release gates.

Chrome extension Person 1 is connected through the supported browser tools; local/prod rendered gates will use it. W0 contracts/security/legacy regressions: 125 passed, 0 failed (11.99s), including existing SQLite migration-cycle regression. W1-W7 not started.


## W1 local gate

Budget aggregation permissions implemented in organization/sub-organization settings, effective response metadata, creation/import-preview validation, draft grandfathering and service initialization. Fresh root defaults median-only; missing legacy key remains both. Omission stays omitted through schema validation until the effective default is resolved. Same-rule existing drafts retain their choice; new imports/clones never receive grandfathering. Existing seed pipelines currently write no allocation budget config; new direct service creation uses initialize_rules with db.

Backend: 90 budget/weighted/delegation/serializer tests passed, 266 sub-org/import/election/JWT compatibility tests passed, final 80 inheritance/config/settings tests passed after the parent-narrowing regression. Initial import-preview test expected 200 for a rejected upload; corrected to the existing 422 error contract. Existing schema test updated because omitted aggregation now intentionally resolves at the organization-aware creation boundary. No unresolved failure.

Frontend: full 140 tests (+5), build index-DK892QzF.js, changed-file lint clean. Locked npm install reports 14 dependency audit findings; release security review pending; no dependency changes made. Existing build chunk/Browserslist warnings remain.

Chrome local normal-auth synthetic owner PASS: fresh median-only settings; keyboard Space/Enter enable/save/reload both choices; keyboard-expanded 10%/weighted/small-sample help; trimmed-only save and creator fixed label; 380px creator, successful draft submission, exact SQLite trimmed_mean roundtrip; child inherited controls locked, override and median-only save; two-choice labeled dropdown with ArrowDown and actual focused/selected state. Temporary viewport reset. Creator document shows existing 10px horizontal overflow at 380px; changed aggregation controls fit their container. No production mutation. Production QA is W7.

Parent narrowing review: stale child aggregation preferences must not make the child unreadable. New effective choices are bounded by the parent; incompatible new explicit child saves reject, unchanged existing drafts retain their aggregation. Null reset removes the new child key, and the existing allowed_voting_methods reset key, without changing the globally intentional explicit-null org_config contract.
