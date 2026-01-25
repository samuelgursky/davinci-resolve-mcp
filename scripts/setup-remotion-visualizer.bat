@echo off
REM Setup script for Remotion Music Visualization
REM This creates a Remotion project for generating music visualizers

echo ==============================================
echo   Remotion Music Visualization Setup
echo ==============================================
echo.

REM Check for Node.js
where node >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo Node.js is not installed!
    echo Please install Node.js from https://nodejs.org/
    pause
    exit /b 1
)

REM Check for npm
where npm >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo npm is not installed!
    echo Please install Node.js from https://nodejs.org/
    pause
    exit /b 1
)

echo Node.js and npm found!
echo.

REM Create visualizer directory
set VISUALIZER_DIR=%~dp0..\remotion-visualizer
if not exist "%VISUALIZER_DIR%" (
    echo Creating Remotion visualizer project...
    mkdir "%VISUALIZER_DIR%"
)

cd /d "%VISUALIZER_DIR%"

REM Initialize Remotion project from template
echo.
echo Initializing Remotion music visualization template...
echo This may take a few minutes...
echo.

npx create-video@latest --template music-visualization .

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Failed to create Remotion project.
    echo Try running manually: npx create-video@latest --template music-visualization
    pause
    exit /b 1
)

echo.
echo ==============================================
echo   Remotion Setup Complete!
echo ==============================================
echo.
echo Your Remotion visualizer is at: %VISUALIZER_DIR%
echo.
echo To use:
echo   1. Copy your music file to: %VISUALIZER_DIR%\public\
echo   2. Run: npx remotion studio
echo   3. Customize the visualizer
echo   4. Click Render to export video
echo   5. Import the rendered video into DaVinci Resolve
echo.
pause
