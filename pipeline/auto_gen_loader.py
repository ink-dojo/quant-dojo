"""
pipeline/auto_gen_loader.py — auto_gen 策略加载器

读取 strategies/generated/auto_gen_latest.json，将 generate 命令产出的
策略定义转换为 daily_signal / backtest 可用的因子字典与方向。

策略 JSON 结构（由 quant_dojo/commands/generate.py 写入）:
{
  "strategy": {
    "name": "auto_gen",
    "factors": [
      {"name": "low_vol_20d", "direction": -1, "icir": 0.35, "ic_mean": -0.03},
      ...
    ],
    "weighting": "ic_weighted",
    "neutralize": true,
    "n_stocks": 30,
    "generated_at": "2026-04-07T..."
  },
  "backtest_metrics": {...},
  "factor_details": [...]
}
"""
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

GENERATED_DIR = Path(__file__).parent.parent / "strategies" / "generated"
LATEST_FILE = GENERATED_DIR / "auto_gen_latest.json"


def load_auto_gen_definition() -> dict:
    """
    加载最新的 auto_gen 策略定义。

    返回:
        dict: {"factors": [{"name", "direction", ...}], "neutralize": bool, ...}

    抛出:
        FileNotFoundError: 若 auto_gen_latest.json 不存在
        ValueError: 若文件格式不正确
    """
    if not LATEST_FILE.exists():
        raise FileNotFoundError(
            f"未找到 auto_gen 策略定义: {LATEST_FILE}\n"
            "请先运行 idea-to-strategy 流水线生成策略定义：\n"
            "  python -m pipeline.cli idea '你的策略想法'\n"
            "或通过 Dashboard 的「策略工坊」面板提交。"
        )

    try:
        with open(LATEST_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        raise ValueError(f"读取 auto_gen 定义失败: {e}")

    strategy = data.get("strategy") or {}
    if not strategy.get("factors"):
        raise ValueError(f"auto_gen 定义无 factors 字段: {LATEST_FILE}")

    return strategy


def compute_auto_gen_factors(
    strategy_def: dict,
    price_wide: pd.DataFrame,
    symbols: list,
    start: str,
    end: str,
) -> dict:
    """
    根据 auto_gen 策略定义计算所有因子宽表。

    参数:
        strategy_def: load_auto_gen_definition() 的返回值
        price_wide: 价格宽表（日期 × 股票）
        symbols: 股票池
        start, end: 数据起止日期

    返回:
        dict: {因子名: (因子宽表, 方向)}，方向 1=正向 -1=反向
    """
    from utils.alpha_factors import build_fast_factors
    from utils.local_data_loader import load_factor_wide, load_price_wide

    # 准备 build_fast_factors 所需的辅助数据
    kwargs = {}
    try:
        high_wide = load_price_wide(symbols, start, end, field="high")
        if not high_wide.empty:
            kwargs["high"] = high_wide
    except Exception:
        pass

    try:
        low_wide = load_price_wide(symbols, start, end, field="low")
        if not low_wide.empty:
            kwargs["low"] = low_wide
    except Exception:
        pass

    try:
        open_wide = load_price_wide(symbols, start, end, field="open")
        if not open_wide.empty:
            kwargs["open_price"] = open_wide
    except Exception:
        pass

    try:
        pe_wide = load_factor_wide(symbols, "pe_ttm", start, end)
        if not pe_wide.empty:
            kwargs["pe"] = pe_wide
    except Exception:
        pass

    try:
        pb_wide = load_factor_wide(symbols, "pb", start, end)
        if not pb_wide.empty:
            kwargs["pb"] = pb_wide
    except Exception:
        pass

    all_factors = build_fast_factors(price_wide, **kwargs)

    # 部分因子在 build_fast_factors 中名为 enhanced_mom，但 v7/v8 用 enhanced_mom_60。
    # 同时注册一个别名，便于 generate 输出复用 v7 命名。
    if "enhanced_mom" in all_factors:
        all_factors.setdefault("enhanced_mom_60", all_factors["enhanced_mom"])

    # 按策略定义的顺序提取因子
    selected = {}
    for entry in strategy_def["factors"]:
        name = entry["name"]
        direction = int(entry.get("direction", 1))

        if name in all_factors:
            selected[name] = (all_factors[name], direction)
        else:
            logger.warning(
                "auto_gen 策略要求的因子 %s 不在 build_fast_factors 输出中，跳过",
                name,
            )

    if not selected:
        raise ValueError("auto_gen 定义中所有因子都无法计算")

    return selected


def get_auto_gen_factor_names() -> list[str]:
    """便捷函数：返回当前 auto_gen 策略使用的因子名列表"""
    try:
        strategy = load_auto_gen_definition()
        return [f["name"] for f in strategy["factors"]]
    except Exception:
        return []
