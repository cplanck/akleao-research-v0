#!/bin/bash

# Start script for Akleao Research services
# This script starts Redis and Celery worker for background job processing

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Akleao Research Services Startup ===${NC}"

# Check if Redis is installed
if ! command -v redis-server &> /dev/null; then
    echo -e "${YELLOW}Redis not found. Installing via Homebrew...${NC}"
    if command -v brew &> /dev/null; then
        brew install redis
    else
        echo -e "${RED}Error: Homebrew not found. Please install Redis manually.${NC}"
        echo "  macOS: brew install redis"
        echo "  Linux: sudo apt-get install redis-server"
        exit 1
    fi
fi

# Check if Redis is already running
if redis-cli ping &> /dev/null; then
    echo -e "${GREEN}✓ Redis is already running${NC}"
else
    echo -e "${YELLOW}Starting Redis via Homebrew services...${NC}"
    brew services start redis
    sleep 2
    if redis-cli ping &> /dev/null; then
        echo -e "${GREEN}✓ Redis started successfully${NC}"
    else
        echo -e "${RED}Failed to start Redis${NC}"
        exit 1
    fi
fi

# Install Python dependencies if needed
echo -e "${YELLOW}Checking Python dependencies...${NC}"
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    python3 -m venv .venv
    source .venv/bin/activate
fi

# Install/upgrade dependencies
pip install -e . --quiet

# Check if celery and redis packages are installed
if ! python -c "import celery" 2>/dev/null; then
    echo -e "${YELLOW}Installing Celery...${NC}"
    pip install celery redis
fi

echo -e "${GREEN}✓ Python dependencies installed${NC}"

# Start Celery worker in background
echo -e "${YELLOW}Starting Celery worker...${NC}"

# Kill any existing Celery workers for this project
pkill -f "celery.*akleao_tasks" 2>/dev/null || true

# Start Celery worker
celery -A api.tasks worker --loglevel=info --detach --pidfile="$PROJECT_ROOT/celery.pid" --logfile="$PROJECT_ROOT/celery.log"

sleep 2

if [ -f "$PROJECT_ROOT/celery.pid" ] && kill -0 $(cat "$PROJECT_ROOT/celery.pid") 2>/dev/null; then
    echo -e "${GREEN}✓ Celery worker started (PID: $(cat $PROJECT_ROOT/celery.pid))${NC}"
    echo -e "  Logs: $PROJECT_ROOT/celery.log"
else
    echo -e "${RED}Failed to start Celery worker. Check celery.log for details.${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}=== All services started! ===${NC}"
echo ""
echo "To start the API server:"
echo "  cd $PROJECT_ROOT && source .venv/bin/activate && uvicorn api.app:app --reload"
echo ""
echo "To start the frontend:"
echo "  cd $PROJECT_ROOT/frontend && npm run dev"
echo ""
echo "To stop services:"
echo "  $SCRIPT_DIR/stop-services.sh"
