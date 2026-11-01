@echo off
setlocal DisableDelayedExpansion
title Spetses GIS API Server

:: Change to script directory
cd /d "%~dp0"

:: Python owns .env parsing and environment precedence, including special characters.
set "EPOL_PYTHON=python"
if exist ".venv\Scripts\python.exe" set "EPOL_PYTHON=%~dp0.venv\Scripts\python.exe"
"%EPOL_PYTHON%" -c "from settings import SETTINGS; SETTINGS.database.require_password()"
if errorlevel 1 (
    echo ERROR: Check Python and the project database settings.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Spetses GIS API Server
echo ============================================================
echo.

:: Start the server, or recognize the healthy API already on its configured port.
"%EPOL_PYTHON%" api_server.py
set "EPOL_SERVER_RESULT=%ERRORLEVEL%"

pause
exit /b %EPOL_SERVER_RESULT%
