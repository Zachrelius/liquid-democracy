# Phase 110 — Voting method explanations and single-winner officeholder elections

Status: COMPLETE AND PRODUCTION VERIFIED, October 10, 2026. Z authorized execution; A shipped and production-passed before B implementation. B supports single-winner officeholder elections. Multiwinner extensions remain NOT STARTED.

## Goal and dispatch

Make voting-method choices understandable, then enable STAR, Score, Ranked Pairs and Majority Judgment for elections selecting one officeholder. Z authorized implementation, tests, normal no-ff integration and deployment through the verification gates below. Dispatch: `Read and execute phase110_voting_method_clarity_and_elections_spec.md`.

Read this document fully, then PROGRESS.md and applicable AGENTS.md. Planning reviewed Phase 109's final integration `8144069`; its release and production verification are complete. Fetch origin/master and reconcile newer work before implementation. The original checkout C:/Users/zachk/Liquid-Democracy is old and dirty: never reset, clean, broadly stage or overwrite it. Copy this spec into an isolated implementation checkout and commit it before code changes.

## Branch, team and sequence

Use one branch `phase-110/voting-method-clarity-and-elections` from current origin/master. Use a visible project task for the implementation lead: Z wants progress and final reports visible. This bounded pass may be executed by one full-stack lead with explicit review/QA stages. Substantial delegated work must use visible project tasks, not hidden long-running subagents. Do not create duplicate owners of one checkout.

A is a small independently deployable slice. Complete its focused checks, no-ff merge, deploy and production check before starting B application changes. B then continues on the phase branch reconciled with the first merge, with its own full gates and verified release. Do not delay A for B. Normal Railway deploys are authorized; destructive production operations, secret/infrastructure changes and unrelated refactors are not. No real org settings, elections or office assignments may be altered for QA.

## Verification matrix

| Check | Required | Notes |
| --- | --- | --- |
| A copy and scope review | Yes | Exact approved text below; no defaults, permissions or tally changes |
| A frontend build and relevant existing tests | Yes | Add interaction tests for new disclosure/shared settings behavior, not tests that merely repeat prose |
| A rendered desktop/mobile/keyboard QA | Yes | Unified list, labels, toggles, disclosure and saved settings; parent/sub-org inheritance |
| A production deploy check | Yes | Changed frontend bundle, successful deployment, page sanity; backend may legitimately skip frontend-only changes |
| B four-method election matrix | Yes | Creation, candidacy, voting, result, installation and rejection paths for every method |
| B manual and worker close parity | Yes | Both proposal advance routes and scoped worker close; same frozen winner and seat outcome |
| B authorization and eligibility | Yes | Org/sub-org isolation, method disabled, election disabled, trigger permissions, title rules, role/verification floors |
| B transaction/retry/concurrency | Yes | PostgreSQL close race and injected failures; no partial role changes, redraws or duplicate side effects |
| B legacy regressions | Yes | Binary/approval/RCV elections, scheduled elections, ordinary Phase 109 proposals and multiwinner behavior unchanged |
| B backend full suite | Yes | Focused suites first; actual pass/skip counts and delta from current baseline |
| B frontend tests/lint/build | Yes | Report pre-existing lint debt separately; no new findings |
| Schema/serializer round trip | If fields added | All create/edit/service/seed paths, OrgOut allow-list for FE-facing organization fields |
| SQLite migration cycle and PG migration smoke | If migration added | Reversible migration, verify prior head (reviewed a109b0c1d2e3), use repository smoke script |
| B production API and browser QA | Yes | Synthetic private org/accounts, each method ballot-to-office result; desktop/mobile/keyboard; scoped worker test |
| Final deployment and closeout | Yes | Exact backend SHA/deployment and health/readiness/monitor; frontend bundle; docs and remaining limitations |

Use available supported Chrome browser tooling. Missing tooling is a reported verification blocker, not a source-review substitute. Do not re-run expensive suites without a new change or unresolved concern. No migration is expected; if none is added, explicitly report PG migration smoke not required, while still running PG transaction/concurrency checks.

## Locked scope

