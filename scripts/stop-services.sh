#!/bin/bash

# Stop script for Akleao Research services

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}=== Stopping Akleao Research Services ===${NC}"

# Stop Celery worker
if [ -f "$PROJECT_ROOT/celery.pid" ]; then
    PID=$(cat "$PROJECT_ROOT/celery.pid")
    if kill -0 "$PID" 2>/dev/null; then
        echo -e "${YELLOW}Stopping Celery worker (PID: $PID)...${NC}"
        kill "$PID"
        rm -f "$PROJECT_ROOT/celery.pid"
        echo -e "${GREEN}✓ Celery worker stopped${NC}"
    else
        rm -f "$PROJECT_ROOT/celery.pid"
        echo -e "${YELLOW}Celery worker was not running${NC}"
    fi
else
    # Try to find and kill any celery workers for this project
    pkill -f "celery.*akleao_tasks" 2>/dev/null && echo -e "${GREEN}✓ Celery workers stopped${NC}" || echo -e "${YELLOW}No Celery workers found${NC}"
fi

# Optionally stop Redis (commented out by default as other apps may use it)
# echo -e "${YELLOW}Stopping Redis...${NC}"
# redis-cli shutdown 2>/dev/null && echo -e "${GREEN}✓ Redis stopped${NC}" || echo -e "${YELLOW}Redis was not running${NC}"

echo ""
echo -e "${GREEN}=== Services stopped ===${NC}"
echo ""
echo "Note: Redis was left running as other applications may depend on it."
echo "To stop Redis manually: redis-cli shutdown"
