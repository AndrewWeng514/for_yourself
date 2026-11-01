# -*- coding: utf-8 -*-
"""Stdlib smoke tests for diary helpers and server static utilities."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

_TEMP_DIARY = tempfile.TemporaryDirectory()
os.environ["PORTAL_DIARY_DIR"] = _TEMP_DIARY.name

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app import diary, paths  # noqa: E402
from app.server import _accepts_gzip, _file_etag, _static_cache_control  # noqa: E402


def tearDownModule():
    _TEMP_DIARY.cleanup()
    os.environ.pop("PORTAL_DIARY_DIR", None)


class PeriodRangeTests(unittest.TestCase):
    def test_week_boundaries(self):
        start, end = diary._period_range("week", "2026-W10")
        self.assertEqual((end - start).days, 6)
        self.assertEqual(start.weekday(), 0)

    def test_month_february_non_leap(self):
        start, end = diary._period_range("month", "2026-02")
        self.assertEqual(start, date(2026, 2, 1))
        self.assertEqual(end, date(2026, 2, 28))

    def test_month_december(self):
        start, end = diary._period_range("month", "2026-12")
        self.assertEqual(start, date(2026, 12, 1))
        self.assertEqual(end, date(2026, 12, 31))

    def test_quarter_q1(self):
        start, end = diary._period_range("quarter", "2026-Q1")
        self.assertEqual(start, date(2026, 1, 1))
        self.assertEqual(end, date(2026, 3, 31))

    def test_quarter_q4(self):
        start, end = diary._period_range("quarter", "2026-Q4")
        self.assertEqual(start, date(2026, 10, 1))
        self.assertEqual(end, date(2026, 12, 31))

    def test_year(self):
        start, end = diary._period_range("year", "2026")
        self.assertEqual(start, date(2026, 1, 1))
        self.assertEqual(end, date(2026, 12, 31))


class StripFinancialTests(unittest.TestCase):
    def test_removes_financial_blocks_keeps_body(self):
        raw = "\n".join(
            [
                "今日反思",
                "",
                "## 本周收支情况",
                "支出 100",
                "中信股票: 999",
                "",
                "## 其它",
                "结尾仍保留",
            ]
        )
        out = diary._strip_financial(raw)
        self.assertIn("今日反思", out)
        self.assertIn("结尾仍保留", out)
        self.assertNotIn("本周收支情况", out)
        self.assertNotIn("中信股票", out)
        self.assertNotIn("支出 100", out)


class SaveEntryTests(unittest.TestCase):
    def test_day_entry_writes_under_temp_root(self):
        key = "2099-06-01"
        diary.save_entry("day", key, "# 冒烟\n\n可写正文。")
        path = diary.resolve("day", key)
        self.assertIsNotNone(path)
        self.assertTrue(path.is_file())
        text = path.read_text(encoding="utf-8")
        self.assertIn("可写正文", text)
        self.assertTrue(str(path).startswith(str(Path(_TEMP_DIARY.name))))

    def test_year_nonempty_then_empty_raises(self):
        year_key = "2098"
        diary.save_entry("year", year_key, "# 2098 年记\n\n已有内容。")
        with self.assertRaises(diary.DiaryError) as ctx:
            diary.save_entry("year", year_key, "")
        self.assertEqual(ctx.exception.code, "EMPTY_OVERWRITE")


class ServerHelperTests(unittest.TestCase):
    def test_file_etag_stable(self):
        etag_a = _file_etag(1710000000.9, 512)
        etag_b = _file_etag(1710000000.1, 512)
        self.assertEqual(etag_a, etag_b)
        self.assertEqual(etag_a, '"1710000000-512"')

    def test_accepts_gzip(self):
        self.assertTrue(_accepts_gzip("gzip"))
        self.assertFalse(_accepts_gzip("gzip;q=0"))
        self.assertFalse(_accepts_gzip(None))
        self.assertFalse(_accepts_gzip(""))

    def test_static_cache_control(self):
        self.assertEqual(_static_cache_control("index.html"), "no-cache")
        self.assertEqual(_static_cache_control("web/page.HTML"), "no-cache")
        vendor_js = paths.WEB_DIR / "vendor" / "vditor" / "dist" / "index.min.js"
        self.assertTrue(vendor_js.is_file(), "fixture vendor js must exist")
        self.assertEqual(
            _static_cache_control(str(vendor_js)),
            "public, max-age=86400",
        )


class ParseMemosTests(unittest.TestCase):
    """Optional: Memos/frontmatter separation (no split_note in app.diary)."""

    def test_parse_memos_after_frontmatter(self):
        content = "\n".join(
            [
                "---",
                "title: smoke",
                "---",
                "",
                "正文在前",
                "",
                "Memos",
                "",
                "- 10:15 速记一条",
            ]
        )
        memos = diary.parse_memos(content)
        self.assertEqual(len(memos), 1)
        self.assertEqual(memos[0]["time"], "10:15")
        self.assertEqual(memos[0]["text"], "速记一条")
        start, end = diary._memo_section(content.splitlines())
        self.assertIsNotNone(start)
        self.assertGreater(end, start)


if __name__ == "__main__":
    unittest.main()
