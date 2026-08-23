# Phase 101 — Trusted High-Volume Proposal Creation

**Status:** SPEC READY / IMPLEMENTATION NOT STARTED. Requested by Z on August 23, 2026 after a 20-proposal Massachusetts Legislature import created ten drafts and then correctly but unexpectedly exhausted Phase 86's `10/day` proposal-create limiter.

## Goal

Preserve the ordinary anti-abuse ceiling while allowing explicitly trusted organization maintainers to create hundreds or thousands of proposals for large organizations without an account-wide hidden allowlist.

This pass has four outcomes:

1. ordinary proposal creators remain limited to 10 proposal creations per 24-hour fixed window;
2. a new organization-scoped role permission grants a much higher, still bounded proposal-creation allowance;
3. the existing multi-proposal import automatically uses the caller's applicable allowance, without a separate upload format or manual ops intervention; and
4. rate-limit failures explain what happened and preserve already-created drafts instead of showing only `Server error 429`.

## Branch and delivery

- Branch: `phase-101/high-volume-proposal-creation`
- Merge: no-fast-forward to `master`.
- One-line dispatch: `Read and execute phase101_high_volume_proposal_creation_spec.md.`
- Push `master`, verify the Railway frontend and backend deployments, then run QA per `AGENTS.md`.
- Expected recurring-cost delta: $0.

## Verification matrix

| Check | Required | Notes |
|---|---:|---|
| Permission registry and defaults | Yes | New key appears once in Proposals; Steward/Admin default on, Moderator/Member default off |
| Existing-org backfill migration | Yes | Enabled rows added only for existing Steward/Admin roles; reversible upgrade → downgrade → upgrade |
| Ordinary limit regression | Yes | Requests 1–10 succeed and request 11 returns 429 with no proposal or audit side effect |
| High-volume allowance | Yes | Permission holder can create more than 10 and a 200-proposal local import completes without the ordinary limiter firing |
| High-volume safety fuse | Yes | Configured ceiling is enforced and its rejected request writes nothing |
| Scope and revocation | Yes | Grant in org A has no effect in org B; revocation returns the caller to the ordinary tier |
| Permission composition | Yes | High-volume permission never substitutes for `proposal.create`, membership, verified email, topic scope, or any proposal validation |
| Sub-organization behavior | Yes | Effective-role and transferability rules are honored; no parent/sub-org privilege leak |
| Existing creation side effects | Yes | Draft/status/timestamps, topics/options, audits, zero-day behavior, Polis links, and notifications remain identical |
| 429 response parsing | Yes | Structured SlowAPI `error` copy reaches the UI; contextual import guidance replaces generic `Server error 429` |
| Multi-import UI | Yes | >10 selection warns/blocks for ordinary callers; high-volume callers can continue; partial progress remains accurate |
| Backend suites | Yes | Phase 101 focused tests, Phase 86 anti-abuse, proposal creation/import, permissions, audit, and notification regressions |
| Frontend suites | Yes | Focused source/unit tests, `npm test`, changed-file lint, and production build |
| PG smoke | Yes | Migration prior revision `c5d6e7f8a9b0`; run `pg_smoke.py --mode both` |
| Browser QA | Yes | Role grant/revoke plus 11-item import on a disposable/demo organization; no Massachusetts production proposal mutation required |
| Production delivery | Yes | New bundle live, backend/readiness/monitor healthy, exact route behavior verified without mass production creation |

## Suggested team structure

- **Lead:** permission/rate-limit design review, migration integration, full gates, deployment, and closeout.
- **Backend developer:** registry/backfill, scoped rate-tier resolver, creation-path integration, audit detail, and backend tests.
- **Frontend developer:** Role Permissions surfacing, import guidance, 429 parsing/copy, and frontend tests.
- **QA teammate:** independent permission, standard-limit, high-volume, revocation, and responsive/keyboard verification on a disposable or daily-reset demo organization.

## Locked decisions

