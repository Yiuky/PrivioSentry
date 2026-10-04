@echo off
setlocal
title PRIVIO SENTRY - Persistent mode (auto-restart)
cd /d "%~dp0.."

set "PROJECT_DIR=%CD%"
if exist "%PROJECT_DIR%\venv\Scripts\python.exe" (
    set "PYTHON_EXE=%PROJECT_DIR%\venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

echo ========================================================
echo   PRIVIO SENTRY - auto-recovery supervisor
echo ========================================================
echo This script keeps app_service.py running. If the process
echo dies, it is restarted automatically after 5 seconds.
echo Close other Python/Uvicorn windows first.
echo.

:loop
echo [%date% %time%] Starting app service...
echo [%date% %time%] start >> service_heartbeat.log
"%PYTHON_EXE%" "%PROJECT_DIR%\app_service.py"

echo.
echo [%date% %time%] WARNING: the service stopped unexpectedly. Restarting in 5 seconds...
echo [%date% %time%] crash detected, restarting >> service_heartbeat.log
timeout /t 5 /nobreak > nul
goto loop
