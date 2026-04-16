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

### Railway

1. Fork/push the repository to GitHub.
2. Create a new project on [Railway](https://railway.app).
3. Add a **PostgreSQL** service from the Railway dashboard.
4. Add a **Backend** service:
   - Set the root directory to `backend/`
   - Railway auto-detects the Dockerfile
   - Add environment variables: `DATABASE_URL` (from the PostgreSQL service), `SECRET_KEY`, `CORS_ORIGINS`, `BASE_URL`
5. Add a **Frontend** service:
   - Set the root directory to `frontend/`
   - Railway auto-detects the Dockerfile
   - Update `nginx.conf` to point the API proxy to the backend service's internal URL
6. Set up a custom domain in Railway settings.

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

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DB_USER` | Yes | — | PostgreSQL username |
| `DB_PASSWORD` | Yes | — | PostgreSQL password |
| `SECRET_KEY` | Yes | — | JWT signing secret (min 32 characters recommended) |
| `CORS_ORIGINS` | No | `["http://localhost:5173"]` | JSON array of allowed CORS origins |
| `BASE_URL` | No | `http://localhost:5173` | Public URL for email links |
| `SMTP_HOST` | No | — | SMTP server hostname (leave empty to log emails to console) |
| `SMTP_PORT` | No | `587` | SMTP server port |
| `SMTP_USER` | No | — | SMTP authentication username |
| `SMTP_PASSWORD` | No | — | SMTP authentication password |
| `FROM_EMAIL` | No | — | Sender email address for notifications |
| `DATABASE_URL` | Auto | — | Set automatically by docker-compose; override for external DB |
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
