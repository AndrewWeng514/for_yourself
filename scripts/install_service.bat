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
echo 正在安装后台常驻服务（登录自启 + 失败自动重启）...
%PYCMD% scripts\manage_service.py install
if errorlevel 1 (
    echo.
    echo [提示] 如提示权限不足，请右键本文件选择“以管理员身份运行”。
)
echo.
pause