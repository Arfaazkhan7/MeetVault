@echo off
setlocal EnableDelayedExpansion

goto :main

:main

set "PROJECT_ROOT=%~dp0"

echo.
echo ============================================================
echo   AI Meeting Memory - Frontend Only
echo ============================================================
echo.

where flutter >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Flutter was not found on PATH.
    echo         Install Flutter: https://flutter.dev/docs/get-started/install
    pause
    exit /b 1
)
echo [OK] Flutter found.

if not exist "%PROJECT_ROOT%frontend\pubspec.yaml" (
    echo [ERROR] frontend\pubspec.yaml not found.
    pause
    exit /b 1
)

echo [....] Getting Flutter packages...
pushd "%PROJECT_ROOT%frontend" >nul
flutter pub get
popd >nul

echo [....] Checking Flutter devices...
set "HAVE_DEVICE=0"
pushd "%PROJECT_ROOT%frontend" >nul
for /f "delims=" %%A in ('flutter devices 2^>nul') do (
    echo %%A | findstr /v "^No devices" | findstr /v "^$" >nul 2>&1
    if not errorlevel 1 set "HAVE_DEVICE=1"
)
popd >nul

if "%HAVE_DEVICE%"=="0" (
    echo [WARN] No Flutter devices detected.
    echo        Run: flutter devices   to see available devices.
    pause
    exit /b 1
)

echo [....] Starting Flutter Frontend...
start "AI Meeting Memory - Frontend" cmd /k "cd /d "%PROJECT_ROOT%frontend" && flutter run"

echo.
echo ============================================================
echo   Frontend started - see "AI Meeting Memory - Frontend" window
echo ============================================================
echo.
echo   Press any key to stop the frontend...
pause >nul

taskkill /FI "WINDOWTITLE eq AI Meeting Memory - Frontend" /T /F >nul 2>&1
echo Frontend stopped.
pause

endlocal
