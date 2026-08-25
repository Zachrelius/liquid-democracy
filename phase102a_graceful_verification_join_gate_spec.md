# Phase 102a — Graceful Identity-Verification Join Gate

**Status:** SPEC READY / IMPLEMENTATION NOT STARTED. Written August 25, 2026 after production testing of the Massachusetts Legislature organization showed that an unverified account is correctly denied membership but sees only a red `Server error 403` toast.

## Goal

Turn a correct backend denial into a clear, actionable membership flow.

When a signed-in person cannot join because they do not meet an organization's identity, residency, locality, or age requirements, the public organization page must open an accessible dialog that:

1. says identity verification is required;
2. names the organization;
3. lists the configured eligible cities, states, or countries in plain language when residency is required;
4. explains any other membership requirement returned by the server;
5. offers a primary **Go to identity verification** action that leads into Liquid Democracy's existing Didit-backed verification flow;
6. identifies Didit as the verification provider and links its privacy policy; and
7. offers a clear **Not now** action without leaving a raw error toast behind.

The denial remains enforced server-side. This pass changes the error transport and recovery experience, not who is eligible.

## Root cause and verified starting state

The backend is already doing most of the right work:

- all three organization-membership creation paths call the verification floor, age, and residency checks before creating a membership;
- those checks raise structured FastAPI 403 details such as `error="verification_required"` and, for residency mismatches, a readable `residency_scope` list;
- `frontend/src/verificationLabels.js` already formats residency entries as `City, ST`, `ST`, or a country name; and
- `OrgPublicLanding.handleJoinAction` already attempts to detect a structured verification denial.

The immediate defect is a frontend envelope mismatch:

- `frontend/src/api.js` throws failed JSON responses as `{ message, status, raw: data }`;
- `extractVerificationRequiredDetail` checks `error.detail`, `error.response.data.detail`, and `error.body.detail`, but not `error.raw.detail`; therefore
- the structured detail is missed and `normalizeApiError` correctly refuses to stringify an arbitrary object, producing the fallback `Server error 403`.

There is a second UX gap. An unverified account normally fails the membership-floor check before the residency check, so the first 403 may not carry the organization's full allowed-location list. The membership-floor denial must be enriched with the complete public membership-verification requirements so the dialog can accurately describe the gate on the first click.

Finally, the current Settings verification section hides its start control once a user reaches `address_on_id`. That creates a dead end for a previously verified person whose ID address changed or does not match a new organization's locality. This pass must expose a deliberate **Update verification** route for real, non-demo accounts while preserving the existing consent and capacity checks.

## Branch and delivery

- Branch: `phase-102a/graceful-verification-join-gate`.
- Merge: no-fast-forward to `master`.
- One-line dispatch: `Read and execute phase102a_graceful_verification_join_gate_spec.md.`
- Expected recurring-cost delta: $0.
- No migration; PostgreSQL smoke is not required.
- Ship after the current Phase 102 work and the pending Phase 101a Router hotfix are reconciled into `master`, unless Z explicitly reprioritizes this as an earlier hotfix.

### Worktree isolation

At authoring time the main checkout is a heavily modified `phase-102/scheduled-proposal-lifecycle` worktree. The executing team must use a clean worktree based on the then-current `master`, copy this spec into it, and leave the Phase 102 checkout untouched. Do not stash, reset, clean, move, or absorb the current uncommitted work.

## Verification matrix