- All current method defaults remain unchanged. Binary remains always enabled. Four Phase 109 methods remain independently configurable and off by default for fresh organizations.
- Keep one method list: binary, approval, ranked choice, budget allocation, budget projects, STAR, Score, Ranked Pairs, Majority Judgment. Existing defaults first, new methods afterward. No separate “Optional voting methods” section.
- B supports elections choosing exactly one officeholder, including one vacancy of a multi-holder title when existing capacity/slate rules permit. It does not enable multiwinner counting for the four methods.
- Preserve the Phase 109 counting algorithms, scales, tie commitments, weighting, delegation, privacy and immutable result contracts. Do not implement new numerical or verbal scales.
- Scheduled election generation currently hardcodes ranked_choice. Preserve that default; adding a per-title scheduled-method setting is outside this pass. Existing configurable admin-direct and member-cosign election paths must accept the four methods under the same permissions. Shared service validation must prevent bypasses.
- Preserve existing nomination windows and candidate eligibility. Ordinary free-text proposal write-ins must not become a way to nominate an arbitrary person or grant a role. This does not tighten ordinary-proposal write-in policy.
- Multiwinner variants and their proportionality goals remain a later research/spec phase, NOT STARTED here.

## A — Wording and consistent presentation

Review OrgSettings.jsx, SubOrgSettings.jsx, voting-method help and proposal/election method selectors. Use shared text where it avoids drift. Show the full approved descriptions in org/sub-org settings and the help page; compact selectors can link to the same help rather than repeat long text. Do not widen scope to rewrite unrelated proposal-type help. Preserve inherited/locked controls and existing save semantics. A unified visual list must not accidentally make inherited choices editable or erase unrelated settings.

Each row has its checkbox, method name and description underneath, consistently styled and sufficiently contrasted. No hover-only explanation. Majority Judgment gets an accessible expandable “How are grades counted?” section usable by keyboard and touch, with aria-expanded/focus behavior or native details/summary. Group descriptive text with the correct input accessible name/description. Verify at about 380px width.

### Approved short descriptions

**Binary (Yes / No / Abstain)**
Vote for or against a proposal, or abstain. Always enabled.

**Approval Voting**
Approve as many options as you find acceptable. Each approval counts equally, and the option with the most approvals wins. For multiple winners, the highest-supported options fill the available places.

Qualification for this existing text: the platform supports configurable approval thresholds and seat rules. Verify the current implementation; if this short description overstates those configurations, use “For multiple winners, options are selected by approval totals and the proposal’s selection rules.” Do not promise a top-N result for threshold configurations. “Equally” refers to approvals within a ballot; weighted organizations still use their configured voting weights.

**Ranked Choice (IRV / STV)**
Rank options in preference order. For one winner, the lowest-supported option is eliminated each round, and those votes move to each voter’s next remaining choice. For multiple winners, votes transfer from eliminated options and surplus votes transfer from elected options to fill the available places proportionally.

**Budget — Allocation (split a pool)**
Suggest how to divide a budget among spending categories. The system combines voters’ allocations into a shared budget, respecting the available funds and category limits.

**Budget — Projects (choose projects to fund)**
Rank projects in funding priority order. The system combines voters’ priorities and funds projects in the resulting order, subject to their costs and the proposal’s spending rules. Projects can offer different funding levels.

**STAR Voting**
Rate each option from 0 to 5. The two options with the highest total scores enter an automatic runoff. Whichever finalist more voters rated higher wins; equal ratings count for neither finalist in the runoff.

**Score Voting**
Rate each option from 0 to 5. The option with the highest total score wins. Every point counts toward the result, with no runoff.

**Ranked Pairs**
Rank options in preference order, allowing ties. The system compares every pair of options. An option preferred over every other option wins; otherwise, it builds an ordering from the strongest victories first, skipping any that would create a circular result.

**Majority Judgment**
Grade each option from Reject to Excellent. The option with the highest middle grade—the median—wins, rather than the highest average. If options share the same middle grade, the system compares their remaining grades to break the tie.

### Majority Judgment expanded explanation

Imagine an option receives these five grades: Reject, Acceptable, **Good**, Very good, Excellent. Its middle grade is **Good**. With an even number of grades, the lower of the two middle grades is used.

When options tie, the system temporarily removes one middle grade from each tied option and compares their new middle grades, repeating as needed. The original ballots remain unchanged. If the grades still cannot distinguish the options, the recorded tie-breaking order decides the result.

**Why words instead of numbers?** These labels express how you judge each option. Their order matters, but they aren’t points to add or average. Majority Judgment compares middle grades; Score and STAR add numerical ratings.

