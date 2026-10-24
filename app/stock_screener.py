# -*- coding: utf-8 -*-
"""沪深两市高股息低价股动态筛选。

流程：
1. 每天抓取一次全 A 股行情快照（东方财富估值分析，含收盘价/PE/PB/行业板块）
2. 批量抓取近 3 年分红方案：近 12 个月用于算股息率，3 年除息日期用于判断「临近分红」
3. 原始数据按日缓存到 SQLite；调整阈值/单价时本地即时重筛，无需重复联网
4. 初筛：单价 < 50 且 股息率 >= 阈值
5. 二次筛选：按「股票动态挑选规则整理.xlsx」的硬约束打标签、剔除明显风险标的
6. 默认仅保留股息率前 10，并提供行业 / 宏观因子 / 临近分红等过滤条件
"""
import datetime
import json
import logging
import threading
import time
from collections import Counter
from urllib import parse, request

from . import store

log = logging.getLogger("dividend.screener")

HIGH_YIELD_THRESHOLD = 0.045   # 股息率高：>= 4.5%
MAX_PRICE = 50.0               # 单价低于 50
MAX_YIELD_SANE = 0.15          # 超过 15% 疑似一次性特别分红，剔除
WARN_YIELD = 0.10              # 10%~15% 保留但提示
TOP_PICKS = 10                 # 默认展示数量
NEAR_DIVIDEND_DAYS = 90        # 距离下次典型分红 90 天内视为「临近分红」

MAX_AUTO_ATTEMPTS = 5          # 自动重试上限，超过后等用户手动「重试」
RETRY_BASE_SECONDS = 20        # 首次失败等 20s，之后 40/80/160/300s 退避
RETRY_MAX_SECONDS = 300

CACHE_KEY = "screener_cache"
_refresh_lock = threading.Lock()   # 同一时刻只允许一个抓取
_spawn_lock = threading.Lock()     # 保护「检查状态 + 起后台线程」这段
_state = {
    "refreshing": False,
    "attempts": 0,
    "last_error": "",
    "next_retry": 0.0,
}

UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}

RULES = {
    "title": "股票动态挑选规则",
    "source": "股票动态挑选规则整理.xlsx",
    "hard_rules": [
        {"name": "单行业上限", "rule": "任一行业 ≤ 35%"},
        {"name": "单一个股上限", "rule": "任一个股 ≤ 20%"},
        {"name": "宏观因子不重复", "rule": "能源链 / 地产链 / 利率链各只保留一个敞口"},
        {"name": "低价股优先", "rule": "低价股便于凑整百股，但不因价格低就给高权重"},
        {"name": "防御底仓", "rule": "公用事业 + 交通运输合计 ≥ 30%"},
        {"name": "现金缓冲", "rule": "保留 ≥ 1%~2% 现金"},
    ],
    "weight_rules": [
        "用「质量」打折，不用「股息率」加分：高息给上限，优质给下限以上。",
        "用「分红承诺强度」加权：写死分红比例下限的可往上靠。",
        "用「估值分位」逆向调节：PE/PB 处于自身十年偏低区间多配。",
        "风险最高的个股权重 = 能接受它归零的程度。",
    ],
    "target_structure": [
        {"industry": "银行", "weight": "35%", "stocks": "光大银行 20% + 江苏银行 15%"},
        {"industry": "基建", "weight": "20%", "stocks": "中国建筑"},
        {"industry": "交通运输", "weight": "15%", "stocks": "大秦铁路"},
        {"industry": "公用事业", "weight": "15%", "stocks": "浙能电力"},
        {"industry": "消费", "weight": "15%", "stocks": "双汇发展"},
    ],
    "rebalance": [
        "单只上涨超 25% / 行业超 40% → 减出多余部分，补到低配标的",
        "股息率 < 一年期定存 + 1.5% → 股价已涨透，考虑减半",
        "现金流覆盖不了分红 / 扣非连续两季下滑 / 分红率突然 ≥90% / 停派中期分红 → 直接砍仓",
        "每年固定复盘一次（避免频繁操作产生红利税）",
    ],
}


