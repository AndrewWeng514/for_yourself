# -*- coding: utf-8 -*-
"""小故事：每日文稿导入、草稿/发布，以及逐条批注。

表结构由本模块的 _init 创建，不改 app/store.py。
"""
import json
import re
import sqlite3
from datetime import date, datetime

from . import paths

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FRONT_OPEN = "---\n"
_FRONT_CLOSE = "\n---\n"


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _connect():
    conn = sqlite3.connect(str(paths.DATA_DIR / "app.db"))
    try:
        conn.row_factory = sqlite3.Row
        _init(conn)
        conn.commit()
        return conn
    except Exception:
        conn.close()
        raise


def _init(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS stories ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " story_date TEXT NOT NULL UNIQUE,"
        " title TEXT NOT NULL DEFAULT '',"
        " body TEXT NOT NULL DEFAULT '',"
        " meta_json TEXT NOT NULL DEFAULT '{}',"
        " source TEXT NOT NULL DEFAULT 'manual',"
        " status TEXT NOT NULL DEFAULT 'published',"
        " created_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS story_annotations ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " story_id INTEGER NOT NULL,"
        " quote TEXT NOT NULL DEFAULT '',"
        " comment TEXT NOT NULL DEFAULT '',"
        " created_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_story_annotations_story "
        "ON story_annotations(story_id)"
    )


