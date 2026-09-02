#!/bin/bash
# Digital Human Job Runner - Stop Script

BACKEND_PORT="${DHJR_BACKEND_PORT:-8008}"
FRONTEND_PORT="${DHJR_FRONTEND_PORT:-5173}"
WORKSPACE="${DHJR_WORKSPACE:-$HOME/AI-Workspace}"
ENV_FILE="$WORKSPACE/.env"

if [ -f "$ENV_FILE" ]; then
  set -a
  . "$ENV_FILE"
  set +a
fi

BACKEND_PORT="${DHJR_BACKEND_PORT:-$BACKEND_PORT}"
FRONTEND_PORT="${DHJR_FRONTEND_PORT:-$FRONTEND_PORT}"
WORKSPACE="${DHJR_WORKSPACE:-$WORKSPACE}"

echo "[DHJR] Stopping services..."

# Backend: kill process using backend port
BACKEND_PID=$(lsof -ti:"$BACKEND_PORT" 2>/dev/null)
if [ -n "$BACKEND_PID" ]; then
    kill "$BACKEND_PID" 2>/dev/null && echo "[DHJR] Backend stopped (PID $BACKEND_PID)."
else
    echo "[DHJR] Backend was not running on port $BACKEND_PORT."
fi

# Frontend: kill process using frontend port
FRONTEND_PID=$(lsof -ti:"$FRONTEND_PORT" 2>/dev/null)
if [ -n "$FRONTEND_PID" ]; then
    kill "$FRONTEND_PID" 2>/dev/null && echo "[DHJR] Frontend stopped (PID $FRONTEND_PID)."
else
    echo "[DHJR] Frontend was not running on port $FRONTEND_PORT."
fi

# Fallback: pkill by configured path (catches child processes)
pkill -f "$WORKSPACE/app/backend" 2>/dev/null || true
pkill -f "$WORKSPACE/app/frontend" 2>/dev/null || true

echo "[DHJR] Done."
