# Phase 109 frontend verification

## W0

Commit `5955428`: 82 Node tests pass, including five registry/default contracts.
Changed-file ESLint and diff checks pass. All experimental availability gates
were false at this stage.

## W1 STAR, local rendered gate passed

Implementation `4086e61` adds the ballot, results, opt-in controls, create/edit
paths, write-in controls, history, profile summaries and method help. STAR's
frontend release gate is enabled only after the backend core integration
tests passed; Score, Ranked Pairs and Majority Judgment remain unavailable.

92 Node tests pass, including four payload/numeric tests and four tests of
actual React-rendered components via Vite SSR. These cover immutable result
labels, runoff winner versus score leader, exact large counts, tie disclosure,
neutral versus abstention ballots, no-meaningful-result presentation, scoped
destructive-change authorization, and unchanged option-list preservation.
SSR does **not** substitute for interactive browser verification.

Production build passes with the pre-existing large bundle warning. New files
pass ESLint. Changed legacy files retain eight pre-existing
`react-hooks/set-state-in-effect` errors and one existing dependency warning;
linting their source from `5955428` reproduces every finding. No new lint
finding was introduced.

### Earlier interactive browser blocker (resolved)

Chrome via `mcp__cua_repl` successfully opened the isolated local login page at
`http://localhost:5173/login`. The page exposed username/password controls and
Sign In. The synthetic fixture credentials were entered and Sign In clicked.
The following observation failed with "Detached while handling command".
After reading the documented browser troubleshooting guidance, the next
accessibility observation explicitly reported:

> Google Chrome is blocking automation because another extension UI is open
> on this page. Complete or dismiss that extension UI in Google Chrome, then
> ask me to continue.

No bypass, unrelated control mechanism, alternate browser, screenshot claim,
or successful login/ballot journey is claimed. The parent lead was informed.
Desktop, 380px, keyboard submit/change/retract, delegation, late write-in,
closure and rendered results remain **NOT VERIFIED**. W2 must not begin until
the W1 gate is satisfied.

### Recheck, 2026-10-08

The previous ephemeral tab had expired. A replacement tab in the same approved
Chrome extension browser opened the local login page successfully. Filling the
synthetic fixture login then reading accessibility state produced the same
explicit extension-UI block quoted above. Sign In was not submitted during
this recheck. No alternate browser or control mechanism was attempted.
At that recheck, the interactive gate remained BLOCKED and ballot journeys
were NOT VERIFIED. The later successful lead verification below supersedes it.

Current frontend: 92 tests pass (rerun after profile-summary integration).
Production build passes at commit `a88646b`, JavaScript `index-DRsQa-g0.js`.
The three profile surfaces render the backend privacy-filtered `ballot_summary`
with legacy vote-value fallbacks; that display mapping is PASS-by-source.

### W1 successful browser verification, reported by the implementation lead

Z dismissed the Bitwarden save-password popup. The implementation lead kept
the authenticated Chrome tab because sign-in did not carry to a new tab and
the tool does not permit two agents to own one browser tab. The frontend
agent did not perform or claim these successful browser interactions.

The lead reported PASS for desktop and approximately 380px mobile, keyboard
rating selection and focus, cast/change/retract, delegation/direct override,
explicit abstention, late write-in omission, manual close and finalized seed
reveal. Exactly one full results panel is visible per viewport after the
network-summary correction. Browser verification also caught and verified
fixes for hidden early-result refresh (an expected aggregate 404 must not
hide the submitted neutral direct ballot) and the actual frozen close date.

Evidence supplied by the lead in `test_results/phase109/`:
- `star-mobile-ballot.jpg`
- `star-final-desktop.jpg`
- `star-final-corrected-date.jpg`
- `star-early-private.jpg`

The W1 frontend finished at 97 passing Node tests with build
`index-CSHkOgul.js`. This local gate does not claim production verification.

## W2 Score, local rendered gate passed

Shared 0–5 ballot controls use explicit Score context and point labels. Score
results show exact total points, highest-total ties, participation and the
committed draw disclosure, with no STAR finalist or runoff fields. The
optional average is omitted. Create/edit/import/sub-org, opt-in controls,
write-ins, early visibility, profile summaries, help and snapshot history
use method-appropriate labels. The existing disabled-by-default contract is
preserved. The successful lead browser verification below supersedes the initial pending state.


