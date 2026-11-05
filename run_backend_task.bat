@echo off
rem Run the FastAPI backend detached via Task Scheduler.
rem %~dp0 = this script's folder (handles spaces in the path safely).
cd /d "%~dp0"
.venv\Scripts\python.exe _server.py >> backend.log 2>&1
