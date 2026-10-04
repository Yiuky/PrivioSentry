@echo off
title Configurar Modelo Multimodal Qwen 3.5
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_vision_model.ps1"
echo.
echo Pressione qualquer tecla para sair...
pause > nul
