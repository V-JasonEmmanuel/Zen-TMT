@echo off
REM Builds an offline package bundle for a server that cannot reach pypi.org.
REM Run on a Windows PC WITH internet and the SAME Python version as the server (3.12 recommended),
REM then copy the "wheels" folder next to start.bat on the server and run start.bat there.
REM   make_offline_bundle.bat        -> base packages + PyTorch (CUDA 12.4 build) + image libraries
REM   make_offline_bundle.bat cpu    -> CPU build of PyTorch instead
setlocal
cd /d "%~dp0.."
set "FLAVOUR=cu124"
if /i "%~1"=="cpu" set "FLAVOUR=cpu"
python -m pip download -r requirements.txt -d wheels || goto :fail
python -m pip download torch --index-url https://download.pytorch.org/whl/%FLAVOUR% -d wheels || goto :fail
python -m pip download -r requirements-images.txt -d wheels || goto :fail
python -m pip download pip setuptools wheel -d wheels
echo.
echo Done: copy the "wheels" folder to the server (next to start.bat). Models still download on first run,
echo or copy the "models" folder from this PC as well.
pause
exit /b 0
:fail
echo Download failed - check the internet connection.
pause
exit /b 1