def _get_json(url, timeout=25):
    req = request.Request(url, headers=UA)
    with request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    return json.loads(raw)


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fetch_quotes():
    """抓取全 A 股最新交易日收盘快照。返回 (quotes, trade_date)。"""
    lookback = time.strftime("%Y-%m-%d", time.localtime(time.time() - 7 * 86400))
    params = {
        "reportName": "RPT_VALUEANALYSIS_DET",
        "columns": "ALL",
        "filter": "(TRADE_DATE>='%s')" % lookback,
        "pageNumber": "1",
        "pageSize": "10",
        "sortTypes": "-1",
        "sortColumns": "TRADE_DATE",
        "source": "WEB",
        "client": "WEB",
    }
    url = ("https://datacenter-web.eastmoney.com/api/data/v1/get?"
           + parse.urlencode(params))
    data = _get_json(url)
    rows = (data.get("result") or {}).get("data") or []
    if not rows:
        raise RuntimeError("估值分析接口无数据")
    trade_date = (rows[0].get("TRADE_DATE") or "")[:10]

    quotes = {}
    page = 1
    while True:
        params = {
            "reportName": "RPT_VALUEANALYSIS_DET",
            "columns": "ALL",
            "filter": "(TRADE_DATE='%s')" % trade_date,
            "pageNumber": str(page),
            "pageSize": "5000",
            "sortTypes": "1",
            "sortColumns": "SECURITY_CODE",
            "source": "WEB",
            "client": "WEB",
        }
        url = ("https://datacenter-web.eastmoney.com/api/data/v1/get?"
               + parse.urlencode(params))
        data = _get_json(url)
        result = data.get("result") or {}
        page_rows = result.get("data") or []
        for r in page_rows:
            code = str(r.get("SECURITY_CODE") or "").strip()
            if not code:
                continue
            quotes[code] = {
                "code": code,
                "name": str(r.get("SECURITY_NAME_ABBR") or "").strip(),
                "price": _f(r.get("CLOSE_PRICE")) or 0.0,
                "pe": _f(r.get("PE_TTM")),
                "pb": _f(r.get("PB_MRQ")),
                "board": str(r.get("BOARD_NAME") or "").strip(),
            }
        if not page_rows or len(quotes) >= (result.get("count") or 0):
            break
        page += 1
    return quotes, trade_date


def _fetch_dividends():
    """抓取近 3 年分红方案。

    返回 (agg, history)：
    - agg：近 12 个月每 10 股派息与股息率汇总（用于算股息率）
    - history：近 3 年每只股票的除息日期列表（用于判断典型分红月份）
    """
    cutoff12 = time.strftime("%Y-%m-%d", time.localtime(time.time() - 365 * 86400))
    cutoff3 = time.strftime("%Y-%m-%d", time.localtime(time.time() - 3 * 365 * 86400))
    agg = {}
    history = {}
    page = 1
    while page <= 120:
        params = {
            "reportName": "RPT_SHAREBONUS_DET",
            "columns": "ALL",
            "pageNumber": str(page),
            "pageSize": "500",
            "sortTypes": "-1",
            "sortColumns": "EX_DIVIDEND_DATE",
            "source": "WEB",
            "client": "WEB",
        }
        url = ("https://datacenter-web.eastmoney.com/api/data/v1/get?"
               + parse.urlencode(params))
        data = _get_json(url)
        rows = (data.get("result") or {}).get("data") or []
        if not rows:
            break
        stopped = False
        for r in rows:
            ex = (str(r.get("EX_DIVIDEND_DATE") or ""))[:10]
            if not ex:
                continue
            if ex < cutoff3:
                stopped = True
                break
            code = str(r.get("SECURITY_CODE") or "").strip()
            if not code:
                continue
            history.setdefault(code, []).append(ex)
            if ex >= cutoff12:
                per10 = _f(r.get("PRETAX_BONUS_RMB")) or 0.0
                ratio = _f(r.get("DIVIDENT_RATIO")) or 0.0
                a = agg.setdefault(code, {"per10": 0.0, "ratio": 0.0, "latest_ex": ""})
                a["per10"] += per10
                a["ratio"] += ratio
                if ex > a["latest_ex"]:
                    a["latest_ex"] = ex
        if stopped:
            break
        page += 1
    return agg, history


