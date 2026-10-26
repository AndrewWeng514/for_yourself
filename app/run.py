# -*- coding: utf-8 -*-
"""服务入口。"""
import argparse
import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from http.server import ThreadingHTTPServer


class _HTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True

from . import paths
from . import store
from .server import make_handler
from . import stock_screener

log = logging.getLogger("dividend")


def setup_logging():
    paths.LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler = logging.FileHandler(paths.LOG_DIR / "server.log", encoding="utf-8")
    handler.setFormatter(fmt)
    root.addHandler(handler)
    if sys.stdout is not None:
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(fmt)
        root.addHandler(stream)


def _open_browser(url):
    try:
        webbrowser.open(url)
    except Exception:
        pass


def _screener_daemon():
    """后台每 6 小时检查一次，当日无缓存时抓取一次动态选股结果。"""
    while True:
        try:
            cached = store.load_json("screener_cache", None)
            today = time.strftime("%Y-%m-%d")
            fresh = (isinstance(cached, dict) and cached.get("date") == today
                     and isinstance(cached.get("quotes"), dict) and cached.get("quotes")
                     and isinstance(cached.get("history"), dict))
            if not fresh:
                stock_screener.get_screener(refresh=True)
        except Exception:  # noqa: BLE001
            log.exception("动态选股后台任务失败")
        time.sleep(6 * 3600)

def _lan_ip():
    """返回本机在局域网中的 IPv4 地址（取不到则返回 None）。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description="红利股票配置计算 - 本地服务")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    parser.add_argument("--service", action="store_true",
                        help="后台服务模式：端口被占用时直接退出")
    args = parser.parse_args(argv)

    setup_logging()

    try:
        config = store.load_config()
    except Exception:
        log.exception("读取 Excel 配置失败")
        return 1

    handler_cls = make_handler(config)
    try:
        server = _HTTPServer((args.host, args.port), handler_cls)
    except OSError:
        if args.service:
            log.error("端口 %s 已被占用，服务未启动（可能已有实例在运行）。", args.port)
            return 1
        server = _HTTPServer((args.host, 0), handler_cls)

    port = server.server_address[1]
    local_url = "http://127.0.0.1:%d" % port
    lan_ip = _lan_ip()
    lan_url = ("http://%s:%d" % (lan_ip, port)) if lan_ip else None
    log.info("服务已启动（本机）：%s", local_url)
    if lan_url:
        log.info("服务已启动（局域网）：%s", lan_url)
    log.info("数据文件：%s", paths.find_xlsx())

    if args.open:
        threading.Timer(0.8, _open_browser, args=(local_url,)).start()

    threading.Thread(target=_screener_daemon, daemon=True).start()

    if not args.service:
        print("=" * 56)
        print("  红利股票配置计算 - 本地服务已启动")
        print("  本机访问:   " + local_url)
        if lan_url:
            print("  局域网访问: " + lan_url)
        print("  按 Ctrl+C 停止服务")
        print("=" * 56)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("服务已停止")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
