# Akleao Research - Deployment Guide

This document covers the production deployment architecture and operations for Akleao Research.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         VERCEL                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │              Next.js Frontend                            │    │
│  │              https://akleao.com                          │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────┬───────────────────────────────────────┘
                          │ HTTPS API calls + WebSocket
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                 GCP COMPUTE ENGINE (e2-small)                    │
│                 IP: 34.57.242.122                                │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │              Docker Compose                              │    │
│  │  ┌─────────┐  ┌─────────────────┐  ┌─────────────────┐  │    │
│  │  │  Nginx  │──│      API        │  │  Celery Worker  │  │    │
│  │  │ :80/443 │  │     :8000       │  │  (background)   │  │    │
│  │  └─────────┘  └────────┬────────┘  └────────┬────────┘  │    │
│  │                        │                     │           │    │
│  │  ┌─────────────────────┴─────────────────────┘           │    │
│  │  │              Redis :6379                              │    │
│  │  └───────────────────────────────────────────────────────│    │
│  │                                                          │    │
│  │  Cloud SQL Proxy (:5432) ──► Cloud SQL PostgreSQL        │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
┌───────▼───────┐ ┌───────▼───────┐ ┌───────▼───────┐
│  Cloud SQL    │ │    GCS        │ │   External    │
│  PostgreSQL   │ │   Bucket      │ │   APIs        │
│ (db-f1-micro) │ │  (uploads)    │ │ Pinecone,etc  │
└───────────────┘ └───────────────┘ └───────────────┘
```

## Infrastructure Components

| Component | Service | Details |
|-----------|---------|---------|
| **Frontend** | Vercel | Auto-deploys from `main` branch, `frontend/` directory |
| **Backend VM** | GCP Compute Engine | `akleao-vm`, e2-small, us-central1-a |
| **Database** | Cloud SQL PostgreSQL | `akleao-db`, db-f1-micro |
| **File Storage** | Cloud Storage | `akleao-research-uploads` bucket |
| **Static IP** | GCP | 34.57.242.122 |

## DNS Configuration

| Domain | Type | Target |
|--------|------|--------|
| `akleao.com` | A | 76.76.21.21 (Vercel) |
| `www.akleao.com` | CNAME | cname.vercel-dns.com |
| `api.akleao.com` | A | 34.57.242.122 (GCP VM) |

## Environment Variables

### Backend (.env on VM at `/opt/akleao/.env`)

```bash
# Database (Cloud SQL via proxy)
DB_HOST=host.docker.internal
DB_PORT=5432
DB_NAME=akleao
DB_USER=akleao_user
DB_PASSWORD=<secret>

# Storage
GCS_BUCKET=akleao-research-uploads

# Frontend URLs (for CORS)
FRONTEND_URL=https://akleao.com
CORS_ORIGINS=https://akleao.com,https://www.akleao.com

# Authentication
JWT_SECRET=<secret>

# API Keys
OPENAI_API_KEY=sk-proj-...
ANTHROPIC_API_KEY=sk-ant-api03-...
PINECONE_API_KEY=pcsk_...
PINECONE_INDEX_NAME=akleao-research
TAVILY_API_KEY=tvly-...

# Email (optional)
MAILGUN_API_KEY=...
MAILGUN_DOMAIN=...
MAILGUN_FROM_EMAIL=...
```

### Frontend (Vercel Environment Variables)

```bash
NEXT_PUBLIC_API_URL=https://api.akleao.com
```

## Docker Services

The backend runs 4 Docker containers via `docker-compose.prod.yml`:

| Service | Image | Purpose |
|---------|-------|---------|
| `nginx` | nginx:alpine | SSL termination, reverse proxy |
| `api` | akleao-api | FastAPI backend (Gunicorn + Uvicorn) |
| `celery` | akleao-celery | Background job processing |
| `redis` | redis:7-alpine | Message broker for Celery |

## Common Operations

### SSH to VM

```bash
gcloud compute ssh akleao-vm --zone=us-central1-a
```

### View Logs

```bash
# All services
gcloud compute ssh akleao-vm --zone=us-central1-a --command="sudo docker compose -f /opt/akleao/docker-compose.prod.yml logs -f"

# Specific service
gcloud compute ssh akleao-vm --zone=us-central1-a --command="sudo docker compose -f /opt/akleao/docker-compose.prod.yml logs -f api"
```

### Restart Services

```bash
# Restart all
gcloud compute ssh akleao-vm --zone=us-central1-a --command="cd /opt/akleao && sudo docker compose -f docker-compose.prod.yml restart"

# Restart specific service
gcloud compute ssh akleao-vm --zone=us-central1-a --command="cd /opt/akleao && sudo docker compose -f docker-compose.prod.yml restart api"
```

### Deploy New Code

```bash
# Option 1: Use deploy script
./scripts/deploy.sh

