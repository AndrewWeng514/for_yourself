# -*- coding: utf-8 -*-
"""数据存储：SQLite（标准库 sqlite3，零第三方依赖）。

- 表 stocks：股票配置（支持增删改，含实仓股数 shares_held）
- 表 settings：全局设置（总本金等）
- 表 asset_snapshots：手动录入的资产快照（周/月/季/年趋势数据源）
- 首次使用：若 stocks 表为空，从 data/stocks.json（旧数据）或 Excel 模板导入。
"""
import json
import sqlite3
from datetime import datetime

from . import paths

DB_FILE = paths.DATA_DIR / "app.db"
_JSON_FILE = paths.DATA_DIR / "stocks.json"
SEED_KEY = "seeded"  # 首次种子完成的标记：置位后即使股票被删空也不再重新导入

ACCOUNT_NAMES = ["中信股票", "支付宝", "招商基金", "流动备用金", "招商固定", "负债"]
LEGACY_FIELDS = {
    "中信股票": "zx_stock",
    "支付宝": "zfb",
    "招商基金": "zs_fund",
    "流动备用金": "flow_cash",
    "招商固定": "zs_fixed",
    "负债": "debt",
}


def _connect():
    conn = sqlite3.connect(str(DB_FILE))
    conn.row_factory = sqlite3.Row
    return conn