| Check | Required | Notes |
|---|---:|---|
| Root-cause regression | Yes | The actual API error shape `{status:403, raw:{detail:{error:'verification_required', ...}}}` is extracted correctly |
| Membership requirement payload | Yes | Floor failure includes readable residency scope and any configured minimum age without exposing member PII |
| Join-path enforcement | Yes | Open, approval-request, and invitation acceptance remain blocked before membership mutation when ineligible |
| Accessible dialog | Yes | Focus trap, initial focus, Escape, backdrop close, labelled title/body, keyboard actions, focus restore |
| Requirement copy | Yes | One/many city, state, and country entries; identity-only; residency; minimum-age; malformed-safe fallback |
| Verification CTA | Yes | Routes to the existing in-app verification section, never to a generic Didit signup/business-console page |
| Re-verification | Yes | Real verified users can intentionally update; demo stubs remain sealed; disclosure and capacity checks still run |
| Structured-error compatibility | Yes | Proposal, role, delegate, invitation, and member-admin callers using the shared extractor do not regress |
| Frontend tests/build | Yes | Complete `npm test`, changed-file lint, production build |
| Backend focused tests | Yes | Verification enforcement and residency/locality suites plus new Phase 102a payload tests |
| Backend full suite | Yes | Use the authoritative post-Phase-102 baseline and report the exact result |
| Browser QA | Yes | Production unverified join, matching verified join, mismatching verified residency, desktop/keyboard/~380px |
| Production delivery | Yes | New bundle live; readiness and monitor healthy; no test membership left behind |
| Migration/PG smoke | No | No schema change; state this explicitly in closeout |

## Suggested team structure

Small pass: **Lead + one full-stack developer + QA**.

- **Lead:** integration review, gates, clean-worktree delivery, deployment, and closeout.
- **Full-stack developer:** structured payload enrichment, shared error extraction, dialog, Settings re-verification path, and tests.
- **QA teammate:** independent production verification through the standard Chrome path in `AGENTS.md`.

## Locked decisions

1. **Keep the 403.** Eligibility denial remains HTTP 403 and server-authoritative. Do not convert an ineligible join into a pending membership or a frontend-only disablement.
2. **Fix the real envelope.** `extractVerificationRequiredDetail` must recognize `error.raw.detail`, the canonical shape emitted by the project's fetch wrapper. Preserve the legacy candidate shapes for compatibility.
3. **Do not stringify arbitrary structured errors.** Keep `normalizeApiError`'s safe object behavior. The fix is typed extraction, not converting backend objects into `[object Object]` or exposing JSON in a toast.
4. **Return complete public requirements.** A membership-floor rejection includes the organization's configured residency scope and minimum age in addition to the existing floor/jurisdiction fields. These are organization rules already visible to administrators and prospective members; no applicant verification data or hashes are returned.
5. **Preserve existing fields.** Enrich the 403 additively. Existing `error`, `floor`, `jurisdiction`, and `scope` consumers continue to work.
6. **Use a dialog, not a transient toast.** A verification denial on the public join action opens a persistent, accessible dialog. Ordinary network errors and unrelated 4xx/5xx failures continue through the normal toast path.
7. **The primary action stays inside Liquid Democracy.** It navigates to the existing Settings identity-verification section, which requests a provider session from the backend and shows the consent disclosure before redirecting to Didit. Never link the primary action to Didit's generic homepage, login, signup, or business console; those routes cannot bind the verification to the Liquid Democracy account and could create the same account-confusion problem Z encountered.
8. **Name Didit honestly.** The dialog may say verification is completed through Didit and must link to Didit's privacy policy. It must not promise provider-side deletion or non-retention; Phase 84's honest-copy constraint remains in force.
9. **Allow intentional updates.** A real verified account may need to re-verify after moving or correcting an ID. Settings shows **Update verification** for eligible real accounts, with a confirmation that the new check replaces/updates the current verification and uses verification capacity. The existing server-side capacity check remains authoritative.
10. **Demo stubs remain sealed.** Demo personas never receive a working Didit CTA and cannot start/update real verification.
11. **No eligibility pre-judgment in the browser.** The frontend may display requirements but must not decide that a user qualifies. A retry always calls the server again.
12. **No automatic join after verification in this pass.** After verification, the person returns to the organization and clicks Join/Request again. Silent membership creation from a provider webhook is out of scope and would be surprising.

## What this pass is

- A repair to the structured-error transport contract.
- A graceful membership-verification denial dialog.
- Complete, readable organization gate requirements on that denial.
- A safe route into the existing Didit-backed flow.
- The already-backlogged ability for a real verified user to update verification when residency changes.

## What this pass is not

- No change to verification ranks, residency matching, age calculations, join policies, or duplicate-flag behavior.
- No direct link to a generic Didit account/login page.
- No Didit business-account recovery or provider-console work.
- No provider-side purge fix or retention promise.
- No automatic retry or automatic organization membership after the webhook.
- No database migration, new verification provider, billing, or free-pool policy change.
- No redesign of every 403 in the application.

