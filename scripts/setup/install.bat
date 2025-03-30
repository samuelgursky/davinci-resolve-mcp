@echo off
REM install.bat - One-step installation for DaVinci Resolve MCP Integration
REM This script handles the entire installation process with improved error detection

setlocal EnableDelayedExpansion

REM Colors for terminal output
for /F "tokens=1,2 delims=#" %%a in ('"prompt #$H#$E# & echo on & for %%b in (1) do rem"') do (
  set "ESC=%%b"
)

set "GREEN=%ESC%[92m"
set "YELLOW=%ESC%[93m"
set "BLUE=%ESC%[94m"
set "RED=%ESC%[91m"
set "BOLD=%ESC%[1m"
set "NC=%ESC%[0m"

REM Get the absolute path of project root directory
pushd "%~dp0..\..\"
set "INSTALL_DIR=%CD%"
popd
set "VENV_DIR=%INSTALL_DIR%\venv"
set "CURSOR_CONFIG_DIR=%APPDATA%\Cursor\mcp"
set "CURSOR_CONFIG_FILE=%CURSOR_CONFIG_DIR%\config.json"
set "PROJECT_CURSOR_DIR=%INSTALL_DIR%\.cursor"
set "PROJECT_CONFIG_FILE=%PROJECT_CURSOR_DIR%\mcp.json"
set "LOG_FILE=%INSTALL_DIR%\install.log"

REM Banner
echo %BLUE%%BOLD%=================================================%NC%
echo %BLUE%%BOLD%  DaVinci Resolve MCP Integration Installer      %NC%
echo %BLUE%%BOLD%=================================================%NC%
echo %YELLOW%Installation directory: %INSTALL_DIR%%NC%
echo Installation log: %LOG_FILE%
echo.

REM Initialize log
echo === DaVinci Resolve MCP Installation Log === > "%LOG_FILE%"
echo Date: %date% %time% >> "%LOG_FILE%"
echo Install directory: %INSTALL_DIR% >> "%LOG_FILE%"
echo User: %USERNAME% >> "%LOG_FILE%"
echo System: %OS% Windows %PROCESSOR_ARCHITECTURE% >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"

REM Log message helper
set "LOG_PREFIX=[%time%]"

REM Check if DaVinci Resolve is running
echo %LOG_PREFIX% Checking if DaVinci Resolve is running >> "%LOG_FILE%"
echo %YELLOW%Checking if DaVinci Resolve is running... %NC%

tasklist /FI "IMAGENAME eq Resolve.exe" 2>NUL | find /I /N "Resolve.exe">NUL
if %ERRORLEVEL% == 0 (
    echo %GREEN%OK%NC%
    echo %LOG_PREFIX% DaVinci Resolve is running >> "%LOG_FILE%"
    set RESOLVE_RUNNING=1
) else (
    echo %RED%NOT RUNNING%NC%
    echo %YELLOW%DaVinci Resolve must be running to complete the installation.%NC%
    echo %YELLOW%Please start DaVinci Resolve and try again.%NC%
    echo %LOG_PREFIX% DaVinci Resolve is not running - installation cannot proceed >> "%LOG_FILE%"
    set RESOLVE_RUNNING=0
    echo %RED%Installation aborted.%NC%
    exit /b 1
)

REM Create Python virtual environment
echo %LOG_PREFIX% Creating/checking Python virtual environment >> "%LOG_FILE%"
echo %YELLOW%Setting up Python virtual environment... %NC%

if exist "%VENV_DIR%\Scripts\python.exe" (
    echo %GREEN%ALREADY EXISTS%NC%
    echo %LOG_PREFIX% Virtual environment already exists >> "%LOG_FILE%"
    set VENV_STATUS=1
) else (
    echo %YELLOW%CREATING%NC%
    python -m venv "%VENV_DIR%" >> "%LOG_FILE%" 2>&1
    
    if %ERRORLEVEL% == 0 (
        echo %GREEN%OK%NC%
        echo %LOG_PREFIX% Virtual environment created successfully >> "%LOG_FILE%"
        set VENV_STATUS=1
    ) else (
        echo %RED%FAILED%NC%
        echo %RED%Failed to create Python virtual environment.%NC%
        echo %YELLOW%Check that Python 3.9+ is installed.%NC%
        echo %LOG_PREFIX% Failed to create virtual environment >> "%LOG_FILE%"
        set VENV_STATUS=0
        echo %RED%Installation aborted.%NC%
        exit /b 1
    )
)

