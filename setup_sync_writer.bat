@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
set "EPOL_PYTHON=python"
if exist ".venv\Scripts\python.exe" set "EPOL_PYTHON=%~dp0.venv\Scripts\python.exe"
"%EPOL_PYTHON%" -B setup_sync_writer.py %*
set "RESULT=%errorlevel%"
echo.
pause
endlocal & exit /b %RESULT%
