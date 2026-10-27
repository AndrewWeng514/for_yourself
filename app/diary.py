# -*- coding: utf-8 -*-
"""日记存储：文件优先的 Markdown 读写、Memos、日历索引与导入。

设计原则：
- `~/文档/portal-diary/` 是唯一内容源，Markdown 原样保存；
- 不修改、不删除 Obsidian 原库；
- 不建数据库索引：103 个文件直接扫描，简单可重建；
- 路径解析兼容 2023/2025 扁平文件与 2026 分层文件。
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from . import ai_advisor

ROOT = Path(os.environ.get(
    "PORTAL_DIARY_DIR", str(Path.home() / "文档" / "portal-diary")
)).expanduser()

DAY_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:\s+周[一二三四五六日天])?$")
WEEK_RE = re.compile(r"^(\d{4})-W(\d{2})$")
MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")
YEAR_RE = re.compile(r"^(\d{4})年记$")
MEMO_RE = re.compile(r"^-\s+(\d{1,2}:\d{2})(?:\s+(.*))?$")
HEADING_RE = re.compile(r"^#{1,6}\s+\S")
MEMOS_RE = re.compile(r"^\s*#{0,6}\s*Memos\s*$")
TAG_RE = re.compile(r"#[^\s#]+")
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".heic"}


class DiaryError(Exception):
    """带 HTTP 语义的日记错误。"""

    def __init__(self, message, status=400, code="VALIDATION"):
        super().__init__(message)
        self.status = status
        self.code = code


def _safe_rel(rel):
    rel = str(rel or "").replace("\\", "/").strip("/")
    if not rel or rel.startswith("../") or "/../" in rel or rel.startswith("/"):
        raise DiaryError("非法路径", 400)
    path = (ROOT / rel).resolve()
    if ROOT.resolve() not in path.parents and path != ROOT.resolve():
        raise DiaryError("非法路径", 400)
    return path


def _rel(path):
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def _sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read(path):
    return path.read_text(encoding="utf-8", errors="replace")


def _atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".diary-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _week_key(d):
    iso = d.isocalendar()
    return "%04d-W%02d" % (iso[0], iso[1])


def _date_from_week(key):
    m = WEEK_RE.match(key)
    if not m:
        raise DiaryError("周格式应为 YYYY-Www")
    year, week = int(m.group(1)), int(m.group(2))
    jan4 = date(year, 1, 4)
    monday = jan4 - timedelta(days=jan4.weekday()) + timedelta(weeks=week - 1)
    return monday


def classify(stem):
    if DAY_RE.match(stem):
        return "day", stem[:10]
    if WEEK_RE.match(stem):
        return "week", stem
    if MONTH_RE.match(stem):
        return "month", stem
    if QUARTER_RE.match(stem):
        return "quarter", stem
    if YEAR_RE.match(stem):
        return "year", stem
    return "note", stem


def _candidates(gran, key):
    key = str(key or "").strip()
    if gran == "day":
        m = DAY_RE.match(key)
        if not m:
            raise DiaryError("日期格式应为 YYYY-MM-DD")
        y = m.group(1)
        return [
            ROOT / y / "日记" / (key + ".md"),
            ROOT / y / (key + ".md"),
        ], lambda: sorted((ROOT / y).glob(key + " *.md"))
    if gran == "week":
        if not WEEK_RE.match(key):
            raise DiaryError("周格式应为 YYYY-Www")
        y = key[:4]
        return [ROOT / y / "周记" / (key + ".md"), ROOT / y / (key + ".md")], None
    if gran == "month":
        if not MONTH_RE.match(key):
            raise DiaryError("月份格式应为 YYYY-MM")
        y = key[:4]
        return [ROOT / y / "月记" / (key + ".md"), ROOT / y / (key + ".md")], None
    if gran == "quarter":
        if not QUARTER_RE.match(key):
            raise DiaryError("季度格式应为 YYYY-Qn")
        y = key[:4]
        return [ROOT / y / "季度" / (key + ".md"), ROOT / y / (key + ".md")], None
    if gran == "year":
        if not re.match(r"^\d{4}$", key):
            raise DiaryError("年份格式应为 YYYY")
        return [ROOT / key / (key + "年记.md")], None
    raise DiaryError("未知粒度：%s" % gran)


def resolve(gran, key, create=False):
    cands, globber = _candidates(gran, key)
    for path in cands:
        if path.is_file():
            return path
    if globber:
        extra = [p for p in globber() if p.is_file()]
        if extra:
            return extra[0]
    if create:
        return cands[0]
    return None


def entry_meta(path):
    stem = path.stem
    gran, key = classify(stem)
    content = _read(path)
    return {
        "path": _rel(path),
        "gran": gran,
        "key": key,
        "title": stem,
        "size": path.stat().st_size,
        "mtime": int(path.stat().st_mtime),
        "memos": len(parse_memos(content)),
        "has_frontmatter": content.startswith("---"),
        "has_dataview": "dataview" in content.lower(),
    }


def list_entries():
    ROOT.mkdir(parents=True, exist_ok=True)
    items = []
    for path in sorted(ROOT.rglob("*.md")):
        rel = _rel(path)
        if rel.startswith("Template/") or rel.startswith("assets/"):
            continue
        try:
            items.append(entry_meta(path))
        except OSError:
            continue
    items.sort(key=lambda x: (x["key"], x["path"]), reverse=True)
    return items


def read_entry(gran, key):
    path = resolve(gran, key)
    if not path:
        default = resolve(gran, key, create=True)
        return {
            "exists": False,
            "path": _rel(default),
            "gran": gran,
            "key": key,
            "content": "",
            "sha256": "",
            "mtime": 0,
            "memos": [],
        }
    content = _read(path)
    return {
        "exists": True,
        "path": _rel(path),
        "gran": gran,
        "key": key,
        "content": content,
        "sha256": _sha256(content),
        "mtime": int(path.stat().st_mtime),
        "memos": parse_memos(content),
    }


_UNSAFE_HTML_RE = re.compile(
    r"<(iframe|script|object|embed|form|video|audio|style)\b",
    re.IGNORECASE,
)


def _without_fences(text):
    kept = []
    open_fence = False
    for line in str(text or "").splitlines():
        if re.match(r"^\s*(```|~~~)", line):
            open_fence = not open_fence
            continue
        if not open_fence:
            kept.append(line)
    return "\n".join(kept)


def _has_unsafe_html(text):
    """代码围栏之外的原始嵌入。frontmatter 与 dataview 围栏不算。"""
    return bool(_UNSAFE_HTML_RE.search(_without_fences(text)))


def _body_text(content):
    """去掉 frontmatter 后的正文；用于判断是否只剩元数据。"""
    text = re.sub(r"^---\n[\s\S]*?\n---\n?", "", str(content or ""), count=1)
    return text.strip()


def _empty_overwrite_blocked(gran, existing):
    if gran in ("week", "month", "quarter", "year"):
        return True
    return _has_unsafe_html(existing)


def save_entry(gran, key, content, base_sha256=None, force=False):
    if not isinstance(content, str):
        raise DiaryError("content 必须是字符串")
    if len(content.encode("utf-8")) > 2 * 1024 * 1024:
        raise DiaryError("单篇日记不能超过 2MB", 413, "PAYLOAD_TOO_LARGE")
    path = resolve(gran, key, create=True)
    existing = _read(path) if path.is_file() else None
    if existing is not None and base_sha256 and not force:
        current = _sha256(existing)
        if current != base_sha256:
            raise DiaryError("文件已被其他页面修改，请刷新后再保存", 409, "CONFLICT")
    if (existing is not None and existing.strip()
            and _empty_overwrite_blocked(gran, existing)
            and _body_text(existing) and not _body_text(content)):
        raise DiaryError("正文为空，已拒绝覆盖原笔记", 400, "EMPTY_OVERWRITE")
    if (existing is not None and existing.strip() and not content.strip()
            and _empty_overwrite_blocked(gran, existing)):
        raise DiaryError("内容为空，已拒绝覆盖原笔记", 400, "EMPTY_OVERWRITE")
    _atomic_write(path, content)
    return read_entry(gran, key)


def _memo_section(lines):
    start = None
    for i, line in enumerate(lines):
        if MEMOS_RE.match(line):
            start = i
    if start is None:
        return None, None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if HEADING_RE.match(lines[j]):
            end = j
            break
    return start, end


def _parse_legacy_memos(section):
    """旧格式：Memos 段里是 1. / - 开头的普通列表，没有 HH:mm。"""
    memos = []
    current = None
    for line in section:
        stripped = line.strip()
        if not stripped:
            continue
        m = re.match(r"^(?:[-*+]|\d+\.)\s+(.*)$", line)
        if m:
            if current:
                memos.append(current)
            text = m.group(1).strip()
            current = {"time": "", "text": text,
                       "tags": TAG_RE.findall(text), "legacy": True}
            continue
        if current is not None:
            current["text"] = (current["text"] + "\n" + stripped).strip()
            current["tags"] = TAG_RE.findall(current["text"])
    if current:
        memos.append(current)
    return memos


def parse_memos(content):
    lines = content.splitlines()
    start, end = _memo_section(lines)
    section = lines[start + 1:end] if start is not None else lines
    memos = []
    current = None
    for line in section:
        m = MEMO_RE.match(line)
        if m:
            if current:
                memos.append(current)
            text = (m.group(2) or "").strip()
            current = {"time": m.group(1), "text": text, "tags": TAG_RE.findall(text)}
            continue
        if current is None:
            continue
        stripped = line.strip()
        if not stripped:
            continue
        if line[:1] in (" ", "\t"):
            current["text"] = (current["text"] + "\n" + stripped).strip()
            current["tags"] = TAG_RE.findall(current["text"])
        else:
            memos.append(current)
            current = None
    if current:
        memos.append(current)
    if not memos and start is not None:
        memos = _parse_legacy_memos(section)
    return memos


def append_memo(day_key, text, memo_time=None):
    text = str(text or "").strip()
    if not text:
        raise DiaryError("memo 内容不能为空")
    if len(text) > 4000:
        raise DiaryError("memo 太长")
    if not DAY_RE.match(day_key):
        raise DiaryError("日期格式应为 YYYY-MM-DD")
    path = resolve("day", day_key, create=True)
    content = _read(path) if path.is_file() else ""
    if memo_time is None:
        memo_time = datetime.now().strftime("%H:%M")
    if not re.match(r"^\d{1,2}:\d{2}$", memo_time):
        raise DiaryError("时间格式应为 HH:mm")

    lines = content.splitlines()
    start, end = _memo_section(lines)
    memo_parts = text.splitlines() or [text]
    memo_line = "- %s %s" % (memo_time, memo_parts[0])
    for extra in memo_parts[1:]:
        memo_line += "\n\t" + extra
    if start is None:
        body = content.rstrip()
        content = (body + "\n\n" if body else "") + "Memos\n\n" + memo_line + "\n"
    else:
        insert_at = end
        while insert_at > start + 1 and not lines[insert_at - 1].strip():
            insert_at -= 1
        lines.insert(insert_at, memo_line)
        content = "\n".join(lines).rstrip("\n") + "\n"
    _atomic_write(path, content)
    return {"path": _rel(path), "memos": parse_memos(content)}


def calendar(year, month):
    y, m = int(year), int(month)
    days = {}
    weeks = {}
    for item in list_entries():
        if item["gran"] == "day":
            m2 = DAY_RE.match(item["key"])
            if not m2 or int(m2.group(1)) != y or int(m2.group(2)) != m:
                continue
            d = date(y, m, int(m2.group(3)))
            wk = _week_key(d)
            days[item["key"]] = {"memos": item["memos"], "path": item["path"]}
            weeks.setdefault(wk, {"memos": 0, "days": 0})
            weeks[wk]["memos"] += item["memos"]
            weeks[wk]["days"] += 1
        elif item["gran"] == "week":
            wk = item["key"]
            if wk.startswith("%04d-" % y):
                weeks.setdefault(wk, {"memos": 0, "days": 0})
                weeks[wk]["has_week"] = True
    return {"year": y, "month": m, "days": days, "weeks": weeks,
            "total_days": len(days)}


def heatmap(year):
    y = int(year)
    days = {}
    for item in list_entries():
        if item["gran"] != "day":
            continue
        m = DAY_RE.match(item["key"])
        if m and int(m.group(1)) == y:
            days[item["key"]] = item["memos"]
    return {"year": y, "days": days}


def tags(year=None):
    counts = {}
    for item in list_entries():
        if item["gran"] != "day":
            continue
        if year and not item["key"].startswith(str(year) + "-"):
            continue
        path = ROOT / item["path"]
        for memo in parse_memos(_read(path)):
            for tag in memo["tags"]:
                counts[tag] = counts.get(tag, 0) + 1
    return sorted(({"tag": k, "count": v} for k, v in counts.items()),
                  key=lambda x: -x["count"])


def memo_history(year=None, limit=500):
    """跨日期汇总 memos；给「速记」页展示历史用。"""
    out = []
    for item in list_entries():
        if item["gran"] != "day":
            continue
        if year and not item["key"].startswith(str(year) + "-"):
            continue
        try:
            memos = parse_memos(_read(ROOT / item["path"]))
        except OSError:
            continue
        for idx, memo in enumerate(memos):
            row = dict(memo)
            row["date"] = item["key"]
            row["path"] = item["path"]
            row["index"] = idx
            out.append(row)
    out.sort(key=lambda x: (x["date"], x.get("time") or "00:00"), reverse=True)
    try:
        limit = max(1, int(limit))
    except (TypeError, ValueError):
        limit = 500
    return out[:limit]


def _format_memo(memo):
    time = str(memo.get("time") or "").strip()
    text = str(memo.get("text") or "").strip()
    parts = text.splitlines() or [""]
    head = (("- %s %s" % (time, parts[0])) if time else ("- " + parts[0])).rstrip()
    out = [head]
    for extra in parts[1:]:
        out.append("\t" + extra)
    return "\n".join(out)


def _replace_memos_section(content, memos):
    lines = content.splitlines()
    start, end = _memo_section(lines)
    block = "Memos\n\n" + "\n".join(_format_memo(m) for m in memos) + "\n"
    if start is None:
        body = content.rstrip()
        return (body + "\n\n" if body else "") + block
    before = "\n".join(lines[:start]).rstrip()
    after = "\n".join(lines[end:]).lstrip("\n")
    result = (before + "\n\n" if before else "") + block
    if after.strip():
        result += "\n" + after
    return result.rstrip() + "\n"


def _load_memos(day_key):
    path = resolve("day", day_key)
    if not path or not path.is_file():
        raise DiaryError("当天日记不存在", 404, "NOT_FOUND")
    content = _read(path)
    return path, content, parse_memos(content)


def update_memo(day_key, index, text=None, memo_time=None):
    path, content, memos = _load_memos(day_key)
    try:
        idx = int(index)
    except (TypeError, ValueError):
        raise DiaryError("memo 序号无效")
    if idx < 0 or idx >= len(memos):
        raise DiaryError("memo 不存在", 404, "NOT_FOUND")
    if text is not None:
        text = str(text).strip()
        if not text:
            raise DiaryError("memo 内容不能为空")
        if len(text) > 4000:
            raise DiaryError("memo 太长")
        memos[idx]["text"] = text
        memos[idx]["tags"] = TAG_RE.findall(text)
    if memo_time is not None:
        if not re.match(r"^\d{1,2}:\d{2}$", str(memo_time)):
            raise DiaryError("时间格式应为 HH:mm")
        memos[idx]["time"] = str(memo_time)
    new_content = _replace_memos_section(content, memos)
    _atomic_write(path, new_content)
    return {"path": _rel(path), "memos": parse_memos(new_content)}


def delete_memo(day_key, index):
    path, content, memos = _load_memos(day_key)
    try:
        idx = int(index)
    except (TypeError, ValueError):
        raise DiaryError("memo 序号无效")
    if idx < 0 or idx >= len(memos):
        raise DiaryError("memo 不存在", 404, "NOT_FOUND")
    memos.pop(idx)
    new_content = _replace_memos_section(content, memos)
    _atomic_write(path, new_content)
    return {"path": _rel(path), "memos": parse_memos(new_content)}


# ---------- 模板 ----------
TEMPLATE_MAP = {
    "day": "日记模板.md",
    "week": "周记模板.md",
    "month": "月记模板.md",
    "quarter": "季度模板.md",
    "year": "年记模板.md",
}


def _template_dir():
    return ROOT / "Template"


def _anchor(gran, key):
    today = date.today()
    key = str(key or "").strip()
    try:
        if gran == "day":
            return date.fromisoformat(key[:10])
        if gran == "week":
            return _date_from_week(key)
        if gran == "month":
            m = MONTH_RE.match(key)
            return date(int(m.group(1)), int(m.group(2)), 1)
        if gran == "quarter":
            m = QUARTER_RE.match(key)
            return date(int(m.group(1)), (int(m.group(2)) - 1) * 3 + 1, 1)
        if gran == "year":
            return date(int(key[:4]), 1, 1)
    except Exception:
        pass
    return today


def render_template(text, gran, key):
    anchor = _anchor(gran, key)
    iso = anchor.isocalendar()
    q = (anchor.month - 1) // 3 + 1
    values = [
        ("{{date:gggg-[W]ww}}", "%04d-W%02d" % (iso[0], iso[1])),
        ("{{date:YYYY-MM-DD}}", anchor.isoformat()),
        ("{{date:YYYY-MM}}", "%04d-%02d" % (anchor.year, anchor.month)),
        ("{{date:YYYY}}", "%04d" % anchor.year),
        ("{{date:Q}}", str(q)),
        ("{{date:MM}}", "%02d" % anchor.month),
        ("{{date:DD}}", "%02d" % anchor.day),
    ]
    for placeholder, value in values:
        text = text.replace(placeholder, value)
    return text


def list_templates():
    out = []
    for gran, name in TEMPLATE_MAP.items():
        path = _template_dir() / name
        out.append({
            "gran": gran,
            "name": name,
            "path": "Template/" + name,
            "exists": path.is_file(),
        })
    return out


def get_template(gran, key=None):
    if gran not in TEMPLATE_MAP:
        raise DiaryError("未知模板粒度：%s" % gran)
    path = _template_dir() / TEMPLATE_MAP[gran]
    if not path.is_file():
        return {"gran": gran, "path": "Template/" + TEMPLATE_MAP[gran],
                "exists": False, "raw": "", "content": ""}
    raw = _read(path)
    content = render_template(raw, gran, key) if key else raw
    return {"gran": gran, "path": "Template/" + TEMPLATE_MAP[gran],
            "exists": True, "raw": raw, "content": content}


def save_template(gran, content):
    if gran not in TEMPLATE_MAP:
        raise DiaryError("未知模板粒度：%s" % gran)
    if not isinstance(content, str):
        raise DiaryError("模板内容必须是字符串")
    if len(content.encode("utf-8")) > 200 * 1024:
        raise DiaryError("模板不能超过 200KB", 413, "PAYLOAD_TOO_LARGE")
    path = _template_dir() / TEMPLATE_MAP[gran]
    _atomic_write(path, content)
    return get_template(gran)


# ---------- 周期总结 ----------

FINANCIAL_HEADINGS = [
    "## 本周收支情况",
    "## 本周基金定投",
    "## 周资产",
    "## 净资产趋势",
    "## 资产趋势",
    "## 资产快照",
    "## 月度定投",
    "## 目标 vs 实际",
    "## 再平衡动作",
]
ASSET_FIELDS = ("中信股票", "支付宝", "招商基金", "流动备用金", "招商固定", "负债")
SUMMARY_GRANS = ("week", "month", "quarter", "year")


def _strip_financial(text):
    if not text:
        return ""
    lines = text.splitlines()
    out = []
    skip = False
    for line in lines:
        stripped = line.strip()
        if any(stripped.startswith(h) for h in FINANCIAL_HEADINGS):
            skip = True
            continue
        if skip and re.match(r"^##\s+", line):
            skip = False
        if skip:
            continue
        if re.match(r"^(%s):" % "|".join(ASSET_FIELDS), stripped):
            continue
        if stripped.startswith("> 周记属性栏填资产"):
            continue
        line = line.replace(" · 财产：[[财产规划]]", "").replace("财产：[[财产规划]]", "")
        out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def _add_months(d, months):
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    return date(year, month, 1)


def _period_range(gran, key):
    key = str(key or "").strip()
    if gran == "week":
        start = _date_from_week(key)
        return start, start + timedelta(days=6)
    if gran == "month":
        m = MONTH_RE.match(key)
        if not m:
            raise DiaryError("月份格式应为 YYYY-MM")
        start = date(int(m.group(1)), int(m.group(2)), 1)
        return start, _add_months(start, 1) - timedelta(days=1)
    if gran == "quarter":
        m = QUARTER_RE.match(key)
        if not m:
            raise DiaryError("季度格式应为 YYYY-Qn")
        start = date(int(m.group(1)), (int(m.group(2)) - 1) * 3 + 1, 1)
        return start, _add_months(start, 3) - timedelta(days=1)
    if gran == "year":
        y = int(key)
        return date(y, 1, 1), date(y, 12, 31)
    raise DiaryError("总结只支持周/月/季/年")


def next_period_key(gran, key):
    start, _ = _period_range(gran, key)
    if gran == "week":
        return _week_key(start + timedelta(days=7))
    if gran == "month":
        return _add_months(start, 1).strftime("%Y-%m")
    if gran == "quarter":
        return _add_months(start, 3).strftime("%Y") + "-Q" + str((_add_months(start, 3).month - 1) // 3 + 1)
    return str(start.year + 1)


def _entry_period(gran, key):
    if gran == "day":
        return date.fromisoformat(key), date.fromisoformat(key)
    return _period_range(gran, key)


def collect_period(gran, key):
    if gran not in SUMMARY_GRANS:
        raise DiaryError("总结只支持周/月/季/年")
    start, end = _period_range(gran, key)
    wanted = {
        "week": {"day", "week"},
        "month": {"day", "week", "month"},
        "quarter": {"day", "week", "month", "quarter"},
        "year": {"day", "week", "month", "quarter", "year"},
    }[gran]
    rows = []
    year_key = str(key).strip()
    for item in list_entries():
        # 年记目录里未按日/周/月/季命名的 Markdown（如「2023年记录」）仍属于该年，不能丢掉。
        same_year_note = (
            gran == "year" and item["gran"] == "note"
            and item["path"].startswith(year_key + "/")
        )
        if item["gran"] not in wanted and not same_year_note:
            continue
        if not same_year_note:
            period_key = item["key"]
            if item["gran"] == "year":
                year_m = re.match(r"^(\d{4})", str(period_key))
                if year_m:
                    period_key = year_m.group(1)
            try:
                p_start, p_end = _entry_period(item["gran"], period_key)
            except (ValueError, DiaryError):
                continue
            if p_end < start or p_start > end:
                continue
        content = _strip_financial(_read(ROOT / item["path"]))
        if not content.strip():
            continue
        rows.append({
            "gran": item["gran"], "key": item["key"],
            "path": item["path"], "content": content,
        })
    rows.sort(key=lambda x: (x["key"], x["path"]))
    return rows


def _period_label(gran, key):
    start, end = _period_range(gran, key)
    return "%s（%s 至 %s）" % (key, start.isoformat(), end.isoformat())


def summary_title(gran, key):
    if gran == "week":
        return "## 上周总结（%s）" % key
    if gran == "month":
        return "## 上月总结（%s）" % key
    if gran == "quarter":
        return "## 上季度总结（%s）" % key
    return "## 去年总结（%s）" % key


_SUMMARY_CONTEXT_LIMIT = 60000
_SUMMARY_TOKENS = 4000
_SUMMARY_TOKENS_RETRY = 6000
_SUMMARY_TIMEOUT = 120


def _summary_system(partial):
    if partial:
        return (
            "你是个人日记复盘助手。下面只是该周期笔记的一部分。"
            "只依据给出的内容提取事实要点，不要编造。"
            "不要输出财务、资产、收支、基金、股票、净值相关内容；如果原文有，忽略。"
            "用中文 Markdown 列出：进展、状态与情绪、决定、未完成事项。"
        )
    return (
        "你是个人日记复盘助手。只依据给出的日记内容总结，不要编造。"
        "输出 Markdown，结构为：主要进展、状态与情绪、做过的决定、未完成/遗留问题、下阶段建议。"
        "不要输出财务、资产、收支、基金、股票、净值相关内容；如果原文有，忽略。"
        "语言简洁，用中文；建议 3-5 条。"
    )


def _pack_blocks(blocks, limit):
    """按块打包。单块超限时按字符切开，不丢弃后半段。"""
    batches = []
    current = []
    for block in blocks:
        if len(block) > limit:
            if current:
                batches.append("\n\n".join(current))
                current = []
            start = 0
            while start < len(block):
                batches.append(block[start:start + limit])
                start += limit
            continue
        trial = "\n\n".join(current + [block]) if current else block
        if current and len(trial) > limit:
            batches.append("\n\n".join(current))
            current = [block]
        else:
            current.append(block)
    if current:
        batches.append("\n\n".join(current))
    return batches


def _ai_error_retryable(exc):
    text = str(exc)
    return ("内容为空" in text) or ("截断" in text) or ("token 上限" in text)


def _complete_summary(messages):
    cfg = ai_advisor.load_config()
    primary = cfg["model"] or "deepseek-chat"
    base = str(cfg["base_url"] or "")
    attempts = [(primary, _SUMMARY_TOKENS)]
    if "deepseek" in base.lower() and primary != "deepseek-chat":
        attempts.append(("deepseek-chat", _SUMMARY_TOKENS_RETRY))
    else:
        attempts.append((primary, _SUMMARY_TOKENS_RETRY))
    last_error = None
    for index, (model, max_tokens) in enumerate(attempts):
        try:
            text = ai_advisor.chat(
                messages, max_tokens=max_tokens, temperature=0.3,
                model=model, timeout=_SUMMARY_TIMEOUT)
            if str(text or "").strip():
                return text, model
            last_error = RuntimeError("AI 返回内容为空")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        if index == 0 and _ai_error_retryable(last_error):
            continue
        break
    raise DiaryError("AI 总结失败：%s" % (last_error or "未返回内容"), 400, "AI_ERROR")


def _ask_summary(label, context, partial):
    if partial:
        user = "周期：%s\n以下是该周期笔记的一部分，请提取要点，不要遗漏这段里的事实：\n\n%s" % (
            label, context)
    else:
        user = "周期：%s\n请阅读以下该周期的全部笔记并总结：\n\n%s" % (label, context)
    messages = [
        {"role": "system", "content": _summary_system(partial)},
        {"role": "user", "content": user},
    ]
    return _complete_summary(messages)


def summarize_period(gran, key):
    rows = collect_period(gran, key)
    if not rows:
        raise DiaryError("该周期没有可总结的笔记", 404, "NOT_FOUND")
    blocks = ["### %s\n%s" % (row["path"], row["content"]) for row in rows]
    label = _period_label(gran, key)
    batches = _pack_blocks(blocks, _SUMMARY_CONTEXT_LIMIT)
    if len(batches) == 1:
        summary, used_model = _ask_summary(label, batches[0], partial=False)
    else:
        partials = []
        used_model = ""
        for index, batch in enumerate(batches, 1):
            text, used_model = _ask_summary(
                "%s · 第 %s/%s 部分" % (label, index, len(batches)),
                batch, partial=True)
            partials.append("### 第 %s 部分要点\n%s" % (index, text))
        merged_blocks = partials
        if sum(len(part) for part in partials) > _SUMMARY_CONTEXT_LIMIT:
            reduced = []
            for index, batch in enumerate(_pack_blocks(partials, _SUMMARY_CONTEXT_LIMIT), 1):
                text, used_model = _ask_summary(
                    "%s · 要点合并 %s" % (label, index), batch, partial=True)
                reduced.append(text)
            merged_blocks = reduced
        summary, used_model = _ask_summary(label, "\n\n".join(merged_blocks), partial=False)
    if not str(summary or "").strip():
        raise DiaryError("AI 总结失败：未返回内容", 400, "AI_ERROR")
    target_key = next_period_key(gran, key)
    target = resolve(gran, target_key, create=True)
    return {
        "source_key": key,
        "source_label": label,
        "target_key": target_key,
        "target_path": _rel(target),
        "title": summary_title(gran, key),
        "summary": summary,
        "source_count": len(rows),
        "model": used_model,
    }


def _upsert_summary(content, title, summary):
    lines = content.splitlines() if content else []
    out = []
    skip = False
    for line in lines:
        if line.strip() == title.strip():
            skip = True
            continue
        if skip and re.match(r"^##\s+", line):
            skip = False
        if not skip:
            out.append(line)
    block = [title, "", summary.strip(), ""]
    pos = None
    for i, line in enumerate(out):
        if MEMOS_RE.match(line):
            pos = i
            break
    if pos is None:
        if out and out[-1].strip():
            out.append("")
        out.extend(block)
    else:
        out = out[:pos] + block + out[pos:]
    return "\n".join(out).strip() + "\n"


def apply_summary(gran, key, summary, title=None):
    if gran not in SUMMARY_GRANS:
        raise DiaryError("总结只支持周/月/季/年")
    summary = str(summary or "").strip()
    if not summary:
        raise DiaryError("总结内容不能为空")
    target_key = next_period_key(gran, key)
    target = resolve(gran, target_key, create=True)
    content = _read(target) if target.is_file() else ""
    title = title or summary_title(gran, key)
    new_content = _upsert_summary(content, title, summary)
    _atomic_write(target, new_content)
    return {"path": _rel(target), "target_key": target_key, "title": title}


# ---------- 导入 ----------

def _convert_wikilinks(text, assets_dir):
    def target_for(name):
        target = assets_dir / Path(name).name
        if target.is_file():
            return target
        return None

    def repl_image(m):
        name = m.group(1).strip()
        if not name:
            return ""
        target = target_for(name)
        if target:
            return "![%s](%s)" % (Path(name).stem, "assets/annex/" + quote(target.name))
        return "（附件缺失：%s）" % Path(name).name

    def repl_link(m):
        name = m.group(1).split("|")[0].split("#")[0].strip()
        target = target_for(name)
        if target:
            url = "assets/annex/" + quote(target.name)
            if target.suffix.lower() in IMAGE_EXT:
                return "![%s](%s)" % (Path(target.name).stem, url)
            return "[%s](%s)" % (target.name, url)
        return name

    text = re.sub(r"!\[\[([^\]]+)\]\]", repl_image, text)
    text = re.sub(r"\[\[([^\]]+)\]\]", repl_link, text)
    return text


def save_asset(data_b64, ext="webp"):
    """保存前端压缩后的 base64 图片；返回 /diary-assets/ 路径。"""
    ext = str(ext or "webp").lower().lstrip(".")
    if ext not in ("webp", "jpg", "jpeg", "png"):
        raise DiaryError("不支持的图片格式")
    raw = str(data_b64 or "").strip()
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[-1]
    try:
        data = base64.b64decode(raw, validate=True)
    except Exception:
        raise DiaryError("图片 base64 无法解析")
    if len(data) > 20 * 1024 * 1024:
        raise DiaryError("图片不能超过 20MB", 413, "PAYLOAD_TOO_LARGE")
    if data.startswith(b"\xff\xd8"):
        ext = "jpg"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        ext = "png"
    elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        ext = "webp"
    else:
        raise DiaryError("只支持 JPEG/PNG/WebP")
    now = datetime.now()
    rel = "assets/%04d/%02d/%s.%s" % (now.year, now.month, uuid.uuid4().hex, ext)
    target = _safe_rel(rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return "/diary-assets/" + rel[len("assets/"):]


def import_zip(fileobj, overwrite=False):
    """导入 zip；只写 portal-diary，绝不碰源 vault。"""
    stats = {"imported": 0, "skipped": 0, "conflict": 0, "failed": [], "assets": 0}
    ROOT.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(fileobj) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            raw = info.filename.replace("\\", "/")
            parts = [p for p in raw.split("/") if p not in ("", ".")]
            if not parts or any(p == ".." for p in parts):
                stats["failed"].append({"name": raw, "error": "非法路径"})
                continue
            if parts[0] == "1.Diary":
                parts = parts[1:]
            if not parts:
                continue
            rel = "/".join(parts)
            try:
                data = zf.read(info)
            except Exception as exc:  # noqa: BLE001
                stats["failed"].append({"name": raw, "error": str(exc)})
                continue
            if rel.startswith("Template/") or rel.lower().endswith(".md"):
                target = _safe_rel(rel)
                if rel.lower().endswith(".md"):
                    text = data.decode("utf-8", "replace")
                    text = _convert_wikilinks(text, ROOT / "assets" / "annex")
                    data = text.encode("utf-8")
                if target.is_file() and not overwrite:
                    if target.read_bytes() == data:
                        stats["skipped"] += 1
                    else:
                        stats["conflict"] += 1
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                stats["imported"] += 1
            elif parts[0] == "Annex":
                target = _safe_rel("assets/annex/" + Path(rel).name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                stats["assets"] += 1
            else:
                stats["failed"].append({"name": raw, "error": "不支持的路径"})
    return stats
