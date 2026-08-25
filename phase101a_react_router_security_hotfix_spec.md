# Phase 101a — React Router Security and CI Hotfix

**Status:** SPEC READY / IMPLEMENTATION NOT STARTED. Written August 25, 2026 after the first GitHub-notification triage found that every recent `master` CI run was stopping at the frontend production-dependency audit.

## Goal

Restore a green default branch and remove the currently reported React Router production vulnerabilities with the smallest compatible dependency-only change.

The intended implementation is an exact-version update of `react-router-dom` from `7.15.1` to `7.18.2`, which also resolves the transitive `react-router` package to `7.18.2`. The pass must prove the audit is clean and that Liquid Democracy's public, authenticated, organization, admin, protected-route, and nested sub-organization navigation still works.

This is a security hotfix, not a general dependency-refresh pass.

## Current evidence and root cause

- Current `master` commit at authoring: `6623ba4613d4071790d8e036d9e2076276cac631` (`Phase 101 closeout: record production verification`).
- Failing GitHub Actions run: `https://github.com/Zachrelius/liquid-democracy/actions/runs/32673280005`.
- Backend job: PASS.
- Frontend job: FAIL in `Audit production dependencies`; subsequent frontend tests and build are skipped by GitHub Actions.
- Direct dependency: `frontend/package.json` pins `react-router-dom` at exact version `7.15.1`.
- Lockfile: both `react-router-dom` and its transitive `react-router` resolve to `7.15.1`.
- Current read-only command:

  ```text
  npm audit --omit=dev --audit-level=low --json
  ```

  reports two affected package nodes: one direct moderate-severity `react-router-dom` finding and one transitive high-severity `react-router` finding. The transitive node aggregates five upstream advisories:

| Advisory | npm severity | Affected v7 range relevant here | Patched v7 boundary |
|---|---:|---|---:|
| `GHSA-wrjc-x8rr-h8h6` — open redirect via backslash in `Link` / `useNavigate` | Moderate | `<7.18.0` | `7.18.0` |
| `GHSA-h8fp-f39c-q6mh` — RSC error-handler protocol validation / XSS | Moderate | `>=7.11.0 <7.18.0` | `7.18.0` |
| `GHSA-337j-9hxr-rhxg` — constructor injection during SSR hydration | Moderate | `<7.18.0` in the applicable line | `7.18.0` |
| `GHSA-chx6-hx7r-mcp5` — unauthenticated route-matching denial of service | High | `>=7.0.0 <7.18.0` | `7.18.0` |
| `GHSA-qwww-vcr4-c8h2` — RSC-mode CSRF bypass | High | `>=7.12.0 <7.18.2` | **`7.18.2`** |

The last advisory makes `7.18.2` the minimum v7 target that clears the full current audit. npm reports `react-router-dom@7.18.2` as the non-major fix. Upstream references:

- `https://www.npmjs.com/package/react-router-dom?activeTab=versions`
- `https://github.com/remix-run/react-router/releases/tag/react-router%407.18.2`
- `https://github.com/advisories/GHSA-qwww-vcr4-c8h2`

Liquid Democracy is a Vite client-rendered SPA and does not intentionally use React Router framework mode, SSR hydration, or unstable RSC APIs. That reduces applicability for some advisories but does not excuse leaving a production audit red: the open-redirect and route-matching findings concern APIs and behavior closer to the application's actual use, and the CI policy correctly requires a clean production dependency graph.

## Branch, isolation, and delivery

- Branch: `phase-101a/react-router-security-hotfix`.
- Base: current `master`; at authoring that is `6623ba4`.
- Merge: `git merge --no-ff` into `master`.
- Push `master`, wait for both GitHub CI and Railway frontend deployment, then perform production QA.
- One-line dispatch: `Read and execute phase101a_react_router_security_hotfix_spec.md.`
- Expected recurring-cost delta: $0.

### Load-bearing worktree warning

At spec-authoring time the main local checkout is on `phase-102/scheduled-proposal-lifecycle` and contains substantial uncommitted Phase 102 work. Those changes are user-owned and must not be stashed, reset, committed into the hotfix, moved, overwritten, cleaned, or otherwise manipulated.

The executing team must:

1. read this spec completely in the current checkout;
2. create or use a **separate clean Codex/git worktree** from `master` for `phase-101a/react-router-security-hotfix`;
3. copy this spec into that clean hotfix worktree so it is tracked with the pass; and
4. leave the existing Phase 102 checkout byte-for-byte untouched.

If a clean worktree cannot be created, stop and report the blocker. Do not implement this hotfix in the dirty Phase 102 checkout. After Phase 101a merges, report that the Phase 102 branch must incorporate the new `master` before it lands, but do not perform that integration during this hotfix.

## Verification matrix

