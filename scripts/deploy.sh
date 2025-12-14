#!/bin/bash
# Deploy Akleao Research backend to GCP VM
#
# Usage:
#   ./scripts/deploy.sh              # Deploy to production
#   ./scripts/deploy.sh --skip-tests # Skip tests (not recommended)
#
# Prerequisites:
# - gcloud CLI installed and authenticated
# - SSH access to the VM configured

set -e

# Configuration
VM="akleao-vm"
ZONE="us-central1-a"
REMOTE_DIR="/opt/akleao"
SKIP_TESTS=false

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --skip-tests) SKIP_TESTS=true ;;
        *) echo "Unknown parameter: $1"; exit 1 ;;
    esac
    shift
done

echo "=== Deploying Akleao Research to GCP ==="
echo "VM: $VM"
echo "Zone: $ZONE"
echo ""

# 1. Run tests locally (unless skipped)
if [ "$SKIP_TESTS" = false ]; then
    echo "[1/4] Running tests locally..."
    if command -v pytest &> /dev/null; then
        pytest tests/ -q --tb=short || {
            echo "Tests failed! Aborting deployment."
            echo "Use --skip-tests to deploy anyway (not recommended)"
            exit 1
        }
        echo "Tests passed!"
    else
        echo "pytest not found, skipping tests..."
    fi
else
    echo "[1/4] Skipping tests (--skip-tests flag)"
fi
echo ""

# 2. Deploy to VM
echo "[2/4] Deploying to VM..."
gcloud compute ssh "$VM" --zone="$ZONE" --command="
    set -e
    cd $REMOTE_DIR

    echo 'Pulling latest code...'
    git pull origin main

    echo 'Building Docker images...'
    docker compose -f docker-compose.prod.yml build

    echo 'Stopping old containers...'
    docker compose -f docker-compose.prod.yml down

    echo 'Starting new containers...'
    docker compose -f docker-compose.prod.yml up -d

    echo 'Running database migrations...'
    docker compose -f docker-compose.prod.yml exec -T api python -c 'from api.database import run_migrations; run_migrations()'

    echo 'Cleaning up old images...'
    docker image prune -f

    echo 'Deployment complete!'
"
echo ""

# 3. Wait for health check
echo "[3/4] Waiting for service to start..."
sleep 10
echo ""

# 4. Verify deployment
echo "[4/4] Verifying deployment..."
API_URL=$(gcloud compute instances describe "$VM" --zone="$ZONE" --format='get(networkInterfaces[0].accessConfigs[0].natIP)')

if curl -sf "http://$API_URL:80/health" > /dev/null 2>&1; then
    echo "Health check passed!"
else
    echo "WARNING: Health check failed. Check container logs:"
    echo "  gcloud compute ssh $VM --zone=$ZONE --command='docker compose -f $REMOTE_DIR/docker-compose.prod.yml logs --tail=50'"
fi

echo ""
echo "=== Deployment Complete ==="
echo "API URL: http://$API_URL"
echo ""
echo "Useful commands:"
echo "  View logs:    gcloud compute ssh $VM --zone=$ZONE --command='docker compose -f $REMOTE_DIR/docker-compose.prod.yml logs -f'"
echo "  SSH to VM:    gcloud compute ssh $VM --zone=$ZONE"
echo "  Restart:      gcloud compute ssh $VM --zone=$ZONE --command='docker compose -f $REMOTE_DIR/docker-compose.prod.yml restart'"
