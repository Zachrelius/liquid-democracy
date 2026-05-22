# Phase 35.1 Closeout — Load Test + 5x Projections (Z-Coordinated Path)

**Status:** Scoped-up — autonomously **blocked** on temporary Railway service provisioning; **runbook delivered** for Z-coordinated execution.

## What this pass shipped

1. **`docs/scalability_audit_phase35_1_runbook.md`** — full Z-coordinated runbook (9 steps, ~90 min Z time, ~$3-8 audit cost). Step-by-step from temp project provisioning through Locust run to teardown.
2. **`docs/scalability_audit_2026-05.md`** — added Phase 35.1 status block at the top explaining the deferral + the path forward.
3. **`backend/tests/test_phase_35_instrumentation.py`** — added `test_phase_35_1_env_gate_falsy_default` (defense-in-depth against accidental prod instrumentation enable; verifies all common falsy values keep the gate off). 6/6 instrumentation tests pass.

## Why the load test couldn't run autonomously

Phase 35.1 D3 requires "Spin up new Railway project from master branch." D11 explicitly forbids prod-load-testing as a fallback. The `RAILWAY_TOKEN` in the project `.env` is project-scoped to `keen-learning` — verified via `railway init -n <name>` returning `Unauthorized` and `railway list` returning the same. The token only authorizes operations within the existing project; cannot provision new projects or list workspaces.

Per Phase 35 D6, the documented fallback ("quiet-hours testing on prod with explicit Z notification") is not authorized by Phase 35.1 D11.

The honest conclusion: **completing this pass requires either (a) Z-coordinated execution via the runbook, or (b) an account-scoped Railway API token shared with the agent.** I chose (a) since (b) would require Z deciding whether to expand the agent's blast radius — that's an explicit policy choice, not an implementation detail.

## Per-cluster status

| Cluster | Status | Notes |
|---|---|---|
| B1 — Temp Railway service | BLOCKED | Token scope. Runbook step 1 covers this. |
| B2 — Seed 1x + 5x | BLOCKED on B1 | Runbook steps 3 + 5 cover this. |
| C1 — 1x load test | BLOCKED on B1 | Runbook step 4. |
| C2 — 5x load test | BLOCKED on B1 | Runbook step 6. |
| C3 — Railway dashboard correlation | BLOCKED on B1 | Runbook step 7. |
| E1 — Audit doc update | PARTIAL | Phase 35.1 status block added; load-test sections (§3-§5) remain code-review-derived; updated when Z runs the runbook. |
| D-cluster bundled fixes | N/A | Spec D9: only if load surfaces hotspots. Load didn't run. |
| T regression tests | DONE | 1 defensive test added (env-gate falsy default). 6/6 pass. |

## Cost projections (unchanged from Phase 35)

The runbook execution updates these with measured numbers. Until then:

- **1x current state:** $4.51/mo (May 2026 actual) pre-Phase-35-fixes; projected ~$1.50-2.00/mo post-fix.
- **5x extrapolated:** ~$5-8/mo post-fix (code-review-derived, no load data).
- **10x extrapolated:** ~$15-25/mo pre-fix; ~$4-8/mo post-fix (with linear-scaling caveat).
- **Hobby exit threshold:** ~3-5x current scale post-fix; pre-fix was already close to exit.

These projections will be revised in `docs/scalability_audit_2026-05.md` once Z runs the runbook and replaces them with measured values.

## Files added/modified

- `docs/scalability_audit_phase35_1_runbook.md` (NEW — the runbook itself)
- `docs/scalability_audit_2026-05.md` (Phase 35.1 status block added to top)
- `backend/tests/test_phase_35_instrumentation.py` (defensive env-gate test added)

## Branch + commits

Branch: `phase-35-1/load-test-and-projections`.
Master commit chain expected: 1 commit on this branch + merge.

## Production deploy status

No application code changes this pass. Only docs + a test addition. Push to master will trigger Railway deploy as a no-op (no behavioral change). 6th consecutive clean auto-deploy expected.

## Temporary Railway service cost + teardown

**Not applicable** — no service was provisioned. Audit budget unspent.

## Auto-deploy reliability data point

Continues clean. No deploy mechanics issue this pass since no application code changed.

## New tech debt

- **Item 84 (Tier 2):** project-scoped `RAILWAY_TOKEN` blocks autonomous load-test workflows that require provisioning isolated environments. If Z wants future audits to be autonomous, generate an account-scoped token (or grant the agent's session a separate workspace) and store it as `RAILWAY_ACCOUNT_TOKEN` alongside the project-scoped one. Without this, every multi-project ops task needs Z-coordinated execution.

## Recommendation

Either:
- **Z runs the runbook** at a time convenient — measurement signal lands in audit doc.
- **OR** Z escalates the agent's Railway access (account-scoped token) and a future agent session completes the run autonomously.

Either path closes the load-test gap. The static-analysis fixes Phase 35 already shipped are the highest-impact memory wins regardless of whether the load test runs; the load test refines projections rather than blocking decisions.
