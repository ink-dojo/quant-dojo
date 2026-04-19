"""风险层 overlay 工具 — Phase 3.5 gross cap 修复 + Phase 4 风险管理层研究.

### 包含
- `apply_gross_cap` : 事件聚集导致 weight 累加超过目标 gross 时, 按比例缩放
- `rolling_realized_vol` : 60 日滚动年化波动
- `vol_target_scale` : min(cap, target/realized_vol) 仓位缩放
- `regime_filter_scale` : CSI300 < 200d SMA → 低仓位; 否则满仓
- `dynamic_hedge_weight` : CSI300 N 日收益 < 阈值 → short 指数

### 设计原则
- 所有函数 pure pandas, 无 side-effect, 易单测
- scale 序列返回时应 shift(1) 再与持仓相乘, 避免 look-ahead
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def apply_gross_cap(W: pd.DataFrame, cap: float = 1.0) -> pd.DataFrame:
    """按行缩放 weight 矩阵, 使 sum(|W_t|) <= cap.

    事件驱动策略若用 `+=` 累加 UNIT 权重, 在事件聚集期 gross 可能远超
    pre-reg 声明. 本函数按行等比例缩放, 保留相对权重不变.

    Args:
        W: T × N weight 矩阵
        cap: 每行允许的最大 gross (sum(|w|))

    Returns:
        capped W, 同 shape
    """
    gross = W.abs().sum(axis=1)
    scale = (cap / gross.where(gross > cap, cap)).clip(upper=1.0)
    return W.mul(scale, axis=0)


def rolling_realized_vol(ret: pd.Series, window: int = 60) -> pd.Series:
    """滚动年化波动 (ddof=1)."""
    return ret.rolling(window, min_periods=max(20, window // 2)).std(ddof=1) * np.sqrt(TRADING_DAYS)


def vol_target_scale(
    ret: pd.Series,
    target_vol: float = 0.12,
    window: int = 60,
    cap: float = 1.5,
    floor: float = 0.0,
) -> pd.Series:
    """按过去 window 日实现波动, 计算 position scale.

    scale_t = clip(target_vol / realized_vol_{t-1}, floor, cap)

    已 shift(1) 保证无 look-ahead.
    """
    rv = rolling_realized_vol(ret, window=window).shift(1)
    scale = (target_vol / rv).clip(lower=floor, upper=cap)
    return scale.fillna(1.0)


def regime_filter_scale(
    index_close: pd.Series,
    sma_window: int = 200,
    in_scale: float = 1.0,
    out_scale: float = 0.3,
) -> pd.Series:
    """CSI300 SMA regime filter.

    close_{t-1} >= SMA_{t-1} → in_scale
    close_{t-1} <  SMA_{t-1} → out_scale

    已 shift(1) 保证用昨日收盘判断.
    """
    sma = index_close.rolling(sma_window, min_periods=sma_window).mean()
    regime_on = (index_close >= sma).shift(1)
    scale = pd.Series(np.where(regime_on, in_scale, out_scale), index=index_close.index)
    scale = scale.where(regime_on.notna(), 1.0)
    return scale


def dynamic_hedge_weight(
    index_close: pd.Series,
    lookback: int = 20,
    threshold: float = -0.08,
    hedge_ratio: float = 1.0,
) -> pd.Series:
    """动态指数对冲信号 — distress 期才 short.

    若 close_{t-1}.pct_change(lookback) < threshold → -hedge_ratio (short)
    否则 0.

    已 shift(1) 保证无 look-ahead. 返回对冲腿权重 (负数代表做空指数).
    """
    past_ret = index_close.pct_change(lookback).shift(1)
    hedge = pd.Series(np.where(past_ret < threshold, -hedge_ratio, 0.0), index=index_close.index)
    return hedge