REM Install MCP SDK
echo %LOG_PREFIX% Installing MCP SDK >> "%LOG_FILE%"
echo %YELLOW%Installing MCP SDK... %NC%

"%VENV_DIR%\Scripts\pip" install "mcp[cli]" >> "%LOG_FILE%" 2>&1

if %ERRORLEVEL% == 0 (
    echo %GREEN%OK%NC%
    echo %LOG_PREFIX% MCP SDK installed successfully >> "%LOG_FILE%"
    set MCP_STATUS=1
) else (
    echo %RED%FAILED%NC%
    echo %RED%Failed to install MCP SDK.%NC%
    echo %YELLOW%Check the log file for details: %LOG_FILE%%NC%
    echo %LOG_PREFIX% Failed to install MCP SDK >> "%LOG_FILE%"
    set MCP_STATUS=0
    echo %RED%Installation aborted.%NC%
    exit /b 1
)

REM Set environment variables
echo %LOG_PREFIX% Setting up environment variables >> "%LOG_FILE%"
echo %YELLOW%Setting up environment variables... %NC%

REM Generate environment variables file
set "ENV_FILE=%INSTALL_DIR%\.env.bat"
(
    echo @echo off
    echo set "RESOLVE_SCRIPT_API=C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting"
    echo set "RESOLVE_SCRIPT_LIB=C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll"
    echo set "PYTHONPATH=%%PYTHONPATH%%;%%RESOLVE_SCRIPT_API%%\Modules;%INSTALL_DIR%"
) > "%ENV_FILE%"

REM Source the environment variables
call "%ENV_FILE%"

echo %GREEN%OK%NC%
echo %LOG_PREFIX% Environment variables set >> "%LOG_FILE%"
echo %LOG_PREFIX% RESOLVE_SCRIPT_API=%RESOLVE_SCRIPT_API% >> "%LOG_FILE%"
echo %LOG_PREFIX% RESOLVE_SCRIPT_LIB=%RESOLVE_SCRIPT_LIB% >> "%LOG_FILE%"

REM Suggest adding to system variables
echo %YELLOW%Consider adding these environment variables to your system:%NC%
echo %BLUE%  RESOLVE_SCRIPT_API = C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting%NC%
echo %BLUE%  RESOLVE_SCRIPT_LIB = C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll%NC%
echo %BLUE%  Add to PYTHONPATH: %%RESOLVE_SCRIPT_API%%\Modules%NC%

REM Setup Cursor MCP configuration
echo %LOG_PREFIX% Setting up Cursor MCP configuration >> "%LOG_FILE%"
echo %YELLOW%Setting up Cursor MCP configuration... %NC%

REM Create system-level directory if it doesn't exist
if not exist "%CURSOR_CONFIG_DIR%" mkdir "%CURSOR_CONFIG_DIR%"

REM Create system-level config file with the absolute paths
(
    echo {
    echo   "mcpServers": {
    echo     "davinci-resolve": {
    echo       "name": "DaVinci Resolve MCP",
    echo       "command": "%INSTALL_DIR:\=\\%\\venv\\Scripts\\python.exe",
    echo       "args": ["%INSTALL_DIR:\=\\%\\src\\resolve_mcp_server.py"]
    echo     }
    echo   }
    echo }
) > "%CURSOR_CONFIG_FILE%"

REM Create project-level directory if it doesn't exist
if not exist "%PROJECT_CURSOR_DIR%" mkdir "%PROJECT_CURSOR_DIR%"

