"""
<FactorName> — <一句话描述>

核心假设:
    <描述这个因子想捕捉什么 market anomaly>

数据依赖:
    data/raw/tushare/<source>/...
    data/processed/price_wide_close_...

计算公式:
    1. <step 1>
    2. <step 2>

因子方向:
    正向 = 做多高分, 做空低分 (sign = +1)
    负向 = 做多低分, 做空高分 (sign = -1)
    [选择一个, 在 README 里记录]

样本期:
    最早可得: YYYY-MM-DD (受 data/raw 最早日期约束)

Caveats / 红线:
    - 不能包含未来函数 (T 日因子仅用 T-1 及之前数据)
    - 参数 (window, threshold, quantile) 必须 pre-reg, 不基于 IC 结果调
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]


def compute_factor(start: str, end: str, **kwargs) -> pd.DataFrame:
    """
    Compute factor wide panel.

    Args:
        start: "YYYY-MM-DD" 开始日期
        end:   "YYYY-MM-DD" 结束日期 (inclusive)
        **kwargs: 任何因子特定参数 (window, threshold 等), 必须 pre-reg 默认值

    Returns:
        pd.DataFrame:
            index   = pd.DatetimeIndex (交易日)
            columns = ts_code list (带 .SZ/.SH/.BJ 后缀)
            values  = float, 因子分数 (NaN = 当日该股无因子值)
    """
    raise NotImplementedError("请在具体因子目录的 factor.py 实现这个函数")


if __name__ == "__main__":
    print("=== <FactorName> 最小验证 ===")
    df = compute_factor("2025-01-01", "2025-03-31")
    print(f"shape: {df.shape}")
    print(f"日均有效股: {df.notna().sum(axis=1).mean():.0f}")
    latest = df.iloc[-1].dropna()
    if len(latest):
        print(f"最新一日: {df.index[-1].date()}, 有效股数: {len(latest)}")
        print(f"分位: p10={latest.quantile(0.1):.3f} | p50={latest.quantile(0.5):.3f} | p90={latest.quantile(0.9):.3f}")
        print("Top 5 high:")
        print(latest.nlargest(5).to_string())
        print("Top 5 low:")
        print(latest.nsmallest(5).to_string())
    print("✅ 最小验证通过")
