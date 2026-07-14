# Phase 93 — First Ten Minutes and Empty-Organization Audit

**Status:** Complete and production-verified (2026-07-14)

## Goal

Make the first real pilot experience coherent for both a steward and an invited member. Exercise genuinely empty and zero-history states, fix the highest-confidence onboarding defects found during that rehearsal, and leave browser-backed evidence that a small organization can get from creation to its first decision without needing platform expertise.

## Branch + delivery

- Branch: `phase-93/first-ten-minutes-audit`
- Merge: no-ff to `master` after tests and browser verification pass.
- Railway auto-deploy follows the push to `master`; production verification is required before closeout.
- Do not create disposable organizations, members, invitations, or proposals in production. Use an isolated local database for mutating journey tests and reserve production for non-mutating sanity checks.
- No recurring cost or Railway infrastructure change is authorized by this phase.

## Verification matrix

| Check | Required | Notes |
|---|---:|---|
| Existing verified user creates an organization | Yes | Normal `/orgs/create` path, not only the first-ever platform bootstrap |
| Organization is created exactly once | Yes | Back navigation and retries after creation must not create a duplicate organization |
| Steward creates starter topics | Yes | Partial failure/retry must not duplicate topics that already succeeded |
| Steward invites a member | Yes | Verify the invitation side effect, not only a success response |
| Invited member registers/verifies/joins | Yes | Exercise the real invitation-token journey and friendly expired/reused-token handling |
| Steward can create the first proposal | Yes | Onboarding completion and the empty proposal page provide a direct, permission-aware action |
| Member can cast a first vote and see the result | Yes | Include repeat-vote handling and the no-delegate path |
| Zero-history surfaces render | Yes | Proposals, delegations, notifications, messages, and zero-node visualizations show useful empty states |
| Narrow mobile viewport | Yes | Approximately 380px on the load-bearing onboarding and first-proposal flow |
| Frontend build | Yes | `npm run build` |
| Targeted backend tests | Yes | Invitation/join/proposal/vote side effects and any changed API behavior |
| Browser QA | Yes | Local isolated journey for mutations; production non-mutating sanity after deploy |
| Migration / PostgreSQL smoke | No | No schema change is planned; update this row if diagnosis changes that |

## Sequence

1. Map the actual steward and member routes, including the difference between first-platform bootstrap and later organization creation.
2. Run source-level and automated baseline checks for organization creation, invitations, first proposal, voting, and empty states.
3. Fix the smallest high-confidence blockers and misleading transitions found in that path.
4. Add regression coverage that asserts both API contracts and downstream side effects.
5. Build the frontend and run targeted backend tests.
6. Browser-rehearse the mutating journey against an isolated local database at desktop and narrow mobile width.
7. Merge, deploy, and run non-mutating production sanity before closeout.

## Locked decisions

- The normal post-launch organization-creation journey must receive onboarding help; a wizard that only runs when the entire platform has zero organizations is insufficient.
- Organization creation is a one-time transition. Once the org exists, UI back/retry behavior must not silently submit another org.
- Starter-topic creation must tolerate partial success and retry only unfinished work.
- Onboarding completion must make “create the first proposal” the primary next action for a steward with permission.
- Empty-state copy and actions are permission-aware. Members who cannot create proposals should not be told to use an admin panel.
- Invitation success is not considered tested unless the invitation record/email dispatch path is asserted.
- This phase improves the existing product path; it does not add analytics, a new governance feature, or paid tooling.

## Workstreams

### A — Journey diagnosis

- Document the actual redirect and route behavior for first-ever registration, later zero-org registration, invitation registration, and existing-user organization creation.
- Identify points where users are dropped into a complex admin surface without a clear next action.
- Inventory true empty and zero-history states, including responsive behavior and chart components with no nodes/data.

### B — Steward onboarding fixes

- Make the guided create-org → topics → invites → first-proposal sequence available to ordinary verified users creating a later organization, while preserving the first-platform bootstrap route.
- Prevent backward navigation from recreating an organization after the create step has committed.
- Make starter-topic retry idempotent from the client’s perspective and show accurate progress/failure feedback.
- Keep optional configuration secondary; use safe existing defaults and link stewards to detailed settings after the first-use path.

### C — First-decision and empty-state fixes

