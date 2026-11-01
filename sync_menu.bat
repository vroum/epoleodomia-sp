@echo off
setlocal DisableDelayedExpansion
title Spetses GIS - Sync Menu
REM Menu/direct modes and exit codes live in sync_launcher.py.
REM Passwords are read by Python and never parsed by cmd.exe.
cd /d "%~dp0"
set "EPOL_PYTHON=python"
if exist ".venv\Scripts\python.exe" set "EPOL_PYTHON=%~dp0.venv\Scripts\python.exe"
"%EPOL_PYTHON%" --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    pause
    exit /b 1
)
"%EPOL_PYTHON%" -B sync_launcher.py %*
set "RESULT=%errorlevel%"
echo.
pause
endlocal & exit /b %RESULT%