# Option 2: Manual deployment
gcloud compute ssh akleao-vm --zone=us-central1-a --command="
  cd /opt/akleao && \
  sudo git pull origin main && \
  sudo docker compose -f docker-compose.prod.yml build api && \
  sudo docker compose -f docker-compose.prod.yml up -d --force-recreate api celery
"
```

### Update Environment Variables

```bash
# SSH and edit
gcloud compute ssh akleao-vm --zone=us-central1-a
sudo nano /opt/akleao/.env

# Then recreate containers (restart won't pick up new env vars!)
cd /opt/akleao && sudo docker compose -f docker-compose.prod.yml up -d --force-recreate api celery
```

### Check Service Status

```bash
gcloud compute ssh akleao-vm --zone=us-central1-a --command="sudo docker compose -f /opt/akleao/docker-compose.prod.yml ps"
```

### Test Health Endpoint

```bash
curl https://api.akleao.com/health
```

## SSL Certificate

SSL is managed via Let's Encrypt with certbot. The certificate is stored at:
- `/etc/letsencrypt/live/api.akleao.com/fullchain.pem`
- `/etc/letsencrypt/live/api.akleao.com/privkey.pem`

### Renew Certificate

```bash
gcloud compute ssh akleao-vm --zone=us-central1-a --command="sudo certbot renew"
```

Consider setting up auto-renewal via cron:
```bash
0 0 1 * * certbot renew --quiet && docker compose -f /opt/akleao/docker-compose.prod.yml restart nginx
```

## Cloud SQL Proxy

The Cloud SQL Proxy runs as a systemd service on the VM, allowing the Docker containers to connect to Cloud SQL PostgreSQL.

### Service Configuration

Location: `/etc/systemd/system/cloud-sql-proxy.service`

```ini
[Unit]
Description=Cloud SQL Proxy
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/cloud-sql-proxy --address 0.0.0.0 --port 5432 akleao-research-v0-481218:us-central1:akleao-db
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Manage Proxy

```bash
# Check status
gcloud compute ssh akleao-vm --zone=us-central1-a --command="sudo systemctl status cloud-sql-proxy"

# Restart
gcloud compute ssh akleao-vm --zone=us-central1-a --command="sudo systemctl restart cloud-sql-proxy"

# View logs
gcloud compute ssh akleao-vm --zone=us-central1-a --command="sudo journalctl -u cloud-sql-proxy -f"
```

## Troubleshooting

### Container can't connect to database

1. Check Cloud SQL Proxy is running:
   ```bash
   sudo systemctl status cloud-sql-proxy
   ```

2. Verify it's listening on all interfaces:
   ```bash
   sudo ss -tlnp | grep 5432
   # Should show *:5432, not 127.0.0.1:5432
   ```

3. Check docker-compose.prod.yml has `extra_hosts`:
   ```yaml
   extra_hosts:
     - "host.docker.internal:host-gateway"
   ```

### API returning 401 errors

1. Check if it's Anthropic/OpenAI API auth error (check error message format)
2. Verify API keys are in container:
   ```bash
   sudo docker compose -f /opt/akleao/docker-compose.prod.yml exec api env | grep API_KEY
   ```
3. If keys were updated in .env, recreate containers (not just restart):
   ```bash
   sudo docker compose -f docker-compose.prod.yml up -d --force-recreate api celery
   ```

### File uploads failing with "Path not found"

The storage abstraction downloads files from GCS to temp files for processing. Check:
1. GCS_BUCKET is set in .env
2. VM service account has Storage Object Admin role
3. Check celery logs for detailed errors

### WebSocket not connecting

1. Check nginx is proxying /ws/ correctly
2. Verify CORS_ORIGINS includes your frontend domain
3. Check API container logs for WebSocket errors

## Cost Estimate

| Resource | Monthly Cost |
|----------|-------------|
| Compute Engine (e2-small) | ~$13 |
| Cloud SQL (db-f1-micro) | ~$9 |
| Cloud Storage (~10GB) | ~$0.26 |
| Static IP | ~$3 |
| Network Egress | ~$1 |
| Vercel | Free |
| **Total** | **~$26/month** |

## Security Notes

1. **Never commit .env files** - Use .env.example with placeholder values
2. **Rotate API keys** if exposed - GitHub's secret scanning will auto-revoke some keys
3. **SSH access** - Restricted via firewall rules
4. **HTTPS only** - HTTP redirects to HTTPS via nginx

## File Locations on VM

| Path | Purpose |
|------|---------|
| `/opt/akleao` | Application code (git repo) |
| `/opt/akleao/.env` | Environment variables |
| `/etc/letsencrypt` | SSL certificates |
| `/etc/systemd/system/cloud-sql-proxy.service` | Proxy service config |
| `/usr/local/bin/cloud-sql-proxy` | Proxy binary |
