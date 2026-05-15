@echo off
setlocal
pushd "%~dp0"

echo ============================================
echo Page Agent Bridge for DeepSeek TUI
echo ============================================
echo.
echo This starts the MCP bridge that lets DeepSeek TUI
echo control a Chrome browser via the Page Agent extension.
echo.
echo Prerequisites:
echo   1. Node.js 20+ installed
echo   2. Page Agent Chrome extension loaded
echo   3. Run: npm install (first time only)
echo.
echo Starting bridge on http://127.0.0.1:38406 ...
echo Press Ctrl+C to stop.
echo.

where node >nul 2>nul
if %errorlevel% neq 0 (
    echo ERROR: Node.js not found. Install from https://nodejs.org/
    pause
    exit /b 1
)

if not exist "node_modules\" (
    echo Installing dependencies...
    call npm install
    if %errorlevel% neq 0 (
        echo ERROR: npm install failed
        pause
        exit /b 1
    )
)

start "PageAgent-PortManager" /min cmd /c "node "%~dp0port-manager.js""
timeout /t 2 /nobreak >nul
node "%~dp0deepseek-bridge.js"

popd
pause
