"""
pipeline/vol_targeting.py — 把组合年化波动率维持在 target_vol (默认 12%).

vol 上升时自动减仓, 防止任一腿在高波动期把整个组合 vol 推到 30%+.

## 核心 API

    compute_vol_scale(nav_series, target_vol=0.12, lookback_days=60) -> VolTargetReport
        单点查询: 返回当前应施加的 gross 缩放系数 + 诊断信息.

    apply_vol_target_to_positions(positions, scale) -> dict
        所有 position 等比例缩放.

    compute_vol_scale_series(nav_series, target_vol=0.12, lookback_days=60) -> pd.Series
        给整段 nav 算每日 scale, 用于回测验证 vol target 的历史效果.

## 与 utils.risk_overlay 的关系

utils.risk_overlay.vol_target_scale 已经实现了序列版的 vol target 缩放
(用于策略 backtest 集成). 本模块在其之上加:
    - 单点 compute_vol_scale + VolTargetReport 数据类: 提供 fallback_reason / asof_date
      等运维诊断字段, 便于 active_strategy 调仓前 log + audit
    - apply_vol_target_to_positions: dict 级别的 position 缩放, 与 active_strategy
      的 target_positions 接口对齐

底层 vol 计算复用 utils.metrics.annualized_volatility 与 utils.risk_overlay.vol_target_scale,
不再自己实现.

## 设计决策

1. 用 60 日 rolling realized vol 而非 EWMA / GARCH: 简单可解释, 抗噪声.
2. min_scale=0.30 / max_scale=1.50 兜底: 防止全现金 / 过度杠杆.
3. NaN / 数据不足时 fallback scale=1.0: 安全默认, 数据不可信时不主动调整.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from utils.metrics import TRADING_DAYS, annualized_volatility
from utils.risk_overlay import vol_target_scale

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class VolTargetReport:
    """vol target 计算结果, 给 caller 完整 context (方便 log + audit)."""

    scale: float                      # 最终施加的缩放系数 ∈ [min_scale, max_scale]
    realized_vol: Optional[float]     # 当前实现波动率 (年化), None = 数据不足
    target_vol: float                 # 目标波动率 (年化)
    lookback_days_used: int           # 实际用的 lookback (可能比要求的少, 数据不足时)
    fallback_reason: Optional[str]    # 若用了 fallback (scale=1.0), 说明原因
    asof_date: Optional[pd.Timestamp] # nav_series 最新日期


def compute_vol_scale(
    nav_series: pd.Series,
    target_vol: float = 0.12,
    lookback_days: int = 60,
    min_scale: float = 0.30,
    max_scale: float = 1.50,
    min_observations: int = 20,
) -> VolTargetReport:
    """
    根据 nav 历史, 计算当前应施加的 gross 缩放系数.

    Args:
        nav_series: 策略历史 NAV (日频, index = 日期, value = NAV)
        target_vol: 目标年化波动率 (默认 12%)
        lookback_days: 计算实现波动率的窗口 (默认 60 个交易日)
        min_scale: 最小缩放 (防全现金, 默认 0.30)
        max_scale: 最大缩放 (防过度杠杆, 默认 1.50)
        min_observations: 最少观测数, 不够就 fallback 到 1.0

    Returns:
        VolTargetReport, 含 scale + 诊断信息.
    """
    if not isinstance(nav_series, pd.Series):
        raise TypeError(f"nav_series 必须是 pd.Series, 收到 {type(nav_series).__name__}")

    asof = nav_series.index[-1] if len(nav_series) > 0 else None

    nav_clean = nav_series.dropna().astype(float)
    if len(nav_clean) < 2:
        return VolTargetReport(
            scale=1.0,
            realized_vol=None,
            target_vol=target_vol,
            lookback_days_used=0,
            fallback_reason=f"nav_series 长度不足 (得到 {len(nav_clean)}, 需 ≥ 2)",
            asof_date=asof,
        )

    log_returns = np.log(nav_clean / nav_clean.shift(1)).dropna()
    window = log_returns.tail(lookback_days)
    actual_window = len(window)

    if actual_window < min_observations:
        return VolTargetReport(
            scale=1.0,
            realized_vol=None,
            target_vol=target_vol,
            lookback_days_used=actual_window,
            fallback_reason=(
                f"观测数 {actual_window} < min_observations {min_observations}, "
                f"vol 估计不可信, fallback 到 scale=1.0"
            ),
            asof_date=asof,
        )

    realized_vol = annualized_volatility(window)

    if realized_vol < 1e-8:
        return VolTargetReport(
            scale=1.0,
            realized_vol=realized_vol,
            target_vol=target_vol,
            lookback_days_used=actual_window,
            fallback_reason="realized_vol 接近 0 (NAV 全平), fallback 到 scale=1.0",
            asof_date=asof,
        )

    raw_scale = target_vol / realized_vol
    scale = float(np.clip(raw_scale, min_scale, max_scale))

    return VolTargetReport(
        scale=scale,
        realized_vol=realized_vol,
        target_vol=target_vol,
        lookback_days_used=actual_window,
        fallback_reason=None,
        asof_date=asof,
    )


def apply_vol_target_to_positions(
    positions: dict[str, float],
    scale: float,
) -> dict[str, float]:
    """所有 position 等比例缩放. 不修改原 dict."""
    if scale < 0:
        raise ValueError(f"scale 必须 ≥ 0, 收到 {scale}")
    return {ts_code: float(value) * scale for ts_code, value in positions.items()}


def compute_vol_scale_series(
    nav_series: pd.Series,
    target_vol: float = 0.12,
    lookback_days: int = 60,
    min_scale: float = 0.30,
    max_scale: float = 1.50,
    min_observations: int = 20,
) -> pd.Series:
    """
    给整段 nav 算每日 scale, 用于回测验证 vol target 的历史效果.

    Returns:
        pd.Series, index = nav_series.index, values = 每日 scale.
        前 min_observations 日是 1.0 (fallback).
    """
    nav_clean = nav_series.dropna().astype(float)
    if len(nav_clean) < 2:
        return pd.Series(1.0, index=nav_series.index, name="vol_scale", dtype=float)

    returns = nav_clean.pct_change().dropna()
    # vol_target_scale 已 shift(1) 防 look-ahead + fillna(1.0)
    scale = vol_target_scale(
        returns,
        target_vol=target_vol,
        window=lookback_days,
        cap=max_scale,
        floor=min_scale,
    )
    # rolling 内部 min_periods 是 max(20, window // 2), 与本模块的 min_observations 不一致 →
    # 手动遮蔽前 min_observations 日为 1.0, 保证语义一致
    if min_observations > 0:
        first_valid_pos = min_observations  # returns 索引上的位置
        if len(scale) > first_valid_pos:
            scale.iloc[:first_valid_pos] = 1.0

    return scale.reindex(nav_series.index).fillna(1.0).rename("vol_scale")


if __name__ == "__main__":
    print("=== vol_targeting 最小验证 ===\n")

    rng = np.random.default_rng(42)
    n_days = 200
    dates = pd.bdate_range("2024-01-02", periods=n_days)

    # 低波动 8% 年化, 期望 scale → 1.50 (clipped)
    nav_low = pd.Series(
        np.cumprod(1 + rng.normal(0.0003, 0.08 / np.sqrt(TRADING_DAYS), n_days)) * 1e6,
        index=dates,
    )
    r1 = compute_vol_scale(nav_low)
    print(f"低波动 8%:  scale={r1.scale:.3f} | realized={r1.realized_vol:.2%}")
    assert 1.30 <= r1.scale <= 1.50

    # 目标 12% 年化, 期望 scale ≈ 1.0
    nav_target = pd.Series(
        np.cumprod(1 + rng.normal(0.0003, 0.12 / np.sqrt(TRADING_DAYS), n_days)) * 1e6,
        index=dates,
    )
    r2 = compute_vol_scale(nav_target)
    print(f"目标 12%:   scale={r2.scale:.3f} | realized={r2.realized_vol:.2%}")
    assert 0.85 <= r2.scale <= 1.20

    # 极端 50% 年化, 期望 scale clip 到 0.30
    nav_extreme = pd.Series(
        np.cumprod(1 + rng.normal(0.0003, 0.50 / np.sqrt(TRADING_DAYS), n_days)) * 1e6,
        index=dates,
    )
    r3 = compute_vol_scale(nav_extreme)
    print(f"极端 50%:   scale={r3.scale:.3f} | realized={r3.realized_vol:.2%}")
    assert r3.scale == 0.30

    # 序列版本 (回测验证)
    series = compute_vol_scale_series(nav_target)
    print(f"\nseries:    len={len(series)} | min={series.min():.3f} | "
          f"max={series.max():.3f} | mean={series.mean():.3f}")
    assert len(series) == n_days

    print("\n✅ 最小验证通过")
