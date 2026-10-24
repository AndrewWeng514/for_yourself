# -*- coding: utf-8 -*-
"""管理 Windows 后台常驻服务（计划任务 + pythonw 无窗口运行）。

用法：
    python scripts/manage_service.py install    安装（登录自启 + 失败自动重启）
    python scripts/manage_service.py uninstall  卸载
    python scripts/manage_service.py start      立即启动
    python scripts/manage_service.py stop       停止
    python scripts/manage_service.py status     查看状态与健康检查
"""
import argparse
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TASK_NAME = "红利股票配置计算服务"
HOST = "127.0.0.1"
PORT = 8000


def _pythonw():
    return Path(sys.executable).with_name("pythonw.exe")


def _current_user():
    domain = os.environ.get("USERDOMAIN", "")
    name = os.environ.get("USERNAME", "")
    if not name:
        return None
    return (domain + "\\" + name) if domain else name


def _build_task_xml(pythonw, user):
    user_line = ("<UserId>%s</UserId>" % user) if user else ""
    trigger_user = ("<UserId>%s</UserId>" % user) if user else ""
    return (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        "  <RegistrationInfo>\n"
        "    <Description>红利股票配置计算 - 本地网站后台常驻服务（登录自启、失败自动重启）</Description>\n"
        "  </RegistrationInfo>\n"
        "  <Triggers>\n"
        "    <LogonTrigger>\n"
        "      <Enabled>true</Enabled>\n"
        "      " + trigger_user + "\n"
        "    </LogonTrigger>\n"
        "  </Triggers>\n"
        "  <Principals>\n"
        '    <Principal id="Author">\n'
        "      " + user_line + "\n"
        "      <LogonType>InteractiveToken</LogonType>\n"
        "      <RunLevel>LeastPrivilege</RunLevel>\n"
        "    </Principal>\n"
        "  </Principals>\n"
        "  <Settings>\n"
        "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n"
        "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n"
        "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n"
        "    <AllowHardTerminate>true</AllowHardTerminate>\n"
        "    <StartWhenAvailable>true</StartWhenAvailable>\n"
        "    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>\n"
        "    <AllowStartOnDemand>true</AllowStartOnDemand>\n"
        "    <Enabled>true</Enabled>\n"
        "    <RunOnlyIfIdle>false</RunOnlyIfIdle>\n"
        "    <WakeToRun>false</WakeToRun>\n"
        "    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>\n"
        "    <Priority>7</Priority>\n"
        "    <RestartOnFailure>\n"
        "      <Interval>PT1M</Interval>\n"
        "      <Count>5</Count>\n"
        "    </RestartOnFailure>\n"
        "  </Settings>\n"
        '  <Actions Context="Author">\n'
        "    <Exec>\n"
        "      <Command>" + str(pythonw) + "</Command>\n"
        '      <Arguments>-X utf8 server.py --service</Arguments>\n'
        "      <WorkingDirectory>" + str(PROJECT_ROOT) + "</WorkingDirectory>\n"
        "    </Exec>\n"
        "  </Actions>\n"
        "</Task>\n"
    )


def _run(*args):
    return subprocess.run(list(args), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _print_result(title, proc):
    print(("[成功] " if proc.returncode == 0 else "[失败] ") + title)
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if out:
        print(out)
    if err:
        print(err)


def cmd_install():
    pythonw = _pythonw()
    if not pythonw.exists():
        print("未找到 pythonw.exe：" + str(pythonw))
        print("请先安装 Python 3。")
        return 1

    # 方式一：导入 XML（带失败自动重启、指定工作目录）
    xml = _build_task_xml(pythonw, _current_user())
    fd, tmp_path = tempfile.mkstemp(suffix=".xml")
    try:
        with open(fd, "w", encoding="utf-16") as f:
            f.write(xml)
        proc = _run("schtasks", "/create", "/tn", TASK_NAME,
                    "/xml", tmp_path, "/f")
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    if proc.returncode == 0:
        _print_result("安装后台服务", proc)
        print("服务名：" + TASK_NAME)
        print("说明：登录 Windows 后自动启动，无窗口、失败自动重启。")
        print("立即启动请运行 scripts\\start_service.bat")
        return 0

    # 方式二：直接参数创建（兼容不支持 /xml 的环境，无失败重启）
    tr = '"%s" -X utf8 "%s" --service' % (pythonw, PROJECT_ROOT / "server.py")
    proc2 = _run("schtasks", "/create", "/tn", TASK_NAME, "/tr", tr,
                 "/sc", "onlogon", "/f")
    _print_result("安装后台服务", proc2)
    if proc2.returncode == 0:
        print("服务名：" + TASK_NAME)
        print("说明：登录 Windows 后自动启动，无窗口运行。")
    return proc2.returncode


def cmd_uninstall():
    proc = _run("schtasks", "/delete", "/tn", TASK_NAME, "/f")
    _print_result("卸载后台服务", proc)
    return proc.returncode


def cmd_start():
    proc = _run("schtasks", "/run", "/tn", TASK_NAME)
    _print_result("启动后台服务", proc)
    return proc.returncode


def cmd_stop():
    proc = _run("schtasks", "/end", "/tn", TASK_NAME)
    _print_result("停止后台服务", proc)
    return proc.returncode


def cmd_status():
    proc = _run("schtasks", "/query", "/tn", TASK_NAME, "/fo", "LIST", "/v")
    if proc.returncode != 0:
        print("后台服务尚未安装。请先运行 scripts\\install_service.bat")
        return proc.returncode
    print((proc.stdout or "").strip())
    print("-" * 40)
    try:
        with urllib.request.urlopen(
                "http://%s:%d/api/health" % (HOST, PORT), timeout=3) as resp:
            print("健康检查：" + resp.read().decode("utf-8"))
    except Exception:
        print("健康检查：服务未响应（可能尚未启动）")
    return 0


def main():
    parser = argparse.ArgumentParser(description="管理后台常驻服务")
    parser.add_argument("command",
                        choices=["install", "uninstall", "start", "stop", "status"])
    args = parser.parse_args()
    return {
        "install": cmd_install,
        "uninstall": cmd_uninstall,
        "start": cmd_start,
        "stop": cmd_stop,
        "status": cmd_status,
    }[args.command]()


if __name__ == "__main__":
    sys.exit(main())
