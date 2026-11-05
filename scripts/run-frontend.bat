@echo off
cd /d "%~dp0..\frontend"
set "PATH=C:\Program Files\nodejs;%PATH%"
call npm run dev > ..\frontend.log 2>&1
