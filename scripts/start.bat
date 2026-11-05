@echo off
REM Smart Financial Platform - one-click startup (Windows)
setlocal enabledelayedexpansion
cd /d "%~dp0.."

echo [1/4] Checking Python virtual environment...
if not exist .venv (
    python -m venv .venv
    if errorlevel 1 goto python_missing
)
call .venv\Scripts\activate.bat

echo [2/4] Installing backend dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 goto pip_failed

if not exist sample-financials.xlsx (
    echo Generating sample financial file...
    python scripts/make_sample.py
)

echo [3/4] Installing frontend dependencies...
pushd frontend
if not exist node_modules (
    call npm install
    if errorlevel 1 goto npm_failed
)
popd

echo [4/4] Starting servers...
start "backend" cmd /k "call .venv\Scripts\activate.bat && uvicorn app.main:app --reload --port 8000"
start "frontend" cmd /k "cd frontend && npm run dev"

timeout /t 6 /nobreak >nul
echo.
echo === READY ===
echo Backend  : http://localhost:8000
echo Frontend : http://localhost:5173
echo (open the frontend URL in your browser)
echo.
goto :eof

:python_missing
echo ERROR: Python not found. Install Python 3.11+ and enable "Add python.exe to PATH".
echo See docs/RUNBOOK.md section T1.
pause
goto :eof

:pip_failed
echo ERROR: pip install failed. See docs/RUNBOOK.md section T2.
pause
goto :eof

:npm_failed
echo ERROR: npm install failed. See docs/RUNBOOK.md section T4.
pause
goto :eof
