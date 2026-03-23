#!/bin/bash
# Tear down Spendly — stops app processes AND Docker infrastructure.
# Use stop.sh instead if you only want to stop the app (backend/worker/frontend).

cd "$(dirname "$0")/.."

echo "=== Spendly Teardown ==="

# 1. Stop app processes (backend, worker, frontend)
if [ -f scripts/stop.sh ]; then
    echo "→ Stopping app services..."
    bash scripts/stop.sh
fi

# 2. Stop Docker infrastructure
echo "→ Stopping Docker services..."
docker compose down

echo ""
echo "All services stopped."
echo "Data volumes (postgres, qdrant, redis) are preserved."
echo "To also delete all data:  docker compose down -v"
echo "To restart everything:    ./scripts/setup.sh && ./scripts/start.sh"
