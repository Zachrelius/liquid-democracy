# Deployment Guide

## Quick Start (Docker Compose)

1. **Clone the repository**
   ```bash
   git clone https://github.com/your-org/liquid-democracy.git
   cd liquid-democracy
   ```

2. **Configure environment variables**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and set secure values for:
   - `DB_PASSWORD` — PostgreSQL password (use a long random string)
   - `SECRET_KEY` — JWT signing key (use a different long random string)
   - `BASE_URL` — your domain, e.g. `https://vote.yourorg.org`
   - `CORS_ORIGINS` — must match your frontend URL, e.g. `["https://vote.yourorg.org"]`
   - SMTP settings if you want email notifications (see Environment Variables Reference below)

3. **Start the services**
   ```bash
   docker-compose up -d
   ```
   This starts PostgreSQL, the backend API, and the frontend (nginx).

4. **Access the application**
   - Frontend: http://localhost (or your configured domain)
   - API health check: http://localhost:8000/api/health

5. **Create your first account**
   Navigate to the app and register. The first user can set up the organization.

## Cloud Deployment

### Railway — Deploying the EA Demo to liquiddemocracy.us

This section is a start-to-finish walkthrough for deploying the public EA demo to `liquiddemocracy.us`. It assumes the reader is comfortable with a web dashboard and editing DNS records, but has no prior Railway experience. If you've deployed to Railway before, skim past the explanatory notes.

**Prerequisites (one-time, Z does these):**
- A GitHub account with push access to `github.com/Zachrelius/liquid-democracy`.
- A Gmail account that will send verification emails. 2-Step Verification turned on. A 16-character App Password generated (see "Setting Up SMTP (Gmail App Password)" below).
- Ownership of `liquiddemocracy.us` with access to the DNS settings in your domain registrar.

#### Step 1 — Create a Railway account

