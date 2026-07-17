# Phase 96 — Adversarial Security Verification

**Status:** Complete (2026-07-17)

## Goal

Exercise the production-shaped application as a hostile anonymous visitor, newly registered user, cross-organization member, and underprivileged organization member. Confirm that privacy, tenancy, authorization, resource, and external-callback boundaries fail closed; remediate every confirmed in-scope vulnerability and preserve the result with regression tests.

## Branch + merge

- Branch: `phase-96/adversarial-security-verification`
- Merge: `git merge --no-ff` to `master`, then push and verify Railway production.
- Active probes use disposable local data. Production verification is non-destructive.

## Verification matrix

| Check | Required | Notes |
|---|---:|---|
| Route/trust-boundary inventory | Yes | Anonymous, optional-auth, authenticated, org-scoped, admin, WebSocket, webhook, upload |
| Cross-org object substitution | Yes | Proposal, vote/result, comment, delegation, message, member/admin surfaces |
| Role/permission bypass | Yes | Fresh account, ordinary member, steward/admin-only actions |
| Invitation abuse | Yes | Enumeration shape, cross-email/cross-org consumption, replay, expiry |
| Upload abuse | Yes | Declared type vs decoded content, decompression limits, path isolation, public delivery |
| Rate-limit/proxy behavior | Yes | Login/reset and high-risk fresh-account write surfaces; spoofed forwarding headers |
| WebSocket/webhook behavior | Yes | Unauthorized subscriptions and unsigned/malformed Didit callbacks fail closed |
| Dependency and secret checks | Yes | Production dependency audit plus tracked-source secret-pattern scan |
| Targeted backend tests | Yes | New adversarial regressions plus affected route suites |
| Full backend suite | Yes | Run where the desktop test environment permits; document environmental blockers honestly |
| Frontend lint/build | Conditional | Required if frontend changes; otherwise production build smoke only |
| PG smoke | Conditional | Required only if an Alembic migration is added |
| Production sanity | Yes | Deployment row, readiness, public/private boundary and safe failure probes |

## Locked decisions

1. Previously remediated Phase 91/91a findings are regression targets, not assumed open defects.
2. No destructive SQL, denial-of-service load, brute-force campaign, unsolicited messages, or persistent test content against production.
3. Endpoint existence is not itself a finding. A finding requires a reproducible unauthorized disclosure, state change, unsafe resource behavior, or materially missing control.
4. Private and secret organizations must remain indistinguishable to an ineligible caller wherever the route contract promises concealment.
5. Frontend permission checks never substitute for backend enforcement.
6. Security fixes ship in this pass when narrow and well-understood. Larger architectural or product-policy choices are documented as follow-ups rather than guessed.

## Work clusters

### A — Exposure and tenancy map

- Enumerate HTTP and WebSocket routes and their authentication dependencies.
- Probe legacy/unscoped and org-scoped object lookups with anonymous, unrelated-user, and wrong-org identities.
- Verify membership, sub-organization, proposal-visibility, and result-visibility gates at the object boundary.

### B — Identity, permissions, and invitations

- Exercise privilege escalation and confused-deputy paths across organization roles.
- Test invitation token metadata, email binding, expiry, replay, and cross-organization substitution.
- Confirm authentication and refresh-token failure paths remain fail-closed after Phase 91.

### C — Resource and callback surfaces

- Validate avatar/logo decoding, pixel ceilings, type normalization, filename/path isolation, and delivery headers.
- Test rate-limit identity behind the private frontend proxy and forwarding-header spoof resistance.
- Verify WebSocket proposal authorization and Didit webhook signature validation.

### D — Remediation and delivery

- Implement confirmed fixes with regression tests.
- Run dependency/security checks and affected suites.
- Merge, deploy, and perform non-destructive production security sanity checks.

## Closeout

Report confirmed findings and fixes, negative probes that passed, test-count delta, dependency-audit results, migration/PG-smoke status, changed files, commits, merge/deploy status, bundle hash, production sanity, and residual risks. Do not mark complete until production verifies.

