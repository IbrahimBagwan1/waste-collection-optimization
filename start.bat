@echo off
REM ======================================================================
REM  WASTEX launcher (Windows)
REM    1. finds Python 3.10+
REM    2. creates .venv and installs requirements (first run only)
REM    3. starts Apache Kafka in Docker when available, else the embedded broker
REM    4. opens the dashboard at http://127.0.0.1:8000
REM  Add  --embedded  to skip Docker:   start.bat --embedded
REM ======================================================================
setlocal
cd /d "%~dp0"
title WASTEX

set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1 && set "PY=py -3"
if not defined PY (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo.
    echo  Python 3.10 or newer was not found.
    echo  Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo  Creating virtual environment .venv ...
    %PY% -m venv .venv || (echo Could not create the virtual environment. & pause & exit /b 1)
)
set "VPY=.venv\Scripts\python.exe"

if not exist ".venv\.installed" (
    echo  Installing dependencies - first run only, this can take several minutes ...
    "%VPY%" -m pip install --disable-pip-version-check -q --upgrade pip
    "%VPY%" -m pip install --disable-pip-version-check -q -r requirements.txt || (echo Dependency installation failed - check your internet connection. & pause & exit /b 1)
    echo ok> ".venv\.installed"
)

if /i "%~1"=="--embedded" (
    "%VPY%" run.py --embedded
) else (
    "%VPY%" run.py --docker
)
if errorlevel 1 pause
endlocal