def _strip_quotes(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _parse_meta_block(block):
    meta = {}
    for line in (block or "").split("\n"):
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if not key:
            continue
        meta[key] = _strip_quotes(value)
    return meta


def _split_frontmatter(raw):
    """有成对 --- 时返回 (meta_block, body)；否则 (None, raw)。"""
    if not raw.startswith(_FRONT_OPEN):
        return None, raw
    end = raw.find(_FRONT_CLOSE, 3)
    if end != -1:
        return raw[len(_FRONT_OPEN):end], raw[end + len(_FRONT_CLOSE):]
    if raw.endswith("\n---"):
        end = len(raw) - 4
        if end >= 3:
            return raw[len(_FRONT_OPEN):end], ""
    return None, raw


def _first_content_line(body):
    for line in (body or "").split("\n"):
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _title_from_body(body, allow_plain):
    line = _first_content_line(body)
    if line.startswith("# "):
        return line[2:].strip()
    if allow_plain and line:
        return line[:40]
    return ""


def parse_markdown(text):
    """解析 markdown，返回 (meta, body, title, story_date)。"""
    raw = text if isinstance(text, str) else ("" if text is None else str(text))
    if raw.startswith("\ufeff"):
        raw = raw[1:]
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    block, body = _split_frontmatter(raw)
    has_frontmatter = block is not None
    meta = _parse_meta_block(block) if has_frontmatter else {}
    title = str(meta.get("title") or "").strip() if has_frontmatter else ""
    if not title:
        title = _title_from_body(body, allow_plain=not has_frontmatter)
    if not title:
        title = "未命名故事"
    story_date = str(meta.get("date") or "").strip() if has_frontmatter else ""
    if not _DATE_RE.match(story_date):
        story_date = date.today().isoformat()
    return meta, body, title, story_date


def _row_to_story(row):
    data = dict(row)
    raw = data.get("meta_json") if "meta_json" in data else "{}"
    meta = {}
    if raw not in (None, ""):
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            meta = parsed
    data["meta"] = meta
    if data.get("annotation_count") is not None:
        data["annotation_count"] = int(data["annotation_count"])
    return data


def _annotations_for(conn, story_id):
    rows = conn.execute(
        "SELECT id, story_id, quote, comment, created_at, updated_at "
        "FROM story_annotations WHERE story_id = ? ORDER BY id ASC",
        (story_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _load_story(conn, story_id):
    row = conn.execute(
        "SELECT * FROM stories WHERE id = ?",
        (story_id,),
    ).fetchone()
    if row is None:
        return None
    story = _row_to_story(row)
    story["annotations"] = _annotations_for(conn, story_id)
    return story


def list_stories(limit=200):
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 200
    if limit < 1:
        limit = 1
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, story_date, title, status, source, created_at, updated_at, "
            "(SELECT COUNT(*) FROM story_annotations "
            " WHERE story_id = stories.id) AS annotation_count "
            "FROM stories ORDER BY story_date DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_story(row) for row in rows]
    finally:
        conn.close()


def get_story(story_id):
    try:
        story_id = int(story_id)
    except (TypeError, ValueError):
        return None
    conn = _connect()
    try:
        return _load_story(conn, story_id)
    finally:
        conn.close()


def import_markdown(text, source="scheduled"):
    if not isinstance(text, str):
        raise ValueError("markdown 必须是字符串")
    if source is None or source == "":
        source = "scheduled"
    source = str(source)
    meta, body, title, story_date = parse_markdown(text)
    meta_json = json.dumps(meta, ensure_ascii=False)
    now = _now()
    conn = _connect()
    story_id = None
    try:
        row = conn.execute(
            "SELECT id FROM stories WHERE story_date = ?",
            (story_date,),
        ).fetchone()
        if row is not None:
            conn.execute(
                "UPDATE stories SET title = ?, body = ?, meta_json = ?, "
                "status = 'published', updated_at = ? WHERE id = ?",
                (title, body, meta_json, now, row["id"]),
            )
            story_id = row["id"]
        else:
            try:
                cur = conn.execute(
                    "INSERT INTO stories ("
                    " story_date, title, body, meta_json, source, status, "
                    " created_at, updated_at"
                    ") VALUES (?, ?, ?, ?, ?, 'published', ?, ?)",
                    (story_date, title, body, meta_json, source, now, now),
                )
                story_id = cur.lastrowid
            except sqlite3.IntegrityError:
                conn.rollback()
                row = conn.execute(
                    "SELECT id FROM stories WHERE story_date = ?",
                    (story_date,),
                ).fetchone()
                if row is None:
                    raise
                conn.execute(
                    "UPDATE stories SET title = ?, body = ?, meta_json = ?, "
                    "status = 'published', updated_at = ? WHERE id = ?",
                    (title, body, meta_json, now, row["id"]),
                )
                story_id = row["id"]
        conn.commit()
    finally:
        conn.close()
    story = get_story(story_id)
    if story is None:
        raise RuntimeError("导入后未能读取故事")
    return story


def _clean_story_date(value):
    text = "" if value is None else str(value).strip()
    if not text:
        return date.today().isoformat()
    if not _DATE_RE.match(text):
        raise ValueError("日期格式应为 YYYY-MM-DD")
    return text


def create_story(payload):
    if not isinstance(payload, dict):
        raise ValueError("请求体必须是 JSON 对象")
    title = payload.get("title")
    title = "" if title is None else str(title).strip()
    body = payload.get("body")
    body = "" if body is None else str(body)
    story_date = _clean_story_date(payload.get("story_date"))
    now = _now()
    conn = _connect()
    story_id = None
    try:
        exists = conn.execute(
            "SELECT id FROM stories WHERE story_date = ?",
            (story_date,),
        ).fetchone()
        if exists is not None:
            raise ValueError("该日期已有故事")
        try:
            cur = conn.execute(
                "INSERT INTO stories ("
                " story_date, title, body, meta_json, source, status, "
                " created_at, updated_at"
                ") VALUES (?, ?, ?, '{}', 'manual', 'draft', ?, ?)",
                (story_date, title, body, now, now),
            )
            story_id = cur.lastrowid
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            raise ValueError("该日期已有故事")
    finally:
        conn.close()
    return get_story(story_id)


def update_story(story_id, payload):
    try:
        story_id = int(story_id)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        raise ValueError("请求体必须是 JSON 对象")
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id FROM stories WHERE id = ?",
            (story_id,),
        ).fetchone()
        if row is None:
            return None
        fields = []
        values = []
        if "title" in payload:
            title = payload.get("title")
            fields.append("title = ?")
            values.append("" if title is None else str(title).strip())
        if "body" in payload:
            body = payload.get("body")
            fields.append("body = ?")
            values.append("" if body is None else str(body))
        if "status" in payload:
            status = payload.get("status")
            status = "" if status is None else str(status).strip()
            if status not in ("draft", "published"):
                raise ValueError("状态只能是 draft 或 published")
            fields.append("status = ?")
            values.append(status)
        if fields:
            fields.append("updated_at = ?")
            values.append(_now())
            values.append(story_id)
            conn.execute(
                "UPDATE stories SET " + ", ".join(fields) + " WHERE id = ?",
                values,
            )
            conn.commit()
    finally:
        conn.close()
    return get_story(story_id)


def delete_story(story_id):
    try:
        story_id = int(story_id)
    except (TypeError, ValueError):
        return 0
    conn = _connect()
    try:
        conn.execute(
            "DELETE FROM story_annotations WHERE story_id = ?",
            (story_id,),
        )
        cur = conn.execute(
            "DELETE FROM stories WHERE id = ?",
            (story_id,),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def add_annotation(story_id, quote, comment):
    try:
        story_id = int(story_id)
    except (TypeError, ValueError):
        raise ValueError("故事不存在")
    text = "" if comment is None else str(comment).strip()
    if not text:
        raise ValueError("批注内容不能为空")
    quote_text = "" if quote is None else str(quote)
    now = _now()
    conn = _connect()
    try:
        story = conn.execute(
            "SELECT id FROM stories WHERE id = ?",
            (story_id,),
        ).fetchone()
        if story is None:
            raise ValueError("故事不存在")
        cur = conn.execute(
            "INSERT INTO story_annotations ("
            " story_id, quote, comment, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?)",
            (story_id, quote_text, text, now, now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id, story_id, quote, comment, created_at, updated_at "
            "FROM story_annotations WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def delete_annotation(story_id, annotation_id):
    try:
        story_id = int(story_id)
        annotation_id = int(annotation_id)
    except (TypeError, ValueError):
        return 0
    conn = _connect()
    try:
        cur = conn.execute(
            "DELETE FROM story_annotations WHERE story_id = ? AND id = ?",
            (story_id, annotation_id),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
