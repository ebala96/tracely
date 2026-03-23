#!/bin/bash
cd "$(dirname "$0")/../backend"
export PATH="$HOME/.local/bin:$PATH"
uv run uvicorn main:app --reload --port 8000
