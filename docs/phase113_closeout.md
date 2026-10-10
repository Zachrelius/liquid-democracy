# Phase 113 closeout — production verified, October 10, 2026

## Delivery

W0–W7 DONE. All five multiwinner variants, ordinary/sub-organization proposals, office elections and organization-controlled budget choices shipped. One owner executed sequential method gates in isolated branch `phase-113/multiwinner-methods-and-budget-choices`. Application release no-ff merge `a77f4a8286eea603f28698df861761b786a41080`; production-QA caption correction no-ff merge `6843a6f9e212896abc0b3f381a5f640c7c1e6740`. Final documentation is integrated separately with no application change.

The only remaining operational gap is primary checkout synchronization. Its safe fast-forward was refused because the original approved spec is untracked. Primary master remains `27e67accafd3367f66f66ff5a27fc462876159fa`; all 312 pre-existing readable files, including notes/Archive and the dirty historical audit sample, have unchanged SHA-256 hashes. Recovery stash `2965358a22b8ee359cc59a81d3e93f50a800191a` remains. No reset, clean, move, overwrite or broad staging occurred. The isolated release does not imply that primary is synchronized. Evidence: `phase113_primary_sync.json`. Reconciliation is **NOT STARTED**; dispatch: `Safely reconcile the untracked Phase 113 spec with a verified Archive backup, then fast-forward primary master to origin/master.`

## Workstream status

| Stage | Status | Delivered behavior |
| --- | --- | --- |
| W0 | DONE | Central method/capability registry, strict K bounds, separately disabled multiwinner opt-ins, frozen rule versions and compatibility contracts |
| W1 | DONE | Fresh median-only budget default, inherited/parent-bounded permission choices, sole-choice label/two-choice dropdown, grandfathered existing rules and server enforcement |
| W2 | DONE | Score top-N; complete-set atomic office installation, ordinary/election lifecycle and aggregate selected-set records |
| W3 | DONE | Bloc STAR repeats exact Phase 109 runoffs using unchanged ballot influence; singleton remainder explicit |
| W4 | DONE | Majority Judgment ranks original six-bin distributions with lower-median comparison and boundary tie handling |
| W5 | DONE | Ranked Pairs computes one locked graph and one complete order, selects its prefix; no after-seat graph recomputation |
| W6 | DONE | Exact proportional Allocated Score with fixed informative-weight Hare quota, contribution bands and rational aggregate traces; all-five selected-set history |
| W7 | DONE | Full/focused gates, disposable PG races, counter/route performance, privacy/license/security review, local and production Chrome journeys, exact deploy verification |

Four nonproportional variants explicitly retain full voting influence between selections. Allocated Score is a separate opt-in identity (K>=2), explains its Proportional STAR association and has no automatic runoff. Existing K=1 methods/rule IDs/defaults remain intact. K is a strict integer, maximum120; new multiwinner variants support the existing120-option boundary. Parent permissions bound child capabilities; null child method settings inherit. A restrictive new budget setting prevents new disallowed proposals while unchanged existing draft rules survive. No live ballot conversion, historical recount, real-election backfill or migration.

Counters retain represented integer weights without expanding shares. Direct neutral ballots override delegation. Selected set, requested/filled/unfilled count, tie commitment, frozen names, aggregate round data and office outcomes are preserved as v2 records; old v1 records remain supported. Allocated original weight is separate from remaining fraction, all-zero/abstaining ballots are excluded from its allocation denominator, equal boundary bands use a common fraction, and exhausted positive support stops selection. Public allocation fields accept only aggregate values and canonical numerator/denominator strings, never voter profiles. Selection order is not a universal quality ranking.

Office closure installs the entire selected set or grants nobody on expected capacity/eligibility/verification/policy rejection. Partial vacancy results and replacement elections follow their explicit policies; incumbents survive rejected replacement. Unexpected assignment/audit failure rolls back close and retry succeeds once. Tally selection and installation remain separately visible. Stability compares winner sets/unfilled reason and does not declare a consulted priority tie stable.

## Diagnostic fixes

* Child creator omitted num_winners; legacy null method override did not inherit and caused500. Child payload/count controls and method-specific inheritance resolver now preserve K/rules/serialization; five real ORM regressions plus child Chrome save/reopen pass. Failed local attempts created no partial row.
* Disposable PG forced a manual assignment capacity read before concurrent close completed, reproducing3 occupants on a capacity2 title. Custom title mutation routes now lock org/title/member state before capacity reads; selected user locks are acquired together in ID order. Forced races now preserve capacity, and overlap/failure/retry tests pass.
* Production rendered QA found singular Score/STAR graph legend copy at K>1. Captions now refer to the selected set/every Bloc round; exact K1 copy preserved. Final deployed browser caption checks pass.
* Release-helper tests corrected driver assumptions (ProposalOut has no org_id; filled_count wire type is a decimal string). Helper-only fixes, no application persistence defect.

