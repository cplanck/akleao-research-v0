# Claude Code Instructions for Akleao Research

## Development Workflow

**Local development setup:**
- **Backend (PostgreSQL, Redis, API, Celery)**: Run in Docker via `docker compose up -d`
- **Frontend**: Run OUTSIDE Docker in dev mode: `cd frontend && npm run dev`

This keeps all backend services containerized while allowing fast frontend hot-reloading.

### Quick Start Commands

```bash
# 1. Start all backend services (PostgreSQL, Redis, API, Celery)
docker compose up -d

# 2. Start frontend (in separate terminal)
cd frontend && npm run dev
```

### First-Time Setup / Seeding from Production

To seed your local database with production data:

```bash
# Make sure postgres is running first
docker compose up -d postgres

# Run the seed script (requires gcloud auth)
./scripts/seed-from-prod.sh

# Or for schema-only (no data):
./scripts/seed-from-prod.sh --schema

# Then start the rest of the services
docker compose up -d
```

### URLs
- Frontend: http://localhost:3000
- API: http://localhost:8000
- PostgreSQL: localhost:5432 (user: akleao, password: akleao_dev, db: akleao)

## Important: PostgreSQL Everywhere

**We use PostgreSQL for both dev and prod** to avoid SQLite/PostgreSQL mismatches.

This prevents issues like:
- Enum type differences (we hit this with ResourceStatus!)
- JSON operator differences
- Type casting differences
- Migration compatibility issues

The local PostgreSQL runs in Docker with dev credentials. Production uses GCP Cloud SQL.

## Production

- **Backend**: GCP Compute Engine (Docker Compose with `docker-compose.prod.yml`)
- **Frontend**: Vercel (auto-deploys from main branch)
- **Database**: PostgreSQL on GCP Cloud SQL
- **Storage**: GCP Cloud Storage for file uploads

## Deploying to Production

```bash
# Deploy backend to GCP
gcloud compute ssh akleao-vm --zone=us-central1-a --command="
  cd /opt/akleao && \
  git pull origin main && \
  docker compose -f docker-compose.prod.yml build && \
  docker compose -f docker-compose.prod.yml up -d --remove-orphans && \
  docker compose -f docker-compose.prod.yml exec -T api python -c 'from api.database import run_migrations; run_migrations()'
"

# Frontend deploys automatically via Vercel when you push to main
```

## Key Architecture Notes

- PostgreSQL for both local dev and production (no more SQLite!)
- Local file storage for dev, GCS for production
- The `api/database.py` auto-detects PostgreSQL connection settings
- The `api/storage.py` handles storage backend detection automatically
- Migrations run automatically on API startup via `init_db()`

## GCP Project Info

- **Project ID**: `akleao-research-v0-481218`
- **Cloud SQL Instance**: `akleao-db` (us-central1)
- **VM**: `akleao-vm` (us-central1-a)

### Retrieve Production DB Password

The production database password is stored on the VM (not in the repo for security). To retrieve it:

```bash
gcloud compute ssh akleao-vm --zone=us-central1-a --command="grep DB_PASSWORD /opt/akleao/.env"
```
