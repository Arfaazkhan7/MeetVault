@echo off
setlocal

echo.
echo ============================================================
echo   AI Meeting Memory - Stopping Project
echo ============================================================
echo.

echo Stopping Backend...
taskkill /FI "WINDOWTITLE eq AI Meeting Memory - Backend" /T /F >nul 2>&1
if errorlevel 1 (
    echo   Backend window not found or already stopped.
) else (
    echo   Backend stopped.
)

echo Stopping Frontend...
taskkill /FI "WINDOWTITLE eq AI Meeting Memory - Frontend" /T /F >nul 2>&1
if errorlevel 1 (
    echo   Frontend window not found or already stopped.
) else (
    echo   Frontend stopped.
)

echo.
echo ============================================================
echo   Project stopped.
echo ============================================================
echo.
pause

endlocal
