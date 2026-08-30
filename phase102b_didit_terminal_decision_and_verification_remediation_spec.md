# Phase 102b — Didit Terminal-Decision Enforcement and Verification Remediation

**Status:** COMPLETE / DEPLOYED August 30, 2026. Written August 27, 2026 after a production investigation confirmed that a Didit session with overall status `Abandoned`, an approved ID-document step, and no completed liveness or face-match result was incorrectly promoted by Liquid Democracy to `address_on_id`.

## Goal

Restore the truthfulness of Liquid Democracy's identity-verification gates.

This pass must:

1. promote a user only after Didit reports an overall approved session and every identity feature required by the configured workflow is present and approved;
2. fail closed for abandoned, declined, in-review, incomplete, malformed, or contradictory decisions without erasing a previously valid verification;
3. make webhook replay handling status-aware so one `status.updated` event cannot suppress a later, different provider status;
4. prevent an organization from saving an `always` proposal-verification policy with no effective floor;
5. audit the full production Didit-verification cohort without exposing identity payloads;
6. correct every confirmed false-positive verification through a guarded, auditable remediation path; and
7. repair the Massachusetts Legislature proposal gate so every direct voter must have an ID address in Massachusetts.

The provider's result is authoritative. An approved document/OCR component is evidence that a document passed checks; it is not by itself proof that the person presenting it completed liveness and face matching.

## Confirmed production incident and root cause

The August 27 read-only investigation established all of the following without reading or printing document numbers, raw addresses, images, selfies, or ballot content:

- the affected account's Didit session currently reports overall `Abandoned`;
- the session declares `ID_VERIFICATION`, `LIVENESS`, `FACE_MATCH`, and `IP_ANALYSIS` features;
- `id_verifications` contains `Approved`, while `liveness_checks` and `face_matches` contain no completed result;
- Liquid Democracy wrote `verification.completed` on June 12, 2026, changing the account from `email_only` to `address_on_id`, jurisdiction `MA`, country `US`, provenance `didit`;
- the local verification-session row was marked `approved_purge_failed` and a verification-consumption row was recorded;
- the account joined `ma-legislature` on August 25 and cast a direct vote on August 27; and
- the organization membership gate is `address_on_id` plus residency scope `{country: US, state: MA}`, so the incorrectly stored MA result satisfied the join checks exactly as implemented.

The code defect is in `backend/verification_provider.py::_decision_passed_id`. It currently returns true when **any one** of these is approved:

- `decision.id_verifications[0].status`;
- the legacy singular `decision.id_verification.status`; or
- `decision.status`.

It does not require the webhook's overall status to be approved and does not require configured liveness or face-match results. `map_decision_to_state` then consumes OCR address fields and returns `address_on_id`. `routes/verification.py::didit_webhook` applies any payload containing a decision object, records completion/consumption, and attempts provider purge. The resulting user row is internally self-consistent but based on an incomplete provider workflow, so downstream join and voting checks cannot distinguish it from a legitimate approval.

The tests encode the same unsafe assumption: Phase 52a mapper and replay fixtures expect a per-document approval alone to promote the user. There is no negative fixture for `Abandoned + ID Approved + missing face/liveness`.

A second defect exists in organization settings. `ma-legislature` currently stores:

```json
{
  "verification_proposal_policy": "always",
  "verification_proposal_floor": null,
  "verification_proposal_jurisdiction": null
}
```

`effective_proposal_floor` correctly resolves that invalid combination to no gate, so the affected proposal had no independent verification requirement at vote time. The settings UI exposes the dependent fields but the persisted settings contract does not prevent this ineffective state.

## Branch and delivery

- Branch: `phase-102b/didit-terminal-decision-fix`.
- Merge: no-fast-forward to `master`.
- One-line dispatch: `Read and execute phase102b_didit_terminal_decision_and_verification_remediation_spec.md.`
- Priority: security and governance-integrity hotfix; ship before relying on new Didit verifications or the Massachusetts Legislature pilot gate.
- Expected recurring-cost delta: $0. Decision retrieval is read-only and must not create paid verification sessions.
- No migration is expected. Existing user, session, membership, audit, and settings columns are sufficient. PostgreSQL migration smoke is not required unless implementation discovers a genuine schema need and scopes it up explicitly.
- Use a clean worktree based on current `master`. Preserve the heavily dirty main checkout; do not stash, reset, clean, move, or absorb unrelated files.

## Verification matrix

