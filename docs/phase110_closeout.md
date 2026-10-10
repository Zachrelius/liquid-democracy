# Phase 110 execution and closeout

Status: A DONE and B DONE. Both sequential releases production verified.

Baseline: refreshed origin/master `81440693b1fed153e66a7127093b6d8ba24e3f10`.
Isolated branch: `phase-110/voting-method-clarity-and-elections`; spec commit `1dc2407`.
Original dirty root checkout preserved.

## A verification

- Approved descriptions shared across organization settings, sub-organization settings and help. Nine methods in legacy-first order; approval uses the qualified threshold/selection-rule text after source review of `_select_approval_winners`.
- Native keyboard/touch Majority Judgment disclosure; labels and descriptions linked to each checkbox. A election exclusion remains truthful.
- Full frontend suite: 124 -> 129 PASS (+5); no failures/skips. Five new checks cover inherited lock, future-choice preservation, binary lock, label/description linkage and native disclosure.
- Corrected final build PASS: `index-DOlyVHds.js`, CSS `index-DQcWNiPm.css`; existing large-bundle and Browserslist warnings.
- Changed-file lint: shared/new modules clean. Existing OrgTitlesPanel effect/unused-handler errors confirmed by baseline source and lint comparison. No new lint findings.
- Local Chrome: desktop and 380px; keyboard Enter/focus and click disclosure; toggle/save/reload; child inherit lock; override/save/reload; reset-to-inherit. SQLite read verified unrelated parent verification policy and child privacy retained. No production data used for local QA.
- QA caught and corrected one UTF-8 explanation defect. New method rows fit 380px; the existing full settings page has 24px horizontal overflow outside this slice.
- Local captures: `test_results/phase110/phase110-a-local-*.jpg`.
- No schema/model/default/permission/tally change or migration. PG migration smoke not required for A.

A and B production evidence is recorded below.

## A release/production evidence

No-ff release `bfbd01712c0c5e9fc0fba09702888139d60abbd1`; implementation `be3ea7c`.
Railway frontend `92274f88-4281-4557-912f-14d2f2c71d75` SUCCESS for exact release.
Backend `d6d7300b-6ede-4e3b-949d-86785dc67e7c` SKIPPED (frontend-only watched paths).
Live https://www.liquiddemocracy.us/ serves `index-DOlyVHds.js`; health/readiness HTTP 200/ok.
Production Chrome reused the synthetic non-platform-admin Phase 109 owner session for read-only settings QA. New nine-row order and truthful A eligibility verified; Enter/Space focus and click disclosure PASS at desktop and 380px. Public help displays shared approved text and weights explanation. Old service-worker shell refreshed to the verified new bundle on second reload. No production settings were changed and no Phase 109 bootstrap/API driver was invoked.
Captures: `test_results/phase110/phase110-a-prod-{desktop,mobile}.jpg`.


## B implementation and pre-release verification

B DONE: application, focused/local, full regression with resolved runner-flag reruns, and production gates complete.

