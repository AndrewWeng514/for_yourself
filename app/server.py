# -*- coding: utf-8 -*-
"""HTTP 服务：静态页面 + JSON API。

新增功能时，在 do_GET 的「API 路由」区域添加 /api/xxx 分支，
并在 web/ 下添加对应的页面与 JS 模块即可。
"""
import json
import logging
import os
import time
from http.server import BaseHTTPRequestHandler
from urllib import parse

from . import paths
from . import market
from . import savings
from . import store
from . import trend
from . import stock_screener
from . import ai_advisor
from . import fund

log = logging.getLogger("dividend.server")

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def make_handler(config):
    """返回绑定了配置的请求处理类。"""

    class Handler(BaseHTTPRequestHandler):
        server_version = "DividendCalc/1.0"

        def log_message(self, fmt, *args):
            log.debug("%s %s", self.address_string(), fmt % args)

        def _send_json(self, obj, status=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path):
            try:
                with open(path, "rb") as f:
                    data = f.read()
            except OSError:
                self.send_error(404, "Not Found")
                return
            ext = os.path.splitext(path)[1].lower()
            ctype = MIME.get(ext, "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            parsed = parse.urlparse(self.path)
            path = parsed.path

            # ---- API 路由（新增功能在这里扩展）----
            if path == "/api/config":
                self._send_json(config)
                return
            if path == "/api/stocks":
                self._send_json({
                    "total_principal": config.get("total_principal", 0),
                    "stocks": config.get("stocks", []),
                })
                return
            if path == "/api/quotes":
                try:
                    result = market.build_quotes(config["stocks"])
                    changed = False
                    for s in config["stocks"]:
                        q = result.get("quotes", {}).get(s["code"]) or {}
                        if q.get("is_live_price") and q.get("price") is not None:
                            if s.get("price") != q["price"]:
                                s["price"] = q["price"]
                                changed = True
                        if q.get("is_live_yield") and q.get("yield") is not None:
                            if s.get("ref_yield") != q["yield"]:
                                s["ref_yield"] = q["yield"]
                                changed = True
                    if changed:
                        store.save_config(config)
                    self._send_json(result)
                except Exception as exc:  # noqa: BLE001
                    log.exception("行情接口异常")
                    self._send_json(
                        {"live": False, "quotes": {}, "errors": [str(exc)]}, 500)
                return
            if path == "/api/stock/lookup":
                qs = parse.parse_qs(parsed.query)
                try:
                    self._send_json(market.lookup_stock(qs.get("q", [""])[0]))
                except Exception as exc:  # noqa: BLE001
                    log.exception("股票查询失败")
                    self._send_json({"ok": False, "error": str(exc)}, 400)
                return
            if path == "/api/savings":
                self._send_json(savings.load_plan())
                return
            if path == "/api/savings/snapshot":
                self._send_json({
                    "ok": True,
                    "latest": store.load_latest_snapshot(),
                    "snapshots": store.load_snapshots(),
                })
                return
            if path == "/api/health":
                self._send_json({
                    "ok": True,
                    "stocks": len(config["stocks"]),
                    "source": paths.find_xlsx().name,
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                })
                return

            if path == "/api/trend":
                try:
                    self._send_json(trend.build_trend())
                except Exception as exc:  # noqa: BLE001
                    log.exception("资产趋势接口异常")
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return
            if path == "/api/screener/rules":
                self._send_json(stock_screener.get_rules())
                return
            if path == "/api/screener":
                qs = parse.parse_qs(parsed.query)
                refresh = qs.get("refresh", ["0"])[0] in ("1", "true", "yes")
                try:
                    self._send_json(stock_screener.get_screener(
                        refresh=refresh,
                        yield_threshold=qs.get("yield", [None])[0],
                        max_price=qs.get("price", [None])[0]))
                except Exception as exc:  # noqa: BLE001
                    log.exception("动态选股接口异常")
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return
            if path == "/api/ai/status":
                self._send_json(ai_advisor.public_config())
                return
            if path == "/api/advice":
                self._send_json(ai_advisor.cached_advice())
                return
            if path == "/api/fund/lookup":
                qs = parse.parse_qs(parsed.query)
                try:
                    self._send_json({"ok": True,
                                     "results": fund.search(qs.get("q", [""])[0])})
                except Exception as exc:  # noqa: BLE001
                    log.exception("基金查询失败")
                    self._send_json({"ok": False, "error": str(exc)}, 400)
                return
            if path == "/api/funds":
                qs = parse.parse_qs(parsed.query)
                refresh = qs.get("refresh", ["0"])[0] in ("1", "true", "yes")
                try:
                    self._send_json(fund.build(store.load_funds(), refresh=refresh))
                except Exception as exc:  # noqa: BLE001
                    log.exception("基金行情失败")
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return
            # ---- 静态页面 ----
            if path == "/":
                path = "/index.html"
            rel = os.path.normpath(path.lstrip("/"))
            target = os.path.join(paths.WEB_DIR, rel)
            if not os.path.abspath(target).startswith(
                    os.path.abspath(str(paths.WEB_DIR))):
                self.send_error(403, "Forbidden")
                return
            if os.path.isfile(target):
                self._send_file(target)
            else:
                self.send_error(404, "Not Found")

        def _post_savings(self):
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length) if length else b""
                data = json.loads(body.decode("utf-8"))
                plan = savings.load_plan()
                if "target" in data:
                    plan["target"] = float(data.get("target") or 0)
                if "monthly_invest" in data:
                    plan["monthly_invest"] = float(data.get("monthly_invest") or 0)
                if "disciplines" in data:
                    raw = data.get("disciplines")
                    if isinstance(raw, list):
                        plan["disciplines"] = [str(x).strip() for x in raw if str(x).strip()]
                    else:
                        plan["disciplines"] = []
                savings.save_plan(plan)
                log.info("已保存储蓄计划")
                self._send_json({"ok": True})
            except Exception as exc:  # noqa: BLE001
                log.exception("保存储蓄计划失败")
                self._send_json({"ok": False, "error": str(exc)}, 400)

        def do_POST(self):
            parsed = parse.urlparse(self.path)
            if parsed.path == "/api/ai/config":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(length) if length else b""
                    data = json.loads(body.decode("utf-8"))
                    self._send_json({"ok": True, **ai_advisor.save_config(data)})
                except Exception as exc:  # noqa: BLE001
                    log.exception("保存 AI 配置失败")
                    self._send_json({"ok": False, "error": str(exc)}, 400)
                return
            if parsed.path == "/api/advice":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(length) if length else b""
                    data = json.loads(body.decode("utf-8"))
                    self._send_json(ai_advisor.generate(
                        data.get("context"), force=bool(data.get("force"))))
                except Exception as exc:  # noqa: BLE001
                    log.exception("生成 AI 建议失败")
                    self._send_json({"ok": False, "error": str(exc)}, 400)
                return
            if parsed.path == "/api/funds/add":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(length) if length else b""
                    data = json.loads(body.decode("utf-8"))
                    code = str(data.get("code") or "").strip()
                    meta = fund.lookup(code)
                    if meta.get("market") == "ETF":
                        try:
                            q = fund.etf_quote(code)
                            meta["market_price"] = q["price"]
                        except Exception:  # noqa: BLE001
                            meta["market"] = "OTC"
                    meta["shares"] = float(data.get("shares") or 0)
                    result = store.add_fund(meta)
                    if result.get("ok"):
                        log.info("已添加基金：%s", code)
                        self._send_json({"ok": True, "fund": meta})
                    else:
                        self._send_json({"ok": False, "exists": True,
                                         "error": "该基金已在持仓中"})
                except Exception as exc:  # noqa: BLE001
                    log.exception("添加基金失败")
                    self._send_json({"ok": False, "error": str(exc)}, 400)
                return
            if parsed.path == "/api/funds/shares":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(length) if length else b""
                    data = json.loads(body.decode("utf-8"))
                    updated = store.update_fund_shares(data.get("shares") or {})
                    self._send_json({"ok": True, "updated": updated})
                except Exception as exc:  # noqa: BLE001
                    log.exception("更新基金份额失败")
                    self._send_json({"ok": False, "error": str(exc)}, 400)
                return
            if parsed.path == "/api/savings":
                self._post_savings()
                return
            if parsed.path == "/api/stocks/shares":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(length) if length else b""
                    data = json.loads(body.decode("utf-8"))
                    updated = store.update_shares(data.get("shares") or {})
                    fresh = store.load_config()
                    config["total_principal"] = fresh["total_principal"]
                    config["stocks"] = fresh["stocks"]
                    log.info("已更新实仓股数：%d 条", updated)
                    self._send_json({"ok": True, "updated": updated})
                except Exception as exc:  # noqa: BLE001
                    log.exception("更新实仓股数失败")
                    self._send_json({"ok": False, "error": str(exc)}, 400)
                return
            if parsed.path == "/api/savings/snapshot":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(length) if length else b""
                    data = json.loads(body.decode("utf-8"))
                    raw_items = data.get("items")
                    if isinstance(raw_items, list):
                        items = store.normalize_items(raw_items)
                    else:
                        items = store.items_from_accounts(data.get("accounts") or {})
                    snap = store.add_snapshot(items)
                    log.info("已保存资产快照：%s", snap["week"])
                    self._send_json({"ok": True, "snapshot": snap})
                except Exception as exc:  # noqa: BLE001
                    log.exception("保存资产快照失败")
                    self._send_json({"ok": False, "error": str(exc)}, 400)
                return
            if parsed.path == "/api/stocks/add":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(length) if length else b""
                    data = json.loads(body.decode("utf-8"))
                    result = store.add_stock(data)
                    if result.get("ok"):
                        fresh = store.load_config()
                        config["total_principal"] = fresh["total_principal"]
                        config["stocks"] = fresh["stocks"]
                        log.info("已从动态选股加入配置：%s", data.get("code"))
                        self._send_json({"ok": True, "exists": False})
                    else:
                        self._send_json({"ok": False, "exists": True,
                                         "error": "该股票已在实仓列表中"})
                except Exception as exc:  # noqa: BLE001
                    log.exception("加入配置失败")
                    self._send_json({"ok": False, "error": str(exc)}, 400)
                return
            if parsed.path != "/api/stocks":
                self.send_error(404, "Not Found")
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length) if length else b""
                data = json.loads(body.decode("utf-8"))
                stocks = data.get("stocks")
                if not isinstance(stocks, list):
                    raise ValueError("stocks 必须是数组")
                norm = []
                for s in stocks:
                    if not isinstance(s, dict):
                        continue
                    norm.append({
                        "name": str(s.get("name") or "").strip(),
                        "code": str(s.get("code") or "").strip(),
                        "weight": float(s.get("weight") or 0),
                        "price": float(s.get("price") or 0),
                        "ref_yield": float(s.get("ref_yield") or 0),
                        "shares_held": float(s.get("shares_held") or 0),
                    })
                merged = [dict(s) for s in config.get("stocks", [])]
                by_code = {
                    s.get("code"): i for i, s in enumerate(merged) if s.get("code")
                }
                for s in norm:
                    code = s.get("code")
                    if not code:
                        continue
                    if code in by_code:
                        merged[by_code[code]].update(s)
                    else:
                        by_code[code] = len(merged)
                        merged.append(s)
                config["total_principal"] = float(data.get("total_principal") or 0)
                config["stocks"] = merged
                store.save_config(config)
                log.info("已合并股票配置：%d 只", len(merged))
                self._send_json({"ok": True, "stocks": len(merged)})
            except Exception as exc:  # noqa: BLE001
                log.exception("保存股票配置失败")
                self._send_json({"ok": False, "error": str(exc)}, 400)

        def do_DELETE(self):
            parsed = parse.urlparse(self.path)
            if parsed.path == "/api/savings/snapshot":
                try:
                    result = store.delete_latest_snapshot()
                    self._send_json({"ok": True, "deleted": result})
                except Exception as exc:  # noqa: BLE001
                    log.exception("删除资产快照失败")
                    self._send_json({"ok": False, "error": str(exc)}, 400)
                return
            if parsed.path == "/api/funds":
                qs = parse.parse_qs(parsed.query)
                code = (qs.get("code", [""])[0] or "").strip()
                try:
                    if not code:
                        raise ValueError("缺少基金代码")
                    deleted = store.delete_fund(code)
                    log.info("已删除基金：%s", code)
                    self._send_json({"ok": True, "deleted": deleted})
                except Exception as exc:  # noqa: BLE001
                    log.exception("删除基金失败")
                    self._send_json({"ok": False, "error": str(exc)}, 400)
                return
            if parsed.path == "/api/stocks":
                qs = parse.parse_qs(parsed.query)
                code = (qs.get("code", [""])[0] or "").strip()
                try:
                    if not code:
                        raise ValueError("缺少股票代码")
                    deleted = store.delete_stock(code)
                    fresh = store.load_config()
                    config["total_principal"] = fresh["total_principal"]
                    config["stocks"] = fresh["stocks"]
                    log.info("已删除实仓股票：%s", code)
                    self._send_json({"ok": True, "deleted": deleted})
                except Exception as exc:  # noqa: BLE001
                    log.exception("删除实仓股票失败")
                    self._send_json({"ok": False, "error": str(exc)}, 400)
                return
            self.send_error(404, "Not Found")

    return Handler
