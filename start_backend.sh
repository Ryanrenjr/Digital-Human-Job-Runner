#!/bin/bash
set -e

AI_WORKSPACE="${DHJR_WORKSPACE:-$HOME/AI-Workspace}"
PYTHON_BIN="${DHJR_PYTHON_BIN:-python3}"
BACKEND_HOST="${DHJR_BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${DHJR_BACKEND_PORT:-8018}"

cd "$AI_WORKSPACE/app/backend"
exec "$PYTHON_BIN" -m uvicorn main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT"
