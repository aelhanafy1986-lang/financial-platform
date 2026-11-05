@echo off
REM Register the backend restart task with a correctly quoted path
schtasks /Create /TN FreebuffRestart /TR "\"C:\Users\Lenovo\restart-fb.bat\"" /SC ONCE /ST 23:59 /F
schtasks /Query /TN FreebuffRestart /V /FO LIST | findstr /C:"Task To Run"
