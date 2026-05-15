@echo off
setlocal
pushd "%~dp0"

chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
echo -------------------------------------------
echo Feishu Screenshot Sentinel (Debug)
echo Stop:
echo   1) Click this window
echo   2) Press Ctrl+C (STOP, not copy)
echo   3) Or close window (X)
echo -------------------------------------------
echo.

:: 找到可用的 python
set PYTHON_EXE=
if exist "C:\Program Files\Python311\python.exe" set PYTHON_EXE=C:\Program Files\Python311\python.exe
if "%PYTHON_EXE%"=="" (
  where python >nul 2>nul
  if %errorlevel%==0 set PYTHON_EXE=python
)
if "%PYTHON_EXE%"=="" goto nopython

:: 自动安装缺失依赖
echo 检查依赖包...
"%PYTHON_EXE%" -c "import pynput, PIL, pyperclip" >nul 2>nul
if %errorlevel% neq 0 (
  echo 正在安装依赖，请稍候...
  "%PYTHON_EXE%" -m pip install -r "%~dp0requirements.txt" --quiet
  if %errorlevel% neq 0 (
    echo 依赖安装失败，请手动运行：pip install -r requirements.txt
    pause
    exit /b 1
  )
  echo 依赖安装完成。
)

"%PYTHON_EXE%" "%~dp0feishu_screenshot_guard.py" %*
goto done

:nopython

echo Python 未找到。请先安装 Python 3.11：https://www.python.org/downloads/

:done
popd
pause
