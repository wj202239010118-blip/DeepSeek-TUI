@echo off
setlocal
pushd "%~dp0"

echo ============================================
echo wx-bot — WeChat Automation for DeepSeek TUI
echo ============================================
echo.
echo Usage:
echo   start-wx-bot.bat              Start orchestrator loop
echo   start-wx-bot.bat --once       Run one poll cycle
echo   start-wx-bot.bat --test       Test safety modules
echo   start-wx-bot.bat --post "..." Post a Moment
echo.
echo Prerequisites:
echo   1. Python 3.10+ with pip
echo   2. WeChat Desktop logged in
echo   3. wx-cli installed and configured
echo   4. Copy config.example.json to config.json and edit
echo.

set PYTHON_EXE=
where python >nul 2>nul
if %errorlevel% equ 0 set PYTHON_EXE=python
if "%PYTHON_EXE%"=="" (
    echo ERROR: Python not found.
    pause
    exit /b 1
)

:: Check config
if not exist "config.json" (
    echo WARNING: config.json not found.
    echo Copy config.example.json to config.json and set wx_cli.exe_path
    echo.
)

:: Auto-install deps
"%PYTHON_EXE%" -c "import pyautogui, pynput, win32gui" >nul 2>nul
if %errorlevel% neq 0 (
    echo Installing dependencies...
    "%PYTHON_EXE%" -m pip install -r requirements.txt --quiet
)

"%PYTHON_EXE%" run.py %*

popd
pause