## Verification

Backend baseline: Phase112 **3,794 passing /21 skipped**, 3,815 collected. One full normal-configuration run with test-only pinned STAR oracle: **3,992 passed /20 skipped /0 failed**, 1,155.65s. The final15 boundary cases and4 guarded-helper cases separately pass; final collection4,031, giving **4,011 distinct passing /20 existing skips**. **216 new cases**; enabling the optional STAR oracle moves one previous skip to pass, so passing-count delta is **+217**. This is one full run plus additions/rechecks, not a second full run. Final affected lock/office recheck286 passed, boundary/shared-office gate134 passed, helpers4 passed. Existing deprecation warnings only; no Phase113 skip. Generated historical audit sample excluded from commits.

Independent tests use hand fixtures, randomized oracles and actual ORM storage: Score/top-N ties, 2,000-profile STAR reference comparisons, original MJ order,400 RP fixed-graph profiles,250 literal-unit Allocated profiles, represented-weight splitting/scaling/permutation, policy/scope/privacy/early-result/clone/import/delegation and both create/serializer/seed paths. See `phase113_counting_references.md` for pinned official STAR specification hash and test-only `starvote==2.1.5` MIT reference. Its Allocated routine differs from the approved contract and was not used as that oracle. No reference code/PDF copied into release; no reference/runtime dependency added.

Frontend **154/154 pass**, zero failures/skips, baseline135 (**+19**). Final build PASS, `index-AI_8GDFa.js`. Same-runtime changed-file lint comparison across24 application files: **zero new diagnostics**; pre-existing12 errors/1 warning documented in `phase113_lint_comparison.json`. Package locks unchanged. Phase112 JWT purpose checks, PyJWT2.15.1 migration and token-path redaction remain unchanged; MIT LICENSE unchanged. Tracked-text Didit assignment scanner PASS; scoped guard, not a general secret-scan guarantee.

No migration; SQLite migration cycle and PG migration smoke **not required**. Mandatory disposable PostgreSQL16 transaction testing **42 checks PASS** with production autoflush=False: all-five manual/manual and manual/worker closes, coherent vote/option races, overlapping office capacity, expected/unexpected second assignment failure, audit rollback/retry and two forced manual-assignment races. Zero checked-out connections. Only phase-owned disposable containers removed; no production SQL destructive operation. Evidence `phase113_pg_transactions.json`.

## Production and browser evidence

Live: https://www.liquiddemocracy.us/ . Backend deployment `a422d913-6b82-4825-984a-ce01d1966b83` SUCCESS matches exact `a77f4a8`; frontend `fcab1159-4f24-4c68-8d08-d22f2c18ad04` SUCCESS matches exact `6843a6f`, bundle **index-AI_8GDFa.js** confirmed in Chrome and homepage. Backend caption-only row `039b9f71-8016-44f0-85e2-ee78991ae123` SKIPPED as expected. Initial frontend `877673d6-559e-446d-80a4-9f5141c90202` succeeded for a77 and was subsequently replaced (Railway now labels it REMOVED). Sanitized rows: `phase113_prod_deployments.json`.

Final homepage, health, readiness and monitor **200/ok**, database connected, no monitoring issues, zero rolling5xx/pool timeouts. Initial and final health bodies persisted. No production failures during synthetic journeys.

Fresh invite-only/hidden/members-only, non-demo org `phase113-release-qa-20261010`, one child, four fictional non-platform-admin accounts, all notification channels disabled. Production helper refused existing fixture collisions; no old phase oneshot, reset or global worker tick. Normal authenticated APIs prepare exact fixtures; owner ballots and manual closure exercised through supported Chrome UI with keyboard controls.

