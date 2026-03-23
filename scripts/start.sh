#!/bin/bash
# Start all Spendly services in the background.
# Automatically stops any already-running services first.
# Logs go to logs/<service>.log
# Usage: bash scripts/start.sh

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
LOGS="$ROOT/logs"
mkdir -p "$LOGS"

# Stop existing services before starting fresh
bash "$ROOT/scripts/stop.sh"

export PATH="$HOME/.local/bin:$PATH"

start_service() {
    local name="$1"
    local script="$2"
    local logfile="$LOGS/$name.log"

    # setsid puts the process in its own process group so stop.sh can kill
    # the whole group (wrapper + children like uvicorn/npm/ollama)
    setsid bash "$script" > "$logfile" 2>&1 &
    local pid=$!
    echo "$pid" > "$LOGS/$name.pid"
    echo "Started $name (PID $pid) → $logfile"
}

start_service "backend"  "$ROOT/scripts/start-backend.sh"
start_service "worker"   "$ROOT/scripts/start-worker.sh"
start_service "frontend" "$ROOT/scripts/start-frontend.sh"

echo ""
echo "All services started. To follow logs:"
echo "  tail -f logs/backend.log"
echo "  tail -f logs/worker.log"
echo "  tail -f logs/frontend.log"
echo ""
echo "Note: Ollama is expected to be running natively (not managed here)"
echo ""
echo "To stop all services: bash scripts/stop.sh"
