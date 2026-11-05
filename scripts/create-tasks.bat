@echo off
REM Register both server tasks with correctly quoted absolute paths
schtasks /Create /TN FreebuffBE /TR "\"C:\Users\Lenovo\restart-fb.bat\"" /SC ONCE /ST 23:59 /F
schtasks /Create /TN FreebuffFE /TR "\"C:\Users\Lenovo\start-fb-fe.bat\"" /SC ONCE /ST 23:58 /F
schtasks /Query /TN FreebuffBE /V /FO LIST | findstr /C:"Task To Run"
schtasks /Query /TN FreebuffFE /V /FO LIST | findstr /C:"Task To Run"
