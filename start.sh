#!/bin/bash

# Kill any existing processes on ports 3000 and 8000
echo "Cleaning up existing processes..."
lsof -ti:3000 | xargs kill -9 2>/dev/null
lsof -ti:8000 | xargs kill -9 2>/dev/null

# Get the directory where this script is located
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Start the API server
echo "Starting API server on http://localhost:8000..."
source .venv/bin/activate
uvicorn api.app:app --host 0.0.0.0 --port 8000 &
API_PID=$!

# Start the frontend
echo "Starting frontend on http://localhost:3000..."
cd frontend
npm run dev &
FRONTEND_PID=$!

# Handle cleanup on exit
cleanup() {
    echo ""
    echo "Shutting down..."
    kill $API_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
    exit 0
}

trap cleanup SIGINT SIGTERM

echo ""
echo "================================"
echo "Akleao Research is running!"
echo "  Frontend: http://localhost:3000"
echo "  API:      http://localhost:8000"
echo "  API Docs: http://localhost:8000/docs"
echo "================================"
echo ""
echo "Press Ctrl+C to stop"

# Wait for both processes
wait