| Check | Required | Notes |
|---|---:|---|
| Worktree isolation | Yes | Hotfix diff contains no Phase 102 implementation files; original dirty checkout remains unchanged |
| Exact dependency graph | Yes | `react-router-dom@7.18.2` direct and one matching `react-router@7.18.2` transitive copy |
| Lockfile review | Yes | Expected Router package/integrity changes only; no unrelated dependency sweep |
| Production npm audit | Yes | `npm audit --omit=dev --audit-level=low` exits 0 with zero production vulnerabilities |
| Clean install | Yes | `npm ci` from the committed lockfile succeeds under Node 22/npm 10-compatible tooling |
| Frontend tests | Yes | Complete `npm test`; Phase 101 baseline is 30/30 PASS |
| Frontend production build | Yes | `npm run build` succeeds; existing large-chunk warning may remain |
| Source compatibility review | Yes | No Router imports or route definitions require migration for 7.15.1 → 7.18.2 |
| Local/browser routing sanity | Yes | Public, auth, org, proposal, admin, protected, deep-link, history, and sub-org paths |
| GitHub CI | Yes | Post-merge `master` run has backend and frontend jobs green; audit no longer skips tests/build |
| Railway frontend deploy | Yes | Deployment matches merge commit, bundle hash changes, homepage serves new bundle |
| Production browser QA | Yes | Critical navigation matrix passes with no Liquid Democracy console errors |
| Backend readiness/monitor | Yes | Both remain 200/healthy after frontend deployment |
| Backend tests | CI-required only | No backend source change; local full backend rerun is not required, but GitHub's backend job must pass |
| Migration/PG smoke | No | No schema or migration change; closeout must state smoke not required |
| Diff hygiene | Yes | `git diff --check`; package/spec/PROGRESS-only expected unless compatibility work is proven necessary |

## Suggested team structure

This is a small pass: **Lead + one frontend developer + QA**.

- **Lead:** worktree isolation, dependency-diff review, complete gates, merge/deploy, GitHub CI confirmation, and closeout.
- **Frontend developer:** exact package update, lockfile regeneration, local test/build/audit, Router compatibility inspection.
- **QA teammate:** independent production routing sanity through the standard Chrome path per `AGENTS.md`.

No backend developer is needed unless an unexpected cross-stack regression is discovered. Do not enlarge the pass merely to keep a default four-role structure.

## Locked decisions

1. **Stay on React Router v7.** Upgrade `react-router-dom` from exact `7.15.1` to exact `7.18.2`. Do not move to React Router v8; that is a separate major-version project.
2. **Pin the exact patched version.** Keep the current exact-version policy (`"react-router-dom": "7.18.2"`), not `^7.18.2` or a floating tag. This makes the lockfile and deployed dependency graph deterministic.
3. **Do not add `react-router` as a direct dependency.** `react-router-dom@7.18.2` declares the matching Router dependency. Verify npm resolves one `7.18.2` copy rather than creating a second explicit package edge.
4. **No audit suppression.** Do not change `.github/workflows/ci.yml`, lower `--audit-level`, add an ignore, use an npm override to disguise the graph, or mark an advisory accepted. The gate stays exactly as shipped in Phase 91.
5. **No `npm audit fix --force`.** Use an intentional exact package update. `--force` is prohibited because it can select unrelated or major changes and makes the reviewed scope unclear.
6. **No general dependency refresh.** Do not update React, Vite, Tailwind, Recharts, eslint, the PWA plugin, actions, or any other package unless npm proves a minimal transitive lockfile adjustment is unavoidable. Any unexpected unrelated update must be explained and justified before merge.
7. **No import migration.** Keep existing `react-router-dom` imports. Upstream notes that v7 can be imported from `react-router`, but changing dozens of imports creates risk and no value for this hotfix.
8. **No application behavior change is intended.** Routing, redirects, protected-route rules, URL shapes, basename/history behavior, and route precedence remain the same.
9. **A source code change is conditional, not presumed.** If the version bump exposes a real compatibility failure, make the smallest source fix plus a focused regression test and document the upstream behavior change. Do not preemptively refactor Router usage.
10. **CI green is part of completion.** A merged dependency bump that still leaves the default branch red is not a completed hotfix.

## What this pass is

- An exact patch/minor-line dependency update within React Router v7.
- A lockfile correction that removes five upstream advisory paths from the production graph.
- A restoration of the Phase 91 npm-audit CI guarantee.
- Focused routing compatibility and production navigation verification.

## What this pass is not

- No React Router v8 migration.
- No React/Vite/Tailwind or broad npm update.
- No conversion from `react-router-dom` imports to `react-router` imports.
- No routing redesign, route rename, basename change, or URL migration.
- No advisory ignore, CI weakening, `overrides` workaround, or `npm audit fix --force`.
- No backend code, database migration, Railway environment-variable change, or production-data mutation.
- No Phase 102 implementation or integration work.

