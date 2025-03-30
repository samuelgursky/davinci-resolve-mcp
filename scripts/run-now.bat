@echo off
REM Quick Start Script for DaVinci Resolve MCP Server (Windows Version)
REM This script sets up the environment and starts the MCP server

echo ==============================================
echo   DaVinci Resolve MCP Server - Quick Start   
echo ==============================================
echo.

REM Get the script directory and root directory
set SCRIPT_DIR=%~dp0
set ROOT_DIR=%SCRIPT_DIR%\..\
set VENV_DIR=%ROOT_DIR%venv
set RESOLVE_MCP_SERVER=%ROOT_DIR%src\resolve_mcp_server.py

REM Check if Python is installed
where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo Python is not installed or not in your PATH
    echo Please install Python 3.6+ from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation
    pause
    exit /b 1
)

REM Check if Node.js/npm is installed (warning only)
where npm >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo WARNING: Node.js/npm is not installed or not in your PATH.
    echo This might cause some features to not work properly.
    echo You can install Node.js from https://nodejs.org/
    echo Make sure to check the option to add to PATH during installation.
    pause
)

REM Check if DaVinci Resolve is running - fixed process detection
echo Checking if DaVinci Resolve is running...

REM Simple check for Resolve process - avoid complex piping that causes syntax errors
tasklist /FI "IMAGENAME eq Resolve.exe" 2>nul | find /i "Resolve.exe" >nul
if not errorlevel 1 (
    echo DaVinci Resolve is running, continuing...
    goto :resolve_running
)

echo DaVinci Resolve is not running
echo Please start DaVinci Resolve before running this script

set /p START_RESOLVE="Would you like to try starting DaVinci Resolve now? (y/n): "
if /i not "%START_RESOLVE%"=="y" (
    echo DaVinci Resolve must be running for the MCP server to function properly
    pause
    exit /b 1
)

REM Try to start DaVinci Resolve
echo Attempting to start DaVinci Resolve...
    
if exist "C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe" (
    echo Starting DaVinci Resolve from the correct path...
    start "" "C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe"
    echo Waiting for DaVinci Resolve to start...
    timeout /t 15 /nobreak >nul
    echo DaVinci Resolve should be running now.
) else (
    echo Could not find DaVinci Resolve executable at:
    echo C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe
    echo Please start DaVinci Resolve manually
    pause
    exit /b 1
)

:resolve_running
REM Create virtual environment if it doesn't exist
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo Creating Python virtual environment...
    python -m venv "%VENV_DIR%"
    
    if %ERRORLEVEL% NEQ 0 (
        echo Failed to create virtual environment
        pause
        exit /b 1
    )
)

REM Install MCP SDK with CLI support
echo Installing MCP SDK with CLI support in virtual environment...
call "%VENV_DIR%\Scripts\pip" install "mcp[cli]"

REM Set environment variables
echo Setting environment variables...
set RESOLVE_SCRIPT_API=C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting
set RESOLVE_SCRIPT_LIB=C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll
set PYTHONPATH=%ROOT_DIR%;%PYTHONPATH%;%RESOLVE_SCRIPT_API%\Modules

REM Save environment variables for user
setx RESOLVE_SCRIPT_API "%RESOLVE_SCRIPT_API%" >nul
setx RESOLVE_SCRIPT_LIB "%RESOLVE_SCRIPT_LIB%" >nul
setx PYTHONPATH "%ROOT_DIR%;%RESOLVE_SCRIPT_API%\Modules" >nul

REM Start the server
echo Starting DaVinci Resolve MCP Server...
echo.

cd "%ROOT_DIR%"
"%VENV_DIR%\Scripts\python" "%RESOLVE_MCP_SERVER%"