- Four Phase 109 methods reuse their existing ballots, delegation, represented weights, quorum, counting algorithms and committed tie rules for exactly one officeholder. Creation and shared rules initialization enforce effective method settings, title/org identity, trigger/role authorization and compatible configuration. Candidate mutations lock the proposal and use authorized nominations; election pre-voting and generic write-ins are blocked for the new path.
- A frozen candidate identity/display snapshot maps the sole counted option to the actual account. Uncontested/no-candidate/quorum/no-meaningful-preference outcomes are explicit, with no legacy first-candidate fallback. Counting winner and installation state remain separate. Ballots/results/history/notification intents use human names while canonical candidate IDs remain intact.
- Installation locks organization/title/member state and preflights eligibility, capacity, verification and governance floors. Expected rejection preserves incumbents and roles via a savepoint; unexpected failures roll back the whole close. Verification-pending winners receive no title/privileged role and require a later authorized role/title action; this phase does not add automatic post-verification installation.
- Review corrected the council-revert preflight: an explicitly authorized sole-admin promotion to steward must not be rejected as a forbidden demotion. Eight cases verify all four methods with opt-in allowed/denied and exact role/mode/audit effects.
- Manual generic, manual org and scoped worker closes freeze the same result and install the same second-declared candidate. PostgreSQL verification caught missing worker announcement metadata; worker close now stages the frozen name and installation message like manual close.
- Focused backend: **167 passed** (148 election cases + 19 transaction/release-harness cases). Final write-in guard narrowed to the new methods to preserve legacy behavior; affected four cases rerun PASS.
- Disposable PostgreSQL 16: **16 checks PASS**, using production-shaped autoflush=False sessions. Four methods each pass manual/manual and manual/worker races, injected assignment/audit failures, preserved incumbent/member roles on rollback, one successful retry, exact seat/role, one resolution/status audit and notification, immutable retry and zero checked-out connections. Container removed after verification.
- Frontend: **135 passed**, +11 from baseline (A +5, B +6), no failures/skips. Build PASS: `index-CpFpIu6F.js`, CSS `index-DQcWNiPm.css`. Full lint reproduces **81 errors/7 warnings** on the exact A baseline with the same local toolchain and rule/file/message inventory; current code adds no findings. Existing chunk-size/Browserslist warnings remain.
- Local Chrome: all four human-readable ballots keyboard-cast the second-declared Bea; exact office/moderator effects verified through the API/database. Desktop and actual 380px STAR/Score/Majority Judgment/Ranked Pairs, saved ballots and closed result passed. One-seat selector offers enabled methods; changing to two seats preserves the incompatible selection visibly, disables submission and requires a compatible choice. Modal fits 380px. Captures: `test_results/phase110/phase110-b-local-*.jpg`.
- Local scoped worker helper closed only its four explicit fixture IDs, installed Bea with moderator role, staged one resolution/intent and proved retry no-op. No global worker tick. New additive private production fixture has four fictional non-platform-admin accounts and all outbound channels disabled; production ballot/release evidence is recorded below.
- No model/schema/serializer field or migration added. PostgreSQL migration smoke not required; transaction/concurrency checks above were required and passed. No backfill, real-org changes, infrastructure/secret changes or destructive production operations.
- Multiwinner variants and per-title scheduled-method configuration are **NOT STARTED**. Scheduled generation remains ranked choice. Existing settings-page 24px mobile overflow, baseline lint debt and bundle warnings remain outside this scope.

Final notification presentation review added frozen candidate/installation text to in-app election close notices; ordinary notices retain their existing text. The sixth B frontend regression covers installed, pending and rejected notices. Final frontend tests/build and baseline rule/file/severity/message lint comparison PASS.


Full-regression runner diagnosis (pending final full-run totals): the initial command set DEBUG=true for the local fixture environment. That deliberately bypasses login rate limiting and caused the Phase 38 11th-login assertion to fail; it does not represent an authentication code regression. The single check passed in a normal process, then both complete Phase 38/40 authorization suites passed **43 cases** with the normal limiter active. Optional pinned starvote 2.1.5 reference also passed its **2,000-profile** check separately. Full-run raw totals and resolved distinct-case totals will be recorded explicitly rather than describing the initial command as green.


## B full regression evidence

Initial full command: **3,753 passed / 21 skipped / 4 failed**, 2,991.27 seconds. The command incorrectly retained local DEBUG=true and DISABLE_DIGEST_SCHEDULER=true flags. Failure traces confirm three limiter checks observed the intended development bypass (401 instead of 429, bypass key instead of user key, 201 instead of 429) and one monitoring check observed a deliberately disabled digest worker. No application authentication/monitoring change was made.

Fresh normal-configuration complete suite reruns: Phase 38/40 **43 passed**, Phase 86 **18 passed**, Phase 97 **15 passed** — all four failed cases resolved within **76 passing** cases. The later 19-case harness and final 167-case focused suite separately verified final installation/notification code. Together: **3,776 distinct core passing cases**, **+167** versus 3,609; optional STAR oracle is another passing case and 2,000 synthetic profiles. Initial full-run skips: 17 retired visibility tests, one retired topic-prefix test, optional STAR (now separately passed), Windows symlink and unavailable age-tool tests. No unresolved failure. No second expensive full run was needed after the environment causes were confirmed and all affected complete suites passed.

Frontend final: **135 passed**, +11 versus 124; no new lint findings; build `index-CpFpIu6F.js`. Backend code review, whitespace and tracked Didit-secret assignment guard PASS. Release commits before integration: `aacd709` (B implementation), `0112ec5` (in-app announcement presentation). Production gates passed as recorded below.


## B release and production verification — DONE

