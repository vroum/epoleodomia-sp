@echo off
title Pull gis backups off the NAS
REM ============================================================================
REM Copies the NAS backup folder to TWO destinations:
REM   1. C:\GIS_BACKUPS            (local disk on this PC)
REM   2. O:\backup_synology_gis    (second destination)
REM
REM Run manually or via Windows Task Scheduler (weekly is fine).
REM
REM NOTE: both destinations are local disks (C: and O:) - either one
REM       survives a dead NAS.
REM ============================================================================

set SRC=\\10.90.144.153\gis_backups\gis
set DEST1=C:\GIS_BACKUPS
set DEST2=O:\backup_synology_gis

set FAILED=

echo ------------------------------------------------------------
echo  [1/2] %SRC%  -^>  %DEST1%
echo ------------------------------------------------------------
robocopy "%SRC%" "%DEST1%" /MIR /R:2 /W:5 /NP
if %ERRORLEVEL% GEQ 8 set FAILED=%FAILED% DEST1

echo.
echo ------------------------------------------------------------
echo  [2/2] %SRC%  -^>  %DEST2%
echo ------------------------------------------------------------
robocopy "%SRC%" "%DEST2%" /MIR /R:2 /W:5 /NP
if %ERRORLEVEL% GEQ 8 set FAILED=%FAILED% DEST2

echo.
echo ============================================================
if "%FAILED%"=="" (
    echo  Backup pull OK. Latest dumps:
    dir /b /o-d "%DEST1%\*.dump" 2>nul
) else (
    echo  ERRORS copying to:%FAILED%
    echo  Check paths and that the Synology backup task has run at least once.
)
echo ============================================================
echo.
pause