## Cluster B — Backend requirement payload

### B1 — Canonical public membership requirements

Add a small pure helper in `backend/verification.py`, named along the lines of `membership_verification_requirements(org)`, that returns only the public gate configuration needed by the UI:

```json
{
  "floor": "address_on_id",
  "jurisdiction": null,
  "requires_residency": true,
  "residency_scope": [
    {"country": null, "state": "MA", "city": null}
  ],
  "min_age": null
}
```

Use the existing normalized residency-scope reader and existing settings constants; do not fork state/city/country normalization. Malformed settings fail safely to empty/null values. Never include the applicant's address, locality hash, legal name, DOB, age band, document identifiers, provider session, attestation, or duplicate-flag data.

### B2 — Additive floor-denial enrichment

When `check_membership_floor_for_join` rejects, include the canonical membership requirements in the structured detail while retaining the existing top-level contract. Recommended additive shape:

```json
{
  "error": "verification_required",
  "scope": "membership",
  "floor": "address_on_id",
  "jurisdiction": null,
  "membership_requirements": { "...": "..." }
}
```

Residency-only and min-age denials may retain their present scope-specific fields, but the frontend formatter must be able to derive the same complete explanation from any membership rejection. Prefer attaching `membership_requirements` consistently to all membership-gate failures if this can be done through one helper without changing enforcement order.

Do not weaken or reorder the join checks merely to obtain better copy. Tests must assert zero membership row and zero join notification/audit side effects after every denial.

## Cluster F — Frontend recovery experience

### F1 — Repair shared extraction

Extend `extractVerificationRequiredDetail(error)` to inspect `error.raw.detail` first or alongside the current supported shapes. Add a direct unit test using the exact object thrown by `api.js`. Keep the helper pure and return `null` for unrelated/malformed errors.

Audit its current callers (`OrgPublicLanding`, `InviteAccept`, `Members`, and `ProposalDetail`) so the new candidate shape improves them without changing their intended presentation. Do not turn all of those surfaces into dialogs in this pass; only the public organization join flow requires the new dialog.

### F2 — Requirement formatter

Refactor or extend the shared verification-copy helper so it can produce structured presentation data for a membership dialog rather than only one toast string. It must support:

- identity-only requirement;
- address-on-ID / verified-resident floor;
- one allowed city/state;
- one state;
- multiple mixed city/state/country entries with grammatical separators;
- minimum age when configured;
- legacy `jurisdiction` payloads; and
- a truthful generic fallback when the payload is incomplete.

Internal state names (`address_on_id`, `residency_scope`) never appear in rendered copy.

### F3 — `VerificationJoinDialog`

Add a focused component, following `useModalDialog` and the Phase 94 accessibility patterns. Suggested content:

- Title: **Identity verification required**
- Lead: **To join [organization], you need to verify a government-issued ID.**
- Requirements: **Your verified ID address must be in Massachusetts.** or the correctly formatted configured list.
- Provider note: **Identity verification is completed securely through Didit.** Include a separate `Didit's privacy policy` link opening safely in a new tab.
- Primary: **Go to identity verification**
- Secondary: **Not now**

The primary navigates to `/settings#identity-verification`. Add a stable `id="identity-verification"` anchor to the Settings section and ensure keyboard focus/scroll reaches the section after navigation. The dialog closes on Escape/backdrop/secondary action, restores focus to Join/Request, and does not emit an additional error toast.

### F4 — Settings update-verification path

Preserve the existing start-session -> server disclosure -> continue-to-provider sequence. Adjust the control states:

- unverified/partially verified real account: **Start verification**;
- already verified real account: **Update verification**;
- demo-stub account: no working provider action;
- starting/pending disclosure/error states retain their current behavior.

Before a verified account starts an update, show a confirmation explaining that the new check updates/replaces the current verification and consumes verification capacity. Do not promise that re-verification will make the person eligible; the address on the submitted ID still must match the organization's rule.

## Cluster T — Tests

Backend focused coverage:

