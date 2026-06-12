# Phase 67 — Election Close Semantics, Approval-Election UI, Bug Fixes

Z-approved follow-ups from the Phase 66a closeout (2026-06-12). Branch `phase-67/election-ux-and-bug-fixes`.

## Goal / clusters

**W1 — Election close semantics (resolves the under-quorum contradiction). REVISED
2026-06-12 per Z + planning agent — supersedes the force-passed design.** Quorum is made
HONEST: **quorum gates seat installation.** An election that closes under quorum closes as
**failed** and seats NOTHING — incumbents stay, vacancies stay vacant, the org can re-run.
The finalize/seating hook fires only on `passed`, never on `failed`. To keep plurality-of-
those-who-vote as the norm, **elections default to quorum 0** at creation (`open_election`
+ the scheduled/cosign service path set `quorum_threshold=0` unless the caller explicitly
passes one; `_OpenElectionBody` accepts an optional `quorum_threshold`). An org that
deliberately sets a quorum on a leadership election means it. Turnout stays visible:
results retain `quorum_met`/`total_ballots_cast`/`total_eligible`; election results UI
shows a neutral turnout line, and a failed-by-quorum election shows an honest "Quorum not
met — no seats were changed" message. Election banner announces the winner set after a
seated close (fixes the stale "Voting will determine the winner" banner). Both close sites
(route advance + worker natural close) must agree. Audit: failed-by-quorum closes record
that seating was skipped. Future nicety, NOT this pass: optional auto-extend-voting-once
toggle when quorum unmet.

**W2 — Approval elections in the UI.** Replace the `window.prompt` chain in
`OrgTitlesPanel.handleOpenElection` with a proper modal/form: voting method picker
(ranked_choice default / approval), winner-selection control for approval (reuse
`frontend/src/utils/approvalWinnerConfig.js` presets + preview + validation), num_winners
for RCV multi-holder titles (existing semantics), slate mode, deliberation/voting windows.
Sends `voting_method` + `approval_winner_config` to the existing endpoint. No backend change.

**W3 — Election surfaces render display names (66a B1).** Ballot form, options list,
approval-results panel, vote-network legend, leading-options box: for election proposals,
`option.description` (candidate display name) is the primary text; never show the raw
user-id UUID label.

**W4 — Title delete with election history (66a B3).** `DELETE /api/orgs/{slug}/titles/{id}`
500s via FK violation (`proposals.election_title_id`, no ondelete) once any election
referenced the title. Fix: friendly 400 ("This title has election history and can't be
deleted...") mirroring the existing holders-check 400. No schema change.

**W5 — Delegations network 500 (fixed inline by lead).** `routes/delegations.py` read
`Topic.description`, dropped in Phase 58 — AttributeError 500 on every My Delegations load.
Fixed to `Topic.name` (canonical). Backend agent adds the missing regression test: personal
network with a TOPIC-SPECIFIC delegation (the untested path that hid this).

## Invariants
- Non-election proposals' pass/fail semantics untouched (quorum still gates them).
- Elections that seat NO winners (no candidates, engine failure paths) keep today's failure
  behavior — only seated-winner closes flip to passed.
- No migration expected. No phase numbers in user-facing copy.
- Tests grow with surface: side-effect tests for W1 (status after close with/without quorum,
  both close sites), W4 (400 + title row intact), W5 regression.

## Verification bar
- Full suite 0 failures (baseline 2370 passed / 18 skipped).
- Browser-verify on Cedar Hollow: open an APPROVAL election entirely through the new UI,
  full lifecycle to close; display names everywhere; under-quorum election shows passed +
  turnout line + winner announcement; title-delete attempt shows friendly error.