1. **The Phase 86 limit was intentional and remains the default.** `PROPOSAL_CREATE_LIMIT = "10/day"` continues to protect ordinary global and organization-scoped proposal creation. “Day” is described to users as a 24-hour window beginning with the first counted request, matching the fixed-window implementation rather than implying a midnight reset.
2. **Use an organization role permission, not a login/email/environment allowlist.** Add `proposal.high_volume_create`, labeled **High-volume proposal creation**, described as: “Allow creating proposals above the standard daily limit for trusted bulk-import and large-organization maintenance. All ordinary proposal permissions and validation still apply.” No email strings, user IDs, JWT claims, or Railway variables identify favored accounts.
3. **The grant is organization-scoped.** A person enabled in Massachusetts has no elevated creation allowance in Oregon or any other organization. Sub-organizations use the existing effective-role and transferability rules.
4. **Default grants match trusted administrative responsibility.** New and existing Steward/Admin roles receive the permission enabled. Moderator and Member roles receive it disabled. The Role Permissions matrix can revoke it from Admin or grant it to another role. The governing-role lock set is unchanged: this new permission is editable, not irrevocably owner-only.
5. **This is role-level, not an individual exception table.** The platform does not add per-membership permission overrides in this pass. To authorize another maintainer, place that person in an appropriate organization role and enable the permission for that role. A per-person grant system would be a broader authorization-model project.
6. **It composes with `proposal.create`.** `proposal.high_volume_create` changes only the rate tier. It grants no ability to create a proposal by itself and bypasses none of: active membership, verified email, `proposal.create`, sub-org authority, topic ownership/scope, voting-method rules, threshold/duration permissions, verification configuration, or proposal schema validation.
7. **No global platform-admin shortcut is invented.** Parent-organization permissions continue to follow the current membership/role matrix. A platform administrator who is not an authorized member does not gain a new cross-org content-creation power through this pass.
8. **Trusted is high-volume, not unbounded.** Permission holders use a separate per-user allowance of **10,000 proposal creations per 24-hour fixed window**. This supports a full approximately 8,000-bill session import while retaining a safety fuse for a runaway client. The constant lives beside `PROPOSAL_CREATE_LIMIT` in `rate_limit_utils.py` and is not per-org configurable.
9. **The two tiers must not consume each other's counters.** An ordinary caller consumes the 10/24h bucket and zero cost from the trusted bucket. An enabled caller consumes the 10,000/24h bucket and zero cost from the ordinary bucket. Revoking the permission changes which tier future requests consume; it does not mutate or erase prior counters.
10. **Resolve entitlement before charging a request.** The rate-tier decision must be based on the authenticated user, target organization, active membership/effective sub-org role, and current permission row. Never trust a client header or request-body boolean. If SlowAPI decorator/dependency ordering cannot be proven with an integration test, move this one gate into an explicit server-side rate-check helper after dependencies resolve; do not ship an ordering assumption.
11. **Keep one proposal-creation implementation.** This pass does not add a second proposal-write implementation. Existing single-form and multi-import creation continue through `POST /api/orgs/{org_slug}/proposals` and the same validation/mutation/side-effect path. The high-volume permission changes only limiter selection.
12. **Sequential import remains resumable.** Phase 72's review UI still creates selected proposals sequentially. Each successful proposal remains an independent draft. A later failure never deletes or rolls back earlier drafts, and retry excludes rows already marked created.
13. **Do not silently run a doomed ordinary batch.** When an ordinary caller selects more than 10 remaining import rows, disable `Create selected` and explain that standard accounts can create at most 10 proposals in a 24-hour window; they may select ten or ask an organization administrator to enable High-volume proposal creation. The UI cannot know how much of the user's current window was already consumed, so it must not claim that ten will definitely succeed.
14. **High-volume state is visible at the point of use.** When the new permission is present, the multi-import review shows a quiet note: `High-volume proposal creation is enabled for your role.` Do not add a modal or an alarming warning.
15. **429s become intelligible.** Extend the shared API error parser to accept a safe top-level string `error` when `detail` is absent, because SlowAPI emits `{ "error": "Rate limit exceeded: …" }`. The import UI maps a proposal-create 429 to contextual copy explaining the applicable tier, that created drafts are safe, and that the remaining checked rows can be retried later. Do not expose stack traces or raw objects.
16. **Audit use without adding an audit storm.** Every successful proposal already emits `proposal.created`. Add `high_volume_rate_tier: true` to that event's details when the trusted tier applied. Do not create a second event per proposal. Rejected rate-limit requests create neither a proposal nor an audit row.
17. **No batch-create endpoint in this phase.** Hundreds of sequential requests are acceptable for the immediate Massachusetts experiment once the trusted tier is active. A purpose-built idempotent batch-create endpoint is a later performance/reliability project if measured imports show request overhead or lost-response duplication to be material. Phase 101 must not copy the large creation function merely to reduce request count.

## What this pass is

- A scoped exception to an intentional anti-abuse default.
- A reusable capability for trusted maintainers of data-heavy organizations.
- A repair of the interaction between Phase 72 multi-import and Phase 86 rate limiting.
- Clearer feedback for all rate-limited actions through the shared API parser.

## What this pass is not

- No account-global allowlist or special-case for Z's email/user ID.
- No removal or universal increase of the ordinary 10/24h proposal limit.
- No bypass of proposal creation permissions or validation.
- No automatic import immediately after file selection; review remains required.
- No automatic advancement to deliberation; Phase 100's separate reviewed bulk action remains the next step.
- No batch-create endpoint, database-wide import job, background queue, or import scheduler.
- No pagination/virtualization or claim that an 8,000-proposal organization is already visually manageable.
- No changes to comment, report, follow, join, invitation, organization, write-in, or share-transfer limits.

