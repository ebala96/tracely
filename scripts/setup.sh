#!/bin/bash
set -e

cd "$(dirname "$0")/.."

echo "=== Spendly Setup ==="

# 1. Copy env if not already done
if [ ! -f .env ]; then
    cp .env.example .env
    echo "→ .env created from .env.example"
    echo "→ Edit .env and set strong passwords, then re-run this script"
    exit 0
fi

# 2. Start infrastructure services
echo "→ Starting infrastructure services..."
docker compose up -d postgres qdrant redis nats

# 3. Wait for Postgres to be ready
echo "→ Waiting for PostgreSQL..."
until docker compose exec postgres pg_isready -U spendly 2>/dev/null; do
    sleep 2
done
echo "→ PostgreSQL ready"

# 4. Install Python dependencies
echo "→ Installing Python dependencies..."
if ! command -v uv &>/dev/null; then
    echo "→ Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi
cd backend
uv sync --quiet
cd ..

# 5. Run Alembic migrations
echo "→ Running database migrations..."
cd backend
uv run alembic upgrade head
cd ..

# 6. Seed categories
echo "→ Seeding categories..."
uv run --project backend python scripts/seed_categories.py

# 7. Pull Ollama models
echo "→ Checking Ollama..."
if command -v ollama &>/dev/null && ollama list &>/dev/null 2>&1; then
    echo "→ Pulling Ollama models (this may take a while on first run)..."
    ollama pull qwen2.5:3b
    ollama pull nomic-embed-text
else
    echo "→ Ollama server not reachable. Skip for now."
    echo "  To start locally:   ollama serve  (then re-run this script)"
    echo "  For WSL2 + Windows: install Ollama on Windows, it auto-starts."
    echo "  Then set in .env:   OLLAMA_BASE_URL=http://host.docker.internal:11434"
    echo "  And pull models in a Windows terminal:"
    echo "    ollama pull qwen2.5:3b"
    echo "    ollama pull nomic-embed-text"
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Start backend:  cd backend && uv run uvicorn main:app --reload --port 8000"
echo "Start worker:   cd backend && uv run python -m workers.nats_worker"
echo "Start frontend: cd frontend && npm install && npm run dev"
