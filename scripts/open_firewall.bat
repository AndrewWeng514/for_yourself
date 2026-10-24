@echo off
chcp 65001 >nul
net session >nul 2>&1
if errorlevel 1 (
  echo [提示] 需要管理员权限，请右键本文件选择“以管理员身份运行”。
  echo.
  pause
  exit /b 1
)
netsh advfirewall firewall add rule name="红利配置服务(8000)" dir=in action=allow protocol=TCP localport=8000
if errorlevel 1 (
  echo [失败] 添加防火墙规则失败。
) else (
  echo [成功] 已允许局域网设备访问本机 8000 端口。
)
echo.
pause
