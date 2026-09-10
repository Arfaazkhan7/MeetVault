@echo off
setlocal

set "PROJECT_ROOT=%~dp0"

echo.
echo ============================================================
echo   AI Meeting Memory - Restarting Project
echo ============================================================
echo.

echo Step 1: Stopping existing processes...
call "%PROJECT_ROOT%stop_project.cmd"

echo Step 2: Waiting 2 seconds...
timeout /t 2 >nul

echo Step 3: Starting project...
call "%PROJECT_ROOT%run_project.cmd"

endlocal
