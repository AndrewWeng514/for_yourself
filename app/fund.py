# -*- coding: utf-8 -*-
"""基金数据：搜索、最新净值、场内 ETF 行情、货基 7 日年化、近 1 年涨幅。

数据来源：东方财富基金搜索/净值接口 + 腾讯场内行情。
场外基金没有真正的盘中实时净值，只提供最新公布净值与净值日期；
ETF 提供盘中实时价格；货币基金提供 7 日年化与万份收益。
"""
import json
import logging
import re
import time
from urllib import parse, request

from . import market

log = logging.getLogger("dividend.fund")

UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://fund.eastmoney.com/"}
F10_UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://fundf10.eastmoney.com/"}

CACHE_NAV = 600          # 场外净值 10 分钟
CACHE_YEAR = 6 * 3600    # 近一年涨幅 6 小时
CACHE_MONEY = 3600       # 货基指标 1 小时
CACHE_ETF = 15           # 场内行情 15 秒

_CACHE = {}


def _get_text(url, headers=None, timeout=15):
    req = request.Request(url, headers=headers or UA)
    with request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _get_json(url, headers=None, timeout=15):
    return json.loads(_get_text(url, headers, timeout))


def _f(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _cached(key, ttl, fetch, refresh=False):
    now = time.time()
    hit = _CACHE.get(key)
    if not refresh and hit and now - hit[0] < ttl:
        return hit[1]
    value = fetch()
    _CACHE[key] = (now, value)
    return value


def classify(code, name="", fund_type=""):
    """判断基金类型：场外 OTC / 场内 ETF / 货币 MONEY。"""
    text = (fund_type or "") + (name or "")
    if "货币" in text:
        return "MONEY"
    if str(code)[:2] in {"15", "16", "50", "51", "52", "56", "58"}:
        return "ETF"
    return "OTC"


def search(query, limit=10):
    """按代码或名称搜索基金。"""
    q = str(query or "").strip()
    if not q:
        return []
    url = "https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx?" + parse.urlencode(
        {"m": "1", "key": q})
    data = _get_json(url)
    out = []
    for row in data.get("Datas") or []:
        base = row.get("FundBaseInfo") or {}
        if row.get("CATEGORYDESC") != "基金" or not base:
            continue
        code = str(base.get("FCODE") or row.get("CODE") or "").strip()
        if not re.fullmatch(r"\d{6}", code):
            continue
        name = str(base.get("SHORTNAME") or row.get("NAME") or "").strip()
        ftype = str(base.get("FTYPE") or "").strip()
        out.append({
            "code": code,
            "name": name,
            "fund_type": ftype,
            "company": str(base.get("JJGS") or "").strip(),
            "nav": _f(base.get("DWJZ")),
            "nav_date": str(base.get("FSRQ") or "")[:10],
            "market": classify(code, name, ftype),
        })
        if len(out) >= limit:
            break
    out.sort(key=lambda x: (x["code"] != q, x["name"]))
    return out


def lookup(code):
    """按代码取一只基金的元数据；代码必须精确命中。"""
    code = str(code or "").strip()
    rows = search(code)
    for row in rows:
        if row["code"] == code:
            return row
    raise ValueError("未找到基金代码 %s" % code)


def latest_nav(code, refresh=False):
    """最新公布净值 + 净值日期。"""
    def fetch():
        url = "https://api.fund.eastmoney.com/f10/lsjz?" + parse.urlencode(
            {"fundCode": code, "pageIndex": "1", "pageSize": "2"})
        data = _get_json(url, headers=F10_UA)
        rows = (data.get("Data") or {}).get("LSJZList") or []
        if not rows:
            raise RuntimeError("未获取到基金净值")
        row = rows[0]
        return {
            "nav": _f(row.get("DWJZ")),
            "nav_date": str(row.get("FSRQ") or "")[:10],
            "change": _f(row.get("JZZZL")),
        }
    return _cached("nav:" + code, CACHE_NAV, fetch, refresh)


def _extract_array(text, name):
    match = re.search(r"var\s+%s\s*=\s*(\[.*?\])\s*;" % re.escape(name), text, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def _points(arr):
    points = []
    for item in arr or []:
        if isinstance(item, dict):
            ts, val = item.get("x"), item.get("y")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            ts, val = item[0], item[1]
        else:
            continue
        try:
            points.append((float(ts), float(val)))
        except (TypeError, ValueError):
            continue
    return points


def return_1y(code, refresh=False):
    """近 1 年涨幅（优先用累计净值，含分红），单位 %。"""
    def fetch():
        text = _get_text(
            "https://fund.eastmoney.com/pingzhongdata/%s.js" % code, timeout=20)
        points = _points(_extract_array(text, "Data_ACWorthTrend"))
        if len(points) < 2:
            points = _points(_extract_array(text, "Data_netWorthTrend"))
        if len(points) < 2:
            return None
        latest = points[-1]
        target = latest[0] - 365 * 86400000
        older = [p for p in points if p[0] <= target + 15 * 86400000]
        base = older[-1] if older else points[0]
        if base[1] <= 0:
            return None
        if (latest[0] - base[0]) / 86400000 < 300:
            return None
        return round((latest[1] / base[1] - 1) * 100, 2)
    return _cached("year:" + code, CACHE_YEAR, fetch, refresh)


def _last_value(text, name):
    arr = _extract_array(text, name)
    if not arr:
        return None
    for item in reversed(arr):
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            value = _f(item[1])
        elif isinstance(item, dict):
            value = _f(item.get("y"))
        else:
            value = None
        if value is not None:
            return value
    return None


def money_metrics(code, refresh=False):
    """货币基金：7 日年化（%）与万份收益（元）。"""
    def fetch():
        text = _get_text(
            "https://fund.eastmoney.com/pingzhongdata/%s.js" % code, timeout=20)
        return {
            "seven_day_yield": _last_value(text, "Data_sevenDaysYearIncome"),
            "wanfen": _last_value(text, "Data_millionCopiesIncome"),
        }
    return _cached("money:" + code, CACHE_MONEY, fetch, refresh)


def etf_quote(code, refresh=False):
    """场内 ETF/LOF 实时价格。"""
    def fetch():
        prices = market.fetch_tencent_prices([{"code": code}])
        item = prices.get(code) or {}
        price = item.get("price")
        if not price or price <= 0:
            raise RuntimeError("未获取到场内行情")
        return {
            "price": price,
            "pct": item.get("pct"),
            "quote_time": item.get("time"),
            "quote_name": item.get("name"),
        }
    return _cached("etf:" + code, CACHE_ETF, fetch, refresh)


def quote(fund, refresh=False):
    """返回单只基金的行情与市值。"""
    code = str(fund.get("code") or "")
    kind = str(fund.get("market") or "OTC")
    shares = float(fund.get("shares") or 0)
    out = {"code": code, "market": kind}

    if kind == "MONEY":
        out.update(money_metrics(code, refresh))
        out["price"] = 1.0
        out["value"] = round(shares, 2)
        out["return_1y"] = None
        return out

    if kind == "ETF":
        q = etf_quote(code, refresh)
        out.update(q)
        out["value"] = round(shares * q["price"], 2)
    else:
        nav = latest_nav(code, refresh)
        out.update({
            "price": nav["nav"],
            "nav": nav["nav"],
            "nav_date": nav["nav_date"],
            "change": nav.get("change"),
        })
        out["value"] = round(shares * (nav["nav"] or 0), 2)

    out["return_1y"] = return_1y(code, refresh)
    return out


def build(funds, refresh=False):
    """批量取基金行情；单只失败不影响其他。"""
    from . import store

    rows, errors = [], []
    for fund in funds:
        code = str(fund.get("code") or "")
        try:
            q = quote(fund, refresh)
            row = {**fund, **q}
            store.update_fund_quote(
                code,
                nav=q.get("nav"),
                nav_date=q.get("nav_date"),
                market_price=q.get("price") if q.get("market") == "ETF" else None,
                seven_day_yield=q.get("seven_day_yield"),
                wanfen=q.get("wanfen"),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("基金行情失败 %s：%s", code, exc)
            errors.append("%s %s：%s" % (fund.get("name") or "", code, exc))
            fallback = fund.get("nav") or fund.get("market_price") or 0
            row = {**fund, "price": fallback,
                   "value": round(float(fund.get("shares") or 0) * fallback, 2),
                   "return_1y": None, "error": str(exc)}
        rows.append(row)
    return {"ok": True, "funds": rows, "errors": errors,
            "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S")}
