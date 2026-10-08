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

## W2 Score, in progress

Shared 0–5 ballot controls use explicit Score context and point labels. Score
results show exact total points, highest-total ties, participation and the
committed draw disclosure, with no STAR finalist or runoff fields. The
optional average is omitted. Create/edit/import/sub-org, opt-in controls,
write-ins, early visibility, profile summaries, help and snapshot history
use method-appropriate labels. The existing disabled-by-default contract is
preserved. W2 rendered browser verification is pending.


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
