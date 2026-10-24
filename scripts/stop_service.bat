@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
set "PYCMD="
python --version >nul 2>nul
if not errorlevel 1 set "PYCMD=python"
if not defined PYCMD (
    py -3 --version >nul 2>nul
    if not errorlevel 1 set "PYCMD=py -3"
)
if not defined PYCMD (
    echo [错误] 没有找到 Python，请先安装 Python 3。
    echo 安装时请勾选 "Add Python to PATH"。
    pause
    exit /b 1
)
echo 正在停止后台服务...
%PYCMD% scripts\manage_service.py stop
echo.
pause