def _init_db(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS settings ("
        " key TEXT PRIMARY KEY,"
        " value TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS stocks ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " sort INTEGER NOT NULL DEFAULT 0,"
        " name TEXT NOT NULL DEFAULT '',"
        " code TEXT NOT NULL DEFAULT '',"
        " weight REAL NOT NULL DEFAULT 0,"
        " price REAL NOT NULL DEFAULT 0,"
        " ref_yield REAL NOT NULL DEFAULT 0,"
        " shares_held REAL NOT NULL DEFAULT 0"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS asset_snapshots ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " recorded_at TEXT NOT NULL,"
        " week TEXT NOT NULL DEFAULT '',"
        " month TEXT NOT NULL DEFAULT '',"
        " zx_stock REAL NOT NULL DEFAULT 0,"
        " zfb REAL NOT NULL DEFAULT 0,"
        " zs_fund REAL NOT NULL DEFAULT 0,"
        " flow_cash REAL NOT NULL DEFAULT 0,"
        " zs_fixed REAL NOT NULL DEFAULT 0,"
        " debt REAL NOT NULL DEFAULT 0,"
        " net REAL NOT NULL DEFAULT 0,"
        " items_json TEXT NOT NULL DEFAULT '[]'"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS funds ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " sort INTEGER NOT NULL DEFAULT 0,"
        " code TEXT NOT NULL DEFAULT '',"
        " name TEXT NOT NULL DEFAULT '',"
        " fund_type TEXT NOT NULL DEFAULT '',"
        " market TEXT NOT NULL DEFAULT 'OTC',"
        " shares REAL NOT NULL DEFAULT 0,"
        " nav REAL NOT NULL DEFAULT 0,"
        " nav_date TEXT NOT NULL DEFAULT '',"
        " market_price REAL NOT NULL DEFAULT 0,"
        " seven_day_yield REAL NOT NULL DEFAULT 0,"
        " wanfen REAL NOT NULL DEFAULT 0,"
        " updated_at TEXT NOT NULL DEFAULT ''"
        ")"
    )
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(stocks)").fetchall()]
    if "shares_held" not in cols:
        conn.execute(
            "ALTER TABLE stocks ADD COLUMN shares_held REAL NOT NULL DEFAULT 0"
        )
    snap_cols = [
        r["name"] for r in conn.execute("PRAGMA table_info(asset_snapshots)").fetchall()
    ]
    if "items_json" not in snap_cols:
        conn.execute(
            "ALTER TABLE asset_snapshots ADD COLUMN items_json TEXT NOT NULL DEFAULT '[]'"
        )
    conn.commit()


def _get_setting(conn, key, default=""):
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row else default


def _set_setting(conn, key, value):
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def _read_legacy_json():
    if not _JSON_FILE.exists():
        return None
    try:
        with open(_JSON_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("stocks"), list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _seed(conn):
    """stocks 表为空时，从旧 JSON 或 Excel 导入。"""
    data = _read_legacy_json()
    source = "stocks.json"
    if data is None:
        from .excel_reader import load_config
        data = load_config()
        source = "excel"
    total = float(data.get("total_principal") or 0)
    stocks = data.get("stocks") or []
    with conn:
        for i, s in enumerate(stocks):
            conn.execute(
                "INSERT INTO stocks(sort, name, code, weight, price, ref_yield, shares_held) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (i, str(s.get("name") or ""), str(s.get("code") or ""),
                 float(s.get("weight") or 0), float(s.get("price") or 0),
                 float(s.get("ref_yield") or 0), float(s.get("shares_held") or 0)),
            )
        _set_setting(conn, "total_principal", total)
        _set_setting(conn, SEED_KEY, "1")
    return {"total_principal": total, "stocks": list(stocks), "source": source}


def load_config():
    """读取配置：优先 SQLite；仅在从未种子过且表为空时导入一次。"""
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    try:
        _init_db(conn)
        rows = conn.execute(
            "SELECT name, code, weight, price, ref_yield, shares_held "
            "FROM stocks ORDER BY sort, id"
        ).fetchall()
        if not rows:
            # 已经经历过首次种子：保持空列表，绝不把删掉的股票重新导入。
            if _get_setting(conn, SEED_KEY, "") == "1":
                total = float(_get_setting(conn, "total_principal", "0") or 0)
                cash = float(_get_setting(conn, "stock_cash", "0") or 0)
                return {"total_principal": total, "stock_cash": cash, "stocks": []}
            seeded = _seed(conn)
            return {
                "total_principal": seeded["total_principal"],
                "stock_cash": 0.0,
                "stocks": seeded["stocks"],
            }
        if _get_setting(conn, SEED_KEY, "") != "1":
            # 老库升级：已有股票视为已种子，避免以后删空时复活。
            with conn:
                _set_setting(conn, SEED_KEY, "1")
        total = float(_get_setting(conn, "total_principal", "0") or 0)
        cash = float(_get_setting(conn, "stock_cash", "0") or 0)
        stocks = [{
            "name": r["name"], "code": r["code"], "weight": r["weight"],
            "price": r["price"], "ref_yield": r["ref_yield"],
            "shares_held": r["shares_held"],
        } for r in rows]
        return {"total_principal": total, "stock_cash": cash, "stocks": stocks}
    finally:
        conn.close()


def save_config(config):
    """整体保存股票配置与总本金（事务替换）。"""
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    try:
        _init_db(conn)
        stocks = config.get("stocks") or []
        with conn:
            conn.execute("DELETE FROM stocks")
            for i, s in enumerate(stocks):
                conn.execute(
                    "INSERT INTO stocks(sort, name, code, weight, price, ref_yield, shares_held) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?)",
                    (i, str(s.get("name") or ""), str(s.get("code") or ""),
                     float(s.get("weight") or 0), float(s.get("price") or 0),
                     float(s.get("ref_yield") or 0), float(s.get("shares_held") or 0)),
                )
            _set_setting(conn, "total_principal",
                         float(config.get("total_principal") or 0))
            cash = config.get("stock_cash")
            if cash is None:
                cash = float(_get_setting(conn, "stock_cash", "0") or 0)
            _set_setting(conn, "stock_cash", max(0.0, float(cash or 0)))
            _set_setting(conn, SEED_KEY, "1")
    finally:
        conn.close()
    return config


def add_stock(stock):
    """新增一只股票到配置（代码已存在则跳过）。返回 {ok, exists}。"""
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    try:
        _init_db(conn)
        code = str(stock.get("code") or "").strip()
        name = str(stock.get("name") or "").strip()
        exists = False
        if code:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM stocks WHERE code = ?", (code,)
            ).fetchone()
            exists = row["n"] > 0
        if exists:
            return {"ok": False, "exists": True}
        row = conn.execute("SELECT COALESCE(MAX(sort), -1) AS m FROM stocks").fetchone()
        sort = int(row["m"]) + 1
        with conn:
            conn.execute(
                "INSERT INTO stocks(sort, name, code, weight, price, ref_yield, shares_held) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (sort, name, code,
                 float(stock.get("weight") or 0), float(stock.get("price") or 0),
                 float(stock.get("ref_yield") or 0), float(stock.get("shares_held") or 0)),
            )
            _set_setting(conn, SEED_KEY, "1")
        return {"ok": True, "exists": False}
    finally:
        conn.close()


def update_stock_cash(value):
    """只更新股票账户现金，返回规范化后的金额。"""
    try:
        cash = max(0.0, float(value or 0))
    except (TypeError, ValueError):
        cash = 0.0
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    try:
        _init_db(conn)
        with conn:
            _set_setting(conn, "stock_cash", cash)
            _set_setting(conn, SEED_KEY, "1")
        return cash
    finally:
        conn.close()


def update_shares(shares):
    """只更新实仓股数，不覆盖名称、价格等其他字段。"""
    if not isinstance(shares, dict):
        return 0
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    try:
        _init_db(conn)
        updated = 0
        with conn:
            for code, value in shares.items():
                try:
                    amount = float(value or 0)
                except (TypeError, ValueError):
                    amount = 0.0
                cur = conn.execute(
                    "UPDATE stocks SET shares_held = ? WHERE code = ?",
                    (amount, str(code)),
                )
                updated += cur.rowcount
        return updated
    finally:
        conn.close()


