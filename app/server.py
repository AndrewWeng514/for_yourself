# -*- coding: utf-8 -*-
"""HTTP 服务：静态页面 + JSON API。

新增功能时，在 do_GET 的「API 路由」区域添加 /api/xxx 分支，
并在 web/ 下添加对应的页面与 JS 模块即可。
"""
import base64
import gzip
import hmac
import io
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from datetime import date
from email.utils import formatdate, parsedate_to_datetime
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
from . import diary

log = logging.getLogger("dividend.server")

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
    ".mp4": "video/mp4",
    ".ico": "image/x-icon",
}

_IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".svg", ".ico", ".gif"})
_LONG_CACHE_PREFIXES = ("vendor/", "css/", "js/")
_GZIP_COMPRESSIBLE_EXTS = frozenset({
    ".html", ".css", ".js", ".json", ".svg", ".txt", ".xml",
})
_GZIP_CACHE_LIMIT = 64 * 1024 * 1024
_gzip_cache = OrderedDict()
_gzip_cache_bytes = 0
_gzip_cache_lock = threading.Lock()
AUTH_USER = os.environ.get("PORTAL_AUTH_USER", "portal")
AUTH_PASSWORD = os.environ.get("PORTAL_AUTH_PASSWORD", "")


def _file_etag(mtime, size):
    return f'"{int(mtime)}-{size}"'


def _accepts_gzip(accept_encoding):
    if not accept_encoding:
        return False
    for part in accept_encoding.split(","):
        pieces = [piece.strip() for piece in part.split(";")]
        if not pieces or pieces[0].lower() != "gzip":
            continue
        quality = 1.0
        for param in pieces[1:]:
            if "=" in param:
                key, value = param.split("=", 1)
                if key.strip().lower() == "q":
                    try:
                        quality = float(value.strip())
                    except ValueError:
                        quality = 0.0
        return quality > 0
    return False


def _gzip_cache_key(path, mtime, size):
    return (os.path.abspath(path), mtime, size)


def _get_gzip_body(path, mtime, size, raw):
    global _gzip_cache_bytes
    key = _gzip_cache_key(path, mtime, size)
    with _gzip_cache_lock:
        cached = _gzip_cache.get(key)
        if cached is not None:
            _gzip_cache.move_to_end(key)
            return cached
    compressed = gzip.compress(raw)
    with _gzip_cache_lock:
        cached = _gzip_cache.get(key)
        if cached is not None:
            _gzip_cache.move_to_end(key)
            return cached
        _gzip_cache[key] = compressed
        _gzip_cache_bytes += len(compressed)
        while _gzip_cache_bytes > _GZIP_CACHE_LIMIT and _gzip_cache:
            _, evicted = _gzip_cache.popitem(last=False)
            _gzip_cache_bytes -= len(evicted)
    return compressed


