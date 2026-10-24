# -*- coding: utf-8 -*-
"""资产趋势：只从 SQLite asset_snapshots 读取，输出周/月/季/年走向。

- 数据源仅为数据库，不再读取任何本地笔记文件
- 同一周多次录入取 recorded_at 最晚的一次
- 周/月/季/年只展示当前年份；years 保留全部年份用于「按年」
"""
import re
import time

from . import store


def _read_snapshot_points():
    out = []
    for s in store.load_snapshots():
        week = s.get("week") or ""
        year = int(week[:4]) if week[:4].isdigit() else 0
        out.append({
            "week": week,
            "year": year,
            "month": s.get("month") or "",
            "net": s.get("net") or 0.0,
            "accounts": s.get("accounts") or {},
            "items": s.get("items") or [],
            "ts": s.get("recorded_at") or "",
            "source": "database",
        })
    return out


def _merge(points):
    """按周合并；同一周取 recorded_at 最晚的一次。"""
    by_week = {}
    for p in points:
        week = p.get("week") or ""
        if not week:
            continue
        items = store.normalize_items(p.get("items") or [])
        if not items:
            items = store.items_from_accounts(p.get("accounts") or {})
        p["items"] = items
        accounts = {}
        for item in items:
            if item["category"] == "asset":
                accounts[item["name"]] = round(
                    accounts.get(item["name"], 0.0) + item["amount"], 2)
        liabilities = sum(
            item["amount"] for item in items if item["category"] == "liability")
        accounts["负债"] = round(-liabilities, 2)
        p["accounts"] = accounts
        p["net"] = round(
            sum(item["amount"] for item in items if item["category"] == "asset")
            - liabilities, 2)
        cur = by_week.get(week)
        if cur is None or (p.get("ts") or "") > (cur.get("ts") or ""):
            by_week[week] = p
    weeks = sorted(by_week.values(),
                   key=lambda x: (x["year"], int(x["week"][-2:])))
    prev = None
    for w in weeks:
        w["change"] = round(w["net"] - prev["net"], 2) if prev else None
        prev = w
    return weeks


def _quarter_of(month):
    m = re.match(r"^(\d{4})-(\d{2})$", month or "")
    if not m:
        return None
    year, mm = int(m.group(1)), int(m.group(2))
    return "%d-Q%d" % (year, (mm - 1) // 3 + 1)


def _build_levels(weeks):
    months = {}
    for w in weeks:
        if not w["month"]:
            continue
        months.setdefault(w["month"], []).append(w)

    month_list = []
    prev_net = None
    for month in sorted(months):
        ws = months[month]
        last = ws[-1]
        first = ws[0]
        net = last["net"]
        month_list.append({
            "month": month,
            "quarter": _quarter_of(month),
            "net": net,
            "first_net": first["net"],
            "month_delta": round(net - first["net"], 2),
            "change": round(net - prev_net, 2) if prev_net is not None else None,
            "weeks": [w["week"] for w in ws],
            "last_week": last["week"],
        })
        prev_net = net

    quarters = {}
    for m in month_list:
        if not m["quarter"]:
            continue
        quarters.setdefault(m["quarter"], []).append(m)
    quarter_list = []
    prev_net = None
    for q in sorted(quarters):
        ms = quarters[q]
        last = ms[-1]
        net = last["net"]
        quarter_list.append({
            "quarter": q,
            "months": [m["month"] for m in ms],
            "net": net,
            "first_net": ms[0]["first_net"],
            "change": round(net - prev_net, 2) if prev_net is not None else None,
            "last_week": last["last_week"],
        })
        prev_net = net

    year = None
    if month_list:
        first_month = month_list[0]
        last_month = month_list[-1]
        year = {
            "year": last_month["month"][:4],
            "net": last_month["net"],
            "first_net": first_month["first_net"],
            "change": round(last_month["net"] - first_month["first_net"], 2),
            "last_week": last_month["last_week"],
            "first_week": first_month["weeks"][0],
        }
    return month_list, quarter_list, year


def build_trend():
    all_weeks = _merge(_read_snapshot_points())

    current_year = int(time.strftime("%Y"))
    cur = [w for w in all_weeks if w["year"] == current_year]
    months, quarters, year = _build_levels(cur)

    years = []
    prev_net = None
    for y in sorted({w["year"] for w in all_weeks}):
        yw = [w for w in all_weeks if w["year"] == y]
        last = yw[-1]
        years.append({
            "year": str(y),
            "net": last["net"],
            "change": round(last["net"] - prev_net, 2) if prev_net is not None else None,
            "last_week": last["week"],
        })
        prev_net = last["net"]

    return {
        "ok": True,
        "source": "SQLite asset_snapshots",
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "current_year": current_year,
        "account_labels": list(store.ACCOUNT_NAMES),
        "weeks": cur,
        "all_weeks": [
            {"week": w["week"], "net": w["net"],
             "source": w["source"], "ts": w["ts"]}
            for w in all_weeks
        ],
        "months": months,
        "quarters": quarters,
        "year": year,
        "years": years,
    }
