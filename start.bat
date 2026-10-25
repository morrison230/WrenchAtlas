@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title WrenchAtlas
cd /d "%~dp0"

rem Force UTF-8 so Chinese paths and JSON output don't break on GBK consoles
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

rem ============================================================
rem  Pick a Python that ACTUALLY has the dependencies.
rem
rem  Machine may have several Pythons (system, store, IDE-bundled).
rem  The one on PATH is not necessarily the one where you ran
rem  pip install. So we probe each candidate instead of trusting PATH.
rem
rem  Order:
rem    1. .python-path        (local, gitignored - per-machine override)
rem    2. WRENCHATLAS_PYTHON  (env var)
rem    3. .\venv              (project virtualenv, the normal case)
rem    4. ..\.venv
rem    5. python on PATH
rem    6. py launcher
rem ============================================================
set "PYEXE="
set "NODEPS="
set "NOPY="

if exist ".python-path" (
    set /p CAND=<.python-path
    if defined CAND call :probe "!CAND!" && goto :found
)
if defined WRENCHATLAS_PYTHON (
    call :probe "%WRENCHATLAS_PYTHON%" && goto :found
)
if exist "venv\Scripts\python.exe" (
    call :probe "%CD%\venv\Scripts\python.exe" && goto :found
)
if exist ".venv\Scripts\python.exe" (
    call :probe "%CD%\.venv\Scripts\python.exe" && goto :found
)
call :probe "python" && goto :found
call :probe "py" && goto :found

goto :failed

:probe
rem %~1 = candidate command or path. Sets PYEXE on success.
if "%~1"=="" exit /b 1
"%~1" -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul
if errorlevel 1 exit /b 1
"%~1" -c "import fastapi, uvicorn, pymupdf, PIL, numpy, cv2" >nul 2>nul
if errorlevel 1 (
    if not defined NODEPS set "NODEPS=%~1"
    exit /b 1
)
set "PYEXE=%~1"
exit /b 0

:found
echo.
echo   Python: %PYEXE%

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
    echo   Build one from your own service manual:
    echo.
    echo       %PYEXE% builder\new_pack.py --id brand-model-year --make Brand --model Model --year 2020
    echo       %PYEXE% builder\enhance.py --src ^<manual folder^> --out packs\brand-model-year\pages
    echo       %PYEXE% builder\index.py --pack packs\brand-model-year --doc-id brand-model-year
    echo.
    echo   See docs\QUICKSTART.md for details.
    echo.
)

echo.
echo   WrenchAtlas - starting...
echo.

%PYEXE% "web\server.py" --port 3000 --host 0.0.0.0

echo.
echo   Server stopped. Press any key to close.
pause >nul
exit /b 0

:failed
echo.
if defined NODEPS (
    echo   [SETUP] Python found, but dependencies are missing:
    echo           %NODEPS%
    echo.
    echo   Run this once:
    echo.
    echo       %NODEPS% -m pip install -r requirements.txt
    echo.
    echo   If that Python is not the one you want to use, install the
    echo   dependencies into your own environment and either activate it
    echo   or point WRENCHATLAS_PYTHON at it.
) else (
    echo   [ERROR] No Python 3.10+ found.
    echo.
    echo   Install from https://www.python.org/downloads/
    echo   and tick "Add python.exe to PATH" during setup.
)
echo.
pause
exit /b 1
