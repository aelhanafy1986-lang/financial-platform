@echo off
REM Smart Financial Platform - self-diagnosing startup (writes run-log.txt in project root)
setlocal enabledelayedexpansion
cd /d "%~dp0.."
set LOG=run-log.txt

echo === Freebuff finance platform diagnostic run === > "%LOG%"
echo started: %date% %time% >> "%LOG%"
echo [step0] cwd=%CD% >> "%LOG%"

echo [step1] checking python... >> "%LOG%"
python --version >> "%LOG%" 2>&1
if errorlevel 1 (
    echo PYTHON_NOT_FOUND >> "%LOG%"
    py --version >> "%LOG%" 2>&1
    where python >> "%LOG%" 2>&1
    echo DONE_WITH_ERRORS: python missing - see RUNBOOK T1 >> "%LOG%"
    start notepad "%LOG%"
    exit /b 1
)

echo [step2] creating venv if missing... >> "%LOG%"
if not exist .venv (
    python -m venv .venv >> "%LOG%" 2>&1
    if errorlevel 1 (
        echo VENV_FAILED >> "%LOG%"
        echo DONE_WITH_ERRORS: venv - RUNBOOK T1 >> "%LOG%"
        start notepad "%LOG%"
        exit /b 1
    )
)
call .venv\Scripts\activate.bat
echo [step2b] venv python: >> "%LOG%"
python --version >> "%LOG%" 2>&1

echo [step3] pip install... >> "%LOG%"
python -m pip install --upgrade pip >> "%LOG%" 2>&1
pip install -r requirements.txt >> "%LOG%" 2>&1
if errorlevel 1 (
    echo PIP_FAILED - RUNBOOK T2 >> "%LOG%"
    echo DONE_WITH_ERRORS >> "%LOG%"
    start notepad "%LOG%"
    exit /b 1
)

echo [step4] generating sample file... >> "%LOG%"
if not exist sample-financials.xlsx (
    python scripts/make_sample.py >> "%LOG%" 2>&1
)

echo [step5] importing backend app as smoke test... >> "%LOG%"
python -c "from app.main import app; print('IMPORT_OK')" >> "%LOG%" 2>&1
findstr /C:"IMPORT_OK" "%LOG%" >nul
if errorlevel 1 (
    echo APP_IMPORT_FAILED >> "%LOG%"
    echo DONE_WITH_ERRORS >> "%LOG%"
    start notepad "%LOG%"
    exit /b 1
)

echo [step6] npm install... >> "%LOG%"
pushd frontend
where npm >> "%LOG%" 2>&1
if not exist node_modules (
    call npm install >> "%LOG%" 2>&1
    if errorlevel 1 (
        echo NPM_FAILED - RUNBOOK T4 >> "%LOG%"
        popd
        echo DONE_WITH_ERRORS >> "%LOG%"
        start notepad "%LOG%"
        exit /b 1
    )
)
popd

echo [step7] starting servers in separate windows... >> "%LOG%"
start "freebuff-backend" cmd /k "cd /d %CD% && .venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000"
start "freebuff-frontend" cmd /k "cd /d %CD%\frontend && npm run dev"

echo [step8] waiting 12 seconds then probing... >> "%LOG%"
timeout /t 12 /nobreak >nul
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/health -TimeoutSec 5).Content } catch { 'BACKEND_DOWN: ' + $_.Exception.Message }" >> "%LOG%" 2>&1
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5173 -TimeoutSec 5).StatusCode } catch { 'FRONTEND_DOWN: ' + $_.Exception.Message }" >> "%LOG%" 2>&1

echo === DONE === >> "%LOG%"
start notepad "%LOG%"
