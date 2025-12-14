#!/bin/bash
# Pull production data to local development environment
#
# Usage:
#   ./scripts/pull-prod-data.sh           # Pull database only
#   ./scripts/pull-prod-data.sh --files   # Also sync uploaded files
#
# Prerequisites:
# - gcloud CLI installed and authenticated
# - Cloud SQL Admin API enabled
# - gsutil configured
# - PostgreSQL client (pg_dump, psql) installed locally

set -e

# Configuration
PROJECT_ID="akleao-research-v0"
INSTANCE="akleao-db"
DATABASE="akleao"
BUCKET="akleao-research-uploads"
LOCAL_DB="akleao.db"
SYNC_FILES=false

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --files) SYNC_FILES=true ;;
        *) echo "Unknown parameter: $1"; exit 1 ;;
    esac
    shift
done

echo "=== Pulling Production Data ==="
echo "Project: $PROJECT_ID"
echo "Database: $INSTANCE/$DATABASE"
echo ""

# Check prerequisites
if ! command -v gcloud &> /dev/null; then
    echo "Error: gcloud CLI not installed"
    exit 1
fi

if ! command -v gsutil &> /dev/null; then
    echo "Error: gsutil not installed"
    exit 1
fi

# Backup current local database
if [ -f "$LOCAL_DB" ]; then
    echo "[1/4] Backing up current local database..."
    cp "$LOCAL_DB" "${LOCAL_DB}.backup.$(date +%Y%m%d_%H%M%S)"
fi

# Export PostgreSQL database
echo "[2/4] Exporting production database..."
TEMP_SQL="/tmp/prod_dump_$(date +%Y%m%d_%H%M%S).sql"
GCS_BACKUP="gs://$BUCKET/backups/latest.sql"

# Create SQL export using gcloud
gcloud sql export sql "$INSTANCE" "$GCS_BACKUP" \
    --database="$DATABASE" \
    --project="$PROJECT_ID" \
    --offload \
    --async 2>/dev/null || {
    echo "Note: Export initiated. Waiting for completion..."
}

# Wait for export to complete (poll for the file)
echo "Waiting for export to complete..."
for i in {1..60}; do
    if gsutil -q stat "$GCS_BACKUP" 2>/dev/null; then
        break
    fi
    sleep 5
done

# Download the SQL dump
echo "Downloading SQL dump..."
gsutil cp "$GCS_BACKUP" "$TEMP_SQL"

# Convert PostgreSQL dump to SQLite
echo "[3/4] Converting to SQLite..."
python3 << 'EOF'
import re
import sqlite3
import sys

# Read the PostgreSQL dump
with open('/tmp/prod_dump.sql', 'r') as f:
    content = f.read()

# Simple conversion patterns (this is a basic converter)
# For production use, consider pgloader or a more robust tool

# Remove PostgreSQL-specific statements
content = re.sub(r'SET\s+\w+\s*=.*?;', '', content)
content = re.sub(r'SELECT\s+pg_catalog\..*?;', '', content)
content = re.sub(r'ALTER\s+TABLE.*?OWNER.*?;', '', content)
content = re.sub(r'GRANT\s+.*?;', '', content)
content = re.sub(r'REVOKE\s+.*?;', '', content)

# Convert data types
content = re.sub(r'\bSERIAL\b', 'INTEGER', content, flags=re.IGNORECASE)
content = re.sub(r'\bBIGSERIAL\b', 'INTEGER', content, flags=re.IGNORECASE)
content = re.sub(r'\bBYTEA\b', 'BLOB', content, flags=re.IGNORECASE)
content = re.sub(r'\bTIMESTAMP\s+WITH\s+TIME\s+ZONE\b', 'DATETIME', content, flags=re.IGNORECASE)
content = re.sub(r'\bTIMESTAMP\s+WITHOUT\s+TIME\s+ZONE\b', 'DATETIME', content, flags=re.IGNORECASE)
content = re.sub(r'\bTIMESTAMP\b', 'DATETIME', content, flags=re.IGNORECASE)
content = re.sub(r'\bBOOLEAN\b', 'INTEGER', content, flags=re.IGNORECASE)
content = re.sub(r'::[\w\[\]]+', '', content)  # Remove type casts

# Convert boolean values
content = re.sub(r"'t'::boolean", '1', content)
content = re.sub(r"'f'::boolean", '0', content)
content = re.sub(r'\btrue\b', '1', content, flags=re.IGNORECASE)
content = re.sub(r'\bfalse\b', '0', content, flags=re.IGNORECASE)

# Write to temp file for sqlite import
with open('/tmp/sqlite_import.sql', 'w') as f:
    f.write(content)

print("Conversion complete. Run the following to import:")
print("  sqlite3 akleao.db < /tmp/sqlite_import.sql")
EOF

# Note: Full conversion is complex - consider using pgloader for production
echo ""
echo "Note: PostgreSQL to SQLite conversion is basic."
echo "For complex schemas, consider using pgloader:"
echo "  https://pgloader.io/"
echo ""

# Sync files if requested
if [ "$SYNC_FILES" = true ]; then
    echo "[4/4] Syncing uploaded files from GCS..."
    mkdir -p uploads
    gsutil -m rsync -r "gs://$BUCKET/uploads/" uploads/
    echo "Files synced!"
else
    echo "[4/4] Skipping file sync (use --files to include)"
fi

echo ""
echo "=== Pull Complete ==="
echo ""
echo "SQL dump saved to: $TEMP_SQL"
echo ""
echo "To complete the import:"
echo "  1. Review the SQL dump"
echo "  2. Import to SQLite: sqlite3 $LOCAL_DB < /tmp/sqlite_import.sql"
echo ""
echo "Or connect directly to production PostgreSQL for testing:"
echo "  1. Start Cloud SQL Proxy: cloud-sql-proxy $PROJECT_ID:us-central1:$INSTANCE"
echo "  2. Set DB_HOST=127.0.0.1 in your .env"
