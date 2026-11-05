@echo off
cd /d "%~dp0.."
".venv\Scripts\python.exe" -m uvicorn app.main:app --port 8000 > backend.log 2>&1