1. Go to [railway.com](https://railway.com) and sign up (GitHub OAuth is the easiest path — it also pre-authorizes repo access for deploys).
2. Railway's free Hobby plan has a monthly usage allowance sufficient for a low-traffic demo. You can always upgrade later; the demo should never hit the free-tier ceiling.

#### Step 2 — Create a new project, provision PostgreSQL

1. From the Railway dashboard, click **New Project** → **Deploy PostgreSQL** (or **Empty Project** and add PostgreSQL after — either works).
2. Once the Postgres service is running, open it. Note that Railway auto-generates a `DATABASE_URL` connection string and stores it as a project-level shared variable. You'll reference this from the backend service in Step 3.

#### Step 3 — Deploy the backend

1. In the same project, click **New** → **GitHub Repo** and pick `Zachrelius/liquid-democracy`. Grant Railway access if prompted.
2. Railway scans the repo and finds multiple Dockerfiles. Configure this service as the **backend**:
   - **Root directory:** `backend`
   - **Watch paths:** `backend/**` (so frontend-only commits don't rebuild backend)
   - **Start command:** leave blank — the Dockerfile's `CMD ["./start.sh"]` handles it.
3. Under **Variables**, add the following. For variable values that live on the Postgres service (like `DATABASE_URL`), use Railway's shared-variable reference syntax `${{Postgres.DATABASE_URL}}` so Railway injects the right value.

    | Variable | Value | Notes |
    |----------|-------|-------|
    | `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` | Auto-linked from Postgres service |
    | `SECRET_KEY` | `<run: openssl rand -hex 32>` | 64-char random hex |
    | `DEBUG` | `false` | Never `true` in production |
    | `IS_PUBLIC_DEMO` | `true` | Enables demo-login + persona picker |
    | `BASE_URL` | `https://liquiddemocracy.us` | Used in verification email links |
    | `CORS_ORIGINS` | `["https://liquiddemocracy.us"]` | JSON array |
    | `SMTP_HOST` | `smtp.gmail.com` | Gmail SMTP server |
    | `SMTP_PORT` | `587` | Gmail STARTTLS port |
    | `SMTP_USER` | `<your-gmail-address>` | The account sending verification emails |
    | `SMTP_PASSWORD` | `<16-char App Password>` | From "Setting Up SMTP" below |
    | `FROM_EMAIL` | `Liquid Democracy <your-gmail-address>` | RFC-5322 From header |

4. Click **Deploy**. The first build will take 3-5 minutes (pip install on a fresh image is the slow step).
5. For an initial deployment only, open the service → **Settings** → **Networking** → **Generate Domain** so Railway assigns a temporary public `*.up.railway.app` URL. Keep it only through the private-network cutover checks below, then remove it. The backend is not intended to remain publicly addressable.
6. Check **Logs** for a successful startup. On a brand-new database you should see `Fresh database detected — bootstrapping via create_all + stamp head.` then `Starting application…`. On a redeploy of an existing DB you should see `Alembic-stamped DB detected — applying pending migrations…` instead. If you see a traceback, paste it into `docker compose logs backend` locally to compare — most startup errors are env-var-related.

> **⚠ Container path convention (read before running `railway ssh` / `railway run`).** Because the backend service is configured with `Root directory: backend`, Railway treats `backend/` as the Docker build context root. The Dockerfile's `COPY . .` then copies `backend/*` (relative to that root) into `/app/`. Net effect: the in-repo path `backend/scripts/foo.py` becomes the container path `/app/scripts/foo.py` — the `backend/` prefix is **collapsed**. In `railway ssh` and `railway run` commands, use container paths (e.g., `python scripts/foo.py`), NOT in-repo paths (`python backend/scripts/foo.py` will fail with `No such file or directory`). Past closeouts that document `railway run python backend/scripts/...` are wrong — use `scripts/...` from `/app`.

#### Step 4 — Deploy the frontend

1. In the same project, click **New** → **GitHub Repo** and pick the same `liquid-democracy` repo. This is a second service pointing at the same repo.
2. Configure as the **frontend**:
   - **Root directory:** `frontend`
   - **Watch paths:** `frontend/**`
3. Under **Variables**, set `BACKEND_URL` to the backend's internal Railway URL from Step 3. nginx's template mechanism substitutes this at container start into the `/api/`, `/ws/`, and `/uploads/` proxy directives. Valid forms:
   - **Production (private networking):** `BACKEND_URL=http://${{backend.RAILWAY_PRIVATE_DOMAIN}}:8000` — replace `backend` with the exact Railway backend service name if it differs. Using a Railway reference variable keeps the private hostname authoritative. Internal HTTP is correct because Railway's private mesh is encrypted.
   - **Equivalent resolved form:** `BACKEND_URL=http://backend.railway.internal:8000` — useful for diagnosis; prefer the reference-variable form in the service configuration.
   - **Fallback (public URL):** `BACKEND_URL=https://<backend-service>.up.railway.app` — works if private networking isn't configured. Slightly slower, traffic goes through Railway's edge.
4. Click **Deploy**. Railway builds the frontend (nginx serves `/app/dist`).
5. **Settings** → **Networking** → **Generate Domain** to get a `*.up.railway.app` URL for the frontend. Visit it — you should see the landing page. The `/api/*` calls should return real data (try visiting `<your-frontend-url>/api/health` — it should return JSON from the backend).

#### Step 4a — Make the backend private (Phase 91a)

The frontend is the sole public gateway. Browsers keep using same-origin
`/api/`, `/ws/`, and `/uploads/`; only nginx's upstream changes.
The nginx container enables the official image's local-resolver discovery and
re-resolves the private backend hostname at request time with a 10-second
validity window. Backend private-IP changes therefore do not require a
frontend restart; brief in-flight failures may still retry on the next request.

1. Deploy the dual-stack backend build while its temporary public domain still
   exists. In backend logs, confirm the Railway-documented `--host ""` bind
   reaches application startup and `GET /api/health` succeeds through the
   temporary backend URL.
2. On the frontend service, set
   `BACKEND_URL=http://${{backend.RAILWAY_PRIVATE_DOMAIN}}:8000` and redeploy.
   Do not remove the backend domain yet.
3. Through the **frontend** public hostname, verify:
   - `/api/health` returns the backend health JSON;
   - an unauthenticated API route and login both behave normally;
   - an authenticated organization/proposal page loads;
   - `/uploads/<known-avatar-path>` serves the image;
   - a `/ws/` connection upgrades successfully;
   - `POST /api/webhooks/didit` remains routed to the backend (the provider URL
     remains `https://www.liquiddemocracy.us/api/webhooks/didit`).
4. Inspect frontend logs for upstream connection or DNS failures. Then
   redeploy **only the backend**, leaving the frontend deployment untouched.
   Wait at least 10 seconds for the resolver window and repeat the frontend
   API, upload, and WebSocket checks. This proves nginx followed the backend's
   new private IP without being restarted.
5. Once those checks pass, remove the backend service's Railway public domain
   under **Settings → Networking**. Confirm the backend has no custom domain
   or TCP proxy exposure. Do not change registrar/Cloudflare DNS.
6. Repeat the frontend health, login, application, upload, WebSocket, and clean
   browser-console checks. Confirm the former backend `*.up.railway.app`
   hostname is unreachable.

The backend retains `--forwarded-allow-ips '*'` because public-domain removal
eliminates direct Internet access and the frontend is the only intended
caller. Other services in the same Railway environment remain able to reach
the private backend, so this is residual lateral-trust debt: a compromised
sibling service could forge proxy headers. If the backend is ever made public
again, forwarded-header trust must be restricted before treating IP-based
rate limits or audit addresses as authoritative. The frontend proxy extracts
Railway's edge-controlled first `X-Forwarded-For` entry and replaces the chain
with that single address (falling back to its direct peer for local Docker
traffic). It deliberately does not rely on `X-Real-IP`, which Railway has
documented can temporarily identify its CDN edge rather than the client.
nginx sends the resolved upstream as
the HTTP `Host` (required for Railway's public-edge rollback routing) while
preserving the browser-facing public hostname separately in
`X-Forwarded-Host`.

**Rollback:** first regenerate a backend Railway public domain. Capture the
actual newly-issued `https://…up.railway.app` URL (do not assume Railway reused
the former hostname) and verify `<new-url>/api/health` directly. Only after that
check passes, change the frontend's `BACKEND_URL` to the captured URL and
redeploy the frontend. Re-run same-origin health/login/upload checks before
treating rollback as complete. Keep the private-domain value recorded for the
subsequent diagnosis; no database, registrar DNS, or secret rollback is
involved.

#### Step 5 — Custom domain (liquiddemocracy.us)

Railway handles HTTPS automatically via Let's Encrypt once DNS is pointed correctly.

1. In the **frontend** service → **Settings** → **Networking** → **Custom Domain** → enter `liquiddemocracy.us` (and `www.liquiddemocracy.us` as a second entry if you want both).
2. Railway shows you a DNS target — something like `<random>.up.railway.app` — and tells you which record type to add (usually CNAME for subdomains, A/ALIAS for root/apex domains).
3. **In your domain registrar's DNS panel** (Namecheap, Cloudflare, GoDaddy, etc.):
   - **For the root `liquiddemocracy.us`:** most registrars require an ALIAS or ANAME record (not a plain CNAME — CNAMEs can't coexist with the mandatory root-zone records). If your registrar doesn't support ALIAS, use an A record with the IP Railway provides. Cloudflare-proxied DNS (orange cloud) is an alternative that works well.
   - **For `www.liquiddemocracy.us`:** CNAME → the `*.up.railway.app` target Railway shows you.
   - A CNAME record is "treat this name as an alias for that name." An A record is "this name resolves to this IPv4 address." You'll add whichever Railway's setup screen instructs.
4. DNS propagation usually takes 5-30 minutes. You can check with `dig liquiddemocracy.us` or [dnschecker.org](https://dnschecker.org).
5. Once Railway detects the correct DNS, it auto-provisions the Let's Encrypt certificate (another ~1-2 minutes). The custom domain flips from "Pending" to "Active."
6. Visit `https://liquiddemocracy.us` — you should see the landing page with a valid HTTPS lock icon.

#### Step 6 — Seed demo data

One-time operation after first deploy. See "Demo Data Management" below for the command.

#### Step 7 — End-to-end smoke test

From a fresh browser (incognito so no stored tokens):
1. Visit `https://liquiddemocracy.us` — landing page renders.
2. Click **Try the Demo** → persona picker renders.
3. Click "Sign in as alice" → lands on `/orgs`, picks demo, navigates to `/{demo-slug}/proposals` with seeded content visible. (Phase 11: path-based org URLs.)
4. Log out. Click **Register your own demo account** → fill in an email you control.
5. Check the inbox — a verification email from `Liquid Democracy <…>` should arrive within 30 seconds.
6. Click the verification link → browser lands on the verified state, auto-joined to the demo org.
7. Cast a vote on a proposal, then create a delegation. Log out and log in again — state persists.

If any of this fails, check `Logs` on the relevant Railway service. A complete failure of email delivery is almost always an SMTP credential or Gmail App Password issue (see Troubleshooting below).

### Fly.io

1. Install the [Fly CLI](https://fly.io/docs/getting-started/installing-flyctl/).

2. **Deploy the backend:**
   ```bash
   cd backend
   fly launch --name your-app-api
   fly postgres create --name your-app-db
   fly postgres attach your-app-db
   fly secrets set SECRET_KEY="your-secret" CORS_ORIGINS='["https://your-app.fly.dev"]' BASE_URL="https://your-app.fly.dev"
   fly deploy
   ```

3. **Deploy the frontend:**
   ```bash
   cd frontend
   fly launch --name your-app-web
   fly deploy
   ```
   Update `nginx.conf` to proxy API requests to `your-app-api.internal:8000`.

### VPS with Docker

1. Provision a VPS (Ubuntu 22.04+ recommended) with at least 1GB RAM.

2. Install Docker and Docker Compose:
   ```bash
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker $USER
   ```

3. Clone the repo, configure `.env`, and run:
   ```bash
   docker-compose up -d
   ```

4. Set up a reverse proxy (nginx or Caddy) for HTTPS — see the HTTPS section below.

## HTTPS Setup

### Option A: Caddy (simplest)

Caddy automatically provisions and renews Let's Encrypt certificates.

Install Caddy and create `/etc/caddy/Caddyfile`:
```
vote.yourorg.org {
    reverse_proxy localhost:80
}
```

Then: `sudo systemctl restart caddy`

### Option B: Nginx + Certbot

1. Install certbot:
   ```bash
   sudo apt install certbot python3-certbot-nginx
   ```

2. Create an nginx site config at `/etc/nginx/sites-available/liquid-democracy`:
   ```nginx
   server {
       listen 80;
       server_name vote.yourorg.org;

       location / {
           proxy_pass http://localhost:80;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
   }
   ```

3. Enable the site and obtain a certificate:
   ```bash
   sudo ln -s /etc/nginx/sites-available/liquid-democracy /etc/nginx/sites-enabled/
   sudo nginx -t && sudo systemctl reload nginx
   sudo certbot --nginx -d vote.yourorg.org
   ```

   Certbot will modify the nginx config to add SSL and set up auto-renewal.

### Option C: Docker with nginx-proxy + acme-companion

Add to your `docker-compose.yml`:
```yaml
services:
  nginx-proxy:
    image: nginxproxy/nginx-proxy
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /var/run/docker.sock:/tmp/docker.sock:ro
      - certs:/etc/nginx/certs
      - html:/usr/share/nginx/html

  acme-companion:
    image: nginxproxy/acme-companion
    volumes_from:
      - nginx-proxy
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - acme:/etc/acme.sh

  frontend:
    environment:
      VIRTUAL_HOST: vote.yourorg.org
      LETSENCRYPT_HOST: vote.yourorg.org
      LETSENCRYPT_EMAIL: admin@yourorg.org
```

## Backup and Restore

### Backup PostgreSQL

```bash
# Create a backup
docker-compose exec db pg_dump -U ${DB_USER} liquid_democracy > backup_$(date +%Y%m%d_%H%M%S).sql

# Or use compressed format
docker-compose exec db pg_dump -U ${DB_USER} -Fc liquid_democracy > backup_$(date +%Y%m%d_%H%M%S).dump
```

### Automated Backups (cron)

Add to crontab (`crontab -e`):
```
# Daily backup at 2 AM
0 2 * * * cd /path/to/liquid-democracy && docker-compose exec -T db pg_dump -U liquid_democracy liquid_democracy | gzip > /backups/ld_$(date +\%Y\%m\%d).sql.gz
```

### Restore from Backup

```bash
# From SQL file
docker-compose exec -T db psql -U ${DB_USER} liquid_democracy < backup.sql

# From compressed dump
docker-compose exec -T db pg_restore -U ${DB_USER} -d liquid_democracy --clean backup.dump
```

### Restore to a Fresh Database

```bash
docker-compose down
docker volume rm liquid-democracy_pgdata
docker-compose up -d db
# Wait for PostgreSQL to start
sleep 5
docker-compose exec -T db psql -U ${DB_USER} liquid_democracy < backup.sql
docker-compose up -d
```

## Setting Up Email Delivery

The backend supports two delivery backends, picked automatically:

1. **Resend (preferred, required on Railway)** — HTTP API, bypasses all SMTP blocks. Use this for the demo deployment.
2. **Gmail SMTP** — works on most dev/self-hosted setups, but Railway's network blocks outbound TCP to Gmail's SMTP ports (both 587 and 465). Keep as a fallback for local dev / non-Railway hosts.

When `RESEND_API_KEY` is set, the backend uses Resend and ignores the SMTP vars. When it's empty and `SMTP_HOST` is set, the backend uses SMTP. When both are empty, emails are logged to stdout (dev mode).

### Option A — Resend (recommended for Railway)

**Z performs these steps personally** — signup, domain verification, API key generation.

1. Sign up at [resend.com](https://resend.com) (Google OAuth is fastest).
2. Domains → Add Domain → enter `liquiddemocracy.us`.
3. Resend shows 3 DNS records (MX, SPF/TXT, DKIM). Add them in the same registrar's DNS panel where the Railway CNAME lives. Propagation usually within 5 min.
4. Wait for Resend's domain status to go green (auto-checks).
5. API Keys → Create API Key → "Full access" or "Sending access" → copy the `re_...` key.
6. **Add to Railway backend service variables:**
   - `RESEND_API_KEY=re_...`
   - `FROM_EMAIL=Liquid Democracy <onboarding@liquiddemocracy.us>` (any address on the verified domain)
   - (Leave the SMTP_* vars — they'll be ignored when `RESEND_API_KEY` is set, but keep them populated so switching fallback is a single env var flip.)
7. Redeploy (Railway auto-redeploys on env var change).
8. Test: register a fresh account; verification email arrives in ~5 seconds.

**Free-tier limits.** 100 emails/day, 3,000/month — far beyond demo needs. Upgrade only if volume spikes post-pilot.

### Option B — Gmail SMTP (NOT on Railway)

For the demo, verification and password-reset emails are sent through a Gmail account using an App Password. This is credible for low-volume demo traffic, no dedicated mail service required.

**Z performs these steps personally** — they require access to the Google account whose address will appear in the `From:` header.

1. **Turn on 2-Step Verification.** In Google Account → Security. App Passwords aren't available until 2SV is on. Use any second-factor method you like (authenticator app is recommended).
2. **Generate an App Password.** Google Account → Security → 2-Step Verification → App passwords (may be linked as "App passwords" in the search bar if hidden). Create a new password, label it "Liquid Democracy Demo." Google displays a 16-character password with spaces — copy it verbatim, spaces and all. Google will not show it again. Paste it into a temporary note for the next step.
3. **Add to Railway backend service variables:**
   - `SMTP_HOST=smtp.gmail.com`
   - `SMTP_PORT=465` (implicit SSL — preferred on cloud providers)
   - `SMTP_USER=<your-gmail-address>` (e.g., `liquiddemocracy.qa@gmail.com`)
   - `SMTP_PASSWORD=<16-char App Password>` (Railway will preserve the spaces; Gmail accepts with or without)
   - `FROM_EMAIL=Liquid Democracy <your-gmail-address>` (the display-name prefix is what recipients see in their inbox)

   **Why port 465 and not 587?** Some cloud hosts (including some Railway tiers) block outbound TCP to port 587 but leave 465 open. Both Gmail endpoints work; the code infers TLS mode from port (465 = implicit SSL, 587 = STARTTLS). If 465 is blocked too, you'll see `SMTPConnectTimeoutError` in the backend logs and will need to switch to a transactional email provider (SendGrid, Postmark, etc.).
4. **Redeploy the backend service** so it picks up the new env vars.
5. **Test delivery:** register a fresh account on the deployed site, confirm the verification email arrives in the real inbox within ~30 seconds. If it doesn't, check the **Troubleshooting** section below for SMTP-specific guidance.

**Gmail limits.** Free Gmail sends up to ~500 emails per day. For the EA demo timeframe that's orders of magnitude more headroom than needed. If you need more, upgrade to Google Workspace or migrate to a transactional email provider (SendGrid, Postmark, SES) later.

**Security.** The App Password is a bearer credential for your Gmail account. Treat it like a production secret — only store in Railway's variable store (encrypted at rest), never commit to the repo.

## Current Deployment Status

The `liquiddemocracy.us` deployment is a **public demo run informally by the
project's founder** (Zachary). It is operated as a personal project, not by a
formal organization, and the current institutional posture is intentional for
the demo stage. Specifically:

- **No operator agreement.** There is no signed agreement governing how the
  platform is run, who has access, or what the data-handling commitments
  are. The platform behaves as the code says it behaves; the audit log
  records who did what; that is the entirety of the accountability layer
  today.
- **No independent oversight body.** No external reviewer, board, or
  ombudsperson exists to review platform-admin actions or arbitrate
  disputes. The user-facing access log
  (`GET /api/users/me/access-log`, Phase 7.5) lets users see when their
  data was accessed, but a user who disagrees with an access has no
  third-party body to escalate to.
- **No separation between platform operations and the founder's individual
  access.** The founder holds the only `is_admin=True` account and
  therefore is the sole party with platform-admin privileges as defined in
  `SECURITY_REVIEW.md` (Privileged Access Tiers). Operationally, "the
  platform" and "the founder" are the same actor.

**This is appropriate for the demo stage** — `liquiddemocracy.us` exists
to let people try out liquid-democracy concepts and inspect the codebase,
not to make binding decisions for organizations. The accountability layer
(audit log + redaction + elevation requirement + user access log) is real
and works as documented; the *institutional* layer is deliberately thin.

**Before binding decisions are made** by real organizations on the platform,
this posture would need to change. Specifically: an operator agreement
defining roles and commitments, an independent oversight body that can
review elevated audit access and arbitrate disputes, and (likely) a
separate deployment per organization with its own admin account so that no
single party holds cross-org platform-admin access.

The path forward is documented in the deferred-features roadmap. See
`future_improvements_roadmap.md`:
- "Formal Operator Agreements and Independent Oversight"
- "Encrypted Ballot Storage" (cryptographic complement to the institutional
  changes)

## Demo Data Management

The demo org (`slug=demo`) is seeded once after the first deploy. Visitor-created content persists across sessions — this is intentional for the EA-demo stage, so visitors can see each others' proposals and delegations accumulate. Auto-reset is deferred to a later phase.

### Initial seed (automatic, additive as of Phase 7C.1)

Auto-seed on boot: when `IS_PUBLIC_DEMO=true`, `backend/start.sh` runs
`seed_if_empty.py` before uvicorn starts. As of Phase 7C.1 (2026-04-27) the
seed is **additive idempotent** — it always runs, whether the users table
is empty or not, and every insert checks for existing rows by unique key
and skips if found. Re-running the seed never disturbs visitor data.

What this means in practice:

- **Fresh Railway deploy** → seed runs, populates everything from scratch.
- **Subsequent redeploys** → seed runs, finds existing rows for users /
  votes / delegations / follows / precedences, and skips each one.
  Visitor-created votes and delegations are preserved.
- **A new phase adds new demo content** (e.g., Phase 7C.1 added the
  Steering Committee STV proposal and the realistically-named voter
  cohort) → on next deploy, the additive seed picks up only the new rows
  and adds them. Older rows untouched. **No manual `docker exec` step
  needed for this** in the auto-seed path — Railway's redeploy alone
  picks it up.

Boot-log pattern after Phase 7C.1:

```
Public demo — first-time seed (empty users table)…       # only on truly empty DB
Public demo — additive seed (existing users: N)…         # on every other boot
Public demo — seed complete: {...}
```

PostgreSQL idempotency was verified end-to-end against `postgres:16-alpine`
during Phase 7C.1: 3 successive seed runs produced identical row counts
(36 users / 129 votes / 57 delegations / 30 follow_relationships / 5
delegate_profiles / 44 topic_precedences / 10 proposals / 19
proposal_options / 6 topics) with zero duplicate-key errors.

### Manually triggering an additive seed run (rarely needed)

If a phase has already deployed and you want the new seed content to land
*without* waiting for the next redeploy, run the seed in the live container:

**Option A — Railway CLI:**

```bash
railway link                # pick the project
railway run --service backend python -m seed_if_empty
```

**Option B — Railway dashboard shell** (Hobby tier doesn't have a shell;
use Option A):

```bash
# Inside the backend container:
python -m seed_if_empty
```

Expected output: `Public demo — additive seed (existing users: N)…` followed
by `Public demo — seed complete: {...}`. Existing visitor data is preserved.

### Manual reset (when you want a clean demo)

Two options depending on Railway plan:

**Option A — Railway CLI (requires `railway login`):**

```bash
railway link                # pick the project
railway run --service backend python -c "from database import engine, Base; Base.metadata.drop_all(engine); Base.metadata.create_all(engine)"
# Restart the backend service; auto-seed kicks in because users table is now empty.
railway redeploy --service backend
```

**Option B — Railway dashboard (no CLI):**

1. Railway dashboard → Postgres service → Database tab → run SQL:
   ```sql
   DROP SCHEMA public CASCADE; CREATE SCHEMA public;
   ```
2. Railway dashboard → backend service → Deployments → Restart.
3. `start.sh` will re-create the schema and auto-seed because the users table is empty.

Do this before EA events if visitor content from previous demos has accumulated beyond what you want to show. Total downtime ≈ 30 seconds.

**Note:** Because `is_public_demo=true` auto-joins new registrants to the demo org, the reset also wipes any real-user accounts. If/when a real org onboards, migrate to a separate-deployment or auto-reset-with-exclusions model before that happens.

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DB_USER` | Yes (compose) | — | PostgreSQL username |
| `DB_PASSWORD` | Yes (compose) | — | PostgreSQL password |
| `SECRET_KEY` | Yes | — | JWT signing secret (min 32 characters recommended) |
| `CORS_ORIGINS` | No | `["http://localhost:5173"]` | JSON array of allowed CORS origins |
| `BASE_URL` | No | `http://localhost:5173` | Public URL for email links |
| `IS_PUBLIC_DEMO` | No | `false` | Enables demo-login endpoint, persona-picker endpoint, and demo-org auto-join on verification. Set `true` on the demo deployment, `false` in real production. |
| `RESEND_API_KEY` | No | — | Resend API key (`re_...`). When set, the backend delivers email via Resend's HTTP API and ignores the SMTP_* vars. Preferred on Railway/other clouds where outbound SMTP is blocked. |
| `SMTP_HOST` | No | — | SMTP server hostname (ignored when RESEND_API_KEY is set; leave empty with no Resend key to log emails to console) |
| `SMTP_PORT` | No | `587` | SMTP server port |
| `SMTP_USER` | No | — | SMTP authentication username |
| `SMTP_PASSWORD` | No | — | SMTP authentication password |
| `FROM_EMAIL` | No | — | Sender email address for notifications |
| `DATABASE_URL` | Auto | — | Set automatically by docker-compose or Railway; override for external DB |
| `WORKERS` | No | `1` | Number of uvicorn worker processes |
| `DEBUG` | No | `false` | Enable debug mode (never use in production) |
| `LOG_LEVEL` | No | `INFO` | Logging level: DEBUG, INFO, WARNING, ERROR |
| `POLIS_AUTH_TOKEN` | No | — | Bearer JWT for the hosted pol.is admin API (Phase 9). When unset, the platform uses the manual-creation fallback flow — admins create a Polis on pol.is manually and paste the conversation_id into the platform. See "pol.is API integration" below. |
| `POLIS_API_BASE_URL` | No | `https://pol.is` | Base URL for the pol.is API. Override only for self-hosted Polis instances. |

## pol.is API integration (Phase 9)

The platform integrates with [pol.is](https://pol.is) for standalone deliberation artifacts. Per `phase9_polis_api_findings.md`, the hosted pol.is API uses **JWT-based authentication, not API keys**. Two prod-deploy paths:

**Path A — Manual creation flow (v1 default; works without configuration).**
- An org admin creates a conversation on `https://pol.is` themselves (using the pol.is admin UI), then pastes the `conversation_id` into the platform's create-Polis form.
- Add seed statements through pol.is's admin UI as well.
- The platform handles everything else: scope filtering, embed-iframe rendering, `data-xid` identity bridging, archival (platform-side state only — the conversation stays open on pol.is until the admin closes it there).
- `POLIS_AUTH_TOKEN` can be left unset.

**Path B — Programmatic creation (requires CompDemocracy admin token).**
- Set `POLIS_AUTH_TOKEN` to a valid pol.is admin Bearer JWT.
- The platform calls `POST /api/v3/conversations` to create the conversation, then loops over seed statements via `POST /api/v3/comments` with `is_seed=true`.
- Archival calls `POST /api/v3/conversation/close`.
- Data export proxies `GET /api/v3/dataExport`.
- Auth tokens are obtained from a pol.is admin user session (OIDC/JWT-based — there is no public API-key endpoint). Reach out to `hello@compdemocracy.org` to ask about programmatic admin access for third-party platforms.

**Failure handling.** If the pol.is API is unavailable during a programmatic Polis creation, `polis_service.py` raises `PolisAPIError` and the route is responsible for rolling back any partial platform-side rows — there will be no orphaned `polises` records on the platform side. Live participation-stats reads (`GET /api/v3/conversationStats`) fail soft to a "stats currently unavailable" badge so transient pol.is outages don't take down the Polis-detail page.

## Troubleshooting

### Backend won't start

**Check logs:**
```bash
docker-compose logs backend
```

**Common issues:**
- `connection refused` to database — the db container may not be ready yet. The healthcheck should prevent this, but you can try restarting: `docker-compose restart backend`
- Migration errors — check if there are conflicting migrations. Try `docker-compose exec backend alembic history` to see the migration chain.
- `SECRET_KEY` not set — the app will start but JWT tokens will use an insecure default. Set a real secret in `.env`.

### Database connection issues

**Verify PostgreSQL is running:**
```bash
docker-compose exec db pg_isready -U ${DB_USER}
```

**Check the readiness endpoint:**
```bash
curl http://localhost:8000/api/health/ready
```
If it returns `{"status": "error", "database": "disconnected"}`, the backend cannot reach PostgreSQL.

### Frontend shows blank page or API errors

**Check that the backend is reachable from the frontend container:**
```bash
docker-compose exec frontend wget -qO- http://backend:8000/api/health
```

**Check nginx logs:**
```bash
docker-compose logs frontend
```

### Resetting everything

```bash
docker-compose down -v   # removes containers AND volumes (deletes all data!)
docker-compose up -d --build
```

### Viewing request logs

Backend logs include a request ID (`X-Request-ID` header) for tracing:
```bash
docker-compose logs -f backend | jq .
```

To find a specific request:
```bash
docker-compose logs backend | grep "request-id-here"
```

### Org invitation links land on the homepage instead of an accept page (Phase 9.7 flow fix)

**Symptoms:** invitation email arrives (Phase 9.6 wiring is intact); recipient clicks the link; they land on the marketing homepage with no indication of what happened. If they later register through the `/register` flow with the same email address, they end up in the demo org instead of the inviting org.

**Cause:** Phase 4c shipped invitation creation/storage but never built the user-facing acceptance flow. The email link format was `/{org_slug}/join?token=` which had no matching React route — the catch-all redirected to `/`. Even if a user reached the registration page, the registration endpoint had no concept of pending invitations and Phase 6.5's `IS_PUBLIC_DEMO=true` auto-join silently routed every new account to the demo org.

**Fix (already shipped in Phase 9.7):**
- Email link format changed to `/invite/{token}` — now hits the new `InviteAccept` React page with four rendering states (unauth+new-email → register / unauth+existing-email → login / authenticated+match → accept button / authenticated+mismatch → clear error).
- `POST /api/auth/register` and `POST /api/auth/login` accept an optional `invitation_token` field. When set, validates + consumes the invitation post-auth and creates the inviting-org membership.
- `_auto_join_demo_org` (called from `verify_email`) now skips when the user is already an active member of any non-demo org. This is the load-bearing behavior change — without it, even a fixed invitation page would silently leak invited users to demo at email-verification time.
- New public endpoint `GET /api/invitations/{token}/meta` returns invitation metadata (org_name, org_slug, invited_email, role, expires_at) for the InviteAccept page to render the right state. 404 covers all "not consumable" outcomes (unknown/expired/revoked/accepted) so it can't be used for state enumeration. Rate-limited 30/min/IP via slowapi.

**Verification after any future change** that touches the invitation flow, the registration / login endpoints, or the auto-join logic:

1. Create a test invitation in any org to a fresh email address you control. Confirm the email arrives with the new `/invite/{token}` format.
2. Click the link from a logged-out browser session. Confirm you land on the InviteAccept page (not the homepage).
3. Register through the page. Confirm the new account ends up in the inviting org and **not in demo** (this is the regression that bit Z's wife pre-9.7).
4. Sign out, sign in as a different email-verified user, click a fresh invitation link to that user's email. Confirm the page renders the authenticated-accept card, not the registration form.
5. As an authenticated user with a different email, click any invitation link. Confirm the email-mismatch error renders cleanly, not a silent reassignment.

If anything diverges, check in this order:
- Is `_auto_join_demo_org`'s "skip when user is in any non-demo org" guard intact? Direct query: `select * from org_memberships where user_id=<new user id>`. Should show inviting-org-only.
- Is `_consume_invitation` being called from the right path? Check audit log for one of `invitation.accepted_via_registration`, `invitation.accepted_via_login`, `invitation.accepted_authenticated`.
- Is the meta endpoint reachable? `curl https://www.liquiddemocracy.us/api/invitations/<token>/meta` should return JSON for valid tokens.

**Backfill for existing orphaned invitations.** Phase 9.7 ships `backend/scripts/phase9_7_backfill_orphaned_invitations.py` — finds pending invitations whose target email has a registered user account, creates the missing membership, marks accepted. Idempotent. Run via `railway run python backend/scripts/phase9_7_backfill_orphaned_invitations.py` post-deploy. Reports per-row + summary (rescued / already-member / auto-join-victim observations).

### Org invitation emails created but never arrive (Phase 9.6 wiring fix)

**Symptoms:** Admin sends invitations from the Members admin page; invitations appear in the admin's invitation list with "pending" status; recipient never receives the email in inbox or spam; Railway logs do not show any Resend API call attempt.

**Cause:** The `POST /api/orgs/{slug}/invitations` and `POST /api/orgs/{slug}/invitations/{id}/resend` endpoints were committing the `Invitation` DB row but never calling `email_service.send_invitation_email()`. Wiring was missing since Phase 4c — the function existed but the call site didn't. Surfaced by Z's friend-pilot dry run; misdiagnosed initially as a Resend / DNS regression after the Cloudflare migration but the cause was unrelated to email infrastructure.

**Fix (already shipped in Phase 9.6):** both endpoints now accept `BackgroundTasks` and queue `send_invitation_email(...)` post-commit, matching the pattern used by `routes/auth.py`'s registration verification endpoint.

**Verification after any future DNS / email-infra change** that might re-expose a similar regression: send a real invitation to a controlled address (e.g., `support@liquiddemocracy.us` which forwards to Z's Gmail post-Cloudflare migration). Inbox arrival within ~30 seconds confirms end-to-end. If absent, check in this order:

1. **Is the route handler queuing the background task at all?** Grep `routes/organizations.py` for `send_invitation_email` — should appear in both `create_invitations` and `resend_invitation` as `background_tasks.add_task(send_invitation_email, ...)`.
2. **Is `RESEND_API_KEY` still set in Railway env?** A missing key falls through to console-log mode silently — the endpoint succeeds, the row is created, the recipient gets nothing, and the log shows "EMAIL (console mode)" only inside the Railway service log (easy to miss).
3. **Is `FROM_EMAIL` still pointing at a Resend-verified address?** A DNS migration that loses Resend's SPF / DKIM TXT records causes Resend to reject the send with HTTP 422. Backend logs will show "Resend API rejected send".
4. **Resend dashboard delivery log.** If Resend accepts the send but the recipient's mailbox bounces, the dashboard shows the bounce reason.

The Phase 4c wiring gap stayed undetected because the existing test suite mocked at the route-response level (asserted 201 + invitation row created); the email-send call wasn't asserted. Adding an end-to-end test would require mocking httpx; not added in this pass but flagged as tech debt.

### Verification emails not arriving on Railway (SMTP blocked)

**Symptoms:** Railway deploy logs show `SMTPConnectTimeoutError: Timed out connecting to smtp.gmail.com on port 587` (or 465). Registration succeeds (201), but no email arrives.

**Cause:** Railway's network blocks outbound TCP to Gmail's SMTP ports, on both 587 and 465. This is not a Gmail-auth issue — the TCP connection never establishes.

**Fix:** Switch to Resend's HTTP API (above, under "Setting Up Email Delivery — Option A"). HTTP traffic on 443 is never blocked. Setup is ~5 min; the backend auto-switches once `RESEND_API_KEY` is set.

### Verification emails not arriving (Gmail SMTP — for non-Railway hosts)

**Symptoms:** registration succeeds, but the inbox never receives the verification email, or Railway logs show `SMTPAuthenticationError`.

**Check, in order:**
1. **2-Step Verification is actually on** for the sending Gmail account. App Passwords are silently rejected if 2SV was turned off since the password was generated.
2. **App Password is pasted correctly.** Google shows it as `xxxx xxxx xxxx xxxx`. Both the spaced and unspaced forms work — but a missing or extra character fails.
3. **"Less secure app access" is not the issue.** That setting was deprecated; App Passwords are the correct mechanism and don't require the deprecated toggle.
4. **`SMTP_PORT=587`** with STARTTLS (which `aiosmtplib` uses by default). Don't use 465 unless you also switch the client to implicit SSL.
5. **`FROM_EMAIL`'s address must match `SMTP_USER`.** Gmail rejects send requests where the From header claims a different address than the authenticated account.
6. **Check spam/promotions folders.** Gmail's spam filter sometimes flags a brand-new sender to a brand-new recipient. Sending to a Gmail-to-Gmail recipient is usually clean; corporate filters are less predictable.
7. **Backend logs.** Railway service → Logs. Search for `smtp`, `email`, or `verification`. Exceptions there are authoritative.

### Custom domain stuck on "Pending verification" in Railway

**Symptoms:** DNS records are added but Railway won't issue the Let's Encrypt cert.

**Check, in order:**
1. **DNS propagation.** `dig liquiddemocracy.us` or [dnschecker.org](https://dnschecker.org) — confirm the record shows up in multiple geographic resolvers. Takes 5-30 minutes, occasionally longer.
2. **Record type.** For the root `liquiddemocracy.us`, you need an ALIAS/ANAME (or A record to an IP Railway provides), not a plain CNAME. Most registrars don't allow CNAME at the zone root. Check your registrar's documentation if their UI is unclear.
3. **TTL isn't blocking updates.** If you previously pointed the domain elsewhere with a long TTL, the old record may still be cached. `dig +trace liquiddemocracy.us` shows whether you're hitting the cached or authoritative answer.
4. **No conflicting records.** Remove any old A/AAAA records pointing at previous hosts before adding the Railway ones.
5. **Trigger revalidation.** In Railway's Custom Domain screen, there's usually a "Check status" or "Retry" button — click it once DNS is propagated to tell Railway to re-check.

### Demo-login endpoint returns 404 on the deployed site

**Symptoms:** persona picker cards fail with 404; `/api/auth/demo-users` also 404s.

`IS_PUBLIC_DEMO` env var is missing or set to `false` on the backend service. Set it to `true` in Railway variables and redeploy. The gate lives in both endpoints; no code change is needed.

---

## PostgreSQL Smoke Harness

**What:** `backend/scripts/pg_smoke.py` (Phase 8.6 Item 4). The standard pre-deploy check for any pass that touches the schema. Run it locally **before** merging a PR that adds an alembic revision.

**Why:** the previous smoke pattern (`create_all` + `alembic stamp head`) tells alembic "you're already at HEAD" without ever running the new migration's DDL. That's why the Phase 8.5 deploy hit a 15-minute 502: the smoke harness verified the new code worked against the resulting schema, but it never exercised the alembic upgrade path that prod would actually run on top of an existing DB. The new harness fixes that gap.

**What it does:**

1. **Fresh-DB path** — spins up a postgres:16-alpine container, runs `Base.metadata.create_all` then `alembic stamp head`. Mirrors what `start.sh` does on a brand-new container. Verifies the fresh-deploy bootstrap doesn't break.
2. **Upgrade-from-prior path** — spins up another container, stamps alembic at the **prior** revision (the migration immediately before the one being tested), then runs `alembic upgrade head` to apply the pass-under-test's migrations. This is the path that bit Phase 8.5; running it pre-deploy will surface collision-class bugs (and any other migration-ordering bug) loudly, with a real Postgres error rather than a green-stamp-head false pass.

After each path, a spot-check verifies the resulting schema (key tables exist, `alembic_version` matches head). Tear-down is automatic.

**Usage** (from `backend/`):

```bash
# Both modes (recommended for any pass that adds an alembic revision)
.venv/Scripts/python.exe scripts/pg_smoke.py

# Pin a specific prior revision (default is c5f3a2b81e07 = Phase 8 sustained-majority)
.venv/Scripts/python.exe scripts/pg_smoke.py --prior-revision <hex>

# Single mode only
.venv/Scripts/python.exe scripts/pg_smoke.py --mode fresh
.venv/Scripts/python.exe scripts/pg_smoke.py --mode upgrade

# Reuse an externally-managed PG instance instead of Docker (caller provides empty DB)
.venv/Scripts/python.exe scripts/pg_smoke.py --reuse-pg-url postgresql://user:pw@host:5432/db
```

**Requires:** Docker on PATH (or `--reuse-pg-url`). Exit code 0 == PASS for all requested modes. Non-zero == FAIL with traceback.

**Adopt-this-pattern checklist for the next pass that adds a migration:**

1. Bump `--prior-revision`'s default in `pg_smoke.py` to the current head (i.e., the revision that is now the "prior" for your new migration).
2. Add a column / table check in `_smoke_spot_check` that asserts your pass's schema additions actually landed.
3. Run `pg_smoke.py` with both modes locally before opening the PR. Both must PASS. If `upgrade` fails, the migration has an ordering bug — fix it before deploy, do not ship-and-pray.

---

## Org Creation Friction Model (Phase 9.5)

The platform allows any authenticated user to create an org by default — the in-person pilot recruitment scenario depends on no admin-approval bottleneck. Instead, four layers of friction sit in front of `POST /api/orgs`. They run in this order; the first one that fails is the user-visible error.

### The four gates

1. **Platform mode (kill switch).** The `platform_settings.org_creation_mode` row stores either `open` (default) or `approval_required`. When `approval_required`, every create request returns `403` with detail `"Org creation is temporarily paused — please contact support@liquiddemocracy.us"`. **Tool of last resort.** Flip it during an active spam attack while you investigate; do not leave it set as a routine state.

2. **Email verification.** The user must have `email_verified=True`. If not, returns `403` with detail `"Please verify your email before creating an organization"`. The frontend renders this with a "Resend verification email" button. This is the **primary spam filter** — free protection since email verification is already required for voting and delegation.

3. **Per-user lifetime cap.** Each user has an effective limit equal to `User.org_creation_limit` if set, else the platform default `3`. The check counts orgs the user owns (`OrgMembership.role == 'owner'`); if `count >= effective_limit`, returns `403` with detail `"You have created the maximum number of organizations (N). Contact support@liquiddemocracy.us if you need more."`. One legitimate user rarely creates more than three orgs; the support-contact path is the manual override without making approval the default.

4. **Platform-wide rate limit.** Counts `org.created` audit events in the last hour. If `>= 20`, returns **`429`** (transient, not 403) with detail `"The platform is processing many organization-creation requests right now — please try again in a few minutes."`. Sits well above realistic legitimate volume (1-2/day) but caps blast radius of a mass-creation attack.

### Audit enrichment

Every successful `org.created` event records:
- `creator_email_verified_age_seconds` — time between user's email verification and now (helps spot "verified-and-immediately-created" patterns)
- `platform_org_creation_hour_count` — platform-wide org count in the past hour at moment of creation
- `creator_user_agent` — for spam-pattern correlation
- `ip_address` — already captured via existing `request.client.host`

These don't enforce anything; they're the data foundation for the deferred monitoring layer.

### Tuning the gates

Three admin endpoints (all gated `is_admin=True`):

```bash
# Read current settings
GET /api/admin/platform-settings

# Flip the kill switch (or any platform setting)
PATCH /api/admin/platform-settings
Body: {"key": "org_creation_mode", "value": "approval_required"}

# Lift a specific user's per-user cap (or set lower; null restores default)
PATCH /api/admin/users/{user_id}/org-creation-limit
Body: {"limit": null}        # restore platform default of 3
Body: {"limit": 100}         # bump to 100
Body: {"limit": 0}           # block this user from creating any
```

All three are audited — `platform_settings.changed` and `user.org_creation_limit_changed` events with `old_value`/`new_value` pairs.

### Direct DB edits (emergency / no admin user available)

If the admin endpoints aren't usable for some reason, both gates can be flipped via direct SQL:

```sql
-- Flip the kill switch on
UPDATE platform_settings SET value = '"approval_required"' WHERE key = 'org_creation_mode';
-- ... and back off
UPDATE platform_settings SET value = '"open"' WHERE key = 'org_creation_mode';

-- Lift Z's account cap (or any user's)
UPDATE users SET org_creation_limit = NULL WHERE username = 'zach';   -- restore default 3
UPDATE users SET org_creation_limit = 100 WHERE username = 'zach';    -- bump to 100
```

Note `value` on `platform_settings` is JSON-typed, so string values need their JSON quoting (`'"approval_required"'` not `'approval_required'`).

### Recovery path: what to do if mass spam ever happens

1. **Flip the kill switch first.** `PATCH /api/admin/platform-settings` body `{"key": "org_creation_mode", "value": "approval_required"}`. Buys time without losing any in-flight legitimate creations.
2. **Investigate the audit log.** `SELECT * FROM audit_log WHERE action = 'org.created' AND timestamp > now() - interval '24 hours'` — look at IP addresses, user-agent strings, account email-verification ages, org-name patterns.
3. **Surgical response.** Cap the offending users' `org_creation_limit` to 0; consider raising the rate limit or restoring `open` mode if the attack signature is identifiable enough to filter by other means.
4. **Restore `open` mode** when you're confident the attack vector is closed.

### Deferred monitoring (Phase 9.7 / Phase 10)

This pass deliberately ships only the manual kill switch + the audit enrichment that will feed monitoring. **Anomaly detection, email alerts, and automatic kill-switch triggering are out of scope.** A follow-up pass should add:

- Hourly background job querying audit log for spam patterns (>5 orgs/hour platform-wide, same-IP-multiple-accounts, gibberish org names, sub-60s-verify-then-create patterns). Email alerts to `support@liquiddemocracy.us`.
- Admin dashboard view of org-creation activity (last 24h / 7d / 30d, per-user, rate-limit utilization, current settings with toggle controls).
- Auto-pause-with-admin-override at a higher threshold (e.g., 20+ orgs/hour) — flip to `approval_required` automatically and email Z.
- "Create your own org" invite tokens for in-person recruitment scenarios where the prospect would be over their per-user cap.

Without this layer, the kill switch is a **recovery tool, not a defense.** Layer 4 (the rate limit) is the only automatic protection. Build the monitoring layer when there's evidence it's needed.

---

## Avatars and uploaded files (Phase 9.8)

Phase 9.8 added user profile pictures. Uploaded avatars are stored on the backend container's local filesystem and served by FastAPI's `StaticFiles` mount.

### Storage layout

- **Disk path:** `backend/uploads/avatars/{user_id}/128.jpg` and `backend/uploads/avatars/{user_id}/48.jpg`. Two sizes are written per upload — 128×128 for graph nodes / profile cards, 48×48 for nav and inline use. Both are JPEG quality 85 regardless of upload format (Pillow handles the resize + format conversion).
- **DB column:** `users.avatar_url` (nullable). When null, the frontend renders the deterministic-color initials fallback. When set, it's the relative path under `/uploads/...` for the 128 size.
- **HTTP mount:** FastAPI mounts `backend/uploads/` at `/uploads/...` (no auth — these are public-readable by design, like any other profile picture). The frontend nginx config and Vite dev proxy both forward `/uploads/...` to the backend; the nginx block is intentionally placed BEFORE the static-asset cache rule so `.jpg` URLs route to the backend rather than 404 from the SPA build directory.

### Upload contract

- `POST /api/users/me/avatar` — multipart, content-type whitelist (`image/jpeg`, `image/png`, `image/webp`), max 2 MB pre-resize. Returns `{avatar_url, avatar_url_small}`. Audited as `user.avatar_uploaded`.
- `DELETE /api/users/me/avatar` — removes both files, nulls `avatar_url`, returns 204. Audited as `user.avatar_removed`.

### ⚠ Railway-ephemeral filesystem caveat

**Railway's container filesystem is ephemeral.** Uploaded avatars persist within a deploy but are **wiped on container restart** (which happens on every redeploy and occasionally for routine reasons). For the friend-pilot scale (5–15 users), this is acceptable — affected users re-upload via Settings, and the deterministic-color initials fallback remains in place for everyone who hasn't re-uploaded yet.

**Before scaling beyond friend-pilot,** migrate avatar storage to one of:
- **Railway Volume** (simplest — mount a persistent volume at `/app/backend/uploads/`)
- **S3 / R2 / DigitalOcean Spaces** (more durable, also enables CDN + backups; requires changing the upload code path to write to object storage and serving signed URLs)

The DB column already stores a path string, so the migration only needs to touch the upload/serve layer — not the schema.

### Verifying the mount in production

```bash
curl -I https://www.liquiddemocracy.us/uploads/avatars/{user_id}/128.jpg
# expect 200 + image/jpeg, OR 404 if no avatar uploaded for that user (correct — endpoint serves real files only)
```

If the URL returns the SPA index.html instead of the image, the nginx ordering is wrong (the `/uploads/` block must come before the static-asset cache rule). Check `frontend/nginx.conf`.

---

## Service worker and PWA (Phase 10)

Phase 10 added a service worker (Workbox via `vite-plugin-pwa`) for app-shell caching, home-screen install, and an offline fallback page.

### What gets shipped on every build

- `dist/manifest.webmanifest` — PWA manifest. Theme color `#1B3A5C` (brand navy), display `standalone`, three icons (192, 512, 512-maskable).
- `dist/sw.js` — generated service worker (Workbox runtime).
- `dist/workbox-*.js` — Workbox library file referenced by `sw.js`.
- `dist/registerSW.js` — small auto-injected registration shim (per `injectRegister: 'auto'`).
- `dist/icons/icon-{192,512,maskable-512}.png` — placeholder "LD" mark on brand color (no platform logo asset exists yet; see Phase 10 closeout note).
- `dist/offline.html` — minimal static fallback page served when navigation requests fail and nothing useful is cached.

### Cache rules

- API responses (`/api/*`) and uploads (`/uploads/*`) are NEVER cached by the SW — `navigateFallbackDenylist` excludes them, and there's no runtime caching rule for either path. Live data always goes to network.
- App shell (JS, CSS, HTML, PNG, SVG, ICO, WebP) is precached on SW install via Workbox's `globPatterns`. Clients pick up new builds automatically because `registerType: 'autoUpdate'` re-registers on each navigation.
- Navigation requests use `NetworkFirst` with a 5s timeout, falling back to the precached `/offline.html` when network and cache both fail.

### Cloudflare and Railway notes

Default Cloudflare handling of `service-worker.js`, `sw.js`, and `manifest.webmanifest` is correct in most cases — they're served as static assets via nginx with the right MIME types out of the box. If a future audit shows the SW being stale-cached at the edge for too long, set Cloudflare cache rules for `*.js` to "Bypass" or shorten the edge TTL specifically for `sw.js`. Vite's content-hashed bundle filenames already prevent stale-asset issues; only the SW file itself (with its fixed `sw.js` name) is at risk.

### Verifying the SW landed

```bash
curl -I https://www.liquiddemocracy.us/sw.js
# expect 200 + application/javascript

curl -I https://www.liquiddemocracy.us/manifest.webmanifest
# expect 200 + application/manifest+json (or application/json — both acceptable)

curl https://www.liquiddemocracy.us/offline.html | head
# expect HTML starting with <!DOCTYPE html> + "Liquid Democracy" + "You're offline."
```

### Updating the placeholder icons

The `frontend/scripts/generate_pwa_icons.py` Pillow script regenerates the three icons on demand. Run from repo root: `backend/.venv/Scripts/python frontend/scripts/generate_pwa_icons.py`. When a real platform brand mark exists, replace the PIL-generated PNGs in `frontend/public/icons/` and remove the script (or keep it for the maskable-padding math).

---

## Smoke checks (Phase 10.2)

The `tests/smoke/` directory at the repo root contains five lightweight HTTP checks that exercise infrastructure boundaries pytest cannot reach (nginx, the deployed service worker, the manifest MIME mapping). They were added in Phase 10.2 (W-FIX-C) after an audit found that every Phase 9.8 / 9.9 / 10 nginx-and-PWA regression had shipped because no automated test exercised the proxy layer.

The checks are intentionally minimal: one fixture (`target_url`), no shared setup, no mocking — each test is just `httpx.get(...)` / `httpx.post(...)` plus assertions. They use `httpx` (already in `backend/.venv`) so no new dependency is required.

### Running against prod

```bash
backend/.venv/Scripts/python -m pytest tests/smoke/ -v --target=https://www.liquiddemocracy.us
```

Expected: 4 passed, 1 failed. The failing one (`test_manifest_mime_type`) is documented below.

### Running against a local docker-compose stack

```bash
backend/.venv/Scripts/python -m pytest tests/smoke/ -v --target=http://localhost:8000
```

(Replace the URL with whatever port the local stack exposes — the default is whatever `--target` is set to without a trailing slash.)

### What each check covers

| Test | Boundary | Catches |
|---|---|---|
| `test_proxy.py::test_uploads_proxies_to_backend` | nginx `/uploads/` proxy | Phase 9.8 missing-`^~`-modifier regression. Asserts FastAPI JSON 404, not nginx HTML 404 or SPA HTML 200. |
| `test_proxy.py::test_body_size_limit_passes_through_to_backend` | nginx `client_max_body_size` | Phase 9.9 1-MB-default regression. POSTs 5 MB with no auth → must be FastAPI 401, not nginx 413. |
| `test_proxy.py::test_manifest_mime_type` | nginx MIME map for `.webmanifest` | Phase 10 closeout open issue. Asserts `Content-Type: application/manifest+json` (currently fails — see below). |
| `test_proxy.py::test_register_sw_js_served` | vite-plugin-pwa auto-injection | Codifies Phase 10 PWA install affordance: `/registerSW.js` must serve as JS. |
| `test_sw.py::test_navigate_fallback_denylist_includes_api_and_uploads` | Workbox `navigateFallbackDenylist` | A future live-data path being silently SW-cached because someone added it without updating the denylist in `frontend/vite.config.js`. String-search the deployed `sw.js` for `/^\/api/` and `/^\/uploads/`. |

### Known-failing check: `test_manifest_mime_type`

The Phase 10 closeout flagged that `manifest.webmanifest` is served with `Content-Type: application/octet-stream` instead of `application/manifest+json` because nginx has no MIME mapping for the `.webmanifest` extension. This degrades Lighthouse PWA scoring and triggers a Chrome DevTools warning on the install affordance.

The fix is one line in `frontend/nginx.conf`: add a `types { application/manifest+json webmanifest; }` block (or an entry in the existing `types` block). Once that ships, this smoke check should pass — and a future regression that loses the mapping would re-fail the check immediately.

Until the fix ships, the failing check is the desired-state codification — running the smoke suite is expected to produce 4 passed, 1 failed, and that one failure is the open issue, not a flake.

### Timing

Total wall-clock runtime against prod: ~1.8 seconds (5 HTTP round trips, no fixtures, no setup). Well under the ~10-second threshold spec'd for the W-FIX-D deploy-poll auto-wiring decision.

### Auto-runs on every deploy via `poll_deploy.py`

`backend/scripts/poll_deploy.py` (Phase 10.2 W-FIX-D) is the canonical post-push poll script. It waits for the bundle hash to flip + `/api/health` to return 200, then runs `pytest tests/smoke/ --target=<url>` automatically. Pass `--no-smoke` to skip the smoke step:

```bash
backend/.venv/Scripts/python backend/scripts/poll_deploy.py
backend/.venv/Scripts/python backend/scripts/poll_deploy.py --no-smoke
backend/.venv/Scripts/python backend/scripts/poll_deploy.py --start-bundle=index-foo.js  # pin pre-deploy hash
backend/.venv/Scripts/python backend/scripts/poll_deploy.py --target=http://localhost:8000  # local stack
```

A failing smoke check after a successful deploy returns the pytest exit code, so the script's overall exit status reflects whether the deploy is healthy AT THE BOUNDARY LAYER, not just whether the bundle flipped. The `test_manifest_mime_type` known-failing check above will count as a smoke failure — bundle the nginx fix or pass `--no-smoke` until it ships.

### Adding a new smoke check

Add a new test function to either `test_proxy.py` (nginx / proxy layer) or `test_sw.py` (service worker / PWA), or create a new `test_<boundary>.py` file. Each test takes the `target_url` fixture, hits the URL with `httpx`, and asserts on the response. Keep them independent — no shared state, no fixtures beyond `target_url`.

---

## Reading Railway logs during a 502 incident (Phase 13.1 W-RUNBOOK + Phase 13.2 W-RUNBOOK-ADDENDUM)

When a deploy lands but `/api/*` starts returning 502 "Application failed to respond" while static `/` still serves 200, the backend container failed to reach the listening state. Railway's load balancer keeps trying the failed container, which keeps restarting, which keeps failing — visible end-to-end as a sustained 502 wall.

The Phase 13 incident (2026-05-04) is the canonical example: backend went 502 immediately after a deploy and stayed down for ~35 minutes before the team reverted **without log access**. Phase 13.2 (2026-05-05) is the resolution case study: with log streaming in place, the team caught the exact failure (a Postgres `BOOLEAN DEFAULT 0` DatatypeMismatch in the migration), fixed it, and re-shipped within the same session.

### Where the logs are

Set the project token in your shell:

```bash
export RAILWAY_TOKEN=<token>      # bash
$env:RAILWAY_TOKEN = "<token>"    # PowerShell
```

The token lives in `.env` (gitignored). **Never commit, paste, or log the token.** If it leaks into tool output, redact it before sharing.

**Railway dashboard:** project → service (the backend service) → "Deployments" tab → click the failing deployment → "Logs" sub-tab.

**Railway CLI** (faster, scriptable):

```bash
railway logs                      # live tail of current deployment
railway logs --build              # build-step logs (Docker layers, image push)
railway logs --deployment         # runtime logs (start.sh + uvicorn)
railway logs --deployment -n 200  # last 200 lines, no streaming
railway logs --service backend    # explicit service (default is the linked service)
```

`railway logs` without flags streams the current deployment until that deployment ends. When a new deploy starts, the streaming command exits and you re-invoke it to follow the new deployment.

### What healthy startup looks like (baseline)

A healthy backend startup on Railway with `--workers 4` produces this log shape (captured from Phase 13.2 post-fix deploy, container started 2026-05-05T22:55:20Z):

```
Starting Container
Alembic-stamped DB detected — applying pending migrations…
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
[INFO  [alembic.runtime.migration] Running upgrade <prior> -> <new>, ...   ← only when there are pending migrations]
Public demo mode — ensuring demo seed data…
Starting sustained-majority worker…
Sustained-majority worker PID: <N>
Starting application…
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started parent process [1]
2026-05-05 22:55:20,770 INFO     [sustained_majority_worker] Worker starting; check_interval=300s, once=False
INFO:     Started server process [8]   ← one per worker (--workers 4 → 4 lines)
INFO:     Started server process [9]
INFO:     Started server process [10]
INFO:     Started server process [11]
[INFO] Creating database tables…       ← one per worker (4×)
[INFO] Rebuilding delegation graphs from DB…   ← one per worker
[INFO] Startup complete.                ← one per worker
INFO:     Application startup complete.   ← one per worker
[INFO] {"...request...","path": "/api/health","status_code": 200, ...}   ← Railway healthcheck
```

Critical observations:

- Each `--workers 4` worker independently runs the FastAPI startup hook. This means every startup-side-effect (`create_tables()`, `graph_store.rebuild_from_db()`, Phase 13's digest scheduler launch when shipped) executes **4 times** at boot. Memory footprint compounds; CPU spike on cold start is visible. This was unfamiliar variance during the Phase 13 diagnosis.
- The `INFO: Application startup complete.` line per worker is the load-bearing signal that uvicorn is serving. Absent for any worker = traffic distribution skews to whichever workers DID come up; sustained absence = 502.
- The first `/api/health 200` log line typically appears within ~30s of "Starting Container" on a warm Railway image cache; cold builds are slower because Docker pulls the base image first.

### What to look for during a 502 incident

Top-to-bottom on the failing container's logs:

1. **Did `start.sh` start at all?** Look for "Alembic-stamped DB detected…" or "Fresh database detected…". Absent → image build / Dockerfile issue.

2. **Did alembic upgrade succeed?** Look for `Running upgrade <a> -> <b>` followed by completion. A migration error here ends start.sh with non-zero exit due to `set -e`, container restarts in a loop. **Phase 13/13.1's failure mode lived here**: `psycopg2.errors.DatatypeMismatch: column "..." is of type boolean but default expression is of type integer` from a `BOOLEAN DEFAULT 0` ADD COLUMN. The transaction rolled back, alembic_version stayed at the prior revision, container looped. Fix: use `sa.false()` for boolean server_defaults, never `sa.text("0")`.

3. **Did the seed step run cleanly?** Only relevant if `IS_PUBLIC_DEMO=true`. Look for "Public demo mode — ensuring demo seed data…" + a clean exit.

4. **Did the worker side-process start?** Look for `Starting sustained-majority worker…` followed by `Sustained-majority worker PID: <N>`. The PID line prints even if the worker dies milliseconds later (because `&` backgrounds the process). Worker death does NOT take down uvicorn.

5. **Did uvicorn reach the listening state?** Look for `INFO: Started server process` (one per worker), then `INFO: Application startup complete.`, after the Railway-documented empty-host bind. Without those lines per worker, the app never bound to the dual-stack/private-network port.

6. **Are health checks reaching workers?** Look for repeated `GET /api/health HTTP/1.1 200 OK`. Distributed across `100.64.0.X` source IPs (Railway's internal probe addresses).

### Failure-mode → diagnosis cheatsheet

| Symptom in logs | Likely cause | Fix |
|---|---|---|
| `psycopg2.errors.DatatypeMismatch: column "..." is of type boolean but default expression is of type integer` | Migration `ADD COLUMN ... BOOLEAN DEFAULT 0`. PG rejects integer for boolean. | Use `sa.false()` (or dialect-aware) for boolean server_defaults; never `sa.text("0")`. |
| `relation "<table>" already exists` mid-migration | Migration not idempotent against post-revert state. | Add `if "<table>" not in existing_tables` guards. |
| `ImportError` or stack trace before any `Started server process` line | Module-level code raises at import. | Find the module, lazy-import the failing import. |
| `Killed` / no exit log + container restart loop | OOM. With `--workers 4` startup compounds memory. | Reduce workers, lazy-import heavy modules, or upgrade tier. |
| `Application startup complete.` but `502` from healthchecks | Railway probe hitting wrong port or container shutdown signal handling. | Check `--port` in start.sh, check WORKERS env var. |
| `alembic upgrade head` no-op when migration file is in the codebase | alembic_version already at head (prior deploy advanced it). | Confirm via direct DB query; usually fine (idempotent path). |

### The start.sh ordering invariant

The container's bring-up sequence is fixed:

```
alembic upgrade (or create_all + stamp head if fresh DB)
  → optional seed_if_empty.py
    → python -m sustained_majority_worker &  (background, fire-and-forget per `&`)
      → exec uvicorn main:app --workers ${WORKERS:-4}
```

A 502 with no `/api/health` response means the container did not reach the `exec uvicorn` line, OR uvicorn started but never reached `Application startup complete.`. The first three steps run in foreground with `set -e`; any failure exits the script and Railway loops the container. The `&` on the worker line decouples its lifecycle from start.sh.

### When to revert vs. hot-fix-forward

If the cause is obvious from the logs and the fix is one or two lines, hot-fix-forward (push, redeploy, observe). Phase 13.2's experience: revert immediately to restore service (~2 minutes), apply the small fix on the deploy branch, push the corrected merge. Total cycle: ~15 minutes from the failing deploy to the recovered + fixed redeploy.

If the cause requires more than ~10 minutes of investigation OR if the diagnosis isn't certain, **revert immediately** with `git revert -m 1 <merge-sha>` and push, then diagnose offline.

---

## Phase 97 production monitoring runbook

The low-cost monitoring layer has two independent paths:

1. `GET /api/health/monitor` aggregates database connectivity/capacity,
   digest and decision-worker heartbeats, repeated non-health 5xx responses,
   repeated email transport failures, upload-volume capacity, and availability
   of a verified platform-admin alert recipient. It returns HTTP 503 only for
   actionable errors; capacity warnings remain HTTP 200.
2. `.github/workflows/production-monitor.yml` checks the homepage and combined
   monitor at minutes 7 and 37 of every hour. Three bounded attempts avoid
   opening an incident for a brief edge-network hiccup. A sustained failure
   opens one `production-monitor` GitHub issue and fails the workflow; recovery
   comments on and closes the issue.

Railway's service healthcheck is still useful during deployment, but Railway
documents that it stops continuously polling after a deployment becomes live.
The GitHub probe is the whole-service/down-database backstop.

### Thresholds and first response

| Component | Alert threshold | First response |
|---|---|---|
| Database | `SELECT 1` fails | Check Railway Postgres and backend deployment/logs. Do not run destructive SQL. |
| Database capacity | warning at 80% of configured 5 GB; error at 90% | Confirm `pg_database_size`, growth source, and resize before the error boundary. |
| HTTP 5xx | 3 non-health 5xx responses in 15 minutes | Search backend logs using the sanitized request IDs in the alert. |
| Email delivery | 3 consecutive common-transport failures | Check Resend logs, quota, domain health, and Railway email variables. GitHub remains the independent alert path. |
| Digest scheduler | 2 failed ticks or no success for 2.5 hours | Inspect `digest_loop` logs and `/api/health/scheduler`; confirm the scheduler is not intentionally disabled. |
| Decision worker | 3 failed ticks or heartbeat older than max(20 min, 3 intervals) | Inspect the sustained-majority/decision-worker process and heartbeat row. |
| Upload volume | warning at 85%, error at 95%, or `/data/uploads` unavailable | Confirm Railway volume mount and usage; resize/archive before writes fail. |
| Alert recipients | zero active, verified, non-placeholder platform-admin emails | Restore at least one real platform-admin email or set `OPS_ALERT_EMAIL` explicitly. |

### Deduplication and recovery

- The internal monitor checks every five minutes, sends once when the incident
  component fingerprint opens/changes, retries failed delivery after one hour,
  and sends at most one unchanged reminder every 12 hours.
- Incident delivery state is stored in the existing
  `platform_settings.ops_monitor_alert_state` JSON row, so normal deploys do not
  reset deduplication.
- Recovery sends one platform-admin email and clears the active fingerprint.
- Known demo/test placeholder domains (including `@demo.example`) are excluded;
  `OPS_ALERT_EMAIL` can explicitly select one operational destination later.
- The GitHub workflow never opens a second issue while a labeled incident is
  already open.

### Safe verification

```bash
curl -i https://www.liquiddemocracy.us/api/health/monitor
```

Expected healthy response: HTTP 200 and top-level `"status":"ok"` (or
`"warning"` for non-critical capacity pressure). Do not generate fake 500s in
production. A platform admin can safely prove operational email delivery with
`POST /api/admin/monitoring/test-alert`; it sends a clearly labeled test and
does not open incident state. The GitHub workflow also supports manual
`workflow_dispatch` for a safe external-path proof.

### Limitations

- GitHub scheduled runs can be delayed during load; this is twice-hourly
  monitoring, not a contractual uptime SLA.
- GitHub workflow email depends on the repository owner's Actions notification
  preferences. The durable Actions failure and incident issue still exist.
- Runtime 5xx/email counters are process-local, appropriate for today's
  one-worker deployment. Revisit aggregation before increasing `WORKERS` or
  adding replicas.
- Internal email cannot deliver during a provider outage; the external GitHub
  incident is the intended independent route.

### pg_smoke gap revealed by Phase 13.2

Phase 13.1 and Phase 13.2's first attempt both passed `pg_smoke --mode both` against the migration that was about to fail in production. Why pg_smoke missed it:

- The smoke's "upgrade-from-prior" mode runs `create_all` first (using model definitions) BEFORE running `alembic upgrade head`. The model definitions contain `server_default="0"` (a string literal, which SQLAlchemy somehow accepts on PG when emitted via metadata). By the time alembic upgrade runs, the columns already exist, and the migration's idempotent skip-path is hit — the failing `add_column(..., server_default=sa.text("0"))` is never exercised against a fresh PG.
- The smoke's "fresh-DB" mode also uses `create_all + stamp head`; the migration body is never run.

A better pg_smoke pattern (logged as tech debt) would: stamp at the prior revision with the prior schema (no Phase-13 columns), then run `alembic upgrade head`. That would actually exercise the add_column path. Until that lands, **add a manual smoke step** for any pass that adds boolean columns to existing tables: spin a fresh PG, apply the prior migration head, then run the new migration directly via `alembic upgrade head`.

### Token rotation

The Railway project token has a 60-day lifetime. Rotation procedure:

1. Railway dashboard → Project Settings → Tokens → Create new token (scope: project).
2. Update `.env` locally with the new token.
3. Verify with `railway logs -n 5` (should print 5 recent lines).
4. Revoke the old token in the dashboard.
5. **Don't** commit the new token. Don't paste it into spec files, closeouts, or commit messages.

Set a reminder ~50 days out to rotate proactively rather than waiting for the token to expire mid-incident.

---

## Phase 13 — Notification digest scheduler

**Implementation choice: in-process asyncio loop.**

Phase 13 ships a notification digest system (daily/weekly digests + quiet-hours queue flush + 90-day cleanup). The scheduler is a single `asyncio.create_task(digest_loop())` started in `backend/main.py`'s startup hook. The loop sleeps `digest_scheduler.TICK_SECONDS` (3600s = 1 hour) between ticks; each tick scans all users, evaluates their local time against 9am-local boundaries, and dispatches digests / flushes quiet-hours queues / runs the 90-day cleanup.

**Why asyncio in-process over Railway cron:**
- Zero infrastructure config — no separate Railway service, no cron config, no shared-secret webhook auth.
- Survives restarts cleanly: on a Railway redeploy the loop simply restarts and resumes scanning at the next tick boundary.
- The scheduler logic is pure DB reads + email sends; no per-tick state needs to persist outside the DB rows themselves (delivered tracking lives in `Notification.payload["delivered_in_digest"]`).
- Tradeoff: dies if the FastAPI worker dies. Acceptable at v1 — Railway restarts the process automatically; the only effect is that a digest scheduled for the missed tick window may be delivered at the next available 9am local boundary instead.

**Multi-worker behavior (Phase 13.2 W-DEPLOY-3 design decision — Option C):**
With `--workers 4`, every worker independently runs the FastAPI startup hook → 4 `digest_loop` tasks running simultaneously. We **accept the N-worker launch** and rely on row-level idempotency (atomic UPDATE-with-WHERE-clause-on-not-yet-delivered + rowcount check) to prevent duplicate digest sends. Other workers see zero rows to process and their tick is a fast no-op. This is more robust than lock-based first-worker-only coordination — any single worker's death doesn't stall the scheduler, and the per-tick query cost is small at friend-pilot scale.

**How to disable:**
Set `DISABLE_DIGEST_SCHEDULER=1` in Railway env vars and redeploy. The startup hook reads the env var and skips the `asyncio.create_task(...)` call entirely (the FastAPI process stays up; only the scheduler is suppressed). The full backend test suite also sets this env var via `tests/conftest.py` so test runs never accidentally launch the loop.

**How to verify in prod:**
Log line `digest_loop: tick complete {daily: N, weekly: N, quiet: N, cleaned: N}` appears every hour in Railway logs. After a known opt-in user has fresh notifications and the local 9am tick fires, expect `daily >= 1`. The 90-day cleanup count surfaces every tick; that line is the heartbeat. With 4 workers, expect 4× `tick complete` lines per hour (one per worker); only one will show non-zero `daily`/`weekly` counts (the worker whose UPDATE landed first); the other three log all-zeros.


## Phase 40 — Worker signal handling on Railway redeploy (B6.4, RESOLVED Phase 40a)

**Original finding (Phase 40, 2026-05-27):** Railway sends SIGTERM to PID 1 only, not to the container cgroup. Pre-Phase-40a: `start.sh` ran `exec uvicorn ...` which made uvicorn PID 1 and the sustained_majority_worker (launched as a background subprocess earlier in `start.sh`) a non-PID-1 child. On redeploy, uvicorn received SIGTERM and shut down gracefully — the digest_scheduler `asyncio.create_task` running inside uvicorn got the asyncio cancel and exited cleanly — but the SM worker subprocess received NO signal. Its `_install_signal_handlers` "Received signal {signum}; finishing tick and exiting." log line was absent from every observed redeploy trace, conclusively confirming the worker was being SIGKILLed by Railway's force-stop after the SIGTERM grace window expired.

**Evidence captured during Phase 40 closeout:** QA pass inspected REMOVED deployment `95465dda` (immediately preceding Phase 40 hotfix #1 at 2026-05-27 15:25:10 EDT). The uvicorn shutdown trace was intact (`Stopping Container` → `INFO: Shutting down` → `Waiting for application shutdown` → `Application shutdown complete` → `Finished server process [1]` → `digest_loop: cancelled; exiting` → final `Stopping Container`). The same deploy's `sustained_majority` filter showed only 3 records (startup + 2 ticks) — zero shutdown-handler messages. Searching the entire deploy log for the literal token `Received` returned "No logs found."

**Risk (pre-fix):** the SM worker could be killed mid-tick on every redeploy. At friend-pilot scale this was rare and recoverable (the next worker startup picks up where it left off — the tick is idempotent at the snapshot level). For higher-stakes pilot orgs with active voting at deploy time, this could mean a partially-written audit log line or an in-flight Stable Result Required evaluation that doesn't complete. Not a security risk; correctness/observability risk only.

**Resolution (Phase 40a, 2026-05-28):** `backend/start.sh` no longer uses `exec uvicorn ...`. Instead the shell stays as PID 1, launches both the SM worker AND uvicorn as background children, and installs a `trap _cleanup SIGTERM SIGINT` that forwards SIGTERM to the worker first (brief sleep for the worker's signal handler to run + finish current tick), then to uvicorn, then waits for both to exit cleanly. The `wait -n` (bash 4.3+) blocks until any child exits — if one crashes for unrelated reasons (OOM, panic), the cleanup path also brings the other down so no orphans linger.

```bash
uvicorn main:app --host "" --port 8000 --workers ${WORKERS:-1} \
    --proxy-headers --forwarded-allow-ips '*' &
UVICORN_PID=$!

_cleanup() {
    echo "[start.sh] Received shutdown signal; forwarding to children…"
    if [ -n "${SM_WORKER_PID:-}" ]; then
        kill -TERM "${SM_WORKER_PID}" 2>/dev/null || true
    fi
    sleep 1
    kill -TERM "${UVICORN_PID}" 2>/dev/null || true
    if [ -n "${SM_WORKER_PID:-}" ]; then
        wait "${SM_WORKER_PID}" 2>/dev/null || true
    fi
    wait "${UVICORN_PID}" 2>/dev/null || true
    exit 0
}
trap _cleanup SIGTERM SIGINT
wait -n
_cleanup
```

Cost: bash script is PID 1 instead of uvicorn — Railway tolerates shell-script entrypoints for this. Benefit: SIGTERM propagates to both subprocesses; the SM worker's `_Stop.flag=True` → finishes current tick → exits cleanly path actually runs on redeploy.

**Verifying the fix is working post-deploy:** after any backend redeploy, search the REMOVED deployment's logs (i.e., the deployment that just got replaced) for the SM worker's shutdown line. The worker's `_install_signal_handlers` logs `Received signal {signum}; finishing tick and exiting.` when the trap forwards SIGTERM. If absent, the trap isn't delivering — investigate. If present, the fix is working as designed.
## Layered backup and recovery (Phase 98)

Liquid Democracy has two independent recovery layers:

1. Railway-native volume backups cover fast, same-project recovery of the
   Postgres and `/data/uploads` volumes while the workspace has the required
   Railway entitlement.
2. A dedicated backend child process creates a PostgreSQL custom-format dump
   plus an uploads archive, embeds both and a versioned manifest in one tar
   bundle, encrypts that bundle with `age`, and uploads only ciphertext to a
   private Cloudflare R2 bucket. This application layer continues to work on
   Hobby and is configuration-disabled by default.

The offsite worker is not part of Uvicorn or the digest scheduler. `start.sh`
launches it only when `OFFSITE_BACKUP_ENABLED=true`, forwards shutdown signals,
and deliberately keeps Uvicorn running if the backup worker exits. A stable
PostgreSQL advisory lock prevents deploy overlap or two selected replicas from
backing up concurrently. Lifecycle expiration is an R2 policy; the worker has
no pruning path and never exercises delete permission.

### Offsite configuration

| Variable | Default | Purpose |
|---|---:|---|
| `OFFSITE_BACKUP_ENABLED` | `false` | Starts the scheduler only when explicitly enabled |
| `OFFSITE_BACKUP_TIME_UTC` | `11:00` | Daily `HH:MM` UTC schedule |
| `OFFSITE_BACKUP_S3_ENDPOINT` | empty | HTTPS R2 S3 endpoint |
| `OFFSITE_BACKUP_S3_REGION` | `auto` | R2 region value |
| `OFFSITE_BACKUP_BUCKET` | empty | Dedicated private bucket name |
| `OFFSITE_BACKUP_PREFIX` | `production` | Root object prefix |
| `OFFSITE_BACKUP_ACCESS_KEY_ID` | empty | Bucket-scoped write credential |
| `OFFSITE_BACKUP_SECRET_ACCESS_KEY` | empty | Bucket-scoped write secret |
| `OFFSITE_BACKUP_AGE_RECIPIENT` | empty | Dedicated public `age1...` recipient only |
| `OFFSITE_BACKUP_STALE_AFTER_SECONDS` | `129600` | Monitor error threshold (36 hours) |
| `OFFSITE_BACKUP_WORKER_INSTANCE_ID` | empty | Optional match for `INSTANCE_ID` or `RAILWAY_REPLICA_ID` |

Missing credentials are valid while disabled. If enabled configuration is
missing, placeholder, non-HTTPS, or malformed, only the backup process exits;
the site remains available and monitoring records a sanitized category. Never
put the private `AGE-SECRET-KEY-...` identity in Railway, R2, repository files,
logs, Google Drive, email, or application environment variables.

The container installs PostgreSQL 18 `pg_dump`/`pg_restore` and checksum-pins
official `age` v1.3.1. Both the image build and runtime preflight enforce the
versions; runtime also refuses a PostgreSQL client older than the live server.
Safe non-secret version checks are:

```bash
pg_dump --version
pg_restore --version
age --version
```

### R2 policy before first production object

Create a private Standard-storage bucket without a public development URL,
custom domain, public listing, or browser CORS exposure. Use credentials scoped
to that one bucket. Configure locks and lifecycle rules over the exact worker
prefixes before enabling:

| Prefix | Minimum lock | Lifecycle expiration |
|---|---:|---:|
| `production/daily/` | 7 days | 8 days |
| `production/weekly/` | 35 days | 36 days |
| `production/monthly/` | 100 days | 101 days |

Every run writes `daily/`; Sunday UTC also writes `weekly/`, and the first day
of the UTC month also writes `monthly/`. These keys reference the same local
ciphertext and are unique/non-overwriting. Do not enable production offsite
backup until Railway-native coverage is visible, per the Phase 98 gate order.

### Preflight, manual run, and monitoring

The preflight reads database/tool/version/upload/space/advisory-lock state,
validates the public recipient by encrypting an empty ephemeral file, and calls
R2 `HEAD Bucket`. It does not invoke `pg_dump` or upload an object, and it can be
run while the enable flag is still false:

```bash
python -m offsite_backup_worker --preflight
```

After native coverage and provider policies are independently verified, enable
and deploy, then use the scheduler's exact core path for the initial manual run:

```bash
python -m offsite_backup_worker --once
```

`GET /api/health/monitor` exposes only coarse `offsite_backup` state:
`disabled`, first-run `warning`, recent verified `ok`, or `error` after a failed
run or 36-hour staleness. It never exposes endpoints, bucket names, object keys,
credentials, database URLs, upload filenames, row contents, or raw command
output. Phase 97 incident/recovery email and the external GitHub monitor consume
this component through the existing deduplicated behavior.

Useful incident order is: confirm the site is healthy; read the public monitor;
run preflight; inspect the backup worker's sanitized category; confirm the R2
bucket/policy/credential and Railway database/uploads services; then manually
run once only after fixing the cause. Do not disable locks, make the bucket
public, log credentials, or restore production as a troubleshooting shortcut.

### Isolated verify and restore rehearsal

The restore CLI is never imported by application startup or exposed through an
HTTP route. Run it only on an isolated operator machine with the offline private
identity, a separate read-only R2 credential, a fresh PostgreSQL 18 database on
a host other than production, and an already-created empty uploads directory.
Set restore secrets in the local process environment rather than command-line
arguments:

```bash
export OFFSITE_RESTORE_S3_ENDPOINT="https://<account>.r2.cloudflarestorage.com"
export OFFSITE_RESTORE_S3_REGION="auto"
export OFFSITE_RESTORE_BUCKET="<private-bucket>"
export OFFSITE_RESTORE_ACCESS_KEY_ID="<read-only-key>"
export OFFSITE_RESTORE_SECRET_ACCESS_KEY="<read-only-secret>"
export OFFSITE_RESTORE_TARGET_DATABASE_URL="postgresql://<user>:<password>@<isolated-host>/phase98_restore_test"
export OFFSITE_PRODUCTION_DATABASE_HOST="<exact-production-host>"
export OFFSITE_PRODUCTION_DATABASE_NAME="<exact-production-database-name>"
python backend/scripts/restore_offsite_backup.py \
  --object-key "production/daily/YYYY/MM/<ciphertext>.tar.age" \
  --identity "/offline/path/phase98-age-identity.txt" \
  --confirm "RESTORE DISPOSABLE DATABASE phase98_restore_test ON <isolated-host>" \
  --uploads-destination "/isolated/empty/uploads" \
  --verify-only
```

Remove `--verify-only` for the approved rehearsal. The tool rejects missing or
ambiguous targets, the current database URL, either configured production host
or database name (case-insensitive), libpq query-string routing overrides,
non-empty databases across all non-system schemas, non-empty upload targets,
and targets whose database name does not clearly contain `restore`, `test`,
`rehearsal`, `disposable`, `scratch`, or `temp`. It verifies ciphertext metadata
and checksum, decrypts, verifies the manifest/member checksums, requires the
backup's Alembic current revision to equal its recorded head, restores with
PostgreSQL 18 `pg_restore`, rechecks revisions and representative counts, then
extracts uploads with traversal/link/special-file rejection and count/byte
verification.

Temporary plaintext is removed on normal completion and failures. The command
fails loudly if cleanup cannot be completed. `--keep-temporary` is an explicit
diagnostic override and must never be used casually with production data.
Filesystem deletion is not guaranteed forensic erasure on SSDs; use an
encrypted operator disk, destroy the disposable database/uploads promptly, and
do not inspect or print private row/file contents.

### Key loss, credential rotation, downgrade, and real incidents

- Losing the private age identity makes existing objects unrecoverable. Keep it
  in a password-manager secure note and a second offline recovery location;
  read both back before the first live run. If the identity may be compromised,
  generate a new dedicated pair, preserve the old identity offline until its
  objects expire, update only the public recipient in Railway, and prove a new
  backup/restore.
- Rotate R2 credentials by creating a new bucket-scoped credential, updating
  Railway, running preflight plus one verified backup, then revoking the old
  credential. Restore rehearsals should use a separate read-only credential.
- Railway native restore stages a replacement volume in the same project and
  environment. Prove mechanics only with a disposable test service/volume.
  Never click through a production-volume restore for testing, and never detach,
  resize, replace, wipe, or overwrite a production volume during rehearsal.
- Before a Pro-to-Hobby downgrade, record schedules, retained native backup
  identifiers, renewal timing, and what Railway's authenticated UI says. Do not
  promise that native schedules or retained-backup access survive. After Hobby
  becomes effective, prove another offsite success and monitor/object state.
- A real production restore is outside Phase 98. Freeze writes and preserve
  evidence, identify the incident window and best verified artifact, obtain a
  separate incident decision, rehearse against disposable resources, and only
  then author a production-specific recovery plan. Never improvise an automated
  destructive restore.
