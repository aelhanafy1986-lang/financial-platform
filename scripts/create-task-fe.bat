@echo off
schtasks /Create /TN FreebuffFE /TR "\"C:\Users\Lenovo\start-fb-fe.bat\"" /SC ONCE /ST 23:59 /F
schtasks /Query /TN FreebuffFE /V /FO LIST | findstr /C:"Task To Run"