- Add a direct first-proposal action to onboarding completion.
- Make the proposals empty state provide that action only when the current user has proposal-create permission; give ordinary members accurate waiting-state copy.
- Fix any reproducible blank, misleading, inaccessible, or overflow state encountered in the journey, staying within first-use scope.

### D — Tests and verification

- Add focused regression tests around changed behavior.
- Reuse existing invitation, registration, proposal, and vote tests where they already prove the full side effect.
- Browser-verify the isolated end-to-end journey and record screenshots/notes in the phase closeout.

## Operational watch-outs

- Local browser QA must use an isolated database and disposable email addresses; do not send real pilot invitations.
- Do not weaken email verification, organization permissions, or invitation-token checks to simplify onboarding.
- Preserve unrelated dirty-worktree files and user-authored untracked documents.
- If a schema migration becomes necessary, stop and amend this spec with the prior revision plus reversible migration and PG smoke requirements before implementing it.
- Cross-browser Safari/Firefox coverage cannot be claimed from a Chromium-only session. Record the available browser evidence honestly and leave a named follow-up if separate engines are unavailable.

## Closeout requirements

- Per-workstream DONE / blocked / scoped-up status.
- Root cause and concrete fix for each defect changed.
- Test count delta and exact frontend/backend verification results.
- Browser evidence for steward creation, invitation/member onboarding, first proposal/vote, empty states, and narrow mobile layout.
- Files changed, commits, branch/merge state, deployed bundle hash, Railway backend deployment evidence, and production sanity.
- No-migration/PG-smoke-not-required statement unless this spec is amended.
- Any deferred cross-browser or broader usability findings added to the roadmap rather than implied complete.

## Local execution evidence — 2026-07-14

- Root cause confirmed: `/setup` served only the first-ever platform bootstrap, while ordinary `/orgs/create` users were sent directly to the full admin settings page. Normal creation now continues to a resumable `/setup?org={slug}` topics → invitations → first-proposal path without changing the detailed access controls on the creation form.
- Removed the post-create route back to organization creation. “Finish later” exits to the already-created organization's proposal list.
- Starter-topic creation now reconciles selected names with server-existing topics before writing and records each successful topic immediately, so retry submits only unfinished names.
- Invitation parsing now normalizes and deduplicates addresses, reports malformed lines instead of silently dropping them, and reports the response-confirmed number queued for email delivery.
- The completion step and true empty proposal state now provide a direct first-proposal action to authorized stewards. Ordinary members receive waiting-state copy with no admin action.
- Fixed a mobile-only blank zero-topic delegation state and made its action permission-aware.
- Fixed the seven proposal status filters clipping “failed” and “archived” at 380px by using a two-row mobile grid.
- Frontend tests: 4 passed. Targeted backend journey/side-effect regression: 49 passed. Frontend production build: PASS, bundle `index-25BxjmrT.js`.
- Isolated local browser journey: PASS for first-platform bootstrap, later organization creation, topics, malformed + valid invitation input, invitation email queue response, invited-member registration, verification, membership landing, first proposal, first vote with no delegation, consumed-invitation friendly failure, zero notifications/messages/delegates, zero-vote graph/trajectory, steward/member permission-aware empty proposals, and steward/member permission-aware zero-topic delegations.
- 380px browser checks reported document width at or below viewport and no overflowing main-content elements after the filter fix. Browser console errors: none.
- Separate Firefox and Safari engine runs remain deferred; this session's browser evidence is Chromium-based and makes no cross-browser-completeness claim.
- No schema migration; PostgreSQL smoke not required.

## Production delivery — 2026-07-14

- Implementation commit: `9b15ec3`; no-ff merge to `master`: `a6a5c1e`.
- Railway frontend deployment `b6ed0266-c82a-490d-afb6-cc57f6feae91`: SUCCESS.
- Railway backend deployment row `68f08c69-8458-4d53-8141-6825f7531d33`: SKIPPED as expected because no backend watched files changed. Existing backend remained Online.
- Production bundle changed from `index-DxjkqN5I.js` to `index-25BxjmrT.js`; the served bundle contains the Phase 93 onboarding and permission-aware empty-state contracts.
- `https://www.liquiddemocracy.us/`: HTTP 200 and normal landing render. `/api/health/ready`: HTTP 200 with database connected. No Liquid Democracy console errors were observed in the production sanity check.