## Confirmed findings and remediation

| Severity | Finding | Remediation |
|---|---|---|
| High | An authenticated verified account holding somebody else's invitation token could consume it, including an admin-role invitation. | Bind authenticated acceptance to the invitation's normalized email before any membership or token mutation. |
| High | Parent-only members could retrieve and mutate private sub-organization proposals by ID through detail, revisions, trajectory, ballot-status, verification-weight, write-in, phase, archive/delete/edit, and cosign surfaces. | Apply the canonical proposal-viewer predicate at every affected ID boundary and return concealment-preserving 404s. |
| High | The deprecated tenant-unscoped delegate directory could serialize private profile metadata and had no frontend consumer. | Unmount the legacy `/api/delegates/public*` router; retain only the org-scoped visibility-filtered directory. |
| High | Proposal create/update accepted Topic IDs belonging to another organization. | Validate topic tenant and sub-organization compatibility before writes; validate the entire replacement set before deleting existing links. |
| Medium | Removed or suspended Polis creators retained creator-based mutation and deanonymized-export authority. | Creator ownership now requires current Polis viewer eligibility; platform admins retain the explicit operational bypass. |
| Medium | Any verified account could create a platform-global proposal visible outside an organization. | Restrict the legacy global create route to platform administrators and require globally scoped topics. |
| Medium | Anonymous and unrelated callers could enumerate parent-level topic names belonging to hidden organizations. | Filter global topic results by organization discoverability and active membership. |
| Medium | Suspended content authors could retain narrow author shortcuts, including recent comment edits. | Require current proposal visibility before proposal/comment mutations; self-deletion remains available where intentionally supported. |

## Verification results (pre-deploy)

- Phase 96 adversarial regressions: 17 passed. Each state-changing denial asserts absence of the unauthorized side effect.
- Full backend suite: 2,983 passed, 18 skipped, 0 failed (four workers, 14m46s).
- Focused invitation, proposal, tenancy, Polis, delegate, comment, cosign, WebSocket, rate-limit, verification-webhook, avatar, logo, and prior security suites: passed.
- Python production dependency audit: no known vulnerabilities (`pip-audit`, pinned requirements, no dependency resolution).
- npm production dependency audit: 0 vulnerabilities across 84 production dependencies.
- Tracked secret/key scan: no tracked `.env`, private-key file, or recognized high-confidence credential signature found.
- Frontend production build: passed. Existing large-bundle warning remains a performance concern, not a security failure.
- No migration added; PostgreSQL migration smoke is not required.

## Production verification

- Implementation commit `9eb39f4`; no-fast-forward merge to `master` at `e9ba7bb`.
- Railway backend deployment `b327db06-9bb8-4947-af72-bd70c5685cb2` matched the Phase 96 merge and reported `Deployment successful`; the frontend service remained online and reported a successful active deployment on the unchanged frontend bundle.
- Production bundle: `index-CCwDG6q2.js` (expected unchanged because Phase 96 contained no frontend source changes).
- Non-destructive production smoke: homepage HTTP 200; `/api/health/ready` HTTP 200 with database connected; retired `/api/delegates/public` HTTP 404; invalid invitation metadata HTTP 404; unsigned Didit webhook HTTP 401.
- Railway CLI authentication was unavailable locally, so deployment-row verification used the signed-in Railway dashboard. No production data was created or mutated during verification.

## Residual risks and next security work

- This pass substantially increased authorization-boundary coverage but is not a claim of formal penetration-test coverage or certification. Repeat adversarial verification after major identity, tenancy, voting, delegation, upload, or infrastructure changes.
- Independent external penetration testing remains appropriate before a high-stakes or regulated deployment.
- Repository-wide frontend lint debt and the existing large JavaScript bundle are engineering-quality/performance work, not confirmed Phase 96 security vulnerabilities.