| Check | Required | Notes |
|---|---:|---|
| Exact incident regression | Yes | `Abandoned` overall + ID Approved + missing liveness/face match remains unverified and produces no completion side effects |
| Strict approved path | Yes | Overall webhook and decision approved; each declared mandatory identity feature present and approved |
| Contradictory/malformed matrix | Yes | Approved component with non-approved overall, approved overall with missing/failed required component, empty arrays, unknown casing/shape |
| Re-verification safety | Yes | Abandoning or failing an update does not erase a prior valid verification |
| Webhook transition/replay | Yes | Same-status replay dedupes; a different later status is processed; no `(session, webhook_type)` false dedupe |
| PII boundary | Yes | No raw decision, document number, address, DOB, images, or biometrics persisted or emitted by audit tooling |
| Consumption/purge side effects | Yes | Only genuine approvals record completion/consumption and enter the approved purge path |
| Proposal-policy invariant | Yes | `always` cannot persist without a valid non-email floor and required jurisdiction; backend authoritative, frontend explanatory |
| Vote enforcement | Yes | Repaired MA settings block a below-floor direct vote and exclude below-floor ballots from eligibility/tally |
| Cohort audit dry run | Yes | All Didit-provenance users classified as confirmed-valid, confirmed-invalid, unavailable/purged, or needs-review without names/PII in output |
| Guarded remediation | Yes | Exact-target, expected-state compare-and-set; clears false derived verification; suspends affected gated memberships; preserves votes/audits/consumption |
| Focused backend tests | Yes | Provider mapper, webhook, enforcement, settings validation, eligibility/tally, remediation script |
| Full backend suite | Yes | Use Phase 102a's 3,115-case baseline and report exact result/delta |
| Frontend tests/build | Yes | Org Settings validation plus complete frontend suite, changed-file lint, production build |
| Production rollout | Yes | Backend first, cohort dry run, settings repair, guarded account remediation, frontend, readiness/monitor |
| Production verification | Yes | Provider decision readback, user/session/audit state, MA gate, blocked unverified vote, eligible verified vote |
| Browser QA | Yes | Org Settings invalid/valid save and affected-account verification/join/vote presentation per AGENTS.md |
| Migration/PG smoke | No expected | State explicitly in closeout; run required migration gates only if scope changes |

## Suggested team structure

Use **Lead + backend developer + frontend developer + QA**.

- **Lead:** incident invariants, production cohort audit, guarded remediation, rollout sequencing, and closeout.
- **Backend developer:** provider acceptance predicate, webhook lifecycle/idempotency, settings validation, audit/remediation tooling, and tests.
- **Frontend developer:** make invalid `always` policy unsaveable and present the backend validation clearly.
- **QA teammate:** independent local and production verification, including the exact abandoned-session regression through a synthetic signed webhook fixture; never consume a real verification merely for QA.

## Sequence

1. Land strict provider-decision helpers and the exact incident regression first.
2. Repair webhook lifecycle, replay semantics, completion/consumption/purge side effects, and re-verification safety.
3. Add the backend proposal-policy invariant and frontend validation.
4. Build and locally exercise the privacy-minimized cohort audit and guarded remediation command.
5. Run focused and full gates; merge and deploy backend before any production data correction.
6. Run production audit in dry-run mode and save only PII-minimized counts/classifications in the closeout.
7. Repair `ma-legislature` proposal settings through the normal validated settings path.
8. Apply remediation only to confirmed false-positive rows whose live provider status and database preconditions still match the dry run.
9. Deploy/verify frontend, run production sanity and browser QA, and close out with exact before/after counts.

## Locked decisions