| Production gate | Result |
| --- | --- |
| Five independent method opt-ins/save, default settings | PASS |
| Median-only and trimmed-only creator without dropdown, both-choice keyboard dropdown | PASS |
| Restrictive budget setting preserves both prior drafts; fresh forbidden trimmed request400/no row | PASS |
| Child inherited Allocated K1 invalid/K2 saved/reopened and org-scoped serializer | PASS |
| Election picker K1 excludes Allocated/K2 exposes it; inspected then canceled | PASS |
| All5 ordinary ballots/manual closes | PASS; frozen Rain garden + Library evening |
| All5 office ballots/manual closes | PASS; Ada Fictional + Bea Fictional, moderator assignments |
| All5 exact-ID scoped worker closes | PASS; actual assignments/roles, one audit and staged intent each, retry unchanged |
| All5 selected-set histories, Recorded aggregates keyboard Enter | PASS |
| Desktop and380px results | PASS; mobile document365/365 and table291/291 client/scroll widths |
| Exact Allocated round2 disclosure | PASS; contribution3/2, mass1, allocated1, common fraction1, zero shortfall; aggregate-only |
| Unauthenticated private results/graph | PASS401/403/404; normal API frozen retrieval repeated unchanged |
| Final Score/Bloc captions | PASS final bundle; K1 unchanged by source |

Safe fixture IDs and method-wise outcomes: `phase113_prod_fixture.json`, `phase113_prod_ordinary_results.json`, `phase113_prod_manual_results.json`, `phase113_prod_worker_results.json`, `phase113_prod_inspect_manual.json`, `phase113_prod_worker_worker.json`, `phase113_prod_budget_child.json`, `phase113_prod_browser_qa.json`. Credentials/tokens and private preservation manifest remain scratch and unstaged. No real organization settings/ballots/roles, provider settings, infrastructure, production env vars or secrets changed. No backfill, so no backfill output.

Screenshot directory: `C:/Users/zachk/.codex/visualizations/2026/10/10/01a12685-aa74-77f2-a3b0-10578f2470d3/`. Per-method office/ordinary mobile results, desktop settings, budget choices, child, election picker and exact-band captures listed in browser JSON. Supported Chrome screenshot raster occasionally lagged responsive layout; separate viewport/state/capture corrected it. Full-page capture timed out, so viewport captures used. Browser viewport restored. All-five history disclosure functionality verified; exact-band screenshot on Allocated. Routine copy fix additionally PASS-by-source.

## Performance and limits

Evidence: `phase113_counter_benchmarks.json` (40 cases), `phase113_counter_stress.json` (5 heterogeneous-weight cases), `phase113_pg_benchmarks.json` (5 untraced loads +1 Allocated memory-traced load). Pure counters make **zero SQL queries**, never expand represented shares. At120 options/K120: dense Bloc worst10.69s/~11.97MB counter peak/1.30MB JSON; RP largest1.62MB JSON; random Allocated2.09s/~11.56MB/782,850-byte JSON. Heterogeneous original weights1..1e12 make exact Allocated4.89s/~18.36MB/7,522,167-byte JSON (3,024,338 gzip), max denominator3,497 bits. Counter peaks exclude prebuilt input. Traces are bounded by120 options/seats; no truncation, approximation or lowered cap introduced. These remain material worst-case costs.

All six disposable PG loads pass40/40 concurrent operations with1,000 members/100-node delegated graph, pool peak5/5, zero leaks/waiting locks/idle transactions. Tally/snapshot query counts remain13/12 independent of K, matching Phase109; votes usually23 vs prior21 due to frozen-rule/option checks. Untraced result p95: Score735ms, Bloc1,050ms, MJ980ms, RP1,283ms, Allocated941ms. Allocated traced peak16,885,893 bytes,20.62sec; tracing latency kept separate. Prior Phase109 single STAR p95912ms/peak13,022,999 bytes is directional cross-run evidence, not isolated scaling. Benchmarks ran alongside test workloads; exact seeded inputs and tie commitments retained per case.

## Files, commits, remaining debt

Application/spec/evidence inventory: `phase113_changed_files.txt`; pre-closeout exact commit inventory: `phase113_commits.txt`. Final closeout adds this file, inventories, production/preservation JSON, PROGRESS status and completed spec/execution status. Explicit staging excludes all scratch, credential files, reference packages/PDF, logs and generated historical audit sample. Worktree remains available for review; owned local8002/5174 development servers are stopped at final closeout. No background automation was created.

Remaining existing debt: lint errors, chunk-size/Browserslist warnings, unchanged locked npm audit14 findings (1 low/3 moderate/10 high), settings-underlay24px mobile overflow, non-durable immediate email delivery. New documented cost: maximum-capacity repeated Bloc latency and heterogeneous exact Allocated trace size above. Verification-pending installation still requires a later authorized action; no new automatic install after verification. Per-title scheduled-method configuration is **NOT STARTED**, scheduled generation remains ranked choice. Primary reconciliation is **NOT STARTED** with exact dispatch above. No unresolved application gate; primary gap is reported separately from the production-complete pass.
