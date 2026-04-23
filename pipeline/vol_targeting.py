"""
pipeline/vol_targeting.py — Phase 8 Tier 1.1 风控基建

把组合年化波动率维持在 target_vol (默认 12%), vol 上升时自动减仓,
防止 RIAD/DSR#30 等任一腿在高波动期 vol 飙升把整个组合 vol 推到 30%+.

## 核心 API

    compute_vol_scale(nav_series, target_vol=0.12, lookback_days=60) -> float
        根据 nav 历史, 返回当前应施加的 gross 缩放系数.

    apply_vol_target_to_positions(positions, scale) -> dict
        所有 position 等比例缩放 (无论是市值还是权重, 都直接乘 scale).

    compute_vol_scale_series(nav_series, target_vol=0.12, lookback_days=60) -> pd.Series
        给整段 nav 算每日 scale, 用于回测验证 vol target 的历史效果.

## 设计决策

1. 用 **rolling 60d 实现波动率** 而非 EWMA / GARCH:
   - 60d 滞后中等, 抗噪声好
   - 简单可解释, jialong 一眼能 sanity check
   - GARCH 等可在 Tier 4 升级
2. 用 **min_scale=0.30 / max_scale=1.50** 兜底:
   - min 防止全现金 (错过反弹)
   - max 防止过度杠杆 (vol 估计误差导致)
3. **不做 vol forecasting**, 仅用 trailing realized:
   - forecast 引入额外模型风险, ROI 不明
   - 60d trailing 已对短期 spike 有 dampen
4. NaN / 数据不足时 **fallback scale=1.0** (不做缩放):
   - 安全默认: 数据不可信时, 不主动调整
   - 上层 caller 可读 log 看到 fallback 决策
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


TRADING_DAYS_PER_YEAR = 252


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

    使用示例 (active_strategy.py 内):
        report = compute_vol_scale(strategy_nav)
        target_positions = apply_vol_target_to_positions(target_positions, report.scale)
        log.info(f"vol_target: scale={report.scale:.3f}, realized_vol={report.realized_vol:.2%}")
    """
    if not isinstance(nav_series, pd.Series):
        raise TypeError(f"nav_series 必须是 pd.Series, 收到 {type(nav_series).__name__}")

    asof = nav_series.index[-1] if len(nav_series) > 0 else None

    # 计算 log returns (vs simple returns: 加和性更好, 高波动期数值更稳)
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

    # 取最近 lookback_days
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

    # 实现波动率 (年化)
    daily_std = window.std(ddof=1)
    realized_vol = float(daily_std * math.sqrt(TRADING_DAYS_PER_YEAR))

    # vol = 0 (e.g. 全现金 / 数据异常): 不能除零, fallback
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
    """
    所有 position 等比例缩放.

    Args:
        positions: dict[ts_code, value], value 可以是市值 (元) 或权重 (0-1)
        scale: 缩放系数, 来自 compute_vol_scale

    Returns:
        新 dict, 每个 value × scale. 不修改原 dict.
    """
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

    Args:
        见 compute_vol_scale.

    Returns:
        pd.Series, index = nav_series.index, values = 每日 scale.
        前 min_observations 日是 1.0 (fallback).

    用法 (回测验证):
        scales = compute_vol_scale_series(historical_nav)
        adjusted_returns = original_returns * scales.shift(1)  # 用昨日 scale 调今日仓位
    """
    nav_clean = nav_series.dropna().astype(float)
    scales = []
    for i in range(len(nav_clean)):
        sub_nav = nav_clean.iloc[: i + 1]
        report = compute_vol_scale(
            sub_nav,
            target_vol=target_vol,
            lookback_days=lookback_days,
            min_scale=min_scale,
            max_scale=max_scale,
            min_observations=min_observations,
        )
        scales.append(report.scale)
    return pd.Series(scales, index=nav_clean.index, name="vol_scale")


# ══════════════════════════════════════════════════════════════
# 最小验证
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=== vol_targeting 最小验证 ===\n")

    rng = np.random.default_rng(42)
    n_days = 200
    dates = pd.bdate_range("2024-01-02", periods=n_days)

    # ── Test 1: 低波动 NAV (8% 年化), 期望 scale → 1.50 (clipped) ──
    daily_vol_low = 0.08 / math.sqrt(TRADING_DAYS_PER_YEAR)
    returns_low = rng.normal(0.0003, daily_vol_low, n_days)
    nav_low = pd.Series(np.cumprod(1 + returns_low) * 1_000_000, index=dates)

    r1 = compute_vol_scale(nav_low)
    print(f"Test 1 (低波动 8%): scale={r1.scale:.3f} | realized_vol={r1.realized_vol:.2%}")
    assert 1.30 <= r1.scale <= 1.50, f"低波动应被 clip 到 max 附近, 得 {r1.scale}"

    # ── Test 2: 目标波动 NAV (12% 年化), 期望 scale ≈ 1.0 ──
    daily_vol_target = 0.12 / math.sqrt(TRADING_DAYS_PER_YEAR)
    returns_target = rng.normal(0.0003, daily_vol_target, n_days)
    nav_target = pd.Series(np.cumprod(1 + returns_target) * 1_000_000, index=dates)

    r2 = compute_vol_scale(nav_target)
    print(f"Test 2 (目标 12%): scale={r2.scale:.3f} | realized_vol={r2.realized_vol:.2%}")
    assert 0.85 <= r2.scale <= 1.20, f"目标波动应 ≈ 1.0, 得 {r2.scale}"

    # ── Test 3: 高波动 NAV (24% 年化), 期望 scale ≈ 0.5 ──
    daily_vol_high = 0.24 / math.sqrt(TRADING_DAYS_PER_YEAR)
    returns_high = rng.normal(0.0003, daily_vol_high, n_days)
    nav_high = pd.Series(np.cumprod(1 + returns_high) * 1_000_000, index=dates)

    r3 = compute_vol_scale(nav_high)
    print(f"Test 3 (高波动 24%): scale={r3.scale:.3f} | realized_vol={r3.realized_vol:.2%}")
    assert 0.40 <= r3.scale <= 0.65, f"高波动应 ≈ 0.5, 得 {r3.scale}"

    # ── Test 4: 极端波动 NAV (50% 年化), 期望 scale 被 clip 到 min=0.30 ──
    daily_vol_extreme = 0.50 / math.sqrt(TRADING_DAYS_PER_YEAR)
    returns_extreme = rng.normal(0.0003, daily_vol_extreme, n_days)
    nav_extreme = pd.Series(np.cumprod(1 + returns_extreme) * 1_000_000, index=dates)

    r4 = compute_vol_scale(nav_extreme)
    print(f"Test 4 (极端 50%): scale={r4.scale:.3f} | realized_vol={r4.realized_vol:.2%}")
    assert r4.scale == 0.30, f"极端波动应被 clip 到 min=0.30, 得 {r4.scale}"

    # ── Test 5: 数据不足 (15 天), 期望 fallback ──
    nav_short = pd.Series([1.0, 1.01, 0.99, 1.02] * 4, index=dates[:16])
    r5 = compute_vol_scale(nav_short)
    print(f"Test 5 (数据不足): scale={r5.scale:.3f} | reason={r5.fallback_reason}")
    assert r5.scale == 1.0
    assert r5.fallback_reason is not None

    # ── Test 6: apply_vol_target_to_positions ──
    positions = {"600519.SH": 100_000.0, "000001.SZ": 50_000.0}
    adjusted = apply_vol_target_to_positions(positions, scale=0.7)
    print(f"\nTest 6 (apply scale=0.7):")
    for ts, v in adjusted.items():
        print(f"  {ts}: {v:,.2f}")
    assert adjusted["600519.SH"] == 70_000.0
    assert adjusted["000001.SZ"] == 35_000.0

    # ── Test 7: compute_vol_scale_series, 回测用 ──
    series = compute_vol_scale_series(nav_target, lookback_days=60)
    print(f"\nTest 7 (整段 scale series): "
          f"len={len(series)} | min={series.min():.3f} | max={series.max():.3f} | "
          f"mean={series.mean():.3f}")
    assert len(series) == n_days
    assert series.iloc[0] == 1.0  # 第一天必 fallback (1 个观测)
    assert series.iloc[-1] != 1.0 or 0.85 <= series.iloc[-1] <= 1.20  # 末日有意义

    print("\n✅ 全部 7 项最小验证通过")
