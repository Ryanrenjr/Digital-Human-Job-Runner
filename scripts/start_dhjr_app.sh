#!/bin/bash
# Digital Human Job Runner - Start Script
set -e

WORKSPACE="${DHJR_WORKSPACE:-$HOME/AI-Workspace}"
LOGS_DIR=$WORKSPACE/logs
BACKEND_DIR=$WORKSPACE/app/backend
FRONTEND_DIR=$WORKSPACE/app/frontend
ENV_FILE="$WORKSPACE/.env"

if [ -f "$ENV_FILE" ]; then
  set -a
  . "$ENV_FILE"
  set +a
fi

WORKSPACE="${DHJR_WORKSPACE:-$WORKSPACE}"
LOGS_DIR=$WORKSPACE/logs
BACKEND_DIR=$WORKSPACE/app/backend
FRONTEND_DIR=$WORKSPACE/app/frontend
UVICORN="${DHJR_UVICORN_BIN:-$HOME/miniconda3/bin/uvicorn}"
BACKEND_HOST="${DHJR_BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${DHJR_BACKEND_PORT:-8008}"
FRONTEND_HOST="${DHJR_FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${DHJR_FRONTEND_PORT:-5173}"

mkdir -p "$LOGS_DIR"

# Backend
echo "[DHJR] Starting backend on http://$BACKEND_HOST:$BACKEND_PORT ..."
cd "$BACKEND_DIR"
nohup "$UVICORN" main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" \
  >> "$LOGS_DIR/app_backend.log" 2>&1 &
BACKEND_PID=$!
echo "[DHJR] Backend PID: $BACKEND_PID"

# Frontend
echo "[DHJR] Starting frontend on http://$FRONTEND_HOST:$FRONTEND_PORT ..."
cd "$FRONTEND_DIR"
nohup npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" \
  >> "$LOGS_DIR/app_frontend.log" 2>&1 &
FRONTEND_PID=$!
echo "[DHJR] Frontend PID: $FRONTEND_PID"

echo "[DHJR] Done. Logs: $LOGS_DIR/"
echo "[DHJR]   Backend  -> $LOGS_DIR/app_backend.log"
echo "[DHJR]   Frontend -> $LOGS_DIR/app_frontend.log"