1. **Overall approval is mandatory.** A component approval can never override an overall `Abandoned`, `Declined`, `In Review`, `In Progress`, missing, or unknown status.
2. **Validate both envelopes.** The top-level webhook `status` and `decision.status` must both normalize to `Approved`. Missing or contradictory values fail closed.
3. **Use the V3 plural-array contract.** Production promotion reads `id_verifications`, `liveness_checks`, and `face_matches`. Do not retain the singular V2 fallback as an alternate production approval path. Legacy fixture compatibility is less important than fail-closed identity enforcement.
4. **Declared mandatory identity features must complete.** `ID_VERIFICATION` requires at least one approved `id_verifications` result. If the session declares `LIVENESS`, at least one liveness result must be present and every required node must be approved. If it declares `FACE_MATCH`, the same rule applies to `face_matches`. Missing/empty arrays fail. `IP_ANALYSIS` remains part of Didit's overall decision rather than becoming an independent Liquid Democracy identity rung.
5. **The configured Liquid Democracy workflow must include ID, liveness, and face match.** Add a startup/testable provider-configuration assertion or explicit session-creation validation. Do not silently approve a weakened workflow that omits either biometric step.
6. **No client callback can verify a user.** Only the signed server webhook and strict predicate may write real verification state.
7. **Last-known-good survives a failed update.** If an already verified user starts a replacement session and abandons/fails it, preserve their existing valid user-level verification. Record the new session outcome without downgrading the prior good result.
8. **Non-approved sessions have honest local statuses.** Use outcome-specific values such as `abandoned`, `declined`, or `in_review`; do not label them approved and do not emit `verification.completed`.
9. **Replay identity includes provider status.** A repeated identical terminal outcome is a no-op. A later different outcome using the same `status.updated` webhook type is not suppressed merely because the webhook type matches.
10. **Completion side effects are approval-only.** Legal-name/age/hash/locality writes, attestation, `verification.completed`, metering consumption, duplicate checks, and approved-session purge run only after strict approval.
11. **Do not rewrite append-only history.** Existing audit and verification-consumption rows from the incident remain. Add a corrective audit event; do not delete or edit the historical record that explains what occurred.
12. **Remediation is exact and guarded.** No broad SQL update. The apply path requires an explicit user ID, expected current verification state/provenance, expected provider session, expected live provider status, and a confirmation flag. A changed precondition aborts without mutation.
13. **Clear all false-derived identity material together.** A confirmed never-approved account returns to `email_only`/`none`; clear jurisdiction, country, attestation, legal-name fields, age-band fields, locality hash, name/DOB hashes, and uniqueness strength. Set `verification_updated_at` to the corrective timestamp and emit `verification.remediated_false_positive` with PII-free old/new state metadata.
14. **Suspend, do not delete, gated memberships.** If remediation makes the user fail an organization's current membership gate, set the affected active membership to `suspended` with an audit event. Do not delete the membership. Re-verification does not silently reactivate it; an authorized org administrator can review and reactivate it afterward.
15. **Preserve historical Vote rows.** Do not delete or rewrite the affected ballot. Suspension plus the repaired proposal floor must exclude the user from current eligibility/tally and block further direct voting. If the member is legitimately reverified/reactivated later, normal current-eligibility semantics apply; no special retroactive ballot mutation is introduced here.
16. **`always` must mean always.** The backend rejects an organization settings write where proposal policy is `always` but the floor is null, `email_only`, malformed, or missing a required jurisdiction. The frontend prevents the save and explains which field is missing, but backend validation is authoritative.
17. **Repair MA to the existing state-level model.** Set `verification_proposal_policy="always"`, floor `address_on_id`, and jurisdiction `MA`. Do not expand proposal gates to the membership residency OR-list model in this hotfix.
18. **Unknown cohort rows are not auto-demoted.** Provider 404/purged, missing-session, or contradictory historical rows go into `needs_review`; only live provider evidence of a non-approved session plus matching DB/audit preconditions permits automatic remediation.
19. **No real-person provider QA.** Use signed webhook fixtures locally. Production QA may inspect existing provider status and exercise gates with already-authorized test accounts, but must not create a paid real verification or collect new identity data solely for testing.

## What this pass is

- A security fix to the Didit decision boundary.
- An idempotency and local-session-lifecycle correction.
- A configuration-integrity fix for always-on proposal verification.
- A PII-minimized production integrity audit.
- A guarded remediation of confirmed false-positive verification and affected gated memberships.

## What this pass is not

- No new verification provider, identity rung, biometric storage, or raw provider-payload retention.
- No client-side verification decision.
- No deletion or rewriting of historical votes, audit logs, or consumption ledger rows.
- No provider-console account recovery, billing change, purge redesign, or promise about Didit's retention.
- No general redesign of membership suspension/reactivation.
- No country/city proposal-residency expansion; MA uses the existing state-jurisdiction vote floor.
- No database migration unless implementation proves an existing column cannot safely represent the required lifecycle.

## Cluster B — Strict provider acceptance

### B1 — One fail-closed approval predicate

Replace `_decision_passed_id` with a helper whose input is the complete webhook payload and decision, not the decision alone. It should return a structured result suitable for tests and PII-safe diagnostics, for example:

```python
ProviderDecisionResult(
    approved=False,
    normalized_status="abandoned",
    reason="overall_not_approved",
    feature_statuses={
        "id_verification": "approved",
        "liveness": "missing",
        "face_match": "missing",
    },
)
```

Do not include OCR fields or provider identifiers in the result. Normalize status casing/spacing only; do not map unknown words to approved.

The helper must prove:

- top-level status is Approved;
- decision status is Approved;
- the declared feature list includes the configured mandatory workflow features;
- the matching plural result arrays exist and are non-empty; and
- all required nodes are Approved.

`map_decision_to_state` may extract jurisdiction/country only after this predicate succeeds. Its public API should make it difficult for a caller to bypass approval accidentally: accept a prevalidated result or call the strict predicate internally with the full payload.

### B2 — Workflow configuration integrity

The application creates sessions against one configured `DIDIT_WORKFLOW_ID`. Validate that the workflow contract expected by code includes ID verification, liveness, and face match. Prefer a deterministic provider-session response/decision assertion and a unit-testable local expected-feature constant over a new recurring network call at every request.

If provider metadata contradicts the expected workflow, fail the verification safely and emit an operational error without PII. Do not weaken the expected feature set dynamically to match a provider response.

## Cluster W — Webhook lifecycle and side effects

### W1 — Outcome-aware state machine

Refactor `didit_webhook` so provider outcome classification happens before `_apply_decision` and before any completion side effect.

- Approved: apply the decision, record completion and consumption, run duplicate checks, commit, then use the existing best-effort purge behavior.
- Abandoned/Declined: mark the new session honestly, emit a PII-free outcome audit, preserve any prior valid user verification, and do not run approval side effects.
- In Review/In Progress: record the transient session state and allow a later `status.updated` event to advance it.
- Missing/unknown/contradictory: fail closed, record a safe diagnostic status/reason, and remain processable if a later valid status arrives.

Keep signature/freshness verification and unknown-session behavior unchanged unless a focused test demonstrates a defect.

### W2 — Status-aware idempotency

The current replay key is effectively `(provider_session_id, webhook_type)` while Didit uses `status.updated` for multiple transitions. Replace the shortcut with comparison against the normalized provider outcome represented by the local session state.

Required examples:

- `In Review` replay -> no duplicate audit, remains processable;
- `In Review` then `Approved` -> approval applies exactly once;
- `Abandoned` replay -> no duplicate outcome audit;
- `Declined` then a genuinely provider-approved reviewed result -> process according to documented provider transition semantics rather than discard due to the repeated webhook type; and
- `Approved` replay -> no duplicate completion, consumption, duplicate flag, or purge side effect.

No migration is needed if `VerificationSession.status` plus `webhook_type_last` can represent this safely. If not, stop and scope a reversible migration with the required migration-cycle and PostgreSQL smoke gates.

### W3 — Approval-only data writes

Tests must assert absence, not just response success. For every non-approved matrix case, assert no changes to:

- user verification state/provenance/jurisdiction/country;
- attestation and derived identity fields;
- legal-name and age fields;
- locality/name hashes;
- verification consumption;
- `verification.completed` audit;
- duplicate-account flags; and
- provider purge invocation.

For a previously valid user attempting an update, assert the original valid fields remain byte-for-byte.

## Cluster C — Organization proposal-gate integrity

### C1 — Backend cross-field validator

At the canonical organization-settings write boundary, validate the merged final settings object atomically rather than validating only keys present in the patch.

For policy `always`:

- floor must be a recognized state stronger than `email_only`;
- `address_on_id` and `residency_verified` require a non-empty valid jurisdiction;
- lower identity-only floors clear stray jurisdiction; and
- invalid writes return structured 422 detail naming the fields without partially mutating settings.

Policies `author` and `never` retain current semantics. Switching to `never` may preserve dormant values or clear them according to the existing UI convention, but effective enforcement must remain none. Tests must cover partial PATCH attempts against an already-invalid row so the validator cannot be bypassed by updating one key at a time.

### C2 — Frontend save contract

In `frontend/src/pages/admin/OrgSettings.jsx`:

- show required indicators when policy is `always`;
- disable/block Save until a valid floor is chosen;
- require state/jurisdiction for address-level floors;
- focus the first invalid control and render an accessible inline explanation; and
- surface backend 422 detail if stale/malicious clients bypass the frontend.

Do not silently replace a missing floor with a default; administrators must see and choose the rule being enforced.

### C3 — MA settings repair and vote proof

After the validating backend is deployed, write the Massachusetts Legislature settings through the normal endpoint as one atomic change:

```json
{
  "verification_proposal_policy": "always",
  "verification_proposal_floor": "address_on_id",
  "verification_proposal_jurisdiction": "MA"
}
```

Read back the effective floor. Prove in tests and production-safe QA that:

- an `email_only` or non-MA account receives structured `verification_required` before a Vote write;
- an eligible MA `address_on_id` account can vote;
- the eligibility/tally helper excludes an existing below-floor ballot; and
- the organization membership settings remain unchanged.

## Cluster R — Cohort audit and remediation

### R1 — Privacy-minimized audit command

Add a checked-in script under `backend/scripts/` with dry-run as the default. It may query only the columns required to correlate:

- Didit-provenance user state;
- verification-session bookkeeping;
- completion/outcome audit timestamps;
- consumption existence;
- gated active memberships; and
- provider decision status plus per-feature statuses.

The script must never print or persist emails, usernames, display/legal names, addresses, DOB/age, document numbers, hashes, attestation IDs, full provider session IDs, images, raw decisions, or ballots. Output aggregate counts and opaque short-lived row labels or truncated UUIDs only when necessary for an operator to target a remediation.

Classification:

- `confirmed_valid`: live overall Approved and required features Approved;
- `confirmed_false_positive`: stored real verification but live provider evidence is non-approved/incomplete under the strict predicate;
- `needs_review_provider_unavailable`: purged/404/unreachable provider decision;
- `needs_review_history_mismatch`: database/audit/session relationships contradict; and
- `not_applicable`: demo/backdoor/non-Didit provenance.

The script exits nonzero on provider/network/shape errors that would make a clean classification look successful.

### R2 — Guarded apply mode

The same command or a companion script may remediate one exact user at a time. Apply requires:

- explicit `--user-id` and `--provider-session-id` inputs;
- an exact expected database state/provenance/session status;
- a fresh provider decision retrieved in the apply transaction window;
- classification `confirmed_false_positive`;
- `--confirm-remediation`;
- a transaction with compare-and-set predicates; and
- a dry-run preview immediately before apply.

If any precondition changes, roll back and print a PII-free refusal. The script must be idempotent: a second invocation reports already remediated and performs no new audit or membership mutation.

Apply behavior:

1. reset the false verification and clear all derived identity fields listed in Locked Decision 13;
2. mark the local session with an honest remediated outcome;
3. append `verification.remediated_false_positive`;
4. find active memberships whose current gate the remediated user no longer satisfies;
5. set those memberships to `suspended` and append an org-scoped audit event; and
6. leave Vote, AuditLog, and VerificationConsumption rows untouched.

Before commit, print only counts of user rows, session rows, memberships, votes preserved, audits to add, and consumption rows preserved. Exactly one user row must be targeted.

### R3 — Production ordering

The lead performs:

1. database backup/readiness confirmation;
2. deploy strict backend;
3. cohort dry run;
4. review `needs_review` separately with no mutation;
5. repair MA proposal settings;
6. dry-run the known confirmed incident;
7. apply exact remediation;
8. read back user/session/membership/audit state;
9. recompute the affected proposal's eligibility/tally without changing the Vote row; and
10. report the full cohort counts and exact number remediated.

Do not place provider keys or database URLs in shell history, committed scripts, logs, or closeout artifacts. Use Railway-injected environment variables.

## Cluster T — Tests

Backend coverage must include at least:

- the exact production incident shape: top-level and decision `Abandoned`, ID Approved, liveness/face empty;
- top-level Abandoned with decision Approved;
- top-level Approved with decision Abandoned/In Review;
- both overall statuses Approved but ID missing/failed;
- liveness declared and missing/failed;
- face match declared and missing/failed;
- all mandatory features present/Approved -> address-on-ID state and expected approval side effects;
- singular V2-only payload rejected for promotion;
- last-known-good verification preserved after abandoned/declined update;
- transient-to-approved and replay matrices;
- no completion/consumption/hash/purge side effects on every failure shape;
- valid and invalid `always` settings, including partial PATCH against invalid persisted data;
- MA below-floor vote rejected before mutation;
- existing below-floor ballot excluded from eligibility/tally;
- audit dry-run redaction and classification;
- remediation precondition mismatch rollback;
- remediation idempotency;
- false fields cleared, membership suspended, vote/audit/consumption preserved; and
- unrelated users/orgs unchanged.

Frontend coverage:

- `always` with missing floor cannot save;
- address-level floor with missing jurisdiction cannot save;
- valid `address_on_id` + MA saves atomically;
- policy changes preserve intended author/never behavior;
- accessible inline error and focus movement; and
- backend structured validation error is rendered safely.

Run focused Phase 52/102b verification suites, settings/enforcement/tally suites, the authoritative full backend suite, complete frontend tests, changed-file lint, production build, Python compile, secret scan, and `git diff --check`.

## Cluster Q — Production QA

1. Confirm deployment SHA and backend health before remediation.
2. Run the audit dry run and record aggregate classifications only.
3. Confirm the known incident remains `Abandoned` at Didit and is classified false-positive without exposing its payload.
4. Apply guarded remediation and confirm the user is `email_only`/`none`, derived fields are cleared, and affected gated membership is suspended.
5. Confirm the historical Vote row, original completion audit, and consumption row remain present.
6. Confirm the new corrective audits exist and contain no PII/provider secret.
7. Confirm MA proposal settings read back as `always` / `address_on_id` / `MA`.
8. Confirm the affected ballot is excluded from current eligibility/tally without deleting it.
9. With an existing authorized verified MA test account, confirm direct voting remains allowed.
10. With an existing unverified test account, confirm join and direct vote are blocked gracefully; do not start Didit.
11. In Org Settings, verify invalid always-policy combinations cannot save and the valid MA combination can be reviewed without changing it again.
12. Run desktop, keyboard, and approximately 380px checks through the standard Chrome path. If the known bridge problem persists, report the browser gate blocked rather than claiming source review as rendered QA.

## Operational and security watch-outs

- Treat this as a false-positive identity incident, not a copy defect. Backend deploy precedes data/config repair.
- The current provider record is available partly because the prior purge failed. Never infer that a provider 404 means approved or invalid; classify it as unavailable.
- Do not broaden redacted webhook logging. The audit command needs statuses, not identity content.
- Preserve Phase 84's honest privacy language. This pass changes acceptance logic, not provider retention.
- A provider retrieval failure must not cause demotion. Fail closed on promotion and fail safe on historical remediation are different rules.
- `verification_consumption` represents a provider session that consumed capacity, even if Liquid Democracy classified it incorrectly. Preserve the ledger.
- Suspension is reversible and safer than deleting membership. Automatic reactivation after a later webhook is out of scope.
- The existing historical plaintext Didit key follow-up remains separate. Do not rotate or rewrite repository history inside this pass without explicit authorization.
- No real verification is needed to test the webhook. Synthetic signed fixtures provide complete deterministic coverage.

## Closeout reporting

Report:

- exact root cause and old/new acceptance truth table;
- status of every verification-matrix row;
- focused and full backend counts with delta from Phase 102a;
- frontend test/lint/build results and bundle hashes;
- no migration / PG smoke not required, or scoped-up migration evidence;
- cohort totals by classification, with no identities or provider IDs;
- number of remediated users, cleared verification rows, and suspended memberships;
- preserved Vote/AuditLog/VerificationConsumption counts;
- MA settings before/after and effective-floor readback;
- below-floor and eligible-voter production proof;
- browser QA or an explicit blocked result;
- files modified, commits, branch, no-ff merge, push, Railway deployment IDs/SHAs, readiness, and monitor; and
- every `needs_review` cohort row as a count and follow-up category, not an auto-remediation claim.

## Expected file set

Expected:

- `phase102b_didit_terminal_decision_and_verification_remediation_spec.md`;
- `backend/verification_provider.py`;
- `backend/routes/verification.py`;
- `backend/verification.py` and/or the canonical organization-settings validator;
- `backend/routes/organizations.py` if that is the settings write boundary;
- `backend/scripts/audit_didit_verification_integrity.py`;
- focused Phase 102b backend tests plus updates to unsafe Phase 52a fixtures;
- `frontend/src/pages/admin/OrgSettings.jsx`;
- focused frontend tests;
- `PROGRESS.md` at closeout.

No model, migration, dependency, raw provider-payload fixture, or unrelated organization-policy change is expected.

## Follow-up considerations

- A later pass may add administrator-facing verification-integrity health reporting if the one-time cohort audit finds enough operational value.
- Continuous enforcement of membership verification on every membership-only action, beyond suspension/remediation and proposal vote gates, should be evaluated separately against current join-time semantics.
- If Didit exposes a stable workflow-version contract, pin and monitor that version rather than relying only on declared decision features.
- Provider purge retry/sweep work remains separate from decision correctness.
