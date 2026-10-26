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


def save_entry(gran, key, content, base_sha256=None, force=False):
    if not isinstance(content, str):
        raise DiaryError("content 必须是字符串")
    if len(content.encode("utf-8")) > 2 * 1024 * 1024:
        raise DiaryError("单篇日记不能超过 2MB", 413, "PAYLOAD_TOO_LARGE")
    path = resolve(gran, key, create=True)
    if path.is_file() and base_sha256 and not force:
        current = _sha256(_read(path))
        if current != base_sha256:
            raise DiaryError("文件已被其他页面修改，请刷新后再保存", 409, "CONFLICT")
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
        for memo in memos:
            row = dict(memo)
            row["date"] = item["key"]
            row["path"] = item["path"]
            out.append(row)
    out.sort(key=lambda x: (x["date"], x.get("time") or "00:00"), reverse=True)
    try:
        limit = max(1, int(limit))
    except (TypeError, ValueError):
        limit = 500
    return out[:limit]


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