def _static_cache_control(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".html":
        return "no-cache"
    web_root = os.path.abspath(str(paths.WEB_DIR))
    abspath = os.path.abspath(path)
    if abspath.startswith(web_root + os.sep):
        rel = os.path.relpath(abspath, web_root).replace("\\", "/")
        if rel.startswith(_LONG_CACHE_PREFIXES):
            return "public, max-age=86400"
    if ext in _IMAGE_EXTS or ext in (".css", ".js"):
        return "public, max-age=86400"
    return "no-cache"


def make_handler(config):
    """返回绑定了配置的请求处理类。"""

    class Handler(BaseHTTPRequestHandler):
        server_version = "DividendCalc/1.0"

        def log_message(self, fmt, *args):
            log.debug("%s %s", self.address_string(), fmt % args)

        def _authorized(self):
            if not AUTH_PASSWORD:
                return True
            if self.path.split("?", 1)[0] == "/api/health":
                return True
            header = self.headers.get("Authorization", "")
            if not header.startswith("Basic "):
                return self._auth_required()
            try:
                decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                return self._auth_required()
            user, _, password = decoded.partition(":")
            if user == AUTH_USER and hmac.compare_digest(password, AUTH_PASSWORD):
                return True
            return self._auth_required()

        def _auth_required(self):
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="Hongli Ledger"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False

        def _send_json(self, obj, status=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _is_not_modified(self, etag, mtime):
            inm = self.headers.get("If-None-Match")
            if inm:
                for token in inm.split(","):
                    candidate = token.strip()
                    if candidate in ("*", etag, f"W/{etag}"):
                        return True
                return False
            ims = self.headers.get("If-Modified-Since")
            if not ims:
                return False
            try:
                ims_ts = parsedate_to_datetime(ims).timestamp()
            except (TypeError, ValueError, OverflowError):
                return False
            return int(mtime) <= int(ims_ts)

        def _send_file(self, path):
            try:
                st = os.stat(path)
            except OSError:
                self.send_error(404, "Not Found")
                return
            mtime = st.st_mtime
            size = st.st_size
            etag = _file_etag(mtime, size)
            last_modified = formatdate(mtime, usegmt=True)
            cache_control = _static_cache_control(path)
            ext = os.path.splitext(path)[1].lower()
            compressible = ext in _GZIP_COMPRESSIBLE_EXTS

            if self._is_not_modified(etag, mtime):
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Last-Modified", last_modified)
                self.send_header("Cache-Control", cache_control)
                if compressible:
                    self.send_header("Vary", "Accept-Encoding")
                self.end_headers()
                return

            try:
                with open(path, "rb") as f:
                    data = f.read()
            except OSError:
                self.send_error(404, "Not Found")
                return
            ctype = MIME.get(ext, "application/octet-stream")
            use_gzip = compressible and _accepts_gzip(self.headers.get("Accept-Encoding"))
            if use_gzip:
                body = _get_gzip_body(path, mtime, size, data)
            else:
                body = data
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            if compressible:
                self.send_header("Vary", "Accept-Encoding")
            if use_gzip:
                self.send_header("Content-Encoding", "gzip")
            self.send_header("ETag", etag)
            self.send_header("Last-Modified", last_modified)
            self.send_header("Cache-Control", cache_control)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _read_json(self):
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
            except (TypeError, ValueError):
                length = 0
            raw = self.rfile.read(length) if length else b""
            if not raw.strip():
                return {}
            try:
                data = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise ValueError("JSON 无法解析")
            if not isinstance(data, dict):
                raise ValueError("请求体必须是 JSON 对象")
            return data

        def _diary_api(self, method, parsed):
            try:
                qs = parse.parse_qs(parsed.query)
                if method == "GET":
                    if parsed.path == "/api/diary/templates":
                        self._send_json({"ok": True, "templates": diary.list_templates()})
                        return
                    if parsed.path.startswith("/api/diary/templates/"):
                        gran = parsed.path.rstrip("/").rsplit("/", 1)[-1]
                        key = qs.get("key", [None])[0]
                        self._send_json({"ok": True, **diary.get_template(gran, key)})
                        return
                    if parsed.path == "/api/diary/entries":
                        self._send_json({"ok": True, "items": diary.list_entries()})
                        return
                    if parsed.path == "/api/diary/calendar":
                        year = qs.get("year", [str(date.today().year)])[0]
                        month = qs.get("month", [str(date.today().month)])[0]
                        self._send_json({"ok": True, **diary.calendar(year, month)})
                        return
                    if parsed.path == "/api/diary/entry":
                        gran = qs.get("gran", ["day"])[0]
                        key = qs.get("key", [""])[0]
                        self._send_json({"ok": True, **diary.read_entry(gran, key)})
                        return
                    if parsed.path == "/api/diary/memos":
                        if qs.get("all", ["0"])[0] in ("1", "true", "yes") or \
                                qs.get("history", ["0"])[0] in ("1", "true", "yes"):
                            year = qs.get("year", [None])[0] or None
                            limit = qs.get("limit", ["500"])[0]
                            memos = diary.memo_history(year, limit)
                            self._send_json({"ok": True, "memos": memos, "total": len(memos)})
                            return
                        day = qs.get("date", [date.today().isoformat()])[0]
                        entry = diary.read_entry("day", day)
                        self._send_json({"ok": True, "date": day, "memos": entry["memos"],
                                         "path": entry["path"], "exists": entry["exists"]})
                        return
                    if parsed.path == "/api/diary/heatmap":
                        year = qs.get("year", [str(date.today().year)])[0]
                        self._send_json({"ok": True, **diary.heatmap(year)})
                        return
                    if parsed.path == "/api/diary/tags":
                        year = qs.get("year", [None])[0]
                        self._send_json({"ok": True, "tags": diary.tags(year)})
                        return
                    self._send_json({"ok": False, "error": "未知日记接口"}, 404)
                    return

                if method == "POST":
                    if parsed.path.startswith("/api/diary/templates/"):
                        gran = parsed.path.rstrip("/").rsplit("/", 1)[-1]
                        data = self._read_json()
                        result = diary.save_template(gran, data.get("content", ""))
                        self._send_json({"ok": True, **result})
                        return
                    if parsed.path == "/api/diary/entry":
                        data = self._read_json()
                        result = diary.save_entry(
                            data.get("gran", "day"),
                            data.get("key", ""),
                            data.get("content", ""),
                            data.get("base_sha256"),
                            bool(data.get("force")),
                        )
                        self._send_json({"ok": True, **result})
                        return
                    if parsed.path == "/api/diary/memos/update":
                        data = self._read_json()
                        result = diary.update_memo(
                            data.get("date", ""), data.get("index"),
                            data.get("text"), data.get("time"))
                        self._send_json({"ok": True, **result})
                        return
                    if parsed.path == "/api/diary/memos/delete":
                        data = self._read_json()
                        result = diary.delete_memo(data.get("date", ""), data.get("index"))
                        self._send_json({"ok": True, **result})
                        return
                    if parsed.path == "/api/diary/summarize":
                        data = self._read_json()
                        result = diary.summarize_period(
                            data.get("gran", "week"), data.get("key", ""))
                        self._send_json({"ok": True, **result})
                        return
                    if parsed.path == "/api/diary/summarize/apply":
                        data = self._read_json()
                        result = diary.apply_summary(
                            data.get("gran", "week"), data.get("key", ""),
                            data.get("summary", ""), data.get("title"))
                        self._send_json({"ok": True, **result})
                        return
                    if parsed.path == "/api/diary/memos":
                        data = self._read_json()
                        result = diary.append_memo(
                            data.get("date", ""), data.get("text", ""), data.get("time"))
                        self._send_json({"ok": True, **result})
                        return
                    if parsed.path == "/api/diary/assets":
                        data = self._read_json()
                        url = diary.save_asset(data.get("data", ""), data.get("ext", "webp"))
                        self._send_json({"ok": True, "url": url})
                        return
                    if parsed.path == "/api/diary/import":
                        length = int(self.headers.get("Content-Length", 0) or 0)
                        raw = self.rfile.read(length) if length else b""
                        if not raw:
                            raise diary.DiaryError("空文件")
                        if len(raw) > 100 * 1024 * 1024:
                            raise diary.DiaryError(
                                "压缩包不能超过 100MB", 413, "PAYLOAD_TOO_LARGE")
                        stats = diary.import_zip(
                            io.BytesIO(raw),
                            overwrite=qs.get("overwrite", ["0"])[0] in ("1", "true", "yes"),
                        )
                        self._send_json({"ok": True, **stats})
                        return
                    self._send_json({"ok": False, "error": "未知日记接口"}, 404)
                    return
            except diary.DiaryError as exc:
                self._send_json({"ok": False, "error": str(exc), "code": exc.code}, exc.status)
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, 400)
            except Exception as exc:  # noqa: BLE001
                log.exception("日记接口异常")
                self._send_json({"ok": False, "error": str(exc)}, 500)

        def _send_diary_asset(self, path):
            rel = parse.unquote(path[len("/diary-assets/"):])
            try:
                target = diary._safe_rel("assets/" + rel)
            except diary.DiaryError:
                self.send_error(403, "Forbidden")
                return
            if not target.is_file():
                self.send_error(404, "Not Found")
                return
            self._send_file(str(target))

        def do_GET(self):
            if not self._authorized():
                return
            parsed = parse.urlparse(self.path)
            path = parsed.path

            # ---- API 路由（新增功能在这里扩展）----
            if path == "/api/config":
                self._send_json(config)
                return
            if path == "/api/stocks":
                self._send_json({
                    "total_principal": config.get("total_principal", 0),
                    "stock_cash": config.get("stock_cash", 0),
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
            if path == "/api/diary" or path.startswith("/api/diary/"):
                self._diary_api("GET", parsed)
                return
            if path.startswith("/diary-assets/"):
                self._send_diary_asset(path)
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
            if not self._authorized():
                return
            parsed = parse.urlparse(self.path)
            if parsed.path == "/api/diary" or parsed.path.startswith("/api/diary/"):
                self._diary_api("POST", parsed)
                return
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
            if parsed.path == "/api/stocks/cash":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(length) if length else b""
                    data = json.loads(body.decode("utf-8"))
                    cash = store.update_stock_cash(data.get("cash"))
                    config["stock_cash"] = cash
                    log.info("已更新股票账户现金：%.2f", cash)
                    self._send_json({"ok": True, "stock_cash": cash})
                except Exception as exc:  # noqa: BLE001
                    log.exception("更新股票现金失败")
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
            if not self._authorized():
                return
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
