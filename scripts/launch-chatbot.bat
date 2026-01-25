@echo off
REM ============================================================
REM Resolve AI Chatbot Launcher
REM One-click launcher for the DaVinci Resolve AI Assistant
REM ============================================================

setlocal enabledelayedexpansion

echo ============================================================
echo  Resolve AI Chatbot Launcher
echo ============================================================
echo.

REM Get the script directory
set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."

REM Check for GEMINI_API_KEY
if "%GEMINI_API_KEY%"=="" (
    if "%GOOGLE_API_KEY%"=="" (
        echo [WARNING] GEMINI_API_KEY environment variable not set.
        echo The chatbot will work but AI features will be disabled.
        echo.
        echo To enable AI, set your API key:
        echo   set GEMINI_API_KEY=your_api_key_here
        echo.
    )
)

REM Set up DaVinci Resolve scripting paths
set "RESOLVE_SCRIPT_API=C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting"
set "RESOLVE_SCRIPT_LIB=C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll"
set "PYTHONPATH=%RESOLVE_SCRIPT_API%\Modules;%PROJECT_ROOT%\src;%PYTHONPATH%"

REM Check for virtual environment
set "VENV_PYTHON=%PROJECT_ROOT%\venv\Scripts\python.exe"
set "PYTHON_CMD="

if exist "%VENV_PYTHON%" (
    echo [OK] Using virtual environment Python
    set "PYTHON_CMD=%VENV_PYTHON%"
) else (
    echo [INFO] Virtual environment not found, using system Python
    where python >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_CMD=python"
    ) else (
        echo [ERROR] Python not found. Please install Python 3.8+
        pause
        exit /b 1
    )
)

REM Verify Python has required packages
echo.
echo Checking dependencies...
%PYTHON_CMD% -c "import tkinter" 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] tkinter not available. Please install Python with tkinter support.
    pause
    exit /b 1
)

REM Check if DaVinci Resolve is running
echo Checking for DaVinci Resolve...
tasklist /FI "IMAGENAME eq Resolve.exe" 2>NUL | find /I "Resolve.exe" >NUL
if %errorlevel% neq 0 (
    echo [WARNING] DaVinci Resolve does not appear to be running.
    echo The chatbot will start but won't be able to control Resolve until it's open.
    echo.
)

REM Launch the chatbot
echo.
echo ============================================================
echo  Starting Resolve AI Chatbot...
echo ============================================================
echo.

cd /d "%PROJECT_ROOT%"
%PYTHON_CMD% -m autonomous.chatbot.chat_window

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Chatbot exited with an error.
    pause
)
