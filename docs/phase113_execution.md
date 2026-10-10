# Phase 113 execution evidence

Execution authorized October 10, 2026. Baseline fetched origin/master: 27e67accafd3367f66f66ff5a27fc462876159fa. Isolated branch phase-113/multiwinner-methods-and-budget-choices. Approved spec committed first as 4da392b. Root notes, audit sample, backup and recovery stash untouched.

## W0 review

Existing Organization.settings, Proposal.voting_rules and final_method_result JSON support additive capability preferences, versioned rules and winner-set installation records without schema alteration. Existing v1 metadata/result readers must retain byte-for-byte contracts; new rule dispatch must branch explicitly and validate K against the proposal. No migration planned; migration smoke not required, but PostgreSQL transaction/race gates remain mandatory.

New preferences: allowed_multiwinner_methods (four separate opt-ins, absent = []), allowed_budget_aggregations (fresh = median; absent existing = median and trimmed_mean). Allocated Score will be a distinct allowed_voting_methods entry only at W6. Effective preferences are bounded by parent restrictions for new capabilities and include provenance. JSON partial merges preserve unrelated/old-client values. No capabilities exposed by W0.

Independent oracles will be locally authored: literal weighted Score sums, independent sequential STAR finalist/runoff fixtures, expanded-small-histogram MJ median deletion, Kahn fixed-graph Ranked Pairs oracle, and Fraction-based unit-voter Allocated Score oracle compared with pinned Appendix D. No reference code copied into MIT production. Required hand profiles precede randomized checks. Large-weight/replication/scaling fixtures prove counters do not expand shares.

Audit targets: both create paths and shared validator; draft method/K destructive-reset flow; import preview/clone and direct seed initialization; delegation dispatch and ballot schema; frozen record validation and privacy projection; sustained-majority snapshot rule compatibility/winner-set/reason; election candidate snapshot and atomic set preflight/assignment; manual routes and worker notification/close. Scheduled generation stays ranked choice. No production mutation before all release gates.

Chrome extension Person 1 is connected through the supported browser tools; local/prod rendered gates will use it. W0 contracts/security/legacy regressions: 125 passed, 0 failed (11.99s), including existing SQLite migration-cycle regression. W1-W7 not started.
