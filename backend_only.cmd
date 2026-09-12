@echo off
setlocal EnableDelayedExpansion

rem Jump past subroutine definitions
goto :main

:check_python
    if exist "%PROJECT_ROOT%backend\venv\Scripts\python.exe" (
        set "PYTHON_EXE=%PROJECT_ROOT%backend\venv\Scripts\python.exe"
        echo [OK] Using project virtual environment.
    ) else (
        where python >nul 2>&1
        if !errorlevel! equ 0 (
            set "PYTHON_EXE=python"
            echo [WARN] venv not found. Using system Python.
        ) else (
            echo [ERROR] Python was not found.
            pause
            exit /b 1
        )
    )
    exit /b 0

:main

set "PROJECT_ROOT=%~dp0"
set "BACKEND_PORT=8000"

echo.
echo ============================================================
echo   AI Meeting Memory - Backend Only
echo ============================================================
echo.

call :check_python
if errorlevel 1 exit /b 1

netstat -ano 2>nul | findstr ":%BACKEND_PORT% " | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo [WARN] Port %BACKEND_PORT% is already in use.
    choice /C YN /M "Continue anyway?"
    if errorlevel 2 exit /b 1
)

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
        goto :done
    )
    if !ATTEMPTS! geq 20 goto :done
    goto :health_loop

:done
echo.
echo ============================================================
if "%BACKEND_READY%"=="1" (
    echo   Backend URL  : http://127.0.0.1:%BACKEND_PORT%
    echo   Login URL    : http://127.0.0.1:%BACKEND_PORT%/login
    echo   API Docs     : http://127.0.0.1:%BACKEND_PORT%/docs
    echo   Status       : RUNNING
    start "" "http://127.0.0.1:%BACKEND_PORT%/login"
) else (
    echo   Status       : FAILED - check the Backend window for errors
)
echo ============================================================
echo.
echo   Press any key to stop the backend...
pause >nul

taskkill /FI "WINDOWTITLE eq AI Meeting Memory - Backend" /T /F >nul 2>&1
echo Backend stopped.
pause

endlocal
