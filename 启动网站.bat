@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 检查 8000 端口是否已有服务在运行（不经过代理，直接探测端口）
powershell -NoProfile -Command "try { (New-Object System.Net.Sockets.TcpClient('127.0.0.1', 8000)).Close() } catch { exit 1 }" >nul 2>nul
if not errorlevel 1 (
    echo 服务已在后台运行，正在打开页面...
    start "" "http://127.0.0.1:8000"
    exit /b 0
)

set "PYCMD="
python --version >nul 2>nul
if not errorlevel 1 set "PYCMD=python"

if not defined PYCMD (
    py -3 --version >nul 2>nul
    if not errorlevel 1 set "PYCMD=py -3"
)

if not defined PYCMD (
    echo [错误] 没有找到 Python，请先安装 Python 3。
    echo 下载地址：https://www.python.org/downloads/
    echo 安装时请勾选 "Add Python to PATH"。
    echo.
    pause
    exit /b 1
)

echo 正在启动红利股票配置计算服务，浏览器将自动打开...
%PYCMD% server.py --open

echo.
echo 服务已停止，按任意键关闭窗口。
pause >nul