# -*- coding: utf-8 -*-
"""解析「红利股票配置计算模板.xlsx」。"""
import re
import time
import zipfile
import xml.etree.ElementTree as ET

from . import paths

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def col_index(ref):
    """把 A1 式引用转成 (行号, 列号)，列号从 0 开始。"""
    m = re.match(r"([A-Z]+)(\d+)", ref or "")
    if not m:
        return None
    letters, digits = m.group(1), m.group(2)
    col = 0
    for ch in letters:
        col = col * 26 + (ord(ch) - ord("A") + 1)
    return int(digits), col - 1


def read_xlsx(path):
    """读取 xlsx，返回 {行号: {列号: 值}}。"""
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml").decode("utf-8"))
            for si in root.findall(NS + "si"):
                shared.append("".join(t.text or "" for t in si.iter(NS + "t")))
        root = ET.fromstring(z.read("xl/worksheets/sheet1.xml").decode("utf-8"))
        grid = {}
        for row in root.iter(NS + "row"):
            r = int(row.get("r"))
            grid[r] = {}
            for c in row.findall(NS + "c"):
                ref = c.get("r")
                if ref is None:
                    continue
                row_no, col = col_index(ref)
                t = c.get("t")
                val = None
                v = c.find(NS + "v")
                if v is not None and v.text is not None:
                    val = v.text
                elif t == "inlineStr":
                    isnode = c.find(NS + "is")
                    if isnode is not None:
                        val = "".join(x.text or "" for x in isnode.iter(NS + "t"))
                if val is not None and t == "s":
                    val = shared[int(val)]
                grid[row_no][col] = val
    return grid


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def load_config():
    """读取 Excel，返回本金与股票配置。"""
    grid = read_xlsx(paths.find_xlsx())
    total_principal = num(grid.get(4, {}).get(1))  # B4

    stocks = []
    for row_no in range(9, 15):
        row = grid.get(row_no, {})
        name = row.get(0, "")
        code = row.get(1, "")
        weight = num(row.get(2))
        price = num(row.get(3))
        if not code:
            continue
        stocks.append({
            "name": str(name),
            "code": str(code),
            "weight": weight,
            "price": price,
        })

    # 参考股息率：第 25~30 行，按股票顺序一一对应
    for i, row_no in enumerate(range(25, 31)):
        row = grid.get(row_no, {})
        ref_yield = num(row.get(2))
        if i < len(stocks):
            stocks[i]["ref_yield"] = ref_yield

    return {
        "total_principal": total_principal,
        "stocks": stocks,
        "source_file": paths.find_xlsx().name,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