W2 automated verification: 102 Node tests pass, including the STAR/Score
counterexample display, large exact tied totals, Score omission/neutral/abstain
copy and payloads, independent opt-in and draft reset, and method-appropriate
network fallback. Production build passes (`index-0UkVHK0t.js`). New files and
changed admin/settings/help/ballot/graph files pass ESLint; the legacy detail,
profile and history hook findings remain the previously recorded baseline.
Score frontend availability is enabled after the lead confirmed the backend
Score handlers and focused API tests passed. Ranked Pairs and Majority
Judgment remain unavailable.

The strictly local `backend/scripts/phase109_score_localqa.py` creates
idempotent Score voting and early-voting fixtures with the existing synthetic
delegate's ballot. It refuses any database other than the exact adjacent
`phase109_localqa.db`, preserves existing proposals/ballots and only enables
STAR/Score in the synthetic `phase109-qa` organization. The lead owns browser
verification of these fixtures.


### W2 successful browser verification, reported by the implementation lead

The lead reported PASS for desktop and approximately 380px mobile points
ballots, delegate override, cast/re-vote, late-option zero, abstain/retract
restoring the delegate, neutral early ballot with immediate refresh and
hidden aggregates, and admin close with final rule/seed/actual date.
Evidence in `test_results/phase109/`: `score-mobile-ballot.jpg`,
`score-early-private.jpg`, `score-final-desktop.jpg`. The lead owned the
signed-in browser tab; the frontend agent did not perform those interactions.

## W3 Ranked Pairs, local rendered gate passed

Native rank-group menus and Move up/down controls support equal ranks and
incomplete ballots without dragging. A group change is not a submission;
neutral empty ranks, explicit abstention, direct override and retraction
retain their distinct semantics. Late write-ins remain unranked-last.

Results include exact pairwise preferences, ordered victories, locked edges,
skipped cycle edges, source candidates, winner, and priority dependence.
History uses head-to-head margins/support and locking detail, with no
first-choice/IRV chart. Authoring/settings/sub-org/import, write-ins, privacy,
profiles, help and closure display recognize Ranked Pairs. Majority Judgment
remains unavailable. Ranked Pairs frontend availability was enabled only
after the backend agent confirmed handlers and focused tests passed.

Automated verification: 110 frontend tests pass. New and changed
admin/help/graph files pass ESLint; legacy detail/profile/history hook
findings retain the previously recorded baseline. Build passes with bundle
`index-BlnTYkUn.js`. New tests cover equal/incomplete/neutral payloads,
malformed/stale ranks, native labels/buttons, cycles, exact large counts,
priority disclosure, history and independent opt-in/election rejection.

`backend/scripts/phase109_ranked_pairs_localqa.py` creates idempotent fixtures
only in the exact adjacent local SQLite database, preserving prior ballots
and statuses. The voting fixture is `261209e6-066c-4207-ae60-489ddcc9f452` and
the early fixture is `f365883c-6dec-44a9-8347-e03804705800`. Both share the
existing synthetic topic and delegate. The later successful lead verification below supersedes the initial pending state.


### W3 successful browser verification, reported by the implementation lead

The lead reported PASS for desktop and approximately 380px mobile, keyboard
tie-group selection, Move up, late write-in, re-vote, abstain, retract restoring
delegation, neutral private early ballot, and close with frozen winner/seed.
Evidence in `test_results/phase109/`: `ranked-pairs-mobile-ballot.jpg`,
`ranked-pairs-early-private.jpg`, `ranked-pairs-final-desktop.jpg`.
The lead owned the browser; the frontend agent did not perform these steps.

## W4 Majority Judgment, local rendered gate passed

The shared rating controls now support six verbal grades: Reject, Poor,
Acceptable, Good, Very good, Excellent. Grade codes are transport identifiers;
the UI presents no point sum or numeric grade average. The ballot preserves
explicit Reject versus omitted entries, neutral empty maps, and abstention.
Mobile grade controls use two columns and wider layouts three columns.

