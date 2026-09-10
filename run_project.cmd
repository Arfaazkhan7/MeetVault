@echo off
setlocal EnableDelayedExpansion

rem ============================================================
rem  AI Meeting Memory - Portable Project Launcher
rem  Double-click this file from Explorer to start the project.
rem  Starts backend + frontend, then opens the browser.
rem ============================================================

goto :main

rem ============================================================
rem  SUBROUTINE: find_python
rem  Sets PYTHON_EXE to a WORKING python interpreter.
rem ============================================================
:find_python
    set "PYTHON_EXE="
    where python >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_EXE=python"
    ) else (
        where py >nul 2>&1
        if !errorlevel! equ 0 (
            set "PYTHON_EXE=py"
        )
    )
    if not defined PYTHON_EXE (
        echo [ERROR] No working Python found. Install Python 3.10+ and add it to PATH.
        pause
        exit /b 1
    )
    exit /b 0

rem ============================================================
rem  SUBROUTINE: setup_venv
rem  Creates venv if missing and installs requirements
rem ============================================================
:setup_venv
    set "VENV_PYTHON=%PROJECT_ROOT%backend\venv\Scripts\python.exe"
    
    rem Check if venv is valid
    if exist "%VENV_PYTHON%" (
        "%VENV_PYTHON%" -c "import sys" >nul 2>&1
        if !errorlevel! equ 0 (
            echo [OK] Valid virtual environment found.
            set "PYTHON_EXE=%VENV_PYTHON%"
            exit /b 0
        )
    )
    
    echo [....] Virtual environment missing or invalid. Recreating...
    if exist "%PROJECT_ROOT%backend\venv" rmdir /s /q "%PROJECT_ROOT%backend\venv"
    
    "%PYTHON_EXE%" -m venv "%PROJECT_ROOT%backend\venv"
    if not exist "%VENV_PYTHON%" (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    
    set "PYTHON_EXE=%VENV_PYTHON%"
    echo [....] Installing backend dependencies...
    "%PYTHON_EXE%" -m pip install --upgrade pip
    "%PYTHON_EXE%" -m pip install -r "%PROJECT_ROOT%backend\requirements.txt"
    echo [OK] Dependencies installed.
    exit /b 0

rem ============================================================
rem  SUBROUTINE: find_flutter
rem  Sets HAVE_FLUTTER=1 or 0
rem ============================================================
:find_flutter
    set "HAVE_FLUTTER=0"
    where flutter >nul 2>&1
    if !errorlevel! equ 0 (
        set "HAVE_FLUTTER=1"
        echo [OK] Flutter found on PATH.
        exit /b 0
    )
    rem Check common local install paths (add your path here if different)
    for %%F in (
        "%USERPROFILE%\Downloads\projects\flutter\bin\flutter.bat"
        "%USERPROFILE%\flutter\bin\flutter.bat"
        "C:\flutter\bin\flutter.bat"
        "C:\src\flutter\bin\flutter.bat"
        "D:\flutter\bin\flutter.bat"
    ) do (
        if exist %%F (
            set "HAVE_FLUTTER=1"
            for %%D in (%%~dpF.) do set "PATH=%%~fD;!PATH!"
            echo [OK] Flutter found at %%~fF.
            exit /b 0
        )
    )
    echo [WARN] Flutter SDK not found. Using prebuilt web frontend if available.
    exit /b 0

rem ============================================================
rem  SUBROUTINE: ensure_backend_env
rem  Creates backend\.env from .env.example if missing.
rem ============================================================
:ensure_backend_env
    if exist "%PROJECT_ROOT%backend\.env" (
        echo [OK] backend\.env already exists.
        exit /b 0
    )
    if exist "%PROJECT_ROOT%.env.example" (
        copy /Y "%PROJECT_ROOT%.env.example" "%PROJECT_ROOT%backend\.env" >nul 2>&1
        echo [OK] Created backend\.env from .env.example.
    ) else (
        echo [WARN] No .env file found. Backend will use default config values.
    )
    exit /b 0

rem ============================================================
rem  MAIN ENTRY POINT
rem ============================================================
:main

set "PROJECT_ROOT=%~dp0"
set "BACKEND_PORT=8000"
set "FRONTEND_PORT=3000"

echo.
echo ============================================================
echo   AI Meeting Memory - Starting Complete Project
echo ============================================================
echo.

call :find_python
if errorlevel 1 exit /b 1

call :setup_venv
if errorlevel 1 exit /b 1

call :ensure_backend_env

call :find_flutter

netstat -ano 2>nul | findstr ":%BACKEND_PORT% " | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo.
    echo [WARN] Port %BACKEND_PORT% is already in use.
    choice /C YN /M "Continue anyway?"
    if errorlevel 2 (
        echo Cancelled.
        pause
        exit /b 1
    )
)

