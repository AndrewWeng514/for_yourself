# -*- coding: utf-8 -*-
"""行情与分红数据抓取。"""
import json
import re
import time
from urllib import request, parse


def fetch_text(url, timeout=5.0, encoding=None):
    req = request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        return data.decode(encoding) if encoding else data.decode("utf-8", "replace")


def _get_json(url, timeout=10.0):
    return json.loads(fetch_text(url, timeout=timeout))


def market_prefix(code):
    """根据 A 股代码推断市场前缀。"""
    c = str(code).strip()
    if c.startswith(("6", "9", "5")):
        return "sh"
    if c.startswith(("4", "8")):
        return "bj"
    return "sz"


def _safe_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_tencent_prices(stocks):
    """腾讯实时行情：返回 {code: {price, change, pct, time, name}}。"""
    symbols = [market_prefix(s["code"]) + s["code"] for s in stocks]
    url = "https://qt.gtimg.cn/q=" + ",".join(symbols)
    text = fetch_text(url, timeout=5.0, encoding="gbk")
    result = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        parts = line.split("=", 1)
        if len(parts) != 2:
            continue
        var = parts[0].strip()
        payload = parts[1].strip().strip(";").strip('"')
        fields = payload.split("~")
        if len(fields) < 33:
            continue
        m = re.search(r"([a-z]{2})(\d{6})", var)
        if not m:
            continue
        code = m.group(2)
        try:
            price = float(fields[3])
        except (ValueError, IndexError):
            price = None
        result[code] = {
            "name": fields[1],
            "price": price,
            "change": _safe_float(fields[31]),
            "pct": _safe_float(fields[32]),
            "time": fields[30],
        }
    return result


def fetch_eastmoney_dividends(code):
    """东方财富分红数据：返回最近 12 个月每 10 股派息总和与最新除息日。"""
    cb = "cb_%d" % int(time.time() * 1000)
    params = {
        "reportName": "RPT_SHAREBONUS_DET",
        "columns": "ALL",
        "filter": '(SECURITY_CODE="%s")' % code,
        "pageNumber": "1",
        "pageSize": "50",
        "sortTypes": "-1",
        "sortColumns": "EX_DIVIDEND_DATE",
        "source": "WEB",
        "client": "WEB",
        "cb": cb,
    }
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get?" + parse.urlencode(params)
    text = fetch_text(url, timeout=5.0)
    if text.lstrip().startswith("{"):
        payload = text
    else:
        start = text.find("(")
        end = text.rfind(")")
        payload = text[start + 1:end] if (start != -1 and end != -1) else text
    data = json.loads(payload)
    if not data.get("success"):
        return {"per10": 0.0, "ex_date": None, "records": 0}
    records = data.get("result", {}).get("data") or []
    cutoff = time.time() - 365 * 86400
    per10 = 0.0
    latest_ex = None
    for rec in records:
        ex = rec.get("EX_DIVIDEND_DATE") or ""
        if ex:
            try:
                ts = time.mktime(time.strptime(ex[:10], "%Y-%m-%d"))
            except ValueError:
                continue
            if ts < cutoff:
                continue
            try:
                per10 += float(rec.get("PRETAX_BONUS_RMB") or 0)
            except (TypeError, ValueError):
                continue
            if latest_ex is None or ex > latest_ex:
                latest_ex = ex[:10]
    return {"per10": per10, "ex_date": latest_ex, "records": len(records)}


def _search_astock(query):
    """按代码或名称搜索 A 股，返回 {code, name} 或 None。"""
    params = {
        "input": query,
        "type": "14",
        "token": "D43BF722C8E33BDC906FB84D85E326E8",
        "count": "10",
    }
    url = "https://searchapi.eastmoney.com/api/suggest/get?" + parse.urlencode(params)
    data = _get_json(url, timeout=10)
    rows = (data.get("QuotationCodeTable") or {}).get("Data") or []
    for row in rows:
        code = str(row.get("Code") or "")
        if row.get("Classify") == "AStock" and re.fullmatch(r"\d{6}", code):
            return {"code": code, "name": str(row.get("Name") or "").strip()}
    return None


def lookup_stock(query):
    """按股票代码或名称查询实时价格与股息率。"""
    q = str(query or "").strip()
    if not q:
        raise ValueError("请输入股票代码或名称")
    found = None
    try:
        found = _search_astock(q)
    except Exception:  # noqa: BLE001
        found = None
    if not found and re.fullmatch(r"\d{6}", q):
        found = {"code": q, "name": ""}
    if not found:
        raise ValueError("未找到匹配的 A 股")

    code = found["code"]
    prices = fetch_tencent_prices([{"code": code}])
    p = prices.get(code) or {}
    price = p.get("price")
    if not price or price <= 0:
        raise ValueError("未获取到 %s 的实时行情" % code)
    dividend = fetch_eastmoney_dividends(code)
    per10 = dividend.get("per10")
    y = (per10 / 10.0 / price) if per10 is not None else None
    return {
        "ok": True,
        "code": code,
        "name": p.get("name") or found["name"] or code,
        "price": round(price, 4),
        "yield": round(y, 6) if y is not None else None,
        "per10": per10,
        "ex_date": dividend.get("ex_date"),
        "is_live_price": True,
        "is_live_yield": per10 is not None,
    }


def build_quotes(stocks):
    """合并腾讯价格 + 东方财富分红，计算最新价与参考股息率。"""
    quotes = {}
    errors = []
    try:
        prices = fetch_tencent_prices(stocks)
    except Exception as exc:  # noqa: BLE001
        prices = {}
        errors.append("价格接口不可用：%s" % exc)

    dividends = {}
    for s in stocks:
        code = s["code"]
        try:
            dividends[code] = fetch_eastmoney_dividends(code)
        except Exception as exc:  # noqa: BLE001
            dividends[code] = {"per10": None, "ex_date": None, "records": 0}
            errors.append("分红接口不可用(%s)：%s" % (code, exc))

    live = False
    for s in stocks:
        code = s["code"]
        p = prices.get(code, {})
        d = dividends.get(code, {})
        price = p.get("price")
        per10 = d.get("per10")
        live_price = price is not None and price > 0
        live_yield = live_price and per10 is not None
        if live_yield:
            y = per10 / 10.0 / price
        else:
            y = None
        if live_price:
            live = True
        quotes[code] = {
            "price": round(price, 4) if live_price else None,
            "change": p.get("change"),
            "pct": p.get("pct"),
            "time": p.get("time"),
            "quote_name": p.get("name"),
            "yield": round(y, 6) if y is not None else None,
            "per10": per10,
            "ex_date": d.get("ex_date"),
            "is_live_price": live_price,
            "is_live_yield": live_yield,
        }
    return {"live": live, "quotes": quotes, "errors": errors,
            "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S")}
