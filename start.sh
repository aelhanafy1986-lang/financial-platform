#!/bin/sh
# Render start command. The build step (npm ci + vite build + pip install)
# already ran; this script only boots the server on $PORT.
export PYTHONUNBUFFERED=1
export MPLBACKEND=Agg
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --timeout-keep-alive 65 --no-access-log