def _fetch_raw():
    quotes, trade_date = _fetch_quotes()
    dividends, history = _fetch_dividends()
    return {
        "trade_date": trade_date,
        "quotes": quotes,
        "dividends": dividends,
        "history": history,
    }


def _dividend_signal(ex_dates):
    """根据近 3 年除息日期，判断典型分红月份与是否临近分红。"""
    if not ex_dates:
        return {"months": [], "near": False, "note": ""}
    c = Counter(int(d[5:7]) for d in ex_dates)
    total = len(ex_dates)
    dominant = [m for m, n in c.items() if n >= 2 and n / total >= 0.5]
    if not dominant:
        top = c.most_common(1)[0]
        if top[1] >= 2 and top[1] / total >= 0.34:
            dominant = [top[0]]
    if not dominant:
        return {"months": [], "near": False, "note": "分红月份分散"}
    months = sorted(dominant)
    today = datetime.date.today()
    near = False
    for m in months:
        for yr in (today.year, today.year + 1):
            day = datetime.date(yr, m, 15)
            delta = (day - today).days
            if 0 <= delta <= NEAR_DIVIDEND_DAYS:
                near = True
                break
        if near:
            break
    label = "、".join("%d月" % m for m in months)
    note = label + ("（临近分红）" if near else "")
    return {"months": months, "near": near, "note": note}


def _tags(board):
    tags = []
    factor = None
    if any(k in board for k in ("煤炭", "石油", "石化", "油气", "燃气", "电力", "焦炭")):
        factor = "能源链"
    elif any(k in board for k in ("房地产", "建筑", "建材", "水泥", "玻璃", "钢铁", "家居", "家电", "装修")):
        factor = "地产链"
    elif any(k in board for k in ("银行", "保险", "证券", "金融", "信托")):
        factor = "利率链"
    if factor:
        tags.append(factor)
    if any(k in board for k in ("电力", "水务", "燃气", "环保", "环境", "公用事业",
                                "铁路", "公路", "港口", "航空", "物流", "交通运输", "高速")):
        tags.append("防御底仓")
    if "银行" in board:
        tags.append("银行")
    return tags, factor


SCORING = {
    "name": "优中选优评分（满分 100）",
    "items": [
        "股息率 25 分：6% 及以上给满",
        "连续分红年数 25 分：近 3 年连续分红给满",
        "估值 25 分：PE 15 分 + PB 10 分，越低分越高",
        "分红规律 15 分：典型分红月份明确者更高",
        "行业防御 10 分：公用事业/交通运输 10 分，银行 5 分",
        "高息警示 -5 分：股息率 10% 以上疑似一次性分红",
    ],
}


def _quality_score(item, ex_dates):
    y = item["yield"] or 0.0
    pe = item["pe"]
    pb = item["pb"]
    years = len({d[:4] for d in ex_dates})
    months = item["dividend_months"]
    has_warn = bool(item["warnings"])

    yield_score = min(y / 0.06, 1.0) * 25
    cont_score = min(years / 3.0, 1.0) * 25

    if pe is not None and pe > 0:
        pe_score = max(0.0, min(1.0, 1 - (pe - 5) / 25.0)) * 15
    else:
        pe_score = 0.0
    if pb is not None and pb > 0:
        pb_score = max(0.0, min(1.0, 1 - (pb - 0.5) / 2.5)) * 10
    else:
        pb_score = 0.0

    reg_score = 15 if months else 8
    if "防御底仓" in (item["tags"] or []):
        defens_score = 10.0
    elif "银行" in (item["tags"] or []):
        defens_score = 5.0
    else:
        defens_score = 0.0

    warn_penalty = 5.0 if has_warn else 0.0
    score = yield_score + cont_score + pe_score + pb_score + reg_score + defens_score - warn_penalty
    return round(max(0.0, min(100.0, score)), 1)


