@echo off
REM Zensar Content Studio - one click: installs everything that is missing, then starts the app.
REM First run on a new PC needs internet (Python/Node/packages/models). Afterwards it runs offline.
setlocal
cd /d "%~dp0"
title Zensar Content Studio - setup
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo Setup did not complete. Read the message above, fix the issue, then run start.bat again.
  pause
  exit /b %RC%
)
timeout /t 8 >nul
endlocal
