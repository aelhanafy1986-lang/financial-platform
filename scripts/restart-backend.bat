@echo off
REM Restart the finance platform backend with current code
cd /d "%~dp0.."
for /f "tokens=5" %%p in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do taskkill /PID %%p /F >nul 2>&1
timeout /t 2 /nobreak >nul
".venv\Scripts\python.exe" -m uvicorn app.main:app --port 8000 >> backend.log 2>&1