Results show original majority grades and accessible stacked distributions,
exact grade frequencies, lower-median rules, repeated-median comparison
steps and final draw disclosure. Histogram ratios use BigInt counts before
converting only the bounded display fraction. History preserves the same
original distributions and verbal labels. Settings, authoring/import,
sub-orgs, write-ins, preliminary visibility, summaries, graph fallback and
help recognize Majority Judgment. Source availability was enabled after
backend handlers and focused API tests passed; organization opt-in remains
independent and defaults remain unchanged.

119 frontend tests pass, including all preceding method tests and new
grade payload/labels, neutral/late/abstain, median-vs-mean, original tie
distributions, exact large counts, native grade controls, history, and
independent opt-in tests. New and changed admin/help/graph/ballot files pass
ESLint. The three previously documented legacy hook files retain baseline
findings. Production build passes: `index-DXSMnm4T.js`. SSR tests disable
unused Vite WebSocket servers to avoid port collisions between test files.

The idempotent `backend/scripts/phase109_majority_judgment_localqa.py` creates
fixtures only in the exact local SQLite test database, preserving prior
ballots/statuses. Voting: `1f2506dc-ee6d-483b-ae81-d867a7a81065`; early:
`e978e4f0-e5ad-4265-a766-4c8193d411d2`. The existing delegate has Playground
Excellent, Community center Acceptable, Parking Reject. The later successful lead verification below supersedes the initial pending state.


### W4 successful browser verification, reported by the implementation lead

The lead reported PASS for desktop and approximately 380px mobile, verbal
grade selection by keyboard, cast/change, late write-in Reject, abstain,
retract restoring delegation, neutral private early ballot, and close with
frozen majority grades/distributions/winner/seed. Evidence in
`test_results/phase109/`: `majority-judgment-mobile-ballot.jpg`,
`majority-judgment-early-private.jpg`, `majority-judgment-final-desktop.jpg`.
The lead owned the browser; the frontend agent did not perform these steps.

## W5 frontend integration review

Reviewed all four methods across opt-in/defaults, global/election exclusions,
sub-org authoring, independent payloads, preliminary visibility, neutral versus
abstention, late options, result units, frozen labels/date/result handling,
profiles, admin/import labels, graph fallback, and history.

Fixed an integration issue: archiving an already-finalized proposal must not
relabel its recorded winner as provisional. All four result panels now honor
the server's frozen `finalized` flag; the archive banner explains that the
final result is preserved. Four rendered regression cases cover this.
Cleared optional graph state at initial refetch so a failed reload cannot
retain an older graph. Cleaned method labels in admin/import summaries and
Majority Judgment grade/abstention copy. These are source-reviewed display
and state fixes; no new interaction is claimed.

Final frontend checks: **123 tests passed**, production build passed,
`index-C2fK2G26.js` with `index-DQcWNiPm.css`. The existing large bundle and
stale Browserslist-data warnings remain. Changed JavaScript lint found
**10 errors and 1 warning**, all reproduced from baseline `0096997`:

- `SupportTrajectoryChart.jsx`: 1 existing set-state-in-effect finding.
- `ProposalDetail.jsx`: 6 existing set-state-in-effect findings and 1
  exhaustive-deps warning.
- `UserProfile.jsx`: 1 existing set-state-in-effect finding.
- `DelegatePublic.jsx`: 1 existing unused import and 1 existing
  set-state-in-effect finding.

The earlier count of 8 errors/1 warning covered the first three files; the
whole-phase check additionally includes DelegatePublic's two baseline
findings. All other changed/new JavaScript files lint clean, including the
new final-result regression. Diff whitespace checks pass. This records local
verification only; production deployment/sanity remains the lead's W5 gate.


### W5 archive-control follow-up

The lead browser verified the preserved archived winner/banner, then spotted
write-in removal controls reappearing after archive. The controls now use a
shared experimental-method lock that recognizes archived/unresolved states
and the authoritative finalized result flag, preserving legacy behavior.
15 focused method/final-result tests pass, including the new four-method
archive/early-state boundary regression; helper/test lint passes. Build:
`index-BYrMsS6k.js`. The full suite was not repeated for this bounded follow-up
(previous full 123 passed; one additional regression is now present).
