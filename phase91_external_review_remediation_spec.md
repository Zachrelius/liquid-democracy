# Phase 91 — External Review Remediation

**Status:** Complete and production-verified (2026-07-12).

## Goal

Close the confirmed privacy, weighted-governance integrity, authentication-concurrency, dependency, and automated-audit gaps found by the July external review.

## Branch + merge

- Branch: `phase-91/external-review-remediation`
- Merge: `git merge --no-ff` to `master`, then push and verify Railway production.
- No destructive production-data operations.

## Locked scope

1. Public profiles must not expose hidden ballot proposal IDs/titles/timestamps. Surface only a hidden-vote count where useful.
2. `GET /api/users/{id}` must not return private `UserOut` fields to other users. Self access remains available through `/api/users/me` and `/api/auth/me`.
3. A stored voting weight of zero must serialize and display as zero.
4. Authorized-share cap enforcement must serialize concurrent issuance changes per organization.
5. Refresh-token rotation must atomically claim a token. Persist only token hashes, with a safe transition for existing plaintext rows.
6. Upgrade vulnerable runtime dependencies to compatible fixed versions and add automated dependency-audit gates.
7. Railway private-networking/exposure changes are explicitly deferred pending a separate infrastructure go/no-go; code must document the residual `--forwarded-allow-ips '*'` risk.

## Verification matrix

| Check | Required | Notes |
|---|---:|---|
| Privacy endpoint tests | Yes | Logged-out, unrelated-user, self, hidden/private proposal cases |
| Zero-share tests | Yes | Member serializers + ballot chip; tally parity retained |
| Refresh-token tests | Yes | Hash-at-rest, legacy transition, rotation/reuse, concurrent claim semantics |
| Share-cap concurrency test | Yes | PostgreSQL-oriented locking behavior plus unit regression coverage |
| Backend suite | Yes | Full pytest suite before merge |
| Frontend lint/build | Yes | Lint baseline must not worsen; build must pass |
| Dependency audits | Yes | `pip-audit` and production `npm audit` |
| PG smoke | Conditional | Required only if an Alembic migration is added |
| Production sanity | Yes | Bundle hash, backend deployment row, health, privacy/API smoke |

## Closeout

Report findings closed/deferred, test delta, dependency audit result, migration/PG-smoke status, changed files, commits, merge/deploy state, bundle hash, and production sanity. Do not mark complete until production verifies.