REM Create project-level config with absolute paths (same as system-level config)
(
    echo {
    echo   "mcpServers": {
    echo     "davinci-resolve": {
    echo       "name": "DaVinci Resolve MCP",
    echo       "command": "%INSTALL_DIR:\=\\%\\venv\\Scripts\\python.exe",
    echo       "args": ["%INSTALL_DIR:\=\\%\\src\\resolve_mcp_server.py"]
    echo     }
    echo   }
    echo }
) > "%PROJECT_CONFIG_FILE%"

if exist "%CURSOR_CONFIG_FILE%" if exist "%PROJECT_CONFIG_FILE%" (
    echo %GREEN%OK%NC%
    echo %GREEN%Cursor MCP config created at: %CURSOR_CONFIG_FILE%%NC%
    echo %GREEN%Project MCP config created at: %PROJECT_CONFIG_FILE%%NC%
    echo %LOG_PREFIX% Cursor MCP configuration created successfully >> "%LOG_FILE%"
    echo %LOG_PREFIX% System config file: %CURSOR_CONFIG_FILE% >> "%LOG_FILE%"
    echo %LOG_PREFIX% Project config file: %PROJECT_CONFIG_FILE% >> "%LOG_FILE%"
    
    REM Show the paths that were set
    echo %YELLOW%Paths configured:%NC%
    echo %BLUE%  Python: %INSTALL_DIR%\venv\Scripts\python.exe%NC%
    echo %BLUE%  Script: %INSTALL_DIR%\src\resolve_mcp_server.py%NC%
    
    set CONFIG_STATUS=1
) else (
    echo %RED%FAILED%NC%
    echo %RED%Failed to create Cursor MCP configuration.%NC%
    echo %LOG_PREFIX% Failed to create Cursor MCP configuration >> "%LOG_FILE%"
    set CONFIG_STATUS=0
    echo %RED%Installation aborted.%NC%
    exit /b 1
)

REM Verify installation
echo %LOG_PREFIX% Verifying installation >> "%LOG_FILE%"
echo %BLUE%%BOLD%=================================================%NC%
echo %YELLOW%%BOLD%Verifying installation...%NC%

REM Run the verification script
call "%INSTALL_DIR%\scripts\verify-installation.bat"
set VERIFY_RESULT=%ERRORLEVEL%

echo %LOG_PREFIX% Verification completed with result: %VERIFY_RESULT% >> "%LOG_FILE%"

if %VERIFY_RESULT% NEQ 0 (
    echo %LOG_PREFIX% Installation completed with verification warnings >> "%LOG_FILE%"
    echo %YELLOW%Installation completed with warnings.%NC%
    echo %YELLOW%Please fix any issues before starting the server.%NC%
    echo %YELLOW%You can run the verification script again:%NC%
    echo %BLUE%  scripts\verify-installation.bat%NC%
    exit /b 1
)

REM Installation successful
echo %LOG_PREFIX% Installation completed successfully >> "%LOG_FILE%"
echo %GREEN%%BOLD%Installation completed successfully!%NC%
echo %YELLOW%You can now start the server with:%NC%
echo %BLUE%  run-now.bat%NC%

REM Ask if the user wants to start the server now
echo.
set /p START_SERVER="Do you want to start the server now? (y/n) "
if /i "%START_SERVER%" == "y" (
    echo %LOG_PREFIX% Starting server >> "%LOG_FILE%"
    echo %BLUE%%BOLD%=================================================%NC%
    echo %GREEN%%BOLD%Starting DaVinci Resolve MCP Server...%NC%
    echo.

    REM Run the server using the virtual environment
    "%VENV_DIR%\Scripts\python.exe" "%INSTALL_DIR%\src\resolve_mcp_server.py"
    set SERVER_EXIT=%ERRORLEVEL%
    echo %LOG_PREFIX% Server exited with code: %SERVER_EXIT% >> "%LOG_FILE%"
) else (
    echo %LOG_PREFIX% User chose not to start the server >> "%LOG_FILE%"
    echo %YELLOW%You can start the server later with:%NC%
    echo %BLUE%  run-now.bat%NC%
)
