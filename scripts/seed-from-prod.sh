#!/bin/bash
# Seed local PostgreSQL database from production (via Cloud SQL Proxy)
#
# Prerequisites:
# 1. gcloud CLI authenticated
# 2. cloud-sql-proxy installed (brew install cloud-sql-proxy)
# 3. Local PostgreSQL running (docker compose up postgres)
#
# Usage:
#   ./scripts/seed-from-prod.sh              # Full sync (schema + data)
#   ./scripts/seed-from-prod.sh --schema     # Schema only (no data)

set -e

# Configuration
PROJECT_ID="akleao-research-v0-481218"
INSTANCE_CONNECTION="akleao-research-v0-481218:us-central1:akleao-db"
PROD_DB="akleao"
PROD_USER="akleao_user"
PROXY_PORT=15432  # Use non-standard port to avoid conflicts

LOCAL_USER="akleao"
LOCAL_DB="akleao"
LOCAL_DUMP="/tmp/akleao_prod_dump.sql"

# Parse arguments
SCHEMA_FLAG=""
if [[ "$1" == "--schema" ]]; then
    SCHEMA_FLAG="--schema-only"
    echo "Schema-only mode: will not copy data"
fi

echo "=== Seeding Local Database from Production ==="
echo ""

# Check if local postgres is running
echo "Checking local PostgreSQL..."
if ! docker compose ps postgres 2>/dev/null | grep -q "healthy"; then
    echo "Error: Local PostgreSQL is not running or not healthy!"
    echo "Start it with: docker compose up -d postgres"
    exit 1
fi
echo "Local PostgreSQL is running."

# Check gcloud auth
echo ""
echo "Checking gcloud authentication..."
if ! gcloud auth print-access-token > /dev/null 2>&1; then
    echo "Error: Not authenticated with gcloud."
    echo "Run: gcloud auth login"
    exit 1
fi
echo "gcloud is authenticated."

# Check for cloud-sql-proxy
echo ""
echo "Checking for cloud-sql-proxy..."
if ! command -v cloud-sql-proxy &> /dev/null; then
    echo "Error: cloud-sql-proxy not found!"
    echo "Install with: brew install cloud-sql-proxy"
    exit 1
fi
echo "cloud-sql-proxy is available."

# Get production database password
echo ""
echo "Enter production database password for $PROD_USER:"
read -s PROD_PASSWORD
echo ""

if [[ -z "$PROD_PASSWORD" ]]; then
    echo "Error: Password cannot be empty"
    exit 1
fi

# Cleanup function
PROXY_PID=""
cleanup() {
    echo ""
    echo "Cleaning up..."
    if [[ -n "$PROXY_PID" ]]; then
        kill $PROXY_PID 2>/dev/null || true
    fi
    rm -f $LOCAL_DUMP
}
trap cleanup EXIT

# Start Cloud SQL Proxy
echo ""
echo "Starting Cloud SQL Proxy on port $PROXY_PORT..."
cloud-sql-proxy --port $PROXY_PORT $INSTANCE_CONNECTION &
PROXY_PID=$!
sleep 3

# Verify proxy is running
if ! kill -0 $PROXY_PID 2>/dev/null; then
    echo "Error: Cloud SQL Proxy failed to start"
    exit 1
fi
echo "Cloud SQL Proxy running (PID: $PROXY_PID)"

# Export from production using postgres Docker container
# Use host.docker.internal to connect to proxy running on host machine
echo ""
echo "Exporting from production database..."
docker run --rm \
    -e PGPASSWORD="$PROD_PASSWORD" \
    postgres:15-alpine pg_dump \
    -h host.docker.internal -p $PROXY_PORT \
    -U $PROD_USER -d $PROD_DB \
    $SCHEMA_FLAG \
    --no-owner \
    --no-acl \
    > $LOCAL_DUMP

echo "Export complete: $(du -h $LOCAL_DUMP | cut -f1)"

# Reset local database
echo ""
echo "Resetting local database..."
# Terminate existing connections before dropping
docker exec simage-rag-v0-postgres-1 psql -U $LOCAL_USER -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$LOCAL_DB' AND pid <> pg_backend_pid();" 2>/dev/null || true
docker exec simage-rag-v0-postgres-1 psql -U $LOCAL_USER -d postgres -c "DROP DATABASE IF EXISTS $LOCAL_DB;" 2>/dev/null || true
docker exec simage-rag-v0-postgres-1 psql -U $LOCAL_USER -d postgres -c "CREATE DATABASE $LOCAL_DB;"
echo "Local database reset."

# Import to local
echo ""
echo "Importing to local database..."
docker cp $LOCAL_DUMP simage-rag-v0-postgres-1:/tmp/dump.sql
docker exec simage-rag-v0-postgres-1 psql -U $LOCAL_USER -d $LOCAL_DB -f /tmp/dump.sql 2>&1 | grep -E "(ERROR|setval)" | head -10 || true
docker exec simage-rag-v0-postgres-1 rm /tmp/dump.sql
echo "Import complete."

# Summary
echo ""
echo "=== Done! ==="
echo ""
echo "Local database seeded from production."
if [[ -n "$SCHEMA_FLAG" ]]; then
    echo "Mode: Schema only (no data)"
else
    echo "Mode: Full sync (schema + data)"
fi
echo ""
echo "Connection: postgresql://$LOCAL_USER:akleao_dev@localhost:5432/$LOCAL_DB"
echo ""
echo "Restart the API to pick up the new data:"
echo "  pkill -f 'uvicorn api.app' && source .venv/bin/activate && uvicorn api.app:app --reload"
