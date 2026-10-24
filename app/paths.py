# -*- coding: utf-8 -*-
"""项目路径常量。"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = PROJECT_ROOT / "web"
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"

_DEFAULT_XLSX = "红利股票配置计算模板.xlsx"


def find_xlsx():
    """返回数据目录中的 Excel 模板路径（找不到时返回默认路径）。"""
    known = DATA_DIR / _DEFAULT_XLSX
    if known.exists():
        return known
    candidates = sorted(DATA_DIR.glob("*.xlsx"))
    return candidates[0] if candidates else known