Explain in shared help that all these descriptions use equal voter weights for simplicity; when weighted voting applies, each ballot counts with its represented voting weight, including grade frequencies and head-to-head comparisons. Avoid suggesting that words mathematically prevent numerical encoding or guarantee identical interpretation among voters. They communicate ordered judgments. Design background: Balinski and Laraki, https://www.rangevoting.org/BalinskiLarakiPNASpdf.pdf.

### Shared footer and staged eligibility text

Both releases: “Enabling a method makes it available for new proposals. Disabling it does not affect existing proposals.”

A only: “STAR, Score, Ranked Pairs, and Majority Judgment currently support single-winner proposals, excluding officeholder elections.”

B, only once support is implemented: “STAR, Score, Ranked Pairs, and Majority Judgment support single-winner proposals and single-winner officeholder elections.”

Keep truthful eligibility copy on all relevant surfaces. Do not remove the A restriction before the backend can fulfill the promise.

## B — Election integration

### Source map and hazards

Reviewed sources: backend/routes/elections.py (OpenElectionRequest, open_election allow-list), backend/elections.py (finalize_election, election_close_status, run_election_close_hook, _resolve_winners, _apply_election_winner, schedule generator), backend/experimental_voting.py (initialize_rules currently rejects is_election; finalize_result assumes ordinary proposal outcomes), backend/proposal_lifecycle.py (lock_election_candidate_options, common close), routes/proposals.py and routes/organizations.py, sustained_majority_worker.py, schemas.py, voting_methods.py, delegation_engine.py. Frontend election controls are in components/OrgTitlesPanel.jsx and ElectionBadge.jsx, with shared proposal ballots/results.

Current candidate options store candidate user_id in option.label and display name in description. Explicitly preserve identity mapping; never map by editable display name. Phase 109 results freeze option labels, so adapt election presentation to human-readable candidate names without breaking canonical user/option identity or leaking private ballots.

Legacy _resolve_winners can choose the first declared candidate after a tally failure or empty result. election_close_status treats quorum exceptions as success, and run_election_close_hook catches assignment failures after close. New methods MUST NOT enter these fallback paths. Scope any safety refactor carefully and test legacy behavior rather than silently changing it.

### Creation and capability contract

1. Server accepts each new method only when effective organization/sub-org settings enable it, elections and trigger are enabled, title is electable and exactly one winner is requested. Reject incompatible approval-winner/budget/multiwinner configuration, including forged API requests. Preserve existing role/identity/cosign permissions and capacity checks.
2. Initialize server-owned versioned rules and seed before any ballot, with the same pre-close seed secrecy as ordinary proposals. Draft edits, generic creates/imports and service helpers cannot bypass capability gates or forge election links. Client-provided seeds/final results remain forbidden.
3. Disabling a method after an election is created does not strand that existing election; block new creation only under established Phase 109 policy.
4. Election selector offers enabled new methods only for a one-winner election. Changing winner count to more than one must explicitly require a compatible method; never silently convert stored ballots. Keep legacy/default ranked choice unchanged.

### Candidate and ballot lifecycle

Use the existing authorized candidacy workflow and voting-open candidate lock. Cover zero, one, two and three-plus candidates. Preserve existing early-voting restrictions specific to elections; do not invent free-text election write-ins or broaden nomination windows. Any supported candidate change must use the same proposal lock as vote/close and correctly invalidate live stability; reject changes disallowed by the nomination policy. Reuse Phase 109 omission behavior where late authorized options are supported.

Reuse exact ballots/results for the four methods, including whole-ballot delegation, direct override, explicit abstention, retraction, represented-member weight, quorum units and early/private-result gating. Election candidate labels must be readable in ballots, results, history and announcements.

### Result and office assignment contract

