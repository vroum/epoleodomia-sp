@echo off
title EMSY Ydrolipsies Sync

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
echo   EMSY Ydrolipsies Sync (lmt.ypeka.gr - Spetses bbox)
echo ============================================================
echo.

:: Pass through any arguments (e.g. --dry-run)
python sync_ydrolipsies.py %*

echo.
pause
