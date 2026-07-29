@echo off
REM ============================================================================
REM TEE Urban Planning Data Sync - Spetses Island  (v1.1)
REM ============================================================================
REM Quick sync script for updating the local PostGIS database from TEE ArcGIS
REM
REM Usage:
REM   sync.bat              - Full sync with change tracking (recommended)
REM   sync.bat full         - Full sync with change tracking
REM   sync.bat quick        - Sync building_blocks only (fast test)
REM   sync.bat replace      - Full replace (no tracking, truncates tables)
REM   sync.bat dry          - Dry run (check counts without loading)
REM   sync.bat rasters      - Download raster planning diagrams only
REM   sync.bat full-rasters - Full sync + download rasters
REM ============================================================================

cd /d "%~dp0"

echo ============================================================
echo TEE Urban Planning Data Sync - Spetses Island
echo ============================================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.8+ and try again
    pause
    exit /b 1
)

REM Check .env file exists
if not exist ".env" (
    echo WARNING: .env file not found!
    echo Copy .env.example to .env and set your DB_PASSWORD.
    echo.
)

REM Parse command line argument
set MODE=%1
if "%MODE%"=="" set MODE=full

if /i "%MODE%"=="full" (
    echo Mode: Full sync with change tracking
    echo.
    python sync_all.py --track
    goto :done
)

if /i "%MODE%"=="quick" (
    echo Mode: Quick sync - building_blocks only
    echo.
    python sync_all.py --track --table building_blocks
    goto :done
)

if /i "%MODE%"=="replace" (
    echo Mode: Full replace - no change tracking
    echo WARNING: This will truncate all tables!
    echo.
    set /p CONFIRM=Are you sure? (Y/N):
    if /i "%CONFIRM%"=="Y" (
        python sync_all.py
    ) else (
        echo Cancelled.
    )
    goto :done
)

if /i "%MODE%"=="dry" (
    echo Mode: Dry run - checking counts only
    echo.
    python sync_all.py --dry-run
    goto :done
)

if /i "%MODE%"=="rasters" (
    echo Mode: Rasters only - downloading planning diagrams
    echo.
    python download_rasters.py
    goto :done
)

if /i "%MODE%"=="full-rasters" (
    echo Mode: Full sync with change tracking + rasters
    echo.
    python sync_all.py --track --rasters
    goto :done
)

if /i "%MODE%"=="help" (
    goto :help
)

echo Unknown mode: %MODE%
goto :help

:help
echo.
echo Usage: sync.bat [mode]
echo.
echo Modes:
echo   full         - Full sync with change tracking (default)
echo   quick        - Sync building_blocks only (fast test)
echo   replace      - Full replace without tracking (truncates tables)
echo   dry          - Dry run (check counts without loading data)
echo   rasters      - Download raster planning diagrams only
echo   full-rasters - Full sync + download rasters
echo   help         - Show this help message
echo.
goto :end

:done
echo.
echo ============================================================
echo Sync completed! Check the logs folder for details.
echo ============================================================

:end
echo.
pause