- unverified membership-floor 403 includes the full MA residency scope on the first denial;
- city/state/country OR-list serialization;
- configured minimum age included;
- malformed settings produce safe empty requirements;
- applicant PII and internal hashes absent;
- open join, approval request, and invitation acceptance remain non-mutating on denial;
- matching verified MA resident still joins through the existing path; and
- no-setting organizations retain exact additive-layer parity.

Frontend coverage:

- extraction from `{raw:{detail:...}}` succeeds and unrelated raw errors return null;
- requirement formatting for identity-only, MA, city lists, mixed countries, minimum age, and fallback;
- public landing source uses dialog state for verification denials and toast for unrelated errors;
- primary action targets `/settings#identity-verification`, not a generic Didit URL;
- privacy-policy link has `target="_blank"` and `rel="noopener noreferrer"`;
- dialog accessibility contract and focus behavior;
- no rendered `Server error 403` for a structured verification denial; and
- Settings start/update/demo-stub branches plus confirmation before re-verification.

Run the complete frontend suite, changed-file lint, production build, focused backend verification/join suites, and the authoritative full backend suite.

## Cluster Q — Production QA

Use disposable/test accounts and avoid altering Z's or his wife's verification records.

1. Signed-in unverified account visits the Massachusetts Legislature public page and clicks Join/Request.
2. Confirm no membership is created and no red `Server error 403` toast appears.
3. Confirm the dialog names the organization, says government-ID verification is required, and lists Massachusetts plus any other configured locations exactly once.
4. Verify keyboard focus, Tab containment, Escape, focus return, and approximately 380px layout.
5. Open Didit's privacy policy in a new tab; confirm the primary action instead goes to the in-app Settings verification section.
6. Start the verification path only far enough to confirm the existing consent disclosure and provider-session handoff; do not consume a real verification unless the test plan explicitly authorizes it.
7. With an existing matching verified Massachusetts test account, confirm join still succeeds normally and no dialog appears.
8. With a verified but nonmatching/locality-mismatched test fixture, confirm the dialog appears and Settings offers **Update verification** rather than a dead end.
9. Confirm invitation-accept and proposal verification-denial copy still render their existing graceful paths after the shared extractor fix.
10. Remove any disposable membership/request created by QA and report cleanup.

## Operational and security watch-outs

- The provider session URL is generated for the signed-in Liquid Democracy user. A generic Didit account URL is not an acceptable substitute.
- The residency scope is organization policy, not member PII. Keep the response limited to configured rules.
- Do not log structured rejection bodies if a future payload ever gains applicant data.
- Phase 84 remains authoritative: say what Liquid Democracy stores and that Didit processes the documents; make no provider deletion promise.
- Re-verification consumes the shared verification pool. The server's existing capacity check and unavailable-until-reset message remain authoritative.
- The current repository contains a historical tracked handoff document with a plaintext Didit API key. Secret rotation/removal is a separate security action and must not be silently bundled into this UX pass without Z authorization and a history-remediation plan.

## Closeout reporting

Report:

- root cause and exact envelope correction;
- backend payload before/after with proof no PII was added;
- status of all three join paths and side-effect assertions;
- dialog copy, accessibility, responsive, and navigation results;
- re-verification behavior and demo-stub sealing;
- backend and frontend test counts, lint, and build;
- no migration / PG smoke not required;
- production bundle, readiness, monitor, and browser QA;
- disposable-account cleanup;
- files changed, commits, branch, no-ff merge, push, and deploy status; and
- whether the historical Didit key was rotated/remediated separately or remains an explicitly tracked security follow-up.

## Expected file set

Expected:

- `phase102a_graceful_verification_join_gate_spec.md`;
- `backend/verification.py`;
- focused backend Phase 102a tests;
- `frontend/src/verificationLabels.js`;
- `frontend/src/pages/OrgPublicLanding.jsx`;
- `frontend/src/pages/Settings.jsx`;
- one focused dialog component and, if needed, a small shared helper;
- focused frontend Phase 102a tests; and
- `PROGRESS.md` at closeout.

No model, migration, dependency, Railway secret, provider workflow, or unrelated organization-setting change is expected.
