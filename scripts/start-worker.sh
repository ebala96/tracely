#!/bin/bash
cd "$(dirname "$0")/../backend"
export PATH="$HOME/.local/bin:$PATH"
uv run python -m workers.nats_worker
