# Phase 95 — Onboarding Defaults Refinement

## Dispatch

### Goal

Make the new-organization setup choices clearer and align fresh organization defaults with the platform's pilot posture: all proposal types available, while proposal-level identity verification is disabled unless the organization deliberately adopts it.

### Branch and delivery

- Branch: `phase-95/onboarding-defaults`
- Merge: `--no-ff` into `master`
- Deploy: push `master`, wait for Railway, then verify the production bundle and backend readiness
- Migration: none anticipated; these defaults are stored when a new organization is created

### Verification matrix

| Check | Required | Notes |
|---|---:|---|
| Topic step includes at least two visibly unselected suggestions | Yes | Preserve the four existing selected starters |
| Topic copy makes any/all/none and custom topics clear | Yes | Browser snapshot at the setup topic step |
| Continuing with zero selected topics works | Yes | No topic POSTs; advances to invitations |
| Custom topic remains selected when added | Yes | Existing behavior preserved |
| A newly created organization enables every supported voting method | Yes | Assert persisted settings through the real create endpoint |
| A newly created organization stores proposal verification policy `never` | Yes | Assert persisted settings through the real create endpoint |
| Existing/unconfigured organization fallback remains `author` | Yes | No backfill or silent policy change |
| Organization settings accurately render the new defaults | Yes | Source test plus browser QA |
| Frontend tests and production build pass | Yes | Run the repository commands |
| Targeted backend tests pass | Yes | Organization creation and verification policy |
| Local browser QA | Yes | Use disposable local data only |
| Production browser sanity | Yes | Read-only where practical after deploy |

### Team structure

Single full-stack Codex pass. The changes are bounded to the setup topic chooser, new-organization settings, supporting copy, and regression tests.

### Sequence

1. Centralize the starter-topic definitions in a testable frontend utility.
2. Add optional unselected suggestions and make the zero-topic continuation explicit.
3. Update only the persisted defaults applied by the top-level organization creation endpoint.
4. Correct organization-settings copy so it does not describe the legacy policy as the new default.
5. Add regression tests, browser-verify locally, merge, deploy, and production-sanity check.

### Load-bearing decisions

- Existing organizations are not backfilled or rewritten.
- Missing `verification_proposal_policy` continues to resolve to `author` for legacy compatibility; fresh organizations explicitly store `never`.
- The new voting-method list is `binary`, `approval`, `ranked_choice`, `budget_allocation`, and `budget_project`.
- The four current starter topics remain preselected. `Events` and `Elections` are added as recognizable optional examples and start unchecked.
- Users may continue with any, all, or zero starter topics, and may add custom topics.
- No paid services, schema changes, or production-data mutation are in scope.

### Operational watch-outs

- Preserve unrelated dirty-worktree files.
- Do not use production organization creation for QA.
- Keep sub-organization inheritance/override behavior unchanged.
- Verify that downstream proposal creation reads the persisted full method list without a separate frontend allow-list.

### Closeout reporting

- Per-workstream status and exact behavior shipped
- Tests/build/browser verification
- Files and commits
- Explicit no-migration / PG-smoke-not-required statement
- Railway deployment IDs, production bundle, and health result

---

## Status

**IN PROGRESS — 2026-07-17**

## What this phase is

A small usability and policy-default refinement based on the owner's first real use of the Phase 93 guided setup.

## What this phase is not

- A redesign of the setup wizard
- A backfill of existing organizations
- A change to identity-verification enforcement for organizations that already configured a policy
- A change to sub-organization inheritance

## Workstreams

### A — Topic-choice clarity

- Add `Events` and `Elections` as unchecked starter suggestions.
- State that users may select any, all, or none and can add their own.
- Let the primary continuation action advance with zero selected topics.

### B — Fresh-organization voting defaults

- Persist all five supported voting methods for organizations created after this deploy.
- Keep administrators able to disable non-binary methods later.

### C — Fresh-organization verification default

- Persist `verification_proposal_policy: "never"` for newly created organizations.
- Preserve `author` as the compatibility fallback for existing organizations without an explicit key.
- Update settings copy to describe the distinction accurately.

### D — Regression coverage and delivery

- Add frontend contracts for starter-topic selection and zero-topic continuation.
- Extend real-endpoint organization-creation coverage for both persisted defaults.
- Run targeted tests, build, browser QA, merge/deploy, and production sanity.

## Follow-ups

- Revisit the exact starter-topic vocabulary after several pilot organizations have used the flow.
- The owner's newly created pre-Phase-95 organization keeps its stored settings; it can enable all methods and choose `never` manually in Organization Settings if desired.
