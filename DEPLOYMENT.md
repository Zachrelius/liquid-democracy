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
5. Once deployed, open the service → **Settings** → **Networking** → **Generate Domain** so Railway assigns a public `*.up.railway.app` URL. This is your temporary backend URL for testing before DNS is live. Note it down.
6. Check **Logs** for a successful startup: you should see `Ensuring base schema exists…`, `Fresh database detected — stamping alembic head.`, and `Starting application…`. If you see a traceback, paste it into `docker compose logs backend` locally to compare — most startup errors are env-var-related.

#### Step 4 — Deploy the frontend

1. In the same project, click **New** → **GitHub Repo** and pick the same `liquid-democracy` repo. This is a second service pointing at the same repo.
2. Configure as the **frontend**:
   - **Root directory:** `frontend`
   - **Watch paths:** `frontend/**`
3. Under **Variables**, set `BACKEND_URL` to the backend's internal Railway URL from Step 3. nginx's template mechanism substitutes this at container start into the `/api/` and `/ws/` proxy directives. Two valid forms:
   - **Preferred (private networking):** `BACKEND_URL=http://backend.railway.internal:8000` — replace `backend` with the actual service name Railway assigned (shown in the Settings page). Private networking means free internal bandwidth and no public hop.
   - **Fallback (public URL):** `BACKEND_URL=https://<backend-service>.up.railway.app` — works if private networking isn't configured. Slightly slower, traffic goes through Railway's edge.
4. Click **Deploy**. Railway builds the frontend (nginx serves `/app/dist`).
5. **Settings** → **Networking** → **Generate Domain** to get a `*.up.railway.app` URL for the frontend. Visit it — you should see the landing page. The `/api/*` calls should return real data (try visiting `<your-frontend-url>/api/health` — it should return JSON from the backend).

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
3. Click "Sign in as alice" → lands on `/proposals` with seeded content visible.
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

## Setting Up SMTP (Gmail App Password)

For the demo, verification and password-reset emails are sent through a Gmail account using an App Password. This is credible for low-volume demo traffic, no dedicated mail service required.

**Z performs these steps personally** — they require access to the Google account whose address will appear in the `From:` header.

1. **Turn on 2-Step Verification.** In Google Account → Security. App Passwords aren't available until 2SV is on. Use any second-factor method you like (authenticator app is recommended).
2. **Generate an App Password.** Google Account → Security → 2-Step Verification → App passwords (may be linked as "App passwords" in the search bar if hidden). Create a new password, label it "Liquid Democracy Demo." Google displays a 16-character password with spaces — copy it verbatim, spaces and all. Google will not show it again. Paste it into a temporary note for the next step.
3. **Add to Railway backend service variables:**
   - `SMTP_HOST=smtp.gmail.com`
   - `SMTP_PORT=587`
   - `SMTP_USER=<your-gmail-address>` (e.g., `liquiddemocracy.qa@gmail.com`)
   - `SMTP_PASSWORD=<16-char App Password>` (Railway will preserve the spaces; Gmail accepts with or without)
   - `FROM_EMAIL=Liquid Democracy <your-gmail-address>` (the display-name prefix is what recipients see in their inbox)
4. **Redeploy the backend service** so it picks up the new env vars.
5. **Test delivery:** register a fresh account on the deployed site, confirm the verification email arrives in the real inbox within ~30 seconds. If it doesn't, check the **Troubleshooting** section below for SMTP-specific guidance.

**Gmail limits.** Free Gmail sends up to ~500 emails per day. For the EA demo timeframe that's orders of magnitude more headroom than needed. If you need more, upgrade to Google Workspace or migrate to a transactional email provider (SendGrid, Postmark, SES) later.

**Security.** The App Password is a bearer credential for your Gmail account. Treat it like a production secret — only store in Railway's variable store (encrypted at rest), never commit to the repo.

## Demo Data Management

The demo org (`slug=demo`) is seeded once after the first deploy. Visitor-created content persists across sessions — this is intentional for the EA-demo stage, so visitors can see each others' proposals and delegations accumulate. Auto-reset is deferred to a later phase.

### Initial seed (one-time, after first deploy)

From your machine, against the live Railway deploy:

```bash
# Option A — Railway CLI (preferred)
railway login
railway link                # pick the project
railway run --service backend python -c "from database import SessionLocal; from seed_data import run_seed; db = SessionLocal(); run_seed(db); db.close()"

# Option B — Railway web console
# Go to the backend service → Deployments → open a shell → run:
python -c "from database import SessionLocal; from seed_data import run_seed; db = SessionLocal(); run_seed(db); db.close()"
```

Verify: `https://liquiddemocracy.us/demo` renders with 6 personas, and clicking "Sign in as alice" lands on `/proposals` with seeded proposals visible.

### Manual reset (when you want a clean demo)

Wipes all data and re-seeds. Expect ~30 seconds of downtime.

```bash
railway run --service backend python -c "from database import engine, Base; Base.metadata.drop_all(engine); Base.metadata.create_all(engine)"
railway run --service backend python -c "from database import SessionLocal; from seed_data import run_seed; db = SessionLocal(); run_seed(db); db.close()"
```

Do this before EA events if visitor content from previous demos has accumulated beyond what you want to show.

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
| `SMTP_HOST` | No | — | SMTP server hostname (leave empty to log emails to console) |
| `SMTP_PORT` | No | `587` | SMTP server port |
| `SMTP_USER` | No | — | SMTP authentication username |
| `SMTP_PASSWORD` | No | — | SMTP authentication password |
| `FROM_EMAIL` | No | — | Sender email address for notifications |
| `DATABASE_URL` | Auto | — | Set automatically by docker-compose or Railway; override for external DB |
| `WORKERS` | No | `4` | Number of uvicorn worker processes |
| `DEBUG` | No | `false` | Enable debug mode (never use in production) |
| `LOG_LEVEL` | No | `INFO` | Logging level: DEBUG, INFO, WARNING, ERROR |

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

### Verification emails not arriving (Gmail SMTP)

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