def _screen(quotes, dividends, history, yield_threshold, max_price):
    candidates = []
    excluded = []
    for code, q in quotes.items():
        price = q["price"]
        if price is None or price <= 0:
            continue
        d = dividends.get(code, {})
        per10 = d.get("per10") or 0.0
        ratio = d.get("ratio") or 0.0
        y = (per10 / 10.0 / price) if (price > 0 and per10 > 0) else ratio
        tags, factor = _tags(q["board"])
        sig = _dividend_signal(history.get(code, []))
        item = {
            "code": code,
            "name": q["name"],
            "price": round(price, 2),
            "yield": round(y, 4),
            "pe": q["pe"],
            "pb": q["pb"],
            "board": q["board"],
            "per10": round(per10, 4),
            "latest_ex": d.get("latest_ex") or "",
            "tags": tags,
            "factor": factor,
            "dividend_months": sig["months"],
            "near_dividend": sig["near"],
            "dividend_note": sig["note"],
            "warnings": [],
            "exclude_reason": "",
        }
        if price >= max_price or y < yield_threshold:
            continue
        reason = ""
        if "ST" in q["name"].upper() or "退" in q["name"]:
            reason = "ST / 退市风险"
        elif q["pe"] is None or q["pe"] <= 0:
            reason = "亏损或市盈率异常（质量打折）"
        elif y > MAX_YIELD_SANE:
            reason = "股息率异常偏高，疑似一次性特别分红"
        if reason:
            item["exclude_reason"] = reason
            excluded.append(item)
            continue
        if y >= WARN_YIELD:
            item["warnings"].append("股息率较高，需核对是否含一次性特别分红")
        if q["pb"] is not None and q["pb"] <= 0:
            item["warnings"].append("市净率为负")
        item["dividend_years"] = len({d[:4] for d in history.get(code, [])})
        item["quality_score"] = _quality_score(item, history.get(code, []))
        candidates.append(item)

    candidates.sort(key=lambda x: (-x["quality_score"], -x["yield"]))
    excluded.sort(key=lambda x: -x["yield"])
    return candidates, excluded


def _build_payload(raw, yield_threshold, max_price):
    quotes = raw.get("quotes") or {}
    dividends = raw.get("dividends") or {}
    history = raw.get("history") or {}
    trade_date = raw.get("trade_date") or ""
    candidates, excluded = _screen(quotes, dividends, history, yield_threshold, max_price)

    industry_count = {}
    for c in candidates:
        industry_count[c["board"]] = industry_count.get(c["board"], 0) + 1
    industry_count = dict(sorted(industry_count.items(), key=lambda x: -x[1]))

    industries = sorted({c["board"] for c in candidates if c["board"]})
    factors = ["能源链", "地产链", "利率链"]

    return {
        "ok": True,
        "trade_date": trade_date,
        "universe": len(quotes),
        "dividend_stocks": len(dividends),
        "yield_threshold": yield_threshold,
        "max_price": max_price,
        "top_picks": candidates[:TOP_PICKS],
        "candidates": candidates,
        "excluded": excluded,
        "industry_count": industry_count,
        "filters": {"industries": industries, "factors": factors},
        "scoring": SCORING,
        "rules": RULES,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cached": False,
    }


def get_rules():
    return RULES


def _is_fresh(raw, today):
    """当日缓存是否完整可用。"""
    return (isinstance(raw, dict) and raw.get("date") == today
            and isinstance(raw.get("quotes"), dict) and bool(raw.get("quotes"))
            and isinstance(raw.get("dividends"), dict)
            and isinstance(raw.get("history"), dict))


def _has_usable_cache(raw):
    """即使不是今天的，只要有完整原料就能先给页面看旧结果。"""
    return (isinstance(raw, dict)
            and isinstance(raw.get("quotes"), dict) and bool(raw.get("quotes"))
            and isinstance(raw.get("dividends"), dict)
            and isinstance(raw.get("history"), dict))


def _fetch_and_store(today):
    data = _fetch_raw()
    store.save_json(CACHE_KEY, {"date": today, **data})
    _state.update({"attempts": 0, "last_error": "", "next_retry": 0.0})
    return {"date": today, **data}


