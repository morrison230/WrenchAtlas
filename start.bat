@echo off
chcp 65001 >nul
setlocal
title WrenchAtlas
cd /d "%~dp0"

set "PYTHONIOENCODING=utf-8"
set "PYEXE=C:\Users\Morrison\.workbuddy\binaries\python\envs\default\Scripts\python.exe"

if not exist "%PYEXE%" (
    where python >nul 2>nul
    if errorlevel 1 (
        echo.
        echo   [ERROR] Python not found.
        echo   Please install Python 3.10+ and make sure "python" is in PATH.
        echo.
        pause
        exit /b 1
    )
    set "PYEXE=python"
)

if not exist "web\server.py" (
    echo.
    echo   [ERROR] web\server.py not found.
    echo   Please run this file from the project root directory.
    echo.
    pause
    exit /b 1
)

echo.
echo   WrenchAtlas - starting...
echo.

"%PYEXE%" "web\server.py" --port 3000 --host 0.0.0.0

echo.
echo   Server stopped. Press any key to close.
pause >nul
