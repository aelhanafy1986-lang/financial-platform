@echo off
REM === Run this from the project folder. It cannot run silently. ===
setlocal
set "ROOT=%~dp0.."
set "LOG=%ROOT%\run-log.txt"

echo Freebuff Finance Platform - launcher
echo Log file: %LOG%
echo(
echo step 0: writing log header...
(
  echo === diagnostic run ===
  echo time: %date% %time%
  echo script dir: %~dp0
  echo root: %ROOT%
  echo current dir: %CD%
) > "%LOG%"
if not exist "%LOG%" (
  echo FATAL: cannot write log file. Close this window and reply to the agent.
  pause
  exit /b 1
)

echo step 1: python?
python --version >> "%LOG%" 2>&1 || echo PYTHON_NOT_FOUND >> "%LOG%"

echo step 2: virtual environment...
if not exist "%ROOT%\.venv" python -m venv "%ROOT%\.venv" >> "%LOG%" 2>&1 || echo VENV_FAILED >> "%LOG%"
call "%ROOT%\.venv\Scripts\activate.bat" >> "%LOG%" 2>&1
python --version >> "%LOG%" 2>&1

echo step 3: installing python packages (2-5 minutes)...
python -m pip install --upgrade pip >> "%LOG%" 2>&1
pip install -r "%ROOT%\requirements.txt" >> "%LOG%" 2>&1 || echo PIP_FAILED >> "%LOG%"

echo step 4: sample file...
if not exist "%ROOT%\sample-financials.xlsx" python "%ROOT%\scripts\make_sample.py" >> "%LOG%" 2>&1

echo step 5: backend smoke test...
cd /d "%ROOT%"
python -c "from app.main import app; print('IMPORT_OK')" >> "%LOG%" 2>&1

echo step 6: npm install (first run takes minutes)...
cd /d "%ROOT%\frontend"
if not exist node_modules call npm install >> "%LOG%" 2>&1 || echo NPM_FAILED >> "%LOG%"
cd /d "%ROOT%"

echo step 7: launching servers (two new windows)...
start "freebuff-backend" cmd /k "cd /d "%ROOT%" && .venv\Scripts\python.exe -m uvicorn app.main:app --port 8000"
start "freebuff-frontend" cmd /k "cd /d "%ROOT%\frontend" && npm run dev"

echo step 8: waiting 15 seconds...
timeout /t 15 /nobreak >nul

echo step 9: probing servers...
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/health -TimeoutSec 5).Content } catch { 'BACKEND_DOWN' }" >> "%LOG%" 2>&1
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5173 -TimeoutSec 5).StatusCode } catch { 'FRONTEND_DOWN' }" >> "%LOG%" 2>&1

echo === COMPLETE === >> "%LOG%"
echo(
echo ================================
echo DONE. Log saved to run-log.txt
echo Backend window: freebuff-backend
echo Frontend window: freebuff-frontend
echo ================================
echo(
echo Keep this window open. Tell the agent it finished.
pause
