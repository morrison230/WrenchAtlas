@echo off
chcp 65001 >nul
setlocal
title WrenchAtlas
cd /d "%~dp0"

rem Force UTF-8 so Chinese paths and JSON output don't break on GBK consoles
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

rem ---- locate Python: PATH first, then the py launcher ----
set "PYEXE="
where python >nul 2>nul && set "PYEXE=python"
if not defined PYEXE (
    where py >nul 2>nul && set "PYEXE=py"
)

if not defined PYEXE (
    echo.
    echo   [ERROR] Python not found.
    echo   Install Python 3.10+ from https://www.python.org/downloads/
    echo   and tick "Add python.exe to PATH" during setup.
    echo.
    pause
    exit /b 1
)

rem ---- python version must be 3.10+ ----
%PYEXE% -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if errorlevel 1 (
    echo.
    echo   [ERROR] Python 3.10 or newer is required.
    echo   Current:
    %PYEXE% --version
    echo.
    pause
    exit /b 1
)

rem ---- dependencies ----
if exist "requirements.txt" (
    %PYEXE% -c "import fastapi, uvicorn, pymupdf, PIL, numpy, cv2" >nul 2>nul
    if errorlevel 1 (
        echo.
        echo   [SETUP] Dependencies are missing. Run this once:
        echo.
        echo       %PYEXE% -m pip install -r requirements.txt
        echo.
        pause
        exit /b 1
    )
)

if not exist "web\server.py" (
    echo.
    echo   [ERROR] web\server.py not found.
    echo   Run this file from the project root directory.
    echo.
    pause
    exit /b 1
)

rem ---- first run without data? explain instead of failing silently ----
if not exist "packs\suzuki-sx4-2010\data\pages.json" (
    echo.
    echo   [NOTE] No page index found. The web UI will show an empty library.
    echo   To build one from your own service manual:
    echo.
    echo       %PYEXE% builder\new_pack.py --id brand-model-year --make Brand --model Model --year 2020
    echo       %PYEXE% builder\enhance.py --src ^<manual folder^> --out packs\brand-model-year\pages
    echo       %PYEXE% builder\index.py --pack packs\brand-model-year --doc-id brand-model-year
    echo.
    echo   See docs/QUICKSTART.md for details.
    echo.
)

echo.
echo   WrenchAtlas - starting...
echo.

%PYEXE% "web\server.py" --port 3000 --host 0.0.0.0

echo.
echo   Server stopped. Press any key to close.
pause >nul
