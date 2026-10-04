@echo off
setlocal
title Gatekeeper Service Control
cd /d "%~dp0.."
echo Starting the Gatekeeper service...
echo.

if exist "venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call venv\Scripts\activate.bat
)

python gatekeeper.py

pause
