@echo off
setlocal
pushd "%~dp0"

echo ============================================
echo Screenshot Sentinel for DeepSeek TUI
echo ============================================
echo.
echo Watches a folder for new screenshots and copies
echo the file path to clipboard for easy pasting.
echo.
echo Usage:
echo   start-sentinel.bat           Node.js version
echo   start-sentinel.bat --python  Python version
echo   start-sentinel.bat --help    Show options
echo.

if "%1"=="--python" goto python_version
if "%1"=="--help" goto show_help

where node >nul 2>nul
if %errorlevel% neq 0 (
    echo Node.js not found, trying Python version...
    goto python_version
)

if not exist "node_modules\" (
    echo Installing dependencies...
    call npm install
)

node "%~dp0media-bridge.js" %*
goto done

:python_version
set PYTHON_EXE=
where python >nul 2>nul
if %errorlevel% equ 0 set PYTHON_EXE=python
if "%PYTHON_EXE%"=="" (
    echo ERROR: Neither Node.js nor Python found.
    pause
    exit /b 1
)
"%PYTHON_EXE%" "%~dp0feishu_screenshot_guard.py" %*
goto done

:show_help
echo Options (Node.js version):
echo   --dir PATH      Watch directory (default: screenshots/)
echo   --max N         Max files to keep (default: 15)
echo   --ext .png,.jpg File extensions to watch
echo   --path relative Path format: absolute or relative
echo   --style posix   Path style: win, posix, or native
echo   --quiet         Less output
echo.
echo Options (Python version):
echo   --dir PATH      Save directory (default: feishu_uploads/)
echo   --max N         Max files to keep (default: 5)
echo   --hotkey KEY    Global hotkey (default: ctrl+shift+a)
echo   --timeout N     Standby timeout seconds (default: 15)
echo.
goto done

:done
popd
pause