netstat -ano 2>nul | findstr ":%FRONTEND_PORT% " | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo.
    echo [WARN] Port %FRONTEND_PORT% is already in use.
    choice /C YN /M "Continue anyway?"
    if errorlevel 2 (
        echo Cancelled.
        pause
        exit /b 1
    )
)

echo.
echo [....] Starting Backend on http://127.0.0.1:%BACKEND_PORT% ...
start "AI Meeting Memory - Backend" cmd /k "cd /d "%PROJECT_ROOT%backend" && "%PROJECT_ROOT%backend\venv\Scripts\uvicorn.exe" app.main:app --host 127.0.0.1 --port %BACKEND_PORT% --reload"

set "HEALTH_URL=http://127.0.0.1:%BACKEND_PORT%/api/v1/health"
set /a ATTEMPTS=0
set "BACKEND_READY=0"

:health_loop
    set /a ATTEMPTS+=1
    echo Attempt %ATTEMPTS%/20 - waiting for backend...
    timeout /t 3 >nul
    powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri '%HEALTH_URL%' -UseBasicParsing -TimeoutSec 4; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
    if !errorlevel! equ 0 (
        set "BACKEND_READY=1"
        echo.
        echo [OK] Backend is ready.
        goto :frontend
    )
    if !ATTEMPTS! geq 20 (
        echo.
        echo [ERROR] Backend did not respond after 20 attempts.
        goto :show_summary
    )
    goto :health_loop

:frontend
if "%BACKEND_READY%"=="0" goto :show_summary

set "WEBROOT="

if exist "%PROJECT_ROOT%frontend\build\web\index.html" (
    set "WEBROOT=%PROJECT_ROOT%frontend\build\web"
    echo [OK] Using prebuilt Flutter web frontend.
)

if "%HAVE_FLUTTER%"=="1" if not defined WEBROOT (
    echo.
    echo [....] Building Flutter web (this may take a while)...
    pushd "%PROJECT_ROOT%frontend" >nul
    call flutter build web
    popd >nul
    if exist "%PROJECT_ROOT%frontend\build\web\index.html" (
        set "WEBROOT=%PROJECT_ROOT%frontend\build\web"
        echo [OK] Flutter web build complete.
    )
)

if not defined WEBROOT if exist "%PROJECT_ROOT%web\index.html" (
    set "WEBROOT=%PROJECT_ROOT%web"
    echo [OK] Using static dashboard frontend.
)

if not defined WEBROOT goto :show_summary

echo.
echo [....] Starting Frontend on http://127.0.0.1:%FRONTEND_PORT% ...
start "AI Meeting Memory - Frontend" cmd /k "cd /d "%WEBROOT%" && "%PYTHON_EXE%" -m http.server %FRONTEND_PORT%"

echo [....] Opening browser...
start "" "http://127.0.0.1:%FRONTEND_PORT%"
echo [OK] Frontend opened in your browser.

:show_summary
echo.
echo ============================================================
echo   AI MEETING MEMORY - STATUS
echo ============================================================
echo.
echo   Backend URL   : http://127.0.0.1:%BACKEND_PORT%
echo   API Health    : http://127.0.0.1:%BACKEND_PORT%/api/v1/health
echo   Frontend URL  : http://127.0.0.1:%FRONTEND_PORT%
echo.
if "%BACKEND_READY%"=="1" (
    echo   Backend      : RUNNING
) else (
    echo   Backend      : FAILED
)
if defined WEBROOT (
    echo   Frontend     : RUNNING
) else (
    echo   Frontend     : SKIPPED
)
echo.
echo ============================================================
echo.
echo   Press any key to STOP the project ...
echo.
pause >nul

call "%PROJECT_ROOT%stop_project.cmd"
endlocal
