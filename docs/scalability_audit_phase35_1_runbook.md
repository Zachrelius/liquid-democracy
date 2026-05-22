# Phase 35.1 Load Test Runbook (Z-Coordinated)

**Purpose:** complete the B + C clusters from Phase 35 / 35.1 — synthetic
1x + 5x load against a temporary Railway service.

**Why this runbook exists:** the autonomous code-team agent attempted to
provision a temporary Railway project per Phase 35.1 spec D3 and was
blocked by the `RAILWAY_TOKEN` scope. The token in the project `.env` is
a **project-scoped token** (lets the agent operate within the existing
`keen-learning` project but not create new projects or list workspaces).
`railway init -n <name>` returns `Unauthorized`. Phase 35.1 D11
explicitly requires prod isolation, so the spec's documented fallback
("quiet-hours testing on prod" from Phase 35 D6) is not authorized for
this pass.

This runbook is the Z-coordinated path forward. Following the steps below
produces the measurements Phase 35.1 was designed to capture.

**Estimated time:** ~90 minutes end-to-end. Estimated cost: ~$3-8 in
Railway audit usage (lower than the $5-10 Phase 35 estimate because the
Phase 35 fixes reduced per-hour memory cost).

---

## Step 1 — Provision a temporary Railway project (Z, dashboard, ~10 min)

1. Open https://railway.app and click **New Project**.
2. Name it something obvious like `liquid-democracy-audit-2026-05`.
3. Add three services mirroring prod:
   - **backend** — connect to the same GitHub repo (`Zachrelius/liquid-democracy`), root directory `backend`, branch `master`.
   - **frontend** — same repo, root directory `frontend`, branch `master`.
   - **Postgres** — Railway's managed Postgres plugin.
