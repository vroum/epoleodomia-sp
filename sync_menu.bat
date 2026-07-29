@echo off
title Spetses GIS - Sync Menu
REM ============================================================================
REM Master sync menu - Spetses GIS (v1.0)
REM ============================================================================
REM Interactive:   sync_menu.bat
REM Direct:        sync_menu.bat tee | ktima | ydro | rasters | all | all-rasters
REM ============================================================================

cd /d "%~dp0"

REM -- Python check ------------------------------------------------------------
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    pause
    exit /b 1
)

REM -- Load credentials from .env ----------------------------------------------
REM NOTE: do not enable delayed expansion - passwords may contain ! characters
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

REM -- Direct mode from command line -------------------------------------------
set MODE=%1
if not "%MODE%"=="" goto :dispatch

REM -- Interactive menu ---------------------------------------------------------
:menu
echo.
echo ============================================================
echo   Spetses GIS - Sync Menu
echo ============================================================
echo.
echo   1. TEE epoleodomia tables      (sync_all.py --track)
echo   2. Ktimatologio operating      (sync_kaek_operating.py)
echo   3. Ydrolipsies EMSY            (sync_ydrolipsies.py)
echo   4. Rasters FEK/DJI/DE          (download_rasters.py)
echo   5. ALL (1+2+3)
echo   6. ALL + rasters (1+2+3+4)
echo   0. Exit
echo.
set /p CHOICE=Select [0-6]:

if "%CHOICE%"=="1" set MODE=tee& goto :dispatch
if "%CHOICE%"=="2" set MODE=ktima& goto :dispatch
if "%CHOICE%"=="3" set MODE=ydro& goto :dispatch
if "%CHOICE%"=="4" set MODE=rasters& goto :dispatch
if "%CHOICE%"=="5" set MODE=all& goto :dispatch
if "%CHOICE%"=="6" set MODE=all-rasters& goto :dispatch
if "%CHOICE%"=="0" goto :end
echo Invalid choice.
goto :menu

REM -- Dispatch ------------------------------------------------------------------
:dispatch
set FAILED=

if /i "%MODE%"=="tee"         call :run_tee & goto :done
if /i "%MODE%"=="ktima"       call :run_ktima & goto :done
if /i "%MODE%"=="ydro"        call :run_ydro & goto :done
if /i "%MODE%"=="rasters"     call :run_rasters & goto :done
if /i "%MODE%"=="all"         call :run_tee & call :run_ktima & call :run_ydro & goto :done
if /i "%MODE%"=="all-rasters" call :run_tee & call :run_ktima & call :run_ydro & call :run_rasters & goto :done

echo Unknown mode: %MODE%
echo Valid: tee ^| ktima ^| ydro ^| rasters ^| all ^| all-rasters
goto :end

REM -- Steps ---------------------------------------------------------------------
:run_tee
echo.
echo ------------------------------------------------------------
echo  [1/..] TEE epoleodomia sync (with change tracking)
echo ------------------------------------------------------------
python sync_all.py --track
if errorlevel 1 set FAILED=%FAILED% TEE
exit /b 0

:run_ktima
echo.
echo ------------------------------------------------------------
echo  Ktimatologio operating sync (AGOL)
echo ------------------------------------------------------------
python sync_kaek_operating.py
if errorlevel 1 set FAILED=%FAILED% KTIMA
exit /b 0

:run_ydro
echo.
echo ------------------------------------------------------------
echo  Ydrolipsies EMSY sync (lmt.ypeka.gr)
echo ------------------------------------------------------------
python sync_ydrolipsies.py
if errorlevel 1 set FAILED=%FAILED% YDRO
exit /b 0

:run_rasters
echo.
echo ------------------------------------------------------------
echo  Raster downloads (FEK / DJI / DE)
echo ------------------------------------------------------------
python download_rasters.py
if errorlevel 1 set FAILED=%FAILED% RASTERS
exit /b 0

REM -- Summary -------------------------------------------------------------------
:done
echo.
echo ============================================================
if "%FAILED%"=="" (
    echo  Sync completed OK. See logs\CHANGES_latest.md for changes.
) else (
    echo  Sync finished with ERRORS in:%FAILED%
    echo  Check output above and logs folder.
)
echo ============================================================

:end
echo.
pause