## Implementation sequence

1. Establish clean hotfix worktree and prove the Phase 102 checkout is untouched.
2. Capture the pre-fix dependency/audit evidence.
3. Apply the exact Router update and review the lockfile diff before running wider gates.
4. Run clean-install, graph, audit, test, and build verification.
5. Inspect Router usage and run local/browser routing sanity.
6. Commit the dependency/spec changes on the hotfix branch.
7. Merge with `--no-ff`, push `master`, and wait for GitHub CI plus Railway deployment.
8. Run production browser QA and service health checks.
9. Add the Phase 101a deployed closeout entry to `PROGRESS.md`, commit/push it if that is the established closeout sequence, and report all evidence.

## Cluster F — Exact frontend dependency repair

### F1 — Pre-change evidence

From the clean hotfix worktree, record:

```powershell
Set-Location frontend
node --version
npm --version
npm ls react-router-dom react-router --depth=1
npm audit --omit=dev --audit-level=low --json
```

Expected before the fix:

- direct `react-router-dom@7.15.1`;
- transitive `react-router@7.15.1`;
- audit exit nonzero;
- metadata total: 2 affected package nodes, with 1 moderate and 1 high severity.

The npm audit command's nonzero exit is expected before the update. Preserve the meaningful advisory summary for the closeout; do not paste enormous raw logs.

### F2 — Exact update

From `frontend/`, use the package manager to update both manifest and lockfile intentionally:

```powershell
npm install --save-exact react-router-dom@7.18.2
```

Expected tracked application changes at this point:

- `frontend/package.json`: `react-router-dom` `7.15.1` → `7.18.2`;
- `frontend/package-lock.json`: root dependency and `node_modules/react-router-dom` / `node_modules/react-router` entries resolve to `7.18.2`, with matching registry URLs and integrity values.

Review the lockfile diff immediately. If npm changes unrelated top-level package versions or rewrites a large unrelated portion of the graph, stop and regenerate under the Node 22/npm 10 toolchain used by CI. Do not accept noisy churn simply because the audit turns green.

### F3 — Dependency graph and audit proof

Run:

```powershell
npm ci
npm ls react-router-dom react-router --depth=1
npm audit --omit=dev --audit-level=low
npm audit --omit=dev --audit-level=low --json
```

Required result:

- `npm ci` succeeds from the committed lockfile;
- direct `react-router-dom@7.18.2`;
- one transitive `react-router@7.18.2`;
- no extraneous, invalid, or duplicate Router package;
- audit exits 0;
- audit metadata reports zero production vulnerabilities at every severity.

If npm reports a new unrelated advisory that appeared after this spec was written, do not suppress it. Determine whether the smallest compatible fix belongs in this hotfix; if it materially expands scope, stop and report the changed upstream state to Z.

### F4 — Compatibility inspection

Inspect all current Router usage without rewriting it. At minimum confirm:

- `frontend/src/main.jsx` still mounts `BrowserRouter` correctly;
- `frontend/src/App.jsx` route ordering and redirects compile;
- `ProtectedRoute.jsx`, `AdminRoute.jsx`, and `AdminOnlyRoute.jsx` preserve their redirect/authorization behavior;
- `Link`, `NavLink`, `Navigate`, `useNavigate`, `useLocation`, `useParams`, and `useSearchParams` imports remain valid;
- nested sub-organization paths and query-string-driven admin surfaces compile;
- no project code uses unstable RSC/framework/SSR APIs implicated by the final advisory.

No source edit is expected. If an edit is needed, add a targeted `node --test` regression that fails on the observed compatibility bug and passes after the minimal fix.

## Cluster T — Local verification

### T1 — Required frontend gates

From `frontend/`:

```powershell
npm test
npm run build
```

Expected baseline from Phase 101: **30/30 frontend tests PASS**. A higher count is acceptable only if a real compatibility regression test was added. The production build must complete; the existing large-chunk warning is known and not part of this hotfix.

Repository-wide eslint has documented pre-existing debt (107 errors / 8 warnings as of recent phases). With manifest/lockfile-only application changes, a full lint run is not a useful new gate. If any JSX/JS source is changed, run eslint on every changed source file and require zero changed-file errors.

From the repository root:

```powershell
git diff --check
git diff --stat master...HEAD
git diff -- frontend/package.json frontend/package-lock.json
```

The final branch diff should contain the two dependency files, this spec, and eventually the Phase 101a `PROGRESS.md` closeout entry. Any additional file requires an explicit reason in the closeout.

### T2 — Local/browser routing sanity

Use the locally built app or dev server and verify representative routing rather than clicking every page:

1. public `/` and `/login` load;
2. an unauthenticated protected URL redirects to login as before;
3. sign-in returns to an authenticated organization route;
4. an organization proposals list and one proposal detail route load;
5. an authorized admin route loads and an unauthorized admin route remains denied/redirected;
6. a nested sub-organization route loads;
7. direct deep-link reload does not 404;
8. browser back/forward navigation preserves expected route and query-string state;
9. no new console exception or Router warning appears.

This local pass does not replace production QA.

## Cluster D — Merge, CI, deployment, and production QA

### D1 — Commit and merge

Use the existing commit style, for example:

```text
Phase 101a F1: patch React Router security advisories

Upgrade react-router-dom and its matching transitive react-router package
from 7.15.1 to 7.18.2, the first v7 release that clears the current
production npm audit. Keep the exact pin and avoid unrelated lockfile churn.

Spec: phase101a_react_router_security_hotfix_spec.md
```

Merge `phase-101a/react-router-security-hotfix` to `master` with `--no-ff`, then push `master`. Never force-push.

### D2 — GitHub CI verification

The merge-triggered `master` run is the decisive regression gate. Confirm:

- frontend `npm ci` succeeds;
- `Audit production dependencies` succeeds;
- frontend tests now run and pass rather than being skipped;
- frontend build now runs and passes rather than being skipped;
- backend job passes;
- overall workflow conclusion is success.

Capture the workflow URL and merge SHA. If the audit is green locally but red in GitHub, compare Node/npm versions and lockfile resolution; do not weaken CI.

### D3 — Railway deployment verification

Because `frontend/package*.json` changes, Railway should rebuild and deploy the frontend. Confirm:

- frontend deployment row corresponds to the pushed merge;
- frontend bundle hash changes from Phase 101's `index-DY8CvJfe.js`;
- homepage serves the new bundle;
- backend deployment is skipped/unchanged as expected for a frontend/spec-only pass, unless Railway's watch configuration legitimately rebuilds it;
- `/api/health/ready` returns 200 with database connected;
- `/api/health/monitor` returns 200/healthy with zero unexpected issues.

### D4 — Production browser QA

QA uses the standard Chrome bridge per `AGENTS.md`. If it is unavailable, report the exact blocker; do not silently replace load-bearing browser verification with source review.

Required production matrix:

1. landing page → login;
2. authenticated sign-in → organization context;
3. organization proposals list → proposal detail → back navigation;
4. notification or another query-string/deep-link route, including a direct reload;
5. one authorized admin route;
6. one nested sub-organization route;
7. one protected-route denial/redirect case using the appropriate lower-privilege or logged-out state;
8. no Liquid Democracy console errors or React Router warnings.

No production data mutation is required. Do not create, edit, advance, vote on, or delete a proposal merely to test the Router update.

## Failure and rollback rules

- If `7.18.2` fails tests/build because of a real compatibility change, inspect the upstream changelog and implement the smallest source adaptation plus focused regression coverage. Do not fall back to a vulnerable version.
- If production navigation regresses after deploy, revert the Phase 101a merge with a normal revert commit and push; do not hard-reset or force-push. This returns CI to red but restores known routing behavior while a corrected patch is prepared.
- If npm audit changes upstream during execution, report the new exact advisory/package state and revise the target based on the smallest safe compatible v7 release. Do not guess or suppress.
- If the only available implementation location is the dirty Phase 102 checkout, stop. Worktree isolation is a completion gate, not a preference.

## Closeout reporting

The Phase 101a closeout must include:

- worktree isolation confirmation and explicit statement that Phase 102 files were untouched;
- before/after direct and transitive Router versions;
- before/after npm audit summary, including zero post-fix production vulnerabilities;
- lockfile-diff scope and any unexpected transitive change;
- frontend test count/result and production build result;
- source-compatibility inspection result and whether any source/test file was needed;
- local routing sanity result;
- GitHub Actions workflow URL, merge SHA, and both job conclusions;
- Railway frontend deployment row, old/new bundle hash, readiness, monitor, and production browser QA;
- files changed, commits, branch, no-ff merge, and push state;
- `no migration; PostgreSQL smoke not required`;
- any new debt or upstream concern; and
- a Phase 101a deployed entry appended to `PROGRESS.md`.

## Expected file set

Expected:

- `phase101a_react_router_security_hotfix_spec.md`;
- `frontend/package.json`;
- `frontend/package-lock.json`;
- `PROGRESS.md` at closeout.

Conditional only if a verified compatibility defect requires it:

- the smallest affected frontend source file(s);
- one focused frontend regression test file/update.

Any CI workflow, backend, migration, Railway configuration, or unrelated package-file change is outside the expected set and must be treated as a scope alarm.

