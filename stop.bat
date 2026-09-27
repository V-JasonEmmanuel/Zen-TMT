@echo off
REM Stops the Zensar Content Studio server started by start.bat.
powershell -NoProfile -Command "$c = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue; if ($c) { Stop-Process -Id $c.OwningProcess -Force; 'Content Studio stopped.' } else { 'Content Studio is not running.' }"
timeout /t 3 >nul
