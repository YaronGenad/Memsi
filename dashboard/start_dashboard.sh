#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "Starting Memsi Control Dashboard..."
cd "$SCRIPT_DIR/backend"
uvicorn main:app --host 127.0.0.1 --port 8765 --reload &
BACKEND_PID=$!
echo "Backend running on http://localhost:8765 (PID $BACKEND_PID)"
cd "$SCRIPT_DIR/frontend"
npm run dev &
FRONTEND_PID=$!
echo "Frontend dev server running (PID $FRONTEND_PID)"
echo ""
echo "Press Ctrl+C to stop both"
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT
wait
