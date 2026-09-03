#!/bin/bash

echo "Starting Chat System"
echo "=========================="

# Ensure logs directory exists
mkdir -p logs

# Function to check and free ports
check_port() {
    local port=$1
    # Only target TCP LISTENers to avoid killing incidental connections
    local pids
    pids=$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
    if [ -n "$pids" ]; then
        echo "Port $port in use by PIDs: $pids. Terminating..."
        kill $pids 2>/dev/null || true
        sleep 1
        # Force kill if still present
        local pids2
        pids2=$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
        if [ -n "$pids2" ]; then
            echo "Force terminating remaining PIDs on $port: $pids2"
            kill -9 $pids2 2>/dev/null || true
            sleep 1
        fi
    fi
}

# Clean up old processes
echo "Cleaning old processes..."
pkill -f "python.*backend.py" 2>/dev/null || true
pkill -f "npm.*dev" 2>/dev/null || true
# Extra cleanup for child processes that may outlive npm
pkill -f "vite.*serve" 2>/dev/null || true
pkill -f "node.*vite" 2>/dev/null || true
pkill -f "react-scripts.*start" 2>/dev/null || true

# Resolve backend ports through the same .env loader used by the backend.
FILE_SERVER_PORT=$(python3 -c 'from backend_app.settings import settings; print(settings.http_server_port)')
BACKEND_PORT=$(python3 -c 'from backend_app.settings import settings; print(settings.backend_port)')
FRONTEND_PORT=$(python3 -c 'from backend_app.settings import settings; print(settings.frontend_port)')

export NEXT_PUBLIC_BACKEND_URL=${NEXT_PUBLIC_BACKEND_URL:-http://localhost:$BACKEND_PORT}

# Check and clean ports (only LISTENers)
check_port "$FILE_SERVER_PORT"
check_port "$BACKEND_PORT"
check_port "$FRONTEND_PORT"

echo "Cleanup completed."
echo ""

# Start backend API
echo "Starting backend API..."
nohup python3 backend.py > logs/backend.log 2>&1 &
BACKEND_PID=$!
echo "Backend PID: $BACKEND_PID"
echo "API running on: http://localhost:$BACKEND_PORT"
echo "File service running on: http://localhost:$FILE_SERVER_PORT"

# Wait for backend to initialize
sleep 3

# Start frontend (React, default port: $FRONTEND_PORT)
echo ""
echo "Starting React frontend..."
cd frontend || exit
nohup npm run dev -- -p "$FRONTEND_PORT" > ../logs/frontend.log 2>&1 &
FRONTEND_PID=$!
cd ..
echo "Frontend PID: $FRONTEND_PID"
echo "Frontend running on: http://localhost:$FRONTEND_PORT"

# Save PIDs
echo $BACKEND_PID > logs/backend.pid
echo $FRONTEND_PID > logs/frontend.pid

echo ""
echo "All services started successfully."
echo ""
echo "Service URLs:"
echo "  Backend API:  http://localhost:$BACKEND_PORT"
echo "  Frontend:     http://localhost:$FRONTEND_PORT"
echo "  File Service: http://localhost:$FILE_SERVER_PORT"
echo ""
echo "Log files:"
echo "  Backend: logs/backend.log"
echo "  Frontend: logs/frontend.log"
echo ""
echo "Stop services: ./stop.sh"