- No-ff release **c7f196335a91b7490ca3710c00d1edc231903a4b** pushed to origin/master; phase branch reconciled to it. B commits `aacd709`, `0112ec5`, `93c9b27`; A evidence `fbc76ef` included. Original dirty root checkout preserved.
- Railway backend **1e40a7da-3466-4259-b1a0-4076f8650d0d** and frontend **6e0b2171-b315-4252-b5a7-efb6a137d75e** are **SUCCESS for exact c7f1963**. Live https://www.liquiddemocracy.us/ serves **index-CpFpIu6F.js**, CSS `index-DQcWNiPm.css`. Chrome confirmed this bundle after the old service-worker shell refreshed. No manual deployment or infrastructure/secret changes were needed.
- Final homepage, health, readiness and monitor return **HTTP 200 / ok**, database connected, no monitoring issues, zero rolling 5xx and pool timeouts. Evidence: `prod-deployment-b.json`, `prod-health-final.json`.
- Production private fixture `phase110-release-qa-20261010`: four fictional non-platform-admin accounts, invite-only/hidden/members-only, all notification channels off. Eight elected moderator-bound single-holder titles are confined to this org; a ninth multi-holder title was used only for a canceled picker check. No real organization policies, elections or roles changed. No Phase 109 one-shot drivers or global worker tick invoked.
- **All four browser ballots -> exact officeholder PASS:** three nominees declared Ada/Bea/Cy. Chrome steward ballot selected Bea (second declared); three other synthetic ballots agreed. Hand-calculated final manual outcomes: STAR Bea 20 stars and 4-0 runoff; Score Bea 20 points; Ranked Pairs Bea preferred to both others by all four ballots; Majority Judgment Bea Excellent versus Reject for others. Every method installed exactly Bea, granted moderator, logged one resolution and staged its notification intent. STAR/Ranked Pairs use the generic advance route; Score/Majority Judgment use the org advance route. API and direct PostgreSQL inspection assert actual assignment and role, not just HTTP success. Evidence: `prod-manual-{ids,api-evidence,db-evidence}.json`.
- **Rendered desktop/actual 380px/keyboard PASS:** candidate names throughout active ballots and frozen results; Enter opens/submits, Space selects rating/grade, ArrowDown chooses Ranked Pairs group 1. Editor focus starts on the first candidate control. Submitted ballots persist. Grade/Ranked Pairs mobile document scrollWidth 365 at width 380. All four closed result pages show Bea and explicit completed installation. Worker-closed Majority Judgment is readable and agrees with the database. Captures: `phase110-b-prod-*.jpg`.
- **Selector PASS:** enabled new methods appear only at one seat; changing STAR to two seats leaves it visibly checked/disabled, shows compatibility guidance and disables submit. Resetting to one seat enables submission and keyboard Majority Judgment selection. Mobile modal bounds 16..349 within width 380. Canceled without opening another election. The ordinary settings underlay's known 24px overflow remains outside scope.
- **Scoped worker four-method PASS:** helper validated the exact private org, account/privacy/notification boundary and four explicit method/title/proposal IDs before changing only those deadlines. Three candidate ballots per fixture selected Bea. All four passed with exact Bea title/moderator assignment, one resolution/intent, immutable frozen result and no-op retry. Evidence: `prod-worker-{ids,api-evidence,db-evidence}.json`. No global tick or backfill.
- **Private access PASS:** unauthenticated requests for all four manual fixture proposals return 401 without private content (`prod-privacy-evidence.json`). Local authorization cases additionally cover outsiders, sub-org membership, disabled methods/elections/triggers, title eligibility, governance and verification floors.
- Notification formatter is PASS-by-source plus behavior regression: the new election payload renders frozen candidate/installation text in-app; ordinary notice wording unchanged. Production notifications remain disabled by QA safety policy; disposable PG explicitly verifies emitted notification payload parity and uniqueness.

## Closeout and remaining scope

A copy/layout: DONE. B creation/candidacy/ballots/frozen results/atomic installation: DONE. Transaction, retry and PG concurrency: DONE. Legacy/default/scheduled/multiwinner regression coverage: DONE with the full-run flags and complete normal-configuration reruns explicitly disclosed. Frontend tests/lint/build and production browser/API/worker QA: DONE. No migration; PG migration smoke not required. No backfill output applicable.

Verification-pending installation deliberately grants neither office nor privileged role and does not auto-install after verification; a later authorized title/role action is needed. Existing dense Ranked Pairs capacity cost, lint/bundle warnings and settings-page mobile overflow remain documented debt. Full regression's repeated demo password hashing is slow locally; development bypass/worker-disable flags must be cleared for limiter/monitoring checks. Multiwinner variants and per-title scheduled-method configuration remain **NOT STARTED**; no follow-up automation exists.

The full suite generated changes to the older `test_results/phase8_5_screenshots/session2_audit_log_sample.txt` (writer in `backend/tests/test_sub_org_routes.py`); they are preserved and excluded from this phase. Automatic approval review rejected a restore without proof of disposability; no unreviewed discard occurred. Local fixture helper/Vite proxy, ignored QA credentials/database, collection/lint intermediates and stale failed focused output are also excluded from release.

Commit and complete changed-file inventories are in `docs/phase110_commits.txt` and `docs/phase110_changed_files.txt`.