def delete_stock(code):
    """删除指定股票，返回删除行数。"""
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    try:
        _init_db(conn)
        with conn:
            cur = conn.execute("DELETE FROM stocks WHERE code = ?", (str(code),))
            _set_setting(conn, SEED_KEY, "1")
        return cur.rowcount
    finally:
        conn.close()


FUND_FIELDS = (
    "code", "name", "fund_type", "market", "shares", "nav", "nav_date",
    "market_price", "seven_day_yield", "wanfen", "updated_at",
)


def _row_to_fund(row):
    return {key: row[key] for key in FUND_FIELDS if key in row.keys()}


def load_funds():
    """读取基金实仓。"""
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    try:
        _init_db(conn)
        rows = conn.execute(
            "SELECT code, name, fund_type, market, shares, nav, nav_date, "
            "market_price, seven_day_yield, wanfen, updated_at "
            "FROM funds ORDER BY sort, id"
        ).fetchall()
        return [_row_to_fund(r) for r in rows]
    finally:
        conn.close()


def add_fund(data):
    """新增基金；代码已存在则跳过。"""
    data = data or {}
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    code = str(data.get("code") or "").strip()
    if not code:
        raise ValueError("缺少基金代码")
    conn = _connect()
    try:
        _init_db(conn)
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM funds WHERE code = ?", (code,)
        ).fetchone()
        if row["n"] > 0:
            return {"ok": False, "exists": True}
        row = conn.execute("SELECT COALESCE(MAX(sort), -1) AS m FROM funds").fetchone()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with conn:
            conn.execute(
                "INSERT INTO funds(sort, code, name, fund_type, market, shares, "
                "nav, nav_date, market_price, seven_day_yield, wanfen, updated_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (int(row["m"]) + 1, code,
                 str(data.get("name") or ""), str(data.get("fund_type") or ""),
                 str(data.get("market") or "OTC"), float(data.get("shares") or 0),
                 float(data.get("nav") or 0), str(data.get("nav_date") or ""),
                 float(data.get("market_price") or 0),
                 float(data.get("seven_day_yield") or 0),
                 float(data.get("wanfen") or 0), now),
            )
        return {"ok": True, "exists": False}
    finally:
        conn.close()


def update_fund_shares(shares):
    """只更新基金份额。"""
    if not isinstance(shares, dict):
        return 0
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    try:
        _init_db(conn)
        updated = 0
        with conn:
            for code, value in shares.items():
                try:
                    amount = float(value or 0)
                except (TypeError, ValueError):
                    amount = 0.0
                cur = conn.execute(
                    "UPDATE funds SET shares = ? WHERE code = ?",
                    (amount, str(code)),
                )
                updated += cur.rowcount
        return updated
    finally:
        conn.close()


def update_fund_quote(code, **fields):
    """把最新净值/行情写回 funds，作为离线兜底。"""
    allowed = ("nav", "nav_date", "market_price", "seven_day_yield", "wanfen")
    sets, values = [], []
    for key in allowed:
        value = fields.get(key)
        if value is None:
            continue
        sets.append(key + " = ?")
        values.append(value)
    if not sets:
        return 0
    sets.append("updated_at = ?")
    values.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    values.append(str(code))
    conn = _connect()
    try:
        _init_db(conn)
        with conn:
            cur = conn.execute(
                "UPDATE funds SET " + ", ".join(sets) + " WHERE code = ?", values)
        return cur.rowcount
    finally:
        conn.close()


def delete_fund(code):
    """删除指定基金，返回删除行数。"""
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    try:
        _init_db(conn)
        with conn:
            cur = conn.execute("DELETE FROM funds WHERE code = ?", (str(code),))
        return cur.rowcount
    finally:
        conn.close()


