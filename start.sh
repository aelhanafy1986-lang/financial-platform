#!/bin/sh
# Render web-service start command. Build step = npm ci && npm run build,
# then this script installs the Python deps and serves the built React app
# AND the /api from one uvicorn process (backend binds to $PORT).
pip install -r requirements.txt
exec gunicorn app.main:app -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:"${PORT}" --timeout 120 --access-logfile - --error-logfile -