## Implementation sequence

1. Add the registry key, defaults, migration/backfill, and permission tests.
2. Add and prove the scoped two-tier rate resolver on organization proposal creation.
3. Surface the permission and rate guidance in multi-import; fix shared 429 parsing.
4. Run focused permission/import/anti-abuse and complete backend/frontend gates.
5. Run migration cycle and PG smoke against prior revision `c5d6e7f8a9b0`.
6. Merge with `--no-ff`, deploy, and run disposable/demo-org production QA.

## Cluster B — Permission and migration

### B1 — Registry definition

Add `proposal.high_volume_create` to the Proposals category in `permission_registry.py`. Update registry counts, category-count assertions, seed invariants, endpoint response tests, and any comments that hardcode the current 31-key total.

`DEFAULT_GRANTS` after the addition:

- Steward: every registered permission, including the new key.
- Admin: every registered permission, including the new key.
- Moderator: unchanged existing set; new key absent/false.
- Member: unchanged empty set.

The key must appear in `OrgOut.user_permissions` and sub-org permission output through the existing serializer/resolver paths. This is not a new `Organization` field; the Phase 46a top-level `OrgOut` allow-list does not need a new field, but focused assertions must prove the new permission reaches the frontend for an enabled caller and disappears after revocation.

### B2 — Existing-organization backfill

Add a reversible Alembic migration after `c5d6e7f8a9b0` that inserts an enabled `RolePermission` row for `proposal.high_volume_create` for every existing role whose `system_key` is `steward` or `admin`. It must:

- be idempotent against an already-present key;
- preserve an already-present explicit enabled/disabled row rather than overwriting it;
- insert nothing for Moderator, Member, or nonmatching roles;
- delete only rows for this new key on downgrade; and
- cycle upgrade → downgrade → upgrade on SQLite and pass PostgreSQL smoke in both modes.

The migration changes authorization data only; it adds no table or column.

### B3 — Role Permissions matrix

The existing matrix should display the registry row without a special component. Verify editable/locked state and confirmation behavior. The row is editable for every role under the same meta-permission rules as other ordinary keys. No dedicated “trusted accounts” administration page is added.

## Cluster R — Scoped two-tier limiter

### R1 — Constants and tier resolver

Keep:

```python
PROPOSAL_CREATE_LIMIT = "10/day"
```

Add beside it:

```python
HIGH_VOLUME_PROPOSAL_CREATE_LIMIT = "10000/day"
```

Implement a small named resolver that determines the rate tier from server-side request context. It must return ordinary unless all relevant conditions pass: authenticated verified user, active membership/effective sub-org authority, `proposal.create`, and `proposal.high_volume_create` in the target organization.

The resolver must be independently testable. Do not add this distinction to the shared `user_or_remote_address` key function because that function is used by unrelated content limits.

### R2 — SlowAPI integration

Apply both counters to the existing organization-scoped create endpoint with mutually exclusive request costs, or implement an equivalently tested explicit gate after FastAPI dependencies resolve:

- ordinary tier: cost 1 against 10/24h, cost 0 against 10,000/24h;
- high-volume tier: cost 0 against 10/24h, cost 1 against 10,000/24h.

The test suite must prove the permission dependency resolves before the limiter chooses a cost. A request denied for auth, membership, verified-email, or creation permission must never be treated as evidence that the rate override works.

Keep the global platform-admin-only `POST /api/proposals` route on the ordinary existing limiter; this pass addresses organization maintenance imports only.

### R3 — Proposal creation audit detail

Thread the resolved tier into the existing `proposal.created` audit detail and add `high_volume_rate_tier: true` only for trusted-tier successes. Preserve every other create behavior byte-for-byte. No new notification is introduced.

## Cluster F — Import and error UX

### F1 — Shared API error normalization

In `frontend/src/api.js`, preserve current precedence:

1. Pydantic `detail` array;
2. string `detail`;
3. safe top-level string `error`;
4. `Server error {status}` fallback.

Apply the same rule to both duplicated response-handling branches or factor them into one tested helper if that reduces drift. Never stringify an object into user-facing copy.

### F2 — Multi-import permission awareness

Read `proposal.high_volume_create` through `useHasPermission`.

For callers with the permission:

- show the quiet enabled note;
- allow any valid selection up to Phase 72's existing 50-item file cap; and
- retain sequential progress and per-row created/failed state.

For callers without it:

- if more than 10 uncreated valid rows are selected, disable creation and show guidance to select no more than ten or request the new permission;
- do not claim ten remain in the current window; and
- if an attempted batch of ten or fewer receives 429 because earlier activity consumed the allowance, stop as today, keep successes marked, and show contextual retry guidance.

For a high-volume caller who reaches the 10,000 safety fuse, use equivalent contextual copy naming the high-volume ceiling without implying that the permission was revoked.