- For contested elections, compute a single authoritative tally and persist its method result and the election outcome in the same transaction. Map its sole winning option to the corresponding eligible candidate account. Do not recount after installing the winner or changing membership/roles.
- Preserve existing quorum behavior, including explicit quorum=0. A contested election with no meaningful preference (no non-abstaining positive weight, all-bottom ratings, or no strict Ranked Pairs preference) installs nobody. Record the reason; no first-declared fallback. Unmet quorum never changes officeholders.
- Preserve the existing uncontested election policy: one eligible candidate may win without a competitive tally if quorum is met. This is an explicit election policy exception to the ordinary-proposal two-option requirement, not a fabricated method winner. Zero candidates produces the existing no-election/holdover outcome. Persist and display these reasons consistently alongside the frozen result; do not pretend a runoff happened.
- Apply current title capacity, fill_vacancies/refresh_slate, elected-revert opt-in, membership, active-user, bound-role and verification policies. Never silently choose a runner-up if the winner cannot be seated. Existing verified-title/pending-role behavior may remain where deliberately supported; clearly record it.
- Validate/preflight assignment before destructive slate changes. Expected policy rejection must produce an explicit installation outcome with existing seats and roles intact. Unexpected tally, mapping, persistence or assignment exceptions must roll back the entire close so it is retryable, with no frozen successful result or partial grant/revoke. Do not swallow exceptions and mark a successful election.
- Distinguish the counting winner from office installation state in API and UI; a finalized winner who is pending verification is not falsely advertised as having received privileged access. Preserve existing status conventions where possible, with explicit reason/outcome metadata for the new path.
- Rule/seed, frozen tally, candidate identity/display snapshot, close status, assignment outcome, audit and notification intent must agree. Closing twice, retries and simultaneous manual/worker closes must not duplicate title grants, role transitions, schedules or notifications. Use database-backed locking and current transaction helpers. Preserve schedule cadence where applicable, without adding scheduled-method configuration.
- Tie resolution remains Phase 109's reproducible algorithm-specific procedure and committed priority, never expand-winners or declaration order. A live arbitrary-priority-dependent result remains unstable for early closing; deadlines/extension caps still terminate normally.

### Test acceptance examples

For each method create an enabled private org election with three candidate accounts, cast independently hand-calculated ballots, close and assert the EXACT candidate receives the title (and the correct bound-role effect where applicable), not just an HTTP success. Include at least one profile where the first declared candidate loses. Check manual generic/org close and scoped worker parity.

Parameterize disabled methods, election opt-out, cross-org candidates, invalid winner counts, missing rules, malformed ballot, quorum failure, zero ballots, abstain-only, all-bottom/equal ranks, deterministic ties, one candidate, zero candidates, withdraw/inactive candidate handling. Assert real database side effects and immutable results after later membership/weight/name changes. Exercise at least one actual bound-role transition and a verification-floor case; cover custom titles plus one-seat vacancy/capacity and refresh-slate behavior.

Inject failures after candidate resolution and during assignment/audit staging; prove rollback leaves current holders untouched and retry succeeds once. Use production-shaped sessions (autoflush=False), real model ballot JSON, and PG concurrent close tests. Retain references/counting tests from Phase 109; changing counting algorithms is not necessary.

## Operational QA and closeout

Use isolated synthetic local/production organizations and fictional accounts with outbound notifications disabled. Production role tests must be confined to those organizations and never create platform admins. Do not reuse one-shot Phase 109 bootstrap/API drivers or invoke a global worker tick. Create scoped, auditable fixtures for this phase; do not print credentials. Reuse authenticated browser sessions where appropriate. If a password manager blocks automation, request the specific user interaction rather than blind keystrokes.

At each release record branch/merge SHAs, Railway deployment IDs and exact commit, bundle, health and rendered evidence. At final closeout update this spec, PROGRESS.md and a concise docs/phase110_closeout.md with A/B status, tests/count deltas/skips, no-migration statement or smoke evidence, changed files, side-effect and rollback checks, deployment evidence and remaining debt. Do not mark incomplete production gates as done. Multiwinner variants and scheduled-method configuration remain NOT STARTED, not an implicit background promise.


## Execution evidence — October 10, 2026

A release `bfbd017` production-passed before B. B no-ff release `c7f1963` has exact successful backend/frontend deployments and live `index-CpFpIu6F.js`; health/readiness/monitor 200/ok, no issues. All four Chrome ballot-to-office paths, both manual routes and four scoped production worker closes installed the exact second-declared fictional candidate in the private QA org. Desktop/380px/keyboard and selector compatibility checks PASS. No real org changes, global worker tick or notification delivery. Backend 3,776 core passing cases (+167), with initial full-run development-flag failures explicitly resolved by complete normal-configuration suite reruns; optional STAR oracle also passed. Frontend 135 passed (+11), build PASS, no new lint findings. Disposable PG16: 16 race/rollback checks PASS. No migration, PG migration smoke not required. Full raw counts, artifacts, SHA/deployment IDs, scope and remaining debt: `docs/phase110_closeout.md`. Scheduled-method configuration and multiwinner variants remain NOT STARTED; no background follow-up created.
