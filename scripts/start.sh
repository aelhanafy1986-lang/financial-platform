#!/usr/bin/env bash
# Smart Financial Platform - one-click startup (macOS / Linux)
set -e
cd "$(dirname "$0")/.."

echo "[1/4] Checking Python virtual environment..."
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "[2/4] Installing backend dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

if [ ! -f sample-financials.xlsx ]; then
  echo "Generating sample financial file..."
  python scripts/make_sample.py
fi

echo "[3/4] Installing frontend dependencies..."
if [ ! -d frontend/node_modules ]; then
  (cd frontend && npm install)
fi

echo "[4/4] Starting servers..."
uvicorn app.main:app --reload --port 8000 &
BACK_PID=$!
(cd frontend && npm run dev) &
FRONT_PID=$!

trap 'kill $BACK_PID $FRONT_PID 2>/dev/null' EXIT
echo ""
echo "=== READY ==="
echo "Backend  : http://localhost:8000"
echo "Frontend : http://localhost:5173"
echo "Press Ctrl+C to stop both servers."
wait
