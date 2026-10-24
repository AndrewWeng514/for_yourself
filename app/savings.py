# -*- coding: utf-8 -*-
"""储蓄计划：目标与纪律（纪律作为 AI 建议的上下文，SQLite 存储）。

资产快照与趋势由 app/store.py 的 asset_snapshots 与 app/trend.py 提供；
本模块只保存长期目标、每月定投额与纪律条款。
"""
import copy

from . import store

KEY = "savings_plan"
PLAN_KEYS = ("target", "monthly_invest", "disciplines")

DEFAULT_PLAN = {
    "target": 1000000,          # 目标净资产 100w
    "monthly_invest": 10500,    # 每月定投合计（含养老金 500）
    "disciplines": [
        "每月发薪后 1–2 天自动扣款，先定投再消费，不手动择时。",
        "长期持有选 A 类；短期/灵活选 C 类。",
        "每年/每半年检查一次，偏离目标配置 >5% 就再平衡。",
        "个股（中信）不追高、不加仓，按减持计划执行。",
        "应急金未稳、负债未清零前，不加大权益比例。",
        "每月固定 1,000 进备用金，应急金始终 ≥ 3.4w。",
    ],
}


def load_plan():
    """读取储蓄计划；只返回当前结构里的三个字段，历史遗留键不再透出。"""
    stored = store.load_json(KEY, None)
    if not isinstance(stored, dict):
        return copy.deepcopy(DEFAULT_PLAN)
    plan = {}
    for key in PLAN_KEYS:
        value = stored.get(key)
        plan[key] = copy.deepcopy(DEFAULT_PLAN[key]) if value is None else value
    return plan


def save_plan(plan):
    store.save_json(KEY, plan)
    return plan