def _record_failure(exc):
    """记录失败并算出下一次自动重试的退避时间（秒）。"""
    attempts = int(_state.get("attempts", 0)) + 1
    delay = min(RETRY_BASE_SECONDS * (2 ** (attempts - 1)), RETRY_MAX_SECONDS)
    _state.update({
        "attempts": attempts,
        "last_error": str(exc) or exc.__class__.__name__,
        "next_retry": time.time() + delay,
    })
    return delay


def _failure_payload(raw, threshold, price_max, error, retry_in_ms=None, exhausted=False):
    """失败时的返回：有旧缓存就带上旧结果，页面至少还能看。"""
    if _has_usable_cache(raw):
        payload = _build_payload(raw, threshold, price_max)
        payload.update({"ok": True, "cached": True, "stale": True, "error": error})
    else:
        payload = {
            "ok": False, "error": error, "rules": RULES,
            "cached": False, "stale": True,
            "yield_threshold": threshold, "max_price": price_max,
            "top_picks": [], "candidates": [], "excluded": [],
            "industry_count": {},
            "filters": {"industries": [], "factors": ["能源链", "地产链", "利率链"]},
            "scoring": SCORING,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
    if retry_in_ms is not None:
        payload["retry_in_ms"] = int(retry_in_ms)
    payload["retry_exhausted"] = bool(exhausted)
    payload["attempts"] = _state.get("attempts", 0)
    return payload


def _refreshing_payload(raw, threshold, price_max):
    return {
        "ok": True,
        "refreshing": True,
        "retry_in_ms": 2500,
        "rules": RULES,
        "cached": _has_usable_cache(raw),
        "last_error": _state.get("last_error", ""),
        "yield_threshold": threshold,
        "max_price": price_max,
    }


def _start_background_refresh():
    """起一个后台抓取线程；已有线程在跑时直接返回。"""
    with _spawn_lock:
        if _state["refreshing"]:
            return False
        _state["refreshing"] = True

        def worker():
            try:
                with _refresh_lock:
                    _fetch_and_store(time.strftime("%Y-%m-%d"))
            except Exception as exc:  # noqa: BLE001
                log.exception("动态选股后台刷新失败")
                _record_failure(exc)
            finally:
                _state["refreshing"] = False

        threading.Thread(target=worker, daemon=True).start()
        return True


def get_screener(refresh=False, yield_threshold=None, max_price=None):
    threshold = float(yield_threshold) if yield_threshold else HIGH_YIELD_THRESHOLD
    price_max = float(max_price) if max_price else MAX_PRICE
    today = time.strftime("%Y-%m-%d")

    raw = store.load_json(CACHE_KEY, None)
    fresh = _is_fresh(raw, today)

    if refresh:
        # 手动刷新始终可用，但同一时刻只跑一个抓取；失败也计入退避。
        if not _refresh_lock.acquire(blocking=False):
            return _refreshing_payload(raw, threshold, price_max)
        _state["refreshing"] = True
        try:
            raw = _fetch_and_store(today)
            fresh = True
        except Exception as exc:  # noqa: BLE001
            log.exception("动态选股抓取失败")
            delay = _record_failure(exc)
            return _failure_payload(
                raw, threshold, price_max, str(exc),
                retry_in_ms=int(delay * 1000),
                exhausted=_state["attempts"] >= MAX_AUTO_ATTEMPTS)
        finally:
            _state["refreshing"] = False
            _refresh_lock.release()

    if not fresh:
        if _state["refreshing"]:
            return _refreshing_payload(raw, threshold, price_max)
        if _state["attempts"] >= MAX_AUTO_ATTEMPTS:
            return _failure_payload(
                raw, threshold, price_max,
                _state.get("last_error") or "多次自动更新失败",
                exhausted=True)
        wait = float(_state.get("next_retry", 0.0)) - time.time()
        if wait > 0:
            return _failure_payload(
                raw, threshold, price_max,
                _state.get("last_error") or "上次更新失败",
                retry_in_ms=int(wait * 1000))
        _start_background_refresh()
        return _refreshing_payload(raw, threshold, price_max)

    payload = _build_payload(raw, threshold, price_max)
    payload["cached"] = True
    return payload