4. Set env vars on `backend`:
   - `DATABASE_URL` — link to the new Postgres service's connection string.
   - `SECRET_KEY` — generate a fresh random string (audit-environment only; do not reuse prod secret).
   - `IS_PUBLIC_DEMO=true`
   - `DEMO_RESET_TRIGGER_TOKEN` — any value (used by the audit's seed scripts).
   - `SCALABILITY_AUDIT_INSTRUMENTATION_ENABLED=true` — this is the Phase 35 env gate that turns on per-request + per-tick JSON logging.
   - `WORKERS=1` — already the new default in `start.sh` post-Phase-35.
5. Wait for the first deploy to complete on all three services.
6. Provision a Railway domain for the backend service. Note the URL — you'll need it for the load test steps.

## Step 2 — Generate a project-scoped token for the temp project (Z, dashboard, ~2 min)

In the temp project's Settings → Tokens, generate a new token. Save it locally; you'll export it as `RAILWAY_TOKEN` when running CLI commands against this project.

## Step 3 — Seed 1x baseline (Z's terminal, ~3 min)

From the temp project's backend service, trigger demo reset to seed the three demo orgs (Cedar Hollow + AFSCME + Coalition) at 1x scale:

```bash
# Use the temp project's backend URL + the DEMO_RESET_TRIGGER_TOKEN you set.
TEMP_URL=https://<temp-backend>.up.railway.app
curl -X POST -H "X-Demo-Reset-Token: <token>" $TEMP_URL/api/demo/trigger-reset
```

Verify success: response should include `success: true` and `rows_seeded > 4000`.

## Step 4 — Run 1x load test (your terminal or an isolated dev machine, ~35 min)

Install Locust:
```bash
pip install locust
```

Run against the temp service:
```bash
cd backend
TEMP_URL=https://<temp-backend>.up.railway.app
PHASE35_USERNAME=marcus_pham \
PHASE35_ORG_SLUG=demo-cedar-hollow \
locust -f scripts/phase35_locustfile.py \
  --host $TEMP_URL \
  --headless -u 5 -r 1 --run-time 30m \
  --csv phase35_1x
```

Output: `phase35_1x_stats.csv`, `phase35_1x_failures.csv`, `phase35_1x_stats_history.csv` in the working dir.

**Capture in parallel:** open the Railway dashboard for the temp project. Note the **Memory** and **CPU** graphs for the backend service during the 30-minute window. Screenshot or note the peak + average values.

## Step 5 — Seed synthetic 5x bible (Z's terminal, ~5 min)

From the temp project's backend container (Railway → backend service → "Open Shell"), or via a one-off script running locally with the temp project's `DATABASE_URL`:

```python
# In the temp project's backend container:
python -c "
from scripts.phase35_synthetic_5x_bible import build_5x_bible
from demo_content.seed_pipeline import seed_org_from_bible
from database import SessionLocal
bible = build_5x_bible()
db = SessionLocal()
result = seed_org_from_bible(db, bible, {})
db.commit()
print('seeded:', result)
db.close()
"
```

This creates `synthetic-5x-audit` org alongside the three demo orgs. If seed fails (likely candidate: Postgres connection pool, though Phase 35 reduced it to 2+3 = 5 connections), batch the seed work — break `seed_org_from_bible` into 4 chunks of ~100 members each.

## Step 6 — Run 5x load test (your terminal, ~35 min)

```bash
PHASE35_USERNAME=syn_0000 \
PHASE35_ORG_SLUG=synthetic-5x-audit \
locust -f scripts/phase35_locustfile.py \
  --host $TEMP_URL \
  --headless -u 20 -r 2 --run-time 30m \
  --csv phase35_5x
```

Same dashboard capture during the window. If RAM hits the Hobby cap (~512MB on the backend service), note when it happened — that's the bottleneck data point.

## Step 7 — Capture instrumentation logs (Z's terminal, ~5 min)

The temp service has `SCALABILITY_AUDIT_INSTRUMENTATION_ENABLED=true`, so per-request + per-tick JSON lines are in stdout. Capture from Railway logs:

```bash
RAILWAY_TOKEN=<temp-project-token> railway logs --service backend > phase35_logs_combined.txt
```

Filter for the audit lines:
```bash
grep '"audit": "request"' phase35_logs_combined.txt > phase35_requests.jsonl
grep '"audit": "tick"' phase35_logs_combined.txt > phase35_ticks.jsonl
```

## Step 8 — Analyze + update audit doc (~20 min)

For each JSONL file, aggregate by endpoint / tick name:
- p50, p95, p99 of `elapsed_ms`
- Mean `query_count` per endpoint
- Mean `rss_mb` (gives memory profile per request type)
- For ticks: peak_rss_mb at 1x vs 5x

Update `docs/scalability_audit_2026-05.md` §4 ("5x synthetic projection") with the measured numbers, replacing the code-review-derived projections. Same for the cost projections + Hobby exit threshold.

## Step 9 — Tear down (Z, dashboard, ~2 min)

In the temp Railway project Settings → Danger Zone → Delete project.

Confirm the audit usage cost in the prod project's billing dashboard didn't increase (the temp project's cost is tracked separately).

---

## Anti-checklist

- **Do not** run synthetic load against prod (`liquiddemocracy.us`). Phase 35.1 D11 requires prod isolation.
- **Do not** enable `SCALABILITY_AUDIT_INSTRUMENTATION_ENABLED` on prod. The temp service is the only environment that should have it on for this pass.
- **Do not** seed the synthetic 5x bible against prod's Postgres. It's audit-only data.

---

## What an autonomous re-attempt would need

If a future agent session is to complete this autonomously (rather than Z-coordinated), it needs:
1. **An account-scoped Railway API token** (or a token with `project:create` scope). The current project-scoped token can't provision new projects.
2. **A budget gate** — a way to programmatically read the temp service's billing meter and tear down at $10 hard cap.
3. **Either:** Railway-CLI commands to seed via SSH-into-container, OR a local seed pipeline that talks to the temp project's `DATABASE_URL` from the agent's environment.