def _iso_week(recorded_at):
    try:
        dt = datetime.strptime(str(recorded_at)[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        dt = datetime.now()
    y, w, _ = dt.isocalendar()
    return "%d-W%02d" % (y, w), dt.strftime("%Y-%m")


def normalize_items(items):
    """把资产/负债模块整理成统一结构：category 为 asset 或 liability。"""
    out = []
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category") or "").strip().lower()
        if category in ("asset", "assets", "资产"):
            category = "asset"
        elif category in ("liability", "liabilities", "debt", "负债"):
            category = "liability"
        else:
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        try:
            amount = abs(float(item.get("amount") or 0))
        except (TypeError, ValueError):
            amount = 0.0
        out.append({
            "category": category,
            "name": name,
            "amount": round(amount, 2),
        })
    return out


def items_from_accounts(accounts):
    """把旧版固定账户字典转换成资产/负债模块列表。"""
    if not isinstance(accounts, dict):
        return []
    items = []
    for name in ACCOUNT_NAMES[:-1]:
        if name in accounts:
            items.append({
                "category": "asset",
                "name": name,
                "amount": round(abs(float(accounts.get(name) or 0)), 2),
            })
    if "负债" in accounts:
        items.append({
            "category": "liability",
            "name": "负债",
            "amount": round(abs(float(accounts.get("负债") or 0)), 2),
        })
    return items


def _snapshot_net(items):
    assets = sum(i["amount"] for i in items if i["category"] == "asset")
    liabilities = sum(i["amount"] for i in items if i["category"] == "liability")
    return round(assets - liabilities, 2)


def _legacy_values(items):
    values = {name: 0.0 for name in ACCOUNT_NAMES}
    for item in items:
        field = LEGACY_FIELDS.get(item["name"])
        if field:
            values[item["name"]] += item["amount"]
    return values


def _legacy_accounts(items):
    accounts = {}
    for item in items:
        if item["category"] == "asset":
            accounts[item["name"]] = round(
                accounts.get(item["name"], 0.0) + item["amount"], 2
            )
    liabilities = sum(
        i["amount"] for i in items if i["category"] == "liability"
    )
    accounts["负债"] = round(-liabilities, 2)
    return accounts


def _row_to_snapshot(row):
    items = []
    try:
        raw = row["items_json"] or "[]"
        items = normalize_items(json.loads(raw))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        items = []
    if not items:
        accounts = {}
        for name in ACCOUNT_NAMES:
            field = LEGACY_FIELDS[name]
            accounts[name] = row[field] or 0.0
        items = items_from_accounts(accounts)
    return {
        "recorded_at": row["recorded_at"],
        "week": row["week"],
        "month": row["month"],
        "items": items,
        "accounts": _legacy_accounts(items),
        "net": round(float(row["net"] or _snapshot_net(items)), 2),
    }


def add_snapshot(items, recorded_at=None):
    """保存一次手动资产快照。

    items: [{category: 'asset'|'liability', name, amount}]；
    也兼容旧版 {账户名: 金额} 字典。
    """
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if isinstance(items, dict):
        items = items_from_accounts(items)
    items = normalize_items(items)
    if not items:
        raise ValueError("请至少填写一个资产或负债模块")
    now = recorded_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    week, month = _iso_week(now)
    values = _legacy_values(items)
    net = _snapshot_net(items)
    conn = _connect()
    try:
        _init_db(conn)
        with conn:
            cur = conn.execute(
                "INSERT INTO asset_snapshots(recorded_at, week, month, "
                "zx_stock, zfb, zs_fund, flow_cash, zs_fixed, debt, net, items_json) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (now, week, month,
                 values["中信股票"], values["支付宝"], values["招商基金"],
                 values["流动备用金"], values["招商固定"], values["负债"],
                 net, json.dumps(items, ensure_ascii=False)),
            )
        return {
            "id": cur.lastrowid, "recorded_at": now, "week": week, "month": month,
            "items": items, "accounts": _legacy_accounts(items), "net": net,
        }
    finally:
        conn.close()


def load_snapshots():
    """读取全部手动资产快照（按时间升序）。"""
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    try:
        _init_db(conn)
        rows = conn.execute(
            "SELECT recorded_at, week, month, zx_stock, zfb, zs_fund, "
            "flow_cash, zs_fixed, debt, net, items_json "
            "FROM asset_snapshots ORDER BY recorded_at"
        ).fetchall()
        return [_row_to_snapshot(r) for r in rows]
    finally:
        conn.close()


def load_latest_snapshot():
    """读取最后一次手动资产快照；没有则返回 None。"""
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    try:
        _init_db(conn)
        row = conn.execute(
            "SELECT recorded_at, week, month, zx_stock, zfb, zs_fund, "
            "flow_cash, zs_fixed, debt, net, items_json FROM asset_snapshots "
            "ORDER BY recorded_at DESC, id DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        return _row_to_snapshot(row)
    finally:
        conn.close()


def delete_latest_snapshot():
    """删除最后一次手动资产快照，返回被删记录（没有则返回 None）。"""
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    try:
        _init_db(conn)
        row = conn.execute(
            "SELECT id FROM asset_snapshots ORDER BY recorded_at DESC, id DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        with conn:
            conn.execute("DELETE FROM asset_snapshots WHERE id = ?", (row["id"],))
        return {"deleted_id": row["id"]}
    finally:
        conn.close()


def load_json(key, default=None):
    """读取 settings 表中的 JSON 数据（不存在或解析失败返回 default）。"""
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    try:
        _init_db(conn)
        raw = _get_setting(conn, key, "")
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
        return default
    finally:
        conn.close()


def save_json(key, obj):
    """把对象以 JSON 形式写入 settings 表。"""
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    try:
        _init_db(conn)
        with conn:
            _set_setting(conn, key, json.dumps(obj, ensure_ascii=False))
    finally:
        conn.close()
