@echo off
REM Stops the Zensar Content Studio server started by start.bat (port 8000, or %ZCS_PORT% if set).
setlocal
if "%ZCS_PORT%"=="" (set "PORT=8000") else (set "PORT=%ZCS_PORT%")
powershell -NoProfile -Command "$c = Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue; if ($c) { Stop-Process -Id $c.OwningProcess -Force; 'Content Studio stopped.' } else { 'Content Studio is not running.' }"
ping -n 3 127.0.0.1 >nul
endlocal