### F3 — Accessible/responsive behavior

The new warning/note must be associated with the create controls, readable at approximately 380px, and not rely on color alone. Disabled-button explanation must remain visible and keyboard-readable. Existing checkbox, expand/collapse, edit-title, and cancel behavior stays unchanged.

## Cluster T — Backend tests

Add a focused Phase 101 test module and update permission-registry/migration coverage. Required cases:

- ordinary organization creator: first 10 requests succeed, 11th is 429, row/audit counts remain 10;
- enabled creator: requests 1–11 and a 200-proposal local sequential scale fixture succeed without the ordinary limiter firing;
- high-volume safety fuse rejects the first over-limit request with zero side effects (exercise through an injectable/test-sized limit or isolated limiter rather than creating 10,001 database rows);
- key enabled but `proposal.create` disabled: 403 and no write;
- unverified, suspended/nonmember, wrong-org, and malformed proposal requests do not gain a bypass;
- permission in org A does not affect org B;
- revoke then request uses the ordinary tier;
- Moderator/Member defaults do not bypass; a matrix grant enables the tier;
- Steward/Admin existing-org migration rows are enabled; preexisting explicit rows are preserved; downgrade is surgical;
- sub-org direct/effective/transferred roles resolve correctly;
- global proposal creation remains on its existing limit;
- successful trusted-tier audit contains the boolean; standard audit does not falsely claim it;
- topics, options, custom thresholds/durations, zero-day skip, Polis linkage, verification gates, and notifications match the existing create route; and
- Phase 86 limiter reset fixtures isolate both new counters between tests.

## Cluster U — Frontend tests

Required cases:

- API error normalization renders SlowAPI's string `error` and preserves `detail` precedence;
- object-valued `error` falls back safely;
- 11 selected ordinary rows disable creation and make zero create calls;
- 10 or fewer ordinary rows retain existing sequential behavior;
- high-volume permission allows 20 selected rows and makes 20 sequential create calls;
- ordinary 429 preserves prior created rows and remaining selections and shows contextual copy;
- high-volume 429 identifies the safety fuse;
- enabled note appears only when permission is present; and
- source contracts still prove one-at-a-time requests, no accidental batch endpoint, and no automatic deliberation transition.

## Cluster Q — QA and production verification

1. On a disposable or daily-reset demo organization, confirm the new permission appears in Role Permissions with Steward/Admin enabled and Moderator/Member disabled.
2. As an ordinary permitted creator, verify the contextual standard-tier guidance for an 11-item selection. Do not create 11 real Massachusetts proposals for this negative test.
3. Grant the permission to the test role and create an 11-item disposable batch; verify all 11 drafts, titles/topics, progress, enabled note, and audit detail.
4. Revoke it and verify the UI returns to the ordinary state.
5. Check desktop, keyboard, and approximately 380px mobile rendering.
6. Confirm production bundle activation, backend readiness/database connectivity, monitor state, and no unexpected notification or incident.
7. Do not alter Z's Massachusetts proposal content during QA. After Phase 101 is verified, Z can retry the remaining rows from the existing reviewed import; already-created rows stay excluded in the current review session, or a freshly loaded file can be deselected to avoid duplicates.

## Operational notes and watch-outs

- The current limiter uses process memory. A backend restart clears its counters; Phase 101 does not change limiter storage architecture. Do not use a restart as the product workflow for trusted imports.
- Phase 72's 50-proposal/256-KB preview caps remain. Large legal-text batches will naturally be split into smaller files even though the trusted daily allowance is 10,000.
- Permission-cache invalidation after a Role Permissions update must follow the existing request/session lifecycle. Verify a fresh request sees grant and revocation immediately; do not require logout/login.
- Large sequential imports can expose request-overhead or lost-response duplication. Record measured behavior at 200 items. If it is materially slow or unreliable, scope a later idempotent batch-create/job pass; do not expand Phase 101 during implementation.
- The Massachusetts pipeline and its ignored local files are not product-code inputs to this phase. Use a synthetic small-body fixture for automated scale tests.

## Closeout reporting

The Phase 101 closeout must include:

- per-cluster DONE/blocked/scoped-up status;
- exact permission defaults and migration/backfill counts by role;
- standard 10/24h, trusted 10,000/24h, cross-org, revocation, and 200-item results;
- backend test-count delta and frontend test results;
- migration cycle and PostgreSQL smoke status against `c5d6e7f8a9b0`;
- browser verification for permission matrix, ordinary guidance, trusted import, revocation, keyboard, and mobile—or an explicit unclaimed/blocker statement per `AGENTS.md`;
- files changed, commits, branch/merge state;
- production bundle, backend deployment/readiness/monitor evidence; and
- confirmation that no Massachusetts production proposal was created, deleted, archived, or advanced during QA.
