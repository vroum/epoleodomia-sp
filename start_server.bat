@echo off
title Spetses GIS API Server

:: Kill any existing process on port 8000
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
    echo Killing existing process on port 8000 (PID: %%a)
    taskkill /PID %%a /F >nul 2>&1
)

:: Change to script directory
cd /d "%~dp0"

:: Load credentials from .env (lines starting with ; are comments)
:: NOTE: do not enable delayed expansion - passwords may contain ! characters
if not exist ".env" (
    echo ERROR: .env file not found. Copy .env.example to .env and fill in credentials.
    pause
    exit /b 1
)
for /f "usebackq tokens=1,* delims==" %%a in (".env") do set "%%a=%%b"

if "%EPOL_DB_PASSWORD%"=="" (
    echo ERROR: EPOL_DB_PASSWORD is not set in .env
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Starting Spetses GIS API Server
echo ============================================================
echo.

:: Start the server
python api_server.py

pause
