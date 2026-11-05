@echo off
REM One-click launcher: start backend + frontend, then open the dashboard.
set "ROOT=%~dp0"
"%ROOT%.venv\Scripts\python.exe" "%ROOT%start_all.py"
if errorlevel 1 (
  echo.
  echo Failed to start the servers - check backend.log / frontend.log
  pause
  exit /b 1
)
start "" http://localhost:5173
exit /b 0
